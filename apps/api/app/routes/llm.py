"""/llm/* routes — thin HTTP surface over the LLMRouter capability."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.llm.models import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Route a single chat request through the LLM router."""
    router_instance = getattr(request.app.state, "llm_router", None)
    if router_instance is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="llm_router_not_initialized",
        )
    return await router_instance.chat(body)
