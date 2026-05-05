import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, act } from "@testing-library/react";
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

const stops: PlannedStop[] = [
  { index: 0, doc_id: "wikipedia:Low_Memorial_Library", name: "Low Memorial Library", lat: 40.808, lon: -73.961, leg_distance_m: 0 },
  { index: 1, doc_id: "wikipedia:Cathedral_of_St._John_the_Divine", name: "Cathedral of St. John the Divine", lat: 40.804, lon: -73.96, leg_distance_m: 250 },
];

const citations: Citation[] = [
  { doc_id: stops[0].doc_id, source_url: "https://en.wikipedia.org/wiki/Low_Memorial_Library", source_type: "wikipedia", span: "An iconic library.", retrieval_turn: 1 },
];

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
