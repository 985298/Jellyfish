"""
文件生命周期管理：删除资产图片链接时级联清理 FileItem 记录与磁盘物理文件。

问题背景：
    删除 character_images/scene_images/prop_images/costume_images 行时，只删了
    图片链接记录，不删 files 表记录，也不删磁盘上的物理文件，导致孤儿文件累积。
    本模块提供级联删除、孤儿清理、项目资产批量清理能力。

磁盘路径约定（与 app.agents.tools.direct_api.save_image_to_db / save_video_to_db 保持一致）：
    - 图片：storage_key = f"{prefix}/{file_id}.png"
            物理路径 = BACKEND_DIR / "data" / prefix.replace("/", "_") / f"{file_id}.png"
            （前缀段用 "_" 拼成扁平目录名）
    - 视频：storage_key = f"generated-videos/shots/{shot_id}/{file_id}.mp4"
            物理路径 = BACKEND_DIR / "data" / "generated-videos" / "shots" / shot_id / f"{file_id}.mp4"
            （保留嵌套目录结构）
    本模块按上述两种约定反推磁盘路径，并用 file_id 模糊查找兜底。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.direct_api import BACKEND_DIR
from app.models.studio import (
    Character,
    CharacterImage,
    Costume,
    CostumeImage,
    FileItem,
    Prop,
    PropImage,
    Scene,
    SceneImage,
    Shot,
    ShotFrameImage,
)

logger = logging.getLogger(__name__)

# (图片表模型, 指向实体表的外键列名, 实体表模型)
# 实体表（Character/Scene/Prop/Costume）均含 project_id 列。
_ASSET_IMAGE_SPECS: tuple[tuple[type, str, type], ...] = (
    (CharacterImage, "character_id", Character),
    (SceneImage, "scene_id", Scene),
    (PropImage, "prop_id", Prop),
    (CostumeImage, "costume_id", Costume),
)


def _resolve_disk_path(file_id: str, storage_key: str | None) -> Path | None:
    """从 storage_key 反推磁盘物理路径，兼容图片(扁平)与视频(嵌套)两种存储约定。

    返回真实存在的磁盘路径；文件不在磁盘上时返回 None（调用方据此决定是否告警）。
    """
    if not storage_key:
        return None
    parts = storage_key.split("/")
    data_dir = BACKEND_DIR / "data"
    if len(parts) < 2:
        # 无目录前缀，直接挂在 data 根下
        candidate = data_dir / storage_key
        return candidate if candidate.exists() else None
    filename = parts[-1]
    # 1) 图片约定：扁平目录（前缀段用 "_" 拼接）
    flat = data_dir / "_".join(parts[:-1]) / filename
    if flat.exists():
        return flat
    # 2) 视频/嵌套约定：storage_key 路径原样挂在 data 下
    nested = data_dir.joinpath(*parts)
    if nested.exists():
        return nested
    # 3) 兜底：按 file_id 在 data 下递归模糊匹配（任意扩展名）
    if data_dir.exists():
        matches = list(data_dir.rglob(f"{file_id}.*"))
        if matches:
            return matches[0]
    return None


async def cascade_delete_file(db: AsyncSession, file_id: str) -> bool:
    """删除一条 FileItem 记录，并清理磁盘上对应的物理文件。

    磁盘文件缺失只记警告、不中断；DB 记录只要存在就删除。

    Returns:
        True 表示 FileItem 记录存在且已删除；False 表示记录不存在。
    """
    file_item = (
        await db.execute(select(FileItem).where(FileItem.id == file_id))
    ).scalars().first()
    if file_item is None:
        logger.warning("cascade_delete_file: FileItem %s 不存在", file_id)
        return False

    disk_path = _resolve_disk_path(file_id, file_item.storage_key)
    if disk_path is not None:
        try:
            disk_path.unlink()
            logger.info("cascade_delete_file: 已删除磁盘文件 %s", disk_path)
        except OSError as exc:
            logger.warning("cascade_delete_file: 删除磁盘文件失败 %s: %s", disk_path, exc)
    else:
        logger.warning(
            "cascade_delete_file: 磁盘文件未找到 file_id=%s storage_key=%s",
            file_id,
            file_item.storage_key,
        )

    await db.execute(delete(FileItem).where(FileItem.id == file_id))
    await db.flush()
    return True


async def delete_image_with_file(db: AsyncSession, image_table: Any, image_id: int) -> bool:
    """删除任意资产图片表（character_images/scene_images/prop_images/costume_images）的一行，
    并级联清理其关联的 FileItem 与磁盘文件。

    Args:
        db: 异步会话。
        image_table: ORM 模型类（CharacterImage/SceneImage/PropImage/CostumeImage）。
        image_id: 图片行的整型主键 id。

    Returns:
        True 表示图片行存在且已删除；False 表示图片行不存在。
    """
    row = (
        await db.execute(select(image_table).where(image_table.id == image_id))
    ).scalars().first()
    if row is None:
        logger.warning(
            "delete_image_with_file: %s id=%s 不存在",
            getattr(image_table, "__name__", image_table),
            image_id,
        )
        return False

    linked_file_id = getattr(row, "file_id", None)
    await db.execute(delete(image_table).where(image_table.id == image_id))
    await db.flush()

    if linked_file_id:
        await cascade_delete_file(db, linked_file_id)
    return True


async def _collect_referenced_file_ids(db: AsyncSession) -> set[str]:
    """收集所有仍被引用的 file_id（资产图片 + 帧图 + 镜头视频）。

    孤儿清理必须把这三种引用都纳入，否则会误删仍在用的帧图/视频文件。
    """
    referenced: set[str] = set()
    for image_model, _fk, _entity in _ASSET_IMAGE_SPECS:
        file_id_col = getattr(image_model, "file_id")
        rows = (
            await db.execute(select(file_id_col).where(file_id_col.is_not(None)))
        ).scalars().all()
        referenced.update(rows)
    # 镜头分镜帧图片
    frame_rows = (
        await db.execute(
            select(ShotFrameImage.file_id).where(ShotFrameImage.file_id.is_not(None))
        )
    ).scalars().all()
    referenced.update(frame_rows)
    # 镜头生成视频
    video_rows = (
        await db.execute(
            select(Shot.generated_video_file_id).where(
                Shot.generated_video_file_id.is_not(None)
            )
        )
    ).scalars().all()
    referenced.update(video_rows)
    return referenced


async def cleanup_orphaned_files(db: AsyncSession) -> dict:
    """清理无任何引用的孤儿 FileItem 记录及其磁盘文件。

    引用来源包括：资产图片表（character/scene/prop/costume images）、
    镜头分镜帧图片（shot_frame_images.file_id）、镜头生成视频（shots.generated_video_file_id）。

    Returns:
        {"deleted_db": int, "deleted_disk": int}
    """
    referenced = await _collect_referenced_file_ids(db)
    all_files = (
        await db.execute(select(FileItem.id, FileItem.storage_key))
    ).all()

    deleted_db = 0
    deleted_disk = 0
    for fid, storage_key in all_files:
        if fid in referenced:
            continue
        disk_path = _resolve_disk_path(fid, storage_key)
        if disk_path is not None:
            try:
                disk_path.unlink()
                deleted_disk += 1
            except OSError as exc:
                logger.warning(
                    "cleanup_orphaned_files: 删除磁盘文件失败 %s: %s", disk_path, exc
                )
        await db.execute(delete(FileItem).where(FileItem.id == fid))
        deleted_db += 1
    await db.flush()
    logger.info(
        "cleanup_orphaned_files: 删除 DB 记录 %s 条，磁盘文件 %s 个",
        deleted_db,
        deleted_disk,
    )
    return {"deleted_db": deleted_db, "deleted_disk": deleted_disk}


async def delete_project_assets(db: AsyncSession, project_id: str) -> dict:
    """删除项目下全部资产图片及其关联 FileItem 与磁盘文件。

    遍历 character/scene/prop/costume 四类资产：先按 project_id 取实体 id 集合，
    再查对应图片行，逐行删除图片行 + 级联删文件。

    Returns:
        {"deleted_images": int, "deleted_files": int}
    """
    deleted_images = 0
    deleted_files = 0
    for image_model, fk_name, entity_model in _ASSET_IMAGE_SPECS:
        entity_ids = (
            await db.execute(
                select(entity_model.id).where(entity_model.project_id == project_id)
            )
        ).scalars().all()
        if not entity_ids:
            continue
        fk_col = getattr(image_model, fk_name)
        img_rows = (
            await db.execute(
                select(image_model.id, image_model.file_id).where(fk_col.in_(entity_ids))
            )
        ).all()
        for img_id, linked_file_id in img_rows:
            await db.execute(delete(image_model).where(image_model.id == img_id))
            deleted_images += 1
            if linked_file_id:
                if await cascade_delete_file(db, linked_file_id):
                    deleted_files += 1
    await db.flush()
    logger.info(
        "delete_project_assets: project=%s 删除图片行 %s 条，文件 %s 个",
        project_id,
        deleted_images,
        deleted_files,
    )
    return {"deleted_images": deleted_images, "deleted_files": deleted_files}


__all__ = [
    "cascade_delete_file",
    "delete_image_with_file",
    "cleanup_orphaned_files",
    "delete_project_assets",
]
