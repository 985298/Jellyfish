"""Shot tools: extract shots, query shots."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.tools.base import Tool
from app.core.db import async_session_maker
from app.models.studio import (
    Character,
    Chapter,
    Costume,
    Prop,
    Scene,
    Shot,
)
from app.services.script_processing_tasks import (
    AsyncTaskCreateResult,
    create_divide_task,
    spawn_divide_task,
)

if TYPE_CHECKING:
    from app.agents.core import AgentContext


class ExtractShotsInput(BaseModel):
    script_text: str = Field(description="script text to divide into shots")


class ExtractShotsTool(Tool):
    name = "divide_shots"
    description = "Divide chapter script into shots (chapter_id from context)"
    input_model = ExtractShotsInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = ExtractShotsInput(**kwargs)
        async with async_session_maker() as db:
            result = await create_divide_task(
                db,
                chapter_id=ctx.chapter_id,
                script_text=data.script_text,
                write_to_db=True,
            )
            await db.commit()
        spawn_divide_task(result.task_id)
        return {
            "task_id": result.task_id,
            "status": str(result.status),
            "reused": result.reused,
            "chapter_id": ctx.chapter_id,
        }


class QueryShotsInput(BaseModel):
    """No parameters needed — chapter_id comes from AgentContext."""


class QueryShotsTool(Tool):
    name = "query_shots"
    description = "Query shots for the current chapter (chapter_id from context, no parameters needed)"
    input_model = QueryShotsInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        async with async_session_maker() as db:
            shots = (
                await db.execute(
                    select(Shot)
                    .where(Shot.chapter_id == ctx.chapter_id)
                    .options(selectinload(Shot.detail))
                    .order_by(Shot.index)
                )
            ).scalars().all()
            items = []
            for shot in shots:
                item: dict = {
                    "id": shot.id,
                    "index": shot.index,
                    "title": shot.title,
                    "status": str(shot.status),
                    "script_excerpt": shot.script_excerpt,
                    "generated_video_file_id": shot.generated_video_file_id,
                }
                if shot.detail is not None:
                    d = shot.detail
                    item["camera_shot"] = d.camera_shot
                    item["angle"] = d.angle
                    item["movement"] = d.movement
                    item["description"] = d.description
                    item["scene_id"] = d.scene_id
                    item["duration"] = d.duration
                items.append(item)
        return {
            "chapter_id": ctx.chapter_id,
            "count": len(items),
            "items": items,
        }
