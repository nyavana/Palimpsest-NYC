# Milestone 1 — Palimpsest NYC slide deck (Claude prompt)

> **How to use this file**: open a fresh Claude conversation and paste the
> entire markdown below the next horizontal rule. Claude will produce a
> single-file HTML artifact with all 8 slides ready to present. The
> deliverable spec, design system, and slide content are all in-line.
>
> **Total budget**: 5 minutes ≈ 8 slides ≈ 35–40 s each.

---

## Prompt for Claude (paste from here down)

You are designing a 5-minute milestone-1 presentation deck for *Palimpsest NYC*, a graduate final project for Columbia EECS E6895 (Advanced Big Data and AI). I want you to build this as **a single self-contained `index.html` artifact** I can open locally or screen-share. Read the full brief and slide content below, then produce the artifact.

### Deliverable spec

- **Artifact format**: one HTML file. Inline `<style>` + minimal vanilla JS for navigation. No external bundlers.
- **Tailwind**: CDN script tag is fine (`https://cdn.tailwindcss.com`).
- **Fonts**: load from Google Fonts — `Cormorant Garamond` (700) for slide titles, `Inter` (400/500/600) for body, `JetBrains Mono` (400/500) for code blocks.
- **Aspect ratio**: 16:9. Each slide is a `min-h-screen` flex container that fills the viewport at 16:9, centered.
- **Navigation**:
  - Right-arrow / `Space` / `PageDown` / click → next slide.
  - Left-arrow / `PageUp` → previous slide.
  - `Home` → first slide. `End` → last slide.
  - Touch / swipe support is nice-to-have, not required.
  - Slide counter in the bottom-right (e.g. `3 / 8`) in muted gray.
  - Subtle progress bar across the bottom (1px, brick-red fill).
- **Print-friendly**: `@media print` rules so each slide becomes its own page when printed to PDF.
- **No animation framework**. Use plain CSS transitions only — opacity fade between slides at most. No bouncing, no parallax, no carousel libs.
- **Speaker notes**: hide on screen by default. A toggle button (or `n` keypress) reveals them as a floating panel at the bottom of the current slide. Notes never appear in the print/PDF output.

### Design system (be strict about this)

- **Tone**: graduate seminar, calm, technical, slightly literary. *Palimpsest* refers to medieval parchments scraped and re-written. Lean into the archival/cartographic feel — this is NOT a generic SaaS pitch deck.
- **Avoid**: emoji, AI buzzwords, gradient backgrounds, neon, drop shadows on text, glassmorphism, "AI startup" aesthetics, stock photography of laptops, generic icon-and-bullet templates.
- **Color palette** (use these exact values):

  ```
  --parchment:  #F5EFE0   /* page background */
  --ink:        #2A2A2A   /* body text */
  --navy:       #0F2A44   /* primary accent, headings */
  --brick:      #A23E2A   /* highlights, key numbers */
  --muted:      #8B8378   /* secondary text, slide counter */
  --rule:       #D9CFB8   /* hairline rules, table borders */
  ```

- **Typography rules**:
  - Slide titles: Cormorant Garamond, 700, ~64px, navy, slight letter-spacing.
  - Body / bullets: Inter, 400, 22–26px, ink color, 1.5 line-height.
  - Numbers (the "928 places" type): Cormorant Garamond, 700, 96–128px, brick.
  - Code: JetBrains Mono, 14–16px, charcoal on cream `#EBE3CD`. No syntax highlighting beyond making `event:` keywords brick-red.
- **Layout rules**:
  - One core idea per slide. Max 5 bullets, max ~50 words of body copy.
  - Generous whitespace; never fill more than ~70% of the slide area with text.
  - Ample top + bottom margins. Slide title is always the same vertical position.
  - Number-heavy slide: numbers oversized, labels small underneath.
- **Imagery**:
  - Background motif: a soft parchment texture (CSS `background-image` with a subtle noise SVG inline) and a faint Manhattan-grid pattern at <10% opacity behind title slides.
  - All diagrams are inline SVG with thin (1.5px) navy strokes — hand-drawn-map feel, no rounded gradient boxes. No raster images, no clipart.
  - Decorative motifs: a single fine-line topographic contour curve along the bottom edge of the title slide; nothing else decorative.

### Slide-by-slide content

For each slide, on-screen content is plain bullets / paragraphs. The `Speaker notes` block is hidden by default — render it only inside the floating notes panel that toggles with `n`. The `[design]` hints are for you (Claude) to follow when laying out that specific slide; do not render their text on the slide.

---

#### Slide 1 — Title

**Palimpsest NYC**
*An agentic walking tour of Morningside Heights, grounded in public-domain archives.*

- Columbia EECS E6895 — Advanced Big Data and AI
- Milestone 1 (MVP demo)
- *(presenter name + date)*

`[design]` Big serif title centered slightly above the vertical midline. Subtitle in italic Inter, muted color, just below. Three meta lines clustered tightly under the subtitle. Below the meta block, a single thin topographic contour line stretching across the slide. Manhattan grid pattern at <10% opacity behind everything.

*Speaker notes*: "Palimpsest NYC is an agent that plans and narrates a short walking tour through Morningside Heights and the Upper West Side, grounded in public-domain archives. Today I'm showing the Milestone 1 demo: the backend is end-to-end working against a real corpus."

---

#### Slide 2 — The problem

**LLMs are confident liars about places.**

- Walking-tour narration needs **verifiable citations**, not vibes.
- Vanilla LLMs hallucinate landmarks, dates, and street addresses.
- The interesting problem isn't "generate prose" — it's **prove every claim came from a real source**.

`[design]` Two side-by-side panels separated by a hairline rule. Left panel labelled "GPT says…" — a soft fuzzy text blob, ink color, with a wavy underline as the "citation". Right panel labelled "Palimpsest says…" — a single sharp pin marker (SVG) on a tiny map sliver, with a stable doc_id `wikipedia:Cathedral_of_Saint_John_the_Divine` rendered in mono below the pin. Right panel border in brick-red.

*Speaker notes*: "The motivating problem isn't generating prose — that's solved. It's grounding. We want a system where every sentence in the narration is provably traceable to a real, retrieved document. So I built a citation contract that the agent has to satisfy at generation time, and a verifier that rejects responses that don't."

---

#### Slide 3 — V1 MVP scope

**Bounded, demoable, online-only.**

- **Geography**: Morningside Heights + Upper West Side (~5 km² bbox).
- **Sources**: Wikipedia/Wikidata + OpenStreetMap. Public-domain only.
- **Agent**: single LLM-callable tool — `search_places`. Multi-turn refinement, max 6 turns.
- **Citation contract** (locked): every claim carries `doc_id`, `source_url`, `source_type`, `span`, `retrieval_turn`. Verifier rejects responses that violate the contract.
- **Routing**: server-side PostGIS walk after the agent finishes. The LLM never plans the route.

`[design]` Two-column layout. Left column: bullets. Right column: a small SVG bbox map of UWS + Morningside Heights with maybe 6–10 thin pin clusters at approximate landmark coordinates (no need for accuracy — just suggest density). Below the map, a five-pill citation card showing the locked field names (`doc_id` / `source_url` / `source_type` / `span` / `retrieval_turn`), each pill outlined in navy.

*Speaker notes*: "V1 is intentionally bounded. One neighborhood, two sources, one tool. The most opinionated decision is that the LLM only ever sees a `search_places` tool. The walking-route optimization is server-side PostGIS — the LLM never has the option to invent an inefficient walk because it has no routing tool to misuse."

---

#### Slide 4 — Architecture

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

`[design]` Render the architecture as inline SVG (NOT a code block). Five rectangles with thin 1.5px navy borders, hand-drawn-map feel. Connecting arrows in navy with brick-red labels (`HTTPS + SSE`). The three downstream boxes (Postgres / Embedder / Router) sit on a horizontal line, each annotated with their key tech in mono underneath. Three short bullets in a strip below the diagram.

*Speaker notes*: "Five components. Frontend talks to FastAPI over Server-Sent Events — not WebSocket — because the channel is server→client only and SSE is half the proxy config. Postgres carries the corpus with pgvector for semantic search and PostGIS for spatial filters. The embedder runs in-process, so no third-party embedding API. And the LLM router is the cost-aware dispatch layer with per-tier circuit breakers."

---

#### Slide 5 — Current progress

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

`[design]` Top half of the slide: the four key numbers in oversized brick (Cormorant Garamond, 96–128px) — `928`, `323`, `100%`, `120` — each with a tiny label in muted Inter underneath (`places`, `documents`, `embedding coverage`, `unit tests`). Bottom half: the SSE trace as a code block with `event:` keywords coloured brick. No chrome around the code; just a hairline rule above and below.

*Speaker notes*: "These numbers aren't projected — the corpus is in postgres right now. 120 unit tests cover the agent loop, the citation verifier, the walk planner, and the SSE framing. The trace at the bottom is from a real run today: kimi-k2.6 calls `search_places`, refines the query, emits narration, the verifier accepts, and the server runs PostGIS routing before the terminal frame."

---

#### Slide 6 — Key technical decisions

**Three opinionated trade-offs.**

1. **Cost-aware LLM dispatch.** Two OpenAI-compatible adapters; complexity → backend mapping; one env-var flip swaps free Gemma to paid GPT-5.4 for the eval. Independent circuit breakers per tier.
2. **Citation contract verified at generation time.** `narration` + `citations[]` JSON. Verifier checks doc_id is in the retrieval ledger, source_type matches, retrieval_turn ≤ current; one retry then a visible uncertainty warning. Hallucinated citations cannot reach the user.
3. **Server-side walking-route, not an LLM tool.** `plan_walk` is PostGIS over the cited place_ids. Removes a whole class of "agent picks a bad route" failure modes.

`[design]` Three numbered cards in a horizontal row with equal width, separated by hairline rules (no boxes/borders around the cards themselves). Each card: a large circled numeral (1/2/3) at the top in navy, a one-line title in brick-red, then 2–3 lines of body in ink. No icons. No drop shadows.

*Speaker notes*: "Three decisions worth flagging. First, the router gives us cost-aware dispatch with one env-var flip from free Gemma to paid GPT — that's the basis for the §13.6 cost-vs-quality study. Second, the citation contract is enforced at generation time, not as a post-hoc filter — the agent literally cannot return a response that fails verification. Third, walk planning is server-side, so the LLM doesn't have to do graph optimization."

---

#### Slide 7 — Two weeks to go

**Demo-ready → polished → graded.**

| Week | Work |
|---|---|
| **Week +1** | Frontend `EventSource` + map markers + flyTo. Fix `apps/web/Dockerfile`. Hand-grade 5 walks (§13.4). |
| **Week +2** | Free-vs-paid cost analysis, ~10 walks (§13.6). Final-report draft incl. agentic-engineering chapter (§13.7). 30-second demo video (§13.8). |
| **Deferred to v2** | Chronicling America / NYPL / NYC Open Data / MTA / NOAA. VPS deploy. On-device LLM. User study. |

`[design]` Two-row timeline. The first two rows (Week +1, Week +2) in normal navy/ink. The third row (Deferred to v2) styled at reduced opacity (~50%) with a small brick-red "v2" tag at the right edge. Hairline rules between rows. No table borders.

*Speaker notes*: "Two weeks left. The biggest user-visible piece is the frontend `EventSource` consumer that renders the walk on the map. Then qualitative eval over five walks, the free-vs-paid cost study, the report draft, and a 30-second demo video. Five live data sources and the VPS deploy are explicitly deferred to v2 — they're spec-tracked, not abandoned."

---

#### Slide 8 — The agentic engineering angle (and Q&A)

**The codebase is itself a dataset.**

- Built end-to-end by Claude Code under one human reviewer.
- Every session is captured to `logs/claude-sessions/*.jsonl` — prompt tokens, completion tokens, files touched, outcome, cost.
- The final report has a chapter quantifying the **cost, cycle time, and failure modes** of agentic software engineering against a non-trivial real-world spec.
- That dataset is itself a "Big Data and AI" artifact for E6895.

**Questions?**

`[design]` Title and subtitle in the upper third. Bullets in the middle third, single column, generous line-height. Bottom third: the word **Questions?** centered in big serif brick-red. A subtle palimpsest texture (faint horizontal scrape lines) covers the entire slide background at <8% opacity.

*Speaker notes*: "One thing that's unusual about this project: it's been written end-to-end by Claude Code under a single human reviewer. Every session — every prompt, every tool call, every cost — is logged to JSONL. So the final report won't just describe the system; it'll quantify what it cost to build, how long each phase took, and where the agent failed. That dataset is itself a Big Data artifact for the course. Happy to take questions."

---

### Optional appendix slides (only render slides 9–11 if I tell you to; otherwise omit)

#### A1 — Citation contract (the locked JSON)

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

#### A2 — Why kimi-k2.6 takes 5 minutes per walk

- Extended-thinking model: ~50–100s/turn just on reasoning tokens.
- Final-turn `max_tokens=8192` so reasoning + JSON output both fit.
- One env-var flip to a non-thinking model collapses end-to-end latency to ~30s with no code change. That's the §13.6 paid-eval setup.

#### A3 — Risk register

| Risk | Mitigation |
|---|---|
| Free Gemma slug rate-limited or renamed | All references env-driven; one-line `.env` flip |
| 384-dim retrieval quality insufficient | Drop+recreate column at 768-dim; small migration |
| Plain-SQL migrations unwieldy | Eight headroom; switching to Alembic is a port, not a rewrite |
| Single-tool agent reads as "less agentic" | Demo highlights iterative `search_places` refinement + the server-side walk |

---

### Build instructions (final pass before you produce the artifact)

1. Render slides 1–8 in order. Skip the appendix unless told otherwise.
2. Use the exact color palette and font stack above. Do not introduce other colors or fonts.
3. Implement the keyboard nav, slide counter, progress bar, and speaker-notes toggle as specified.
4. Inline SVG for the architecture diagram (slide 4) and the bbox map + citation pills (slide 3). No external image URLs.
5. Make the deck print cleanly to PDF with one slide per page; speaker notes must NOT print.
6. Include a `<title>` of `Palimpsest NYC — Milestone 1`.
7. Validate that all slides fit at 1280×720 without scrolling. If a slide overflows, reduce body copy rather than shrinking the title.

When you're done, output **only the artifact** — no commentary, no recap.

---

## Notes for the presenter (NOT slide content; for me, not for Claude)

- **Open the talk by naming the problem, not the project.** "LLMs are confident liars about places" lands harder than "we built a thing".
- **Keep one slide on numbers, one on the trace.** Don't dilute either.
- **The agentic engineering angle is the differentiator** for E6895 specifically — don't bury it on slide 8; if you have only 4 minutes, demote slide 6 (decisions) and keep slide 8.
- **If a demo is allowed**: skip slide 5's numbers table and live-run the curl SSE call instead. The event stream is more compelling than a static excerpt.
- **If asked about hallucination**: point at the citation contract slide. "The agent cannot emit a response that doesn't pass the verifier; if it tries, it gets one corrective retry, then we surface a visible uncertainty warning."
- **If asked about scale**: be honest. 928 places is small. The architecture is the same at 100× — pgvector ivfflat + bbox filter scales linearly with the corpus.
