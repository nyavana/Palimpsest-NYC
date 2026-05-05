import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MarkerInfoCard } from "./MarkerInfoCard";
import type { Citation, PlannedStop } from "@/state/types";

const stop: PlannedStop = {
  index: 0,
  doc_id: "wikipedia:Low_Memorial_Library",
  name: "Low Memorial Library",
  lat: 40.808,
  lon: -73.961,
  leg_distance_m: 0,
};

const citation: Citation = {
  doc_id: "wikipedia:Low_Memorial_Library",
  source_url: "https://en.wikipedia.org/wiki/Low_Memorial_Library",
  source_type: "wikipedia",
  span: "An iconic Beaux-Arts library on Columbia's Morningside campus.",
  retrieval_turn: 1,
};

vi.mock("@/state/useWikipediaSummary", () => ({
  useWikipediaSummary: vi.fn(),
}));

import { useWikipediaSummary } from "@/state/useWikipediaSummary";
const mockedHook = vi.mocked(useWikipediaSummary);

describe("MarkerInfoCard", () => {
  it("hover variant renders just number + name", () => {
    render(<MarkerInfoCard variant="hover" stop={stop} citation={citation} onClose={() => {}} />);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("Low Memorial Library")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
  });

  it("pinned variant with wikipedia success shows thumbnail + extract + close", () => {
    mockedHook.mockReturnValue({
      status: "success",
      summary: {
        title: "Low Memorial Library",
        extract: "Designed by Charles McKim.",
        thumbnailUrl: "https://upload.wikimedia.org/x.jpg",
        pageUrl: "https://en.wikipedia.org/wiki/Low_Memorial_Library",
      },
    });

    render(<MarkerInfoCard variant="pinned" stop={stop} citation={citation} onClose={() => {}} />);

    expect(screen.getByRole("img")).toHaveAttribute("src", "https://upload.wikimedia.org/x.jpg");
    expect(screen.getByText("Designed by Charles McKim.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /close/i })).toBeInTheDocument();
  });

  it("pinned variant with wikipedia loading shows skeleton", () => {
    mockedHook.mockReturnValue({ status: "loading" });

    render(<MarkerInfoCard variant="pinned" stop={stop} citation={citation} onClose={() => {}} />);

    expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
  });

  it("pinned variant with wikipedia error falls back to citation span + link", () => {
    mockedHook.mockReturnValue({ status: "error" });

    render(<MarkerInfoCard variant="pinned" stop={stop} citation={citation} onClose={() => {}} />);

    expect(screen.getByText(citation.span)).toBeInTheDocument();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", citation.source_url);
  });

  it("pinned variant for OSM doc shows span only, no fetch", () => {
    mockedHook.mockReturnValue({ status: "idle" });

    const osmStop = { ...stop, doc_id: "osm:way/12345" };
    const osmCit: Citation = {
      ...citation,
      doc_id: "osm:way/12345",
      source_type: "osm",
      source_url: "https://www.openstreetmap.org/way/12345",
      span: "A historic stoop on West 116th.",
    };

    render(<MarkerInfoCard variant="pinned" stop={osmStop} citation={osmCit} onClose={() => {}} />);

    expect(screen.getByText("A historic stoop on West 116th.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("pinned variant with no citation shows just name", () => {
    mockedHook.mockReturnValue({ status: "idle" });

    render(<MarkerInfoCard variant="pinned" stop={stop} citation={null} onClose={() => {}} />);

    expect(screen.getByText("Low Memorial Library")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("close button calls onClose", async () => {
    mockedHook.mockReturnValue({ status: "idle" });

    const onClose = vi.fn();
    render(<MarkerInfoCard variant="pinned" stop={stop} citation={null} onClose={onClose} />);

    await userEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
