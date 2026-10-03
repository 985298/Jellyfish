"""统一实体 CRUD：actor/character/scene/prop/costume。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.common import ApiResponse, PaginatedData, created_response, empty_response, paginated_response, success_response
from app.schemas.studio.entity_existence import (
    EntityNameExistenceCheckRequest,
    EntityNameExistenceCheckResponse,
)
from app.services.studio import StudioEntitiesService

router = APIRouter()


@router.post(
    "/existence-check",
    response_model=ApiResponse[EntityNameExistenceCheckResponse],
    summary="批量检测资产名称是否存在（模糊匹配，不分页）",
)
async def check_entity_names_existence(
    body: EntityNameExistenceCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EntityNameExistenceCheckResponse]:
    service = StudioEntitiesService(db)
    data = await service.check_names_existence(
        project_id=body.project_id,
        shot_id=body.shot_id,
        character_names=body.character_names,
        prop_names=body.prop_names,
        scene_names=body.scene_names,
        costume_names=body.costume_names,
    )
    return success_response(EntityNameExistenceCheckResponse.model_validate(data))


# ---- 类型化图片全局列表（scene_images / prop_images / costume_images） ----
# 注意：必须声明在 `/{entity_type}` 这类动态路径之前，否则 FastAPI 会把
# `scene_images` 当作 entity_type 参数，先匹配到 list_entities（→ 400 invalid_choice）。
@router.get(
    "/scene_images",
    response_model=ApiResponse[PaginatedData[dict[str, Any]]],
    summary="场景图片全局列表（分页）",
)
async def list_scene_images(
    db: AsyncSession = Depends(get_db),
    entity_id: str | None = Query(None, description="按场景 ID 过滤；缺省返回全部场景图片"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    service = StudioEntitiesService(db)
    payload, total = await service.list_asset_images(
        entity_type="scene",
        entity_id=entity_id,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
    )
    return paginated_response(payload, page=page, page_size=page_size, total=total)


@router.get(
    "/prop_images",
    response_model=ApiResponse[PaginatedData[dict[str, Any]]],
    summary="道具图片全局列表（分页）",
)
async def list_prop_images(
    db: AsyncSession = Depends(get_db),
    entity_id: str | None = Query(None, description="按道具 ID 过滤；缺省返回全部道具图片"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    service = StudioEntitiesService(db)
    payload, total = await service.list_asset_images(
        entity_type="prop",
        entity_id=entity_id,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
    )
    return paginated_response(payload, page=page, page_size=page_size, total=total)


@router.get(
    "/costume_images",
    response_model=ApiResponse[PaginatedData[dict[str, Any]]],
    summary="服装图片全局列表（分页）",
)
async def list_costume_images(
    db: AsyncSession = Depends(get_db),
    entity_id: str | None = Query(None, description="按服装 ID 过滤；缺省返回全部服装图片"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    service = StudioEntitiesService(db)
    payload, total = await service.list_asset_images(
        entity_type="costume",
        entity_id=entity_id,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
    )
    return paginated_response(payload, page=page, page_size=page_size, total=total)


@router.get("/{entity_type}", response_model=ApiResponse[PaginatedData[dict[str, Any]]], summary="统一实体列表（分页）")
async def list_entities(
    entity_type: str,
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="关键字，过滤 name/description"),
    style: str | None = Query(None, description="题材/风格（单值）"),
    visual_style: str | None = Query(None, description="画面表现形式（单值：真人/动漫）"),
    project_id: str | None = Query(None, description="可选：按项目过滤（character/scene/prop/costume 直接匹配；actor 经 ProjectActorLink 反查）；缺省返回全部"),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    service = StudioEntitiesService(db)
    payload, total = await service.list_entities(
        entity_type=entity_type,
        q=q,
        style=style,
        visual_style=visual_style,
        project_id=project_id,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
    )
    return paginated_response(payload, page=page, page_size=page_size, total=total)


@router.post("/{entity_type}", response_model=ApiResponse[dict[str, Any]], status_code=status.HTTP_201_CREATED, summary="统一创建实体")
async def create_entity(
    entity_type: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.create_entity(entity_type=entity_type, body=body)
    return created_response(payload)


@router.get("/{entity_type}/{entity_id}", response_model=ApiResponse[dict[str, Any]], summary="统一获取实体")
async def get_entity(entity_type: str, entity_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.get_entity(entity_type=entity_type, entity_id=entity_id)
    return success_response(payload)


@router.patch("/{entity_type}/{entity_id}", response_model=ApiResponse[dict[str, Any]], summary="统一更新实体")
async def update_entity(
    entity_type: str,
    entity_id: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.update_entity(entity_type=entity_type, entity_id=entity_id, body=body)
    return success_response(payload)


@router.delete("/{entity_type}/{entity_id}", response_model=ApiResponse[None], summary="统一删除实体")
async def delete_entity(entity_type: str, entity_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[None]:
    service = StudioEntitiesService(db)
    await service.delete_entity(entity_type=entity_type, entity_id=entity_id)
    return empty_response()


@router.get(
    "/{entity_type}/{entity_id}/images",
    response_model=ApiResponse[PaginatedData[dict[str, Any]]],
    summary="统一实体图片列表（分页）",
)
async def list_entity_images(
    entity_type: str,
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    order: str | None = Query(None),
    is_desc: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> ApiResponse[PaginatedData[dict[str, Any]]]:
    service = StudioEntitiesService(db)
    payload, total = await service.list_entity_images(
        entity_type=entity_type,
        entity_id=entity_id,
        order=order,
        is_desc=is_desc,
        page=page,
        page_size=page_size,
    )
    return paginated_response(payload, page=page, page_size=page_size, total=total)


@router.post(
    "/{entity_type}/{entity_id}/images",
    response_model=ApiResponse[dict[str, Any]],
    status_code=status.HTTP_201_CREATED,
    summary="统一创建实体图片",
)
async def create_entity_image(
    entity_type: str,
    entity_id: str,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.create_entity_image(entity_type=entity_type, entity_id=entity_id, body=body)
    return created_response(payload)


@router.patch(
    "/{entity_type}/{entity_id}/images/{image_id}",
    response_model=ApiResponse[dict[str, Any]],
    summary="统一更新实体图片",
)
async def update_entity_image(
    entity_type: str,
    entity_id: str,
    image_id: int,
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[dict[str, Any]]:
    service = StudioEntitiesService(db)
    payload = await service.update_entity_image(
        entity_type=entity_type,
        entity_id=entity_id,
        image_id=image_id,
        body=body,
    )
    return success_response(payload)


@router.delete(
    "/{entity_type}/{entity_id}/images/{image_id}",
    response_model=ApiResponse[None],
    summary="统一删除实体图片",
)
async def delete_entity_image(
    entity_type: str,
    entity_id: str,
    image_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    service = StudioEntitiesService(db)
    await service.delete_entity_image(entity_type=entity_type, entity_id=entity_id, image_id=image_id)
    return empty_response()
