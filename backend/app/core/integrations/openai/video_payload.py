"""OpenAI Videos API：请求体与参考图映射。"""

from __future__ import annotations

from typing import Any

from app.core.integrations.openai.video_capabilities import validate_openai_video_options
from app.core.integrations.video_capabilities import derive_provider_size, resolve_effective_ratio
from app.core.contracts.video_generation import VideoGenerationInput, _strip_optional_b64


def to_image_data_url(value: str) -> str:
    v = value.strip()
    if v.startswith("data:image/"):
        return v
    return f"data:image/png;base64,{v}"


def pick_input_reference(input_: VideoGenerationInput) -> dict[str, str] | None:
    """reference 模式：用 images 列表（官方 URL 直传）。"""
    if input_.images:
        return {"image_url": input_.images[0]}
    return None


def build_create_video_body(input_: VideoGenerationInput) -> dict[str, Any]:
    validate_openai_video_options(input_)
    # 官方格式：size + aspect_ratio 顶层（不放 metadata），mode + images（reference）
    body: dict[str, Any] = {}
    body["size"] = "720P"
    effective_ratio = resolve_effective_ratio(input_)
    if effective_ratio:
        body["aspect_ratio"] = effective_ratio
    body["prompt"] = input_.prompt or ""
    if input_.model:
        body["model"] = input_.model
    if input_.seconds is not None:
       body["seconds"] = str(int(input_.seconds))

    if input_.seed is not None:
        body["seed"] = int(input_.seed)
    if input_.watermark is not None:
        body["watermark"] = bool(input_.watermark)

    if input_.images:
        body["mode"] = "reference"
        body["images"] = input_.images[:5]
    else:
        body["mode"] = "text"
    return body
