"""Media tools: frame image generation and video generation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.tools.base import Tool
from app.core.db import async_session_maker
from app.models.studio import Shot, ShotFrameImage
from app.models.studio_projects import Project
from app.services.studio.image_task_runner import create_image_task_and_link

if TYPE_CHECKING:
    from app.agents.core import AgentContext

logger = logging.getLogger(__name__)


class GenerateFrameInput(BaseModel):
    shot_id: str = Field(description="shot id")
    frame_type: str = Field(default="first", description="first / last / key")
    prompt: str | None = Field(default=None, description="custom prompt (auto-built from shot detail if empty)")

    @field_validator("frame_type", mode="before")
    @classmethod
    def normalize_frame_type(cls, v):
        """Map 'first_frame' -> 'first', 'last_frame' -> 'last', etc."""
        if isinstance(v, str):
            v = v.lower().strip()
            if "first" in v: return "first"
            if "last" in v: return "last"
            if "key" in v: return "key"
        return v


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
    reference_mode: str = Field(default="first", description="reference mode: first / last / key / first_last / first_last_key / text_only")
    prompt: str | None = Field(default=None, description="video prompt")
    images: list[str] = Field(default_factory=list, description="reference image file ids")
    ratio: str | None = Field(default=None, description="video aspect ratio")

    @field_validator("reference_mode", mode="before")
    @classmethod
    def normalize_reference_mode(cls, v):
        """Map 'first_frame' -> 'first', 'last_frame' -> 'last', etc."""
        if isinstance(v, str):
            v = v.lower().strip()
            if v in ("first", "last", "key", "first_last", "first_last_key", "text_only"):
                return v
            if "text" in v: return "text_only"
            if "first" in v and "last" in v and "key" in v: return "first_last_key"
            if "first" in v and "last" in v: return "first_last"
            if "first" in v: return "first"
            if "last" in v: return "last"
            if "key" in v: return "key"
        return v or "first"


class GenerateVideoTool(Tool):
    name = "generate_video"
    description = "Create a video generation task for a shot (replicates internal.py video logic)"
    input_model = GenerateVideoInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = GenerateVideoInput(**kwargs)
        async with async_session_maker() as db:
            # Replicate internal.py:450-460 logic — build run_args, create task,
            # add GenerationTaskLink, mark shot generating, commit, enqueue.
            ratio = data.ratio
            if not ratio:
                project = await db.get(Project, ctx.project_id)
                ratio = getattr(project, 'default_video_ratio', None) or '9:16'
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

            try:
                run_args = await build_vg_run_args(
                    db,
                    shot_id=data.shot_id,
                    reference_mode=data.reference_mode,
                    prompt=data.prompt,
                    images=data.images,
                    ratio=ratio,
                )
            except Exception as exc:
                return {'error': str(exc)[:300], 'shot_id': data.shot_id,
                        'hint': 'Frame images may not be ready yet. Use check_task_status to verify.'}
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
class GenerateVideosBatchInput(BaseModel):
    shot_ids: list[str] = Field(default_factory=list, description="shot ids (auto-queries all chapter shots if empty)")
    reference_mode: str = Field(default="first", description="first / last / key / first_last / first_last_key / text_only")
    @field_validator("reference_mode", mode="before")
    @classmethod
    def normalize_reference_mode(cls, v):
        if isinstance(v, str):
            v = v.lower().strip()
            if v in ("first", "last", "key", "first_last", "first_last_key", "text_only"): return v
            if "text" in v: return "text_only"
            if "first" in v and "last" in v and "key" in v: return "first_last_key"
            if "first" in v and "last" in v: return "first_last"
            if "first" in v: return "first"
            if "last" in v: return "last"
            if "key" in v: return "key"
        return v or "first"
class GenerateVideosBatchTool(Tool):
    name = "generate_videos_batch"
    description = "Submit video generation tasks for ALL shots at once (parallel). Prefer over calling generate_video multiple times."
    input_model = GenerateVideosBatchInput
    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = GenerateVideosBatchInput(**kwargs)
        async with async_session_maker() as db:
            from app.api.v1.routes.film.common import _CreateOnlyTask
            from app.core.task_manager import DeliveryMode, SqlAlchemyTaskStore, TaskManager
            from app.models.task_links import GenerationTaskLink
            from app.models.studio_projects import Project
            from app.services.film.generated_video import build_run_args as build_vg_run_args
            from app.services.studio.shot_status import mark_shot_generating
            from app.tasks.execute_task import enqueue_task_execution
            ratio = getattr(await db.get(Project, ctx.project_id), "default_video_ratio", None) or "9:16"
            shot_ids = data.shot_ids
            if not shot_ids and ctx.chapter_id:
                shot_ids = [str(r) for r in (await db.execute(select(Shot.id).where(Shot.chapter_id == ctx.chapter_id).order_by(Shot.index))).scalars().all()]
            # Pre-fetch all shots' first-frame file_ids for continuity
            frame_map = {}
            if shot_ids:
                for row in (await db.execute(select(ShotFrameImage.shot_detail_id, ShotFrameImage.file_id).where(
                    ShotFrameImage.shot_detail_id.in_(shot_ids),
                    ShotFrameImage.frame_type == "first",
                    ShotFrameImage.file_id.isnot(None),
                ))).all():
                    frame_map[str(row[0])] = str(row[1])
            results = []
            succeeded = 0
            failed = 0
            for i, sid in enumerate(shot_ids):
                try:
                    # Continuity: use first_last mode with next shot's first frame as last frame
                    cur_frame = frame_map.get(sid)
                    next_sid = shot_ids[i + 1] if i + 1 < len(shot_ids) else None
                    next_frame = frame_map.get(next_sid) if next_sid else None
                    if cur_frame and next_frame:
                        images_list = [cur_frame, next_frame]
                        ref_mode = "first_last"
                    else:
                        images_list = []
                        ref_mode = data.reference_mode
                    run_args = await build_vg_run_args(db, shot_id=sid, reference_mode=ref_mode, prompt=None, images=images_list, ratio=ratio)
                    store = SqlAlchemyTaskStore(db)
                    tm = TaskManager(store=store, strategies={})
                    task_record = await tm.create(task=_CreateOnlyTask(), mode=DeliveryMode.async_polling, task_kind="video_generation", run_args=run_args)
                    db.add(GenerationTaskLink(task_id=task_record.id, resource_type="video", relation_type="shot_video", relation_entity_id=sid))
                    await mark_shot_generating(db, shot_id=sid)
                    results.append({"shot_id": sid, "task_id": task_record.id, "status": "submitted"})
                    succeeded += 1
                except Exception as exc:
                    results.append({"shot_id": sid, "error": str(exc)[:200]})
                    failed += 1
            await db.commit()
            for r in results:
                if "task_id" in r:
                    try: enqueue_task_execution(r["task_id"])
                    except Exception as e: logger.warning("enqueue failed: %s", e)
            return {"total": len(shot_ids), "succeeded": succeeded, "failed": failed, "results": results}
