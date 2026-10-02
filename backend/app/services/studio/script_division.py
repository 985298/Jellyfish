"""剧本分镜写库服务：将分镜结果落到 Chapter/Shot/ShotDetail。"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.studio import (
    CameraAngle,
    CameraMovement,
    CameraShotType,
    Chapter,
    Character,
    CharacterImage,
    Scene,
    SceneImage,
    Shot,
    ShotDetail,
    VFXType,
)
from app.schemas.skills.script_processing import ScriptDivisionResult
from app.services.common import entity_not_found, require_entity


def _append_division_rows(
    db_add,
    *,
    chapter_id: str,
    result: ScriptDivisionResult,
) -> None:
    for shot_division in result.shots:
        title = (shot_division.shot_name or "").strip() or f"镜头 {shot_division.index}"
        shot_id = str(uuid.uuid4())
        db_add(
            Shot(
                id=shot_id,
                chapter_id=chapter_id,
                index=shot_division.index,
                title=title,
                script_excerpt=shot_division.script_excerpt,
            )
        )
        db_add(
            ShotDetail(
                id=shot_id,
                description=shot_division.description,
                camera_shot=getattr(shot_division, 'camera_shot', None) and CameraShotType(getattr(shot_division, 'camera_shot', '').lower()) or CameraShotType.ms,
                angle=getattr(shot_division, 'angle', None) and CameraAngle(getattr(shot_division, 'angle', '').lower()) or CameraAngle.eye_level,
                movement=getattr(shot_division, 'movement', None) and CameraMovement(getattr(shot_division, 'movement', '').lower()) or CameraMovement.static,
                follow_atmosphere=True,
                vfx_type=VFXType.none,
                duration=getattr(shot_division, 'duration', 6) or 6,
            )
        )


async def write_division_result_to_chapter(
    db: AsyncSession,
    *,
    chapter_id: str,
    result: ScriptDivisionResult,
) -> None:
    """将分镜结果写入指定章节；若章节已有镜头则拒绝写入。"""
    await require_entity(
        db,
        Chapter,
        chapter_id,
        detail=entity_not_found("Chapter"),
        status_code=400,
    )

    existing = await db.execute(select(Shot.id).where(Shot.chapter_id == chapter_id).limit(1))
    if existing.first() is not None:
        raise HTTPException(
            status_code=400,
            detail="Chapter already has shots; refusing to write (write_strategy=fail)",
        )

    _append_division_rows(db.add, chapter_id=chapter_id, result=result)

    # 触发唯一约束与外键检查，确保在返回前失败。
    await db.flush()


def write_division_result_to_chapter_sync(
    db: Session,
    *,
    chapter_id: str,
    result: ScriptDivisionResult,
) -> None:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=400, detail=entity_not_found("Chapter"))

    existing = db.execute(select(Shot.id).where(Shot.chapter_id == chapter_id).limit(1))
    if existing.first() is not None:
        raise HTTPException(
            status_code=400,
            detail="Chapter already has shots; refusing to write (write_strategy=fail)",
        )

    _append_division_rows(db.add, chapter_id=chapter_id, result=result)
    db.flush()




async def build_asset_list_text(db: AsyncSession, project_id: str) -> str:
    """Query characters and scenes for a project, format as asset list text."""
    lines = []
    img_num = 1

    # Query characters with their reference images
    chars = (await db.execute(
        select(Character).where(Character.project_id == project_id).order_by(Character.created_at)
    )).scalars().all()

    char_parts = []
    for char in chars:
        desc = (char.description or "")[:60]
        # Check if character has a reference image
        img = (await db.execute(
            select(CharacterImage.file_id).where(
                CharacterImage.character_id == char.id,
                CharacterImage.file_id.isnot(None),
            ).limit(1)
        )).first()
        has_img = "has_ref" if img else "no_ref"
        char_parts.append("%s(@图片%d, %s, %s)" % (char.name, img_num, desc, has_img))
        img_num += 1
    if char_parts:
        lines.append("角色：" + "、".join(char_parts))

    # Query scenes
    scenes = (await db.execute(
        select(Scene).where(Scene.project_id == project_id).order_by(Scene.created_at)
    )).scalars().all()

    scene_parts = []
    for scene in scenes:
        desc = (scene.description or "")[:60]
        img = (await db.execute(
            select(SceneImage.file_id).where(
                SceneImage.scene_id == scene.id,
                SceneImage.file_id.isnot(None),
            ).limit(1)
        )).first()
        has_img = "has_ref" if img else "no_ref"
        scene_parts.append("%s(@图片%d, %s, %s)" % (scene.name, img_num, desc, has_img))
        img_num += 1
    if scene_parts:
        lines.append("场景：" + "、".join(scene_parts))

    return "\n".join(lines) if lines else ""


def build_asset_list_text_sync(db, project_id: str) -> str:
    """Sync version of build_asset_list_text."""
    lines = []
    img_num = 1

    chars = db.execute(
        select(Character).where(Character.project_id == project_id).order_by(Character.created_at)
    ).scalars().all()

    char_parts = []
    for char in chars:
        desc = (char.description or "")[:60]
        img = db.execute(
            select(CharacterImage.file_id).where(
                CharacterImage.character_id == char.id,
                CharacterImage.file_id.isnot(None),
            ).limit(1)
        ).first()
        has_img = "has_ref" if img else "no_ref"
        char_parts.append("%s(@图片%d, %s, %s)" % (char.name, img_num, desc, has_img))
        img_num += 1
    if char_parts:
        lines.append("角色：" + "、".join(char_parts))

    scenes = db.execute(
        select(Scene).where(Scene.project_id == project_id).order_by(Scene.created_at)
    ).scalars().all()

    scene_parts = []
    for scene in scenes:
        desc = (scene.description or "")[:60]
        img = db.execute(
            select(SceneImage.file_id).where(
                SceneImage.scene_id == scene.id,
                SceneImage.file_id.isnot(None),
            ).limit(1)
        ).first()
        has_img = "has_ref" if img else "no_ref"
        scene_parts.append("%s(@图片%d, %s, %s)" % (scene.name, img_num, desc, has_img))
        img_num += 1
    if scene_parts:
        lines.append("场景：" + "、".join(scene_parts))

    return "\n".join(lines) if lines else ""
