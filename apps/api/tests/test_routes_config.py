"""Tests for the GET /config endpoint."""

from __future__ import annotations

from app.routes.config import router as config_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _StubOpenRouter:
    base_url = "https://openrouter.ai/api/v1"
    standard_model = "openai/gpt-5.4-mini"


class _StubSettings:
    openrouter = _StubOpenRouter()


def _build_app(*, byok_required: bool) -> FastAPI:
    app = FastAPI()
    app.state.settings = _StubSettings()
    app.state.byok_required = byok_required
    app.include_router(config_router)
    return app


def test_config_reports_byok_not_required_when_server_key_present():
    app = _build_app(byok_required=False)
    with TestClient(app) as client:
        resp = client.get("/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["byok_required"] is False
    assert body["byok_supported"] is True
    assert body["defaults"]["base_url"] == "https://openrouter.ai/api/v1"
    # Server has a default model the UI can pre-fill as a hint.
    assert body["defaults"]["model"] == "openai/gpt-5.4-mini"


def test_config_reports_byok_required_with_no_default_model():
    """When the server has no API key, /config flags BYOK as required and
    omits a server-suggested model so the UI can prompt the user freshly."""
    app = _build_app(byok_required=True)
    with TestClient(app) as client:
        resp = client.get("/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["byok_required"] is True
    assert body["defaults"]["model"] is None
    # base_url default is still useful as a placeholder.
    assert body["defaults"]["base_url"] == "https://openrouter.ai/api/v1"


def test_config_response_does_not_leak_api_key_field():
    """Defense in depth: /config response shape forbids extra fields."""
    app = _build_app(byok_required=False)
    with TestClient(app) as client:
        resp = client.get("/config")
    body = resp.json()
    # No api_key, secret, or token fields anywhere in the response.
    flat = str(body).lower()
    for forbidden in ("api_key", "apikey", "secret", "token"):
        assert forbidden not in flat
