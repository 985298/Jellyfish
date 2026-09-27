"""Timeline routes: return clips for a project."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.studio import TimelineClip

router = APIRouter()


@router.get("/projects/{project_id}")
async def get_project_timeline(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return all timeline clips for a project (currently empty)."""
    stmt = select(TimelineClip).where(TimelineClip.source_id == project_id)
    result = await db.execute(stmt)
    clips = result.scalars().all()
    return [
        {
            "id": c.id,
            "type": c.type,
            "source_id": c.source_id,
            "label": c.label,
            "start": c.start,
            "end": c.end,
            "track": c.track,
        }
        for c in clips
    ]
