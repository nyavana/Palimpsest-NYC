# Milestone 1 — Palimpsest NYC slide deck

> Paste this whole markdown file into Google Gemini's canvas feature and ask it
> to build a slide deck. The blocks below are slide-by-slide. Section headers
> = slide titles, bullets = on-slide content, *italicized* lines = speaker
> notes / what to say (do not put on the slide), and `[design hints]` give
> Gemini guidance on visuals.
>
> Total budget: **5 minutes = ~8 slides ≈ 35-40 s each**.

---

## Designer brief (read this once before building any slide)

- **Tone**: graduate seminar, Columbia EECS E6895. Calm, technical, slightly literary. Avoid emoji; avoid "AI buzzwords". The project name *Palimpsest* is from medieval parchments scraped and re-written — lean into the archival/cartographic feel.
- **Palette**: parchment cream `#F5EFE0` background, deep navy `#0F2A44` accent, brick red `#A23E2A` for highlights, charcoal `#2A2A2A` for body text.
- **Typography**: serif for titles (Playfair Display / Cormorant Garamond / Lora). Sans-serif for body (Inter / Source Sans Pro). Monospace for code (JetBrains Mono / IBM Plex Mono).
- **Layout**: generous whitespace. One core idea per slide. No more than 5 lines of text. Numbers should be large and prominent. Use the architecture diagram as a recurring visual motif (small inset on later slides).
- **Imagery**: subtle Manhattan / topographic map texture in the background of title and section-divider slides at ~10% opacity. NO clip-art, NO stock photography of "people pointing at laptops". Hand-drawn map iconography only.

---

# Slide 1 — Title

**Palimpsest NYC**
*An agentic walking tour of Morningside Heights, grounded in public-domain archives.*

- Columbia EECS E6895 — Advanced Big Data and AI
- Milestone 1 (MVP demo)
- *(presenter name + date)*

`[design hints]` Big serif title. Small map sliver of UWS + Morningside as a background motif at low opacity. The word "Palimpsest" set apart and slightly larger.

*Speaker notes*: "Palimpsest NYC is an agent that plans and narrates a short walking tour through Morningside Heights and the Upper West Side, grounded in public-domain archives. Today I'm showing the Milestone 1 demo: the backend is end-to-end working against a real corpus."

---

# Slide 2 — The problem

**LLMs are confident liars about places.**

- Walking-tour narration needs **verifiable citations**, not vibes.
- Vanilla LLMs hallucinate landmarks, dates, and street addresses.
- The interesting problem isn't "generate prose" — it's **prove every claim came from a real source**.

`[design hints]` Two side-by-side panels. Left: a vague blob labelled "GPT says…" with a wavy citation. Right: a sharp pin on a map with a stable `wikipedia:Cathedral_of_Saint_John_the_Divine` doc_id underneath. Brick-red accent on the right panel.

*Speaker notes*: "The motivating problem isn't generating prose — that's solved. It's grounding. We want a system where every sentence in the narration is provably traceable to a real, retrieved document. So I built a citation contract that the agent has to satisfy at generation time, and a verifier that rejects responses that don't."

---

# Slide 3 — V1 MVP scope (what we're shipping)

**Bounded, demoable, online-only.**

- **Geography**: Morningside Heights + Upper West Side (~5 km² bbox).
- **Sources (V1)**: Wikipedia/Wikidata + OpenStreetMap. Public-domain only.
- **Agent**: single LLM-callable tool — `search_places`. Multi-turn refinement, max 6 turns.
- **Citation contract** (locked): every claim carries `doc_id`, `source_url`, `source_type`, `span`, `retrieval_turn`. Verifier rejects responses that violate the contract.
- **Routing**: server-side PostGIS walk after the agent finishes — the LLM never plans the route.

`[design hints]` Bounded-bbox map of UWS + Morningside Heights with thin pin clusters. Five-field citation pill on the right with each field labelled. "single tool" callout in brick red.

*Speaker notes*: "V1 is intentionally bounded. One neighborhood, two sources, one tool. The most opinionated decision is that the LLM only ever sees a `search_places` tool. The walking-route optimization is server-side PostGIS — the LLM never has the option to invent an inefficient walk because it has no routing tool to misuse."

---

# Slide 4 — Architecture

**Five pieces, each minimal.**

```
React + Vite + MapLibre  ──HTTPS + SSE──▶  FastAPI
                                              │
                  ┌───────────────────────────┼───────────────────────────┐
                  ▼                           ▼                           ▼
          Postgres 16              Sentence-Transformers          LLM Router
       postgis · pgvector            BAAI/bge-small-en-v1.5      (cache · breaker)
       pg_trgm · vector(384)         CPU singleton, 384-dim       OpenRouter
```

- **Hybrid retrieval**: pgvector cosine ANN + PostGIS `ST_DWithin` spatial filter.
- **LLM router**: two OpenAI-compatible adapters; per-tier circuit breakers; cost telemetry.
- **Embeddings in-process**: `app.state.embedder`, no external embedding API.

`[design hints]` Replicate the ASCII diagram cleanly with hand-drawn-map style boxes. Highlight the three "shared state" components in navy: postgres, embedder, router. Annotate the SSE arrow in brick red.

*Speaker notes*: "Five components. Frontend talks to FastAPI over Server-Sent Events — not WebSocket — because the channel is server→client only and SSE is half the proxy config. Postgres carries the corpus with pgvector for semantic search and PostGIS for spatial filters. The embedder runs in-process, so no third-party embedding API. And the LLM router is the cost-aware dispatch layer with per-tier circuit breakers."

---

# Slide 5 — Current progress (numbers and a live trace)

**Backend demo-ready.**

| | |
|---|---|
| **Places ingested** | **928** (492 Wikipedia + 436 OSM) |
| **Documents ingested** | **323** Wikipedia summaries |
| **Embedding coverage** | **100%** (384-dim, locked) |
| **Unit tests** | **120 passing**, 1 integration skipped |
| **End-to-end agent run** | ✓ verified citations, ordered walk emitted |

Live SSE trace excerpt (real, not faked):

```
event: tool_call    data: {"name":"search_places","arguments":{"query":"gothic cathedral Morningside"}}
event: tool_result  data: {"name":"search_places","n_hits":8}
event: narration    data: {"text":"…The Church of Notre Dame stands near Morningside Park…"}
event: citations    data: {"citations":[{"doc_id":"osm:way:274996134","source_type":"osm","retrieval_turn":3}, …]}
event: walk         data: {"stops":[{"index":0,"name":"Church of Notre Dame","leg_distance_m":0}, …]}
event: done
```

`[design hints]` Numbers in oversized navy. Code block in monospace with brick-red `event:` keywords. Subtle parchment grid lines.

*Speaker notes*: "These numbers aren't projected — the corpus is in postgres right now. 120 unit tests cover the agent loop, the citation verifier, the walk planner, and the SSE framing. The trace at the bottom is from a real run today: kimi-k2.6 calls `search_places`, refines the query, emits narration, the verifier accepts, and the server runs PostGIS routing before the terminal frame."

---

# Slide 6 — Key technical decisions

**Three opinionated trade-offs.**

1. **Cost-aware LLM dispatch.** Two OpenAI-compatible adapters; complexity → backend mapping; one env-var flip swaps free Gemma to paid GPT-5.4 for the eval. Independent circuit breakers per tier.
2. **Citation contract verified at generation time.** `narration` + `citations[]` JSON. Verifier checks doc_id is in the retrieval ledger, source_type matches, retrieval_turn ≤ current; one retry then a visible uncertainty warning. Hallucinated citations cannot reach the user.
3. **Server-side walking-route, not an LLM tool.** `plan_walk` is PostGIS over the cited place_ids. Removes a whole class of "agent picks a bad route" failure modes.

`[design hints]` Three numbered cards in a row. Each card titled in brick red, body in charcoal. Use a tiny icon for each: scale (cost), check-mark inside a quote (citation), zigzag walking path (route).

*Speaker notes*: "Three decisions worth flagging. First, the router gives us cost-aware dispatch with one env-var flip from free Gemma to paid GPT — that's the basis for the §13.6 cost-vs-quality study. Second, the citation contract is enforced at generation time, not as a post-hoc filter — the agent literally cannot return a response that fails verification. Third, walk planning is server-side, so the LLM doesn't have to do graph optimization."

---

# Slide 7 — Two weeks to go

**Demo-ready → polished → graded.**

| Week | Work |
|---|---|
| **Week +1** | Frontend `EventSource` + map markers + flyTo. Fix `apps/web/Dockerfile`. Hand-grade 5 walks (§13.4). |
| **Week +2** | Free-vs-paid cost analysis, ~10 walks (§13.6). Final-report draft incl. agentic-engineering chapter (§13.7). 30-second demo video (§13.8). |
| **Deferred to v2** | Chronicling America / NYPL / NYC Open Data / MTA / NOAA. VPS deploy. On-device LLM. User study. |

`[design hints]` Two-column timeline, weeks side by side. Strikethrough the v2 row in muted gray. A small "deferred ⇢ v2" tag.

*Speaker notes*: "Two weeks left. The biggest user-visible piece is the frontend `EventSource` consumer that renders the walk on the map. Then qualitative eval over five walks, the free-vs-paid cost study, the report draft, and a 30-second demo video. Five live data sources and the VPS deploy are explicitly deferred to v2 — they're spec-tracked, not abandoned."

---

# Slide 8 — The agentic engineering angle (and Q&A)

**The codebase is itself a dataset.**

- Built end-to-end by Claude Code under one human reviewer.
- Every session is captured to `logs/claude-sessions/*.jsonl` — prompt tokens, completion tokens, files touched, outcome, cost.
- The final report has a chapter quantifying the **cost, cycle time, and failure modes** of agentic software engineering against a non-trivial real-world spec.
- That dataset is itself a "Big Data and AI" artifact for E6895.

**Questions?**

`[design hints]` Centered title in navy serif. The bullets in two short lines beneath. Big "Questions?" centered, brick-red. Subtle palimpsest texture in background.

*Speaker notes*: "One thing that's unusual about this project: it's been written end-to-end by Claude Code under a single human reviewer. Every session — every prompt, every tool call, every cost — is logged to JSONL. So the final report won't just describe the system; it'll quantify what it cost to build, how long each phase took, and where the agent failed. That dataset is itself a Big Data artifact for the course. Happy to take questions."

---

## Appendix slides (use only if the timer permits, otherwise skip)

### A1 — Citation contract (the locked JSON)

```json
{
  "narration": "The Cathedral of St. John the Divine was begun in 1892…",
  "citations": [
    {
      "doc_id": "wikipedia:Cathedral_of_Saint_John_the_Divine",
      "source_url": "https://en.wikipedia.org/wiki/…",
      "source_type": "wikipedia",
      "span": "intro",
      "retrieval_turn": 2
    }
  ]
}
```

Verifier rules (paraphrased): doc_id in ledger; source_type ∈ V1 enum;
source_url matches retrieved row; retrieval_turn ≤ current_turn; span opaque.

### A2 — Why kimi-k2.6 takes 5 minutes per walk

- Extended-thinking model: ~50–100s/turn just on reasoning tokens.
- Final-turn `max_tokens=8192` so reasoning + JSON output both fit.
- One env-var flip to a non-thinking model collapses end-to-end latency
  to ~30s with no code change. That's the §13.6 paid-eval setup.

### A3 — Risk register (short)

| Risk | Mitigation |
|---|---|
| Free Gemma slug rate-limited or renamed | All references env-driven; one-line `.env` flip |
| 384-dim retrieval quality insufficient | Drop+recreate column at 768-dim; small migration |
| Plain-SQL migrations unwieldy | Eight headroom; switching to Alembic is a port, not a rewrite |
| Single-tool agent reads as "less agentic" | Demo highlights iterative `search_places` refinement + the server-side walk |

---

## Notes for the presenter (NOT slide content)

- **Open the talk by naming the problem, not the project.** "LLMs are confident liars about places" lands harder than "we built a thing".
- **Keep one slide on numbers, one on the trace.** Don't dilute either.
- **The agentic engineering angle is the differentiator** for E6895 specifically — don't bury it on slide 8; if you have only 4 minutes, demote slide 6 (decisions) and keep slide 8.
- **If a demo is allowed**: skip slide 5's numbers table and live-run the curl SSE call instead. The event stream is more compelling than a static excerpt.
- **If asked about hallucination**: point at the citation contract slide. "The agent cannot emit a response that doesn't pass the verifier; if it tries, it gets one corrective retry, then we surface a visible uncertainty warning."
- **If asked about scale**: be honest. 928 places is small. The architecture is the same at 100× — pgvector ivfflat + bbox filter scales linearly with the corpus.
