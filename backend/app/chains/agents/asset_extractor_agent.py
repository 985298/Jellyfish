"""Phase 1: Decoupled agents for asset extraction and shot binding."""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import PromptTemplate

from app.chains.agents.base import AgentBase
from app.schemas.skills.script_processing import AssetExtractionResult, ShotBindingResult


# === AssetExtractorAgent: extracts project-level assets from script text ===

_ASSET_EXTRACTOR_SYSTEM_PROMPT = """\
You are a script asset extractor. Your task: analyze the full script text and extract ALL unique characters, scenes, props, and costumes as a project-level asset library.

Output AssetExtractionResult (JSON only):
- project_id (required)
- characters: [{name, description, costume_name?, prop_names[], tags[]}]
- scenes: [{name, description, tags[], view_count}]
- props: [{name, description, tags[], view_count}]
- costumes: [{name, description, tags[], view_count}]

Rules:
- Extract ALL unique entities from the ENTIRE script, not per-scene
- Same entity appears only once (global deduplication)
- Do NOT output any shots or shot-level bindings
- Do NOT output any id fields (backend generates them)
- Character names must preserve exact text: full-width/half-width brackets, spaces, punctuation
- For group characters (e.g. "guests", "crowd"), create one entry with that exact name
- description should be concise: appearance, clothing, key traits for characters; location, atmosphere for scenes
- view_count: default 1

Input:
- project_id
- script_text

Output JSON only.
"""

_ASSET_EXTRACTOR_PROMPT = PromptTemplate(
    input_variables=["project_id", "script_text"],
    template=(
        "## project_id\n{project_id}\n\n"
        "## Script Text\n{script_text}\n\n"
        "## Output\n"
    ),
)


class AssetExtractorAgent(AgentBase[AssetExtractionResult]):
    """Extracts project-level assets from script text (no division needed)."""

    @property
    def system_prompt(self) -> str:
        return _ASSET_EXTRACTOR_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return _ASSET_EXTRACTOR_PROMPT

    @property
    def output_model(self) -> type[AssetExtractionResult]:
        return AssetExtractionResult

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        data.setdefault("project_id", "")
        for k in ("characters", "scenes", "props", "costumes"):
            if k not in data or not isinstance(data[k], list):
                data[k] = []
        return data


# === ShotBinderAgent: binds existing assets to shots based on division ===

_SHOT_BINDER_SYSTEM_PROMPT = """\
You are a shot asset binder. Given the storyboard division and a list of existing project assets, your task: for each shot, specify which assets appear.

Output ShotBindingResult (JSON only):
- chapter_id (required)
- shots: [{index, scene_name?, character_names[], prop_names[], costume_names[]}]

CRITICAL constraint:
- character_names / prop_names / costume_names / scene_name MUST ONLY use names from the provided asset list
- Do NOT create new assets. Do NOT invent names not in the asset list
- If a shot mentions a character not in the asset list, omit that character (do not create new)
- If unsure whether an asset appears in a shot, include it (better to over-bind than miss)
- index must match the division shots index exactly

Input:
- chapter_id
- script_division_json (the division result with shots)
- asset_list_json (existing assets: characters, scenes, props, costumes with their names)

Output JSON only.
"""

_SHOT_BINDER_PROMPT = PromptTemplate(
    input_variables=["chapter_id", "script_division_json", "asset_list_json"],
    template=(
        "## chapter_id\n{chapter_id}\n\n"
        "## Division\n{script_division_json}\n\n"
        "## Existing Assets\n{asset_list_json}\n\n"
        "## Output\n"
    ),
)


class ShotBinderAgent(AgentBase[ShotBindingResult]):
    """Binds existing project assets to shots (requires division + asset list)."""

    @property
    def system_prompt(self) -> str:
        return _SHOT_BINDER_SYSTEM_PROMPT

    @property
    def prompt_template(self) -> PromptTemplate:
        return _SHOT_BINDER_PROMPT

    @property
    def output_model(self) -> type[ShotBindingResult]:
        return ShotBindingResult

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data)
        data.setdefault("chapter_id", "")
        if "shots" not in data or not isinstance(data["shots"], list):
            data["shots"] = []
        return data
