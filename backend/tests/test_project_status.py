"""P0 智能特性 smoke test：项目状态汇总 / 资产缺口 / retry_task 工具。

用内存 SQLite + 真实 ORM 模型建库，只测聚合与判定逻辑，不碰外部服务。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.studio import (
    Chapter,
    Character,
    CharacterImage,
    Scene,
    Shot,
    ShotDetail,
    ShotFrameImage,
)
from app.models.task import GenerationTask
from app.models.task_links import GenerationTaskLink
from app.services.studio.project_status import (
    collect_asset_stats,
    collect_shot_stats,
    get_project_asset_gaps,
    get_project_status_summary,
    recommend_next_step,
)

PROJECT_ID = "proj-test"


@pytest_asyncio.fixture()
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: __import__("app.core.db", fromlist=["Base"]).Base.metadata.create_all(c))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_project(db: AsyncSession) -> str:
    chapter = Chapter(id="ch-1", project_id=PROJECT_ID, index=1, title="第一章")
    db.add(chapter)
    from app.models.types import ProjectStyle, ProjectVisualStyle
    db.add(Character(id="c-1", project_id=PROJECT_ID, name="小明", description="", style=ProjectStyle.real_people_city, visual_style=ProjectVisualStyle.live_action))
    db.add(Character(id="c-2", project_id=PROJECT_ID, name="小红", description="", style=ProjectStyle.real_people_city, visual_style=ProjectVisualStyle.live_action))
    db.add(Scene(id="s-1", project_id=PROJECT_ID, name="教室", description="", style=ProjectStyle.real_people_city))
    await db.flush()

    shot = Shot(id="sh-1", chapter_id="ch-1", index=1, title="开场", status="pending")
    db.add(shot)
    await db.flush()
    db.add(
        ShotDetail(
            id="sh-1",
            camera_shot="MS",
            angle="EYE_LEVEL",
            movement="STATIC",
            duration=3,
            vfx_type="none",
            mood_tags=[],
            description="一个镜头",
        )
    )
    await db.commit()
    return chapter.id


@pytest.mark.asyncio
async def test_asset_stats_counts_missing_images(db: AsyncSession) -> None:
    await _seed_project(db)
    # 只给 c-1 一张图，c-2 与场景都没有图
    db.add(CharacterImage(id=1, character_id="c-1", quality_level="low", view_angle="front", format="png", file_id="f1"))
    await db.commit()

    stats = await collect_asset_stats(db, PROJECT_ID)
    assert stats["total"] == 3
    assert stats["ready"] == 1
    assert stats["pending"] == 2
    gaps = {g["entity_id"] for g in stats["gaps"]}
    assert gaps == {"c-2", "s-1"}


@pytest.mark.asyncio
async def test_shot_stats_reports_frame_and_video_gaps(db: AsyncSession) -> None:
    await _seed_project(db)
    db.add(
        ShotFrameImage(
            id=1,
            shot_detail_id="sh-1",
            frame_type="first",
            format="png",
            file_id="f2",
        )
    )
    await db.commit()

    stats, gaps = await collect_shot_stats(db, PROJECT_ID)
    assert stats["total"] == 1
    assert stats["with_detail"] == 1
    assert stats["with_first_frame"] == 1
    assert stats["with_video"] == 0
    kinds = {g["kind"] for g in gaps}
    assert kinds == {"shot_missing_video"}


def test_recommend_next_step_walks_pipeline() -> None:
    def assets(total: int, pending: int) -> dict:
        return {"total": total, "pending": pending}

    def shots(total: int, detail: int, frame: int, video: int) -> dict:
        return {
            "total": total,
            "with_detail": detail,
            "with_first_frame": frame,
            "with_video": video,
        }

    assert recommend_next_step(assets(0, 0), shots(0, 0, 0, 0))["stage"] == "build_assets"
    assert recommend_next_step(assets(2, 1), shots(1, 1, 1, 1))["stage"] == "build_assets"
    assert recommend_next_step(assets(2, 0), shots(0, 0, 0, 0))["stage"] == "extract_shots"
    assert recommend_next_step(assets(2, 0), shots(2, 1, 0, 0))["stage"] == "bind_assets"
    assert recommend_next_step(assets(2, 0), shots(2, 2, 1, 0))["stage"] == "generate_frames"
    assert recommend_next_step(assets(2, 0), shots(2, 2, 2, 1))["stage"] == "generate_videos"
    assert recommend_next_step(assets(2, 0), shots(2, 2, 2, 2))["stage"] == "completed"


@pytest.mark.asyncio
async def test_task_stats_groups_by_kind_and_status(db: AsyncSession) -> None:
    await _seed_project(db)
    db.add(
        GenerationTask(
            id="t-failed",
            mode="async_polling",
            task_kind="image_generation",
            status="failed",
            progress=0,
            payload={},
            result=None,
            error="boom",
        )
    )
    db.add(
        GenerationTaskLink(
            task_id="t-failed",
            resource_type="image",
            relation_type="character_image",
            relation_entity_id="c-1",
            status="todo",
        )
    )
    await db.commit()

    summary = await get_project_status_summary(db, PROJECT_ID)
    assert summary["tasks"]["by_kind"]["image_generation"]["failed"] == 1
    assert summary["tasks"]["failed_count"] == 1
    assert summary["tasks"]["failed"][0]["task_id"] == "t-failed"


@pytest.mark.asyncio
async def test_asset_gaps_combines_asset_and_shot_gaps(db: AsyncSession) -> None:
    await _seed_project(db)
    gaps = await get_project_asset_gaps(db, PROJECT_ID)
    # 3 个资产全部缺图；镜头有细节但既无首帧也无视频 → 2 条镜头缺口
    assert gaps["total"] == 5
    assert gaps["by_kind"]["asset_missing_image"] == 3
    assert gaps["by_kind"]["shot_missing_video"] == 1
    assert gaps["by_kind"]["shot_missing_first_frame"] == 1
    assert gaps["by_kind"].get("shot_missing_detail") is None


@pytest.mark.asyncio
async def test_status_summary_omits_gap_details(db: AsyncSession) -> None:
    """聚合视图不带逐条缺口，避免 payload 随资产数线性膨胀。"""
    await _seed_project(db)
    summary = await get_project_status_summary(db, PROJECT_ID)
    assert "gaps" not in summary["assets"]
    assert summary["assets"]["pending"] == 3