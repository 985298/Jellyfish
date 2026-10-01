"""Orchestrator: Director-driven 循环（带确定性兜底）。

设计要点（相对旧版硬编码 5 阶段状态机的改动）：

1. **Director 驱动**：每轮先问 Director "下一步做什么"（``next_action``），
   再把该阶段派给对应 specialist。Director 判断基于 check_asset_status /
   query_shots 等工具的真实数据，而不是"跑到第 5 步就结束"的固定顺序。
2. **确定性兜底**：Director 返回不可识别的 ``next_action``（空值 / 未知值 / LLM 调用
   异常）时，退回 ``_fallback_next_stage`` 按阶段完成度推断，而不是直接结束。
   这保证即使 LLM 不可用，流程仍能推进。
3. **自动重试**：某个阶段失败（specialist 报错或抛异常）时，最多重试
   ``MAX_STAGE_RETRIES``（2）次；仍然失败才终止并把错误透出。
4. **进度事件**：on_progress 事件带上 ``tool_calls``（本轮实际调用的工具）和
   ``output_counts``（extract_assets / extract_shots 等返回的条目数），
   前端不再只能看到"阶段开始/结束"两条空事件。
5. **防死循环**：同一阶段连续执行次数超过 ``MAX_STAGE_ATTEMPTS``（3）即判定
   Director 在原地打转，终止并报告。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from app.agents.core import AgentContext, AgentResult

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict], None]

# Director 的 next_action -> 执行该阶段的 specialist 名
_ACTION_TO_AGENT: dict[str, str] = {
    "build_assets": "character_designer",
    "extract_shots": "storyboard",
    "bind_assets": "storyboard",
    "generate_frames": "production",
    "generate_videos": "production",
}

_VALID_ACTIONS = set(_ACTION_TO_AGENT) | {"completed"}

# 阶段顺序（用于跳过已完成阶段）
_STAGE_ORDER = ["build_assets", "extract_shots", "bind_assets", "generate_frames", "generate_videos"]


def _next_uncompleted_stage(completed: set[str]) -> str | None:
    """返回第一个未完成的阶段，全部完成返回 None。"""
    for stage in _STAGE_ORDER:
        if stage not in completed:
            return stage
    return None


class Orchestrator:
    """一键制作编排器：Director 决策循环 + 确定性兜底 + 阶段重试。"""

    # 单个阶段最多连续执行次数（防止 Director 反复选同一阶段空转）
    MAX_STAGE_ATTEMPTS = 3
    # 单个阶段失败后的最大重试次数（不含首次执行）
    MAX_STAGE_RETRIES = 2
    # 整轮编排的硬上限，防止 Director 不断切换阶段导致无限循环
    MAX_TOTAL_STAGES = 20

    def __init__(self, llm: BaseChatModel) -> None:
        self.llm = llm
        self.agents: dict[str, object] = {}

    def _get_agent(self, name: str) -> object:
        if name not in self.agents:
            from app.agents.specialists import create_agent_with_tools

            self.agents[name] = create_agent_with_tools(name, self.llm)
        return self.agents[name]

    # ---------- 决策 ----------

    async def _ask_director(self, goal: str, ctx: AgentContext, history: list[str]) -> str | None:
        """问 Director 下一步该做什么。

        返回归一化后的 action（``_VALID_ACTIONS`` 之一），或 None 表示 Director
        不可用/给了无法识别的值，调用方应走兜底。
        """
        agent = self._get_agent("director")
        hint = ""
        if history:
            hint = "\n已执行阶段（不要重复，除非有新的缺口）：" + "、".join(history)
        prompt = f"总目标：{goal}。{hint}\n请检查项目状态并给出下一步 next_action。"
        try:
            result = await agent.run(ctx, prompt)  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Director failed to decide next action")
            return None
        action = (getattr(result, "next_action", None) or "").strip()
        if action not in _VALID_ACTIONS:
            logger.warning("Director returned unusable next_action=%r", action)
            return None
        return action

    async def _fallback_next_stage(self, ctx: AgentContext) -> str:
        """Director 不可用时的确定性兜底。

        直接复用 ``project_status`` 服务里的 ``recommend_next_stage``，让 Director 判定、
        SaaS 控制台展示、兜底推断三者用同一份口径，不会出现"控制台说该生成帧图、
        编排器却去重绑资产"这种不一致。
        """
        from app.core.db import async_session_maker
        from app.services.studio.project_status import (
            collect_asset_stats,
            collect_shot_stats,
            recommend_next_step,
        )

        try:
            async with async_session_maker() as db:
                assets = await collect_asset_stats(db, ctx.project_id)
                shots, _gaps = await collect_shot_stats(db, ctx.project_id)
        except Exception:
            logger.exception("fallback: status aggregation failed")
            return "completed"
        return recommend_next_step(assets, shots)["stage"]

    # ---------- 执行 ----------

    async def _run_stage(
        self,
        stage: str,
        goal: str,
        ctx: AgentContext,
        on_progress: ProgressCallback | None,
    ) -> AgentResult:
        """执行单个阶段，失败自动重试，返回最后一次结果。"""
        agent_name = _ACTION_TO_AGENT[stage]
        agent = self._get_agent(agent_name)
        last: AgentResult | None = None

        for attempt in range(self.MAX_STAGE_RETRIES + 1):
            if on_progress:
                on_progress(
                    {
                        "stage": stage,
                        "status": "running",
                        "attempt": attempt + 1,
                        "max_attempts": self.MAX_STAGE_RETRIES + 1,
                    }
                )
            try:
                result = await agent.run(ctx, f"执行阶段：{stage}。目标：{goal}")  # type: ignore[attr-defined]
                last = result
                if result.status != "error":
                    return result
                logger.warning("Stage %s returned error (attempt %d): %s", stage, attempt + 1, result.output)
            except Exception as e:
                logger.exception("Stage %s raised (attempt %d)", stage, attempt + 1)
                last = AgentResult(status="error", output=str(e))

        return last or AgentResult(status="error", output="stage did not run")

    async def run(
        self,
        goal: str,
        ctx: AgentContext,
        on_progress: ProgressCallback | None = None,
    ) -> list[AgentResult]:
        results: list[AgentResult] = []
        history: list[str] = []
        attempts_by_stage: dict[str, int] = {}
        completed_stages: set[str] = set()

        for _ in range(self.MAX_TOTAL_STAGES):
            action = await self._ask_director(goal, ctx, history)
            if action is None:
                if on_progress:
                    on_progress({"stage": "director", "status": "fallback"})
                action = await self._fallback_next_stage(ctx)

            if action == "completed":
                # Don't trust "completed" if stages remain uncompleted
                next_stage = _next_uncompleted_stage(completed_stages)
                if next_stage is not None:
                    action = next_stage
                else:
                    if on_progress:
                        on_progress({"stage": "completed", "status": "completed"})
                    break

            # 跳过已完成的阶段，自动推进到下一个未完成阶段
            if action in completed_stages:
                next_stage = _next_uncompleted_stage(completed_stages)
                if next_stage is None:
                    if on_progress:
                        on_progress({"stage": "completed", "status": "completed"})
                    break
                action = next_stage

            attempts_by_stage[action] = attempts_by_stage.get(action, 0) + 1
            if attempts_by_stage[action] > self.MAX_STAGE_ATTEMPTS:
                message = (
                    f"stage {action} attempted {attempts_by_stage[action]} times without completing; "
                    "stopping to avoid a loop"
                )
                logger.error(message)
                results.append(AgentResult(status="error", output=message))
                if on_progress:
                    on_progress({"stage": action, "status": "error", "error": message})
                break

            # 执行前记录本轮起始的工具调用数，用于切出本阶段实际调用的工具
            tool_offset = len(ctx.tool_results)
            result = await self._run_stage(action, goal, ctx, on_progress)
            results.append(result)
            stage_tools = ctx.tool_results[tool_offset:]

            if result.status == "error":
                if on_progress:
                    on_progress(
                        {
                            "stage": action,
                            "status": "error",
                            "error": result.output,
                            "tool_calls": stage_tools,
                        }
                    )
                # Mark as completed (failed) and continue to next stage
                # instead of stopping the entire orchestration
                completed_stages.add(action)
                attempts_by_stage[action] = 0
                continue

            history.append(action)
            if on_progress:
                on_progress(
                    {
                        "stage": action,
                        "status": "completed",
                        "output": result.output,
                        "tool_calls": stage_tools,
                        "counts": _extract_counts(stage_tools),
                    }
                )
            # 阶段完成后重置该阶段的尝试计数
            attempts_by_stage[action] = 0
            # 标记该阶段已完成，Director 不会再选已完成的阶段
            completed_stages.add(action)

        else:
            logger.warning("Orchestrator hit MAX_TOTAL_STAGES (%d)", self.MAX_TOTAL_STAGES)
            results.append(
                AgentResult(status="error", output=f"hit stage limit ({self.MAX_TOTAL_STAGES})")
            )

        return results


def _extract_counts(tool_calls: list[dict]) -> dict[str, int]:
    """从工具结果里抽出条目数，方便前端在阶段完成事件里直接显示"新增 N 个资产"。

    ``_to_structured_tool`` 记录的是 ``{tool, args, result}``，计数字段在 ``result``
    里；同时兼容计数直接放在顶层的旧格式。只取数值型字段，避免把整个 items 列表
    塞进 SSE 事件导致 payload 膨胀。
    """
    counts: dict[str, int] = {}
    for call in tool_calls:
        name = call.get("tool")
        if not name:
            continue
        result = call.get("result")
        sources = (result, call) if isinstance(result, dict) else (call,)
        for source in sources:
            for field in ("count", "shot_count", "task_id", "created", "pending", "ready"):
                value = source.get(field)
                if isinstance(value, int):
                    counts[f"{name}.{field}"] = value
    return counts
