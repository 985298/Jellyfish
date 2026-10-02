"""Composition tools: film editing, BGM, subtitle burning."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.agents.tools.base import Tool
from app.core.db import async_session_maker

if TYPE_CHECKING:
    from app.agents.core import AgentContext

logger = logging.getLogger(__name__)


class ComposeFilmInput(BaseModel):
    chapter_id: str = Field(description="chapter ID to compose")
    bgm_path: str | None = Field(default=None, description="path to BGM audio file (optional)")


class ComposeFilmTool(Tool):
    name = "compose_film"
    description = (
        "Compose final film: concatenate all shot videos, burn subtitles, add BGM. "
        "Returns path to final MP4 file."
    )
    input_model = ComposeFilmInput

    async def execute(self, ctx: "AgentContext", **kwargs) -> dict:
        from app.services.film.composition import compose_film
        data = ComposeFilmInput(**kwargs)
        try:
            final_path = await compose_film(data.chapter_id, bgm_path=data.bgm_path)
            return {
                "status": "ok",
                "final_video_path": final_path,
                "chapter_id": data.chapter_id,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)[:300], "chapter_id": data.chapter_id}


class GenerateBgmInput(BaseModel):
    mood: str = Field(default="dramatic", description="music mood: dramatic / sad / upbeat / tense")
    duration: int = Field(default=120, description="target duration in seconds")


class GenerateBgmTool(Tool):
    name = "generate_bgm"
    description = "Generate background music (placeholder - uses local music library or API)"
    input_model = GenerateBgmInput

    async def execute(self, ctx: "AgentContext", **kwargs) -> dict:
        # Placeholder: in production, this would call an audio generation API
        # For now, return a placeholder path
        return {
            "status": "placeholder",
            "message": "BGM generation not yet implemented. Use compose_film with bgm_path=None to skip BGM.",
            "bgm_path": None,
        }
