"""OpenAI Videos API：创建与查询。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.integrations.openai.video_payload import build_create_video_body
from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput

logger = logging.getLogger(__name__)

# 网络抖动 / 网关 5xx / 429 限流时重试，避免单次失败直接把整个视频任务判死刑。
# 仅重试幂等的创建请求；查询天然幂等。
# 429 限流：解析 Retry-After 头（秒），若无则使用 2^n 退避。
_CREATE_RETRY_STATUSES = {429, 502, 503, 504}
_CREATE_MAX_RETRIES = 3
_CREATE_RETRY_BASE_DELAY = 1.5


class OpenAIVideoApiAdapter:
    """OpenAI 视频：POST /videos 与 GET /videos/{id}。"""

    async def create_video(
        self,
        *,
        cfg: ProviderConfig,
        input_: VideoGenerationInput,
        timeout_s: float,
    ) -> str:
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("httpx is required for video generation tasks") from e

        base_url = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
        }
        body = build_create_video_body(input_)

        last_exc: Exception | None = None
        for attempt in range(_CREATE_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    r = await client.post(f"{base_url}/videos", headers=headers, json=body)
                    # 4xx 是请求本身的问题，不要重试；5xx/网关错误重试。
                    if r.status_code in _CREATE_RETRY_STATUSES:
                        raise httpx.HTTPStatusError(
                            f"OpenAI /videos retryable status {r.status_code}",
                            request=r.request,
                            response=r,
                        )
                    r.raise_for_status()
                    data: dict[str, Any] = r.json()
                    video_id = str(data.get("id") or "")
                    if not video_id:
                        raise RuntimeError(f"OpenAI /videos missing id: {data!r}")
                    return video_id
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code not in _CREATE_RETRY_STATUSES:
                    raise
                logger.warning(
                    "OpenAI /videos retryable failure attempt=%d status=%s",
                    attempt + 1,
                    exc.response.status_code,
                )
                # 429 时优先用 Retry-After 头指定的秒数，退避更精准
                if exc.response.status_code == 429:
                    retry_after = exc.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            _delay = float(retry_after)
                        except ValueError:
                            _delay = _CREATE_RETRY_BASE_DELAY * (2 ** attempt)
                    else:
                        _delay = _CREATE_RETRY_BASE_DELAY * (2 ** attempt)
                else:
                    _delay = _CREATE_RETRY_BASE_DELAY * (2 ** attempt)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning("OpenAI /videos transport error attempt=%d: %s", attempt + 1, exc)
                _delay = _CREATE_RETRY_BASE_DELAY * (2 ** attempt)

            if attempt < _CREATE_MAX_RETRIES - 1:
                await asyncio.sleep(_delay)

        raise RuntimeError(f"OpenAI /videos failed after {_CREATE_MAX_RETRIES} attempts: {last_exc}") from last_exc

    async def get_video(
        self,
        *,
        cfg: ProviderConfig,
        video_id: str,
        timeout_s: float,
    ) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("httpx is required for video generation tasks") from e

        base_url = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        headers = {"Authorization": f"Bearer {cfg.api_key}"}

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            rr = await client.get(f"{base_url}/videos/{video_id}", headers=headers)
            rr.raise_for_status()
            return rr.json()
