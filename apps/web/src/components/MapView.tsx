/**
 * MapView — thin React wrapper that mounts a MapEngine on a div.
 *
 * This component does not import maplibre-gl; ESLint blocks that for every
 * file outside `@/map/engines/`. All map behavior flows through the
 * `MapEngine` interface returned by `createMapEngine()`.
 */

import { useEffect, useRef } from "react";

import { DEFAULT_VIEWPORT, createMapEngine, type MapEngine } from "@/map";

export function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<MapEngine | null>(null);

  useEffect(() => {
    if (containerRef.current === null) {
      return;
    }
    const engine = createMapEngine();
    engineRef.current = engine;
    let cancelled = false;

    engine
      .init(containerRef.current, DEFAULT_VIEWPORT)
      .then(() => {
        if (cancelled) {
          engine.destroy();
        }
      })
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error("map init failed", err);
      });

    return () => {
      cancelled = true;
      engineRef.current?.destroy();
      engineRef.current = null;
    };
  }, []);

  return <div ref={containerRef} className="absolute inset-0" />;
}
