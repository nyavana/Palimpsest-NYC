import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MapView } from "./MapView";
import { MapEngineProvider } from "@/state/MapEngineContext";
import { TourFocusProvider } from "@/state/TourFocusContext";
import type { Citation, PlannedRoute } from "@/state/types";

// Mocked engine — lets tests drive marker events and assert flyTo / addPath calls.
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

// Mock `@/map` without `importActual` — pulling the real module triggers
// the eager `MaplibreEngine` import which loads maplibre-gl, and that blows
// up under jsdom (no `window.URL.createObjectURL`). Re-export only what
// MapView consumes.
vi.mock("@/map", () => ({
  createMapEngine: () => fakeEngine,
  DEFAULT_VIEWPORT: {
    center: { lat: 40.8075, lng: -73.9626 },
    zoom: 15.5,
    bearing: 0,
    pitch: 60,
  },
}));

vi.mock("@/state/useWikipediaSummary", () => ({
  useWikipediaSummary: () => ({ status: "idle" as const }),
}));

const walk: PlannedRoute = {
  stops: [
    {
      index: 0,
      doc_id: "wikipedia:Low_Memorial_Library",
      name: "Low Memorial Library",
      lat: 40.808,
      lon: -73.961,
    },
    {
      index: 1,
      doc_id: "wikipedia:Cathedral_of_St._John_the_Divine",
      name: "Cathedral of St. John the Divine",
      lat: 40.804,
      lon: -73.96,
    },
  ],
};

const citations: Citation[] = [
  {
    doc_id: walk.stops[0].doc_id,
    source_url: "https://en.wikipedia.org/wiki/Low_Memorial_Library",
    source_type: "wikipedia",
    span: "An iconic library.",
    retrieval_turn: 1,
  },
];

const ROUTED_WALK: PlannedRoute = {
  stops: [
    { index: 0, doc_id: "wikipedia:A", name: "A", lat: 40.804, lon: -73.962 },
    { index: 1, doc_id: "wikipedia:B", name: "B", lat: 40.811, lon: -73.962 },
  ],
  legs: [
    {
      from_index: 0,
      to_index: 1,
      distance_m: 412,
      duration_s: 295,
      geometry: {
        type: "LineString",
        coordinates: [
          [-73.962, 40.804],
          [-73.961, 40.808],
          [-73.962, 40.811],
        ],
      },
      steps: [],
    },
  ],
  geometry: {
    type: "LineString",
    coordinates: [
      [-73.962, 40.804],
      [-73.961, 40.808],
      [-73.962, 40.811],
    ],
  },
  total_distance_m: 412,
  total_duration_s: 295,
  routing_backend: "osrm",
  stop_ordering: "input_order",
};

beforeEach(() => {
  // The global setup file runs `vi.restoreAllMocks()` which wipes out
  // `mockResolvedValue` implementations. Re-establish them so init() and
  // flyTo() return Promises.
  fakeEngine.init.mockReset().mockResolvedValue(undefined);
  fakeEngine.flyTo.mockReset().mockResolvedValue(undefined);
  fakeEngine.setViewport.mockReset();
  fakeEngine.addMarkers.mockReset();
  fakeEngine.addPath.mockReset();
  fakeEngine.clearLayer.mockReset();
  fakeEngine.destroy.mockReset();
  fakeEngine.setPopup.mockReset().mockImplementation((_at, el) => {
    fakeEngine.popupEl = el;
  });
  fakeEngine.clearPopup.mockReset().mockImplementation(() => {
    fakeEngine.popupEl = null;
  });
  fakeEngine.onMarkerHover.mockReset().mockImplementation((cb) => {
    fakeEngine.hoverCb = cb;
    return () => {};
  });
  fakeEngine.onMarkerClick.mockReset().mockImplementation((cb) => {
    fakeEngine.clickCb = cb;
    return () => {};
  });
  fakeEngine.onCameraChange.mockReset().mockImplementation((cb) => {
    fakeEngine.cameraCb = cb;
    return () => {};
  });
  fakeEngine.popupEl = null;
  fakeEngine.hoverCb = null;
  fakeEngine.clickCb = null;
});

async function renderMap(props: {
  walk: PlannedRoute | null;
  citations: Citation[];
  candidates?: {
    doc_id: string;
    name: string;
    source_type: "osm";
    source_url: string;
    lat: number;
    lon: number;
    distance_m: number | null;
    amenity: string | null;
    cuisine: string | null;
    why: string;
    tags: Record<string, unknown>;
  }[];
}) {
  const utils = render(
    <TourFocusProvider>
      <MapEngineProvider>
        <MapView {...props} candidates={props.candidates ?? []} />
      </MapEngineProvider>
    </TourFocusProvider>,
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
    await renderMap({ walk, citations });
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
    await renderMap({ walk, citations });

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
    await renderMap({ walk, citations });

    act(() => {
      fakeEngine.clickCb!({ layerId: "walk", markerId: "stop-0", at: { lat: 40.808, lng: -73.961 } });
    });

    await userEvent.keyboard("{Escape}");
    expect(fakeEngine.clearPopup).toHaveBeenCalled();
  });

  it("clears popup state when the walk changes", async () => {
    const { rerender } = await renderMap({ walk, citations });

    act(() => {
      fakeEngine.clickCb!({ layerId: "walk", markerId: "stop-0", at: { lat: 40.808, lng: -73.961 } });
    });

    rerender(
      <TourFocusProvider>
        <MapEngineProvider>
          <MapView walk={null} citations={[]} candidates={[]} />
        </MapEngineProvider>
      </TourFocusProvider>,
    );

    expect(fakeEngine.clearPopup).toHaveBeenCalled();
  });
});

// MapView contract: when a walk frame carries a GeoJSON LineString, MapView
// passes its coords (after `[lon, lat] → {lat, lng}` conversion) directly
// into `engine.addPath("walk", coords)`. There is no decoder helper.
//
// Spec: `agent-route-planning` §map-engine ADDED requirement "Walk frame
// consumer renders LineString geometry + steps", scenario "Walk frame with
// GeoJSON LineString renders street-following path".
describe("MapView path drawing", () => {
  it("feeds walk.geometry.coordinates into engine.addPath after lon/lat → lat/lng swap", async () => {
    await renderMap({ walk: ROUTED_WALK, citations: [] });

    await waitFor(() => {
      expect(fakeEngine.addPath).toHaveBeenCalledWith(
        "walk",
        // RFC 7946 [lon, lat] → engine {lat, lng}
        [
          { lat: 40.804, lng: -73.962 },
          { lat: 40.808, lng: -73.961 },
          { lat: 40.811, lng: -73.962 },
        ],
        expect.objectContaining({ widthPx: 4 }),
      );
    });
  });

  it("falls back to straight-line stop coords when walk.geometry is absent (legacy V1)", async () => {
    const legacy: PlannedRoute = { stops: ROUTED_WALK.stops };
    await renderMap({ walk: legacy, citations: [] });

    await waitFor(() => {
      expect(fakeEngine.addPath).toHaveBeenCalledWith(
        "walk",
        [
          { lat: 40.804, lng: -73.962 },
          { lat: 40.811, lng: -73.962 },
        ],
        expect.any(Object),
      );
    });
  });

  it("renders haversine-fallback paths with a dashed/muted style", async () => {
    await renderMap({
      walk: { ...ROUTED_WALK, routing_backend: "haversine_fallback" },
      citations: [],
    });

    await waitFor(() => {
      const lastCall = fakeEngine.addPath.mock.calls.at(-1)!;
      const style = lastCall[2] as { dashed?: boolean };
      expect(style.dashed).toBe(true);
    });
  });

  it("clears the walk layer when walk is null", async () => {
    await renderMap({ walk: null, citations: [] });

    await waitFor(() => {
      expect(fakeEngine.clearLayer).toHaveBeenCalledWith("walk");
    });
    expect(fakeEngine.addPath).not.toHaveBeenCalled();
  });

  it("renders a separate marker layer for food candidates", async () => {
    await renderMap({
      walk: null,
      citations: [],
      candidates: [
        {
          doc_id: "osm:node:food-1",
          name: "Campus Ramen",
          source_type: "osm",
          source_url: "https://www.openstreetmap.org/node/1",
          lat: 40.8072,
          lon: -73.9641,
          distance_m: 220,
          amenity: "restaurant",
          cuisine: "ramen;japanese",
          why: "Good match for ramen",
          tags: {},
        },
      ],
    });

    await waitFor(() => {
      expect(fakeEngine.addMarkers).toHaveBeenCalledWith(
        "food-candidates",
        [
          expect.objectContaining({
            id: "food-0",
            label: "Campus Ramen",
          }),
        ],
      );
    });
  });

  it("flies to the first food candidate when a new result set arrives", async () => {
    await renderMap({
      walk: null,
      citations: [],
      candidates: [
        {
          doc_id: "osm:node:food-1",
          name: "Campus Ramen",
          source_type: "osm",
          source_url: "https://www.openstreetmap.org/node/1",
          lat: 40.8072,
          lon: -73.9641,
          distance_m: 220,
          amenity: "restaurant",
          cuisine: "ramen;japanese",
          why: "Good match for ramen",
          tags: {},
        },
      ],
    });

    await waitFor(() => {
      expect(fakeEngine.flyTo).toHaveBeenCalledWith(
        expect.objectContaining({
          center: { lat: 40.8072, lng: -73.9641 },
        }),
        expect.any(Number),
      );
    });
  });
});
