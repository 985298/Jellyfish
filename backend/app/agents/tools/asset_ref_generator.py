"""GenerateAssetRefsTool: auto-generate reference images for characters/scenes.

Simplified version (P1-5): 1 reference image per character/scene.
Prompt comes from Character.description / Scene.description.
Uses direct_image_generate (text-to-image, no img2img needed for first reference).
"""

from __future__ import annotations

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
from app.models.studio import Character, CharacterImage, FileItem, Scene, SceneImage

if TYPE_CHECKING:
    from app.agents.core import AgentContext

logger = logging.getLogger(__name__)

STYLE_LOCK = (
    "Real photo texture, matte material, no CGI, no retouching, "
    "9:16 portrait, simple grey background, soft neutral studio lighting, "
    "professional commercial portrait photography, cinematic quality."
)


class GenerateAssetRefsInput(BaseModel):
    asset_type: str = Field(
        default="character",
        description="character or scene",
    )
    asset_ids: list[str] = Field(
        default_factory=list,
        description="specific asset IDs; empty = all assets for project",
    )


class GenerateAssetRefsTool(Tool):
    name = "generate_asset_refs"
    description = (
        "Auto-generate reference images for all characters or scenes. "
        "Uses text-to-image with style locking. Results saved to character_images/scene_images."
    )
    input_model = GenerateAssetRefsInput

    async def execute(self, ctx: AgentContext, **kwargs) -> dict:
        data = GenerateAssetRefsInput(**kwargs)
        async with async_session_maker() as db:
            api_key, base_url, model_name = await get_image_api_config(db)

            if data.asset_type == "character":
                return await self._gen_character_refs(db, ctx, api_key, base_url, model_name, data.asset_ids)
            elif data.asset_type == "scene":
                return await self._gen_scene_refs(db, ctx, api_key, base_url, model_name, data.asset_ids)
            else:
                return {"error": "asset_type must be 'character' or 'scene'"}

    async def _gen_character_refs(self, db, ctx, api_key, base_url, model_name, asset_ids):
        stmt = select(Character).where(Character.project_id == ctx.project_id)
        if asset_ids:
            stmt = stmt.where(Character.id.in_(asset_ids))
        stmt = stmt.order_by(Character.created_at)
        characters = (await db.execute(stmt)).scalars().all()

        results = []
        for char in characters:
            # Skip if already has a reference image
            existing = (await db.execute(
                select(CharacterImage.file_id).where(
                    CharacterImage.character_id == char.id,
                    CharacterImage.file_id.isnot(None),
                ).limit(1)
            )).first()
            if existing:
                results.append({"character_id": char.id, "name": char.name, "status": "skipped", "reason": "already has ref"})
                continue

            # Build prompt from character description
            desc = char.description or char.name
            prompt = "%s. %s" % (desc, STYLE_LOCK)

            try:
                img_url = await direct_image_generate(api_key, base_url, model_name, prompt, size="1024x1024")
                file_id = await save_image_to_db(db, img_url, "char-ref-%s" % char.name, "generated-images/character-refs")
                db.add(CharacterImage(
                    character_id=char.id,
                    file_id=file_id,
                    quality_level="standard",
                    view_angle="front",
                    format="png",
                    is_primary=True,
                ))
                await db.commit()
                results.append({"character_id": char.id, "name": char.name, "file_id": file_id, "status": "ok"})
            except Exception as e:
                results.append({"character_id": char.id, "name": char.name, "status": "error", "error": str(e)[:150]})

        ok = sum(1 for r in results if r.get("status") == "ok")
        return {"asset_type": "character", "total": len(characters), "generated": ok, "results": results}

    async def _gen_scene_refs(self, db, ctx, api_key, base_url, model_name, asset_ids):
        stmt = select(Scene).where(Scene.project_id == ctx.project_id)
        if asset_ids:
            stmt = stmt.where(Scene.id.in_(asset_ids))
        stmt = stmt.order_by(Scene.created_at)
        scenes = (await db.execute(stmt)).scalars().all()

        results = []
        for scene in scenes:
            existing = (await db.execute(
                select(SceneImage.file_id).where(
                    SceneImage.scene_id == scene.id,
                    SceneImage.file_id.isnot(None),
                ).limit(1)
            )).first()
            if existing:
                results.append({"scene_id": scene.id, "name": scene.name, "status": "skipped", "reason": "already has ref"})
                continue

            desc = scene.description or scene.name
            prompt = "%s. 16:9 cinematic scene, wide angle, realistic photo texture, no CGI." % desc

            try:
                img_url = await direct_image_generate(api_key, base_url, model_name, prompt, size="1920x1080")
                file_id = await save_image_to_db(db, img_url, "scene-ref-%s" % scene.name, "generated-images/scene-refs")
                db.add(SceneImage(
                    scene_id=scene.id,
                    file_id=file_id,
                    quality_level="standard",
                    view_angle="front",
                    format="png",
                ))
                await db.commit()
                results.append({"scene_id": scene.id, "name": scene.name, "file_id": file_id, "status": "ok"})
            except Exception as e:
                results.append({"scene_id": scene.id, "name": scene.name, "status": "error", "error": str(e)[:150]})

        ok = sum(1 for r in results if r.get("status") == "ok")
        return {"asset_type": "scene", "total": len(scenes), "generated": ok, "results": results}
