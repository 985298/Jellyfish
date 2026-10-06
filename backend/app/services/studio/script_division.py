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
    ShotCharacterLink,
    ShotDetail,
    VFXType,
)
from app.schemas.skills.script_processing import ScriptDivisionResult
from app.services.common import entity_not_found, require_entity



_CAMERA_SHOT_CN_MAP = {
    "大特写": "ecu", "特写": "cu", "中近景": "mcu", "中景": "ms",
    "中远景": "mls", "远景": "ls", "大远景": "els",
    "全景": "ls", "近景": "cu", "半身": "ms", "全身": "ls",
}

_CAMERA_ANGLE_CN_MAP = {
    "平视": "eye_level", "高角度": "high_angle", "低角度": "low_angle",
    "鸟瞰": "bird_eye", "荷兰式": "dutch", "过肩": "over_shoulder",
    "俯视": "high_angle", "俯拍": "high_angle", "仰视": "low_angle", "仰拍": "low_angle",
    "仰角": "low_angle", "俯角": "high_angle",
}

_CAMERA_MOVEMENT_CN_MAP = {
    "静止": "static", "平移": "pan", "倾斜": "tilt", "拉近": "dolly_in",
    "拉远": "dolly_out", "轨道": "track", "摇臂": "crane", "手持": "handheld",
    "稳定器": "steadicam", "推入": "dolly_in", "拉出": "dolly_out",
    "跟随": "track", "跟拍": "track", "下降": "crane", "上升": "crane",
    "变焦": "zoom_in", "缓推": "dolly_in", "缓拉": "dolly_out",
    "环绕": "track", "旋转": "pan",
}


def _normalize_enum(value, mapping, enum_class, default):
    if not value:
        return default
    v = value.strip()
    # Try direct enum match (by value, uppercase)
    try:
        return enum_class(v.upper())
    except ValueError:
        pass
    # Try by name (lowercase)
    try:
        return enum_class[v.lower()]
    except KeyError:
        pass
    # Try Chinese mapping (by name)
    for cn, en in mapping.items():
        if cn in value:
            try:
                return enum_class[en]
            except KeyError:
                pass
    return default


def _append_division_rows(
    db_add,
    *,
    chapter_id: str,
    result: ScriptDivisionResult,
    character_name_to_id: dict[str, str] | None = None,
    scene_name_to_id: dict[str, str] | None = None,
) -> None:
    character_name_to_id = character_name_to_id or {}
    scene_name_to_id = scene_name_to_id or {}
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
        _scene_name = getattr(shot_division, "scene_name", None)
        _scene_id = scene_name_to_id.get(_scene_name) if _scene_name else None
        db_add(
            ShotDetail(
                id=shot_id,
                description=shot_division.description,
                scene_id=_scene_id,
                camera_shot=_normalize_enum(getattr(shot_division, 'camera_shot', None), _CAMERA_SHOT_CN_MAP, CameraShotType, CameraShotType.ms),
                angle=_normalize_enum(getattr(shot_division, 'angle', None), _CAMERA_ANGLE_CN_MAP, CameraAngle, CameraAngle.eye_level),
                movement=_normalize_enum(getattr(shot_division, 'movement', None), _CAMERA_MOVEMENT_CN_MAP, CameraMovement, CameraMovement.static),
                follow_atmosphere=True,
                vfx_type=VFXType.none,
                duration=getattr(shot_division, 'duration', 6) or 6,
            )
        )
        # 绑定角色：character_names → ShotCharacterLink（Hubble P0-prompt-2，清 drift #5）
        for _ci, _cname in enumerate(shot_division.character_names or []):
            _cid = character_name_to_id.get(_cname)
            if _cid:
                db_add(ShotCharacterLink(shot_id=shot_id, character_id=_cid, index=_ci))


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

    # 构建项目内 name→id 映射，传入 _append_division_rows 做角色/场景绑定（Hubble P0-prompt-2）
    _chapter = await db.get(Chapter, chapter_id)
    _pid = str(_chapter.project_id) if _chapter and _chapter.project_id else ""
    _char_map = {c.name: c.id for c in (await db.execute(select(Character).where(Character.project_id == _pid))).scalars().all()} if _pid else {}
    _scene_map = {s.name: s.id for s in (await db.execute(select(Scene).where(Scene.project_id == _pid))).scalars().all()} if _pid else {}
    _append_division_rows(db.add, chapter_id=chapter_id, result=result, character_name_to_id=_char_map, scene_name_to_id=_scene_map)

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

    # 构建项目内 name→id 映射（Hubble P0-prompt-2）
    _pid = str(chapter.project_id) if chapter and chapter.project_id else ""
    _char_map = {c.name: c.id for c in db.execute(select(Character).where(Character.project_id == _pid)).scalars().all()} if _pid else {}
    _scene_map = {s.name: s.id for s in db.execute(select(Scene).where(Scene.project_id == _pid)).scalars().all()} if _pid else {}
    _append_division_rows(db.add, chapter_id=chapter_id, result=result, character_name_to_id=_char_map, scene_name_to_id=_scene_map)
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
        desc = (char.description or "")[:200]
        # Check if character has a reference image
        img = (await db.execute(
            select(CharacterImage.file_id).where(
                CharacterImage.character_id == char.id,
                CharacterImage.file_id.isnot(None),
            ).limit(1)
        )).first()
        if img:
            char_parts.append("%s(@图片%d, %s, has_ref)" % (char.name, img_num, desc))
            img_num += 1
        else:
            char_parts.append("%s(%s, no_ref)" % (char.name, desc))
    if char_parts:
        lines.append("角色（分镜时必须使用以上名称）：" + "、".join(char_parts))

    # Query scenes
    scenes = (await db.execute(
        select(Scene).where(Scene.project_id == project_id).order_by(Scene.created_at)
    )).scalars().all()

    scene_parts = []
    for scene in scenes:
        desc = (scene.description or "")[:200]
        img = (await db.execute(
            select(SceneImage.file_id).where(
                SceneImage.scene_id == scene.id,
                SceneImage.file_id.isnot(None),
            ).limit(1)
        )).first()
        if img:
            scene_parts.append("%s(@图片%d, %s, has_ref)" % (scene.name, img_num, desc))
            img_num += 1
        else:
            scene_parts.append("%s(%s, no_ref)" % (scene.name, desc))
    if scene_parts:
        lines.append("场景（分镜时必须使用以上名称）：" + "、".join(scene_parts))

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
        desc = (char.description or "")[:200]
        img = db.execute(
            select(CharacterImage.file_id).where(
                CharacterImage.character_id == char.id,
                CharacterImage.file_id.isnot(None),
            ).limit(1)
        ).first()
        if img:
            char_parts.append("%s(@图片%d, %s, has_ref)" % (char.name, img_num, desc))
            img_num += 1
        else:
            char_parts.append("%s(%s, no_ref)" % (char.name, desc))
    if char_parts:
        lines.append("角色（分镜时必须使用以上名称）：" + "、".join(char_parts))

    scenes = db.execute(
        select(Scene).where(Scene.project_id == project_id).order_by(Scene.created_at)
    ).scalars().all()

    scene_parts = []
    for scene in scenes:
        desc = (scene.description or "")[:200]
        img = db.execute(
            select(SceneImage.file_id).where(
                SceneImage.scene_id == scene.id,
                SceneImage.file_id.isnot(None),
            ).limit(1)
        ).first()
        if img:
            scene_parts.append("%s(@图片%d, %s, has_ref)" % (scene.name, img_num, desc))
            img_num += 1
        else:
            scene_parts.append("%s(%s, no_ref)" % (scene.name, desc))
    if scene_parts:
        lines.append("场景（分镜时必须使用以上名称）：" + "、".join(scene_parts))

    return "\n".join(lines) if lines else ""
