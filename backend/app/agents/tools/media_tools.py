"""Media tools: frame image generation and video generation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.tools.base import Tool
from app.core.db import async_session_maker
from app.models.studio import Shot, ShotFrameImage
from app.services.studio.image_task_runner import create_image_task_and_link

if TYPE_CHECKING:
    from app.agents.core import AgentContext

logger = logging.getLogger(__name__)


class GenerateFrameInput(BaseModel):
    shot_id: str = Field(description="shot id")
    frame_type: str = Field(default="first", description="first / last / key")
    prompt: str | None = Field(default=None, description="custom prompt (auto-built from shot detail if empty)")


class GenerateFrameTool(Tool):
    name = "generate_frame"
    description = "Generate a shot frame image via create_image_task_and_link (relation_type=shot_frame_image)"
    input_model = GenerateFrameInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = GenerateFrameInput(**kwargs)
        async with async_session_maker() as db:
            # Load shot with detail to build a default prompt
            shot = (
                await db.execute(
                    select(Shot)
                    .where(Shot.id == data.shot_id)
                    .options(selectinload(Shot.detail))
                )
            ).scalars().first()
            if shot is None:
                return {"error": "shot not found", "shot_id": data.shot_id}
            prompt = data.prompt
            if not prompt and shot.detail is not None:
                detail = shot.detail
                prompt = (
                    getattr(detail, "first_frame_prompt", "")
                    or detail.description
                    or shot.title
                )
            if not prompt:
                prompt = shot.title

            # Find or create a ShotFrameImage row; the runner expects its id.
            frame_row = (
                await db.execute(
                    select(ShotFrameImage)
                    .where(
                        ShotFrameImage.shot_detail_id == data.shot_id,
                        ShotFrameImage.frame_type == data.frame_type,
                    )
                    .limit(1)
                )
            ).scalars().first()
            if frame_row is None:
                frame_row = ShotFrameImage(
                    shot_detail_id=data.shot_id,
                    frame_type=data.frame_type,
                    format="png",
                )
                db.add(frame_row)
                await db.flush()
            task_id = await create_image_task_and_link(
                db=db,
                model_id=None,
                relation_type="shot_frame_image",
                relation_entity_id=str(frame_row.id),
                prompt=prompt,
            )
        return {
            "task_id": task_id,
            "shot_id": data.shot_id,
            "frame_type": data.frame_type,
            "prompt": prompt,
        }


class GenerateVideoInput(BaseModel):
    shot_id: str = Field(description="shot id")
    reference_mode: str = Field(default="first_frame", description="reference mode for video generation")
    prompt: str | None = Field(default=None, description="video prompt")
    images: list[str] = Field(default_factory=list, description="reference image file ids")
    ratio: str | None = Field(default=None, description="video aspect ratio")


class GenerateVideoTool(Tool):
    name = "generate_video"
    description = "Create a video generation task for a shot (replicates internal.py video logic)"
    input_model = GenerateVideoInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = GenerateVideoInput(**kwargs)
        async with async_session_maker() as db:
            # Replicate internal.py:450-460 logic — build run_args, create task,
            # add GenerationTaskLink, mark shot generating, commit, enqueue.
            from app.api.v1.routes.film.common import _CreateOnlyTask
            from app.core.task_manager import (
                DeliveryMode,
                SqlAlchemyTaskStore,
                TaskManager,
            )
            from app.models.task_links import GenerationTaskLink
            from app.services.film.generated_video import build_run_args as build_vg_run_args
            from app.services.studio.shot_status import mark_shot_generating
            from app.tasks.execute_task import enqueue_task_execution

            run_args = await build_vg_run_args(
                db,
                shot_id=data.shot_id,
                reference_mode=data.reference_mode,
                prompt=data.prompt,
                images=data.images,
                ratio=data.ratio,
            )
            task_kind = "video_generation"
            resource_type = "video"
            relation_type = "shot_video"

            store = SqlAlchemyTaskStore(db)
            tm = TaskManager(store=store, strategies={})
            task_record = await tm.create(
                task=_CreateOnlyTask(),
                mode=DeliveryMode.async_polling,
                task_kind=task_kind,
                run_args=run_args,
            )
            db.add(
                GenerationTaskLink(
                    task_id=task_record.id,
                    resource_type=resource_type,
                    relation_type=relation_type,
                    relation_entity_id=data.shot_id,
                )
            )
            await mark_shot_generating(db, shot_id=data.shot_id)
            await db.commit()

            try:
                enqueue_task_execution(task_record.id)
            except Exception as e:
                logger.warning(
                    "enqueue_task_execution failed (task=%s): %s",
                    task_record.id,
                    e,
                )
        return {
            "task_id": task_record.id,
            "shot_id": data.shot_id,
            "task_kind": task_kind,
        }
