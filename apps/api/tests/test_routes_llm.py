"""Tests for /llm/chat — specifically the BYOK gating added in V1.1.

The endpoint is a thin passthrough to the router; full LLM behavior is
covered by test_llm_router.py. These tests verify the BYOK-mode gate.
"""

from __future__ import annotations

from app.llm.models import ChatRequest, Message
from app.routes.llm import router as llm_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_app(*, byok_required: bool, llm_router_obj: object | None) -> FastAPI:
    app = FastAPI()
    app.state.byok_required = byok_required
    app.state.llm_router = llm_router_obj
    app.include_router(llm_router, prefix="/llm")
    return app


def _body() -> dict:
    return ChatRequest(messages=[Message(role="user", content="hi")]).model_dump()


def test_llm_chat_returns_503_when_byok_required():
    """In BYOK mode, /llm/chat is unavailable — clients are directed to /agent/ask."""
    app = _build_app(byok_required=True, llm_router_obj=None)
    with TestClient(app) as client:
        resp = client.post("/llm/chat", json=_body())
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["error"] == "byok_mode_active"
    assert "agent/ask" in detail["message"].lower()


def test_llm_chat_returns_503_when_router_uninitialized():
    """Defensive path: even when not in BYOK mode, an absent router
    surfaces 503 rather than crashing."""
    app = _build_app(byok_required=False, llm_router_obj=None)
    with TestClient(app) as client:
        resp = client.post("/llm/chat", json=_body())
    assert resp.status_code == 503
    # Distinct error from byok_mode_active so logs can tell them apart.
    assert resp.json()["detail"] == "llm_router_not_initialized"
