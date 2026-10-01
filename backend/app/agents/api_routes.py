"""Agent system API: async orchestration + SSE progress streaming."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.core import AgentContext
from app.agents.orchestrator import Orchestrator

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

_progress_store: dict[str, list[dict[str, Any]]] = {}


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
        _progress_store[task_id].append(event)

    await orchestrator.run(req.goal, ctx, on_progress=on_progress)
    _progress_store[task_id].append({"stage": "done", "status": "completed"})


@router.get("/orchestrate/{task_id}/stream")
async def orchestrate_stream(task_id: str) -> StreamingResponse:
    """SSE stream for orchestration progress."""
    async def event_generator():
        idx = 0
        while True:
            events = _progress_store.get(task_id, [])
            while idx < len(events):
                yield f"data: {json.dumps(events[idx], ensure_ascii=False)}\n\n"
                idx += 1
            if events and events[-1].get("stage") == "done":
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
