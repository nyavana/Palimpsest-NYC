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
