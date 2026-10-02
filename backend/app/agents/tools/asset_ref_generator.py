"""GenerateAssetRefsTool: parallel reference image generation for all asset types.

Reads prompt templates from DB (prompt_templates table).
Supports 4 asset types: character (4-view turnaround), scene, prop, costume.
Character refs support multi-state via costume_id column.
All generation runs in parallel with asyncio.gather + semaphore.
Uses direct_image_generate_with_retry for automatic retry.
Uses file_lifecycle for cleanup on replacement.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.tools.base import Tool
from app.agents.tools.direct_api import (
    get_image_api_config,
    direct_image_generate_with_retry,
    save_image_to_db,
)
from app.core.db import async_session_maker
from app.models.studio import (
    Character, CharacterImage, Costume, CostumeImage,
    Prop, PropImage, Scene, SceneImage,
)
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.services.studio.file_lifecycle import delete_image_with_file

if TYPE_CHECKING:
    from app.agents.core import AgentContext

logger = logging.getLogger(__name__)
_CONCURRENCY = 8


async def _get_prompt_templates(db) -> dict:
    """Read all prompt templates from DB. Returns {category: content}."""
    rows = (await db.execute(
        select(PromptTemplate.category, PromptTemplate.content)
    )).all()
    return {r[0]: r[1] for r in rows}


def _build_prompt(template: str, desc: str) -> str:
    """Substitute %s placeholder in template with description."""
    if "%s" in template:
        return template.replace("%s", desc)
    return template + " " + desc if desc else template


class GenerateAssetRefsInput(BaseModel):
    asset_type: str = Field(
        default="character", description="character / scene / prop / costume"
    )
    asset_ids: list[str] = Field(
        default_factory=list, description="specific asset IDs; empty = all"
    )
    force: bool = Field(
        default=False, description="if True, delete and regenerate existing images"
    )


class GenerateAssetRefsTool(Tool):
    name = "generate_asset_refs"
    description = "Auto-generate reference images for characters/scenes/props/costumes."
    input_model = GenerateAssetRefsInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = GenerateAssetRefsInput(**kwargs)
        async with async_session_maker() as db:
            api_key, base_url, model_name = await get_image_api_config(db)
            templates = await _get_prompt_templates(db)
        handlers = {
            "character": self._gen_character_refs,
            "scene": self._gen_scene_refs,
            "prop": self._gen_prop_refs,
            "costume": self._gen_costume_refs,
        }
        handler = handlers.get(data.asset_type)
        if not handler:
            return {"error": "asset_type must be character/scene/prop/costume"}
        return await handler(
            ctx, api_key, base_url, model_name, templates, data.asset_ids, data.force
        )

    # === Per-item generation (each creates own session) ===

    async def _gen_one_char(
        self, api_key, base_url, model_name, templates, char, costume, is_primary, force
    ):
        async with async_session_maker() as db:
            # Idempotent check by (character_id, costume_id)
            if costume is not None:
                existing = (await db.execute(
                    select(CharacterImage.id).where(
                        CharacterImage.character_id == char.id,
                        CharacterImage.costume_id == costume.id,
                    ).limit(1)
                )).scalars().first()
            else:
                existing = (await db.execute(
                    select(CharacterImage.id).where(
                        CharacterImage.character_id == char.id,
                        CharacterImage.costume_id.is_(None),
                    ).limit(1)
                )).scalars().first()

            state_label = costume.name if costume else "default"

            if existing and not force:
                return {
                    "character_id": char.id, "name": char.name,
                    "state": state_label, "status": "skipped", "reason": "exists",
                }

            if existing and force:
                await delete_image_with_file(db, CharacterImage, existing)
                await db.flush()

            desc = char.description or char.name
            if costume and costume.description:
                desc = desc + " Outfit: " + costume.description
            prompt = _build_prompt(
                templates.get("character_image_front", ""), desc
            )
            neg = templates.get("character_image_negative", "")
            try:
                img_url, retries = await direct_image_generate_with_retry(
                    api_key, base_url, model_name, prompt,
                    size="2048x1152", negative_prompt=neg,
                )
                file_id = await save_image_to_db(
                    db, img_url,
                    "char-ref-%s-%s" % (char.name, state_label),
                    "generated-images/character-refs",
                )
                db.add(CharacterImage(
                    character_id=char.id,
                    file_id=file_id,
                    quality_level="standard",
                    view_angle="front",
                    format="png",
                    is_primary=is_primary,
                    costume_id=costume.id if costume else None,
                ))
                await db.commit()
                return {
                    "character_id": char.id, "name": char.name,
                    "state": state_label, "file_id": file_id,
                    "retries": retries, "status": "ok",
                }
            except Exception as e:
                return {
                    "character_id": char.id, "name": char.name,
                    "status": "error", "error": str(e)[:150],
                }

    async def _gen_one_scene(
        self, api_key, base_url, model_name, templates, scene, force
    ):
        async with async_session_maker() as db:
            existing = (await db.execute(
                select(SceneImage.id).where(
                    SceneImage.scene_id == scene.id,
                    SceneImage.file_id.isnot(None),
                ).limit(1)
            )).scalars().first()

            if existing and not force:
                return {"scene_id": scene.id, "name": scene.name, "status": "skipped"}

            if existing and force:
                await delete_image_with_file(db, SceneImage, existing)
                await db.flush()

            desc = scene.description or scene.name
            prompt = _build_prompt(
                templates.get("scene_image_front", ""), desc
            )
            neg = templates.get("scene_image_negative", "")
            try:
                img_url, retries = await direct_image_generate_with_retry(
                    api_key, base_url, model_name, prompt,
                    size="1152x2048", negative_prompt=neg,
                )
                file_id = await save_image_to_db(
                    db, img_url, "scene-ref-%s" % scene.name,
                    "generated-images/scene-refs",
                )
                db.add(SceneImage(
                    scene_id=scene.id, file_id=file_id,
                    quality_level="standard", view_angle="front", format="png",
                ))
                await db.commit()
                return {
                    "scene_id": scene.id, "name": scene.name,
                    "file_id": file_id, "retries": retries, "status": "ok",
                }
            except Exception as e:
                return {
                    "scene_id": scene.id, "name": scene.name,
                    "status": "error", "error": str(e)[:150],
                }

    async def _gen_one_prop(
        self, api_key, base_url, model_name, templates, prop, force
    ):
        async with async_session_maker() as db:
            existing = (await db.execute(
                select(PropImage.id).where(
                    PropImage.prop_id == prop.id,
                    PropImage.file_id.isnot(None),
                ).limit(1)
            )).scalars().first()

            if existing and not force:
                return {"prop_id": prop.id, "name": prop.name, "status": "skipped"}

            if existing and force:
                await delete_image_with_file(db, PropImage, existing)
                await db.flush()

            desc = prop.description or prop.name
            prompt = _build_prompt(
                templates.get("prop_image_front", ""), desc
            )
            neg = templates.get("prop_image_negative", "")
            try:
                img_url, retries = await direct_image_generate_with_retry(
                    api_key, base_url, model_name, prompt,
                    size="2048x2048", negative_prompt=neg,
                )
                file_id = await save_image_to_db(
                    db, img_url, "prop-ref-%s" % prop.name,
                    "generated-images/prop-refs",
                )
                db.add(PropImage(
                    prop_id=prop.id, file_id=file_id,
                    quality_level="standard", view_angle="front", format="png",
                ))
                await db.commit()
                return {
                    "prop_id": prop.id, "name": prop.name,
                    "file_id": file_id, "retries": retries, "status": "ok",
                }
            except Exception as e:
                return {
                    "prop_id": prop.id, "name": prop.name,
                    "status": "error", "error": str(e)[:150],
                }

    async def _gen_one_costume(
        self, api_key, base_url, model_name, templates, costume, force
    ):
        async with async_session_maker() as db:
            existing = (await db.execute(
                select(CostumeImage.id).where(
                    CostumeImage.costume_id == costume.id,
                    CostumeImage.file_id.isnot(None),
                ).limit(1)
            )).scalars().first()

            if existing and not force:
                return {"costume_id": costume.id, "name": costume.name, "status": "skipped"}

            if existing and force:
                await delete_image_with_file(db, CostumeImage, existing)
                await db.flush()

            desc = costume.description or costume.name
            prompt = _build_prompt(
                templates.get("costume_image_front", ""), desc
            )
            neg = templates.get("costume_image_negative", "")
            try:
                img_url, retries = await direct_image_generate_with_retry(
                    api_key, base_url, model_name, prompt,
                    size="2048x2048", negative_prompt=neg,
                )
                file_id = await save_image_to_db(
                    db, img_url, "costume-ref-%s" % costume.name,
                    "generated-images/costume-refs",
                )
                db.add(CostumeImage(
                    costume_id=costume.id, file_id=file_id,
                    quality_level="standard", view_angle="front", format="png",
                ))
                await db.commit()
                return {
                    "costume_id": costume.id, "name": costume.name,
                    "file_id": file_id, "retries": retries, "status": "ok",
                }
            except Exception as e:
                return {
                    "costume_id": costume.id, "name": costume.name,
                    "status": "error", "error": str(e)[:150],
                }

    # === Batch methods: query data, then generate in parallel ===

    async def _gen_character_refs(
        self, ctx, api_key, base_url, model_name, templates, asset_ids, force
    ):
        async with async_session_maker() as db:
            stmt = select(Character).where(
                Character.project_id == ctx.project_id
            ).order_by(Character.created_at)
            if asset_ids:
                stmt = stmt.where(Character.id.in_(asset_ids))
            characters = (await db.execute(stmt)).scalars().all()
            # Query costumes via character_id column (new multi-state link)
            char_ids = [c.id for c in characters]
            costumes_by_char = {}
            if char_ids:
                costume_rows = (await db.execute(
                    select(Costume).where(
                        Costume.character_id.in_(char_ids)
                    ).order_by(Costume.created_at)
                )).scalars().all()
                for costume in costume_rows:
                    costumes_by_char.setdefault(
                        costume.character_id, []
                    ).append(costume)

        tasks = []
        for char in characters:
            char_costumes = costumes_by_char.get(char.id, [])
            if char_costumes:
                for idx, costume in enumerate(char_costumes):
                    tasks.append(self._gen_one_char(
                        api_key, base_url, model_name, templates,
                        char, costume, idx == 0, force,
                    ))
            else:
                tasks.append(self._gen_one_char(
                    api_key, base_url, model_name, templates,
                    char, None, True, force,
                ))

        sem = asyncio.Semaphore(_CONCURRENCY)

        async def limited(t):
            async with sem:
                return await t

        results = await asyncio.gather(*[limited(t) for t in tasks])
        ok = sum(1 for r in results if r.get("status") == "ok")
        return {
            "asset_type": "character", "total": len(results),
            "generated": ok, "results": list(results),
        }

    async def _gen_scene_refs(
        self, ctx, api_key, base_url, model_name, templates, asset_ids, force
    ):
        async with async_session_maker() as db:
            stmt = select(Scene).where(
                Scene.project_id == ctx.project_id
            ).order_by(Scene.created_at)
            if asset_ids:
                stmt = stmt.where(Scene.id.in_(asset_ids))
            scenes = (await db.execute(stmt)).scalars().all()

        sem = asyncio.Semaphore(_CONCURRENCY)

        async def limited(s):
            async with sem:
                return await self._gen_one_scene(
                    api_key, base_url, model_name, templates, s, force
                )

        results = await asyncio.gather(*[limited(s) for s in scenes])
        ok = sum(1 for r in results if r.get("status") == "ok")
        return {
            "asset_type": "scene", "total": len(scenes),
            "generated": ok, "results": list(results),
        }

    async def _gen_prop_refs(
        self, ctx, api_key, base_url, model_name, templates, asset_ids, force
    ):
        async with async_session_maker() as db:
            stmt = select(Prop).where(
                Prop.project_id == ctx.project_id
            ).order_by(Prop.created_at)
            if asset_ids:
                stmt = stmt.where(Prop.id.in_(asset_ids))
            props = (await db.execute(stmt)).scalars().all()

        sem = asyncio.Semaphore(_CONCURRENCY)

        async def limited(p):
            async with sem:
                return await self._gen_one_prop(
                    api_key, base_url, model_name, templates, p, force
                )

        results = await asyncio.gather(*[limited(p) for p in props])
        ok = sum(1 for r in results if r.get("status") == "ok")
        return {
            "asset_type": "prop", "total": len(props),
            "generated": ok, "results": list(results),
        }

    async def _gen_costume_refs(
        self, ctx, api_key, base_url, model_name, templates, asset_ids, force
    ):
        async with async_session_maker() as db:
            stmt = select(Costume).where(
                Costume.project_id == ctx.project_id
            ).order_by(Costume.created_at)
            if asset_ids:
                stmt = stmt.where(Costume.id.in_(asset_ids))
            costumes = (await db.execute(stmt)).scalars().all()

        sem = asyncio.Semaphore(_CONCURRENCY)

        async def limited(c):
            async with sem:
                return await self._gen_one_costume(
                    api_key, base_url, model_name, templates, c, force
                )

        results = await asyncio.gather(*[limited(c) for c in costumes])
        ok = sum(1 for r in results if r.get("status") == "ok")
        return {
            "asset_type": "costume", "total": len(costumes),
            "generated": ok, "results": list(results),
        }
