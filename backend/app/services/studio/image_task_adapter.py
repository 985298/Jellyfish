"""Image task adapter: wraps direct_image_generate_with_retry with task tracking.

Creates GenerationTask records for audit trail, updates status on success/failure.
This fixes Route B bypassing the task system (#9).
"""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select

from app.agents.tools.direct_api import (
    direct_image_generate_with_retry,
    save_image_to_db,
)
from app.core.db import async_session_maker
from app.models.studio import FileItem
from app.models.task import GenerationTask, GenerationTaskStatus, GenerationDeliveryMode
from app.models.task_links import GenerationTaskLink, GenerationTaskLinkStatus

logger = logging.getLogger(__name__)


async def generate_image_tracked(
    api_key: str,
    base_url: str,
    model_name: str,
    prompt: str,
    size: str,
    negative_prompt: str,
    project_id: str,
    asset_type: str,
    asset_id: str,
    name_prefix: str,
    storage_prefix: str,
) -> dict:
    """Generate image with GenerationTask tracking.

    Returns: {file_id, image_url, task_id, retries, status}
    """
    task_id = str(uuid.uuid4())

    # Create task record
    async with async_session_maker() as db:
        task = GenerationTask(
            id=task_id,
            mode=GenerationDeliveryMode.async_polling,
            task_kind="image_generation",
            status=GenerationTaskStatus.running,
            progress=5,
            payload={
                "prompt": prompt[:200],
                "size": size,
                "asset_type": asset_type,
                "asset_id": asset_id,
            },
            executor_type="direct_api",
        )
        db.add(task)
        await db.flush()

        db.add(GenerationTaskLink(
            task_id=task_id,
            resource_type="task_link",
            relation_type=f"{asset_type}_image_generation",
            relation_entity_id=asset_id,
            status=GenerationTaskLinkStatus.todo,
        ))
        await db.commit()

    try:
        img_url, retries = await direct_image_generate_with_retry(
            api_key, base_url, model_name, prompt,
            size=size, negative_prompt=negative_prompt,
        )

        async with async_session_maker() as db:
            file_id = await save_image_to_db(db, img_url, name_prefix, storage_prefix)

            task = await db.get(GenerationTask, task_id)
            if task:
                task.status = GenerationTaskStatus.succeeded
                task.progress = 100
                task.result = json.dumps({"file_id": file_id, "retries": retries})
                task.executor_task_id = file_id
            await db.commit()

        return {
            "file_id": file_id,
            "image_url": img_url,
            "task_id": task_id,
            "retries": retries,
            "status": "ok",
        }
    except Exception as e:
        logger.warning("Image generation failed (task %s): %s", task_id, str(e)[:200])
        async with async_session_maker() as db:
            task = await db.get(GenerationTask, task_id)
            if task:
                task.status = GenerationTaskStatus.failed
                task.error = str(e)[:500]
            await db.commit()
        return {
            "task_id": task_id,
            "status": "error",
            "error": str(e)[:150],
        }
