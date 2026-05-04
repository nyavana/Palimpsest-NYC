# Map QoL — 2D/3D toggle + marker info popups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 2D/3D pitch toggle and hover/click info popups to the walk-tour map in `apps/web`, with Wikipedia REST enrichment for `wikipedia:` doc_ids.

**Architecture:** Four small additions to the `MapEngine` interface (`onMarkerHover`, `onMarkerClick`, `setPopup`, `clearPopup`); `MaplibreEngine` implementation factored through a new test-friendly `MarkerEventBus` helper that works on plain DOM (no maplibre dep) so events can be unit-tested in JSDOM. React owns popup content via `createPortal` into a stable element handed to `engine.setPopup`. A new `useWikipediaSummary` hook lazy-fetches summaries from `/api/rest_v1/page/summary/{title}` with a module-level Promise cache.

**Tech Stack:** TypeScript, React 18, Vite 5, MapLibre GL 4, Tailwind. **New dev deps to install:** `vitest`, `@vitest/ui`, `@testing-library/react`, `@testing-library/dom`, `@testing-library/user-event`, `@testing-library/jest-dom`, `jsdom`.

**Spec:** `docs/superpowers/specs/2026-05-04-map-qol-toggle-and-marker-popups-design.md`

---

## File Structure

| Path | Status | Responsibility |
| --- | --- | --- |
| `apps/web/package.json` | modify | add vitest + RTL devDeps and `test` / `test:watch` scripts |
| `apps/web/vitest.config.ts` | new | vitest config (jsdom env, alias, setup file) |
| `apps/web/src/test/setup.ts` | new | RTL jest-dom matchers, global fetch reset |
| `apps/web/eslint.config.mjs` | modify | add vitest globals (`describe`, `it`, `expect`, `vi`) |
| `apps/web/src/map/types.ts` | modify | add `MarkerEvent` |
| `apps/web/src/map/MapEngine.ts` | modify | add 4 method signatures |
| `apps/web/src/map/engines/MarkerEventBus.ts` | new | DOM-only marker event tracker (testable without maplibre) |
| `apps/web/src/map/engines/MarkerEventBus.test.ts` | new | unit tests for the bus |
| `apps/web/src/map/engines/MaplibreEngine.ts` | modify | wire bus in `addMarkers`; add `setPopup`/`clearPopup` |
| `apps/web/src/map/engines/GoogleTilesEngine.ts` | modify | stub the 4 new methods with `NotImplementedError` |
| `apps/web/src/state/useWikipediaSummary.ts` | new | hook + module-level Promise cache |
| `apps/web/src/state/useWikipediaSummary.test.ts` | new | unit tests for the hook |
| `apps/web/src/components/MapViewModeToggle.tsx` | new | 2D/3D segmented buttons + storage helpers |
| `apps/web/src/components/MapViewModeToggle.test.tsx` | new | component + storage tests |
| `apps/web/src/components/MarkerInfoCard.tsx` | new | hover preview + pinned variants |
| `apps/web/src/components/MarkerInfoCard.test.tsx` | new | renders all variants |
| `apps/web/src/components/MapView.tsx` | modify | citations prop, popup state machine, portal mount, toggle host |
| `apps/web/src/components/MapView.test.tsx` | new | popup transitions, fly-to on click, toggle wiring |
| `apps/web/src/App.tsx` | modify | thread `citations` into `<MapView>` |

---

## Task 1: Bootstrap vitest + RTL

**Files:**
- Modify: `apps/web/package.json` (devDependencies + scripts)
- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/src/test/setup.ts`
- Modify: `apps/web/eslint.config.mjs` (add globals)

- [ ] **Step 1: Install dev dependencies**

Run from repo root:

```bash
cd apps/web && npm install --save-dev vitest@^2.1.0 @vitest/ui@^2.1.0 @testing-library/react@^16.0.0 @testing-library/dom@^10.4.0 @testing-library/user-event@^14.5.0 @testing-library/jest-dom@^6.5.0 jsdom@^25.0.0
```

Expected: install completes, `package.json` updated with devDeps.

- [ ] **Step 2: Add `test` scripts to `package.json`**

In `apps/web/package.json`, replace the `scripts` block to include test entries:

```json
"scripts": {
  "dev": "vite",
  "build": "tsc -b && vite build",
  "preview": "vite preview --port 5173",
  "lint": "eslint .",
  "format": "prettier --write \"src/**/*.{ts,tsx,css}\"",
  "typecheck": "tsc -b",
  "test": "vitest run",
  "test:watch": "vitest"
}
```

- [ ] **Step 3: Create `apps/web/vitest.config.ts`**

```ts
import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
```

- [ ] **Step 4: Create `apps/web/src/test/setup.ts`**

```ts
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.restoreAllMocks();
});
```

- [ ] **Step 5: Add vitest globals to ESLint config**

Edit `apps/web/eslint.config.mjs`. In the main config block, extend the `globals` map:

```js
globals: {
  window: "readonly",
  document: "readonly",
  console: "readonly",
  process: "readonly",
  HTMLElement: "readonly",
  HTMLDivElement: "readonly",
  // vitest globals (test files only — see file-specific override below)
  describe: "readonly",
  it: "readonly",
  expect: "readonly",
  vi: "readonly",
  beforeEach: "readonly",
  afterEach: "readonly",
  beforeAll: "readonly",
  afterAll: "readonly",
},
```

- [ ] **Step 6: Add a smoke test to verify the rig works**

Create `apps/web/src/test/smoke.test.ts`:

```ts
import { describe, it, expect } from "vitest";

describe("smoke", () => {
  it("vitest is wired up", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 7: Run the smoke test**

```bash
cd apps/web && npm test
```

Expected: passes, 1 test reported.

- [ ] **Step 8: Run typecheck and lint**

```bash
cd apps/web && npm run typecheck && npm run lint
```

Expected: both pass.

- [ ] **Step 9: Commit**

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/vitest.config.ts apps/web/src/test/setup.ts apps/web/src/test/smoke.test.ts apps/web/eslint.config.mjs
git commit -m "chore(web): bootstrap vitest + react testing library"
```

---

## Task 2: Add `MarkerEvent` type and extend `MapEngine` interface

**Files:**
- Modify: `apps/web/src/map/types.ts`
- Modify: `apps/web/src/map/MapEngine.ts`

- [ ] **Step 1: Add `MarkerEvent` to `apps/web/src/map/types.ts`**

After the `Marker` type definition, add:

```ts
/** Emitted by `MapEngine.onMarkerHover` and `onMarkerClick`. */
export type MarkerEvent = {
  layerId: string;
  markerId: string;
  at: LatLng;
};
```

- [ ] **Step 2: Add the four method signatures to `MapEngine`**

Edit `apps/web/src/map/MapEngine.ts`. Update the import line to include `MarkerEvent`:

```ts
import type { LatLng, Marker, MarkerEvent, PathStyle, Unsubscribe, Viewport } from "./types";
```

Inside the `MapEngine` interface, just before `onCameraChange`, add:

```ts
  /**
   * Subscribe to marker hover. The callback fires with the currently-hovered
   * marker, or `null` when no marker is hovered. Implementations debounce so
   * a single hover-leave/hover-enter pair across two markers emits two
   * events, not three.
   */
  onMarkerHover(cb: (e: MarkerEvent | null) => void): Unsubscribe;

  /** Subscribe to marker clicks. */
  onMarkerClick(cb: (e: MarkerEvent) => void): Unsubscribe;

  /**
   * Show a popup at `at` using `el` as the popup content. Replaces any
   * prior popup. The element is positioned by the underlying map and
   * follows pan/zoom/rotate.
   */
  setPopup(at: LatLng, el: HTMLElement, opts?: { offsetPx?: number }): void;

  /** Hide the popup if any. Idempotent. */
  clearPopup(): void;
```

- [ ] **Step 3: Re-export `MarkerEvent` from `apps/web/src/map/index.ts`**

Locate the `export type { ... } from "./types";` line and add `MarkerEvent`:

```ts
export type { LatLng, MapEngineKind, Marker, MarkerEvent, PathStyle, Unsubscribe, Viewport } from "./types";
```

- [ ] **Step 4: Run typecheck (will fail in engines until Task 3/4)**

```bash
cd apps/web && npm run typecheck
```

Expected: TS errors in `MaplibreEngine.ts` and `GoogleTilesEngine.ts` reporting missing methods. That's intentional — fixed in the next two tasks.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/map/types.ts apps/web/src/map/MapEngine.ts apps/web/src/map/index.ts
git commit -m "feat(web/map): extend MapEngine with marker events and popup methods"
```

(Note: this commit leaves the project in a non-typechecking state. The next two tasks restore green; we commit anyway to keep the interface change atomic.)

---

## Task 3: Stub the 4 new methods in `GoogleTilesEngine`

**Files:**
- Modify: `apps/web/src/map/engines/GoogleTilesEngine.ts`

- [ ] **Step 1: Add stubs to `GoogleTilesEngine.ts`**

Inside the `GoogleTilesEngine` class, after `onCameraChange`, add:

```ts
  onMarkerHover(_cb: (e: import("../types").MarkerEvent | null) => void): import("../types").Unsubscribe {
    throw new NotImplementedError(
      `GoogleTilesEngine.onMarkerHover is not implemented. ${UPGRADE_DOC_HINT}`,
    );
  }

  onMarkerClick(_cb: (e: import("../types").MarkerEvent) => void): import("../types").Unsubscribe {
    throw new NotImplementedError(
      `GoogleTilesEngine.onMarkerClick is not implemented. ${UPGRADE_DOC_HINT}`,
    );
  }

  setPopup(_at: LatLng, _el: HTMLElement, _opts?: { offsetPx?: number }): void {
    throw new NotImplementedError(
      `GoogleTilesEngine.setPopup is not implemented. ${UPGRADE_DOC_HINT}`,
    );
  }

  clearPopup(): void {
    // Safe no-op for parity with destroy().
  }
```

(Inline `import("../types").MarkerEvent` keeps the existing top-of-file import block tidy; keeping `LatLng` reference satisfies TypeScript without a new import.)

- [ ] **Step 2: Run typecheck**

```bash
cd apps/web && npm run typecheck
```

Expected: only `MaplibreEngine.ts` errors remain.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/map/engines/GoogleTilesEngine.ts
git commit -m "feat(web/map): stub new MapEngine methods in GoogleTilesEngine"
```

---

## Task 4: Build `MarkerEventBus` helper (TDD)

**Files:**
- Create: `apps/web/src/map/engines/MarkerEventBus.ts`
- Create: `apps/web/src/map/engines/MarkerEventBus.test.ts`

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/map/engines/MarkerEventBus.test.ts`:

```ts
import { describe, it, expect, vi } from "vitest";

import { MarkerEventBus } from "./MarkerEventBus";

function makeEl(): HTMLDivElement {
  return document.createElement("div");
}

describe("MarkerEventBus", () => {
  it("emits a click event with layerId, markerId, and at", () => {
    const bus = new MarkerEventBus();
    const onClick = vi.fn();
    bus.onClick(onClick);

    const el = makeEl();
    bus.attach("walk", "stop-0", el, { lat: 40.8, lng: -73.9 });
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(onClick).toHaveBeenCalledWith({
      layerId: "walk",
      markerId: "stop-0",
      at: { lat: 40.8, lng: -73.9 },
    });
  });

  it("emits hover events with the active marker, and null on leave", () => {
    const bus = new MarkerEventBus();
    const onHover = vi.fn();
    bus.onHover(onHover);

    const el = makeEl();
    bus.attach("walk", "stop-0", el, { lat: 1, lng: 2 });
    el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
    el.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true }));

    expect(onHover).toHaveBeenNthCalledWith(1, {
      layerId: "walk",
      markerId: "stop-0",
      at: { lat: 1, lng: 2 },
    });
    expect(onHover).toHaveBeenNthCalledWith(2, null);
  });

  it("emits one new hover event when moving from marker A to marker B", () => {
    const bus = new MarkerEventBus();
    const onHover = vi.fn();
    bus.onHover(onHover);

    const a = makeEl();
    const b = makeEl();
    bus.attach("walk", "a", a, { lat: 0, lng: 0 });
    bus.attach("walk", "b", b, { lat: 1, lng: 1 });

    a.dispatchEvent(new MouseEvent("mouseenter"));
    b.dispatchEvent(new MouseEvent("mouseenter"));
    a.dispatchEvent(new MouseEvent("mouseleave"));

    // Expect: A enter (hover=A), B enter (hover=B; A.leave is implicit), A.leave is no-op.
    expect(onHover).toHaveBeenCalledTimes(2);
    expect(onHover.mock.calls[0][0]).toEqual({ layerId: "walk", markerId: "a", at: { lat: 0, lng: 0 } });
    expect(onHover.mock.calls[1][0]).toEqual({ layerId: "walk", markerId: "b", at: { lat: 1, lng: 1 } });
  });

  it("detachAll removes all listeners and resets hover state", () => {
    const bus = new MarkerEventBus();
    const onHover = vi.fn();
    const onClick = vi.fn();
    bus.onHover(onHover);
    bus.onClick(onClick);

    const el = makeEl();
    bus.attach("walk", "stop-0", el, { lat: 0, lng: 0 });
    bus.detachAll();
    el.dispatchEvent(new MouseEvent("mouseenter"));
    el.dispatchEvent(new MouseEvent("click"));

    expect(onHover).not.toHaveBeenCalled();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("unsubscribe stops calls", () => {
    const bus = new MarkerEventBus();
    const onClick = vi.fn();
    const off = bus.onClick(onClick);

    const el = makeEl();
    bus.attach("walk", "stop-0", el, { lat: 0, lng: 0 });
    off();
    el.dispatchEvent(new MouseEvent("click"));

    expect(onClick).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/web && npm test -- MarkerEventBus
```

Expected: FAIL — "Cannot find module './MarkerEventBus'".

- [ ] **Step 3: Implement `MarkerEventBus`**

Create `apps/web/src/map/engines/MarkerEventBus.ts`:

```ts
/**
 * MarkerEventBus — DOM-only helper for marker hover/click events.
 *
 * Lives in `engines/` because it's an implementation detail of
 * `MaplibreEngine.addMarkers`. Pulled out as its own helper so the event
 * logic (especially the hover state machine) can be unit-tested in JSDOM
 * without instantiating a real maplibre map.
 */

import type { LatLng, MarkerEvent, Unsubscribe } from "../types";

type AttachedMarker = {
  layerId: string;
  markerId: string;
  el: HTMLElement;
  at: LatLng;
  cleanup: () => void;
};

export class MarkerEventBus {
  private markers = new Map<string, AttachedMarker>();
  private hovered: { layerId: string; markerId: string } | null = null;
  private hoverCbs = new Set<(e: MarkerEvent | null) => void>();
  private clickCbs = new Set<(e: MarkerEvent) => void>();

  attach(layerId: string, markerId: string, el: HTMLElement, at: LatLng): void {
    const key = this.keyOf(layerId, markerId);
    this.detach(key);

    const onEnter = () => {
      // Fire only if this is a new marker focus (suppress duplicate enters).
      if (this.hovered?.layerId === layerId && this.hovered.markerId === markerId) {
        return;
      }
      this.hovered = { layerId, markerId };
      this.emitHover({ layerId, markerId, at });
    };
    const onLeave = () => {
      if (this.hovered?.layerId === layerId && this.hovered.markerId === markerId) {
        this.hovered = null;
        this.emitHover(null);
      }
      // Otherwise a different marker has already taken focus — no-op.
    };
    const onClick = () => {
      this.emitClick({ layerId, markerId, at });
    };

    el.addEventListener("mouseenter", onEnter);
    el.addEventListener("mouseleave", onLeave);
    el.addEventListener("click", onClick);

    this.markers.set(key, {
      layerId,
      markerId,
      el,
      at,
      cleanup: () => {
        el.removeEventListener("mouseenter", onEnter);
        el.removeEventListener("mouseleave", onLeave);
        el.removeEventListener("click", onClick);
      },
    });
  }

  detachAll(): void {
    for (const m of this.markers.values()) {
      m.cleanup();
    }
    this.markers.clear();
    if (this.hovered !== null) {
      this.hovered = null;
      this.emitHover(null);
    }
  }

  onHover(cb: (e: MarkerEvent | null) => void): Unsubscribe {
    this.hoverCbs.add(cb);
    return () => {
      this.hoverCbs.delete(cb);
    };
  }

  onClick(cb: (e: MarkerEvent) => void): Unsubscribe {
    this.clickCbs.add(cb);
    return () => {
      this.clickCbs.delete(cb);
    };
  }

  private detach(key: string): void {
    const existing = this.markers.get(key);
    if (existing) {
      existing.cleanup();
      this.markers.delete(key);
    }
  }

  private keyOf(layerId: string, markerId: string): string {
    return `${layerId} ${markerId}`;
  }

  private emitHover(e: MarkerEvent | null): void {
    for (const cb of this.hoverCbs) {
      cb(e);
    }
  }

  private emitClick(e: MarkerEvent): void {
    for (const cb of this.clickCbs) {
      cb(e);
    }
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/web && npm test -- MarkerEventBus
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/map/engines/MarkerEventBus.ts apps/web/src/map/engines/MarkerEventBus.test.ts
git commit -m "feat(web/map): add MarkerEventBus for testable marker hover/click"
```

---

## Task 5: Wire `MarkerEventBus`, `setPopup`, `clearPopup` into `MaplibreEngine`

**Files:**
- Modify: `apps/web/src/map/engines/MaplibreEngine.ts`

- [ ] **Step 1: Update imports + class fields**

In `apps/web/src/map/engines/MaplibreEngine.ts`, expand the maplibre import to include `Popup`:

```ts
import maplibregl, {
  LngLatBoundsLike,
  Map as MaplibreMap,
  Marker as MlMarker,
  Popup as MlPopup,
  StyleSpecification,
} from "maplibre-gl";
```

Update the local imports:

```ts
import { MapEngine, MapEngineLifecycleError } from "../MapEngine";
import type { LatLng, Marker, MarkerEvent, PathStyle, Unsubscribe, Viewport } from "../types";
import { MarkerEventBus } from "./MarkerEventBus";
```

In the class body, add private fields after `private destroyed = false;`:

```ts
  private events = new MarkerEventBus();
  private popup: MlPopup | null = null;
```

- [ ] **Step 2: Wire the bus inside `addMarkers`**

Inside `addMarkers`, after the `for (const m of markers)` loop, attach to the bus. Replace the existing loop body to capture the marker id and lat/lng:

```ts
addMarkers(layerId: string, markers: Marker[]): void {
  const map = this.requireMap();
  const layerKey = MARKER_LAYER_PREFIX + layerId;
  this.clearLayer(layerId);
  const instances: MlMarker[] = [];
  for (const m of markers) {
    const el = document.createElement("div");
    el.className = "palimpsest-marker";
    el.style.width = "14px";
    el.style.height = "14px";
    el.style.borderRadius = "50%";
    el.style.background = m.color ?? "#0a0a0a";
    el.style.border = "2px solid #f5f0e6";
    el.style.boxShadow = "0 1px 4px rgba(0,0,0,0.3)";
    el.style.cursor = "pointer";
    if (m.label) {
      el.title = m.label;
    }
    const marker = new maplibregl.Marker({ element: el })
      .setLngLat([m.position.lng, m.position.lat])
      .addTo(map);
    instances.push(marker);
    this.events.attach(layerId, m.id, el, m.position);
  }
  this.markerLayers.set(layerKey, { instances });
}
```

(Two changes vs. existing: added `cursor: pointer` for affordance, and the `events.attach(...)` line.)

- [ ] **Step 3: Detach in `clearLayer` and `destroy`**

In `clearLayer`, after the marker layer cleanup block (after `this.markerLayers.delete(markerKey);`), the bus state for that layer no longer matters — `detachAll` is sufficient at destroy time, but per-layer detach keeps memory tidy. Add this after the existing marker layer block:

```ts
    // Bus listeners were attached on the (now-removed) marker DOM nodes.
    // Maplibre's Marker.remove() detaches the elements from the DOM, but
    // our listeners remain on the orphaned nodes — they'll be garbage
    // collected when nothing else holds them. detachAll on destroy below
    // handles the explicit teardown.
```

In `destroy`, add at the start (before clearing markerLayers):

```ts
  destroy(): void {
    if (this.map !== null) {
      this.events.detachAll();
      this.clearPopup();
      // ...existing body...
```

- [ ] **Step 4: Implement `onMarkerHover`, `onMarkerClick`**

After `onCameraChange`, add:

```ts
  onMarkerHover(cb: (e: MarkerEvent | null) => void): Unsubscribe {
    return this.events.onHover(cb);
  }

  onMarkerClick(cb: (e: MarkerEvent) => void): Unsubscribe {
    return this.events.onClick(cb);
  }
```

- [ ] **Step 5: Implement `setPopup` and `clearPopup`**

Add right after `onMarkerClick`:

```ts
  setPopup(at: LatLng, el: HTMLElement, opts?: { offsetPx?: number }): void {
    const map = this.requireMap();
    if (this.popup !== null) {
      this.popup.remove();
      this.popup = null;
    }
    const popup = new maplibregl.Popup({
      closeOnClick: false,
      closeButton: false,
      offset: opts?.offsetPx ?? 14,
      maxWidth: "320px",
    });
    popup.setLngLat([at.lng, at.lat]).setDOMContent(el).addTo(map);
    this.popup = popup;
  }

  clearPopup(): void {
    if (this.popup !== null) {
      this.popup.remove();
      this.popup = null;
    }
  }
```

- [ ] **Step 6: Run typecheck and lint**

```bash
cd apps/web && npm run typecheck && npm run lint
```

Expected: both pass.

- [ ] **Step 7: Run all tests**

```bash
cd apps/web && npm test
```

Expected: all tests pass (no new tests for `MaplibreEngine` itself; behavior is covered by the bus tests + later `MapView` tests).

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/map/engines/MaplibreEngine.ts
git commit -m "feat(web/map): implement marker events and popup in MaplibreEngine"
```

---

## Task 6: Build `useWikipediaSummary` hook (TDD)

**Files:**
- Create: `apps/web/src/state/useWikipediaSummary.ts`
- Create: `apps/web/src/state/useWikipediaSummary.test.ts`

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/state/useWikipediaSummary.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import {
  useWikipediaSummary,
  __resetWikipediaCacheForTests,
} from "./useWikipediaSummary";

const MOCK_RESPONSE = {
  title: "Cathedral of St. John the Divine",
  extract: "A cathedral in Manhattan.",
  thumbnail: { source: "https://upload.wikimedia.org/x.jpg" },
  content_urls: { desktop: { page: "https://en.wikipedia.org/wiki/Cathedral_of_St._John_the_Divine" } },
};

function mockFetchOk(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response);
}

beforeEach(() => {
  __resetWikipediaCacheForTests();
  vi.stubGlobal("fetch", mockFetchOk(MOCK_RESPONSE));
});

describe("useWikipediaSummary", () => {
  it("returns idle for null docId", () => {
    const { result } = renderHook(() => useWikipediaSummary(null));
    expect(result.current.status).toBe("idle");
  });

  it("returns idle for non-wikipedia docId", () => {
    const { result } = renderHook(() => useWikipediaSummary("osm:way/12345"));
    expect(result.current.status).toBe("idle");
  });

  it("fetches and returns success for a wikipedia: docId", async () => {
    const { result } = renderHook(() =>
      useWikipediaSummary("wikipedia:Cathedral_of_St._John_the_Divine"),
    );

    expect(result.current.status).toBe("loading");

    await waitFor(() => expect(result.current.status).toBe("success"));
    if (result.current.status !== "success") throw new Error("type narrow");

    expect(result.current.summary.title).toBe("Cathedral of St. John the Divine");
    expect(result.current.summary.extract).toBe("A cathedral in Manhattan.");
    expect(result.current.summary.thumbnailUrl).toBe("https://upload.wikimedia.org/x.jpg");
    expect(result.current.summary.pageUrl).toBe(
      "https://en.wikipedia.org/wiki/Cathedral_of_St._John_the_Divine",
    );
  });

  it("dedups concurrent fetches for the same docId", async () => {
    const fetchSpy = mockFetchOk(MOCK_RESPONSE);
    vi.stubGlobal("fetch", fetchSpy);

    const docId = "wikipedia:Low_Memorial_Library";
    const a = renderHook(() => useWikipediaSummary(docId));
    const b = renderHook(() => useWikipediaSummary(docId));

    await waitFor(() => expect(a.result.current.status).toBe("success"));
    await waitFor(() => expect(b.result.current.status).toBe("success"));

    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("returns error on non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404 } as unknown as Response),
    );

    const { result } = renderHook(() => useWikipediaSummary("wikipedia:Nonexistent"));

    await waitFor(() => expect(result.current.status).toBe("error"));
  });

  it("returns error on rejected fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));

    const { result } = renderHook(() => useWikipediaSummary("wikipedia:NetworkFailure"));

    await waitFor(() => expect(result.current.status).toBe("error"));
  });

  it("handles missing thumbnail gracefully", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchOk({
        title: "T",
        extract: "X",
        content_urls: { desktop: { page: "https://en.wikipedia.org/wiki/T" } },
      }),
    );

    const { result } = renderHook(() => useWikipediaSummary("wikipedia:T"));

    await waitFor(() => expect(result.current.status).toBe("success"));
    if (result.current.status !== "success") throw new Error("type narrow");
    expect(result.current.summary.thumbnailUrl).toBeNull();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/web && npm test -- useWikipediaSummary
```

Expected: FAIL — "Cannot find module './useWikipediaSummary'".

- [ ] **Step 3: Implement the hook**

Create `apps/web/src/state/useWikipediaSummary.ts`:

```ts
/**
 * useWikipediaSummary — lazy fetch a Wikipedia page summary for a doc_id.
 *
 * Slug is taken from the `wikipedia:` prefix; non-wikipedia docs stay
 * `idle`. Concurrent callers share one in-flight Promise via a
 * module-level cache that lives for the page session.
 *
 * The endpoint is the public Wikipedia REST summary API; no key required.
 */

import { useEffect, useRef, useState } from "react";

const PREFIX = "wikipedia:";
const ENDPOINT = "https://en.wikipedia.org/api/rest_v1/page/summary";

export type WikipediaSummary = {
  title: string;
  extract: string;
  thumbnailUrl: string | null;
  pageUrl: string;
};

export type WikipediaFetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; summary: WikipediaSummary }
  | { status: "error" };

const cache = new Map<string, Promise<WikipediaSummary>>();
const warned = new Set<string>();

export function __resetWikipediaCacheForTests(): void {
  cache.clear();
  warned.clear();
}

function slugFromDocId(docId: string | null): string | null {
  if (docId === null) return null;
  if (!docId.startsWith(PREFIX)) return null;
  const slug = docId.slice(PREFIX.length);
  return slug.length > 0 ? slug : null;
}

async function fetchSummary(slug: string): Promise<WikipediaSummary> {
  const url = `${ENDPOINT}/${encodeURIComponent(slug)}`;
  const response = await fetch(url, {
    headers: {
      Accept:
        'application/json; charset=utf-8; profile="https://www.mediawiki.org/wiki/Specs/Summary/1.4.2"',
    },
  });
  if (!response.ok) {
    throw new Error(`wikipedia summary HTTP ${response.status}`);
  }
  const body = (await response.json()) as {
    title?: string;
    extract?: string;
    thumbnail?: { source?: string };
    content_urls?: { desktop?: { page?: string } };
  };
  return {
    title: body.title ?? slug.replace(/_/g, " "),
    extract: body.extract ?? "",
    thumbnailUrl: body.thumbnail?.source ?? null,
    pageUrl: body.content_urls?.desktop?.page ?? `https://en.wikipedia.org/wiki/${encodeURIComponent(slug)}`,
  };
}

function getOrFetch(docId: string, slug: string): Promise<WikipediaSummary> {
  const existing = cache.get(docId);
  if (existing) return existing;
  const inFlight = fetchSummary(slug).catch((err) => {
    cache.delete(docId);
    if (!warned.has(docId)) {
      warned.add(docId);
      // eslint-disable-next-line no-console
      console.warn(`[wikipedia-summary] failed for ${docId}:`, err);
    }
    throw err;
  });
  cache.set(docId, inFlight);
  return inFlight;
}

export function useWikipediaSummary(docId: string | null): WikipediaFetchState {
  const [state, setState] = useState<WikipediaFetchState>({ status: "idle" });
  const abortedRef = useRef(false);

  useEffect(() => {
    abortedRef.current = false;
    const slug = slugFromDocId(docId);
    if (slug === null || docId === null) {
      setState({ status: "idle" });
      return;
    }

    setState({ status: "loading" });
    getOrFetch(docId, slug).then(
      (summary) => {
        if (abortedRef.current) return;
        setState({ status: "success", summary });
      },
      () => {
        if (abortedRef.current) return;
        setState({ status: "error" });
      },
    );

    return () => {
      abortedRef.current = true;
    };
  }, [docId]);

  return state;
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/web && npm test -- useWikipediaSummary
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/state/useWikipediaSummary.ts apps/web/src/state/useWikipediaSummary.test.ts
git commit -m "feat(web): add useWikipediaSummary hook with module cache"
```

---

## Task 7: Build `MarkerInfoCard` component (TDD)

**Files:**
- Create: `apps/web/src/components/MarkerInfoCard.tsx`
- Create: `apps/web/src/components/MarkerInfoCard.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/components/MarkerInfoCard.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MarkerInfoCard } from "./MarkerInfoCard";
import type { Citation, PlannedStop } from "@/state/types";

const stop: PlannedStop = {
  index: 0,
  doc_id: "wikipedia:Low_Memorial_Library",
  name: "Low Memorial Library",
  lat: 40.808,
  lon: -73.961,
  leg_distance_m: 0,
};

const citation: Citation = {
  doc_id: "wikipedia:Low_Memorial_Library",
  source_url: "https://en.wikipedia.org/wiki/Low_Memorial_Library",
  source_type: "wikipedia",
  span: "An iconic Beaux-Arts library on Columbia's Morningside campus.",
  retrieval_turn: 1,
};

vi.mock("@/state/useWikipediaSummary", () => ({
  useWikipediaSummary: vi.fn(),
}));

import { useWikipediaSummary } from "@/state/useWikipediaSummary";
const mockedHook = vi.mocked(useWikipediaSummary);

describe("MarkerInfoCard", () => {
  it("hover variant renders just number + name", () => {
    render(<MarkerInfoCard variant="hover" stop={stop} citation={citation} onClose={() => {}} />);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Low Memorial Library")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
  });

  it("pinned variant with wikipedia success shows thumbnail + extract + close", () => {
    mockedHook.mockReturnValue({
      status: "success",
      summary: {
        title: "Low Memorial Library",
        extract: "Designed by Charles McKim.",
        thumbnailUrl: "https://upload.wikimedia.org/x.jpg",
        pageUrl: "https://en.wikipedia.org/wiki/Low_Memorial_Library",
      },
    });

    render(<MarkerInfoCard variant="pinned" stop={stop} citation={citation} onClose={() => {}} />);

    expect(screen.getByRole("img")).toHaveAttribute("src", "https://upload.wikimedia.org/x.jpg");
    expect(screen.getByText("Designed by Charles McKim.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /close/i })).toBeInTheDocument();
  });

  it("pinned variant with wikipedia loading shows skeleton", () => {
    mockedHook.mockReturnValue({ status: "loading" });

    render(<MarkerInfoCard variant="pinned" stop={stop} citation={citation} onClose={() => {}} />);

    expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
  });

  it("pinned variant with wikipedia error falls back to citation span + link", () => {
    mockedHook.mockReturnValue({ status: "error" });

    render(<MarkerInfoCard variant="pinned" stop={stop} citation={citation} onClose={() => {}} />);

    expect(screen.getByText(citation.span)).toBeInTheDocument();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", citation.source_url);
  });

  it("pinned variant for OSM doc shows span only, no fetch", () => {
    mockedHook.mockReturnValue({ status: "idle" });

    const osmStop = { ...stop, doc_id: "osm:way/12345" };
    const osmCit: Citation = {
      ...citation,
      doc_id: "osm:way/12345",
      source_type: "osm",
      source_url: "https://www.openstreetmap.org/way/12345",
      span: "A historic stoop on West 116th.",
    };

    render(<MarkerInfoCard variant="pinned" stop={osmStop} citation={osmCit} onClose={() => {}} />);

    expect(screen.getByText("A historic stoop on West 116th.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("pinned variant with no citation shows just name", () => {
    mockedHook.mockReturnValue({ status: "idle" });

    render(<MarkerInfoCard variant="pinned" stop={stop} citation={null} onClose={() => {}} />);

    expect(screen.getByText("Low Memorial Library")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("close button calls onClose", async () => {
    mockedHook.mockReturnValue({ status: "idle" });

    const onClose = vi.fn();
    render(<MarkerInfoCard variant="pinned" stop={stop} citation={null} onClose={onClose} />);

    await userEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/web && npm test -- MarkerInfoCard
```

Expected: FAIL — "Cannot find module './MarkerInfoCard'".

- [ ] **Step 3: Implement `MarkerInfoCard`**

Create `apps/web/src/components/MarkerInfoCard.tsx`:

```tsx
/**
 * MarkerInfoCard — popup card rendered into the engine's popup container
 * via createPortal. Two variants:
 *   - "hover": small preview, name only.
 *   - "pinned": full card with chip, body (Wikipedia thumbnail+extract,
 *     citation span fallback, or name-only when there's no citation),
 *     external-link footer, and a close button.
 */

import { sourceTypeColor } from "@/styles/tokens";
import type { Citation, PlannedStop } from "@/state/types";
import { useWikipediaSummary } from "@/state/useWikipediaSummary";

import { ExternalLinkIcon } from "./Icon";
import { LoadingSkeleton } from "./LoadingSkeleton";

type Props = {
  variant: "hover" | "pinned";
  stop: PlannedStop;
  citation: Citation | null;
  onClose: () => void;
};

export function MarkerInfoCard({ variant, stop, citation, onClose }: Props) {
  if (variant === "hover") {
    return (
      <div className="flex max-w-[220px] items-center gap-2 rounded border border-hairline bg-parchment px-3 py-2 shadow-md">
        <NumberBadge index={stop.index} />
        <span className="truncate font-serif text-body text-ink">{stop.name}</span>
      </div>
    );
  }

  return (
    <article className="w-[300px] space-y-3 rounded border border-hairline bg-parchment p-3 shadow-md">
      <header className="flex items-start gap-2">
        <NumberBadge index={stop.index} />
        <h3 className="min-w-0 flex-1 font-serif text-body font-semibold leading-tight text-ink">
          {stop.name}
        </h3>
        <button
          type="button"
          aria-label="Close popup"
          onClick={onClose}
          className="shrink-0 rounded px-1 text-ink-muted hover:text-ink focus:outline-none focus:ring-2 focus:ring-ink/40"
        >
          ×
        </button>
      </header>

      {citation !== null && (
        <div>
          <span
            className="rounded px-1.5 py-0.5 font-mono text-mono uppercase tracking-wide text-white"
            style={{ backgroundColor: sourceTypeColor[citation.source_type] }}
          >
            {citation.source_type}
          </span>
        </div>
      )}

      <PinnedBody stop={stop} citation={citation} />

      {citation !== null && (
        <footer>
          <a
            href={citation.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-serif text-small text-archival-blue underline-offset-4 hover:underline focus:outline-none focus:ring-2 focus:ring-ink/40"
          >
            View source <ExternalLinkIcon className="text-small" />
          </a>
        </footer>
      )}
    </article>
  );
}

function NumberBadge({ index }: { index: number }) {
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-hairline bg-parchment-deep font-serif text-small font-semibold text-ink">
      {index + 1}
    </span>
  );
}

function PinnedBody({ stop, citation }: { stop: PlannedStop; citation: Citation | null }) {
  const isWikipedia = stop.doc_id.startsWith("wikipedia:");
  const fetchState = useWikipediaSummary(isWikipedia ? stop.doc_id : null);

  if (citation === null) {
    return null;
  }

  if (isWikipedia) {
    if (fetchState.status === "loading") {
      return <LoadingSkeleton />;
    }
    if (fetchState.status === "success") {
      return (
        <div className="flex gap-3">
          {fetchState.summary.thumbnailUrl !== null && (
            <img
              src={fetchState.summary.thumbnailUrl}
              alt=""
              className="h-24 w-24 shrink-0 rounded border border-hairline object-cover"
              loading="lazy"
            />
          )}
          <p className="flex-1 font-serif text-small leading-snug text-ink-soft">
            {fetchState.summary.extract}
          </p>
        </div>
      );
    }
    // idle (e.g. transient before useEffect runs) or error → fall through to span fallback.
  }

  return <p className="font-serif text-small italic leading-snug text-ink-soft">{citation.span}</p>;
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/web && npm test -- MarkerInfoCard
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Run typecheck**

```bash
cd apps/web && npm run typecheck
```

Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/MarkerInfoCard.tsx apps/web/src/components/MarkerInfoCard.test.tsx
git commit -m "feat(web): add MarkerInfoCard with hover preview and pinned variants"
```

---

## Task 8: Build `MapViewModeToggle` component (TDD)

**Files:**
- Create: `apps/web/src/components/MapViewModeToggle.tsx`
- Create: `apps/web/src/components/MapViewModeToggle.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/components/MapViewModeToggle.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  MapViewModeToggle,
  readSavedViewMode,
  writeSavedViewMode,
  STORAGE_KEY,
} from "./MapViewModeToggle";

beforeEach(() => {
  localStorage.clear();
});

describe("readSavedViewMode", () => {
  it("returns 3d when storage is empty", () => {
    expect(readSavedViewMode()).toBe("3d");
  });

  it("returns 2d when stored as 2d", () => {
    localStorage.setItem(STORAGE_KEY, "2d");
    expect(readSavedViewMode()).toBe("2d");
  });

  it("returns 3d for invalid stored value", () => {
    localStorage.setItem(STORAGE_KEY, "garbage");
    expect(readSavedViewMode()).toBe("3d");
  });

  it("falls back to 3d when localStorage throws", () => {
    const original = globalThis.localStorage;
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() {
        throw new Error("private mode");
      },
    });
    try {
      expect(readSavedViewMode()).toBe("3d");
    } finally {
      Object.defineProperty(globalThis, "localStorage", { configurable: true, value: original });
    }
  });
});

describe("writeSavedViewMode", () => {
  it("writes the value to localStorage", () => {
    writeSavedViewMode("2d");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("2d");
  });

  it("does not throw when localStorage is unavailable", () => {
    const original = globalThis.localStorage;
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() {
        throw new Error("private mode");
      },
    });
    try {
      expect(() => writeSavedViewMode("3d")).not.toThrow();
    } finally {
      Object.defineProperty(globalThis, "localStorage", { configurable: true, value: original });
    }
  });
});

describe("MapViewModeToggle", () => {
  it("renders both buttons with the active one marked", () => {
    render(<MapViewModeToggle mode="3d" onChange={() => {}} />);

    const btn3d = screen.getByRole("button", { name: /3d/i });
    const btn2d = screen.getByRole("button", { name: /2d/i });
    expect(btn3d).toHaveAttribute("aria-pressed", "true");
    expect(btn2d).toHaveAttribute("aria-pressed", "false");
  });

  it("invokes onChange with the new mode when the inactive button is clicked", async () => {
    const onChange = vi.fn();
    render(<MapViewModeToggle mode="3d" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: /2d/i }));
    expect(onChange).toHaveBeenCalledWith("2d");
  });

  it("does not invoke onChange when the active button is clicked", async () => {
    const onChange = vi.fn();
    render(<MapViewModeToggle mode="3d" onChange={onChange} />);

    await userEvent.click(screen.getByRole("button", { name: /3d/i }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/web && npm test -- MapViewModeToggle
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the toggle**

Create `apps/web/src/components/MapViewModeToggle.tsx`:

```tsx
/**
 * MapViewModeToggle — segmented 2D / 3D buttons rendered as an overlay
 * on the map. Persists the choice to localStorage under STORAGE_KEY.
 */

export type MapViewMode = "2d" | "3d";

export const STORAGE_KEY = "palimpsest.map.viewMode";
const DEFAULT_MODE: MapViewMode = "3d";

export function readSavedViewMode(): MapViewMode {
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
    return raw === "2d" || raw === "3d" ? raw : DEFAULT_MODE;
  } catch {
    return DEFAULT_MODE;
  }
}

export function writeSavedViewMode(mode: MapViewMode): void {
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, mode);
  } catch {
    // Ignore — localStorage may be unavailable (private mode, SSR).
  }
}

type Props = {
  mode: MapViewMode;
  onChange: (next: MapViewMode) => void;
};

export function MapViewModeToggle({ mode, onChange }: Props) {
  return (
    <div className="inline-flex overflow-hidden rounded border border-hairline bg-parchment shadow-md">
      <ModeButton label="2D" mode="2d" active={mode === "2d"} onClick={onChange} />
      <ModeButton label="3D" mode="3d" active={mode === "3d"} onClick={onChange} />
    </div>
  );
}

function ModeButton({
  label,
  mode,
  active,
  onClick,
}: {
  label: string;
  mode: MapViewMode;
  active: boolean;
  onClick: (next: MapViewMode) => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => {
        if (!active) onClick(mode);
      }}
      className={`px-3 py-1.5 font-mono text-mono uppercase tracking-wide transition-colors duration-fast focus:outline-none focus:ring-2 focus:ring-ink/40 ${
        active ? "bg-oxblood text-parchment" : "bg-parchment text-ink hover:bg-parchment-deep"
      }`}
    >
      {label}
    </button>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/web && npm test -- MapViewModeToggle
```

Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/components/MapViewModeToggle.tsx apps/web/src/components/MapViewModeToggle.test.tsx
git commit -m "feat(web): add MapViewModeToggle with persisted 2D/3D state"
```

---

## Task 9: Wire popup state machine into `MapView` (TDD)

**Files:**
- Modify: `apps/web/src/components/MapView.tsx`
- Create: `apps/web/src/components/MapView.test.tsx`

- [ ] **Step 1: Write the failing component test**

Create `apps/web/src/components/MapView.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MapView } from "./MapView";
import { MapEngineProvider } from "@/state/MapEngineContext";
import type { Citation, PlannedStop } from "@/state/types";

// Mocked engine — lets tests drive marker events and assert flyTo calls.
type Cb = (...args: unknown[]) => void;
const fakeEngine = {
  hoverCb: null as Cb | null,
  clickCb: null as Cb | null,
  cameraCb: null as Cb | null,
  popupEl: null as HTMLElement | null,
  flyTo: vi.fn().mockResolvedValue(undefined),
  setViewport: vi.fn(),
  addMarkers: vi.fn(),
  addPath: vi.fn(),
  clearLayer: vi.fn(),
  setPopup: vi.fn((_at, el) => {
    fakeEngine.popupEl = el;
  }),
  clearPopup: vi.fn(() => {
    fakeEngine.popupEl = null;
  }),
  onMarkerHover: vi.fn((cb) => {
    fakeEngine.hoverCb = cb;
    return () => {};
  }),
  onMarkerClick: vi.fn((cb) => {
    fakeEngine.clickCb = cb;
    return () => {};
  }),
  onCameraChange: vi.fn((cb) => {
    fakeEngine.cameraCb = cb;
    return () => {};
  }),
  destroy: vi.fn(),
  init: vi.fn().mockResolvedValue(undefined),
};

vi.mock("@/map", async () => {
  const actual = await vi.importActual<typeof import("@/map")>("@/map");
  return {
    ...actual,
    createMapEngine: () => fakeEngine,
  };
});

vi.mock("@/state/useWikipediaSummary", () => ({
  useWikipediaSummary: () => ({ status: "idle" as const }),
}));

const stops: PlannedStop[] = [
  { index: 0, doc_id: "wikipedia:Low_Memorial_Library", name: "Low Memorial Library", lat: 40.808, lon: -73.961, leg_distance_m: 0 },
  { index: 1, doc_id: "wikipedia:Cathedral_of_St._John_the_Divine", name: "Cathedral of St. John the Divine", lat: 40.804, lon: -73.96, leg_distance_m: 250 },
];

const citations: Citation[] = [
  { doc_id: stops[0].doc_id, source_url: "https://en.wikipedia.org/wiki/Low_Memorial_Library", source_type: "wikipedia", span: "An iconic library.", retrieval_turn: 1 },
];

beforeEach(() => {
  fakeEngine.flyTo.mockClear();
  fakeEngine.setPopup.mockClear();
  fakeEngine.clearPopup.mockClear();
  fakeEngine.popupEl = null;
  fakeEngine.hoverCb = null;
  fakeEngine.clickCb = null;
});

async function renderMap(props: { stops: PlannedStop[]; citations: Citation[] }) {
  const utils = render(
    <MapEngineProvider>
      <MapView {...props} />
    </MapEngineProvider>,
  );
  // Wait a microtask for the async `init().then(...)` to fire.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return utils;
}

describe("MapView popup", () => {
  it("on hover, mounts a popup; on leave, clears it", async () => {
    await renderMap({ stops, citations });
    expect(fakeEngine.hoverCb).not.toBeNull();

    act(() => {
      fakeEngine.hoverCb!({ layerId: "walk", markerId: "stop-0", at: { lat: 40.808, lng: -73.961 } });
    });
    expect(fakeEngine.setPopup).toHaveBeenCalledTimes(1);

    act(() => {
      fakeEngine.hoverCb!(null);
    });
    expect(fakeEngine.clearPopup).toHaveBeenCalled();
  });

  it("on click, pins the popup and flies to the stop", async () => {
    await renderMap({ stops, citations });

    act(() => {
      fakeEngine.clickCb!({ layerId: "walk", markerId: "stop-0", at: { lat: 40.808, lng: -73.961 } });
    });

    expect(fakeEngine.flyTo).toHaveBeenCalledWith(
      expect.objectContaining({ center: { lat: 40.808, lng: -73.961 } }),
      expect.any(Number),
    );
    // The popup remains mounted on the engine.
    expect(fakeEngine.setPopup).toHaveBeenCalled();
  });

  it("Escape clears a pinned popup", async () => {
    await renderMap({ stops, citations });

    act(() => {
      fakeEngine.clickCb!({ layerId: "walk", markerId: "stop-0", at: { lat: 40.808, lng: -73.961 } });
    });

    await userEvent.keyboard("{Escape}");
    expect(fakeEngine.clearPopup).toHaveBeenCalled();
  });

  it("clears popup state when stops change", async () => {
    const { rerender } = await renderMap({ stops, citations });

    act(() => {
      fakeEngine.clickCb!({ layerId: "walk", markerId: "stop-0", at: { lat: 40.808, lng: -73.961 } });
    });

    rerender(
      <MapEngineProvider>
        <MapView stops={[]} citations={[]} />
      </MapEngineProvider>,
    );

    expect(fakeEngine.clearPopup).toHaveBeenCalled();
  });
});
```

(The toggle wiring is verified manually after Task 10; testing it in `MapView` would duplicate the toggle's own component tests.)

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/web && npm test -- MapView.test
```

Expected: FAIL — `setPopup`/`onMarkerHover` not used by the current `MapView`.

- [ ] **Step 3: Update `MapView.tsx` — props, imports, state**

Replace the entire file `apps/web/src/components/MapView.tsx` with:

```tsx
/**
 * MapView — mounts a MapEngine on a div, draws the walk, and hosts the
 * marker info popups + the 2D/3D toggle overlay.
 *
 * The popup element is React-owned (a stable div referenced via useRef),
 * mounted into the engine's popup container by `engine.setPopup(at, el)`.
 * React renders MarkerInfoCard into that element via createPortal.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { DEFAULT_VIEWPORT, createMapEngine, type MapEngine } from "@/map";
import type { LatLng, MarkerEvent, Viewport } from "@/map";
import type { Citation, PlannedStop } from "@/state/types";
import { useMapEngineHandle } from "@/state/MapEngineContext";

import { MarkerInfoCard } from "./MarkerInfoCard";
import {
  MapViewModeToggle,
  readSavedViewMode,
  writeSavedViewMode,
  type MapViewMode,
} from "./MapViewModeToggle";

const WALK_LAYER = "walk";
const PATH_COLOR = "#7a1f1f";
const MARKER_COLOR = "#7a1f1f";
const FLYTO_DURATION_MS = 1200;
const TOGGLE_FLY_MS = 600;
const PINNED_FLY_MIN_ZOOM = 17.5;

type Props = {
  stops: PlannedStop[];
  citations: Citation[];
};

type MarkerFocus =
  | { kind: "idle" }
  | { kind: "hover"; markerId: string; at: LatLng }
  | { kind: "pinned"; markerId: string; at: LatLng };

function pitchForMode(mode: MapViewMode): number {
  return mode === "2d" ? 0 : 60;
}

function parseStopIndex(markerId: string): number | null {
  const m = /^stop-(\d+)$/.exec(markerId);
  if (m === null) return null;
  const n = Number.parseInt(m[1], 10);
  return Number.isFinite(n) ? n : null;
}

export function MapView({ stops, citations }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const popupHostRef = useRef<HTMLDivElement | null>(null);
  const cameraRef = useRef<Viewport>({ ...DEFAULT_VIEWPORT });
  const engineRef = useRef<MapEngine | null>(null);
  const handle = useMapEngineHandle();
  const [ready, setReady] = useState(false);
  const [focus, setFocus] = useState<MarkerFocus>({ kind: "idle" });
  const [viewMode, setViewMode] = useState<MapViewMode>(() => readSavedViewMode());

  // Keep popup host alive across renders.
  if (popupHostRef.current === null) {
    popupHostRef.current = document.createElement("div");
  }

  // Citation lookup — first citation wins per doc_id.
  const citationByDocId = useMemo(() => {
    const m = new Map<string, Citation>();
    for (const c of citations) {
      if (!m.has(c.doc_id)) m.set(c.doc_id, c);
    }
    return m;
  }, [citations]);

  // Engine lifecycle.
  useEffect(() => {
    if (containerRef.current === null) return;
    const engine = createMapEngine();
    engineRef.current = engine;
    let cancelled = false;

    const initialView: Viewport = {
      ...DEFAULT_VIEWPORT,
      pitch: pitchForMode(readSavedViewMode()),
    };
    cameraRef.current = { ...initialView };

    engine
      .init(containerRef.current, initialView)
      .then(() => {
        if (cancelled) {
          engine.destroy();
          return;
        }
        handle.set(engine);
        setReady(true);
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error("map init failed", err);
      });

    return () => {
      cancelled = true;
      handle.set(null);
      engineRef.current?.destroy();
      engineRef.current = null;
      setReady(false);
    };
  }, [handle]);

  // Subscribe to camera, marker hover, marker click after init.
  useEffect(() => {
    if (!ready) return;
    const engine = engineRef.current;
    if (engine === null) return;

    const offCamera = engine.onCameraChange((v) => {
      cameraRef.current = v;
    });

    const offHover = engine.onMarkerHover((e: MarkerEvent | null) => {
      setFocus((prev) => {
        if (prev.kind === "pinned") return prev; // suppress hover while pinned.
        if (e === null) return { kind: "idle" };
        return { kind: "hover", markerId: e.markerId, at: e.at };
      });
    });

    const offClick = engine.onMarkerClick((e) => {
      setFocus({ kind: "pinned", markerId: e.markerId, at: e.at });
      const cur = cameraRef.current;
      void engine.flyTo(
        {
          center: e.at,
          zoom: Math.max(cur.zoom, PINNED_FLY_MIN_ZOOM),
          pitch: cur.pitch ?? pitchForMode(viewMode),
          bearing: cur.bearing,
        },
        FLYTO_DURATION_MS,
      );
    });

    return () => {
      offCamera();
      offHover();
      offClick();
    };
  }, [ready, viewMode]);

  // Escape dismisses pinned popup.
  useEffect(() => {
    if (focus.kind !== "pinned") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFocus({ kind: "idle" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focus.kind]);

  // Drive the popup into / out of the engine.
  useEffect(() => {
    if (!ready) return;
    const engine = engineRef.current;
    const host = popupHostRef.current;
    if (engine === null || host === null) return;

    if (focus.kind === "idle") {
      engine.clearPopup();
      return;
    }
    engine.setPopup(focus.at, host);
  }, [ready, focus]);

  // Reset focus and clear popup whenever stops change.
  useEffect(() => {
    setFocus({ kind: "idle" });
  }, [stops]);

  // Draw the walk.
  useEffect(() => {
    if (!ready) return;
    const engine = engineRef.current;
    if (engine === null) return;

    if (stops.length === 0) {
      engine.clearLayer(WALK_LAYER);
      return;
    }

    const coords = stops.map((s) => ({ lat: s.lat, lng: s.lon }));
    engine.addPath(WALK_LAYER, coords, { color: PATH_COLOR, widthPx: 4, opacity: 0.85 });
    engine.addMarkers(
      WALK_LAYER,
      stops.map((s) => ({
        id: `stop-${s.index}`,
        position: { lat: s.lat, lng: s.lon },
        label: `${s.index + 1}. ${s.name}`,
        color: MARKER_COLOR,
      })),
    );

    const first = stops[0];
    if (first) {
      void engine.flyTo(
        { center: { lat: first.lat, lng: first.lon }, zoom: 15.5, pitch: pitchForMode(viewMode) },
        FLYTO_DURATION_MS,
      );
    }
  }, [stops, ready, viewMode]);

  const handleViewModeChange = (next: MapViewMode) => {
    setViewMode(next);
    writeSavedViewMode(next);
    const engine = engineRef.current;
    if (engine === null) return;
    const cur = cameraRef.current;
    void engine.flyTo(
      { ...cur, pitch: pitchForMode(next) },
      TOGGLE_FLY_MS,
    );
  };

  // Resolve focused stop & citation for the popup.
  const focusedStopIndex =
    focus.kind === "idle" ? null : parseStopIndex(focus.markerId);
  const focusedStop =
    focusedStopIndex === null ? null : stops.find((s) => s.index === focusedStopIndex) ?? null;
  const focusedCitation =
    focusedStop === null ? null : citationByDocId.get(focusedStop.doc_id) ?? null;

  return (
    <>
      <div ref={containerRef} className="absolute inset-0" />
      <div className="pointer-events-none absolute left-4 top-20 z-10">
        <div className="pointer-events-auto">
          <MapViewModeToggle mode={viewMode} onChange={handleViewModeChange} />
        </div>
      </div>
      {focus.kind !== "idle" && focusedStop !== null && popupHostRef.current !== null
        ? createPortal(
            <MarkerInfoCard
              variant={focus.kind === "pinned" ? "pinned" : "hover"}
              stop={focusedStop}
              citation={focusedCitation}
              onClose={() => setFocus({ kind: "idle" })}
            />,
            popupHostRef.current,
          )
        : null}
    </>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/web && npm test -- MapView.test
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Run typecheck and lint**

```bash
cd apps/web && npm run typecheck && npm run lint
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/MapView.tsx apps/web/src/components/MapView.test.tsx
git commit -m "feat(web): wire marker popup state machine and 2D/3D toggle into MapView"
```

---

## Task 10: Thread `citations` from `App.tsx` into `<MapView>`

**Files:**
- Modify: `apps/web/src/App.tsx`

- [ ] **Step 1: Update the `<MapView>` invocation in `App.tsx`**

Replace the line:

```tsx
<MapView stops={session.state.walk} />
```

with:

```tsx
<MapView stops={session.state.walk} citations={session.state.citations} />
```

- [ ] **Step 2: Run typecheck**

```bash
cd apps/web && npm run typecheck
```

Expected: passes.

- [ ] **Step 3: Run all tests**

```bash
cd apps/web && npm test
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/App.tsx
git commit -m "feat(web): pass citations to MapView for marker popups"
```

---

## Task 11: Manual verification

No code changes — run the app and verify by hand. Document results in the PR description.

- [ ] **Step 1: Build and start the stack**

From repo root:

```bash
make up
```

Wait until the health endpoint comes up (the API container will print a ready line; alternatively `curl http://localhost:8000/health`). The web app is at `http://localhost:5173`.

- [ ] **Step 2: Verify 2D/3D toggle**

Checklist:

- The toggle is visible top-left of the map.
- "3D" is the active button on first load (filled oxblood).
- Clicking "2D" flattens the map (pitch goes to 0). The transition is animated (~600ms).
- Clicking "3D" returns to a tilted view (pitch 60).
- The active button is `aria-pressed="true"` (verify in DevTools).
- Reload the page after choosing "2D" — the map starts flat, and "2D" is the active button.
- Right-click-drag still rotates the map (compass moves) in both 2D and 3D modes.

- [ ] **Step 3: Verify marker popups (Wikipedia path)**

Type a question that produces a walk with Wikipedia stops:

```
Tell me about Low Memorial Library and the Cathedral of St. John the Divine
```

Wait until red dots and the path render. Then:

- Hover a red dot — a small preview card appears with the stop number and name.
- Move the mouse off — the preview disappears.
- Click a red dot — the preview is replaced by a full pinned card with: source-type chip ("WIKIPEDIA"), Wikipedia thumbnail (if the page has one), one paragraph of extract, and a "View source" external link. The map flies to the stop.
- Click another red dot — the popup switches to the new stop and the camera flies again.
- Hovering a different marker while one is pinned does NOT change the popup.
- Clicking the "×" closes the popup.
- Pressing `Escape` while a popup is pinned closes it.

- [ ] **Step 4: Verify marker popups (OSM/Wikidata fallback)**

Ask a question whose answer mixes Wikipedia and OSM stops, e.g.:

```
What's a good walk between Riverside Park benches and Grant's Tomb?
```

Confirm:

- OSM stops show the citation's `span` snippet, no thumbnail.
- The "View source" link points to the OSM way / Wikidata page.

- [ ] **Step 5: Verify error fallback**

Throttle the network to "Offline" in DevTools, then click a fresh marker that hasn't been hovered yet (so the cache is empty). The popup should fall back to the citation `span` + link, with a `[wikipedia-summary] failed for ...` warning in the console.

- [ ] **Step 6: Verify behavior across walks**

Plan a second walk after the first. Confirm the popup is dismissed and the new walk's markers are interactive.

- [ ] **Step 7: Final commit (if any docs were updated)**

If you updated `docs/` to reflect the manual verification, commit it:

```bash
git add docs/
git commit -m "docs: verification notes for map QoL features"
```

If nothing changed, skip.

---

## Deviations from spec

- **Playwright E2E:** The spec calls for Playwright tests for two flows (walk → marker → popup; toggle pitch). `apps/web` does not currently have a Playwright setup, and bootstrapping it is its own multi-step effort with its own CI implications. This plan ships **vitest unit + component tests** for the same behaviors and a manual verification checklist (Task 11). Playwright deferred to a separate plan.
- **Marker event helper:** The spec talks about wiring DOM listeners directly inside `MaplibreEngine.addMarkers`. The plan factors that into a new `MarkerEventBus` helper inside `engines/` so the hover state machine can be unit-tested in JSDOM without mocking maplibre. Same external behavior; cleaner test boundary.

## Self-review notes

- **Spec coverage:** Each numbered section of the spec maps to at least one task — Engine surface (T2/T3/T5), 2D/3D toggle (T8/T9), Marker popup (T7/T9), Wikipedia fetch (T6), Data wiring (T10), File changes (covered), Error handling (covered in code + T11), Testing plan (vitest covered; Playwright explicit deviation), Out of scope (preserved).
- **Type consistency:** `MarkerEvent`, `MapViewMode`, `WikipediaFetchState` are defined once and referenced everywhere by the same name. Engine method names (`onMarkerHover`, `onMarkerClick`, `setPopup`, `clearPopup`) are stable across all tasks.
- **Placeholder scan:** No TBDs or TODOs. Every code step shows actual code; every test step shows expected output.
