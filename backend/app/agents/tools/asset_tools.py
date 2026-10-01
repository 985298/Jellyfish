"""Asset tools: script query, asset extraction, asset query, image generation, status check."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.tools.base import Tool
from app.core.db import async_session_maker
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
)
from app.models.types import AssetQualityLevel, AssetViewAngle
from app.services.script_processing_tasks import (
    create_asset_extract_task,
    spawn_asset_extract_task,
)
from app.services.studio.image_task_runner import create_image_task_and_link

if TYPE_CHECKING:
    from app.agents.core import AgentContext

# entity_type -> (model_class, relation_type, image_model_class, fk_field)
_ENTITY_MAP: dict[str, tuple[type, str, type, str]] = {
    "character": (Character, "character", CharacterImage, "character_id"),
    "scene": (Scene, "scene_image", SceneImage, "scene_id"),
    "prop": (Prop, "prop_image", PropImage, "prop_id"),
    "costume": (Costume, "costume_image", CostumeImage, "costume_id"),
}


class GetChapterScriptInput(BaseModel):
    chapter_id: str = Field(description="chapter id")


class GetChapterScriptTool(Tool):
    name = "get_chapter_script"
    description = "Get chapter script text (raw_text, fallback condensed_text)"
    input_model = GetChapterScriptInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = GetChapterScriptInput(**kwargs)
        async with async_session_maker() as db:
            chapter = await db.get(Chapter, data.chapter_id)
            if chapter is None:
                return {"error": "chapter not found", "chapter_id": data.chapter_id}
            script_text = chapter.raw_text or chapter.condensed_text or ""
            return {
                "chapter_id": chapter.id,
                "title": chapter.title,
                "script_text": script_text,
            }


class ExtractAssetsInput(BaseModel):
    project_id: str = Field(description="project id")
    script_text: str = Field(description="script text")


class ExtractAssetsTool(Tool):
    name = "extract_assets"
    description = "Extract project-level assets from script text and spawn the task"
    input_model = ExtractAssetsInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = ExtractAssetsInput(**kwargs)
        async with async_session_maker() as db:
            result = await create_asset_extract_task(
                db,
                project_id=data.project_id,
                script_text=data.script_text,
                write_to_db=True,
            )
            await db.commit()
        spawn_asset_extract_task(result.task_id)
        return {
            "task_id": result.task_id,
            "status": str(result.status),
            "reused": result.reused,
            "relation_entity_id": result.relation_entity_id,
        }


class QueryAssetsInput(BaseModel):
    project_id: str = Field(description="project id")
    entity_type: str = Field(description="character / scene / prop / costume")


class QueryAssetsTool(Tool):
    name = "query_assets"
    description = "Query project assets (character / scene / prop / costume)"
    input_model = QueryAssetsInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = QueryAssetsInput(**kwargs)
        mapping = _ENTITY_MAP.get(data.entity_type)
        if mapping is None:
            return {"error": f"unknown entity_type: {data.entity_type}"}
        model_cls = mapping[0]
        async with async_session_maker() as db:
            rows = (
                await db.execute(
                    select(model_cls).where(model_cls.project_id == data.project_id)
                )
            ).scalars().all()
            items = [
                {"id": r.id, "name": r.name, "description": r.description}
                for r in rows
            ]
            return {
                "entity_type": data.entity_type,
                "count": len(items),
                "items": items,
            }


class GenerateImageInput(BaseModel):
    entity_type: str = Field(description="character / scene / prop / costume")
    entity_id: str = Field(description="entity id")
    prompt: str | None = Field(default=None, description="custom prompt (auto-built if empty)")


class GenerateImageTool(Tool):
    name = "generate_image"
    description = "Generate an image for a given asset via create_image_task_and_link"
    input_model = GenerateImageInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = GenerateImageInput(**kwargs)
        mapping = _ENTITY_MAP.get(data.entity_type)
        if mapping is None:
            return {"error": f"unknown entity_type: {data.entity_type}"}
        model_cls, relation_type, img_cls, fk_field = mapping
        async with async_session_maker() as db:
            entity = await db.get(model_cls, data.entity_id)
            if entity is None:
                return {
                    "error": "entity not found",
                    "entity_type": data.entity_type,
                    "entity_id": data.entity_id,
                }
            prompt = data.prompt or f"{entity.name} {entity.description}".strip()
            relation_entity_id = data.entity_id
            # For non-character assets the runner expects an image-row id, not the
            # entity id. Find or create a low/front slot to use as the target.
            if relation_type != "character":
                image_row = (
                    await db.execute(
                        select(img_cls)
                        .where(
                            getattr(img_cls, fk_field) == data.entity_id,
                            img_cls.quality_level == AssetQualityLevel.low,
                            img_cls.view_angle == AssetViewAngle.front,
                        )
                        .limit(1)
                    )
                ).scalars().first()
                if image_row is None:
                    image_row = img_cls(
                        **{fk_field: data.entity_id},
                        quality_level=AssetQualityLevel.low,
                        view_angle=AssetViewAngle.front,
                        format="png",
                    )
                    db.add(image_row)
                    await db.flush()
                relation_entity_id = str(image_row.id)
            task_id = await create_image_task_and_link(
                db=db,
                model_id=None,
                relation_type=relation_type,
                relation_entity_id=relation_entity_id,
                prompt=prompt,
            )
        return {
            "task_id": task_id,
            "entity_type": data.entity_type,
            "entity_id": data.entity_id,
            "prompt": prompt,
        }


class CheckAssetStatusInput(BaseModel):
    project_id: str = Field(description="project id")


class CheckAssetStatusTool(Tool):
    name = "check_asset_status"
    description = "Check image generation status for all project assets (file_id null = pending)"
    input_model = CheckAssetStatusInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = CheckAssetStatusInput(**kwargs)
        details: list[dict] = []
        total = 0
        ready = 0
        async with async_session_maker() as db:
            for entity_type, (model_cls, _rt, img_cls, fk) in _ENTITY_MAP.items():
                entities = (
                    await db.execute(
                        select(model_cls).where(
                            model_cls.project_id == data.project_id
                        )
                    )
                ).scalars().all()
                for entity in entities:
                    total += 1
                    has_image = (
                        await db.execute(
                            select(img_cls.id)
                            .where(
                                getattr(img_cls, fk) == entity.id,
                                img_cls.file_id.isnot(None),
                            )
                            .limit(1)
                        )
                    ).first() is not None
                    if has_image:
                        ready += 1
                    details.append(
                        {
                            "entity_type": entity_type,
                            "entity_id": entity.id,
                            "name": entity.name,
                            "has_image": has_image,
                        }
                    )
        return {
            "project_id": data.project_id,
            "total": total,
            "ready": ready,
            "pending": total - ready,
            "details": details,
        }
