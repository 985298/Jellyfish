"""P6 binding tests: model management refactor — dict mapping + base_url + probe mock.

Tests the key logic changes from P0-P2:
- _CATEGORY_TO_SETTINGS_FIELD maps all 7 categories correctly
- resolve_effective_base_url handles new categories
- probe_provider_models parses OpenAI /models response format
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.llm import ModelCategoryKey


# ---- P0-3: _CATEGORY_TO_SETTINGS_FIELD dict mapping ----

def test_settings_field_dict_covers_all_7_categories():
    """All 7 ModelCategoryKey values must have a settings field mapping."""
    from app.services.llm.resolver import _CATEGORY_TO_SETTINGS_FIELD
    for cat in ModelCategoryKey:
        assert cat in _CATEGORY_TO_SETTINGS_FIELD, f"Missing mapping for {cat}"


def test_settings_field_dict_values_are_valid_attr_names():
    """Dict values must be valid ModelSettings attribute names."""
    from app.services.llm.resolver import _CATEGORY_TO_SETTINGS_FIELD
    from app.models.llm import ModelSettings
    for cat, field_name in _CATEGORY_TO_SETTINGS_FIELD.items():
        assert hasattr(ModelSettings, field_name), f"ModelSettings has no attr {field_name} for {cat}"


# ---- P0-4: resolve_effective_base_url new categories ----

def test_resolve_effective_base_url_image_to_video_uses_video_base():
    """image_to_video should use video_base_url (not common base_url)."""
    from app.services.llm.provider_config_resolver import resolve_effective_base_url
    provider = MagicMock()
    provider.base_url = "https://api.example.com/v1"
    provider.image_base_url = "https://img.example.com/v1"
    provider.video_base_url = "https://vid.example.com/v1"
    result = resolve_effective_base_url(
        provider=provider,
        category=ModelCategoryKey.image_to_video,
        provider_key="openai",
    )
    assert result == "https://vid.example.com/v1"


def test_resolve_effective_base_url_super_resolution_uses_common():
    """super_resolution should fall through to common base_url."""
    from app.services.llm.provider_config_resolver import resolve_effective_base_url
    provider = MagicMock()
    provider.base_url = "https://api.example.com/v1"
    provider.image_base_url = None
    provider.video_base_url = None
    result = resolve_effective_base_url(
        provider=provider,
        category=ModelCategoryKey.super_resolution,
        provider_key="openai",
    )
    assert result == "https://api.example.com/v1"


# ---- P2: probe_provider_models mock ----

@pytest.mark.asyncio
async def test_probe_parses_openai_models_response():
    """probe should parse OpenAI {data: [{id: ...}]} format correctly."""
    from app.services.llm.manage import probe_provider_models

    mock_provider = MagicMock()
    mock_provider.api_key = "test-key"
    mock_provider.base_url = "https://api.example.com/v1"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_provider)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {"id": "gpt-4o", "object": "model"},
            {"id": "dall-e-3", "object": "model"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await probe_provider_models(mock_db, provider_id="test-prov")

    assert len(result.models) == 2
    assert result.models[0].id == "gpt-4o"
    assert result.models[1].id == "dall-e-3"
    assert result.raw_status == 200


@pytest.mark.asyncio
async def test_probe_404_returns_empty_list():
    """404 from provider should return empty models list, not raise."""
    from app.services.llm.manage import probe_provider_models

    mock_provider = MagicMock()
    mock_provider.api_key = "test-key"
    mock_provider.base_url = "https://api.example.com/v1"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_provider)

    mock_resp = MagicMock()
    mock_resp.status_code = 404

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await probe_provider_models(mock_db, provider_id="test-prov")

    assert len(result.models) == 0
    assert result.raw_status == 404


@pytest.mark.asyncio
async def test_probe_401_raises_403():
    """401 from provider should raise HTTPException 403."""
    from app.services.llm.manage import probe_provider_models
    from fastapi import HTTPException

    mock_provider = MagicMock()
    mock_provider.api_key = "test-key"
    mock_provider.base_url = "https://api.example.com/v1"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_provider)

    mock_resp = MagicMock()
    mock_resp.status_code = 401

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(HTTPException) as exc_info:
            await probe_provider_models(mock_db, provider_id="test-prov")
    assert exc_info.value.status_code == 403


# ---- P0-1: runtime re-export ----

def test_runtime_reexports_sync_function():
    """runtime.py should re-export build_default_text_llm_sync from resolver."""
    from app.services.llm.runtime import build_default_text_llm_sync
    from app.services.llm.resolver import build_default_text_llm_sync as resolver_sync
    assert build_default_text_llm_sync is resolver_sync


# ---- P0-3: _settings_model_id no longer has implicit video fallback ----

def test_settings_model_id_returns_none_for_unknown_category():
    """Before P0, unknown categories fell through to video. Now should return None."""
    from app.services.llm.resolver import _settings_model_id
    settings = MagicMock()
    settings.default_text_model_id = "text-uuid"
    settings.default_image_model_id = "img-uuid"
    settings.default_video_model_id = "vid-uuid"
    settings.default_image_to_video_model_id = None
    settings.default_super_resolution_model_id = None
    settings.default_tts_model_id = None

    # Known categories return correct values
    assert _settings_model_id(settings, ModelCategoryKey.text) == "text-uuid"
    assert _settings_model_id(settings, ModelCategoryKey.image) == "img-uuid"
    assert _settings_model_id(settings, ModelCategoryKey.video) == "vid-uuid"

    # New categories return None (not video!)
    assert _settings_model_id(settings, ModelCategoryKey.image_to_video) is None
    assert _settings_model_id(settings, ModelCategoryKey.super_resolution) is None
    assert _settings_model_id(settings, ModelCategoryKey.tts) is None


def test_settings_model_id_none_settings_returns_none():
    """None settings_row should return None for any category."""
    from app.services.llm.resolver import _settings_model_id
    assert _settings_model_id(None, ModelCategoryKey.text) is None
    assert _settings_model_id(None, ModelCategoryKey.video) is None
