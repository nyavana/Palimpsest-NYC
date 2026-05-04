# Map QoL — 2D/3D toggle + marker info popups

**Date:** 2026-05-04
**Scope:** `apps/web` only. No backend, SSE, or schema changes.
**Locked invariants preserved:** five-field Citation contract; `maplibre-gl` imports stay inside `apps/web/src/map/engines/`.

## 1. Problem

Two QoL gaps on the map pane:

1. **Fixed tilt.** The map ships with `pitch: 60`, but the v1 raster is flat OSM — there are no extruded buildings, so the tilt buys nothing visually and makes label reading harder. Users can already rotate via MapLibre's compass and right-click drag, so rotation needs no new UI; only a flat-vs-tilted toggle is missing.
2. **Inert markers.** Walk stops render as red dots whose only metadata is a browser `title` tooltip ("N. Name"). The user pane already shows the stop list, but the markers themselves don't tell the user anything about a place — name, picture, source — even though most data is already on the wire and Wikipedia summaries are one fetch away.

## 2. Goals / non-goals

**Goals**

- Toggle the map between flat (pitch 0) and tilted (pitch 60). Persist the choice across reloads.
- On hover, show a lightweight name preview anchored to the marker.
- On click, pin a richer card with: name, source-type chip, Wikipedia thumbnail + 1-paragraph extract (when the doc is `wikipedia:`), and a click-through to the source URL. Click also flies the camera to the stop, mirroring the existing `WalkTimeline` button.
- Keep the engine boundary intact: components never import `maplibre-gl` directly.

**Non-goals**

- True 3D building extrusion (deferred to v2 per existing notes).
- Backend enrichment of `PlannedStop` with image/summary fields. Out of scope; uses client-side Wikipedia REST only.
- Mobile-first redesign. Touch falls back to click-only naturally.
- Caching Wikipedia data to disk; the cache is module-scoped and resets on reload.
- Thumbnails / summaries for `osm:` or `wikidata:` stops in v1 (lean fallback only).

## 3. Engine surface additions

Add four members to `MapEngine` (impl in `MaplibreEngine`, stubbed with `NotImplementedError` in `GoogleTilesEngine`):

```ts
type MarkerEvent = { layerId: string; markerId: string; at: LatLng };

onMarkerHover(cb: (e: MarkerEvent | null) => void): Unsubscribe;
onMarkerClick(cb: (e: MarkerEvent) => void): Unsubscribe;
setPopup(at: LatLng, el: HTMLElement, opts?: { offsetPx?: number }): void;
clearPopup(): void;
```

`MarkerEvent` is added to `apps/web/src/map/types.ts`. No changes to `Marker`, `PathStyle`, or `Viewport`.

`MaplibreEngine` implementation:

- In `addMarkers`, attach `mouseenter`, `mouseleave`, `click` listeners to each marker's `el` (the div the engine already creates). Maintain a single hovered-id pointer and emit a stream that goes `null` when nothing is hovered.
- `setPopup` constructs `new maplibregl.Popup({ closeOnClick: false, closeButton: false, offset: opts?.offsetPx ?? 14 })`, replaces any prior popup, sets DOM via `setDOMContent(el)`, and adds it to the map. The element is supplied by React (portal mount).
- `clearPopup` removes the current popup if any; idempotent.
- All four follow the existing `requireMap()` discipline → `MapEngineLifecycleError` if called before init / after destroy.
- The 2D/3D toggle uses the existing `flyTo` — no new method needed.

## 4. 2D/3D toggle

New component `apps/web/src/components/MapViewModeToggle.tsx`. Mounted as an absolute-positioned overlay inside the same wrapper as `<MapView>`, top-left corner.

Two segmented buttons "2D" / "3D"; the active button uses `bg-oxblood text-parchment`, the other is outlined — same vocabulary as existing project buttons.

Behavior:

- The active mode is held in React state and persisted to `localStorage` under `palimpsest.map.viewMode` (values `"2d"` | `"3d"`; missing or invalid → `"3d"`).
- A small storage helper module (co-located in the toggle file) reads/writes safely with try/catch (covers private-browsing or SSR cases — no-op fallback).
- `MapView` reads the saved value at mount and passes the corresponding pitch into `engine.init(...)` (replacing the hard-coded `pitch: 60` in `DEFAULT_VIEWPORT`). `DEFAULT_VIEWPORT` retains its current shape; `MapView` overrides the `pitch` field at init time only.
- On toggle: read the last camera state (held in a `useRef`, populated by `engine.onCameraChange`), then `engine.flyTo({...current, pitch: nextPitch}, 600)` where `nextPitch` is `0` for 2D and `60` for 3D. Bearing is preserved.

## 5. Marker info popup

State machine in `MapView`:

```ts
type MarkerFocus =
  | { kind: 'idle' }
  | { kind: 'hover'; markerId: string; at: LatLng }
  | { kind: 'pinned'; markerId: string; at: LatLng };
```

Transitions:

| From | Event | To |
| --- | --- | --- |
| idle | hover-enter | hover |
| hover | hover-leave | idle |
| hover | click | pinned (+ fly-to) |
| pinned | click on different marker | pinned (new marker, + fly-to) |
| pinned | click "X" / Escape | idle |
| pinned | hover-enter on any marker | unchanged (hover preview suppressed while pinned) |

Rationale for suppressing hover while pinned: a user reading a pinned popup who happens to mouse near another marker should not have their reading material yanked away. Switching popups is an explicit click.

The popup element is created once by `MapView` (a stable `<div>` referenced via `useRef`). React renders the card into it via `createPortal`. When state moves to `hover` or `pinned`, `MapView` calls `engine.setPopup(at, el)`. When state moves to `idle`, `engine.clearPopup()`.

**Card variants** rendered by `MarkerInfoCard.tsx`:

- **Hover preview.** Stop number badge (1-based, matching `WalkTimeline`'s `stop.index + 1`) + name. ~200×80px, no fetch, mounts immediately.
- **Pinned full.** Header (number + name), source-type chip from existing `sourceTypeColor`, body, footer with external link to `citation.source_url`, "X" close button. Body content depends on the doc:
  - `wikipedia:` doc — 96px-square thumbnail (when present) and the 1-paragraph extract from the Wikipedia REST summary endpoint. While loading, the existing `LoadingSkeleton` component is used.
  - `osm:` / `wikidata:` doc — the citation `span` snippet, no image.
  - No matching citation (defensive) — name only.

**Click → fly-to:** on transition to `pinned`,

```ts
engine.flyTo({
  center: at,
  zoom: Math.max(currentZoom, 17.5),
  pitch: currentPitch,
}, 1200);
```

Pitch is preserved so 2D-mode users don't get tilted unexpectedly.

**Dismiss surfaces:**

- "X" button on the pinned card.
- Escape key (window-level listener active only while a popup is `pinned`).
- Clicking another marker (transitions, doesn't dismiss).
- Map background click is *not* a dismiss surface in v1 — pan/zoom should not accidentally close a card the user is reading.

## 6. Wikipedia summary fetch

New hook in `apps/web/src/state/useWikipediaSummary.ts`:

```ts
type WikipediaSummary = {
  title: string;
  extract: string;        // 1-paragraph plain text
  thumbnailUrl: string | null;
  pageUrl: string;
};

type FetchState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; summary: WikipediaSummary }
  | { status: 'error' };

function useWikipediaSummary(docId: string | null): FetchState;
```

- **Slug derivation.** If `docId` starts with `wikipedia:`, slug = the remainder. Otherwise the hook stays in `idle` and the popup falls back to the citation `span`.
- **Endpoint.** `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(slug)}`. No API key. Sends `Accept: application/json; charset=utf-8; profile="https://www.mediawiki.org/wiki/Specs/Summary/1.4.2"`. Pulls `title`, `extract`, `thumbnail?.source`, `content_urls.desktop.page`.
- **Cache.** A module-level `Map<docId, Promise<WikipediaSummary>>` so repeat hovers don't re-fetch and concurrent callers share one in-flight Promise. Cleared only on full page reload — Wikipedia content can change, and a session-scoped re-fetch is cheap.
- **Triggering.** The fetch fires on first non-idle render (i.e. when `docId` first arrives as a `wikipedia:` value).
- **Errors.** Any non-2xx, malformed body, or network error → `error` state. The popup renders the lean fallback (citation span + source link). One `console.warn` per slug. No retry. The hook checks an `aborted` ref before `setState` to avoid setting state after the popup unmounts mid-fetch.

## 7. Data wiring

`App.tsx` already has `session.state.walk` and `session.state.citations`. Today only `walk` reaches `<MapView>`. Pass both:

```tsx
<MapView stops={session.state.walk} citations={session.state.citations} />
```

`MapView` builds a memoized `Map<doc_id, Citation>`. The map is built by iterating `citations` once and keeping the *first* citation per `doc_id` (lowest `retrieval_turn`, then lowest position in the array) — this is deterministic and avoids any thrash when multiple turns cite the same document with different spans. On marker click/hover, the marker id (already `stop-${index}`) maps to a `PlannedStop` by index; the citation is looked up by `stop.doc_id`. Both are passed to `MarkerInfoCard`.

If a stop has no matching citation (rare — walk stops are only built for cited docs), the card renders the lean variant with name only.

## 8. File changes

| File | Action | Notes |
| --- | --- | --- |
| `apps/web/src/map/MapEngine.ts` | edit | add 4 method signatures (§3) |
| `apps/web/src/map/types.ts` | edit | add `MarkerEvent` |
| `apps/web/src/map/engines/MaplibreEngine.ts` | edit | implement events + popup; attach DOM listeners in `addMarkers` |
| `apps/web/src/map/engines/GoogleTilesEngine.ts` | edit | stub the new methods with `NotImplementedError` |
| `apps/web/src/components/MapView.tsx` | edit | host toggle, popup state machine, portal mount, pass camera state through `useRef` |
| `apps/web/src/components/MapViewModeToggle.tsx` | new | 2D/3D segmented buttons + storage helpers |
| `apps/web/src/components/MarkerInfoCard.tsx` | new | hover preview + pinned variants |
| `apps/web/src/state/useWikipediaSummary.ts` | new | hook + module cache |
| `apps/web/src/App.tsx` | edit | thread `citations` prop into `<MapView>` |
| `apps/web/eslint.config.mjs` | check | confirm new files comply with the maplibre-import restriction |

No new env vars. No package additions.

## 9. Error handling

| Surface | Failure mode | Behavior |
| --- | --- | --- |
| Wikipedia REST | non-2xx, malformed body, network | popup shows lean variant; one `console.warn` per slug |
| Marker event for unknown id | stale id after walk replaced | no-op; `console.warn` |
| Marker has no matching citation | defensive | lean card with name only |
| Engine method pre-init / post-destroy | existing | `MapEngineLifecycleError` via `requireMap()` |
| `localStorage` unavailable | SSR / private mode | guarded read/write; default to 3D silently |
| Popup unmounts mid-fetch | race | hook checks `aborted` ref before `setState` |

## 10. Testing plan

Per repo rules (vitest in `apps/web`, Playwright for E2E, 80% coverage target).

**Unit (vitest):**

- `MaplibreEngine` — hover/click events emit `MarkerEvent` with correct id and `at`; `setPopup` then `setPopup` replaces the prior popup; `clearPopup` is idempotent; new methods throw `MapEngineLifecycleError` after `destroy`. Stubbed `maplibregl` via `vi.mock`.
- `useWikipediaSummary` — slug derivation; non-`wikipedia:` doc stays in `idle`; cache dedup (two callers share one in-flight Promise); error → `error`; aborted-mid-fetch does not call `setState`.
- Storage helpers in `MapViewModeToggle` — get/set under SSR-safe guards; missing/invalid value returns default.

**Component (vitest + Testing Library):**

- `MarkerInfoCard` — renders all five states: hover preview, pinned-loading, pinned-success (with thumbnail), pinned-error fallback (span + link), pinned-no-citation (name only).
- `MapViewModeToggle` — click flips active state and writes to localStorage; initial state respects existing localStorage value.
- `MapView` — `vi.mock` the engine; assert hover-enter mounts a popup; click pins it and invokes `flyTo`; Escape clears.

**E2E (Playwright, `apps/web/tests/e2e/`):**

- Plan a walk by typing in the composer → wait for markers → hover a marker → assert preview text contains the stop name → click → assert pinned card is present (close button visible) and the camera moved. Press Escape → popup gone.
- Toggle 2D ↔ 3D and assert the map's pitch updates. Reload and assert persistence.

## 11. Out of scope (explicit)

- True 3D building extrusion.
- Backend enrichment of `PlannedStop`.
- Wikipedia caching beyond the session.
- Image / summary support for non-Wikipedia stops.
- Mobile-specific UI redesign.

## 12. Open risks

- **Wikipedia REST availability.** If the public endpoint is rate-limited or blocked from the user's network, every popup falls back to the lean variant. Acceptable degradation.
- **Marker id collisions across walks.** Walks are replaced wholesale, so this is a non-issue, but the `MarkerFocus` state must be cleared whenever `stops` changes — covered by the existing `useEffect` on `[stops, ready]` in `MapView`.
- **`createPortal` into engine-owned DOM.** The engine's popup container is owned by MapLibre and could be re-created on style change. v1 doesn't change styles after init, so this is fine, but a future style swap would need to reset the popup wiring.
