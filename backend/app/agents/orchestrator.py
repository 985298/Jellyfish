"""Orchestrator: Python deterministic state machine, no LLM for orchestration decisions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from app.agents.core import AgentContext, AgentResult

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict], None]


class Orchestrator:
    """One-click production orchestrator using a deterministic state machine."""

    STAGES: list[tuple[str, str]] = [
        ("build_assets", "character_designer"),
        ("extract_shots", "storyboard"),
        ("bind_assets", "storyboard"),
        ("generate_frames", "production"),
        ("generate_videos", "production"),
    ]

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self.agents: dict[str, object] = {}

    def _get_agent(self, name: str) -> object:
        if name not in self.agents:
            from app.agents.specialists import create_agent_with_tools
            self.agents[name] = create_agent_with_tools(name, self.llm)
        return self.agents[name]

    async def run(
        self,
        goal: str,
        ctx: AgentContext,
        on_progress: ProgressCallback | None = None,
    ) -> list[AgentResult]:
        results: list[AgentResult] = []
        for stage_name, agent_name in self.STAGES:
            if on_progress:
                on_progress({"stage": stage_name, "status": "running"})
            agent = self._get_agent(agent_name)
            try:
                result = await agent.run(ctx, f"执行阶段：{stage_name}。目标：{goal}")
                results.append(result)
                if result.status == "error":
                    if on_progress:
                        on_progress({"stage": stage_name, "status": "error", "error": result.output})
                    break
                if on_progress:
                    on_progress({"stage": stage_name, "status": "completed", "output": result.output})
            except Exception as e:
                logger.exception("Stage %s failed", stage_name)
                results.append(AgentResult(status="error", output=str(e)))
                if on_progress:
                    on_progress({"stage": stage_name, "status": "error", "error": str(e)})
                break
        return results
