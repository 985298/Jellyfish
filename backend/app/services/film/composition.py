"""Step 6: Film composition - concatenate videos, add BGM, burn subtitles."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.models.studio import Shot, ShotDetail, FileItem

logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
OUTPUT_DIR = BACKEND_DIR / "data" / "composed-films"


async def get_chapter_video_paths(db: AsyncSession, chapter_id: str) -> list[dict]:
    """Get all shot video file paths for a chapter, in order."""
    shots = (await db.execute(
        select(Shot, ShotDetail)
        .join(ShotDetail, ShotDetail.id == Shot.id)
        .where(Shot.chapter_id == chapter_id, Shot.generated_video_file_id.isnot(None))
        .order_by(Shot.index)
    )).all()
    result = []
    for shot, detail in shots:
        file_item = await db.get(FileItem, shot.generated_video_file_id)
        if file_item is None:
            continue
        # Resolve local file path from storage_key
        local_path = BACKEND_DIR / "data" / file_item.storage_key.replace("/", "\\")
        if not local_path.exists():
            # Try with .mp4 extension
            local_path = local_path.with_suffix(".mp4")
        result.append({
            "shot_id": shot.id,
            "index": shot.index,
            "video_path": str(local_path),
            "duration": detail.duration or 8,
            "title": shot.title or "",
            "script_excerpt": shot.script_excerpt or "",
        })
    return result


async def concatenate_videos(video_paths: list[str], output_path: str) -> str:
    """Concatenate videos using ffmpeg concat demuxer."""
    # Create file list
    list_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8")
    for path in video_paths:
        # ffmpeg concat requires escaped single quotes on Windows
        list_file.write("file '%s'\n" % path.replace("'", "\\'"))
    list_file.close()

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file.name,
        "-c", "copy",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    Path(list_file.name).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg concat failed: %s" % stderr.decode("utf-8", errors="replace")[:500])
    logger.info("Concatenated %d videos -> %s", len(video_paths), output_path)
    return output_path


def generate_ass_subtitles(shots: list[dict], output_path: str) -> str:
    """Generate ASS subtitle file from shot dialogue/script excerpts."""
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Microsoft YaHei,48,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,60,60,60,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    current_time = 0.0
    for shot in shots:
        duration = shot.get("duration", 8)
        start = current_time
        end = current_time + duration
        current_time = end

        # Use script_excerpt as subtitle text
        text = (shot.get("script_excerpt") or "").strip()
        if text:
            # Escape ASS special characters
            text = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
            start_str = _format_ass_time(start)
            end_str = _format_ass_time(end)
            lines.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (start_str, end_str, text))

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    logger.info("Generated ASS subtitles: %s (%d entries)", output_path, len(shots))
    return output_path


def _format_ass_time(seconds: float) -> str:
    """Format seconds as ASS time: H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return "%d:%02d:%02d.%02d" % (h, m, s, cs)


async def add_bgm(video_path: str, bgm_path: str, output_path: str, bgm_volume: float = 0.3) -> str:
    """Mix background music into video using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", bgm_path,
        "-filter_complex", "[1:a]volume=%.1f[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]" % bgm_volume,
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg BGM mix failed: %s" % stderr.decode("utf-8", errors="replace")[:500])
    logger.info("Added BGM -> %s", output_path)
    return output_path


async def burn_subtitles(video_path: str, ass_path: str, output_path: str) -> str:
    """Burn ASS subtitles into video using ffmpeg."""
    # Escape path for ffmpeg filter on Windows
    ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", "ass='%s'" % ass_escaped,
        "-c:a", "copy",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg subtitle burn failed: %s" % stderr.decode("utf-8", errors="replace")[:500])
    logger.info("Burned subtitles -> %s", output_path)
    return output_path


async def compose_film(chapter_id: str, bgm_path: str | None = None) -> str:
    """Full composition pipeline: concat -> BGM -> subtitles -> final film."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_session_maker() as db:
        shots = await get_chapter_video_paths(db, chapter_id)

    if not shots:
        raise RuntimeError("No videos found for chapter %s" % chapter_id)

    video_paths = [s["video_path"] for s in shots]
    concat_path = str(OUTPUT_DIR / ("%s_concat.mp4" % chapter_id))
    ass_path = str(OUTPUT_DIR / ("%s_subtitles.ass" % chapter_id))
    final_path = str(OUTPUT_DIR / ("%s_final.mp4" % chapter_id))

    # Step 1: Concatenate
    await concatenate_videos(video_paths, concat_path)

    # Step 2: Generate subtitles
    generate_ass_subtitles(shots, ass_path)

    # Step 3: Burn subtitles
    subbed_path = str(OUTPUT_DIR / ("%s_subbed.mp4" % chapter_id))
    await burn_subtitles(concat_path, ass_path, subbed_path)

    # Step 4: Add BGM (if provided)
    if bgm_path and Path(bgm_path).exists():
        await add_bgm(subbed_path, bgm_path, final_path)
    else:
        # No BGM, just rename subbed to final
        Path(subbed_path).rename(final_path)

    # Cleanup intermediate files
    for p in [concat_path, subbed_path]:
        Path(p).unlink(missing_ok=True)

    logger.info("Film composed: %s (%d shots)", final_path, len(shots))
    return final_path
