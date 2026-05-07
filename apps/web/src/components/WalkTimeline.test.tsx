/**
 * WalkTimeline rendering contract.
 *
 * NOTE: vitest is not yet wired up in this project (no devDependency in
 * `apps/web/package.json`). These tests describe the contract and will run
 * the moment vitest + @testing-library/react land — they currently sit
 * outside tsc's `include` and eslint's lint set (see `tsconfig.json`
 * excludes and `eslint.config.mjs` ignores).
 *
 * Spec: `agent-route-planning` §map-engine "Walk frame consumer renders
 * LineString geometry + steps" and design.md §9 (Frontend changes).
 */

import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import type { PlannedRoute } from "@/state/types";
import { MapEngineProvider } from "@/state/MapEngineContext";
import { TourFocusProvider } from "@/state/TourFocusContext";

import { WalkTimeline } from "./WalkTimeline";

const STEP_FIXTURES = [
  { instruction: "Head east on West 110th Street for 80 m", distance_m: 80, duration_s: 60, maneuver_type: "depart" },
  { instruction: "Turn right onto Broadway", distance_m: 220, duration_s: 165, maneuver_type: "turn" },
  { instruction: "Arrive at the destination", distance_m: 30, duration_s: 22, maneuver_type: "arrive" },
];

function fakeRoute(overrides: Partial<PlannedRoute> = {}): PlannedRoute {
  return {
    stops: [
      { index: 0, doc_id: "wikipedia:Cathedral_of_Saint_John_the_Divine", name: "Cathedral of St. John the Divine", lat: 40.804, lon: -73.962 },
      { index: 1, doc_id: "wikipedia:Riverside_Church", name: "Riverside Church", lat: 40.811, lon: -73.962 },
      { index: 2, doc_id: "wikipedia:Grants_Tomb", name: "Grant's Tomb", lat: 40.813, lon: -73.963 },
    ],
    legs: [
      {
        from_index: 0,
        to_index: 1,
        distance_m: 412,
        duration_s: 295,
        geometry: { type: "LineString", coordinates: [[-73.962, 40.804], [-73.962, 40.811]] },
        steps: STEP_FIXTURES,
      },
      {
        from_index: 1,
        to_index: 2,
        distance_m: 380,
        duration_s: 270,
        geometry: { type: "LineString", coordinates: [[-73.962, 40.811], [-73.963, 40.813]] },
        steps: STEP_FIXTURES,
      },
    ],
    geometry: { type: "LineString", coordinates: [[-73.962, 40.804], [-73.962, 40.811], [-73.963, 40.813]] },
    total_distance_m: 1245,
    total_duration_s: 890,
    stop_ordering: "tsp_optimized",
    routing_backend: "osrm",
    ...overrides,
  };
}

function renderWithProvider(walk: PlannedRoute | null) {
  return render(
    <TourFocusProvider>
      <MapEngineProvider>
        <WalkTimeline walk={walk} />
      </MapEngineProvider>
    </TourFocusProvider>,
  );
}

describe("WalkTimeline", () => {
  it("renders the totals footer with km + minute formatting", () => {
    renderWithProvider(fakeRoute());
    // 1245 m → "1.2 km", 890 s / 60 ≈ 15 min
    expect(screen.getByText(/Total\s*·\s*1\.2 km\s*·\s*~15 min/)).toBeInTheDocument();
  });

  it("renders sub-1km totals as integer meters", () => {
    renderWithProvider(fakeRoute({ total_distance_m: 850, total_duration_s: 600 }));
    // 850 m stays as meters; 600 s / 60 = 10 min
    expect(screen.getByText(/Total\s*·\s*850 m\s*·\s*~10 min/)).toBeInTheDocument();
  });

  it("hides the footer when totals are absent", () => {
    renderWithProvider(fakeRoute({ total_distance_m: undefined, total_duration_s: undefined }));
    expect(screen.queryByText(/^Total\s*·/)).not.toBeInTheDocument();
  });

  it("shows the TSP annotation only when stop_ordering is tsp_optimized", () => {
    const { rerender } = renderWithProvider(fakeRoute());
    expect(screen.getByText(/tsp-optimized/i)).toBeInTheDocument();

    rerender(
      <TourFocusProvider>
        <MapEngineProvider>
          <WalkTimeline walk={fakeRoute({ stop_ordering: "input_order" })} />
        </MapEngineProvider>
      </TourFocusProvider>,
    );
    expect(screen.queryByText(/tsp-optimized/i)).not.toBeInTheDocument();
  });

  it("does not render a disclosure for stop 0", () => {
    renderWithProvider(fakeRoute());
    // Stop 0's row has no incoming-leg disclosure trigger.
    const stop0List = screen.queryByLabelText("Turn-by-turn instructions for stop 1");
    expect(stop0List).not.toBeInTheDocument();
  });

  it("expands the disclosure on click and reveals numbered steps", () => {
    renderWithProvider(fakeRoute());

    const trigger = screen.getByRole("button", { expanded: false, name: /412 m/ });
    fireEvent.click(trigger);

    const stepsList = screen.getByLabelText("Turn-by-turn instructions for stop 2");
    const items = within(stepsList).getAllByRole("listitem");
    expect(items).toHaveLength(STEP_FIXTURES.length);
    // First instruction surfaced verbatim
    expect(within(items[0]).getByText(/Head east on West 110th Street/)).toBeInTheDocument();
    // Per-step distance label is rendered in the right gutter (the
    // standalone "80 m" span — anchored so it does not match the same
    // distance embedded in the instruction text).
    expect(within(items[0]).getByText(/^80 m$/)).toBeInTheDocument();

    // aria-expanded flips to true after the click
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("collapses on a second click", () => {
    renderWithProvider(fakeRoute());
    const trigger = screen.getByRole("button", { expanded: false, name: /412 m/ });
    fireEvent.click(trigger);
    fireEvent.click(trigger);
    expect(screen.queryByLabelText("Turn-by-turn instructions for stop 2")).not.toBeInTheDocument();
  });

  it("renders nothing when walk is null", () => {
    const { container } = renderWithProvider(null);
    expect(container.firstChild).toBeNull();
  });
});
