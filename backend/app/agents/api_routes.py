"""Agent system API: async orchestration + SSE progress streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.core import AgentContext
from app.agents.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

_progress_store: dict[str, list[dict[str, Any]]] = {}

# SSE 保活间隔（秒）。多数反向代理的空闲超时在 30-60s，取 15s 留足余量。
_KEEPALIVE_INTERVAL_S = 15.0

# 进程内进度表不落库，长时间运行会无界增长（每次 orchestrate 都留一串事件）。
# 只保留最近若干条已完成的编排：正在跑的（SSE 还没结束）不淘汰，否则前端读到一半流会断。
_MAX_FINISHED_RUNS = 200


def _evict_finished() -> None:
    if len(_progress_store) <= _MAX_FINISHED_RUNS:
        return
    finished = [
        tid
        for tid, events in _progress_store.items()
        if events and events[-1].get("stage") == "done"
    ]
    # 超出额度时从最早的完成项开始丢；字典按插入顺序迭代，即创建顺序。
    for tid in finished[: len(_progress_store) - _MAX_FINISHED_RUNS]:
        _progress_store.pop(tid, None)


class OrchestrateRequest(BaseModel):
    project_id: str
    chapter_id: str | None = None
    goal: str = "制作短剧"


@router.post("/orchestrate")
async def orchestrate(req: OrchestrateRequest) -> dict[str, str]:
    """Create orchestration task, run in background, return task_id."""
    task_id = str(uuid.uuid4())
    _progress_store[task_id] = []
    asyncio.create_task(_run_orchestration(task_id, req))
    return {"task_id": task_id, "status": "pending"}


async def _run_orchestration(task_id: str, req: OrchestrateRequest) -> None:
    """Background orchestration execution."""
    from app.core.db_sync import sync_session_maker
    from app.services.llm.runtime import build_default_text_llm_sync

    with sync_session_maker() as db:
        llm = build_default_text_llm_sync(db, thinking=True)

    ctx = AgentContext(project_id=req.project_id, chapter_id=req.chapter_id)
    orchestrator = Orchestrator(llm)

    def on_progress(event: dict[str, Any]) -> None:
        # 事件可能从 specialist 的 async task 里写入，统一走 task_id 定位存储。
        # 用 setdefault 而不是直接下标：编排已结束、后到的尾事件不应再抛 KeyError。
        _progress_store.setdefault(task_id, []).append(event)

    try:
        await orchestrator.run(req.goal, ctx, on_progress=on_progress)
    except Exception:
        logger.exception("Orchestration failed: task_id=%s project_id=%s", task_id, req.project_id)
        _progress_store.setdefault(task_id, []).append(
            {"stage": "error", "status": "error", "error": "orchestration crashed; see server logs"}
        )
    finally:
        _progress_store.setdefault(task_id, []).append({"stage": "done", "status": "completed"})
        _evict_finished()


@router.get("/orchestrate/{task_id}/stream")
async def orchestrate_stream(task_id: str) -> StreamingResponse:
    """SSE stream for orchestration progress."""
    async def event_generator():
        idx = 0
        last_keepalive = 0.0
        while True:
            events = _progress_store.get(task_id, [])
            while idx < len(events):
                yield f"data: {json.dumps(events[idx], ensure_ascii=False)}\n\n"
                idx += 1
            if events and events[-1].get("stage") == "done":
                break
            # 长时间没有新事件时发 SSE 注释行保活，避免中间代理按空闲超时掐断连接。
            # 阶段可能跑几分钟（图片/视频生成），不保活会让前端看到"流断了"。
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now - last_keepalive >= _KEEPALIVE_INTERVAL_S:
                last_keepalive = now
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
