"""Phase 4 视频生成诊断修复的回归测试。

覆盖三件事：
1. 429 被纳入创建请求的重试集合，并解析 Retry-After 决定退避时长；
2. 轮询期间的瞬时故障（429/5xx/传输错误）退避重试，而非直接判死；
3. 轮询超时上限从 120s 放宽到 900s，且软截止时间真的会触发。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

import app.core.integrations.openai.video as create_mod
from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput
from app.core.integrations.openai.video import (
    _CREATE_MAX_RETRIES,
    _CREATE_RETRY_STATUSES,
    OpenAIVideoApiAdapter,
)
from app.core.tasks.video_generation_tasks import (
    AbstractVideoGenerationTask,
    OpenAIVideoGenerationTask,
)

_REQ = httpx.Request("GET", "https://example.invalid/v1/videos/x")


def _cfg() -> ProviderConfig:
    return ProviderConfig(provider="openai", api_key="k", base_url="https://example.invalid/v1")


def _input() -> VideoGenerationInput:
    return VideoGenerationInput(prompt="a cat", model="sora-2", ratio="16:9")


def _resp(status: int, *, headers: dict[str, str] | None = None, payload: Any = None) -> httpx.Response:
    return httpx.Response(status, request=_REQ, headers=headers or {}, json=payload or {})


def _status_error(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError("boom", request=_REQ, response=_resp(status))


class _StubAdapter:
    """假 adapter：不走 HTTP，按脚本返回结果或抛异常。"""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls = 0

    async def get_video(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


def _task(adapter: Any, **kw: Any) -> OpenAIVideoGenerationTask:
    task = OpenAIVideoGenerationTask(
        adapter=adapter,
        provider_config=_cfg(),
        input_=_input(),
        poll_interval_s=kw.get("poll_interval_s", 0.0),
        timeout_s=kw.get("timeout_s", 900.0),
    )
    # 关掉退避 sleep，避免测试真的等 2s/4s/8s。
    task._POLL_RETRY_BASE_DELAY = 0.0
    task._provider_task_id = "vid-1"
    return task


# ---------------------------------------------------------------- 429 创建重试


def test_429_is_in_create_retry_statuses() -> None:
    assert 429 in _CREATE_RETRY_STATUSES


@pytest.mark.asyncio
async def test_create_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 不再是一击致命：前两次 429、第三次 200 时应正常返回 video_id。"""
    statuses = [429, 429, 200]
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, **_: Any) -> None: ...

        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def post(self, url: str, **_: Any) -> Any:
            calls["n"] += 1
            code = statuses.pop(0)
            return _resp(code, headers={"Retry-After": "0"}, payload={"id": "vid-123"})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(create_mod, "_CREATE_RETRY_BASE_DELAY", 0.0)

    vid = await OpenAIVideoApiAdapter().create_video(cfg=_cfg(), input_=_input(), timeout_s=5.0)

    assert vid == "vid-123"
    assert calls["n"] == 3, "前两次 429 后第三次成功"


@pytest.mark.asyncio
async def test_create_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, **_: Any) -> None: ...

        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def post(self, url: str, **_: Any) -> Any:
            calls["n"] += 1
            return _resp(429, headers={"Retry-After": "0"})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    monkeypatch.setattr(create_mod, "_CREATE_RETRY_BASE_DELAY", 0.0)

    with pytest.raises(RuntimeError, match="failed after"):
        await OpenAIVideoApiAdapter().create_video(cfg=_cfg(), input_=_input(), timeout_s=5.0)
    assert calls["n"] == _CREATE_MAX_RETRIES


@pytest.mark.asyncio
async def test_create_does_not_retry_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """鉴权失败重试没有意义，应该第一次就抛。"""
    calls = {"n": 0}

    class _FakeClient:
        def __init__(self, **_: Any) -> None: ...

        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def post(self, url: str, **_: Any) -> Any:
            calls["n"] += 1
            return _resp(401)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    with pytest.raises(httpx.HTTPStatusError):
        await OpenAIVideoApiAdapter().create_video(cfg=_cfg(), input_=_input(), timeout_s=5.0)
    assert calls["n"] == 1


# ---------------------------------------------------------------- 轮询重试


@pytest.mark.asyncio
async def test_poll_retries_transient_500_then_succeeds() -> None:
    adapter = _StubAdapter([_status_error(500), {"status": "completed"}])
    result = await _task(adapter)._poll_and_get_result()
    assert result.status == "completed"
    assert adapter.calls == 2


@pytest.mark.asyncio
async def test_poll_retries_transport_error() -> None:
    adapter = _StubAdapter([httpx.ConnectError("reset"), {"status": "completed"}])
    result = await _task(adapter)._poll_and_get_result()
    assert result.status == "completed"
    assert adapter.calls == 2


@pytest.mark.asyncio
async def test_poll_does_not_retry_404() -> None:
    """401/404 重试没有意义，应该第一次就抛出。"""
    adapter = _StubAdapter([_status_error(404)])
    with pytest.raises(httpx.HTTPStatusError):
        await _task(adapter)._poll_and_get_result()
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_poll_gives_up_after_transient_budget() -> None:
    """持续 503 时，重试预算耗尽后抛出，而不是无限循环。"""
    adapter = _StubAdapter([_status_error(503) for _ in range(50)])
    with pytest.raises(httpx.HTTPStatusError):
        await _task(adapter)._poll_and_get_result()
    assert adapter.calls == AbstractVideoGenerationTask._POLL_MAX_TRANSIENT_RETRIES + 1


# ---------------------------------------------------------------- 超时上限


def test_video_defaults_allow_long_jobs() -> None:
    """轮询软截止从 120s 放宽到 900s，适配分钟级视频任务。"""
    task = OpenAIVideoGenerationTask(provider_config=_cfg(), input_=_input())
    assert task._timeout_s == 900.0
    assert task._poll_interval_s == 5.0


@pytest.mark.asyncio
async def test_poll_deadline_actually_fires() -> None:
    """供应商一直 queued 时，软截止时间应触发超时错误。"""
    adapter = _StubAdapter([{"status": "queued"} for _ in range(100)])
    task = _task(adapter, poll_interval_s=0.0, timeout_s=30.0)
    # 把软截止压到 50ms：_poll_deadline() 走 max(timeout_s, 30.0)，不覆盖就得真等 30s。
    loop = asyncio.get_running_loop()
    task._poll_deadline = lambda: loop.time() + 0.05  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="timed out"):
        await task._poll_and_get_result()