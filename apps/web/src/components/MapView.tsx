/**
 * MapView — thin React wrapper that mounts a MapEngine on a div and shares
 * the live engine handle via `MapEngineProvider`.
 *
 * Drawing the walk (path layer + stop markers) lives here too: when
 * `stops` changes, we replace the `walk` layer through the engine
 * interface. No `maplibre-gl` imports — the eslint rule blocks that for
 * everything outside `@/map/engines/`.
 */

import { useEffect, useRef, useState } from "react";

import { DEFAULT_VIEWPORT, createMapEngine, type MapEngine } from "@/map";
import type { PlannedStop } from "@/state/types";
import { useMapEngineHandle } from "@/state/MapEngineContext";

const WALK_LAYER = "walk";
const PATH_COLOR = "#7a1f1f"; // tokens.palette.oxblood
const MARKER_COLOR = "#7a1f1f";

type Props = {
  stops: PlannedStop[];
};

export function MapView({ stops }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<MapEngine | null>(null);
  const handle = useMapEngineHandle();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (containerRef.current === null) return;
    const engine = createMapEngine();
    engineRef.current = engine;
    let cancelled = false;

    engine
      .init(containerRef.current, DEFAULT_VIEWPORT)
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

  // Draw / clear the walk layer whenever stops change.
  useEffect(() => {
    if (!ready) return;
    const engine = engineRef.current;
    if (engine === null) return;

    if (stops.length === 0) {
      engine.clearLayer(WALK_LAYER);
      return;
    }

    const coords = stops.map((s) => ({ lat: s.lat, lng: s.lon }));
    engine.addPath(WALK_LAYER, coords, {
      color: PATH_COLOR,
      widthPx: 4,
      opacity: 0.85,
    });
    engine.addMarkers(
      WALK_LAYER,
      stops.map((s) => ({
        id: `stop-${s.index}`,
        position: { lat: s.lat, lng: s.lon },
        label: `${s.index + 1}. ${s.name}`,
        color: MARKER_COLOR,
      })),
    );

    // Frame the walk: fit to first stop with extra padding so the whole
    // route is in view, but defer to per-stop fly-to from the timeline.
    const first = stops[0];
    if (first) {
      void engine.flyTo(
        {
          center: { lat: first.lat, lng: first.lon },
          zoom: 15.5,
          pitch: 60,
        },
        1200,
      );
    }
  }, [stops, ready]);

  return <div ref={containerRef} className="absolute inset-0" />;
}
