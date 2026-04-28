/**
 * Map engine factory.
 *
 * The rest of the app imports from `@/map` only. Swapping engines happens
 * here, in a single file — change the factory, change the engine, never
 * touch components. See specs/map-engine/spec.md.
 */

import { MapEngine } from "./MapEngine";
import { GoogleTilesEngine } from "./engines/GoogleTilesEngine";
import { MaplibreEngine } from "./engines/MaplibreEngine";
import type { MapEngineKind } from "./types";

export type { MapEngine } from "./MapEngine";
export { MapEngineLifecycleError, NotImplementedError } from "./MapEngine";
export type { LatLng, MapEngineKind, Marker, PathStyle, Unsubscribe, Viewport } from "./types";

/** Default view for v1 — roughly centered on Low Steps, Columbia. */
export const DEFAULT_VIEWPORT = {
  center: { lat: 40.8075, lng: -73.9626 },
  zoom: 15.5,
  bearing: 0,
  pitch: 60,
};

function resolveKind(): MapEngineKind {
  const raw = (import.meta.env?.VITE_MAP_ENGINE ?? "maplibre") as string;
  if (raw === "google-3d") {
    return "google-3d";
  }
  return "maplibre";
}

/**
 * Build the engine configured for this environment.
 *
 * Misconfiguration (e.g. selecting google-3d without a key) throws at
 * construction time, never at first method call.
 */
export function createMapEngine(kind: MapEngineKind = resolveKind()): MapEngine {
  switch (kind) {
    case "maplibre":
      return new MaplibreEngine();
    case "google-3d": {
      const apiKey = (import.meta.env?.VITE_GOOGLE_MAP_TILES_API_KEY ?? "") as string;
      return new GoogleTilesEngine(apiKey);
    }
    default: {
      const exhaustive: never = kind;
      throw new Error(`Unknown map engine kind: ${String(exhaustive)}`);
    }
  }
}
