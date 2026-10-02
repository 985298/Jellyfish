"""给 Celery worker 使用的同步任务执行服务。"""

from __future__ import annotations

import json
import logging
import uuid as _uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.chains.agents import ScriptDividerAgent
from app.chains.agents import (
    CharacterPortraitAnalysisAgent,
    ConsistencyCheckerAgent,
    CostumeInfoAnalysisAgent,
    PropInfoAnalysisAgent,
    SceneInfoAnalysisAgent,
    ScriptOptimizerAgent,
    ScriptSimplifierAgent,
)
from app.chains.agents.asset_extractor_agent import AssetExtractorAgent, ShotBinderAgent
from app.chains.agents.script_processing_agents import (
    ScriptConsistencyCheckResult,
    ScriptDivisionResult,
    ScriptOptimizationResult,
    ScriptSimplificationResult,
)
from app.core.db_sync import sync_session_maker
from app.models.studio import (
    Character,
    Chapter,
    Costume,
    Project,
    ProjectStyle,
    ProjectVisualStyle,
    Prop,
    Scene,
    Shot,
    ShotCharacterLink,
    ShotExtractedCandidate,
)
from app.models.types import ShotCandidateStatus, ShotCandidateType
from app.services.llm.runtime import build_default_text_llm_sync
from app.services.studio.script_division import write_division_result_to_chapter_sync
from app.services.worker.task_executor import (
    AbstractLLMResultGenerator,
    AbstractWorkerTaskExecutor,
    WorkerTaskContext,
)


logger = logging.getLogger(__name__)


# === LLM Result Generators ===


class DivideResultGenerator(AbstractLLMResultGenerator):
    thinking = False

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> ScriptDivisionResult:
        agent = ScriptDividerAgent(llm)
        project_id = str(run_args.get("project_id") or "")
        asset_list = ""
        if project_id:
            from app.core.db_sync import sync_session_maker
            from app.services.studio.script_division import build_asset_list_text_sync
            with sync_session_maker() as _db:
                asset_list = build_asset_list_text_sync(_db, project_id)
        return agent.divide_script(script_text=str(run_args.get("script_text") or ""), asset_list=asset_list)


class ConsistencyResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> ScriptConsistencyCheckResult:
        agent = ConsistencyCheckerAgent(llm)
        return agent.extract(script_text=str(run_args.get("script_text") or ""))


class CharacterPortraitResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = CharacterPortraitAnalysisAgent(llm)
        return agent.analyze_character_description(
            character_context=run_args.get("character_context"),
            character_description=str(run_args.get("character_description") or ""),
        )


class PropInfoResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = PropInfoAnalysisAgent(llm)
        return agent.analyze_prop_description(
            prop_context=run_args.get("prop_context"),
            prop_description=str(run_args.get("prop_description") or ""),
        )


class SceneInfoResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = SceneInfoAnalysisAgent(llm)
        return agent.analyze_scene_description(
            scene_context=run_args.get("scene_context"),
            scene_description=str(run_args.get("scene_description") or ""),
        )


class CostumeInfoResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = CostumeInfoAnalysisAgent(llm)
        return agent.analyze_costume_description(
            costume_context=run_args.get("costume_context"),
            costume_description=str(run_args.get("costume_description") or ""),
        )


class ScriptOptimizationResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> ScriptOptimizationResult:
        agent = ScriptOptimizerAgent(llm)
        return agent.extract(
            script_text=str(run_args.get("script_text") or ""),
            consistency_json=json.dumps(dict(run_args.get("consistency") or {}), ensure_ascii=False),
        )


class ScriptSimplificationResultGenerator(AbstractLLMResultGenerator):
    thinking = True

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> ScriptSimplificationResult:
        agent = ScriptSimplifierAgent(llm)
        return agent.extract(script_text=str(run_args.get("script_text") or ""))


# === Phase 3: Asset extraction + binding generators ===


class AssetExtractResultGenerator(AbstractLLMResultGenerator):
    """Generates project-level assets from script text (no division needed)."""

    thinking = False

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = AssetExtractorAgent(llm)
        return agent.extract(
            project_id=str(run_args.get("project_id") or ""),
            script_text=str(run_args.get("script_text") or ""),
        )


class AssetBindResultGenerator(AbstractLLMResultGenerator):
    """Binds existing project assets to shots using ShotBinderAgent."""

    thinking = False

    def generate_with_llm(self, llm, run_args: dict[str, Any]) -> Any:
        agent = ShotBinderAgent(llm)
        return agent.extract(
            chapter_id=str(run_args.get("chapter_id") or ""),
            script_division_json=str(run_args.get("script_division_json") or ""),
            asset_list_json=str(run_args.get("asset_list_json") or ""),
        )


# === Task Executors ===


class DivideTaskExecutor(AbstractWorkerTaskExecutor):
    task_kind = "script_divide"
    timeout_seconds = 1800.0

    def __init__(self) -> None:
        super().__init__(session_maker=sync_session_maker)
        self._generator = DivideResultGenerator()

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> ScriptDivisionResult:
        return self._generator.generate(ctx.db, run_args)

    def should_apply(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: ScriptDivisionResult) -> bool:  # noqa: ARG002
        return bool(run_args.get("write_to_db"))

    def apply_result(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: ScriptDivisionResult) -> None:
        chapter_id = str(run_args.get("chapter_id") or "")
        if not chapter_id:
            raise HTTPException(status_code=400, detail="chapter_id is required for write_to_db=true")
        apply_division_result(ctx.db, chapter_id=chapter_id, result=result)


class ConsistencyTaskExecutor(AbstractWorkerTaskExecutor):
    task_kind = "script_consistency"
    succeeded_progress = 100
    timeout_seconds = 300.0

    def __init__(self) -> None:
        super().__init__(session_maker=sync_session_maker)
        self._generator = ConsistencyResultGenerator()

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> ScriptConsistencyCheckResult:
        return self._generator.generate(ctx.db, run_args)


class _SimpleLLMTaskExecutor(AbstractWorkerTaskExecutor):
    succeeded_progress = 100
    timeout_seconds = 300.0
    generator_class: type[AbstractLLMResultGenerator]

    def __init__(self) -> None:
        super().__init__(session_maker=sync_session_maker)
        self._generator = self.generator_class()

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> Any:
        return self._generator.generate(ctx.db, run_args)


class CharacterPortraitTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_character_portrait"
    generator_class = CharacterPortraitResultGenerator


class PropInfoTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_prop_info"
    generator_class = PropInfoResultGenerator


class SceneInfoTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_scene_info"
    generator_class = SceneInfoResultGenerator


class CostumeInfoTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_costume_info"
    generator_class = CostumeInfoResultGenerator


class ScriptOptimizationTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_optimize"
    generator_class = ScriptOptimizationResultGenerator


class ScriptSimplificationTaskExecutor(_SimpleLLMTaskExecutor):
    task_kind = "script_simplify"
    generator_class = ScriptSimplificationResultGenerator


# === Phase 3: Asset extraction + binding executors ===


def _default_style_for_project(db: Session, project_id: str) -> tuple[str, str]:
    """Resolve (style, visual_style) for a project, falling back to defaults."""
    project = db.get(Project, project_id)
    if project is not None:
        return (
            str(getattr(project, "style", None) or ProjectStyle.real_people_city.value),
            str(getattr(project, "visual_style", None) or ProjectVisualStyle.live_action.value),
        )
    return ProjectStyle.real_people_city.value, ProjectVisualStyle.live_action.value


def _existing_character_id_by_name(db: Session, *, project_id: str, name: str) -> str | None:
    stmt = select(Character.id).where(
        Character.project_id == project_id,
        Character.name == name,
    ).limit(1)
    row = db.execute(stmt).scalar_one_or_none()
    return str(row) if row is not None else None


def _existing_asset_id_by_name(db: Session, *, model: type, name: str) -> str | None:
    stmt = select(model.id).where(model.name == name).limit(1)
    row = db.execute(stmt).scalar_one_or_none()
    return str(row) if row is not None else None


def _ensure_asset_project_id(
    db: Session,
    *,
    model: type,
    asset_id: str,
    project_id: str,
) -> None:
    """Idempotently ensure an asset row carries this project_id.

    Phase 3：中间表 project_scene_links / project_prop_links / project_costume_links
    已删除，改为直接维护 Scene/Prop/Costume.project_id。
    """
    stmt = select(model.id).where(
        model.id == asset_id,
        model.project_id == project_id,
    ).limit(1)
    existing = db.execute(stmt).scalar_one_or_none()
    if existing is not None:
        return
    asset = db.get(model, asset_id)
    if asset is None:
        return
    asset.project_id = project_id
    db.flush()


class AssetExtractTaskExecutor(AbstractWorkerTaskExecutor):
    """Extracts project-level assets (characters/scenes/props/costumes) from script text.

    Phase 3: decoupled from script division. Runs against the full script text and
    persists a project-level asset library. No shots or bindings are produced here.
    """

    task_kind = "script_asset_extract"
    timeout_seconds = 600.0
    succeeded_progress = 100

    def __init__(self) -> None:
        super().__init__(session_maker=sync_session_maker)
        self._generator = AssetExtractResultGenerator()

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> Any:
        return self._generator.generate(ctx.db, run_args)

    def should_apply(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: Any) -> bool:  # noqa: ARG002
        return bool(run_args.get("project_id"))

    def apply_result(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: Any) -> None:
        project_id = str(run_args.get("project_id") or "")
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required for script_asset_extract")

        if project_id != getattr(result, "project_id", project_id):
            # Trust the agent's result project_id if present; keep run_args as fallback.
            pass

        style, visual_style = _default_style_for_project(ctx.db, project_id)
        ctx.db.flush()

        created_counts = {"character": 0, "scene": 0, "prop": 0, "costume": 0}

        # Characters: backend-owned id; idempotent by (project_id, name).
        for char in list(getattr(result, "characters", []) or []):
            name = str(getattr(char, "name", "") or "").strip()
            if not name:
                continue
            try:
                existing_id = _existing_character_id_by_name(ctx.db, project_id=project_id, name=name)
                if existing_id is not None:
                    continue
                description = str(getattr(char, "description", "") or "")
                ctx.db.add(
                    Character(
                        id=f"char_{_uuid.uuid4().hex[:12]}",
                        project_id=project_id,
                        name=name,
                        description=description,
                        style=style,
                        visual_style=visual_style,
                        actor_id=None,
                        costume_id=None,
                    )
                )
                ctx.db.flush()
                created_counts["character"] += 1
            except Exception:
                logger.exception("asset_extract: failed to persist character %r for project %s", name, project_id)

        # Assets: scene/prop/costume share the same shape; idempotent by name (global unique).
        # Phase 3：中间表 project_scene_links / project_prop_links / project_costume_links 已删除，
        # 改为直接写 Scene/Prop/Costume.project_id（不再通过 link_model 旁挂）。
        asset_specs = (
            (Scene, "scene"),
            (Prop, "prop"),
            (Costume, "costume"),
        )
        for model, label in asset_specs:
            items = list(getattr(result, f"{label}s", []) or [])
            for item in items:
                name = str(getattr(item, "name", "") or "").strip()
                if not name:
                    continue
                try:
                    existing_id = _existing_asset_id_by_name(ctx.db, model=model, name=name)
                    if existing_id is not None:
                        # Ensure the existing asset is linked to this project.
                        _ensure_asset_project_id(
                            ctx.db,
                            model=model,
                            asset_id=existing_id,
                            project_id=project_id,
                        )
                        continue
                    description = str(getattr(item, "description", "") or "")
                    tags = list(getattr(item, "tags", []) or [])
                    view_count = int(getattr(item, "view_count", 1) or 1)
                    if view_count < 1:
                        view_count = 1
                    asset_id = f"{label}_{_uuid.uuid4().hex[:12]}"
                    ctx.db.add(
                        model(
                            id=asset_id,
                            name=name,
                            description=description,
                            style=style,
                            visual_style=visual_style,
                            tags=tags,
                            view_count=view_count,
                            prompt_template_id=None,
                            project_id=project_id,
                        )
                    )
                    ctx.db.flush()
                    created_counts[label] += 1
                except Exception:
                    logger.exception("asset_extract: failed to persist %s %r for project %s", label, name, project_id)

        ctx.db.commit()
        logger.info(
            "asset_extract applied: project_id=%s created=%s",
            project_id,
            created_counts,
        )


class AssetBindTaskExecutor(AbstractWorkerTaskExecutor):
    """Binds existing project assets to shots based on script division.

    Phase 3: consumes the division result + an asset list, resolves each named
    asset to its stable entity id, and persists shot-level bindings (ShotCharacterLink
    + ShotExtractedCandidate linked state). Does NOT create new assets.
    """

    task_kind = "script_asset_bind"
    timeout_seconds = 300.0
    succeeded_progress = 100

    def __init__(self) -> None:
        super().__init__(session_maker=sync_session_maker)
        self._generator = AssetBindResultGenerator()

    def execute(self, ctx: WorkerTaskContext, run_args: dict[str, Any]) -> Any:
        return self._generator.generate(ctx.db, run_args)

    def should_apply(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: Any) -> bool:  # noqa: ARG002
        return bool(run_args.get("chapter_id"))

    def apply_result(self, ctx: WorkerTaskContext, run_args: dict[str, Any], result: Any) -> None:
        chapter_id = str(run_args.get("chapter_id") or "")
        if not chapter_id:
            raise HTTPException(status_code=400, detail="chapter_id is required for script_asset_bind")

        chapter = ctx.db.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=400, detail="Chapter not found")
        project_id = str(chapter.project_id)

        shots = list(
            ctx.db.execute(
                select(Shot).where(Shot.chapter_id == chapter_id)
            ).scalars().all()
        )
        shot_by_index: dict[int, Shot] = {shot.index: shot for shot in shots}

        # Pre-resolve asset name -> id maps scoped to this project / global table.
        def _resolve_character(name: str) -> str | None:
            return _existing_character_id_by_name(ctx.db, project_id=project_id, name=name)

        def _resolve_asset(model: type, name: str) -> str | None:
            return _existing_asset_id_by_name(ctx.db, model=model, name=name)

        bound_counts = {"character": 0, "scene": 0, "prop": 0, "costume": 0}

        for shot_binding in list(getattr(result, "shots", []) or []):
            index = getattr(shot_binding, "index", None)
            shot = shot_by_index.get(int(index)) if index is not None else None
            if shot is None:
                continue

            # Characters: upsert ShotCharacterLink + mark candidate linked.
            character_names = [str(n).strip() for n in (getattr(shot_binding, "character_names", []) or []) if str(n).strip()]
            existing_link_char_ids = {
                str(row[0])
                for row in ctx.db.execute(
                    select(ShotCharacterLink.character_id).where(ShotCharacterLink.shot_id == shot.id)
                ).all()
            }
            next_index = (
                int(
                    ctx.db.execute(
                        select(ShotCharacterLink.index)
                        .where(ShotCharacterLink.shot_id == shot.id)
                        .order_by(ShotCharacterLink.index.desc())
                        .limit(1)
                    ).scalar() or 0
                )
            )
            for name in character_names:
                char_id = _resolve_character(name)
                if char_id is None:
                    continue
                if char_id in existing_link_char_ids:
                    bound_counts["character"] += 1
                    continue
                next_index += 1
                ctx.db.add(
                    ShotCharacterLink(
                        shot_id=shot.id,
                        character_id=char_id,
                        index=next_index,
                        note="",
                    )
                )
                bound_counts["character"] += 1
            ctx.db.flush()

            # Scene / prop / costume: mark ShotExtractedCandidate linked by name.
            scene_name = getattr(shot_binding, "scene_name", None)
            if scene_name:
                scene_name = str(scene_name).strip()
                if scene_name:
                    scene_id = _resolve_asset(Scene, scene_name)
                    self._mark_candidate_linked(
                        ctx.db, shot_id=shot.id, candidate_type=ShotCandidateType.scene,
                        candidate_name=scene_name, linked_entity_id=scene_id,
                    )
                    bound_counts["scene"] += 1

            for name in (getattr(shot_binding, "prop_names", []) or []):
                name = str(name).strip()
                if not name:
                    continue
                prop_id = _resolve_asset(Prop, name)
                self._mark_candidate_linked(
                    ctx.db, shot_id=shot.id, candidate_type=ShotCandidateType.prop,
                    candidate_name=name, linked_entity_id=prop_id,
                )
                bound_counts["prop"] += 1

            for name in (getattr(shot_binding, "costume_names", []) or []):
                name = str(name).strip()
                if not name:
                    continue
                costume_id = _resolve_asset(Costume, name)
                self._mark_candidate_linked(
                    ctx.db, shot_id=shot.id, candidate_type=ShotCandidateType.costume,
                    candidate_name=name, linked_entity_id=costume_id,
                )
                bound_counts["costume"] += 1

        ctx.db.commit()
        logger.info(
            "asset_bind applied: chapter_id=%s bound=%s",
            chapter_id,
            bound_counts,
        )

    @staticmethod
    def _mark_candidate_linked(
        db: Session,
        *,
        shot_id: str,
        candidate_type: ShotCandidateType,
        candidate_name: str,
        linked_entity_id: str | None,
    ) -> None:
        """Mark a matching ShotExtractedCandidate as linked (if any). Idempotent / silent."""
        if not linked_entity_id:
            return
        stmt = (
            select(ShotExtractedCandidate)
            .where(ShotExtractedCandidate.shot_id == shot_id)
            .where(ShotExtractedCandidate.candidate_type == candidate_type)
            .where(ShotExtractedCandidate.candidate_name == candidate_name)
            .order_by(ShotExtractedCandidate.id.asc())
            .limit(1)
        )
        row = db.execute(stmt).scalars().first()
        if row is None:
            return
        row.candidate_status = ShotCandidateStatus.linked
        row.linked_entity_id = linked_entity_id
        from datetime import datetime, timezone
        row.confirmed_at = datetime.now(timezone.utc)


# === Sync helpers / public entry points ===


def generate_division_result(
    *,
    db: Session,
    script_text: str,
    project_id: str = "",
) -> ScriptDivisionResult:
    llm = build_default_text_llm_sync(db, thinking=False)
    agent = ScriptDividerAgent(llm)
    asset_list = ""
    if project_id:
        from app.services.studio.script_division import build_asset_list_text_sync
        asset_list = build_asset_list_text_sync(db, project_id)
    return agent.divide_script(script_text=script_text, asset_list=asset_list)


def apply_division_result(
    db: Session,
    *,
    chapter_id: str,
    result: ScriptDivisionResult,
) -> None:
    write_division_result_to_chapter_sync(db, chapter_id=chapter_id, result=result)


def run_divide_task_sync(task_id: str) -> None:
    DivideTaskExecutor().run(task_id)


def run_consistency_task_sync(task_id: str) -> None:
    ConsistencyTaskExecutor().run(task_id)


def run_character_portrait_task_sync(task_id: str) -> None:
    CharacterPortraitTaskExecutor().run(task_id)


def run_prop_info_task_sync(task_id: str) -> None:
    PropInfoTaskExecutor().run(task_id)


def run_scene_info_task_sync(task_id: str) -> None:
    SceneInfoTaskExecutor().run(task_id)


def run_costume_info_task_sync(task_id: str) -> None:
    CostumeInfoTaskExecutor().run(task_id)


def run_script_optimization_task_sync(task_id: str) -> None:
    ScriptOptimizationTaskExecutor().run(task_id)


def run_script_simplification_task_sync(task_id: str) -> None:
    ScriptSimplificationTaskExecutor().run(task_id)


def run_asset_extract_task_sync(task_id: str) -> None:
    """Phase 3 sync entry point for script_asset_extract tasks."""
    AssetExtractTaskExecutor().run(task_id)


def run_asset_bind_task_sync(task_id: str) -> None:
    """Phase 3 sync entry point for script_asset_bind tasks."""
    AssetBindTaskExecutor().run(task_id)
