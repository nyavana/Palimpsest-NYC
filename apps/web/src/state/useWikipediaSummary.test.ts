import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import {
  useWikipediaSummary,
  __resetWikipediaCacheForTests,
} from "./useWikipediaSummary";

const MOCK_RESPONSE = {
  title: "Cathedral of St. John the Divine",
  extract: "A cathedral in Manhattan.",
  thumbnail: { source: "https://upload.wikimedia.org/x.jpg" },
  content_urls: { desktop: { page: "https://en.wikipedia.org/wiki/Cathedral_of_St._John_the_Divine" } },
};

function mockFetchOk(body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response);
}

beforeEach(() => {
  __resetWikipediaCacheForTests();
  vi.stubGlobal("fetch", mockFetchOk(MOCK_RESPONSE));
});

describe("useWikipediaSummary", () => {
  it("returns idle for null docId", () => {
    const { result } = renderHook(() => useWikipediaSummary(null));
    expect(result.current.status).toBe("idle");
  });

  it("returns idle for non-wikipedia docId", () => {
    const { result } = renderHook(() => useWikipediaSummary("osm:way/12345"));
    expect(result.current.status).toBe("idle");
  });

  it("fetches and returns success for a wikipedia: docId", async () => {
    const { result } = renderHook(() =>
      useWikipediaSummary("wikipedia:Cathedral_of_St._John_the_Divine"),
    );

    expect(result.current.status).toBe("loading");

    await waitFor(() => expect(result.current.status).toBe("success"));
    if (result.current.status !== "success") throw new Error("type narrow");

    expect(result.current.summary.title).toBe("Cathedral of St. John the Divine");
    expect(result.current.summary.extract).toBe("A cathedral in Manhattan.");
    expect(result.current.summary.thumbnailUrl).toBe("https://upload.wikimedia.org/x.jpg");
    expect(result.current.summary.pageUrl).toBe(
      "https://en.wikipedia.org/wiki/Cathedral_of_St._John_the_Divine",
    );
  });

  it("dedups concurrent fetches for the same docId", async () => {
    const fetchSpy = mockFetchOk(MOCK_RESPONSE);
    vi.stubGlobal("fetch", fetchSpy);

    const docId = "wikipedia:Low_Memorial_Library";
    const a = renderHook(() => useWikipediaSummary(docId));
    const b = renderHook(() => useWikipediaSummary(docId));

    await waitFor(() => expect(a.result.current.status).toBe("success"));
    await waitFor(() => expect(b.result.current.status).toBe("success"));

    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("returns error on non-2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404 } as unknown as Response),
    );

    const { result } = renderHook(() => useWikipediaSummary("wikipedia:Nonexistent"));

    await waitFor(() => expect(result.current.status).toBe("error"));
  });

  it("returns error on rejected fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));

    const { result } = renderHook(() => useWikipediaSummary("wikipedia:NetworkFailure"));

    await waitFor(() => expect(result.current.status).toBe("error"));
  });

  it("handles missing thumbnail gracefully", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetchOk({
        title: "T",
        extract: "X",
        content_urls: { desktop: { page: "https://en.wikipedia.org/wiki/T" } },
      }),
    );

    const { result } = renderHook(() => useWikipediaSummary("wikipedia:T"));

    await waitFor(() => expect(result.current.status).toBe("success"));
    if (result.current.status !== "success") throw new Error("type narrow");
    expect(result.current.summary.thumbnailUrl).toBeNull();
  });
});
