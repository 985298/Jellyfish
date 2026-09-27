"""Chapter render: call Media Service for TTS + subtitle + FFmpeg merge."""
from __future__ import annotations

import logging
import os
import uuid

import boto3
import httpx
from botocore.client import Config as BotoConfig
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import storage
from app.dependencies import get_db
from app.models.studio import Chapter, FileItem, Shot, ShotDialogLine

router = APIRouter()
logger = logging.getLogger(__name__)

MEDIA_SERVICE_URL = os.environ.get("MEDIA_SERVICE_URL", "http://127.0.0.1:8001")
MEDIA_SERVICE_DIR = os.environ.get("MEDIA_SERVICE_DIR", os.path.abspath(os.path.join(os.getcwd(), "..", "..", "media-service")))


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region_name or "us-east-1",
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _presigned_url(storage_key: str, expires: int = 3600) -> str:
    client = _s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket_name, "Key": storage_key},
        ExpiresIn=expires,
    )


def _resolve_media_path(relative_path: str) -> str:
    """Resolve a path returned by Media Service (relative to its CWD) to an absolute path."""
    if os.path.isabs(relative_path) and os.path.isfile(relative_path):
        return relative_path
    candidate = os.path.join(MEDIA_SERVICE_DIR, relative_path)
    if os.path.isfile(candidate):
        return candidate
    candidate2 = os.path.join(os.getcwd(), relative_path)
    if os.path.isfile(candidate2):
        return candidate2
    return ""


@router.post("/chapters/{chapter_id}/render")
async def render_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Collect ready shots with videos and dialogues, call Media Service for dub."""

    chapter = await db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found")

    stmt = (
        select(Shot, FileItem)
        .join(FileItem, Shot.generated_video_file_id == FileItem.id)
        .where(Shot.chapter_id == chapter_id, Shot.status == "ready")
        .order_by(Shot.index)
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No ready shots with generated videos in this chapter",
        )

    dub_shots = []
    for shot, file_obj in rows:
        dialog_stmt = (
            select(ShotDialogLine)
            .where(ShotDialogLine.shot_detail_id == shot.id)
            .order_by(ShotDialogLine.index)
        )
        lines = (await db.execute(dialog_stmt)).scalars().all()
        dialogue = "\n".join(line.text for line in lines if line.text.strip())

        video_url = _presigned_url(file_obj.storage_key)
        logger.info("render shot %s: dialogue_lines=%d, video_key=%s", shot.id, len(lines), file_obj.storage_key)

        dub_shots.append({"shot_id": shot.id, "video_url": video_url, "dialogue": dialogue})

    logger.info("render chapter %s: %d shots, project=%s", chapter_id, len(dub_shots), chapter.project_id)

    dub_request = {"episode_id": chapter_id, "shots": dub_shots, "output_dir": "./output/" + chapter_id}

    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(MEDIA_SERVICE_URL + "/internal/v1/media/dub", json=dub_request)
            resp.raise_for_status()
            result = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error("media service HTTP error: %s", exc.response.text[:500])
        raise HTTPException(status_code=502, detail="Media service error: " + exc.response.text[:300]) from exc
    except httpx.RequestError as exc:
        logger.error("media service unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Media service unavailable: " + str(exc)[:200]) from exc

    # Try to find and upload the final output
    final_output_raw = result.get("final_output", "")
    final_path = _resolve_media_path(final_output_raw) if final_output_raw else ""

    # If no final concatenated file, try to find individual dubbed videos and concat them
    if not final_path:
        output_dir = os.path.join(MEDIA_SERVICE_DIR, "output", chapter_id)
        dubbed_files = []
        for r in result.get("results", []):
            if r.get("status") == "SUCCEEDED" and r.get("output_path"):
                p = _resolve_media_path(r["output_path"])
                if p and os.path.isfile(p):
                    dubbed_files.append(p)
        if len(dubbed_files) > 1:
            logger.info("concatenating %d dubbed videos", len(dubbed_files))
            final_path = os.path.join(output_dir, "episode_final.mp4")
            try:
                list_path = final_path + ".list"
                with open(list_path, "w", encoding="utf-8") as f:
                    for p in dubbed_files:
                        f.write("file '" + p.replace("\\", "/") + "'\n")
                import asyncio
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", list_path, "-c", "copy", final_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                os.remove(list_path)
                if proc.returncode != 0:
                    logger.error("concat failed: %s", stderr.decode()[-500:])
                    final_path = dubbed_files[0] if dubbed_files else ""
                else:
                    logger.info("concat succeeded: %s", final_path)
            except Exception as exc:
                logger.error("concat error: %s", exc)
                final_path = dubbed_files[0] if dubbed_files else ""
        elif len(dubbed_files) == 1:
            final_path = dubbed_files[0]

    if final_path and os.path.isfile(final_path):
        try:
            with open(final_path, "rb") as f:
                video_bytes = f.read()

            s3_key = "rendered-episodes/" + chapter_id + "/" + uuid.uuid4().hex + ".mp4"
            info = await storage.upload_file(key=s3_key, data=video_bytes, content_type="video/mp4", extra_args={"ACL": "public-read"})

            file_obj = FileItem(id=str(uuid.uuid4()), type="video", name="chapter-" + chapter_id + "-final", thumbnail=info.url, tags=[], storage_key=s3_key)
            db.add(file_obj)
            await db.commit()
            await db.refresh(file_obj)

            result["final_file_id"] = file_obj.id
            result["final_url"] = info.url
            logger.info("render chapter %s: final uploaded, file_id=%s, size=%d", chapter_id, file_obj.id, len(video_bytes))
        except Exception as exc:
            logger.error("render chapter %s: upload failed: %s", chapter_id, exc)
            result["upload_error"] = str(exc)[:200]
    else:
        logger.warning("render chapter %s: no final_output file found", chapter_id)
        result["upload_error"] = "Could not locate final output file"

    return result
