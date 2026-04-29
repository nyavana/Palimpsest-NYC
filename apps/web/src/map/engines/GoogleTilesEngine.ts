/**
 * GoogleTilesEngine — stub reserving the upgrade path.
 *
 * Intentionally throws NotImplementedError from every runtime method. The
 * factory in `../index.ts` rejects construction unless a
 * `VITE_GOOGLE_MAP_TILES_API_KEY` is set, so misconfiguration fails loudly
 * at startup rather than at first use.
 *
 * When we actually ship this (tracked in tasks.md §14 or a later change),
 * this file will wrap CesiumJS + Google Photorealistic 3D Tiles while
 * keeping the MapEngine interface unchanged.
 */

import { MapEngine, NotImplementedError } from "../MapEngine";
import type { LatLng, Marker, PathStyle, Unsubscribe, Viewport } from "../types";

const UPGRADE_DOC_HINT =
  "Tracked in openspec/changes/initial-palimpsest-scaffold/tasks.md §8.4 (GoogleTilesEngine).";

export class GoogleTilesEngine implements MapEngine {
  constructor(apiKey: string) {
    if (!apiKey) {
      throw new Error("GoogleTilesEngine requires VITE_GOOGLE_MAP_TILES_API_KEY to be set.");
    }
    // apiKey is captured in the closure once we wire CesiumJS in. For the
    // stub it just needs to be present so misconfiguration fails fast.
    void apiKey;
  }

  async init(_container: HTMLElement, _initialView: Viewport): Promise<void> {
    throw new NotImplementedError(`GoogleTilesEngine.init is not implemented. ${UPGRADE_DOC_HINT}`);
  }

  setViewport(_v: Viewport): void {
    throw new NotImplementedError(
      `GoogleTilesEngine.setViewport is not implemented. ${UPGRADE_DOC_HINT}`,
    );
  }

  async flyTo(_target: Viewport, _durationMs?: number): Promise<void> {
    throw new NotImplementedError(
      `GoogleTilesEngine.flyTo is not implemented. ${UPGRADE_DOC_HINT}`,
    );
  }

  addMarkers(_layerId: string, _markers: Marker[]): void {
    throw new NotImplementedError(
      `GoogleTilesEngine.addMarkers is not implemented. ${UPGRADE_DOC_HINT}`,
    );
  }

  addPath(_layerId: string, _coords: LatLng[], _style?: PathStyle): void {
    throw new NotImplementedError(
      `GoogleTilesEngine.addPath is not implemented. ${UPGRADE_DOC_HINT}`,
    );
  }

  clearLayer(_layerId: string): void {
    throw new NotImplementedError(
      `GoogleTilesEngine.clearLayer is not implemented. ${UPGRADE_DOC_HINT}`,
    );
  }

  onCameraChange(_cb: (v: Viewport) => void): Unsubscribe {
    throw new NotImplementedError(
      `GoogleTilesEngine.onCameraChange is not implemented. ${UPGRADE_DOC_HINT}`,
    );
  }

  destroy(): void {
    // Safe no-op so consumer cleanup paths don't throw in dev.
  }
}
