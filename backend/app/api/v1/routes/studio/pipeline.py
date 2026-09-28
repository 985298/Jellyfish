"""Pipeline orchestration routes for chapter-level auto-processing."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_db
from app.models.studio_shots import Shot, ShotExtractedCandidate, ShotCandidateStatus
from app.models.studio_assets import Character, Scene, Prop, Costume
from app.models.studio_projects import Chapter, ProjectSceneLink, ProjectPropLink, ProjectCostumeLink
from app.models.studio_shots import ShotCharacterLink
from app.schemas.common import ApiResponse, success_response
from app.services.studio.entity_crud import create_entity as _create_entity_crud
from app.services.studio.shot_extracted_candidates import mark_linked_by_name

router = APIRouter()

ENTITY_MAP = {
    "character": (Character, "character"),
    "scene": (Scene, "scene"),
    "prop": (Prop, "prop"),
    "costume": (Costume, "costume"),
}


@router.get("/chapters/{chapter_id}/pipeline-status", response_model=ApiResponse[dict])
async def get_pipeline_status(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """Check completion status of all pipeline stages for a chapter."""
    chapter = (await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )).scalars().first()
    project_id = str(chapter.project_id) if chapter else ""

    shots = (await db.execute(
        select(Shot).where(Shot.chapter_id == chapter_id).order_by(Shot.index)
    )).scalars().all()
    shot_ids = [s.id for s in shots]

    if not shot_ids:
        return success_response({
            "stage_asset_extract": "not_started",
            "stage_divide": "not_started",
            "stage_bind": "not_started",
            "stage_asset_images": "not_started",
            "stage_keyframes": "not_started",
            "stage_videos": "not_started",
            "shots_count": 0,
        })

    cands = (await db.execute(
        select(ShotExtractedCandidate).where(ShotExtractedCandidate.shot_id.in_(shot_ids))
    )).scalars().all()
    pending = [c for c in cands if c.candidate_status == ShotCandidateStatus.pending]
    linked = [c for c in cands if c.candidate_status == ShotCandidateStatus.linked]

    char_count = (await db.execute(
        select(func.count(Character.id)).where(Character.project_id == project_id)
    )).scalar() or 0

    bind_count = (await db.execute(
        select(func.count(ShotCharacterLink.id)).where(ShotCharacterLink.shot_id.in_(shot_ids))
    )).scalar() or 0

    return success_response({
        "stage_asset_extract": "done" if char_count > 0 else "not_started",
        "stage_divide": "done" if shots else "not_started",
        "stage_bind": "done" if bind_count > 0 else ("not_started" if shots else "blocked"),
        "stage_extract": "done" if cands else ("not_started" if shots else "blocked"),
        "stage_confirm": "done" if cands and not pending else ("partial" if linked else "not_started"),
        "pending_count": len(pending),
        "linked_count": len(linked),
        "shots_count": len(shots),
        "candidates_count": len(cands),
        "asset_count": char_count,
        "bind_count": bind_count,
    })


@router.post("/chapters/{chapter_id}/auto-confirm", response_model=ApiResponse[dict])
async def auto_confirm_candidates(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """Auto-confirm all pending candidates: create entities + link to shots."""
    shots = (await db.execute(
        select(Shot).where(Shot.chapter_id == chapter_id)
    )).scalars().all()
    if not shots:
        raise HTTPException(status_code=400, detail="No shots found for chapter")

    # Get project_id from first shot's chapter
    from app.models.studio_projects import Chapter
    chapter = (await db.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )).scalars().first()
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    project_id = chapter.project_id

    created_count = 0
    linked_count = 0
    errors = []

    for shot in shots:
        cands = (await db.execute(
            select(ShotExtractedCandidate)
            .where(ShotExtractedCandidate.shot_id == shot.id)
            .where(ShotExtractedCandidate.candidate_status == ShotCandidateStatus.pending)
        )).scalars().all()

        for cand in cands:
            try:
                entity_type_str = str(cand.candidate_type)
                if entity_type_str not in ENTITY_MAP:
                    errors.append(f"Unknown type: {entity_type_str} for {cand.candidate_name}")
                    continue

                model_cls, api_type = ENTITY_MAP[entity_type_str]

                # Check if entity exists by name in this project
                existing = (await db.execute(
                    select(model_cls)
                    .where(model_cls.name == cand.candidate_name)
                    .where(model_cls.project_id == project_id if hasattr(model_cls, "project_id") else True)
                )).scalars().first()

                if existing:
                    entity_id = existing.id
                else:
                    # Create entity
                    body: dict[str, Any] = {"project_id": project_id, "name": cand.candidate_name}
                    if api_type != "character":
                        import uuid
                        body["id"] = f"{api_type}_{uuid.uuid4().hex[:12]}"
                        body["style"] = "真人都市"
                        body["view_count"] = 1
                    payload = await _create_entity_crud(db, entity_type=api_type, body=body)
                    entity_id = payload.get("id")
                    if not entity_id:
                        errors.append(f"Failed to create {api_type}: {cand.candidate_name}")
                        continue
                    created_count += 1

                # Link candidate to entity
                await mark_linked_by_name(
                    db,
                    shot_id=shot.id,
                    candidate_type=cand.candidate_type,
                    candidate_name=cand.candidate_name,
                    linked_entity_id=str(entity_id),
                )
                linked_count += 1
            except Exception as e:
                errors.append(f"{cand.candidate_type}:{cand.candidate_name} -> {str(e)[:100]}")

    await db.commit()

    return success_response({
        "created": created_count,
        "linked": linked_count,
        "errors": errors[:10],
        "total_errors": len(errors),
    })
