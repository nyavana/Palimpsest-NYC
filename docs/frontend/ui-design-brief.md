# Palimpsest NYC — V1 UI Design Brief

> Source of truth for the v1 frontend visual direction. Generated through the
> `/ui-ux-pro-max:ui-ux-pro-max` skill (`action: design`, stack `React + Tailwind`,
> product `agentic walking-tour app`) per design.md §8 and tasks.md §12.5.1.
> Implementation in §12.5.2–12.5.3 must reference this file. The token module at
> `apps/web/src/styles/tokens.ts` is the code mirror of §3 below.

## 1. Aesthetic intent

Palimpsest NYC's narrations are stitched together from public-domain archives
(Wikipedia, Wikidata, OpenStreetMap), and the product name itself names a
manuscript whose old text shows through under the new. The visual direction
follows that brief literally rather than chasing the default "AI-app aesthetic"
of gray cards, muted purples, and Inter-everywhere.

Three constraints fall out of that:

- **Editorial, not generic LLM**. Serif for headlines and pull-quotes (IBM Plex
  Serif), humanist sans for UI (Inter), monospaced for `doc_id` and other
  identifiers (IBM Plex Mono). No pink/purple AI gradients (anti-pattern called
  out by the design skill).
- **Parchment and ink, not white-on-gray**. Background is a warm off-white
  (`parchment` `#f5f0e6`); foreground is true ink (`ink` `#0a0a0a`). All cards
  sit on parchment, separated by thin ink-tinted hairlines instead of drop
  shadows.
- **One archival accent**. A brick / oxblood that echoes Morningside-Heights
  brownstones and the Low Memorial Library facade, used for the primary CTA and
  the active stop on the walk. Citation links pick up an archival-blue
  reminiscent of Wikipedia source links — different role from the CTA, so users
  never have to guess which color means "act" vs. which means "go read".

These choices are the v1 tokens in §3. They are intentionally narrow so the
implementation cannot drift back into a generic palette.

## 2. Layout grid

The product is a split-pane: map fills the main pane, chat lives in the aside.
Spacing is on a 4 px rhythm (Tailwind defaults), with the larger steps coming
from a 4-pt scale: `4 8 12 16 24 32 48 64`.

### 2.1 Desktop (≥1024 px)

```
┌──────────────────────────────────────────┬──────────────────────┐
│                                          │  Header                │
│                                          │  (project title +     │
│              MapView (flex-1)            │   region label)       │
│                                          ├───────────────────────┤
│                                          │                       │
│  ┌── floating header ──────────┐         │   Narration stream    │
│  │ Palimpsest NYC              │         │   (scrolls)           │
│  │ Morningside Heights & UWS   │         │                       │
│  └─────────────────────────────┘         │                       │
│                                          ├───────────────────────┤
│                                          │   Citations           │
│                                          │   (cards)             │
│                                          ├───────────────────────┤
│                                          │   Walk timeline       │
│                                          │   (stops + fly-to)    │
│                                          ├───────────────────────┤
│                                          │   Composer            │
│                                          │   (textarea + Ask)    │
└──────────────────────────────────────────┴───────────────────────┘
                  flex-1                            w-[28rem]
```

- Aside width: `w-[28rem]` (448 px). Wider than the previous `w-96` so a
  three-line citation snippet doesn't wrap badly. Border is one hairline of
  `ink/15` on the left edge — no shadow.
- Map fills the rest. The floating header inside the map is a parchment chip
  with `ink/85` translucency so it reads against satellite or street tiles.
- Aside is one column with five vertical zones (header / stream / citations /
  walk / composer). Each zone separates from its neighbors with a 1 px
  `ink/10` divider, never with a card border + shadow.

### 2.2 Mobile (< 1024 px) — V1 graceful, not pixel-tuned

The course demo runs on a laptop, so V1 doesn't ship a hand-tuned mobile
layout. Instead, on viewports `<lg` the aside collapses below the map (full
width, max-h-[60vh] scrollable). This keeps the demo presentable on a phone
without committing to phone-tuned tap targets. A real mobile pass is v2.

### 2.3 Z-index scale

`0 / 10 / 20 / 40 / 100`:
- `0` map canvas
- `10` map overlays (path, markers)
- `20` floating header chip
- `40` warning banner
- `100` modal/toast (none in V1)

## 3. Tokens (mirror of `apps/web/src/styles/tokens.ts`)

### 3.1 Color

| Token | Hex | Role |
|---|---|---|
| `parchment` | `#f5f0e6` | base background |
| `parchment-deep` | `#ece5d5` | secondary/elevated surface (citations, composer) |
| `ink` | `#0a0a0a` | primary text & icons |
| `ink-soft` | `#3a3a3a` | secondary text, captions |
| `ink-muted` | `#6f6a5f` | tertiary, helper text, leg-distance labels |
| `hairline` | `rgba(10,10,10,0.10)` | dividers |
| `oxblood` | `#7a1f1f` | primary CTA, active walk stop |
| `oxblood-hover` | `#5e1717` | CTA hover/pressed |
| `archival-blue` | `#1d4ed8` | citation source links |
| `archival-blue-visited` | `#5b21b6` | visited source link |
| `ochre` | `#b6873e` | warnings (verifier failure, retry) |
| `success` | `#3b6e3b` | verified-citations confirmation |
| `wikipedia` | `#36c` | source-type chip: Wikipedia |
| `wikidata` | `#990000` | source-type chip: Wikidata |
| `osm` | `#7ebc6f` | source-type chip: OpenStreetMap |

`hairline` is a translucent ink so it works equally on parchment and
parchment-deep. The three source-type chip colors come from each project's own
brand palette so the chip reads as "this came from there", not as a Palimpsest
choice.

### 3.2 Typography

| Token | Family | Use |
|---|---|---|
| `font-serif` | IBM Plex Serif | headlines, narration body |
| `font-sans` | Inter | UI, secondary copy, buttons |
| `font-mono` | IBM Plex Mono | `doc_id`, `retrieval_turn`, code-like glyphs |

Type scale (rem):

| Step | rem / px | Use |
|---|---|---|
| `display` | 1.5 / 24 | floating header title |
| `h2` | 1.25 / 20 | aside section labels (Narration, Citations…) |
| `body` | 0.9375 / 15 | narration body, default UI |
| `small` | 0.8125 / 13 | citation snippet, helper text |
| `mono` | 0.75 / 12 | doc_id, retrieval_turn |

Line-height: 1.6 for narration body (long-form readability), 1.45 for UI
copy, 1.2 for monospaced identifiers. Letter-spacing default; `tracking-wide`
only on the all-caps source-type chip.

### 3.3 Radius, weight, shadow

- Corner radius: a single `radius` token of `4 px` (sharp, editorial). No
  larger pill or `rounded-2xl` cards; that's an LLM-app trope we're avoiding.
- Weight: `400` body, `500` UI labels, `600` headings. No `700/800` heavy
  weights.
- Shadow: **none.** Elevation is conveyed by `parchment-deep` + `hairline`,
  not drop shadow. The one exception is the floating map header, which uses
  a soft `0 1 8 rgba(0,0,0,0.12)` so it reads on bright tiles.

### 3.4 Motion

| Token | ms | Use |
|---|---|---|
| `dur-fast` | 120 | hover state, focus ring, button press |
| `dur-base` | 200 | small layout transitions, citation card reveal |
| `dur-slow` | 1200 | map fly-to per stop |

Easing: `ease-out` for entries, `ease-in` for exits. Streamed narration tokens
fade in via opacity over `dur-fast`; no per-letter typewriter effect (it
fights with browser text-rendering). All animations honour
`prefers-reduced-motion: reduce` — they collapse to a 0 ms switch.

## 4. Component inventory

Each entry calls out the component's role, its props at the React level, and
the SSE frame(s) it reads.

### 4.1 `AppShell`

Two-column flex layout from §2.1. Owns the global `AgentSession` state (see
§5). No props.

### 4.2 `MapView`

Existing (`apps/web/src/components/MapView.tsx`). The 12.5.3 task wires its
`addPath`, `addMarkers`, and `flyTo` to a `walk` payload. Always behind the
`MapEngine` interface — no `maplibre-gl` imports outside `engines/`.

### 4.3 `ChatPane` (rewritten in 12.5.2)

Stack of:
1. `PaneHeader` — title + region.
2. `NarrationStream`
3. `CitationList`
4. `WalkTimeline`
5. `Composer`

The pane reads from a single `useAgentSession()` hook so each subsection only
sees the slice of state it needs.

### 4.4 `Composer`

A textarea + button row.

- Textarea: `font-sans body`, ink on parchment, 3 lines tall, autosize up to
  6, `min-h-[44px]` so the tap target is honest. Border is `hairline` not
  `rounded`. Focus state: `ring-2 ring-ink/40 ring-offset-2 ring-offset-parchment`.
- Submit button: `bg-oxblood text-parchment hover:bg-oxblood-hover`,
  `rounded-[4px]`, `px-4 py-2`, `font-sans medium`.
- Disabled while a session is in flight; shows `Asking…` with a small spinner
  glyph (`<svg>` from Lucide; never an emoji).
- Submit on `Cmd/Ctrl + Enter`. Plain `Enter` inserts a newline because users
  are likely to paste multi-line questions.

### 4.5 `NarrationStream`

Renders streamed narration tokens as they arrive on `event: narration`.

- Container: `font-serif body`, `leading-relaxed`, `text-ink`,
  `max-w-prose` so lines stay 60–72 ch.
- Tokens append; new tokens fade in over `dur-fast`. The whole block is
  rendered as plain text — no markdown — because the agent's prompt contract
  emits prose, not markdown.
- A small ticker above the narration shows the current `turn` and the most
  recent `tool_call.name`, both in `font-mono mono text-ink-muted`. This is
  what makes the demo legible: graders see the agent thinking. It collapses
  to invisible on `done`.

### 4.6 `CitationCard`

Renders one item from `event: citations[]`. The strict five-field contract is
on the card so anyone evaluating the demo can audit it directly:

```
┌──────────────────────────────────────────────────────────┐
│  ┌───────────┐                                           │
│  │ wikipedia │   Cathedral of Saint John the Divine ↗   │
│  └───────────┘                                           │
│                                                          │
│  "begun in 1892 in the Romanesque Revival style…"       │
│                                                          │
│  doc_id  wikipedia:Cathedral_of_Saint_John_the_Divine   │
│  span    1-2   ·   retrieval_turn  2                    │
└──────────────────────────────────────────────────────────┘
```

- Surface: `bg-parchment-deep` + 1 px `hairline` border, no shadow.
- Source-type chip: top-left, `font-mono mono`, `tracking-wide`,
  background = source-type token, foreground = white. Three values only:
  `wikipedia | wikidata | osm`.
- Title: `font-serif h2`, ends with a trailing `↗` icon. The whole title is
  the link to `source_url`, opens in a new tab, `archival-blue`, underline on
  hover.
- Snippet (preview of `span`): `font-serif small italic` between curly quotes,
  capped at 2 lines (`line-clamp-2`).
- Metadata row: `doc_id`, `span`, `retrieval_turn` in `font-mono mono`,
  `text-ink-muted`. `doc_id` is selectable (long press / triple-click) so a
  reviewer can copy it to verify against the corpus.

### 4.7 `WalkTimeline`

Renders `event: walk.stops[]` as a numbered list. One stop per line:

```
①  Cathedral of Saint John the Divine          fly to →
    0 m

②  Riverside Park (UWS section)                fly to →
    760 m  ·  ~10 min
```

- Numbers in serif `display` weight 600 inside an oxblood roundel for the
  active stop, ink for others.
- Distance row in `font-mono mono`, `ink-muted`. Walking time = `leg / 80
  m·min⁻¹` rounded to nearest minute, hidden when leg is 0.
- "fly to" is a button on the row (icon-button with text label, `font-sans`,
  `ink`) that calls `engine.flyTo(stop)` through the MapEngine handle from
  `MapView`. Active stop highlights the row with `bg-parchment-deep` and the
  oxblood roundel.
- Pressing a stop also pulses its marker on the map for `dur-base`.

### 4.8 `WarningBanner`

Renders `event: warning` (verifier failure, plan_walk failure, turn-cap hit).

- Inline in the aside, above the narration. Background `bg-parchment-deep`,
  left border 3 px `ochre`, `font-sans body`, `text-ink`. Dismissable but
  defaults to staying visible — these warnings matter for the demo.

### 4.9 `LoadingSkeleton`

Displayed before the first SSE frame (`turn` 1) arrives. Three rows of
skeleton lines using `bg-hairline` + `animate-pulse`. Reduced-motion users see
a static ink-tinted bar instead of a pulse.

## 5. Session state model

A single `useAgentSession()` hook owns the session reducer:

```ts
type SessionState = {
  status: "idle" | "asking" | "streaming" | "done" | "error";
  question: string | null;
  turn: number;
  lastToolCall: { name: string; args: unknown } | null;
  narration: string;
  citations: Citation[];
  walk: PlannedStop[];
  warnings: string[];
};
```

Each SSE event type maps to one reducer action. The hook owns:

- creating `EventSource` against `${VITE_API_BASE_URL}/agent/ask?q=…`,
- closing it on `done`, on `error`, and on unmount,
- exposing `ask(q)` and `cancel()` to the composer.

This keeps every visual component a pure function of `SessionState`.

## 6. Interaction primitives

- **Focus rings**: 2 px solid, `ink/40`, with 2 px offset on parchment. Never
  removed. This is the single most "make it feel finished" rule.
- **Buttons**: 44 px min height. Hover transitions `dur-fast`. Pressed state
  uses `bg-oxblood-hover`, no scale.
- **Links**: archival-blue, no underline at rest, underline on hover/focus.
  Visited links shift to `archival-blue-visited`.
- **Scrolling**: each aside zone scrolls independently when its content
  overflows; the composer is sticky to the bottom of the aside.
- **Reduced motion**: `prefers-reduced-motion: reduce` collapses fly-to to
  `setViewport`, and disables narration token fade-in and skeleton pulse.

## 7. Accessibility budget

V1 ships these and is honest about not shipping more:

- Color contrast ≥ 4.5:1 for all body text on its surface (verified for
  `ink/parchment`, `ink/parchment-deep`, `oxblood/parchment`, `archival-blue
  /parchment-deep`).
- Visible focus rings on every interactive element.
- All icons are SVG (Lucide); no emoji.
- The composer textarea has a programmatic label.
- `prefers-reduced-motion` honoured globally.
- Walk timeline buttons and citation links are keyboard-reachable; tab order
  follows visual order.

Out-of-scope for V1, tracked for v2: aria-live on the narration stream
(currently announces in chunks; needs polite live region tuning), full
screen-reader narration rehearsal, RTL.

## 8. Anti-patterns we are avoiding

Pulled directly from the design-skill output and from the EECS-demo failure
modes we want to dodge:

- AI-purple / pink gradients.
- Over-rounded `rounded-2xl` cards.
- Drop-shadowed cards stacked on a white background.
- Emoji used as icons.
- Inter-only typography (no serif anywhere).
- Generic "ChatGPT clone" three-column layouts.
- Animating `width` / `height` (use transform/opacity).
- Hover-only affordances (everything must be obvious without hovering).

## 9. Hand-off

- Tokens implementation: `apps/web/src/styles/tokens.ts`
- Tailwind theme extension: `apps/web/tailwind.config.ts` (extended with the
  tokens above).
- Component implementation: §12.5.2 (chat / narration / citations) and
  §12.5.3 (map walk rendering).
- Review pass: `/ui-ux-pro-max:ui-ux-pro-max` `action: review` after the
  surface compiles, per §12.5.4.
