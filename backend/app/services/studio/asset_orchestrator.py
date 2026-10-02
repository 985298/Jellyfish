"""Asset orchestration layer: coordinates parallel image generation.

Reads prompt templates from DB, queries assets, generates in parallel
using image_task_adapter (with task tracking), uses file_lifecycle for cleanup.
This fixes module layering (#8) — tool is now a thin wrapper.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.core.db import async_session_maker
from app.models.studio import (
    Character, CharacterImage, Costume, CostumeImage,
    Prop, PropImage, Scene, SceneImage,
)
from app.models.studio_prompts_files_timeline import PromptTemplate
from app.services.studio.file_lifecycle import delete_image_with_file
from app.services.studio.image_task_adapter import generate_image_tracked

logger = logging.getLogger(__name__)
_CONCURRENCY = 8

_SIZES = {
    "character": "2048x1152",
    "scene": "1152x2048",
    "prop": "2048x2048",
    "costume": "2048x2048",
}
_POS_CATEGORIES = {
    "character": "character_image_front",
    "scene": "scene_image_front",
    "prop": "prop_image_front",
    "costume": "costume_image_front",
}
_NEG_CATEGORIES = {
    "character": "character_image_negative",
    "scene": "scene_image_negative",
    "prop": "prop_image_negative",
    "costume": "costume_image_negative",
}


async def _get_prompt_templates(db) -> dict:
    rows = (await db.execute(
        select(PromptTemplate.category, PromptTemplate.content)
    )).all()
    return {r[0]: r[1] for r in rows}


def _build_prompt(template: str, desc: str) -> str:
    if "%s" in template:
        return template.replace("%s", desc)
    return template + " " + desc if desc else template


# === Per-item generation (each creates own session + task) ===

async def _gen_one_char(ctx, api_key, base_url, model_name, templates, char, costume, is_primary, force):
    async with async_session_maker() as db:
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
            return {"character_id": char.id, "name": char.name, "state": state_label, "status": "skipped"}

        if existing and force:
            await delete_image_with_file(db, CharacterImage, existing)
            await db.flush()

        desc = char.description or char.name
        if costume and costume.description:
            desc = desc + " Outfit: " + costume.description
        prompt = _build_prompt(templates.get("character_image_front", ""), desc)
        neg = templates.get("character_image_negative", "")

    result = await generate_image_tracked(
        api_key, base_url, model_name, prompt,
        _SIZES["character"], neg,
        ctx.project_id, "character", char.id,
        "char-ref-%s-%s" % (char.name, state_label),
        "generated-images/character-refs",
    )
    if result.get("status") == "ok":
        async with async_session_maker() as db:
            db.add(CharacterImage(
                character_id=char.id,
                file_id=result["file_id"],
                quality_level="standard",
                view_angle="front",
                format="png",
                is_primary=is_primary,
                costume_id=costume.id if costume else None,
            ))
            await db.commit()
    result["name"] = char.name
    result["state"] = state_label
    return result


async def _gen_one_scene(ctx, api_key, base_url, model_name, templates, scene, force):
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
        prompt = _build_prompt(templates.get("scene_image_front", ""), desc)
        neg = templates.get("scene_image_negative", "")

    result = await generate_image_tracked(
        api_key, base_url, model_name, prompt,
        _SIZES["scene"], neg,
        ctx.project_id, "scene", scene.id,
        "scene-ref-%s" % scene.name,
        "generated-images/scene-refs",
    )
    if result.get("status") == "ok":
        async with async_session_maker() as db:
            db.add(SceneImage(
                scene_id=scene.id,
                file_id=result["file_id"],
                quality_level="standard",
                view_angle="front",
                format="png",
            ))
            await db.commit()
    result["name"] = scene.name
    return result


async def _gen_one_prop(ctx, api_key, base_url, model_name, templates, prop, force):
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
        prompt = _build_prompt(templates.get("prop_image_front", ""), desc)
        neg = templates.get("prop_image_negative", "")

    result = await generate_image_tracked(
        api_key, base_url, model_name, prompt,
        _SIZES["prop"], neg,
        ctx.project_id, "prop", prop.id,
        "prop-ref-%s" % prop.name,
        "generated-images/prop-refs",
    )
    if result.get("status") == "ok":
        async with async_session_maker() as db:
            db.add(PropImage(
                prop_id=prop.id,
                file_id=result["file_id"],
                quality_level="standard",
                view_angle="front",
                format="png",
            ))
            await db.commit()
    result["name"] = prop.name
    return result


async def _gen_one_costume(ctx, api_key, base_url, model_name, templates, costume, force):
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
        prompt = _build_prompt(templates.get("costume_image_front", ""), desc)
        neg = templates.get("costume_image_negative", "")

    result = await generate_image_tracked(
        api_key, base_url, model_name, prompt,
        _SIZES["costume"], neg,
        ctx.project_id, "costume", costume.id,
        "costume-ref-%s" % costume.name,
        "generated-images/costume-refs",
    )
    if result.get("status") == "ok":
        async with async_session_maker() as db:
            db.add(CostumeImage(
                costume_id=costume.id,
                file_id=result["file_id"],
                quality_level="standard",
                view_angle="front",
                format="png",
            ))
            await db.commit()
    result["name"] = costume.name
    return result


# === Batch orchestrators (query assets, then parallel generate) ===

async def generate_character_refs(ctx, api_key, base_url, model_name, templates, asset_ids, force):
    async with async_session_maker() as db:
        stmt = select(Character).where(Character.project_id == ctx.project_id).order_by(Character.created_at)
        if asset_ids:
            stmt = stmt.where(Character.id.in_(asset_ids))
        characters = (await db.execute(stmt)).scalars().all()
        costumes = (await db.execute(
            select(Costume).where(Costume.project_id == ctx.project_id)
        )).scalars().all()

    tasks = []
    for char in characters:
        char_costumes = [c for c in costumes if c.character_id == char.id]
        if not char_costumes:
            char_costumes = [c for c in costumes if char.name in c.name]
        if char_costumes and len(char_costumes) > 1:
            for idx, costume in enumerate(char_costumes):
                tasks.append(_gen_one_char(ctx, api_key, base_url, model_name, templates, char, costume, idx == 0, force))
        else:
            costume = char_costumes[0] if char_costumes else None
            tasks.append(_gen_one_char(ctx, api_key, base_url, model_name, templates, char, costume, True, force))

    sem = asyncio.Semaphore(_CONCURRENCY)
    async def limited(t):
        async with sem:
            return await t
    results = await asyncio.gather(*[limited(t) for t in tasks])
    ok = sum(1 for r in results if r.get("status") == "ok")
    return {"asset_type": "character", "total": len(results), "generated": ok, "results": list(results)}


async def generate_scene_refs(ctx, api_key, base_url, model_name, templates, asset_ids, force):
    async with async_session_maker() as db:
        stmt = select(Scene).where(Scene.project_id == ctx.project_id).order_by(Scene.created_at)
        if asset_ids:
            stmt = stmt.where(Scene.id.in_(asset_ids))
        scenes = (await db.execute(stmt)).scalars().all()
    sem = asyncio.Semaphore(_CONCURRENCY)
    async def limited(s):
        async with sem:
            return await _gen_one_scene(ctx, api_key, base_url, model_name, templates, s, force)
    results = await asyncio.gather(*[limited(s) for s in scenes])
    ok = sum(1 for r in results if r.get("status") == "ok")
    return {"asset_type": "scene", "total": len(scenes), "generated": ok, "results": list(results)}


async def generate_prop_refs(ctx, api_key, base_url, model_name, templates, asset_ids, force):
    async with async_session_maker() as db:
        stmt = select(Prop).where(Prop.project_id == ctx.project_id).order_by(Prop.created_at)
        if asset_ids:
            stmt = stmt.where(Prop.id.in_(asset_ids))
        props = (await db.execute(stmt)).scalars().all()
    sem = asyncio.Semaphore(_CONCURRENCY)
    async def limited(p):
        async with sem:
            return await _gen_one_prop(ctx, api_key, base_url, model_name, templates, p, force)
    results = await asyncio.gather(*[limited(p) for p in props])
    ok = sum(1 for r in results if r.get("status") == "ok")
    return {"asset_type": "prop", "total": len(props), "generated": ok, "results": list(results)}


async def generate_costume_refs(ctx, api_key, base_url, model_name, templates, asset_ids, force):
    async with async_session_maker() as db:
        stmt = select(Costume).where(Costume.project_id == ctx.project_id).order_by(Costume.created_at)
        if asset_ids:
            stmt = stmt.where(Costume.id.in_(asset_ids))
        costumes = (await db.execute(stmt)).scalars().all()
    sem = asyncio.Semaphore(_CONCURRENCY)
    async def limited(c):
        async with sem:
            return await _gen_one_costume(ctx, api_key, base_url, model_name, templates, c, force)
    results = await asyncio.gather(*[limited(c) for c in costumes])
    ok = sum(1 for r in results if r.get("status") == "ok")
    return {"asset_type": "costume", "total": len(costumes), "generated": ok, "results": list(results)}
