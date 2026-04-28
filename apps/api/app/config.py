"""Application configuration.

All settings come from environment variables. Missing required variables
cause startup to fail fast with a clear error message.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production", "test"]


class OpenRouterSettings(BaseSettings):
    """Cloud LLM backend (OpenRouter)."""

    model_config = SettingsConfigDict(env_prefix="OPENROUTER_", extra="ignore")

    api_key: SecretStr = Field(..., description="OpenRouter API key")
    base_url: str = Field(default="https://openrouter.ai/api/v1")
    standard_model: str = Field(default="openai/gpt-5.4-mini")
    complex_model: str = Field(default="openai/gpt-5.4")
    timeout_s: float = Field(default=60.0)


class LocalLLMSettings(BaseSettings):
    """Router's `simple` tier backend (OpenAI-compatible HTTP).

    For V1 this points at OpenRouter, same as the cloud tier — the split is
    router-internal terminology so the two complexities can have independent
    circuit breakers. v2 may swap the URL for an on-device endpoint without
    code change.
    """

    model_config = SettingsConfigDict(env_prefix="LOCAL_LLM_", extra="ignore")

    base_url: str = Field(default="https://openrouter.ai/api/v1")
    model: str = Field(default="google/gemma-4-31b-it:free")
    api_key: SecretStr = Field(default=SecretStr("sk-no-key-required"))
    timeout_s: float = Field(default=60.0)


class EmbeddingsSettings(BaseSettings):
    """Sentence-transformers embeddings settings (loaded inside api container)."""

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", extra="ignore")

    model: str = Field(default="BAAI/bge-small-en-v1.5")
    dim: int = Field(default=384)
    batch_size: int = Field(default=32)


class LLMRouterSettings(BaseSettings):
    """Router-level knobs: cache TTLs and circuit breaker."""

    model_config = SettingsConfigDict(env_prefix="LLM_", extra="ignore")

    cache_ttl_simple_s: int = Field(default=86_400)
    cache_ttl_standard_s: int = Field(default=21_600)
    cache_ttl_complex_s: int = Field(default=3_600)

    cb_fail_threshold: int = Field(default=3)
    cb_window_s: int = Field(default=60)
    cb_cooldown_s: int = Field(default=30)


class PostgresSettings(BaseSettings):
    """Postgres connection settings."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", extra="ignore")

    user: str = Field(default="palimpsest")
    password: SecretStr = Field(default=SecretStr("devpassword"))
    db: str = Field(default="palimpsest")
    host: str = Field(default="postgres")
    port: int = Field(default=5432)

    @property
    def dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:"
            f"{self.password.get_secret_value()}@{self.host}:{self.port}/{self.db}"
        )


class AgentSettings(BaseSettings):
    """Agent loop settings."""

    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore")

    max_turns: int = Field(default=6)


class MetaSettings(BaseSettings):
    """Meta-instrumentation harness settings."""

    model_config = SettingsConfigDict(env_prefix="META_", extra="ignore")

    session_log_dir: str = Field(default="/app/logs/claude-sessions")


class Settings(BaseSettings):
    """Root settings aggregator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Environment = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")  # noqa: S104
    api_port: int = Field(default=8000, alias="API_PORT")
    api_cors_origins: str = Field(
        default="http://localhost:5173",
        alias="API_CORS_ORIGINS",
    )

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    openrouter: OpenRouterSettings = Field(default_factory=OpenRouterSettings)  # type: ignore[arg-type]
    local_llm: LocalLLMSettings = Field(default_factory=LocalLLMSettings)
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings)
    llm_router: LLMRouterSettings = Field(default_factory=LLMRouterSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    meta: MetaSettings = Field(default_factory=MetaSettings)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]
