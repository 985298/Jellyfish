from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import FileItem, ShotFrameImage, ShotFrameType
from app.models.studio_asset_images import CharacterImage
from app.models.studio_shots import ShotCharacterLink
from app.services.studio.generation.shared.types import GenerationContext
from app.services.studio.shot_assets_overview import get_shot_assets_overview

REQUIRED_FRAMES_BY_MODE: dict[str, tuple[ShotFrameType, ...]] = {
    "first": (ShotFrameType.first,),
    "last": (ShotFrameType.last,),
    "key": (ShotFrameType.key,),
    "first_last": (ShotFrameType.first, ShotFrameType.last),
    "first_last_key": (ShotFrameType.first, ShotFrameType.last, ShotFrameType.key),
    "text_only": (),
}


def required_image_count(reference_mode: str) -> int:
    return len(REQUIRED_FRAMES_BY_MODE[reference_mode])


def validate_images_count(reference_mode: str, images: list[str]) -> None:
    actual = len(images or [])
    # first 模式支持多图 reference（1-5 张角色图），其余模式严格匹配
    if reference_mode == "first":
        if not (1 <= actual <= 5):
            raise HTTPException(
                status_code=400,
                detail=f"reference_mode=first requires 1-5 images, got {actual}",
            )
        return
    expected = required_image_count(reference_mode)
    if actual != expected:
        raise HTTPException(
            status_code=400,
            detail=f"reference_mode={reference_mode} requires exactly {expected} images, got {actual}",
        )


async def resolve_video_reference_images(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
    images: list[str] | None = None,
) -> list[str]:
    normalized = [str(item).strip() for item in (images or []) if str(item).strip()]
    if normalized:
        validate_images_count(reference_mode, normalized)
        return normalized

    required_frames = REQUIRED_FRAMES_BY_MODE[reference_mode]
    if not required_frames:
        return []

    # 治本：reference_mode=first 传所有关联角色 primary 图（最多5张），按 shot_character_links index 顺序
    # 同角色跨 shot 用同一张 primary → 人物一致；多角色都有 reference → 不会自由生成
    if reference_mode == "first":
        _link_stmt = select(ShotCharacterLink).where(ShotCharacterLink.shot_id == shot_id).order_by(ShotCharacterLink.index)
        _links = (await db.execute(_link_stmt)).scalars().all()
        _fids: list[str] = []
        for _link in _links:
            _ci_stmt = select(CharacterImage).where(CharacterImage.character_id == _link.character_id, CharacterImage.is_primary == True)
            _ci = (await db.execute(_ci_stmt)).scalars().first()
            if _ci and _ci.file_id:
                _fo = await db.get(FileItem, _ci.file_id)
                if _fo and _fo.storage_key and _fo.storage_key.startswith(("https://", "http://")):
                    _fids.append(str(_ci.file_id))
        if _fids:
            return _fids[:5]  # 官方上限 5 张
        # 无角色图时回退到 first frame 场景图

    stmt = select(ShotFrameImage).where(
        ShotFrameImage.shot_detail_id == shot_id,
        ShotFrameImage.frame_type.in_(required_frames),
    )
    rows = (await db.execute(stmt)).scalars().all()
    frame_map = {row.frame_type: row for row in rows}

    missing: list[ShotFrameType] = []
    ordered_images: list[str] = []
    for frame_type in required_frames:
        row = frame_map.get(frame_type)
        if row is None or not row.file_id:
            missing.append(frame_type)
            continue
        ordered_images.append(str(row.file_id))

    if missing:
        missing_name = ",".join(item.value for item in missing)
        raise HTTPException(
            status_code=400,
            detail=f"Required frame image is missing: {missing_name}; please generate it first",
        )
    return ordered_images


class VideoGenerationContext(GenerationContext):
    """视频生成的动态上下文。"""

    kind: str = "video"
    shot_id: str
    reference_mode: str
    images: list[str]
    template_id: str | None = None


async def build_video_context(
    db: AsyncSession,
    *,
    shot_id: str,
    reference_mode: str,
    images: list[str] | None,
    template_id: str | None = None,
) -> VideoGenerationContext:
    resolved_images = await resolve_video_reference_images(
        db,
        shot_id=shot_id,
        reference_mode=reference_mode,
        images=images,
    )
    return VideoGenerationContext(
        shot_id=shot_id,
        reference_mode=reference_mode,
        images=resolved_images,
        template_id=template_id,
    )

