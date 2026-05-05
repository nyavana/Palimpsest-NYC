"""/llm/* routes — thin HTTP surface over the LLMRouter capability.

In BYOK mode (no server-side OPENROUTER_API_KEY configured), this surface
is unavailable: every call returns 503 directing callers to /agent/ask,
which knows how to thread per-request user credentials through a fresh
LLMRouter. /llm/chat does not currently accept user credentials of its own.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.llm.models import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Route a single chat request through the LLM router."""
    if getattr(request.app.state, "byok_required", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "byok_mode_active",
                "message": "Server has no OPENROUTER_API_KEY; use POST /agent/ask with X-LLM-Credentials.",
            },
        )
    router_instance = getattr(request.app.state, "llm_router", None)
    if router_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="llm_router_not_initialized",
        )
    return await router_instance.chat(body)
