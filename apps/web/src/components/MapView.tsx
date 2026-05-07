/**
 * MapView — mounts a MapEngine on a div, draws the walk (path + markers),
 * and hosts the marker info popups + the 2D/3D toggle overlay.
 *
 * Popups: the host element is React-owned (a stable div referenced via
 * useRef), mounted into the engine's popup container by `engine.setPopup`.
 * React renders MarkerInfoCard into that host via createPortal.
 *
 * Walk drawing: when `walk` changes, we replace the `walk` layer through the
 * engine interface. No `maplibre-gl` imports — the eslint rule blocks that
 * for everything outside `@/map/engines/`.
 *
 * Path source of truth, in priority order:
 *   1. `walk.geometry.coordinates` (the OSRM-routed LineString) — the only
 *      vertex-by-vertex source per `agent-route-planning` spec §map-engine.
 *   2. Otherwise, fall back to the stop coordinates as a straight-line draft
 *      (legacy V1 walks that don't carry `geometry`).
 *
 * No polyline decoder. GeoJSON LineString feeds the engine's geojson source
 * natively; we only need to swap `[lon, lat] → {lat, lng}` shape.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { DEFAULT_VIEWPORT, createMapEngine, type MapEngine } from "@/map";
import type { LatLng, MarkerEvent, Viewport } from "@/map";
import type { PathStyle } from "@/map/types";
import type { Citation, FoodCandidate, PlannedRoute, PlannedStop } from "@/state/types";
import { useMapEngineHandle } from "@/state/MapEngineContext";
import { useTourFocus } from "@/state/TourFocusContext";

import { MarkerInfoCard } from "./MarkerInfoCard";
import {
  MapViewModeToggle,
  readSavedViewMode,
  writeSavedViewMode,
  type MapViewMode,
} from "./MapViewModeToggle";

const WALK_LAYER = "walk";
const FOOD_LAYER = "food-candidates";
const PATH_COLOR = "#5364C0"; // tokens.palette["archival-blue"] — royal indigo
const FALLBACK_PATH_COLOR = "#6A6F8C"; // tokens.palette["ink-muted"] — cool gray
const MARKER_COLOR = "#77295D"; // tokens.palette.oxblood — plum
const ACTIVE_MARKER_COLOR = "#5364C0"; // archival-blue
const FOOD_MARKER_COLOR = "#A35A17"; // warm ochre for food candidates
const FLYTO_DURATION_MS = 1200;
const TOGGLE_FLY_MS = 600;
const PINNED_FLY_MIN_ZOOM = 17.5;

type Props = {
  walk: PlannedRoute | null;
  citations: Citation[];
  candidates: FoodCandidate[];
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

function parseCandidateIndex(markerId: string): number | null {
  const m = /^food-(\d+)$/.exec(markerId);
  if (m === null) return null;
  const n = Number.parseInt(m[1], 10);
  return Number.isFinite(n) ? n : null;
}

/**
 * Convert an OSRM/GeoJSON `[lon, lat][]` array to the engine-facing
 * `{lat, lng}[]`. RFC 7946 LineString is `[longitude, latitude]`; the engine
 * speaks `{lat, lng}`. Centralized here so the swap is a one-liner.
 */
function geojsonCoordsToLatLng(coords: [number, number][]): LatLng[] {
  return coords.map(([lng, lat]) => ({ lat, lng }));
}

/** Stops as a `LatLng[]` for the legacy straight-line fallback path. */
function stopsToLatLng(walk: PlannedRoute): LatLng[] {
  return walk.stops.map((s) => ({ lat: s.lat, lng: s.lon }));
}

export function MapView({ walk, citations, candidates }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const popupHostRef = useRef<HTMLDivElement | null>(null);
  const cameraRef = useRef<Viewport>({ ...DEFAULT_VIEWPORT });
  const engineRef = useRef<MapEngine | null>(null);
  const lastCandidateSignatureRef = useRef<string>("");
  const handle = useMapEngineHandle();
  const { focus: tourFocus, focusDocId } = useTourFocus();
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
  const stopByDocId = useMemo(
    () => new Map((walk?.stops ?? []).map((s) => [s.doc_id, s] as const)),
    [walk],
  );
  const candidateByDocId = useMemo(
    () => new Map(candidates.map((candidate) => [candidate.doc_id, candidate] as const)),
    [candidates],
  );

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
      const stopIdx = parseStopIndex(e.markerId);
      const stop = stopIdx === null ? null : walk?.stops.find((s) => s.index === stopIdx) ?? null;
      if (stop !== null) {
        focusDocId(stop.doc_id);
        return;
      }
      const candidateIndex = parseCandidateIndex(e.markerId);
      const candidate = candidateIndex === null ? null : candidates[candidateIndex] ?? null;
      if (candidate !== null) {
        focusDocId(candidate.doc_id);
        return;
      }
      setFocus({ kind: "pinned", markerId: e.markerId, at: e.at });
    });

    return () => {
      offCamera();
      offHover();
      offClick();
    };
  }, [candidates, focusDocId, ready, walk]);

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

  // Reset focus and clear popup whenever the walk changes.
  useEffect(() => {
    setFocus({ kind: "idle" });
  }, [candidates, walk]);

  useEffect(() => {
    if (!ready) return;
    if (tourFocus.docId === null) return;
    const stop = stopByDocId.get(tourFocus.docId);
    const candidate = candidateByDocId.get(tourFocus.docId);
    if (stop === undefined && candidate === undefined) return;
    const fallbackCandidate = candidate ?? null;
    const candidateIndex =
      fallbackCandidate === null
        ? -1
        : candidates.findIndex((entry) => entry.doc_id === fallbackCandidate.doc_id);

    const at =
      stop !== undefined
        ? { lat: stop.lat, lng: stop.lon }
        : { lat: fallbackCandidate!.lat, lng: fallbackCandidate!.lon };
    setFocus({
      kind: "pinned",
      markerId: stop !== undefined ? `stop-${stop.index}` : `food-${Math.max(candidateIndex, 0)}`,
      at,
    });

    const engine = engineRef.current;
    if (engine === null) return;
    const cur = cameraRef.current;
    void engine.flyTo(
      {
        center: at,
        zoom: Math.max(cur.zoom, PINNED_FLY_MIN_ZOOM),
        pitch: cur.pitch ?? pitchForMode(viewMode),
        bearing: cur.bearing,
      },
      FLYTO_DURATION_MS,
    );
  }, [candidateByDocId, candidates, ready, stopByDocId, tourFocus.docId, tourFocus.version, viewMode]);

  // Draw / clear the walk layer whenever the walk frame changes.
  useEffect(() => {
    if (!ready) return;
    const engine = engineRef.current;
    if (engine === null) return;

    if (walk === null || walk.stops.length === 0) {
      engine.clearLayer(WALK_LAYER);
      return;
    }

    // Prefer the routed GeoJSON LineString when present; fall back to a
    // straight line through stops for legacy V1 frames without geometry.
    const pathCoords: LatLng[] =
      walk.geometry !== undefined && walk.geometry.coordinates.length >= 2
        ? geojsonCoordsToLatLng(walk.geometry.coordinates)
        : stopsToLatLng(walk);

    // Subtle visual signal when the routing engine fell back to haversine —
    // a thoughtful reviewer can tell the path is a draft, not a real route.
    const degraded = walk.routing_backend === "haversine_fallback";
    const pathStyle: PathStyle = {
      color: degraded ? FALLBACK_PATH_COLOR : PATH_COLOR,
      widthPx: 4,
      opacity: degraded ? 0.7 : 0.85,
      dashed: degraded,
    };

    engine.addPath(WALK_LAYER, pathCoords, pathStyle);
    engine.addMarkers(
      WALK_LAYER,
      walk.stops.map((s) => ({
        id: `stop-${s.index}`,
        position: { lat: s.lat, lng: s.lon },
        label: `${s.index + 1}. ${s.name}`,
        color: s.doc_id === tourFocus.docId ? ACTIVE_MARKER_COLOR : MARKER_COLOR,
      })),
    );

    // Frame the walk: fly to the first stop with the active tour pitch.
    // Per-stop fly-to from the timeline takes over once the user navigates.
    const first = walk.stops[0];
    if (first) {
      void engine.flyTo(
        { center: { lat: first.lat, lng: first.lon }, zoom: 15.5, pitch: pitchForMode(viewMode) },
        FLYTO_DURATION_MS,
      );
    }
  }, [tourFocus.docId, walk, ready, viewMode]);

  useEffect(() => {
    if (!ready) return;
    const engine = engineRef.current;
    if (engine === null) return;

    if (candidates.length === 0) {
      engine.clearLayer(FOOD_LAYER);
      return;
    }

    engine.addMarkers(
      FOOD_LAYER,
      candidates.map((candidate, index) => ({
        id: `food-${index}`,
        position: { lat: candidate.lat, lng: candidate.lon },
        label: candidate.name,
        color: candidate.doc_id === tourFocus.docId ? ACTIVE_MARKER_COLOR : FOOD_MARKER_COLOR,
      })),
    );
  }, [candidates, ready, tourFocus.docId]);

  useEffect(() => {
    if (!ready) return;
    if (candidates.length === 0) {
      lastCandidateSignatureRef.current = "";
      return;
    }

    const signature = candidates.map((candidate) => candidate.doc_id).join("|");
    if (signature === lastCandidateSignatureRef.current) return;
    lastCandidateSignatureRef.current = signature;

    const first = candidates[0];
    const at = { lat: first.lat, lng: first.lon };
    setFocus({ kind: "pinned", markerId: "food-0", at });

    const engine = engineRef.current;
    if (engine === null) return;
    const cur = cameraRef.current;
    void engine.flyTo(
      {
        center: at,
        zoom: Math.max(cur.zoom, 16.25),
        pitch: cur.pitch ?? pitchForMode(viewMode),
        bearing: cur.bearing,
      },
      FLYTO_DURATION_MS,
    );
  }, [candidates, ready, viewMode]);

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
  const focusedCandidateIndex =
    focus.kind === "idle" ? null : parseCandidateIndex(focus.markerId);
  const focusedStop =
    focusedStopIndex === null
      ? null
      : walk?.stops.find((s) => s.index === focusedStopIndex) ?? null;
  const focusedCandidate =
    focusedCandidateIndex === null ? null : candidates[focusedCandidateIndex] ?? null;
  const focusedCitation =
    focusedStop === null ? null : citationByDocId.get(focusedStop.doc_id) ?? null;
  const focusedPopupStop: PlannedStop | null =
    focusedStop ??
    (focusedCandidate === null
      ? null
      : {
          index: focusedCandidateIndex ?? 0,
          doc_id: focusedCandidate.doc_id,
          name: focusedCandidate.name,
          lat: focusedCandidate.lat,
          lon: focusedCandidate.lon,
        });
  const focusedBodyText =
    focusedCandidate === null
      ? null
      : [focusedCandidate.cuisine?.replace(/;/g, ", "), focusedCandidate.why]
          .filter((part): part is string => part !== undefined && part !== null && part.length > 0)
          .join(" - ");

  return (
    <>
      <div ref={containerRef} className="absolute inset-0" />
      <div className="pointer-events-none absolute left-4 top-24 z-10">
        <div className="pointer-events-auto">
          <MapViewModeToggle mode={viewMode} onChange={handleViewModeChange} />
        </div>
      </div>
      {focus.kind !== "idle" && focusedPopupStop !== null && popupHostRef.current !== null
        ? createPortal(
            <MarkerInfoCard
              variant={focus.kind === "pinned" ? "pinned" : "hover"}
              stop={focusedPopupStop}
              citation={focusedCitation}
              bodyText={focusedBodyText}
              onClose={() => setFocus({ kind: "idle" })}
              onRevealCitation={
                focusedCitation !== null ? () => focusDocId(focusedPopupStop.doc_id) : undefined
              }
            />,
            popupHostRef.current,
          )
        : null}
    </>
  );
}
