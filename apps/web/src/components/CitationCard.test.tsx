import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Citation } from "@/state/types";

import { CitationCard } from "./CitationCard";

const citation: Citation = {
  doc_id: "wikipedia:Riverside_Church",
  source_url: "https://en.wikipedia.org/wiki/Riverside_Church",
  source_type: "wikipedia",
  span: "Neo-Gothic church overlooking the Hudson.",
  retrieval_turn: 2,
};

describe("CitationCard", () => {
  it("renders a map-focus button when onFocus is provided", async () => {
    const onFocus = vi.fn();
    render(<CitationCard citation={citation} title="Riverside Church" onFocus={onFocus} />);

    await userEvent.click(screen.getByRole("button", { name: /show riverside church on the map/i }));
    expect(onFocus).toHaveBeenCalledOnce();
  });

  it("omits the map-focus button when no mapped stop is available", () => {
    render(<CitationCard citation={citation} title="Riverside Church" />);
    expect(screen.queryByRole("button", { name: /show .* on the map/i })).toBeNull();
  });
});
