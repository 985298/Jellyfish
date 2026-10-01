"""Status tool: check generation task status."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.agents.tools.base import Tool
from app.core.db import async_session_maker
from app.models.task import GenerationTask

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
