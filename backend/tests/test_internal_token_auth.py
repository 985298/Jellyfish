"""条款3 binding tests: studio entities internal-token auth + project_id required.

台账#6 recurrence guard: proves verify_internal_token actually blocks unauthenticated
access (403) and that scene_images/prop_images/costume_images now require project_id.
Pre-fix: entities router had no dependencies + three typed endpoints had Query(None).
Post-fix: router has Depends(verify_internal_token) + three endpoints have Query(...).

Tests:
- No X-Internal-Token -> 403 (auth blocks)
- Wrong X-Internal-Token -> 403 (value checked, not just presence)
- Correct X-Internal-Token -> not 403 (auth passes, does not over-block)
- scene_images without project_id (with token) -> 422 (Query tightening)
- prop_images without project_id (with token) -> 422
- costume_images without project_id (with token) -> 422
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings

_VALID_TOKEN = settings.jellyfish_internal_token

import pytest


@pytest.fixture(autouse=True)
def _restore_real_auth():
    """Undo conftest's verify_internal_token bypass so we test real auth.

    conftest sets app.dependency_overrides[verify_internal_token] = no-op for logic
    tests. This fixture pops it so our auth tests exercise the real verify_internal_token.
    """
    from app.api.internal import verify_internal_token
    from app.main import app
    app.dependency_overrides.pop(verify_internal_token, None)
    yield




def test_no_internal_token_returns_403(client: TestClient) -> None:
    """无 X-Internal-Token -> 403。Pre-fix would have returned 200/422 (no auth)."""
    r = client.get("/api/v1/studio/entities/character")
    assert r.status_code == 403, r.text


def test_wrong_internal_token_returns_403(client: TestClient) -> None:
    """错误 token -> 403。Proves value is checked via secrets.compare_digest."""
    r = client.get(
        "/api/v1/studio/entities/character",
        headers={"X-Internal-Token": "wrong-token"},
    )
    assert r.status_code == 403, r.text


def test_correct_token_passes_auth() -> None:
    """正确 token -> 非 403（auth 通过，进入端点逻辑）。

    DB-agnostic: raise_server_exceptions=False 让缺表 500 返回为 response
    而非抛异常 — 我们只断言 auth 没返回 403。
    """
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get(
        "/api/v1/studio/entities/character",
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert r.status_code != 403, f"token should pass auth but got 403: {r.text}"


def test_scene_images_requires_project_id(client: TestClient) -> None:
    """scene_images 无 project_id -> 422。Pre-fix: Query(None) would have accepted."""
    r = client.get(
        "/api/v1/studio/entities/scene_images",
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert r.status_code == 422, r.text


def test_prop_images_requires_project_id(client: TestClient) -> None:
    """prop_images 无 project_id -> 422。"""
    r = client.get(
        "/api/v1/studio/entities/prop_images",
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert r.status_code == 422, r.text


def test_costume_images_requires_project_id(client: TestClient) -> None:
    """costume_images 无 project_id -> 422。"""
    r = client.get(
        "/api/v1/studio/entities/costume_images",
        headers={"X-Internal-Token": _VALID_TOKEN},
    )
    assert r.status_code == 422, r.text
