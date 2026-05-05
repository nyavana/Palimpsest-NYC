"""GET /config — small public endpoint the web UI consults at startup.

The frontend uses this to decide whether to:
- show a "BYOK required" banner and auto-open the Settings modal, or
- treat user-supplied credentials as an optional override of the server key.

The response intentionally does NOT include the server's actual API key;
only flags + non-secret defaults that a user might want pre-filled.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter()


class ConfigDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    model: str | None


class ConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    byok_required: bool
    byok_supported: bool
    defaults: ConfigDefaults


@router.get("/config", response_model=ConfigResponse, tags=["config"])
async def get_config(request: Request) -> ConfigResponse:
    settings = request.app.state.settings
    byok_required: bool = getattr(request.app.state, "byok_required", False)
    return ConfigResponse(
        byok_required=byok_required,
        byok_supported=True,
        defaults=ConfigDefaults(
            base_url=settings.openrouter.base_url,
            # When BYOK is required there is no server-picked default model
            # to suggest — the user must choose one. When server keys exist,
            # surface the standard tier as the most likely BYOK starting point.
            model=None if byok_required else settings.openrouter.standard_model,
        ),
    )
