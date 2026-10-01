"""视频生成任务（Task）：对接 OpenAI Videos API 与火山方舟内容生成。

HTTP 细节在 `app.core.integrations`；本模块保留轮询节奏与 BaseTask 契约。
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx

from app.core.integrations.openai.video import OpenAIVideoApiAdapter
from app.core.integrations.volcengine.video import VolcengineVideoApiAdapter
from app.core.contracts.provider import ProviderConfig
from app.core.tasks.registry import resolve_task_adapter
from app.core.contracts.video_generation import VideoGenerationInput, VideoGenerationResult
from app.core.task_manager.types import BaseTask

logger = logging.getLogger(__name__)

__all__ = [
    "VideoGenerationInput",
    "VideoGenerationResult",
    "AbstractVideoGenerationTask",
    "OpenAIVideoGenerationTask",
    "VolcengineVideoGenerationTask",
    "VideoGenerationTask",
]

# 轮询时可重试的 HTTP 状态：429 限流 + 网关/服务端错误。
# 其余 4xx（401 鉴权失败、404 任务不存在等）重试无意义，直接抛出。
_RETRYABLE_POLL_STATUSES = frozenset({429, 500, 502, 503, 504})


class AbstractVideoGenerationTask(BaseTask, ABC):
    """视频生成任务基类：公共状态与 run/status/is_done/get_result。"""

    def __init__(
        self,
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 5.0,
        timeout_s: float = 900.0,
    ) -> None:
        self._cfg = provider_config
        self._input = input_
        self._poll_interval_s = poll_interval_s
        self._timeout_s = timeout_s
        self._provider_task_id: str | None = None
        self._result: VideoGenerationResult | None = None
        self._error: str = ""

    async def _sleep_poll(self) -> None:
        await asyncio.sleep(self._poll_interval_s)

    def _poll_deadline(self) -> float:
        """供应商轮询的软截止时间。

        外层 Worker 用 asyncio.wait_for 给整个 task 兜底（默认 3600s），
        但轮询循环本身没有中断点；这里以 timeout_s 为软截止，
        让长时间不返回终态的供应商任务能更快失败、把错误写进 task.error，
        而不是被外层硬超时一刀切掉，前端只看到 "Task timed out"。
        """
        return asyncio.get_event_loop().time() + max(self._timeout_s, 30.0)

    # 轮询期间网络抖动/网关错误的重试预算：查询天然幂等，可以放心重试。
    # 注意次数上限而非无限重试——软截止时间才是主闸门，这里只是别让单次抖动
    # 把一个已经提交成功的供应商任务判死刑。
    _POLL_MAX_TRANSIENT_RETRIES = 5
    _POLL_RETRY_BASE_DELAY = 2.0

    async def _poll_query(self, query: Any) -> Any:
        """执行一次轮询查询，对瞬时故障（传输错误/超时/429/5xx）退避重试。

        query 是一个无参协程工厂（``lambda: adapter.get_video(...)``），
        因为协程只能 await 一次，重试时需要重新构造。
        """
        last_exc: Exception | None = None
        for attempt in range(self._POLL_MAX_TRANSIENT_RETRIES + 1):
            try:
                return await query()
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
            except httpx.HTTPStatusError as exc:
                # 4xx（除 429）是请求本身的问题，重试没有意义；5xx/429 才值得再试。
                if exc.response.status_code not in _RETRYABLE_POLL_STATUSES:
                    raise
                last_exc = exc
            if attempt >= self._POLL_MAX_TRANSIENT_RETRIES:
                break
            delay = self._POLL_RETRY_BASE_DELAY * (2**attempt)
            logger.warning(
                "poll transient failure: task=%s attempt=%d/%d retry_in=%.1fs err=%s",
                type(self).__name__,
                attempt + 1,
                self._POLL_MAX_TRANSIENT_RETRIES,
                delay,
                last_exc,
            )
            await asyncio.sleep(delay)
        assert last_exc is not None
        raise last_exc

    @abstractmethod
    async def _create_task(self) -> None:
        """发起供应商创建任务请求，并设置 self._provider_task_id。"""

    @abstractmethod
    async def _poll_and_get_result(self) -> VideoGenerationResult:
        """轮询至终态并解析为 VideoGenerationResult。"""

    async def run(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any] | None:  # type: ignore[override]
        try:
            await self._create_task()
            self._result = await self._poll_and_get_result()
            if self._result is not None:
                self._provider_task_id = self._result.provider_task_id
        except Exception as exc:  # noqa: BLE001
            self._error = str(exc)
            self._result = None
        return None

    async def status(self) -> dict[str, Any]:  # type: ignore[override]
        return {
            "task": "video_generation",
            "provider": self._cfg.provider,
            "provider_task_id": self._provider_task_id,
            "done": await self.is_done(),
            "has_result": self._result is not None,
            "error": self._error,
            "status": self._result.status if self._result else None,
        }

    async def is_done(self) -> bool:  # type: ignore[override]
        return self._result is not None or bool(self._error)

    async def get_result(self) -> VideoGenerationResult | None:  # type: ignore[override]
        return self._result


class OpenAIVideoGenerationTask(AbstractVideoGenerationTask):
    """OpenAI Videos：adapter 负责 HTTP，Task 负责轮询间隔。"""

    def __init__(
        self,
        *,
        adapter: OpenAIVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 5.0,
        timeout_s: float = 900.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or OpenAIVideoApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_video(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=self._timeout_s,
        )

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        video_id = self._provider_task_id or ""
        if not video_id:
            raise RuntimeError("OpenAI poll missing provider task id")

        base_url = (self._cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        status_val = ""
        deadline = self._poll_deadline()
        while True:
            meta = await self._poll_query(
                lambda: self._adapter.get_video(
                    cfg=self._cfg,
                    video_id=video_id,
                    timeout_s=self._timeout_s,
                )
            )
            status_val = str(meta.get("status") or "")
            if status_val in ("completed", "failed"):
                if status_val == "failed":
                    raise RuntimeError(f"OpenAI video failed: {meta.get('error')!r}")
                break
            if asyncio.get_event_loop().time() > deadline:
                raise RuntimeError(
                    f"OpenAI video poll timed out after {self._timeout_s}s: "
                    f"video_id={video_id} last_status={status_val!r}"
                )
            await self._sleep_poll()

        return VideoGenerationResult(
            url=f"{base_url}/videos/{video_id}/content",
            file_id=None,
            provider_task_id=video_id,
            provider="openai",
            status=status_val or "completed",
        )


class VolcengineVideoGenerationTask(AbstractVideoGenerationTask):
    """火山内容生成任务：adapter 负责 HTTP，Task 负责轮询。"""

    def __init__(
        self,
        *,
        adapter: VolcengineVideoApiAdapter | None = None,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 5.0,
        timeout_s: float = 900.0,
    ) -> None:
        super().__init__(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        self._adapter = adapter or VolcengineVideoApiAdapter()

    async def _create_task(self) -> None:
        self._provider_task_id = await self._adapter.create_contents_task(
            cfg=self._cfg,
            input_=self._input,
            timeout_s=self._timeout_s,
        )

    async def _poll_and_get_result(self) -> VideoGenerationResult:
        task_id = self._provider_task_id or ""
        if not task_id:
            raise RuntimeError("Volcengine poll missing provider task id")

        base_url = (self._cfg.base_url or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
        status_val = ""
        video_url: str | None = None
        deadline = self._poll_deadline()
        while True:
            meta = await self._poll_query(
                lambda: self._adapter.get_contents_task(
                    cfg=self._cfg,
                    task_id=task_id,
                    timeout_s=self._timeout_s,
                )
            )
            status_val = str(meta.get("status") or "")
            content = meta.get("content") or {}
            if isinstance(content, dict):
                vu = content.get("video_url")
                if isinstance(vu, str) and vu:
                    video_url = vu
            if status_val in ("succeeded", "failed", "cancelled"):
                if status_val != "succeeded":
                    raise RuntimeError(f"Volcengine task not succeeded: status={status_val!r} meta={meta!r}")
                break
            if asyncio.get_event_loop().time() > deadline:
                raise RuntimeError(
                    f"Volcengine poll timed out after {self._timeout_s}s: "
                    f"task_id={task_id} last_status={status_val!r}"
                )
            await self._sleep_poll()

        if not video_url:
            video_url = f"{base_url}/contents/generations/tasks/{task_id}"

        return VideoGenerationResult(
            url=video_url,
            file_id=None,
            provider_task_id=task_id,
            provider="volcengine",
            status=status_val or "succeeded",
        )


class VideoGenerationTask(BaseTask):
    """按 provider 分派到 OpenAI / 火山实现；对外构造函数签名保持不变。"""

    def __init__(
        self,
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 5.0,
        timeout_s: float = 900.0,
    ) -> None:
        from app.bootstrap import bootstrap_all_registries

        bootstrap_all_registries()
        factory = resolve_task_adapter("video_generation", provider_config.provider)
        self._impl: AbstractVideoGenerationTask = factory(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )  # type: ignore[assignment]

    @staticmethod
    def _build_openai_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 5.0,
        timeout_s: float = 900.0,
    ) -> AbstractVideoGenerationTask:
        return OpenAIVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    @staticmethod
    def _build_volcengine_impl(
        *,
        provider_config: ProviderConfig,
        input_: VideoGenerationInput,
        poll_interval_s: float = 5.0,
        timeout_s: float = 900.0,
    ) -> AbstractVideoGenerationTask:
        return VolcengineVideoGenerationTask(
            provider_config=provider_config,
            input_=input_,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )

    async def run(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any] | None:  # type: ignore[override]
        return await self._impl.run(*args, **kwargs)

    async def status(self) -> dict[str, Any]:  # type: ignore[override]
        return await self._impl.status()

    async def is_done(self) -> bool:  # type: ignore[override]
        return await self._impl.is_done()

    async def get_result(self) -> VideoGenerationResult | None:  # type: ignore[override]
        return await self._impl.get_result()
