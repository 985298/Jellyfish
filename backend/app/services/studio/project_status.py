"""项目状态汇总 + 资产缺口分析。

设计目标：
- 给 SaaS 控制台（ProjectDetailPage）和 DirectorAgent 共用同一份聚合口径，
  避免前端自己拼多个列表端点导致数字对不上。
- 全部从 DB 聚合，不依赖 Orchestrator 的内存态（``app.agents.api_routes._progress_store``），
  因此 Jellyfish 重启、或项目从未跑过 Agent 时依然返回真实数据。

聚合维度：
1. assets：character / scene / prop / costume 四类，各自 total / ready / pending
   （ready = 该资产名下至少有一行 image 的 file_id 非空）。
2. shots：total / with_detail / with_first_frame / with_video / by_status。
3. tasks：本项目相关 GenerationTask 的 task_kind × status 计数，以及 failed 任务明细。
4. gaps：缺图资产、缺细节镜头、缺首帧镜头、缺视频镜头。
5. next_step：按制作阶段顺序给出唯一的推荐下一步。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio import (
    Chapter,
    Character,
    CharacterImage,
    Costume,
    CostumeImage,
    Prop,
    PropImage,
    Scene,
    SceneImage,
    Shot,
    ShotDetail,
    ShotFrameImage,
)
from app.models.task import GenerationTask
from app.models.task_links import GenerationTaskLink

# entity_type -> (实体模型, 图片模型, 图片外键字段, 中文名)
_ASSET_SPECS: tuple[tuple[str, type, type, str, str], ...] = (
    ("character", Character, CharacterImage, "character_id", "角色"),
    ("scene", Scene, SceneImage, "scene_id", "场景"),
    ("prop", Prop, PropImage, "prop_id", "道具"),
    ("costume", Costume, CostumeImage, "costume_id", "服装"),
)

# 制作阶段顺序；next_step 取第一个"未完成"的阶段。
_STAGE_LABELS: dict[str, str] = {
    "extract_assets": "提取资产（角色/场景/道具入库）",
    "generate_asset_refs": "生成角色/场景参考图",
    "divide_shots": "分镜（Agnes 三段式提示词）",
    "generate_keyframes": "生成关键帧（img2img）",
    "generate_videos": "生成视频",
    "completed": "全部完成",
}

_STAGE_ORDER: tuple[str, ...] = (
    "extract_assets",
    "generate_asset_refs",
    "divide_shots",
    "generate_keyframes",
    "generate_videos",
)


async def _asset_ids_with_image(
    db: AsyncSession,
    image_model: type,
    fk_field: str,
    ids: list[str],
) -> set[str]:
    """返回 ids 中"至少有一行 file_id 非空图片"的子集。

    一次 IN 查询取回，避免逐资产 N+1（资产多的项目上这是主要开销）。
    """
    if not ids:
        return set()
    fk = getattr(image_model, fk_field)
    rows = (
        await db.execute(
            select(fk)
            .where(fk.in_(ids), image_model.file_id.isnot(None))
            .distinct()
        )
    ).scalars().all()
    return {str(x) for x in rows}


async def collect_asset_stats(db: AsyncSession, project_id: str) -> dict[str, Any]:
    """按类型统计资产图片完成度，并返回缺图资产清单。"""
    per_type: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    for entity_type, model, image_model, fk_field, label in _ASSET_SPECS:
        entities = (
            await db.execute(select(model).where(model.project_id == project_id).order_by(model.name))
        ).scalars().all()
        ids = [str(e.id) for e in entities]
        ready_ids = await _asset_ids_with_image(db, image_model, fk_field, ids)
        ready = len(ready_ids)
        per_type.append(
            {
                "entity_type": entity_type,
                "label": label,
                "total": len(ids),
                "ready": ready,
                "pending": len(ids) - ready,
            }
        )
        for entity in entities:
            if str(entity.id) in ready_ids:
                continue
            gaps.append(
                {
                    "kind": "asset_missing_image",
                    "entity_type": entity_type,
                    "entity_id": str(entity.id),
                    "name": entity.name or "",
                    "reason": f"{label}「{entity.name}」尚未生成图片",
                }
            )

    total = sum(x["total"] for x in per_type)
    ready_total = sum(x["ready"] for x in per_type)
    return {
        "by_type": per_type,
        "total": total,
        "ready": ready_total,
        "pending": total - ready_total,
        "has_refs": total > 0 and (total - ready_total) == 0,
        # gaps 只含缺图资产；镜头类缺口由 collect_shot_stats 单独产出。
        "gaps": gaps,
    }


async def collect_shot_stats(db: AsyncSession, project_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """统计镜头完成度，返回 (统计, 缺口清单)。"""
    chapter_ids = (
        await db.execute(select(Chapter.id).where(Chapter.project_id == project_id))
    ).scalars().all()
    chapter_ids = [str(x) for x in chapter_ids]

    if not chapter_ids:
        return (
            {
                "total": 0,
                "with_detail": 0,
                "with_first_frame": 0,
                "with_video": 0,
                "by_status": {},
            },
            [],
        )

    # 必须显式 join chapters 才能按章节序号排序：只 select Shot 时 ORDER BY
    # chapters.index 会引用不在 FROM 里的表，SQLite 直接报 "no such column"。
    shots = (
        await db.execute(
            select(Shot)
            .join(Chapter, Shot.chapter_id == Chapter.id)
            .where(Chapter.project_id == project_id)
            .order_by(Chapter.index, Shot.index)
        )
    ).scalars().all()
    if not shots:
        return (
            {
                "total": 0,
                "with_detail": 0,
                "with_first_frame": 0,
                "with_video": 0,
                "by_status": {},
            },
            [],
        )

    shot_ids = [str(s.id) for s in shots]

    with_detail = {
        str(x)
        for x in (
            await db.execute(select(ShotDetail.id).where(ShotDetail.id.in_(shot_ids)))
        ).scalars().all()
    }
    with_frame = {
        str(x)
        for x in (
            await db.execute(
                select(ShotFrameImage.shot_detail_id).where(
                    ShotFrameImage.shot_detail_id.in_(shot_ids),
                    ShotFrameImage.frame_type == "first",
                    ShotFrameImage.file_id.isnot(None),
                )
            )
        ).scalars().all()
    }

    by_status: dict[str, int] = {}
    for shot in shots:
        key = str(shot.status)
        by_status[key] = by_status.get(key, 0) + 1

    stats = {
        "total": len(shots),
        "with_detail": len(with_detail),
        "with_first_frame": len(with_frame),
        "with_video": sum(1 for s in shots if s.generated_video_file_id),
        "by_status": by_status,
    }

    gaps: list[dict[str, Any]] = []
    for shot in shots:
        sid = str(shot.id)
        title = shot.title or f"#{shot.index}"
        if sid not in with_detail:
            gaps.append(
                {
                    "kind": "shot_missing_detail",
                    "shot_id": sid,
                    "title": title,
                    "reason": f"镜头「{title}」缺少分镜细节",
                }
            )
        if sid not in with_frame:
            gaps.append(
                {
                    "kind": "shot_missing_first_frame",
                    "shot_id": sid,
                    "title": title,
                    "reason": f"镜头「{title}」尚未生成首帧图",
                }
            )
        if not shot.generated_video_file_id:
            gaps.append(
                {
                    "kind": "shot_missing_video",
                    "shot_id": sid,
                    "title": title,
                    "reason": f"镜头「{title}」尚未生成视频",
                }
            )

    return stats, gaps


async def collect_task_stats(
    db: AsyncSession,
    project_id: str,
    *,
    related_ids: set[str],
) -> dict[str, Any]:
    """统计本项目相关任务的 task_kind × status 计数，以及失败任务明细。

    相关性通过 ``GenerationTaskLink.relation_entity_id ∈ related_ids`` 判定：
    related_ids 覆盖本项目的镜头 ID、资产 ID、章节 ID。同一个 ID 字符串理论上可能
    跨实体类型重复，但实践中 ID 由 uuid/前缀生成，碰撞概率可忽略；即使碰撞也只是
    多统计一条，不会漏。
    """
    empty = {"by_kind": {}, "failed": [], "failed_count": 0}
    if not related_ids:
        return empty

    id_list = list(related_ids)
    rows = (
        await db.execute(
            select(
                GenerationTask.task_kind,
                GenerationTask.status,
                func.count(GenerationTask.id),
            )
            .join(GenerationTaskLink, GenerationTaskLink.task_id == GenerationTask.id)
            .where(GenerationTaskLink.relation_entity_id.in_(id_list))
            .group_by(GenerationTask.task_kind, GenerationTask.status)
        )
    ).all()

    by_kind: dict[str, dict[str, int]] = {}
    for task_kind, status, count in rows:
        by_kind.setdefault(str(task_kind), {})[str(status)] = int(count)

    failed_rows = (
        await db.execute(
            select(GenerationTask.id, GenerationTask.task_kind, GenerationTask.error, GenerationTaskLink.relation_type, GenerationTaskLink.relation_entity_id)
            .join(GenerationTaskLink, GenerationTaskLink.task_id == GenerationTask.id)
            .where(
                GenerationTaskLink.relation_entity_id.in_(id_list),
                GenerationTask.status == "failed",
            )
            .order_by(GenerationTask.updated_at.desc())
            .limit(50)
        )
    ).all()

    failed = [
        {
            "task_id": r[0],
            "task_kind": r[1],
            "error": r[2] or "",
            "relation_type": r[3],
            "relation_entity_id": r[4],
        }
        for r in failed_rows
    ]
    failed_count = sum(count for statuses in by_kind.values() for key, count in statuses.items() if key == "failed")
    return {
        "by_kind": by_kind,
        "failed": failed,
        # failed 明细被 limit(50) 截断，所以总数取自 by_kind（不受截断影响）。
        "failed_count": failed_count,
    }


def recommend_next_step(assets: dict[str, Any], shots: dict[str, Any]) -> dict[str, str]:
    """按制作阶段顺序取第一个未完成阶段作为推荐下一步。"""
    stage = "completed"
    if assets["total"] == 0 or assets["pending"] > 0:
        stage = "extract_assets"
    elif not assets.get("has_refs", False):
        stage = "generate_asset_refs"
    elif shots["total"] == 0:
        stage = "divide_shots"
    elif shots.get("with_detail", 0) < shots["total"]:
        stage = "divide_shots"
    elif shots["with_first_frame"] < shots["total"]:
        stage = "generate_keyframes"
    elif shots["with_video"] < shots["total"]:
        stage = "generate_videos"
    return {"stage": stage, "label": _STAGE_LABELS[stage]}


async def _collect_related_ids(db: AsyncSession, project_id: str) -> set[str]:
    """本项目所有实体 ID（章节 + 镜头 + 四类资产），用于任务相关性过滤。"""
    ids: set[str] = set()
    ids.update(
        str(x)
        for x in (
            await db.execute(select(Chapter.id).where(Chapter.project_id == project_id))
        ).scalars().all()
    )
    ids.update(
        str(x)
        for x in (
            await db.execute(select(Shot.id).where(Shot.chapter_id.in_(select(Chapter.id).where(Chapter.project_id == project_id))))
        ).scalars().all()
    )
    for _entity_type, model, _image_model, _fk, _label in _ASSET_SPECS:
        ids.update(
            str(x)
            for x in (await db.execute(select(model.id).where(model.project_id == project_id))).scalars().all()
        )
    return ids


async def get_project_status_summary(db: AsyncSession, project_id: str) -> dict[str, Any]:
    """项目状态汇总：资产 / 镜头 / 任务 三段统计 + 推荐下一步。

    刻意不含逐条缺口明细（那是 ``get_project_asset_gaps`` 的职责）：控制台首屏只需要
    聚合数字，明细量大且会拖慢首屏渲染，需要时再单独拉。
    """
    assets = await collect_asset_stats(db, project_id)
    shots, _shot_gaps = await collect_shot_stats(db, project_id)
    related_ids = await _collect_related_ids(db, project_id)
    tasks = await collect_task_stats(db, project_id, related_ids=related_ids)
    next_step = recommend_next_step(assets, shots)

    return {
        "project_id": project_id,
        # 去掉 gaps：聚合视图不需要逐条明细，避免 payload 随资产数线性膨胀。
        "assets": {k: v for k, v in assets.items() if k != "gaps"},
        "shots": shots,
        "tasks": tasks,
        "next_step": next_step,
    }


async def get_project_asset_gaps(db: AsyncSession, project_id: str) -> dict[str, Any]:
    """资产缺口：缺图资产 + 缺细节/缺首帧/缺视频的镜头。

    前端用它做高亮提示；缺口条目按 kind 分组计数，方便只渲染需要的区块。
    """
    assets = await collect_asset_stats(db, project_id)
    _shot_stats, shot_gaps = await collect_shot_stats(db, project_id)
    items = [
        {
            "kind": "asset_missing_image",
            "entity_type": g["entity_type"],
            "entity_id": g["entity_id"],
            "name": g["name"],
            "shot_id": None,
            "title": None,
            "reason": g["reason"],
        }
        for g in assets.get("gaps", [])
    ]
    items.extend(shot_gaps)

    by_kind: dict[str, int] = {}
    for item in items:
        by_kind[item["kind"]] = by_kind.get(item["kind"], 0) + 1

    return {
        "project_id": project_id,
        "total": len(items),
        "by_kind": by_kind,
        "items": items,
    }
