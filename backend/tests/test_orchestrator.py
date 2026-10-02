"""Orchestrator 决策循环 / 阶段重试 / SSE 事件回填的单元测试。

用假 agent 替身，不连 LLM、不连 DB：只验证编排逻辑本身。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.core import AgentContext, AgentResult
from app.agents.orchestrator import Orchestrator, _extract_counts


def _decision(action: str):
    return lambda _ctx: AgentResult(status="completed", output="", next_action=action)


def _sequence_decisions(*actions: str):
    """返回一个 _ask_director 替身，按顺序吐出 actions。"""
    it = iter(actions)

    async def _ask(ctx, goal, history):
        try:
            return next(it)
        except StopIteration:
            return "completed"

    return _ask


@pytest.mark.asyncio
async def test_director_drives_stage_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = Orchestrator(llm=None)  # type: ignore[arg-type]
    monkeypatch.setattr(orch, "_ask_director", _sequence_decisions(
        "extract_assets", "generate_videos", "completed",
    ))

    seen: dict[str, int] = {}

    def _get(name: str):
        seen[name] = seen.get(name, 0) + 1
        return _OK_AGENT

    monkeypatch.setattr(orch, "_get_agent", _get)

    events: list[dict] = []
    ctx = AgentContext(project_id="p1")
    results = await orch.run("做短剧", ctx, on_progress=events.append)

    assert len(results) == 6, "五个非 completed 阶段各产出一条结果"
    assert seen == {"character_designer": 2, "storyboard": 1, "production": 3}
    completed_stages = [e["stage"] for e in events if e.get("status") == "completed"]
    assert completed_stages == ["extract_assets", "generate_videos", "generate_asset_refs", "divide_shots", "generate_keyframes", "compose_film", "completed"]


@pytest.mark.asyncio
async def test_director_failure_falls_back_instead_of_stopping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Director 内部异常时必须自己 catch 并返回 None（和真实 _ask_director 行为一致），
    随后 Orchestrator.run 会自动走兜底流程——这是"LLM 挂了流程仍能推进"的关键。"""
    orch = Orchestrator(llm=None)  # type: ignore[arg-type]

    # 真实 _ask_director 在 agent.run 抛异常时 catch 并返回 None；测试模拟同一行为。
    async def _director_unavailable(goal: str, ctx, history: list) -> str | None:
        return None

    monkeypatch.setattr(orch, "_ask_director", _director_unavailable)

    fallback_calls = {"n": 0}

    async def _fallback(ctx) -> str:
        fallback_calls["n"] += 1
        stages = ["extract_assets", "generate_asset_refs", "divide_shots", "generate_keyframes", "generate_videos", "completed"]
        idx = min(fallback_calls["n"] - 1, len(stages) - 1)
        return stages[idx]

    monkeypatch.setattr(orch, "_fallback_next_stage", _fallback)
    monkeypatch.setattr(orch, "_get_agent", lambda name: _OK_AGENT)

    events: list[dict] = []
    results = await orch.run("做短剧", AgentContext(project_id="p1"), on_progress=events.append)

    assert fallback_calls["n"] == 7
    assert len(results) == 6
    assert all(r.status == "completed" for r in results)
    assert any(e.get("status") == "fallback" for e in events)


@pytest.mark.asyncio
async def test_failing_stage_is_retried_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = Orchestrator(llm=None)  # type: ignore[arg-type]
    calls: list[str] = []

    class _Flaky:
        async def run(self, ctx: AgentContext, user_input: str) -> AgentResult:
            calls.append(user_input)
            if len(calls) < 3:
                raise RuntimeError("transient")
            return AgentResult(status="completed", output="recovered")

    # Director provides all 5 stages in order to avoid guard interference
    monkeypatch.setattr(orch, "_ask_director", _sequence_decisions(
        "extract_assets", "generate_asset_refs", "divide_shots",
        "generate_keyframes", "generate_videos", "completed",
    ))
    monkeypatch.setattr(orch, "_get_agent", lambda name: _Flaky())

    events: list[dict] = []
    results = await orch.run("做短剧", AgentContext(project_id="p1"), on_progress=events.append)

    # extract_assets retries: call 1 (fail), call 2 (fail), call 3 (succeed)
    assert len(calls) >= 3, "extract_assets should retry at least 3 times"
    assert results[0].status == "completed"
    assert len(results) == 6
    # Check retry attempts for the first stage
    first_stage_attempts = [e["attempt"] for e in events
                            if e.get("status") == "running" and e.get("stage") == "extract_assets"]
    assert first_stage_attempts == [1, 2, 3]


@pytest.mark.asyncio
async def test_stage_error_result_also_triggers_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """specialist 返回 status=error（而非抛异常）时同样走重试。"""
    orch = Orchestrator(llm=None)  # type: ignore[arg-type]
    calls: list[str] = []

    class _ErroringThenOk:
        async def run(self, ctx: AgentContext, user_input: str) -> AgentResult:
            calls.append(user_input)
            if len(calls) < 2:
                return AgentResult(status="error", output="bad")
            return AgentResult(status="completed", output="ok")

    # _ask_director 是协程，monkeypatch 替身也必须是 async。
    async def _director(goal: str, ctx, history: list) -> str:
        return "divide_shots" if len(calls) < 2 else "completed"

    monkeypatch.setattr(orch, "_ask_director", _director)
    monkeypatch.setattr(orch, "_get_agent", lambda name: _ErroringThenOk())

    results = await orch.run("做短剧", AgentContext(project_id="p1"))
    assert len(calls) >= 2
    assert results[0].status == "completed"
    assert len(results) == 6


@pytest.mark.asyncio
async def test_repeated_stage_stops_before_infinite_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = Orchestrator(llm=None)  # type: ignore[arg-type]
    orch.MAX_STAGE_ATTEMPTS = 2

    async def _always(ctx, goal, history) -> str:
        return "extract_assets"

    class _FailOnExtract:
        async def run(self, ctx: AgentContext, user_input: str) -> AgentResult:
            if "extract_assets" in user_input:
                return AgentResult(status="error", output="always fails")
            return AgentResult(status="completed", output="ok")

    monkeypatch.setattr(orch, "_ask_director", _always)
    monkeypatch.setattr(orch, "_get_agent", lambda name: _FailOnExtract())

    results = await orch.run("做短剧", AgentContext(project_id="p1"))

    # extract_assets 跑满 2 次后中止（error），guard 推进剩余 4 个阶段。
    assert len(results) == 6
    error_results = [r for r in results if r.status == "error"]
    assert len(error_results) == 1
    assert error_results[0].output  # stage failed after max retries


@pytest.mark.asyncio
async def test_progress_event_carries_tool_calls_and_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = Orchestrator(llm=None)  # type: ignore[arg-type]
    monkeypatch.setattr(orch, "_ask_director", _sequence_decisions("extract_assets", "completed"))

    ctx = AgentContext(project_id="p1")

    class _AssetAgent:
        async def run(self, c: AgentContext, user_input: str) -> AgentResult:
            # 复刻 _to_structured_tool 的副作用：把真实返回值写进 ctx.tool_results
            c.tool_results.append(
                {"tool": "extract_assets", "args": {"project_id": "p1"}, "result": {"count": 7}}
            )
            return AgentResult(status="completed", output="extracted")

    monkeypatch.setattr(orch, "_get_agent", lambda name: _AssetAgent())

    events: list[dict] = []
    await orch.run("做短剧", ctx, on_progress=events.append)

    done = [e for e in events if e.get("status") == "completed" and e["stage"] == "extract_assets"]
    assert len(done) == 1
    assert done[0]["counts"] == {"extract_assets.count": 7}
    assert done[0]["tool_calls"][0]["tool"] == "extract_assets"


@pytest.mark.asyncio
async def test_stage_tool_calls_do_not_leak_across_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """每阶段只回填自己那轮的工具调用，不应带上上一阶段的。"""
    orch = Orchestrator(llm=None)  # type: ignore[arg-type]
    monkeypatch.setattr(orch, "_ask_director", _sequence_decisions("extract_assets", "completed"))

    ctx = AgentContext(project_id="p1")

    class _TwoToolAgent:
        async def run(self, c: AgentContext, user_input: str) -> AgentResult:
            c.tool_results.append({"tool": "extract_assets", "result": {"count": 2}})
            c.tool_results.append({"tool": "generate_image", "result": {"task_id": "t1"}})
            return AgentResult(status="completed", output="ok")

    monkeypatch.setattr(orch, "_get_agent", lambda name: _TwoToolAgent())

    events: list[dict] = []
    await orch.run("做短剧", ctx, on_progress=events.append)

    done = [e for e in events if e.get("status") == "completed" and e["stage"] == "extract_assets"][0]
    assert [t["tool"] for t in done["tool_calls"]] == ["extract_assets", "generate_image"]
    assert done["counts"] == {"extract_assets.count": 2}


def test_extract_counts_ignores_non_numeric_fields() -> None:
    counts = _extract_counts(
        [
            {"tool": "query_shots", "count": 3, "items": ["a", "b"]},
            {"tool": "check_task_status", "task_id": "abc"},  # str -> 不计入
            {"result": {"count": 1}},  # 缺 tool 名 -> 跳过
        ]
    )
    assert counts == {"query_shots.count": 3}


class _OkAgent:
    async def run(self, ctx: AgentContext, user_input: str) -> AgentResult:
        return AgentResult(status="completed", output="ok")


_OK_AGENT: Any = _OkAgent()