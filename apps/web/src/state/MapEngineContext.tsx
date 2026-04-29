/**
 * Shared handle to the live MapEngine instance.
 *
 * `MapView` registers its engine here once `init()` resolves; `App` and
 * `WalkTimeline` consume the handle to draw paths and animate fly-tos.
 * Components only ever see the `MapEngine` interface — the engines
 * themselves stay behind the eslint boundary.
 */

import { createContext, useCallback, useContext, useMemo, useRef, type ReactNode } from "react";

import type { MapEngine } from "@/map";

type MapEngineHandle = {
  /** Returns the engine if mounted, or null if not yet ready. */
  get(): MapEngine | null;
  /** Called by MapView once init() resolves. */
  set(engine: MapEngine | null): void;
};

const MapEngineContext = createContext<MapEngineHandle | null>(null);

export function MapEngineProvider({ children }: { children: ReactNode }) {
  const ref = useRef<MapEngine | null>(null);

  const get = useCallback(() => ref.current, []);
  const set = useCallback((engine: MapEngine | null) => {
    ref.current = engine;
  }, []);

  const value = useMemo<MapEngineHandle>(() => ({ get, set }), [get, set]);

  return <MapEngineContext.Provider value={value}>{children}</MapEngineContext.Provider>;
}

export function useMapEngineHandle(): MapEngineHandle {
  const ctx = useContext(MapEngineContext);
  if (ctx === null) {
    throw new Error("useMapEngineHandle must be used inside MapEngineProvider");
  }
  return ctx;
}
