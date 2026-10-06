"""Direct API helpers for img2img and first_frame video generation (Route B).

Bypasses Jellyfish's create_image_task_and_link / build_run_args infrastructure
and calls the Agnes API directly with `image: url` parameter format (A/B tested).
Results are written back to DB (files table + shot_frame_images / shots).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import async_session_maker
from app.models.llm import Model, ModelSettings, Provider
from app.models.studio import FileItem, Shot, ShotFrameImage

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent


async def get_image_api_config(db: AsyncSession) -> tuple[str, str, str]:
    """Return (api_key, base_url, model_name) for the default image model."""
    settings = await db.get(ModelSettings, 1)
    model_id = settings.default_image_model_id if settings else None
    if not model_id:
        raise RuntimeError("No default image model configured")
    model = await db.get(Model, model_id)
    if model is None:
        raise RuntimeError("Image model not found: %s" % model_id)
    provider = await db.get(Provider, model.provider_id)
    if provider is None:
        raise RuntimeError("Provider not found for model: %s" % model_id)
    return provider.api_key, provider.base_url, model.name


async def get_video_api_config(db: AsyncSession) -> tuple[str, str, str]:
    """Return (api_key, base_url, model_name) for the default video model."""
    settings = await db.get(ModelSettings, 1)
    model_id = settings.default_video_model_id if settings else None
    if not model_id:
        raise RuntimeError("No default video model configured")
    model = await db.get(Model, model_id)
    if model is None:
        raise RuntimeError("Video model not found: %s" % model_id)
    provider = await db.get(Provider, model.provider_id)
    if provider is None:
        raise RuntimeError("Provider not found for model: %s" % model_id)
    return provider.api_key, provider.base_url, model.name


class _NonRetryableError(Exception):
    """Raised for non-retryable HTTP statuses (e.g. 400 bad request).

    ``_retry_with_backoff`` re-raises this immediately without consuming a
    retry slot, so callers can distinguish "don't bother trying again" from
    transient failures.
    """


async def _retry_with_backoff(func, max_attempts=5, base_delay=2):
    """Retry an async function with exponential backoff.

    ``func`` is an awaitable callable taking no arguments. Retries on any
    ``Exception`` except ``_NonRetryableError`` (raised immediately). Backoff
    schedule: ``base_delay * 2**attempt`` -> 2s, 4s, 8s, 16s for base=2.

    Returns ``(result, attempts)`` where ``attempts`` is the number of
    retries consumed (0 means first-try success).
    """
    for attempt in range(max_attempts):
        try:
            result = await func()
            return result, attempt
        except _NonRetryableError:
            raise
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Retry %d/%d after %ds: %s",
                attempt + 1, max_attempts, delay, str(e)[:100],
            )
            await asyncio.sleep(delay)
    raise RuntimeError("All retries exhausted")


async def _direct_image_generate_core(
    api_key, base_url, model_name, prompt, image_url=None,
    size="1920x1080", negative_prompt=None,
):
    """Core image generation with exponential backoff.

    Returns ``(image_url, retry_count)``. Retries on 429/500/502/503 with
    exponential backoff (2s, 4s, 8s, 16s); raises ``_NonRetryableError``
    immediately on 400 (and other non-2xx non-retryable statuses).
    """
    headers = {"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"}
    payload = {"model": model_name, "prompt": prompt, "n": 1, "size": size}
    if image_url:
        payload["image"] = image_url
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    async with httpx.AsyncClient(timeout=120) as client:
        async def _attempt():
            resp = await client.post(
                base_url + "/images/generations", json=payload, headers=headers,
            )
            if resp.status_code in (429, 500, 502, 503):
                raise RuntimeError(
                    "Retryable status %d: %s" % (resp.status_code, str(resp.text)[:100])
                )
            if not (200 <= resp.status_code < 300):
                raise _NonRetryableError(
                    "Non-retryable status %d: %s"
                    % (resp.status_code, str(resp.text)[:200])
                )
            data = resp.json()
            if "data" in data and len(data["data"]) > 0:
                return data["data"][0].get("url", "")
            raise RuntimeError("No image URL in response: %s" % str(data)[:200])

        return await _retry_with_backoff(_attempt, max_attempts=5, base_delay=2)


async def direct_image_generate(
    api_key, base_url, model_name, prompt, image_url=None,
    size="1920x1080", negative_prompt=None,
):
    """Call image API directly. If ``image_url`` provided, use img2img mode.

    Returns the generated image URL (backward compatible). Use
    :func:`direct_image_generate_with_retry` to also receive the retry count.
    """
    url, _ = await _direct_image_generate_core(
        api_key, base_url, model_name, prompt, image_url, size, negative_prompt,
    )
    return url


async def direct_image_generate_with_retry(
    api_key, base_url, model_name, prompt, image_url=None,
    size="1920x1080", negative_prompt=None,
):
    """Same as :func:`direct_image_generate` but returns ``(image_url, retry_count)``."""
    return await _direct_image_generate_core(
        api_key, base_url, model_name, prompt, image_url, size, negative_prompt,
    )


async def direct_video_generate(api_key, base_url, model_name, prompt, image_url, seconds=12, ratio="16:9", size="720P"):
    """Call video API directly with image (first_frame reference).

    Polls until complete, returns the video content URL. Submission step
    retries on 429/500/502/503 with exponential backoff (2s, 4s, 8s, 16s);
    raises ``_NonRetryableError`` immediately on 400. Polling loop unchanged.
    """
    headers = {"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "prompt": prompt,
        "size": "720P",
        "aspect_ratio": ratio,
        "seconds": str(min(seconds, 12)),
    }
    if image_url:
        payload["image"] = image_url
    async with httpx.AsyncClient(timeout=30) as client:
        async def _submit():
            resp = await client.post(base_url + "/videos", json=payload, headers=headers)
            if resp.status_code in (429, 500, 502, 503):
                raise RuntimeError(
                    "Retryable status %d: %s" % (resp.status_code, str(resp.text)[:100])
                )
            if not (200 <= resp.status_code < 300):
                raise _NonRetryableError(
                    "Non-retryable status %d: %s"
                    % (resp.status_code, str(resp.text)[:200])
                )
            task_id = resp.json().get("id", "")
            if not task_id:
                raise RuntimeError("No task id in submission response")
            return task_id

        task_id, _ = await _retry_with_backoff(_submit, max_attempts=5, base_delay=2)
        for _ in range(60):
            await asyncio.sleep(10)
            resp = await client.get(base_url + "/videos/" + task_id, headers=headers)
            if resp.status_code != 200:
                continue
            data = resp.json()
            status = data.get("status", "")
            if status in ("succeeded", "completed"):
                url = data.get("url", "") or data.get("video_url", "")
                if not url:
                    url = base_url + "/videos/" + task_id + "/content"
                return url
            elif status == "failed":
                raise RuntimeError("Video task failed: %s" % str(data)[:200])
        raise RuntimeError("Video polling timeout for task %s" % task_id)


async def save_image_to_db(db, image_url, name, prefix):
    """Download image, upload to object storage, create FileItem. Returns file_id."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(image_url)
        resp.raise_for_status()
        image_data = resp.content
    file_id = str(uuid.uuid4())
    # 内容派生 storage_key：重试覆盖同 S3 对象，不造孤儿（note 1）
    content_hash = hashlib.sha256(image_data).hexdigest()[:24]
    storage_key = "%s/%s.png" % (prefix, content_hash)
    # upload-then-persist：对象上传成功才写行，无"行存在/对象未上传"窗口（条款 1）
    await storage.upload_file(key=storage_key, data=image_data, content_type="image/png")
    file_item = FileItem(id=file_id, type="image", name=name, thumbnail="", tags="[]", storage_key=storage_key)
    db.add(file_item)
    await db.flush()
    return file_id


async def save_video_to_db(db, video_url, shot_id, api_key):
    """Download video, upload to object storage, create FileItem, update shot. Returns file_id."""
    headers = {"Authorization": "Bearer %s" % api_key}
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.get(video_url, headers=headers)
        resp.raise_for_status()
        video_data = resp.content
    file_id = str(uuid.uuid4())
    # 内容派生 storage_key：重试覆盖同 S3 对象（note 1）
    content_hash = hashlib.sha256(video_data).hexdigest()[:24]
    storage_key = "generated-videos/shots/%s/%s.mp4" % (shot_id, content_hash)
    # upload-then-persist：对象上传成功才写行（条款 1）
    await storage.upload_file(key=storage_key, data=video_data, content_type="video/mp4")
    file_item = FileItem(id=file_id, type="video", name="shot-%s-video" % shot_id, thumbnail="", tags="[]", storage_key=storage_key)
    db.add(file_item)
    shot = await db.get(Shot, shot_id)
    if shot is not None:
        shot.generated_video_file_id = file_id
    await db.flush()
    return file_id


async def get_char_ref_url(db, character_names, project_id):
    """Get first available character reference image URL for given names."""
    from app.models.studio import Character, CharacterImage
    for name in character_names:
        char = (await db.execute(
            select(Character).where(Character.project_id == project_id, Character.name == name).limit(1)
        )).scalars().first()
        if char is None:
            continue
        img = (await db.execute(
            select(CharacterImage.file_id).where(
                CharacterImage.character_id == char.id, CharacterImage.file_id.isnot(None)
            ).limit(1)
        )).first()
        if img:
            file_item = await db.get(FileItem, img[0])
            if file_item and file_item.storage_key:
                try:
                    await storage.get_file_info(key=file_item.storage_key)
                except FileNotFoundError:
                    logger.warning("char ref object missing (corrupted): %s", file_item.storage_key)
                    continue
                return storage.presigned_url(key=file_item.storage_key)
    return None


async def get_keyframe_url(db, shot_id):
    """Get the keyframe (first frame) image URL for a shot."""
    frame = (await db.execute(
        select(ShotFrameImage.file_id).where(
            ShotFrameImage.shot_detail_id == shot_id,
            ShotFrameImage.frame_type == "first",
            ShotFrameImage.file_id.isnot(None),
        ).limit(1)
    )).first()
    if frame:
        file_item = await db.get(FileItem, frame[0])
        if file_item and file_item.storage_key:
            try:
                await storage.get_file_info(key=file_item.storage_key)
            except FileNotFoundError:
                logger.warning("keyframe object missing (corrupted): shot=%s", shot_id)
                return None
            return storage.presigned_url(key=file_item.storage_key)
    return None



async def check_frame_complete(db, shot_id):
    """Check if shot keyframe is fully generated."""
    frame = (await db.execute(
        select(ShotFrameImage.file_id).where(
            ShotFrameImage.shot_detail_id == shot_id,
            ShotFrameImage.frame_type == "first",
            ShotFrameImage.file_id.isnot(None),
        ).limit(1)
    )).first()
    return frame is not None


async def retry_with_backoff(func, *args, max_retries=3, base_delay=10, **kwargs):
    """Compensation queue: retry with exponential backoff."""
    import logging
    logger = logging.getLogger(__name__)
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning("Retry %d/%d after %ds: %s", attempt + 1, max_retries, delay, str(e)[:100])
            await asyncio.sleep(delay)
    raise RuntimeError("All retries exhausted")
