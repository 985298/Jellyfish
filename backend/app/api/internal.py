"""Stub internal API for gateway PoC integration.

Internal endpoints for gateway-Jellyfish integration.
Directly call Jellyfish service layer, avoiding HTTP internal calls.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import uuid4
from app.schemas.common import ApiResponse, success_response
from app.dependencies import get_db
from app.models.studio_projects import Project
from app.models.studio import Character
from app.models.studio import Chapter, Shot, ShotDetail
from app.models.studio import Scene, Prop, Costume, ProjectSceneLink, ProjectPropLink, ProjectCostumeLink
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)

class ProjectCreateInternal(BaseModel):
    project_name: str = Field(..., description="Project name")
    description: str = Field("", description="Project description")
    style: str = Field("真人都市", description="Style/theme")
    visual_style: str = Field("现实", description="Visual style")

class CharacterImportItem(BaseModel):
    """Gateway 批量导入角色中的单条数据。"""
    character_id: str | None = Field(None, description="角色唯一 ID（用于幂等；为空时由 Jellyfish 自动生成）")
    name: str = Field(..., description="角色名称")
    description: str = Field("", description="角色描述")

class CharactersImportInternal(BaseModel):
    """Gateway 批量导入角色请求体。"""
    characters: list[CharacterImportItem] = Field(..., description="角色列表")

@router.post("/v1/projects", response_model=ApiResponse[dict], status_code=status.HTTP_201_CREATED)
async def create_project_internal(
    body: ProjectCreateInternal,
    db: AsyncSession = Depends(get_db)
):
    project_id = f"project_{uuid4().hex[:12]}"
    
    project = Project(
        id=project_id,
        name=body.project_name,
        description=body.description,
        style=body.style,
        visual_style=body.visual_style,
        seed=0,
        unify_style=True,
        progress=0,
        default_video_ratio=None,
        stats={}
    )
    
    db.add(project)
    await db.flush()
    await db.refresh(project)
    
    return success_response(data={
        "project_id": project.id,
        "space_id": project.id,
        "project_name": project.name,
        "status": "created"
    })

@router.get("/v1/health", response_model=ApiResponse[dict])
async def internal_health():
    return success_response(data={"status": "ok"})

@router.get("/v1/projects/{project_id}", response_model=ApiResponse[dict])
async def get_project_internal(
    project_id: str,
    db: AsyncSession = Depends(get_db)
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    
    return success_response(data={
        "project_id": project.id,
        "space_id": project.id,
        "project_name": project.name,
        "description": project.description,
        "style": project.style,
        "visual_style": project.visual_style,
        "status": "active"
    })

@router.post(
    "/v1/projects/{project_id}/characters/import",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_201_CREATED,
)
async def import_characters_internal(
    project_id: str,
    body: CharactersImportInternal,
    db: AsyncSession = Depends(get_db),
):
    """Gateway 调用：批量导入角色（幂等写入）。

    - 项目不存在返回 404。
    - 单条角色数据缺失必填字段返回 422。
    - character_id 已存在则幂等跳过，不重复创建。
    - 继承项目的 style 与 visual_style，不传 actor_id。
    - 不创建分镜、任务、素材图片，仅落角色记录。
    - character_id 缺省时由 Jellyfish 自动生成 char_{uuid4().hex[:12]}，Gateway 透传不落库。
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    created: list[str] = []
    skipped: list[str] = []

    for item in body.characters:
        char_id = item.character_id or f"char_{uuid4().hex[:12]}"
        existing = await db.get(Character, char_id)
        if existing is not None:
            skipped.append(char_id)
            continue
        generated = not item.character_id
        logger.info(
            "batch_import_characters create",
            extra={
                "entity_type": "character",
                "entity_id": char_id,
                "id_source": "backend_generated" if generated else "gateway_upstream",
                "idempotency_key": "character_id",
                "project_id": project_id,
            },
        )

        character = Character(
            id=char_id,
            project_id=project_id,
            name=item.name,
            description=item.description,
            style=project.style,
            visual_style=project.visual_style,
        )
        db.add(character)
        created.append(char_id)

    await db.flush()
    logger.info(
        "batch_import_characters success",
        extra={
            "entity_type": "character",
            "idempotency_key": "character_id",
            "project_id": project_id,
            "created_count": len(created),
            "skipped_count": len(skipped),
            "skipped_ids": skipped,
            "created_ids": created,
            "generated_count": sum(1 for c in created if c.startswith("char_")),
        },
    )

    return success_response(data={
        "project_id": project_id,
        "created": len(created),
        "skipped": len(skipped),
        "skipped_ids": skipped,
        "created_ids": created,
        "generated": sum(1 for c in created if c.startswith("char_")),
        "status": "imported",
    })


class ShotImportItem(BaseModel):
    """分镜导入中的单条镜头数据。"""
    shot_id: str | None = Field(None, description="镜头 ID（可选，为空时由 Jellyfish 自动生成）")
    index: int = Field(..., description="镜头序号（章节内唯一）")
    title: str = Field(..., description="镜头标题")
    script_excerpt: str = Field("", description="剧本摘录")


class ChapterImportItem(BaseModel):
    """分镜导入中的单条章节数据。"""
    chapter_id: str | None = Field(None, description="章节 ID（可选，为空时由 Jellyfish 自动生成）")
    index: int = Field(..., description="章节序号（项目内唯一）")
    title: str = Field(..., description="章节标题")
    summary: str = Field("", description="章节摘要")
    shots: list[ShotImportItem] = Field(default_factory=list, description="镜头列表")


class StoryboardImportInternal(BaseModel):
    """Gateway 批量导入分镜请求体。"""
    chapters: list[ChapterImportItem] = Field(..., description="章节列表")


@router.post(
    "/v1/projects/{project_id}/storyboards/import",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_201_CREATED,
)
async def import_storyboards_internal(
    project_id: str,
    body: StoryboardImportInternal,
    db: AsyncSession = Depends(get_db),
):
    """Gateway 调用：批量导入章节与分镜。

    - 项目不存在返回 404。
    - 缺少必填字段返回 422。
    - chapter_id / shot_id 已存在则幂等跳过，不重复创建。
    - ID 为空时由 Jellyfish 自动生成（chap_ / shot_ 前缀）。
    - 创建 Shot 时自动创建 ShotDetail（默认 MS/EYE_LEVEL/STATIC）。
    - 不创建任务、素材图片，仅落章节、镜头主记录和镜头细节。
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    chapters_created = 0
    chapters_skipped = 0
    shots_created = 0
    shots_skipped = 0
    chapter_created_ids: list[str] = []
    chapter_skipped_ids: list[str] = []
    shot_created_ids: list[str] = []
    shot_skipped_ids: list[str] = []
    chapter_generated_count = 0
    shot_generated_count = 0
    result_chapters: list[dict] = []

    for ch in body.chapters:
        chap_id = ch.chapter_id or f"chap_{uuid4().hex[:12]}"
        existing_ch = await db.get(Chapter, chap_id)
        if existing_ch is not None:
            chapters_skipped += 1
            chapter_skipped_ids.append(chap_id)
            if not ch.chapter_id:
                chapter_generated_count += 1
            shot_results: list[dict] = []
            for sh in ch.shots:
                shot_id = sh.shot_id or f"shot_{uuid4().hex[:12]}"
                existing_shot = await db.get(Shot, shot_id)
                if existing_shot is not None:
                    shots_skipped += 1
                    shot_skipped_ids.append(shot_id)
                    if not sh.shot_id:
                        shot_generated_count += 1
                    shot_results.append({"shot_id": shot_id, "title": sh.title, "status": "skipped"})
                else:
                    shot = Shot(
                        id=shot_id,
                        chapter_id=chap_id,
                        index=sh.index,
                        title=sh.title,
                        script_excerpt=sh.script_excerpt,
                    )
                    db.add(shot)
                    db.add(ShotDetail(
                        id=shot_id,
                        camera_shot="MS",
                        angle="EYE_LEVEL",
                        movement="STATIC",
                    ))
                    shots_created += 1
                    shot_created_ids.append(shot_id)
                    if not sh.shot_id:
                        shot_generated_count += 1
                    shot_results.append({"shot_id": shot_id, "title": sh.title, "status": "created"})
            result_chapters.append({
                "chapter_id": chap_id,
                "title": ch.title,
                "status": "skipped",
                "shots": shot_results,
            })
            continue

        chapter = Chapter(
            id=chap_id,
            project_id=project_id,
            index=ch.index,
            title=ch.title,
            summary=ch.summary,
        )
        db.add(chapter)
        await db.flush()
        chapters_created += 1
        chapter_created_ids.append(chap_id)
        if not ch.chapter_id:
            chapter_generated_count += 1

        shot_results = []
        for sh in ch.shots:
            shot_id = sh.shot_id or f"shot_{uuid4().hex[:12]}"
            existing_shot = await db.get(Shot, shot_id)
            if existing_shot is not None:
                shots_skipped += 1
                shot_skipped_ids.append(shot_id)
                if not sh.shot_id:
                    shot_generated_count += 1
                shot_results.append({"shot_id": shot_id, "title": sh.title, "status": "skipped"})
                continue

            shot = Shot(
                id=shot_id,
                chapter_id=chap_id,
                index=sh.index,
                title=sh.title,
                script_excerpt=sh.script_excerpt,
            )
            db.add(shot)
            db.add(ShotDetail(
                id=shot_id,
                camera_shot="MS",
                angle="EYE_LEVEL",
                movement="STATIC",
            ))
            shot_results.append({"shot_id": shot_id, "title": sh.title, "status": "created"})
            shots_created += 1
            shot_created_ids.append(shot_id)
            if not sh.shot_id:
                shot_generated_count += 1

        await db.flush()
        result_chapters.append({
            "chapter_id": chap_id,
            "title": ch.title,
            "status": "created",
            "shots": shot_results,
        })

    logger.info(
        "batch_import_storyboards success",
        extra={
            "project_id": project_id,
            "entity_type": "storyboard",
            "idempotency_key": "chapter_id/shot_id",
            "chapters_created": chapters_created,
            "chapters_skipped": chapters_skipped,
            "shots_created": shots_created,
            "shots_skipped": shots_skipped,
            "chapter_created_ids": chapter_created_ids,
            "chapter_skipped_ids": chapter_skipped_ids,
            "shot_created_ids": shot_created_ids,
            "shot_skipped_ids": shot_skipped_ids,
            "chapter_generated_count": chapter_generated_count,
            "shot_generated_count": shot_generated_count,
        },
    )

    return success_response(data={
        "project_id": project_id,
        "chapters_created": chapters_created,
        "chapters_skipped": chapters_skipped,
        "shots_created": shots_created,
        "shots_skipped": shots_skipped,
        "chapter_created_ids": chapter_created_ids,
        "chapter_skipped_ids": chapter_skipped_ids,
        "shot_created_ids": shot_created_ids,
        "shot_skipped_ids": shot_skipped_ids,
        "chapters": result_chapters,
        "status": "imported",
    })


class GenerationTaskCreateInternal(BaseModel):
    """Gateway 调用：提交生成任务。"""
    shot_id: str = Field(..., description="镜头 ID")
    task_type: str = Field(..., description="任务类型: shot_frame_prompt | video_generation")
    frame_type: str | None = Field(None, description="帧类型: first | last | key")
    reference_mode: str | None = Field(None, description="参考模式")
    prompt: str | None = Field(None, description="视频提示词")
    images: list[str] = Field(default_factory=list, description="参考图 file_id 列表")
    ratio: str | None = Field(None, description="视频画幅比例")


@router.post(
    "/v1/projects/{project_id}/generation-tasks",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_201_CREATED,
)
async def create_generation_task_internal(
    project_id: str,
    body: GenerationTaskCreateInternal,
    db: AsyncSession = Depends(get_db),
):
    """Gateway 调用：提交生成任务。

    - 项目不存在返回 404。
    - 镜头不存在返回 404。
    - 镜头不属于该项目返回 400。
    - 任务创建后通过 Celery 异步执行；Celery 不可用时仅记录告警。
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    shot = await db.get(Shot, body.shot_id)
    if not shot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shot not found")
    chapter = await db.get(Chapter, shot.chapter_id)
    if not chapter or chapter.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Shot does not belong to this project")

    from app.core.task_manager import SqlAlchemyTaskStore, TaskManager, DeliveryMode
    from app.api.v1.routes.film.common import _CreateOnlyTask
    from app.models.task_links import GenerationTaskLink
    from app.services.studio.shot_status import mark_shot_generating
    from app.tasks.execute_task import enqueue_task_execution

    store = SqlAlchemyTaskStore(db)
    tm = TaskManager(store=store, strategies={})

    if body.task_type == "shot_frame_prompt":
        from app.services.film.shot_frame_prompt_tasks import (
            build_run_args as build_sfp_run_args,
            normalize_frame_type,
            relation_type_for_frame,
        )
        frame_type = normalize_frame_type(body.frame_type)
        relation_type = relation_type_for_frame(frame_type)
        run_args = await build_sfp_run_args(db, shot_id=body.shot_id, frame_type=frame_type)
        task_kind = "shot_frame_prompt"
        resource_type = "prompt"
    elif body.task_type == "video_generation":
        from app.services.film.generated_video import build_run_args as build_vg_run_args
        run_args = await build_vg_run_args(
            db, shot_id=body.shot_id, reference_mode=body.reference_mode,
            prompt=body.prompt, images=body.images, ratio=body.ratio,
        )
        task_kind = "video_generation"
        resource_type = "video"
        relation_type = "shot_video"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported task_type: {body.task_type}",
        )

    task_record = await tm.create(
        task=_CreateOnlyTask(),
        mode=DeliveryMode.async_polling,
        task_kind=task_kind,
        run_args=run_args,
    )
    db.add(GenerationTaskLink(
        task_id=task_record.id,
        resource_type=resource_type,
        relation_type=relation_type,
        relation_entity_id=body.shot_id,
    ))
    await mark_shot_generating(db, shot_id=body.shot_id)
    await db.commit()

    try:
        enqueue_task_execution(task_record.id)
    except Exception as e:
        logger.warning(f"enqueue_task_execution failed (task={task_record.id}): {e}")

    logger.info(
        "create_generation_task",
        extra={
            "project_id": project_id,
            "shot_id": body.shot_id,
            "task_id": task_record.id,
            "task_type": task_kind,
        },
    )

    return success_response(data={
        "task_id": task_record.id,
        "task_type": task_kind,
        "status": "pending",
        "shot_id": body.shot_id,
    })


@router.get("/v1/generation-tasks/{task_id}/status", response_model=ApiResponse[dict])
async def get_task_status_internal(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Gateway 调用：查询任务状态。"""
    from app.core.task_manager import SqlAlchemyTaskStore
    store = SqlAlchemyTaskStore(db)
    view = await store.get_status_view(task_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return success_response(data={
        "task_id": view.id,
        "status": view.status,
        "progress": view.progress,
        "cancel_requested": view.cancel_requested,
        "started_at_ts": view.started_at_ts,
        "finished_at_ts": view.finished_at_ts,
        "elapsed_ms": view.elapsed_ms,
    })


@router.get("/v1/generation-tasks/{task_id}/result", response_model=ApiResponse[dict])
async def get_task_result_internal(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Gateway 调用：获取任务结果。"""
    from app.core.task_manager import SqlAlchemyTaskStore
    store = SqlAlchemyTaskStore(db)
    rec = await store.get(task_id)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return success_response(data={
        "task_id": rec.id,
        "status": rec.status,
        "progress": rec.progress,
        "result": rec.result,
        "error": rec.error,
    })


@router.get("/v1/projects/{project_id}/assets", response_model=ApiResponse[dict])
async def get_project_assets_internal(
    project_id: str,
    asset_type: str | None = Query(None, description="character|scene|prop|costume"),
    q: str | None = Query(None, description="keyword search"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Gateway 调用：查询项目素材（只读）。

    - 项目不存在返回 404。
    - asset_type 为空返回所有类型；指定则过滤。
    - q 模糊搜索 name 和 description。
    - 不创建/修改/删除素材。
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    valid_types = {"character", "scene", "prop", "costume"}
    if asset_type and asset_type not in valid_types:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid asset_type: {asset_type}")

    types_to_query = [asset_type] if asset_type else list(valid_types)
    all_assets: list[dict] = []

    for etype in types_to_query:
        if etype == "character":
            stmt = select(Character).where(Character.project_id == project_id)
            if q:
                stmt = stmt.where((Character.name.ilike(f"%{q}%")) | (Character.description.ilike(f"%{q}%")))
            result = await db.execute(stmt)
            for row in result.scalars():
                all_assets.append({"asset_id": row.id, "asset_type": "character", "name": row.name, "description": row.description, "style": row.style, "visual_style": row.visual_style})
        elif etype == "scene":
            stmt = select(Scene).join(ProjectSceneLink, ProjectSceneLink.scene_id == Scene.id).where(ProjectSceneLink.project_id == project_id)
            if q:
                stmt = stmt.where((Scene.name.ilike(f"%{q}%")) | (Scene.description.ilike(f"%{q}%")))
            result = await db.execute(stmt)
            for row in result.scalars():
                all_assets.append({"asset_id": row.id, "asset_type": "scene", "name": row.name, "description": row.description, "style": row.style, "visual_style": row.visual_style})
        elif etype == "prop":
            stmt = select(Prop).join(ProjectPropLink, ProjectPropLink.prop_id == Prop.id).where(ProjectPropLink.project_id == project_id)
            if q:
                stmt = stmt.where((Prop.name.ilike(f"%{q}%")) | (Prop.description.ilike(f"%{q}%")))
            result = await db.execute(stmt)
            for row in result.scalars():
                all_assets.append({"asset_id": row.id, "asset_type": "prop", "name": row.name, "description": row.description, "style": row.style, "visual_style": row.visual_style})
        elif etype == "costume":
            stmt = select(Costume).join(ProjectCostumeLink, ProjectCostumeLink.costume_id == Costume.id).where(ProjectCostumeLink.project_id == project_id)
            if q:
                stmt = stmt.where((Costume.name.ilike(f"%{q}%")) | (Costume.description.ilike(f"%{q}%")))
            result = await db.execute(stmt)
            for row in result.scalars():
                all_assets.append({"asset_id": row.id, "asset_type": "costume", "name": row.name, "description": row.description, "style": row.style, "visual_style": row.visual_style})

    total = len(all_assets)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = all_assets[start:end]
    has_more = end < total

    return success_response(data={
        "project_id": project_id,
        "asset_type": asset_type or "all",
        "count": len(page_items),
        "total": total,
        "assets": page_items,
        "has_more": has_more,
    })
