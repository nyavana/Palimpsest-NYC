import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { openAgentStream } from "./sse";

function makeStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i >= chunks.length) {
        controller.close();
        return;
      }
      controller.enqueue(encoder.encode(chunks[i] ?? ""));
      i += 1;
    },
  });
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

let fetchSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
});

async function flushMicrotasks() {
  for (let i = 0; i < 5; i++) {
    await Promise.resolve();
  }
}

describe("openAgentStream", () => {
  it("dispatches handlers in frame order", async () => {
    const body = makeStream([frame("turn", { index: 1 }), frame("done", { result: null })]);
    fetchSpy.mockResolvedValueOnce(new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }));

    const calls: string[] = [];
    openAgentStream("hi", {
      turn: () => calls.push("turn"),
      done: () => calls.push("done"),
    });

    // Wait for the async stream consumer to finish.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(calls).toEqual(["turn", "done"]);
  });

  it("posts to /api/agent/ask with JSON body containing q", async () => {
    const body = makeStream([frame("done", { result: null })]);
    fetchSpy.mockResolvedValueOnce(new Response(body, { status: 200 }));

    openAgentStream("hello world", { done: () => {} });
    await flushMicrotasks();

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/agent/ask");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ q: "hello world" }));
  });

  it("does NOT include X-LLM-Credentials header when no credentials are supplied", async () => {
    const body = makeStream([frame("done", { result: null })]);
    fetchSpy.mockResolvedValueOnce(new Response(body, { status: 200 }));

    openAgentStream("q", { done: () => {} });
    await flushMicrotasks();

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-LLM-Credentials"]).toBeUndefined();
  });

  it("includes X-LLM-Credentials header (base64 JSON) when credentials are supplied", async () => {
    const body = makeStream([frame("done", { result: null })]);
    fetchSpy.mockResolvedValueOnce(new Response(body, { status: 200 }));

    openAgentStream(
      "q",
      { done: () => {} },
      { credentials: { api_key: "sk-user", model: "openai/x", base_url: "https://x.test" } },
    );
    await flushMicrotasks();

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers["X-LLM-Credentials"]).toBeDefined();
    const decoded = JSON.parse(atob(headers["X-LLM-Credentials"] as string));
    expect(decoded).toEqual({
      api_key: "sk-user",
      model: "openai/x",
      base_url: "https://x.test",
    });
  });

  it("invokes onError with status + detail on non-2xx responses", async () => {
    const errorBody = JSON.stringify({ detail: { error: "byok_required" } });
    fetchSpy.mockResolvedValueOnce(
      new Response(errorBody, {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const onError = vi.fn();
    openAgentStream("q", {}, { onError });
    await flushMicrotasks();

    expect(onError).toHaveBeenCalledTimes(1);
    const arg = onError.mock.calls[0]?.[0] as { status: number; detail: { detail: { error: string } } };
    expect(arg.status).toBe(400);
    expect(arg.detail.detail.error).toBe("byok_required");
  });

  it("handles split chunks across frame boundaries", async () => {
    // Split one frame across two reader chunks to exercise buffering.
    const f1 = frame("turn", { index: 1 });
    const split = Math.floor(f1.length / 2);
    const body = makeStream([f1.slice(0, split), f1.slice(split), frame("done", { result: null })]);
    fetchSpy.mockResolvedValueOnce(new Response(body, { status: 200 }));

    const turns: number[] = [];
    let doneCount = 0;
    openAgentStream("q", {
      turn: (p) => turns.push(p.index),
      done: () => {
        doneCount += 1;
      },
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(turns).toEqual([1]);
    expect(doneCount).toBe(1);
  });
});
