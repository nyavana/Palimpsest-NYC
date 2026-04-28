## MODIFIED Requirements

### Requirement: Dual-backend dispatch by complexity

The LLM router SHALL expose a single `chat(request)` entry point that accepts a `complexity` tag (`simple | standard | complex`) and dispatches the request to one of two **OpenAI-compatible HTTP backends** configured by environment variables. The router SHALL bind `simple` to the "local-tier" backend (env: `LOCAL_LLM_BASE_URL` + `LOCAL_LLM_MODEL`), and `standard` / `complex` to the "cloud-tier" backend (env: `OPENROUTER_BASE_URL` + `OPENROUTER_STANDARD_MODEL` / `OPENROUTER_COMPLEX_MODEL`). The chosen backend and model SHALL be returned to the caller as part of the response metadata. The router MUST NOT hard-code any backend hostname or model slug.

For V1, both `LOCAL_LLM_BASE_URL` and `OPENROUTER_BASE_URL` SHALL be set to `https://openrouter.ai/api/v1`. The split exists for the router's internal circuit-breaker and tier abstractions; the "local" name is router-internal terminology and does NOT mean network-local in V1. On-device LLM hosting is out of V1 scope.

#### Scenario: Simple request routed to the local-tier endpoint
- **WHEN** a caller invokes `router.chat(ChatRequest(messages=..., complexity="simple"))` and the local-tier backend is healthy
- **THEN** the request is sent to the URL configured by `LOCAL_LLM_BASE_URL` targeting the model in `LOCAL_LLM_MODEL`, and the response metadata reports `backend="local"` and `model=<LOCAL_LLM_MODEL>`

#### Scenario: V1 default routes simple to OpenRouter free Gemma
- **WHEN** the V1 default `.env.example` values are in effect (`LOCAL_LLM_BASE_URL=https://openrouter.ai/api/v1`, `LOCAL_LLM_MODEL=google/gemma-4-31b-it:free`) and a `simple` request arrives
- **THEN** the request hits OpenRouter and the response metadata reports `backend="local"` and `model="google/gemma-4-31b-it:free"` — the "local" name refers to the *router-internal tier*, not to network locality

#### Scenario: Complex request routed to the cloud-tier model
- **WHEN** a caller invokes `router.chat(ChatRequest(messages=..., complexity="complex"))`
- **THEN** the request is sent to `OPENROUTER_BASE_URL` targeting `OPENROUTER_COMPLEX_MODEL`, and the response metadata reports `backend="openrouter"` and `model=<OPENROUTER_COMPLEX_MODEL>`

#### Scenario: V1 deployment never points LOCAL_LLM_BASE_URL at a non-OpenRouter host
- **WHEN** a V1 environment is brought up
- **THEN** `LOCAL_LLM_BASE_URL` resolves to an OpenRouter origin; any other value is treated as a v2 configuration outside this spec's scope

### Requirement: Configuration via environment

Router configuration SHALL come from environment variables loaded by `pydantic-settings`, never from hardcoded values. Required variables: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_STANDARD_MODEL`, `OPENROUTER_COMPLEX_MODEL`, `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`, `LOCAL_LLM_API_KEY`, `LLM_CACHE_TTL_SIMPLE_S`, `LLM_CACHE_TTL_STANDARD_S`, `LLM_CACHE_TTL_COMPLEX_S`. Missing required variables MUST cause startup to fail with a clear error naming the missing variable.

For V1, `LOCAL_LLM_API_KEY` MUST be a real OpenRouter key (typically the same value as `OPENROUTER_API_KEY`).

#### Scenario: Missing OPENROUTER_API_KEY aborts startup
- **WHEN** the API starts without `OPENROUTER_API_KEY` set
- **THEN** startup fails with a clear message naming the missing variable

#### Scenario: Missing LOCAL_LLM_BASE_URL aborts startup
- **WHEN** the API starts without `LOCAL_LLM_BASE_URL` set
- **THEN** startup fails with a clear message naming the missing variable

### Requirement: Fallback ladder and circuit breaker

The router SHALL maintain a per-backend circuit breaker that opens after three consecutive failures within 60 seconds and half-opens after a 30-second cooldown. When the **local-tier backend** is open, `simple` requests SHALL silently upgrade to the **cloud-tier `standard` model**. When the **cloud-tier backend** is open, `standard` and `complex` requests SHALL surface an explicit error rather than silently downgrading to the local-tier model. The router MUST NOT drop requests; every call either returns a `ChatResponse` or raises a typed exception the caller can handle.

In V1, both tiers terminate at OpenRouter, so a true platform outage will trip both breakers in close succession. The breakers nevertheless track per-tier failure counts independently, since the model slug, prompt size, and rate-limit class differ per tier and may fail asymmetrically.

#### Scenario: Local-tier degraded, simple request upgraded
- **WHEN** the local-tier circuit breaker is open and a `simple` request arrives
- **THEN** the router transparently uses `OPENROUTER_STANDARD_MODEL` and the response metadata reports `backend="openrouter"`, `model=<OPENROUTER_STANDARD_MODEL>`, and `upgraded_from="local"`

#### Scenario: Cloud-tier unavailable, complex request surfaces error
- **WHEN** the cloud-tier circuit breaker is open and a `complex` request arrives
- **THEN** the router raises `CloudBackendUnavailableError` and does NOT silently route to the local-tier backend
