"""H4: FileItem reverse navigation - query which entities use a given file."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import (
    CharacterImage,
    CostumeImage,
    FileItem,
    PropImage,
    SceneImage,
    ShotFrameImage,
)


async def lookup_file_usage(db: AsyncSession, file_id: str) -> list[dict]:
    """Reverse lookup: find all entities that reference a given file_id.
    Returns a list of {entity_type, entity_id, relation} dicts."""
    results = []

    # Character images
    rows = (await db.execute(
        select(CharacterImage.character_id).where(CharacterImage.file_id == file_id)
    )).all()
    for row in rows:
        results.append({"entity_type": "character", "entity_id": row[0], "relation": "character_image"})

    # Scene images
    rows = (await db.execute(
        select(SceneImage.scene_id).where(SceneImage.file_id == file_id)
    )).all()
    for row in rows:
        results.append({"entity_type": "scene", "entity_id": row[0], "relation": "scene_image"})

    # Prop images
    rows = (await db.execute(
        select(PropImage.prop_id).where(PropImage.file_id == file_id)
    )).all()
    for row in rows:
        results.append({"entity_type": "prop", "entity_id": row[0], "relation": "prop_image"})

    # Costume images
    rows = (await db.execute(
        select(CostumeImage.costume_id).where(CostumeImage.file_id == file_id)
    )).all()
    for row in rows:
        results.append({"entity_type": "costume", "entity_id": row[0], "relation": "costume_image"})

    # Shot frame images
    rows = (await db.execute(
        select(ShotFrameImage.shot_detail_id, ShotFrameImage.frame_type).where(
            ShotFrameImage.file_id == file_id
        )
    )).all()
    for row in rows:
        results.append({"entity_type": "shot", "entity_id": row[0], "relation": "frame_%s" % row[1]})

    return results


async def get_file_info_with_usage(db: AsyncSession, file_id: str) -> dict:
    """Get file info + all usages in one call."""
    file_item = await db.get(FileItem, file_id)
    if file_item is None:
        return {"error": "file not found", "file_id": file_id}
    usages = await lookup_file_usage(db, file_id)
    return {
        "file_id": file_id,
        "name": file_item.name,
        "type": file_item.type,
        "storage_key": file_item.storage_key,
        "usage_count": len(usages),
        "usages": usages,
    }
