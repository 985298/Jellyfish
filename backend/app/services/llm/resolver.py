from __future__ import annotations

from typing import Any, cast

from fastapi import HTTPException, status
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.llm import Model, ModelCategoryKey, ModelSettings, Provider
from app.services.common import entity_not_found
from app.services.llm.provider_config_resolver import resolve_effective_base_url


_CATEGORY_TO_SETTINGS_FIELD = {
    ModelCategoryKey.text: "default_text_model_id",
    ModelCategoryKey.image: "default_image_model_id",
    ModelCategoryKey.video: "default_video_model_id",
    ModelCategoryKey.image_to_video: "default_image_to_video_model_id",
    ModelCategoryKey.super_resolution: "default_super_resolution_model_id",
    ModelCategoryKey.tts: "default_tts_model_id",
}


def _settings_model_id(settings_row: ModelSettings | None, category: ModelCategoryKey) -> str | None:
    if settings_row is None:
        return None
    field_name = _CATEGORY_TO_SETTINGS_FIELD.get(category)
    if not field_name:
        return None
    return getattr(settings_row, field_name, None)


async def get_provider_by_id_or_obj(db: AsyncSession, provider_or_id: Provider | str) -> Provider:
    """通过 Provider 实体或 provider_id 获取 Provider。"""
    return await _resolve_provider(db, provider_or_id)


async def get_model_by_category(
    db: AsyncSession,
    category: ModelCategoryKey,
    *,
    model_or_id: Model | str | None = None,
    project_id: str | None = None,
) -> Model:
    """按类别解析模型，三级：model_or_id > project_binding > global_default > 503。"""
    if model_or_id is not None:
        model = await _resolve_model(db, model_or_id)
        if model.category != category:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Configured model category mismatch: {model.id} (category={model.category})",
            )
        return model

    # 项目级绑定（binding.model_id 为 None 时跳过，走 global default）
    if project_id is not None:
        from app.models.llm import ProjectModelBinding
        binding = (await db.execute(
            select(ProjectModelBinding).where(
                ProjectModelBinding.project_id == project_id,
                ProjectModelBinding.category == category,
            )
        )).scalar_one_or_none()
        if binding and binding.model_id:
            return await get_model_by_category(db, category, model_or_id=binding.model_id)

    # 全局默认
    settings_row = await db.get(ModelSettings, 1)
    settings_model_id = _settings_model_id(settings_row, category)
    if settings_model_id:
        try:
            return await get_model_by_category(db, category, model_or_id=settings_model_id)
        except HTTPException as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Configured default model not found: {settings_model_id}",
                ) from e
            raise

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"No default model configured for category={category.value}",
    )


async def get_default_model_by_category(db: AsyncSession, category: ModelCategoryKey) -> Model:
    """按类别解析默认模型，仅从单例 ModelSettings 读取。"""
    return await get_model_by_category(db, category)


async def _resolve_model(db: AsyncSession, model_or_id: Model | str) -> Model:
    if not isinstance(model_or_id, str):
        return model_or_id
    model = await db.get(Model, model_or_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("Model"))
    return model if isinstance(model, Model) else cast(Model, cast(Any, model))


async def _resolve_provider(db: AsyncSession, provider_or_id: Provider | str) -> Provider:
    if not isinstance(provider_or_id, str):
        return provider_or_id
    provider = await db.get(Provider, provider_or_id)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=entity_not_found("Provider"))
    return provider if isinstance(provider, Provider) else cast(Provider, cast(Any, provider))


async def get_provider_by_model_or_id(db: AsyncSession, model_or_id: Model | str) -> Provider:
    """通过 Model 实体或 model_id 获取 Provider。"""
    model = await _resolve_model(db, model_or_id)
    try:
        provider = await get_provider_by_id_or_obj(db, model.provider_id)
    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Provider not found for model_id={model.id}",
            ) from e
        raise
    return provider


async def build_chat_model_from_provider(
    db: AsyncSession,
    provider_or_id: Provider | str,
) -> BaseChatModel:
    """根据 Provider 配置构造文本对话模型（ChatOpenAI）。"""
    provider = await _resolve_provider(db, provider_or_id)

    stmt = (
        select(Model)
        .where(Model.provider_id == provider.id, Model.category == ModelCategoryKey.text)
        .order_by(Model.updated_at.desc())
        .limit(1)
    )
    model = (await db.execute(stmt)).scalars().first()
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No text model configured for provider_id={provider.id}",
        )

    settings_row = await db.get(ModelSettings, 1)
    api_timeout = (settings_row.api_timeout if settings_row and settings_row.api_timeout else 30) or 30

    return _build_chat_openai_model(
        provider=provider,
        model=model,
        thinking=True,
        timeout=api_timeout,
        import_error_detail="Install langchain-openai to build chat model from provider config",
    )


async def build_default_text_llm(
    db: AsyncSession,
    *,
    thinking: bool,
    model_id: str | None = None,
    project_id: str | None = None,
) -> BaseChatModel:
    """基于默认文本模型构造 ChatOpenAI。"""
    model = await get_model_by_category(db, ModelCategoryKey.text, model_or_id=model_id, project_id=project_id)
    provider = await get_provider_by_model_or_id(db, model)
    settings_row = await db.get(ModelSettings, 1)
    api_timeout = (settings_row.api_timeout if settings_row and settings_row.api_timeout else 30) or 30
    return _build_chat_openai_model(
        provider=provider,
        model=model,
        thinking=thinking,
        timeout=api_timeout,
        import_error_detail="Install langchain-openai (e.g. uv sync --group dev) to use film extraction endpoints",
    )


def _build_chat_openai_model(
    *,
    provider: Provider,
    model: Model,
    thinking: bool,
    timeout: int = 30,
    import_error_detail: str,
) -> BaseChatModel:
    api_key = (provider.api_key or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Provider api_key is empty for provider_id={provider.id}",
        )

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=import_error_detail,
        ) from e

    kwargs: dict[str, Any] = dict(model.params or {})
    kwargs["model"] = model.name
    kwargs["api_key"] = api_key
    kwargs.setdefault("temperature", 0)
    kwargs.setdefault("timeout", timeout)
    kwargs.setdefault("max_retries", 0)

    base_url = resolve_effective_base_url(provider=provider, category=ModelCategoryKey.text)
    if base_url:
        kwargs.setdefault("base_url", base_url)

    if not thinking:
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["enable_thinking"] = False
        kwargs["extra_body"] = extra_body

    return ChatOpenAI(**kwargs)


def build_default_text_llm_sync(
    db: Session,
    *,
    thinking: bool,
    model_id: str | None = None,
    project_id: str | None = None,
) -> BaseChatModel:
    """同步入口 — Celery worker 用。DB 查询保持同步，ChatOpenAI 构造共享 _build_chat_openai_model。"""
    model: Model | None = None

    # 1. 显式 model_id
    if model_id:
        model = db.get(Model, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail=entity_not_found("Model"))
        if model.category != ModelCategoryKey.text:
            raise HTTPException(status_code=503, detail=f"Model category mismatch: {model.id} (category={model.category})")

    # 2. 项目级绑定
    if model is None and project_id:
        from app.models.llm import ProjectModelBinding
        binding = db.execute(
            select(ProjectModelBinding).where(
                ProjectModelBinding.project_id == project_id,
                ProjectModelBinding.category == ModelCategoryKey.text,
            )
        ).scalar_one_or_none()
        if binding and binding.model_id:
            model = db.get(Model, binding.model_id)
            if model and model.category != ModelCategoryKey.text:
                raise HTTPException(status_code=503, detail=f"Model category mismatch: {model.id}")

    # 3. 全局默认
    if model is None:
        settings_row = db.get(ModelSettings, 1)
        sid = _settings_model_id(settings_row, ModelCategoryKey.text)
        if sid:
            model = db.get(Model, sid)

    if model is None:
        raise HTTPException(status_code=503, detail="No default text model configured")

    provider = db.get(Provider, model.provider_id)
    if provider is None:
        raise HTTPException(status_code=503, detail=f"Provider not found for model_id={model.id}")

    settings_row = db.get(ModelSettings, 1)
    api_timeout = (settings_row.api_timeout if settings_row and settings_row.api_timeout else 30) or 30

    return _build_chat_openai_model(
        provider=provider,
        model=model,
        thinking=thinking,
        timeout=api_timeout,
        import_error_detail="Install langchain-openai to use script-processing tasks",
    )
