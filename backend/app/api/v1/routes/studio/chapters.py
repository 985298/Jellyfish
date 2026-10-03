"""Chapter CRUD（从 projects.py 拆分）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.utils import apply_keyword_filter, apply_order, paginate
from app.dependencies import get_db
from app.models.studio import Chapter, Project, Shot
from app.schemas.common import ApiResponse, PaginatedData, created_response, empty_response, paginated_response, success_response
from app.services.common import (
    create_and_refresh,
    delete_if_exists,
    entity_already_exists,
    entity_not_found,
    ensure_not_exists,
    flush_and_refresh,
    get_or_404,
    patch_model,
    require_entity,
)
from app.schemas.studio.projects import ChapterCreate, ChapterRead, ChapterUpdate
from app.services.studio.project_status import collect_asset_stats

router = APIRouter()

CHAPTER_ORDER_FIELDS = {"index", "title", "created_at", "updated_at", "storyboard_count", "status"}


async def _resolve_asset_stage(db: AsyncSession, project_id: str) -> str | None:
    """根据项目资产统计推断 asset_stage：有资产且有参考图视为 done，有资产缺参考图视为 partial，
    无资产视为 not_started。运行/失败/阻塞需任务事件驱动，此处不推断（返回 None 表示未知）。
    """
    if not project_id:
        return None
    assets = await collect_asset_stats(db, project_id)
    if assets["total"] == 0:
        return "not_started"
    if assets.get("has_refs", False):
        return "done"
    return "partial"


async def _chapter_read_with_extras(db: AsyncSession, chapter: Chapter) -> ChapterRead:
    """构造 ChapterRead，回填 shot_count 与 asset_stage。"""
    count_stmt = select(func.count(Shot.id)).where(Shot.chapter_id == chapter.id)
    shot_count = int((await db.execute(count_stmt)).scalar() or 0)
    asset_stage = await _resolve_asset_stage(db, str(chapter.project_id))
    return ChapterRead.model_validate(chapter).model_copy(
        update={"shot_count": shot_count, "asset_stage": asset_stage}
    )



@router.get(
    "",
    response_model=ApiResponse[PaginatedData[ChapterRead]],
    summary="章节列表（分页）",
)
async def list_chapters(
    db: AsyncSession = Depends(get_db),
    project_id: str | None = Query(None, description="按项目过滤"),
    q: str | None = Query(None, description="关键字，过滤 title/summary"),
    order: str | None = Query(None, description="排序字段"),
    is_desc: bool = Query(False, description="是否倒序"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[ChapterRead]]:
    stmt = select(Chapter)
    if project_id:
        stmt = stmt.where(Chapter.project_id == project_id)
    stmt = apply_keyword_filter(stmt, q=q, fields=[Chapter.title, Chapter.summary])
    stmt = apply_order(
        stmt,
        model=Chapter,
        order=order,
        is_desc=is_desc,
        allow_fields=CHAPTER_ORDER_FIELDS,
        default="index",
    )
    items, total = await paginate(db, stmt=stmt, page=page, page_size=page_size)

    chapter_ids = [c.id for c in items]
    shot_count_by_chapter: dict[str, int] = {}
    if chapter_ids:
        count_stmt = (
            select(Shot.chapter_id, func.count(Shot.id))
            .where(Shot.chapter_id.in_(chapter_ids))
            .group_by(Shot.chapter_id)
        )
        res = await db.execute(count_stmt)
        shot_count_by_chapter = {str(ch_id): int(cnt) for ch_id, cnt in res.all()}

    # asset_stage 按项目推断：同一项目的章节共享同一个 asset_stage 值。
    project_ids = {str(c.project_id) for c in items}
    asset_stage_by_project: dict[str, str | None] = {}
    for pid in project_ids:
        asset_stage_by_project[pid] = await _resolve_asset_stage(db, pid)

    return paginated_response(
        [
            ChapterRead.model_validate(x).model_copy(
                update={
                    "shot_count": shot_count_by_chapter.get(x.id, 0),
                    "asset_stage": asset_stage_by_project.get(str(x.project_id)),
                }
            )
            for x in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "",
    response_model=ApiResponse[ChapterRead],
    status_code=status.HTTP_201_CREATED,
    summary="创建章节",
)
async def create_chapter(
    body: ChapterCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChapterRead]:
    await ensure_not_exists(
        db,
        Chapter,
        body.id,
        detail=entity_already_exists("Chapter"),
    )
    await require_entity(
        db,
        Project,
        body.project_id,
        detail=entity_not_found("Project"),
        status_code=400,
    )
    obj = await create_and_refresh(db, Chapter(**body.model_dump()))
    return created_response(ChapterRead.model_validate(obj))


@router.get(
    "/{chapter_id}",
    response_model=ApiResponse[ChapterRead],
    summary="获取章节",
)
async def get_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChapterRead]:
    obj = await get_or_404(db, Chapter, chapter_id, detail=entity_not_found("Chapter"))
    return success_response(await _chapter_read_with_extras(db, obj))


@router.patch(
    "/{chapter_id}",
    response_model=ApiResponse[ChapterRead],
    summary="更新章节",
)
async def update_chapter(
    chapter_id: str,
    body: ChapterUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChapterRead]:
    obj = await get_or_404(db, Chapter, chapter_id, detail=entity_not_found("Chapter"))
    update = body.model_dump(exclude_unset=True)
    if "project_id" in update:
        await require_entity(
            db,
            Project,
            update["project_id"],
            detail=entity_not_found("Project"),
            status_code=400,
        )
    patch_model(obj, update)
    await flush_and_refresh(db, obj)
    return success_response(ChapterRead.model_validate(obj))


@router.delete(
    "/{chapter_id}",
    response_model=ApiResponse[None],
    summary="删除章节",
)
async def delete_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    await delete_if_exists(db, Chapter, chapter_id)
    return empty_response()
