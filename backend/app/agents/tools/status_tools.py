"""Status tools: check task status, retry failed task."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.agents.tools.base import Tool
from app.core.db import async_session_maker
from app.models.task import GenerationTask, GenerationTaskStatus

if TYPE_CHECKING:
    from app.agents.core import AgentContext


class CheckTaskStatusInput(BaseModel):
    task_id: str = Field(description="generation task id")


class CheckTaskStatusTool(Tool):
    name = "check_task_status"
    description = "Check generation task status by task_id (queries GenerationTask table)"
    input_model = CheckTaskStatusInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = CheckTaskStatusInput(**kwargs)
        async with async_session_maker() as db:
            task = await db.get(GenerationTask, data.task_id)
            if task is None:
                return {"error": "task not found", "task_id": data.task_id}
            return {
                "task_id": task.id,
                "status": str(task.status),
                "progress": task.progress,
                "task_kind": task.task_kind,
                "error": task.error or "",
                "result": task.result,
            }


class RetryTaskInput(BaseModel):
    task_id: str = Field(description="generation task id to retry")
    reason: str | None = Field(default=None, description="optional reason for retry")


class RetryTaskTool(Tool):
    """重试失败的生成任务。

    只允许重试终态的 ``failed`` 任务：把状态重置为 ``pending``、清空 error/result /
    时间戳后重新入队执行。重试次数记在 ``payload["_agent_retry_count"]``，超过
    ``MAX_RETRIES``（2）即拒绝，避免同一失败任务被无限循环重试。
    """

    name = "retry_task"
    description = "Retry a failed generation task (max 2 retries). Only failed tasks are eligible."
    input_model = RetryTaskInput
    MAX_RETRIES = 2

    # GenerationTask 没有 retry_count 列（加列需要迁移），重试次数存在 payload JSON 里。
    _RETRY_KEY = "_agent_retry_count"

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = RetryTaskInput(**kwargs)
        async with async_session_maker() as db:
            task = await db.get(GenerationTask, data.task_id)
            if task is None:
                return {"error": "task not found", "task_id": data.task_id}
            if str(task.status) != GenerationTaskStatus.failed.value:
                return {
                    "error": f"task is not failed (status={task.status})",
                    "task_id": data.task_id,
                    "status": str(task.status),
                }
            payload = dict(task.payload or {})
            retry_count = int(payload.get(self._RETRY_KEY, 0) or 0) + 1
            if retry_count > self.MAX_RETRIES:
                return {
                    "error": f"max retries ({self.MAX_RETRIES}) exceeded",
                    "task_id": data.task_id,
                    "retry_count": retry_count - 1,
                }
            payload[self._RETRY_KEY] = retry_count
            task.payload = payload
            task.status = GenerationTaskStatus.pending
            task.error = ""
            task.result = None
            task.progress = 0
            task.cancel_requested = False
            task.cancel_requested_at = None
            task.cancel_reason = None
            task.cancelled_at = None
            task.finished_at = None
            await db.commit()

            from app.tasks.execute_task import enqueue_task_execution

            try:
                enqueue_task_execution(data.task_id)
            except Exception as exc:  # noqa: BLE001
                return {
                    "task_id": data.task_id,
                    "retry_count": retry_count,
                    "enqueued": False,
                    "error": f"enqueue failed: {exc}",
                }
            return {
                "task_id": data.task_id,
                "retry_count": retry_count,
                "enqueued": True,
                "reason": data.reason or "",
            }