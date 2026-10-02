"""GenerateAssetRefsTool: parallel reference image generation for all asset types.

Supports 4 asset types: character (4-view turnaround), scene, prop, costume.
Character refs support multi-state (e.g. Lin Chen x3 states).
All prompts follow ASSET_REFERENCE_STANDARDS.md.
All generation runs in parallel with asyncio.gather + semaphore.
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
    direct_image_generate,
    save_image_to_db,
)
from app.core.db import async_session_maker
from app.models.studio import (
    Character, CharacterImage, Costume, CostumeImage,
    FileItem, Prop, PropImage, Scene, SceneImage,
)

if TYPE_CHECKING:
    from app.agents.core import AgentContext

logger = logging.getLogger(__name__)
_CONCURRENCY = 8

# === Character: 4-view turnaround sheet ===
_CHAR_POS = (
    "Professional real-person character reference sheet, landscape layout, "
    "left side is head/face close-up, "
    "right side 3 full body photos: front, right side, back. "
    "All same person, unified features/hair/outfit/accessories. "
    "Natural neutral standing pose, arms hanging, head to toe no crop, "
    "orthographic view, no perspective distortion. "
    "Pure white solid studio background, even soft studio lighting, "
    "commercial portrait photography, Chinese realistic style, "
    "realistic skin texture, rich detail, 8K HD, "
    "no text, no watermark, no extra objects. %s"
)
_CHAR_NEG = (
    "Inconsistent features, face change, different person, limb distortion, "
    "crop, close-up misalignment, extra person, scene environment, "
    "strong shadow, text, watermark, perspective, deformed hands/feet, "
    "clothing error, blur, low quality, anime, 2D, 3D render, cartoon, hand-drawn"
)

# === Scene: establishing shot ===
_SCENE_POS = (
    "Cinematic establishing shot, wide angle, 9:16 vertical, "
    "completely empty environment, absolutely no people, "
    "no human figures, no silhouettes, no shadows of people, "
    "vacant, uninhabited, deserted location. %s "
    "Realistic photo texture, cinematic lighting, 8K HD, "
    "no text, no watermark."
)
_SCENE_NEG = (
    "Any person, human figure, silhouette, shadow of person, partial body, "
    "crowd, guest, face, back of person, hand, arm, leg, "
    "text, watermark, cartoon, anime, 2D, 3D render, "
    "low quality, blur, oversaturated, fisheye distortion"
)

# === Prop: product photography ===
_PROP_POS = (
    "Product photography, multiple angles on pure white background, "
    "studio lighting, macro detail, material texture visible, "
    "high quality commercial shot, 8K. %s"
)
_PROP_NEG = (
    "Hands, human, background clutter, blur, low quality, text, watermark, "
    "cartoon, anime, 2D, 3D render, deformed, cropped"
)

# === Costume: flat-lay ===
_COSTUME_POS = (
    "Flat lay clothing photography, full outfit laid out on pure white background, "
    "all pieces visible, fabric texture detail, accurate colors, "
    "commercial fashion photography, 8K. %s"
)
_COSTUME_NEG = (
    "Human model, mannequin, body, background clutter, blur, low quality, "
    "text, watermark, cartoon, anime, 2D, 3D render, deformed, cropped"
)

_STATE_ANGLES = ["front", "side_left", "side_right", "back"]


class GenerateAssetRefsInput(BaseModel):
    asset_type: str = Field(default="character", description="character / scene / prop / costume")
    asset_ids: list[str] = Field(default_factory=list, description="specific asset IDs; empty = all")


class GenerateAssetRefsTool(Tool):
    name = "generate_asset_refs"
    description = "Auto-generate reference images for characters/scenes/props/costumes."
    input_model = GenerateAssetRefsInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = GenerateAssetRefsInput(**kwargs)
        async with async_session_maker() as db:
            api_key, base_url, model_name = await get_image_api_config(db)
        handlers = {
            "character": self._gen_character_refs,
            "scene": self._gen_scene_refs,
            "prop": self._gen_prop_refs,
            "costume": self._gen_costume_refs,
        }
        handler = handlers.get(data.asset_type)
        if not handler:
            return {"error": "asset_type must be character/scene/prop/costume"}
        return await handler(ctx, api_key, base_url, model_name, data.asset_ids)

    # === Per-item generation (each creates own session) ===

    async def _gen_one_char(self, api_key, base_url, model_name, char, costume, angle, is_primary):
        async with async_session_maker() as db:
            existing = (await db.execute(
                select(CharacterImage.file_id).where(
                    CharacterImage.character_id == char.id,
                    CharacterImage.view_angle == angle,
                ).limit(1)
            )).first()
            if existing:
                return {"character_id": char.id, "name": char.name, "status": "skipped", "reason": "exists " + angle}
            desc = char.description or char.name
            if costume and costume.description:
                desc = desc + " Outfit: " + costume.description
            prompt = _CHAR_POS % desc
            try:
                img_url = await direct_image_generate(api_key, base_url, model_name, prompt, size="2048x1152", negative_prompt=_CHAR_NEG)
                state_label = costume.name.split("\u00b7")[-1] if costume and "\u00b7" in costume.name else "default"
                file_id = await save_image_to_db(db, img_url, "char-ref-%s-%s" % (char.name, state_label), "generated-images/character-refs")
                db.add(CharacterImage(character_id=char.id, file_id=file_id, quality_level="standard", view_angle=angle, format="png", is_primary=is_primary))
                await db.commit()
                return {"character_id": char.id, "name": char.name, "state": state_label, "file_id": file_id, "angle": angle, "status": "ok"}
            except Exception as e:
                return {"character_id": char.id, "name": char.name, "status": "error", "error": str(e)[:150]}

    async def _gen_one_scene(self, api_key, base_url, model_name, scene):
        async with async_session_maker() as db:
            existing = (await db.execute(select(SceneImage.file_id).where(SceneImage.scene_id == scene.id, SceneImage.file_id.isnot(None)).limit(1))).first()
            if existing:
                return {"scene_id": scene.id, "name": scene.name, "status": "skipped"}
            desc = scene.description or scene.name
            prompt = _SCENE_POS % desc
            try:
                img_url = await direct_image_generate(api_key, base_url, model_name, prompt, size="1152x2048", negative_prompt=_SCENE_NEG)
                file_id = await save_image_to_db(db, img_url, "scene-ref-%s" % scene.name, "generated-images/scene-refs")
                db.add(SceneImage(scene_id=scene.id, file_id=file_id, quality_level="standard", view_angle="front", format="png"))
                await db.commit()
                return {"scene_id": scene.id, "name": scene.name, "file_id": file_id, "status": "ok"}
            except Exception as e:
                return {"scene_id": scene.id, "name": scene.name, "status": "error", "error": str(e)[:150]}

    async def _gen_one_prop(self, api_key, base_url, model_name, prop):
        async with async_session_maker() as db:
            existing = (await db.execute(select(PropImage.file_id).where(PropImage.prop_id == prop.id, PropImage.file_id.isnot(None)).limit(1))).first()
            if existing:
                return {"prop_id": prop.id, "name": prop.name, "status": "skipped"}
            desc = prop.description or prop.name
            prompt = _PROP_POS % desc
            try:
                img_url = await direct_image_generate(api_key, base_url, model_name, prompt, size="2048x2048", negative_prompt=_PROP_NEG)
                file_id = await save_image_to_db(db, img_url, "prop-ref-%s" % prop.name, "generated-images/prop-refs")
                db.add(PropImage(prop_id=prop.id, file_id=file_id, quality_level="standard", view_angle="front", format="png"))
                await db.commit()
                return {"prop_id": prop.id, "name": prop.name, "file_id": file_id, "status": "ok"}
            except Exception as e:
                return {"prop_id": prop.id, "name": prop.name, "status": "error", "error": str(e)[:150]}

    async def _gen_one_costume(self, api_key, base_url, model_name, costume):
        async with async_session_maker() as db:
            existing = (await db.execute(select(CostumeImage.file_id).where(CostumeImage.costume_id == costume.id, CostumeImage.file_id.isnot(None)).limit(1))).first()
            if existing:
                return {"costume_id": costume.id, "name": costume.name, "status": "skipped"}
            desc = costume.description or costume.name
            prompt = _COSTUME_POS % desc
            try:
                img_url = await direct_image_generate(api_key, base_url, model_name, prompt, size="2048x2048", negative_prompt=_COSTUME_NEG)
                file_id = await save_image_to_db(db, img_url, "costume-ref-%s" % costume.name, "generated-images/costume-refs")
                db.add(CostumeImage(costume_id=costume.id, file_id=file_id, quality_level="standard", view_angle="front", format="png"))
                await db.commit()
                return {"costume_id": costume.id, "name": costume.name, "file_id": file_id, "status": "ok"}
            except Exception as e:
                return {"costume_id": costume.id, "name": costume.name, "status": "error", "error": str(e)[:150]}

    # === Batch methods: query data, then generate in parallel ===

    async def _gen_character_refs(self, ctx, api_key, base_url, model_name, asset_ids):
        async with async_session_maker() as db:
            stmt = select(Character).where(Character.project_id == ctx.project_id).order_by(Character.created_at)
            if asset_ids:
                stmt = stmt.where(Character.id.in_(asset_ids))
            characters = (await db.execute(stmt)).scalars().all()
            costumes = (await db.execute(select(Costume).where(Costume.project_id == ctx.project_id))).scalars().all()

        tasks = []
        for char in characters:
            char_costumes = [c for c in costumes if c.name.startswith(char.name + "\u00b7")]
            if not char_costumes:
                char_costumes = [c for c in costumes if char.name in c.name]
            if char_costumes and len(char_costumes) > 1:
                for idx, costume in enumerate(char_costumes):
                    angle = _STATE_ANGLES[idx] if idx < len(_STATE_ANGLES) else "back"
                    tasks.append(self._gen_one_char(api_key, base_url, model_name, char, costume, angle, idx == 0))
            else:
                costume = char_costumes[0] if char_costumes else None
                tasks.append(self._gen_one_char(api_key, base_url, model_name, char, costume, "front", True))

        sem = asyncio.Semaphore(_CONCURRENCY)
        async def limited(t):
            async with sem:
                return await t
        results = await asyncio.gather(*[limited(t) for t in tasks])
        ok = sum(1 for r in results if r.get("status") == "ok")
        return {"asset_type": "character", "total": len(results), "generated": ok, "results": list(results)}

    async def _gen_scene_refs(self, ctx, api_key, base_url, model_name, asset_ids):
        async with async_session_maker() as db:
            stmt = select(Scene).where(Scene.project_id == ctx.project_id).order_by(Scene.created_at)
            if asset_ids:
                stmt = stmt.where(Scene.id.in_(asset_ids))
            scenes = (await db.execute(stmt)).scalars().all()
        sem = asyncio.Semaphore(_CONCURRENCY)
        async def limited(s):
            async with sem:
                return await self._gen_one_scene(api_key, base_url, model_name, s)
        results = await asyncio.gather(*[limited(s) for s in scenes])
        ok = sum(1 for r in results if r.get("status") == "ok")
        return {"asset_type": "scene", "total": len(scenes), "generated": ok, "results": list(results)}

    async def _gen_prop_refs(self, ctx, api_key, base_url, model_name, asset_ids):
        async with async_session_maker() as db:
            stmt = select(Prop).where(Prop.project_id == ctx.project_id).order_by(Prop.created_at)
            if asset_ids:
                stmt = stmt.where(Prop.id.in_(asset_ids))
            props = (await db.execute(stmt)).scalars().all()
        sem = asyncio.Semaphore(_CONCURRENCY)
        async def limited(p):
            async with sem:
                return await self._gen_one_prop(api_key, base_url, model_name, p)
        results = await asyncio.gather(*[limited(p) for p in props])
        ok = sum(1 for r in results if r.get("status") == "ok")
        return {"asset_type": "prop", "total": len(props), "generated": ok, "results": list(results)}

    async def _gen_costume_refs(self, ctx, api_key, base_url, model_name, asset_ids):
        async with async_session_maker() as db:
            stmt = select(Costume).where(Costume.project_id == ctx.project_id).order_by(Costume.created_at)
            if asset_ids:
                stmt = stmt.where(Costume.id.in_(asset_ids))
            costumes = (await db.execute(stmt)).scalars().all()
        sem = asyncio.Semaphore(_CONCURRENCY)
        async def limited(c):
            async with sem:
                return await self._gen_one_costume(api_key, base_url, model_name, c)
        results = await asyncio.gather(*[limited(c) for c in costumes])
        ok = sum(1 for r in results if r.get("status") == "ok")
        return {"asset_type": "costume", "total": len(costumes), "generated": ok, "results": list(results)}
