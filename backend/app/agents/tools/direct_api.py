"""Direct API helpers for img2img and first_frame video generation (Route B).

Bypasses Jellyfish's create_image_task_and_link / build_run_args infrastructure
and calls the Agnes API directly with `image: url` parameter format (A/B tested).
Results are written back to DB (files table + shot_frame_images / shots).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def direct_image_generate(api_key, base_url, model_name, prompt, image_url=None, size="1920x1080", negative_prompt=None):
    """Call image API directly. If image_url provided, use img2img mode.
    Returns the generated image URL."""
    headers = {"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"}
    payload = {"model": model_name, "prompt": prompt, "n": 1, "size": size}
    if image_url:
        payload["image"] = image_url
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(3):
            resp = await client.post(base_url + "/images/generations", json=payload, headers=headers)
            if resp.status_code == 429:
                await asyncio.sleep(60)
                continue
            resp.raise_for_status()
            data = resp.json()
            if "data" in data and len(data["data"]) > 0:
                return data["data"][0].get("url", "")
            raise RuntimeError("No image URL in response: %s" % str(data)[:200])
    raise RuntimeError("Image generation failed after 3 attempts")


async def direct_video_generate(api_key, base_url, model_name, prompt, image_url, seconds=12, ratio="16:9"):
    """Call video API directly with image (first_frame reference).
    Polls until complete, returns the video content URL."""
    headers = {"Authorization": "Bearer %s" % api_key, "Content-Type": "application/json"}
    payload = {
        "model": model_name,
        "prompt": prompt,
        "image": image_url,
        "seconds": str(min(seconds, 12)),
        "ratio": ratio,
        "size": "720P",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(5):
            resp = await client.post(base_url + "/videos", json=payload, headers=headers)
            if resp.status_code == 429:
                await asyncio.sleep(60)
                continue
            resp.raise_for_status()
            task_id = resp.json().get("id", "")
            if task_id:
                break
        else:
            raise RuntimeError("Video submission failed after 5 attempts")
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
    """Download image, save to local storage, create FileItem. Returns file_id."""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(image_url)
        resp.raise_for_status()
        image_data = resp.content
    file_id = str(uuid.uuid4())
    storage_key = "%s/%s.png" % (prefix, file_id)
    local_dir = BACKEND_DIR / "data" / prefix.replace("/", "_")
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / (file_id + ".png")).write_bytes(image_data)
    file_item = FileItem(id=file_id, type="image", name=name, thumbnail="", tags="[]", storage_key=storage_key)
    db.add(file_item)
    await db.flush()
    return file_id


async def save_video_to_db(db, video_url, shot_id, api_key):
    """Download video, save to local storage, create FileItem, update shot. Returns file_id."""
    headers = {"Authorization": "Bearer %s" % api_key}
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.get(video_url, headers=headers)
        resp.raise_for_status()
        video_data = resp.content
    file_id = str(uuid.uuid4())
    storage_key = "generated-videos/shots/%s/%s.mp4" % (shot_id, file_id)
    local_dir = BACKEND_DIR / "data" / "generated-videos" / "shots" / shot_id
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / (file_id + ".mp4")).write_bytes(video_data)
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
                return file_item.storage_key
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
            return file_item.storage_key
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
