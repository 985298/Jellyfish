"""Studio 实体与实体图片的协调服务。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.studio.entity_crud import (
    create_entity as create_entity_service,
    delete_entity as delete_entity_service,
    get_entity as get_entity_service,
    list_entities_paginated,
    update_entity as update_entity_service,
)
from app.services.studio.entity_existence import check_names_existence as check_names_existence_service
from app.services.studio.entity_images import (
    create_entity_image as create_entity_image_service,
    delete_entity_image as delete_entity_image_service,
    list_asset_images_paginated,
    list_entity_images_paginated,
    update_entity_image as update_entity_image_service,
)


class StudioEntitiesService:
    """封装 studio 通用实体与图片的协调调用。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def check_names_existence(
        self,
        *,
        project_id: str,
        shot_id: str | None = None,
        character_names: list[str],
        prop_names: list[str],
        scene_names: list[str],
        costume_names: list[str],
    ) -> dict[str, list[dict[str, object]]]:
        return await check_names_existence_service(
            self._db,
            project_id=project_id,
            shot_id=shot_id,
            character_names=character_names,
            prop_names=prop_names,
            scene_names=scene_names,
            costume_names=costume_names,
        )

    async def list_entities(
        self,
        *,
        entity_type: str,
        q: str | None,
        style: str | None,
        visual_style: str | None,
        project_id: str | None,
        order: str | None,
        is_desc: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], int]:
        return await list_entities_paginated(
            self._db,
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

    async def create_entity(self, *, entity_type: str, body: dict[str, object]) -> dict[str, object]:
        return await create_entity_service(self._db, entity_type=entity_type, body=body)

    async def get_entity(self, *, entity_type: str, entity_id: str) -> dict[str, object]:
        return await get_entity_service(self._db, entity_type=entity_type, entity_id=entity_id)

    async def update_entity(
        self,
        *,
        entity_type: str,
        entity_id: str,
        body: dict[str, object],
    ) -> dict[str, object]:
        return await update_entity_service(
            self._db,
            entity_type=entity_type,
            entity_id=entity_id,
            body=body,
        )

    async def delete_entity(self, *, entity_type: str, entity_id: str) -> None:
        await delete_entity_service(self._db, entity_type=entity_type, entity_id=entity_id)

    async def get_entity_usage(self, *, entity_type: str, entity_id: str) -> dict[str, object]:
        """统计实体被多少镜头/章节引用（B2：删除前影响面提示）。

        - character：经 ShotCharacterLink 反查 shot_id，再聚合 chapter_id
        - scene：经 ShotDetail.scene_id 反查 shot_id，再聚合 chapter_id
        - prop / costume：经 ShotExtractedCandidate（candidate_type + linked_entity_id）反查
        - actor：当前不直接被镜头引用，返回 0（演员是项目级 casting，不绑镜头）
        """
        from sqlalchemy import func, select
        from app.models.studio import Chapter, Shot, ShotCharacterLink, ShotDetail, ShotExtractedCandidate
        from app.models.types import ShotCandidateType

        entity_type_norm = entity_type.strip().lower()
        shot_ids: set[str] = set()

        if entity_type_norm == "character":
            rows = (
                await self._db.execute(
                    select(ShotCharacterLink.shot_id).where(ShotCharacterLink.character_id == entity_id)
                )
            ).scalars().all()
            shot_ids = {str(r) for r in rows}
        elif entity_type_norm == "scene":
            rows = (
                await self._db.execute(
                    select(ShotDetail.id).where(ShotDetail.scene_id == entity_id)
                )
            ).scalars().all()
            shot_ids = {str(r) for r in rows}
        elif entity_type_norm in {"prop", "costume"}:
            cand_type = ShotCandidateType.prop if entity_type_norm == "prop" else ShotCandidateType.costume
            rows = (
                await self._db.execute(
                    select(ShotExtractedCandidate.shot_id).where(
                        ShotExtractedCandidate.candidate_type == cand_type,
                        ShotExtractedCandidate.linked_entity_id == entity_id,
                    )
                )
            ).scalars().all()
            shot_ids = {str(r) for r in rows}
        else:
            return {"shot_count": 0, "chapter_count": 0, "shot_ids": []}

        if not shot_ids:
            return {"shot_count": 0, "chapter_count": 0, "shot_ids": []}

        chapter_rows = (
            await self._db.execute(
                select(Shot.chapter_id).where(Shot.id.in_(shot_ids)).distinct()
            )
        ).scalars().all()
        chapter_ids = {str(r) for r in chapter_rows}

        return {
            "shot_count": len(shot_ids),
            "chapter_count": len(chapter_ids),
            "shot_ids": sorted(shot_ids),
        }

    async def list_entity_images(
        self,
        *,
        entity_type: str,
        entity_id: str,
        order: str | None,
        is_desc: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], int]:
        return await list_entity_images_paginated(
            self._db,
            entity_type=entity_type,
            entity_id=entity_id,
            order=order,
            is_desc=is_desc,
            page=page,
            page_size=page_size,
        )

    async def list_asset_images(
        self,
        *,
        entity_type: str,
        entity_id: str | None,
        order: str | None,
        is_desc: bool,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], int]:
        return await list_asset_images_paginated(
            self._db,
            entity_type=entity_type,
            entity_id=entity_id,
            order=order,
            is_desc=is_desc,
            page=page,
            page_size=page_size,
        )

    async def create_entity_image(
        self,
        *,
        entity_type: str,
        entity_id: str,
        body: dict[str, object],
    ) -> dict[str, object]:
        return await create_entity_image_service(
            self._db,
            entity_type=entity_type,
            entity_id=entity_id,
            body=body,
        )

    async def update_entity_image(
        self,
        *,
        entity_type: str,
        entity_id: str,
        image_id: int,
        body: dict[str, object],
    ) -> dict[str, object]:
        return await update_entity_image_service(
            self._db,
            entity_type=entity_type,
            entity_id=entity_id,
            image_id=image_id,
            body=body,
        )

    async def delete_entity_image(self, *, entity_type: str, entity_id: str, image_id: int) -> None:
        await delete_entity_image_service(
            self._db,
            entity_type=entity_type,
            entity_id=entity_id,
            image_id=image_id,
        )
