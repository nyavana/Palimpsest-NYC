/**
 * MapEngine — the stable interface the Palimpsest frontend imports.
 *
 * Concrete implementations live under `./engines/` and must NOT be imported
 * directly by components. The factory at `./index.ts` selects an engine by
 * environment variable and returns something shaped like this.
 *
 * The v2 upgrade to Google Photorealistic 3D Tiles is a one-file swap in
 * `./index.ts` — every component that consumes the map only talks to this
 * interface, so no component code changes.
 *
 * See `specs/map-engine/spec.md` for the full behavioral contract.
 */

import type { LatLng, Marker, MarkerEvent, PathStyle, Unsubscribe, Viewport } from "./types";

export interface MapEngine {
  /**
   * Mount the engine on a DOM container. Returns when the first frame is rendered.
   */
  init(container: HTMLElement, initialView: Viewport): Promise<void>;

  /** Jump instantly to a new viewport without animation. */
  setViewport(v: Viewport): void;

  /** Animate smoothly to a target viewport. */
  flyTo(target: Viewport, durationMs?: number): Promise<void>;

  /** Replace all markers on the given layer (creates the layer if missing). */
  addMarkers(layerId: string, markers: Marker[]): void;

  /** Replace the path on the given layer (creates the layer if missing). */
  addPath(layerId: string, coords: LatLng[], style?: PathStyle): void;

  /** Remove everything on a layer. No-op if the layer does not exist. */
  clearLayer(layerId: string): void;

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

  /** Subscribe to camera movements. Returns an unsubscribe function. */
  onCameraChange(cb: (v: Viewport) => void): Unsubscribe;

  /** Tear down the engine and release its resources. */
  destroy(): void;
}

/** Raised when an engine method is called before `init` or after `destroy`. */
export class MapEngineLifecycleError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MapEngineLifecycleError";
  }
}

/** Raised by stubbed engines whose implementation is not yet wired up. */
export class NotImplementedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotImplementedError";
  }
}
