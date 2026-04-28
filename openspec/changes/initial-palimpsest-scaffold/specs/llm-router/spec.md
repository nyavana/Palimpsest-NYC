## ADDED Requirements

### Requirement: Dual-backend dispatch by complexity

The LLM router SHALL expose a single `chat(request)` entry point that accepts a `complexity` tag (`simple | standard | complex`) and dispatches the request to the appropriate backend: local `llama.cpp` Gemma-4 for `simple`, OpenRouter `gpt-5.4-mini` for `standard`, OpenRouter `gpt-5.4` for `complex`. The chosen backend and model SHALL be returned to the caller as part of the response metadata.

#### Scenario: Simple request routed to local backend
- **WHEN** a caller invokes `router.chat(ChatRequest(messages=..., complexity="simple"))` and the local backend is healthy
- **THEN** the request is sent to the `llama.cpp` adapter targeting `gemma-4-26B-A4B-it` and the response metadata reports `backend="local"` and `model="gemma-4-26B-A4B-it"`

#### Scenario: Complex request routed to cloud GPT-5.4
- **WHEN** a caller invokes `router.chat(ChatRequest(messages=..., complexity="complex"))`
- **THEN** the request is sent to the OpenRouter adapter targeting `openai/gpt-5.4` and the response metadata reports `backend="openrouter"` and `model="openai/gpt-5.4"`

### Requirement: Fallback ladder and circuit breaker

The router SHALL maintain a per-backend circuit breaker that opens after three consecutive failures within 60 seconds and half-opens after a 30-second cooldown. When the local backend is open, `simple` requests SHALL silently upgrade to `gpt-5.4-mini`. When the OpenRouter backend is open, `standard` and `complex` requests SHALL surface an explicit error rather than silently downgrading to the local model. The router MUST NOT drop requests; every call either returns a `ChatResponse` or raises a typed exception the caller can handle.

#### Scenario: Local backend degraded, simple request upgraded
- **WHEN** the local circuit breaker is open and a `simple` request arrives
- **THEN** the router transparently uses the OpenRouter `gpt-5.4-mini` model and the response metadata reports `backend="openrouter"`, `model="openai/gpt-5.4-mini"`, and `upgraded_from="local"`

#### Scenario: Cloud backend unavailable, complex request surfaces error
- **WHEN** the OpenRouter circuit breaker is open and a `complex` request arrives
- **THEN** the router raises `CloudBackendUnavailableError` and does NOT silently route to the local backend

### Requirement: Request caching with canonicalization

The router SHALL cache successful responses in Redis keyed by SHA-256 of the canonicalized request (`model`, sorted `messages`, `temperature`, optional `tool` schema hash). Cache TTLs SHALL be 24 hours for `simple`, 6 hours for `standard`, and 1 hour for `complex`. Cache hits MUST still emit a telemetry record with `cached: true`.

#### Scenario: Identical simple request hits cache
- **WHEN** two identical `simple` requests are sent within 24 hours
- **THEN** the second request returns the cached response without calling the backend, and the telemetry record has `cached: true` with the same `response_id` as the first call

#### Scenario: Request with different temperature is cache-miss
- **WHEN** two otherwise-identical requests differ only in `temperature`
- **THEN** the router treats them as distinct cache keys and calls the backend for both

### Requirement: Telemetry for every call

The router SHALL emit a telemetry record to the configured logger AND to a Redis time-series for every call (including cache hits and errors). Each record SHALL contain: `request_id`, `timestamp`, `backend`, `model`, `complexity`, `cached`, `prompt_tokens`, `completion_tokens`, `latency_ms`, `cost_usd`, `error_code` (if any), and a `tags` map the caller may populate.

#### Scenario: Successful cloud call emits full telemetry record
- **WHEN** a `standard` request succeeds against OpenRouter
- **THEN** a telemetry record is emitted with non-null `prompt_tokens`, `completion_tokens`, `latency_ms`, `cost_usd`, and `cached=false`

#### Scenario: Errored call emits telemetry with error_code
- **WHEN** a request fails because OpenRouter returns HTTP 429
- **THEN** a telemetry record is emitted with `error_code="rate_limited"`, `latency_ms` set, and `prompt_tokens=0`, `completion_tokens=0`

### Requirement: OpenAI-compatible adapter interface

Both adapters (`OpenRouterAdapter` and `LlamaCppAdapter`) SHALL implement the same `async def complete(request: NormalizedRequest) -> NormalizedResponse` protocol so the router is agnostic to which backend it talks to. The `LlamaCppAdapter` SHALL target `llama.cpp`'s built-in OpenAI-compatible `/v1/chat/completions` endpoint, allowing the router to treat both backends identically.

#### Scenario: Adapters share a single interface
- **WHEN** the router calls `await adapter.complete(req)` on either adapter
- **THEN** both return a `NormalizedResponse` with the same shape (`id`, `model`, `choices`, `usage`)

### Requirement: Configuration via environment

Router configuration SHALL come from environment variables loaded by `pydantic-settings`, never from hardcoded values. Required variables: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `LLAMA_CPP_BASE_URL`, `LLAMA_CPP_MODEL`, `LLM_CACHE_TTL_SIMPLE_S`, `LLM_CACHE_TTL_STANDARD_S`, `LLM_CACHE_TTL_COMPLEX_S`. Missing required variables MUST cause startup to fail with a clear error.

#### Scenario: Missing OPENROUTER_API_KEY aborts startup
- **WHEN** the API starts without `OPENROUTER_API_KEY` set
- **THEN** startup fails with a clear message naming the missing variable
