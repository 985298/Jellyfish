"""Shot tools: extract shots, bind assets to shots, query shots."""

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
    create_asset_bind_task,
    create_divide_task,
    spawn_asset_bind_task,
    spawn_divide_task,
)

if TYPE_CHECKING:
    from app.agents.core import AgentContext


class ExtractShotsInput(BaseModel):
    script_text: str = Field(description="script text to divide into shots")


class ExtractShotsTool(Tool):
    name = "extract_shots"
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


class BindAssetsInput(BaseModel):
    """No parameters needed — chapter_id and project_id come from AgentContext."""


class BindAssetsTool(Tool):
    name = "bind_assets"
    description = "Bind existing project assets to shots (chapter_id and project_id from context, no parameters needed)"
    input_model = BindAssetsInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        project_id = ctx.project_id
        async with async_session_maker() as db:
            # --- query shots for the chapter (with detail eagerly loaded) ---
            shots = (
                await db.execute(
                    select(Shot)
                    .where(Shot.chapter_id == ctx.chapter_id)
                    .options(selectinload(Shot.detail))
                    .order_by(Shot.index)
                )
            ).scalars().all()
            division = []
            for shot in shots:
                item: dict = {
                    "index": shot.index,
                    "title": shot.title,
                    "script_excerpt": shot.script_excerpt,
                }
                if shot.detail is not None:
                    d = shot.detail
                    item["description"] = d.description
                    item["camera_shot"] = d.camera_shot
                    item["angle"] = d.angle
                    item["movement"] = d.movement
                    if d.scene_id:
                        item["scene_id"] = d.scene_id
                division.append(item)

            # --- query project assets ---
            characters = (
                await db.execute(
                    select(Character).where(Character.project_id == project_id)
                )
            ).scalars().all()
            scenes = (
                await db.execute(
                    select(Scene).where(Scene.project_id == project_id)
                )
            ).scalars().all()
            props = (
                await db.execute(
                    select(Prop).where(Prop.project_id == project_id)
                )
            ).scalars().all()
            costumes = (
                await db.execute(
                    select(Costume).where(Costume.project_id == project_id)
                )
            ).scalars().all()
            asset_list = {
                "characters": [
                    {"name": c.name, "description": c.description} for c in characters
                ],
                "scenes": [
                    {"name": s.name, "description": s.description} for s in scenes
                ],
                "props": [
                    {"name": p.name, "description": p.description} for p in props
                ],
                "costumes": [
                    {"name": c.name, "description": c.description} for c in costumes
                ],
            }

            # --- create bind task ---
            result = await create_asset_bind_task(
                db,
                chapter_id=ctx.chapter_id,
                script_division_json=json.dumps(division, ensure_ascii=False),
                asset_list_json=json.dumps(asset_list, ensure_ascii=False),
            )
            await db.commit()
        spawn_asset_bind_task(result.task_id)
        return {
            "task_id": result.task_id,
            "status": str(result.status),
            "reused": result.reused,
            "chapter_id": ctx.chapter_id,
            "shot_count": len(division),
            "asset_counts": {
                "characters": len(characters),
                "scenes": len(scenes),
                "props": len(props),
                "costumes": len(costumes),
            },
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
