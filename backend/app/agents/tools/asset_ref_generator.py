"""GenerateAssetRefsTool: thin wrapper calling asset_orchestrator service.

Architecture layers (fixes #8 module layering):
- Standard layer: prompt_templates DB table + ASSET_REFERENCE_STANDARDS.md
- Orchestration layer: app/services/studio/asset_orchestrator.py
- API adapter layer: app/services/studio/image_task_adapter.py + direct_api.py
  (with task tracking, fixes #9 Route B bypass)
- Storage layer: app/services/studio/file_lifecycle.py
- Validation layer: tests/test_asset_standards.py
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.agents.tools.base import Tool
from app.agents.tools.direct_api import get_image_api_config
from app.core.db import async_session_maker
from app.services.studio.asset_orchestrator import (
    _get_prompt_templates,
    generate_character_refs,
    generate_scene_refs,
    generate_prop_refs,
    generate_costume_refs,
)

if TYPE_CHECKING:
    from app.agents.core import AgentContext

logger = logging.getLogger(__name__)


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
            "character": generate_character_refs,
            "scene": generate_scene_refs,
            "prop": generate_prop_refs,
            "costume": generate_costume_refs,
        }
        handler = handlers.get(data.asset_type)
        if not handler:
            return {"error": "asset_type must be character/scene/prop/costume"}
        return await handler(
            ctx, api_key, base_url, model_name, templates, data.asset_ids, data.force
        )
