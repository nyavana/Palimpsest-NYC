/**
 * Thin EventSource wrapper that dispatches typed payloads to per-event
 * handlers. Keeps the parsing/error-handling shape out of the React reducer
 * so the hook can stay declarative.
 */

import type { SseEventName, SsePayloads } from "./types";

export type SseHandlers = {
  [K in SseEventName]?: (payload: SsePayloads[K]) => void;
};

export type SseSession = {
  close: () => void;
};

export function openAgentStream(
  question: string,
  handlers: SseHandlers,
  options: { onError?: (err: unknown) => void; baseUrl?: string } = {},
): SseSession {
  const base = options.baseUrl ?? "/api";
  const url = `${base}/agent/ask?q=${encodeURIComponent(question)}`;
  const source = new EventSource(url);

  const subs: Array<[string, (e: MessageEvent) => void]> = [];

  for (const [name, handler] of Object.entries(handlers)) {
    if (handler === undefined) continue;
    const listener = (e: MessageEvent) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(e.data);
      } catch (err) {
        options.onError?.(err);
        return;
      }
      // The handler is keyed by event name; the Object.entries pair has lost
      // its precise type, but the parsed payload is JSON the backend produced
      // against the typed schema. We trust the backend contract here.
      (handler as (p: unknown) => void)(parsed);
    };
    source.addEventListener(name, listener);
    subs.push([name, listener]);
  }

  source.onerror = (event) => {
    // EventSource emits `error` both for transient disconnects and for the
    // remote closing the stream. Surface to the caller; the hook decides what
    // to do (typically: ignore once `done` has arrived; otherwise surface).
    options.onError?.(event);
  };

  return {
    close: () => {
      for (const [name, listener] of subs) {
        source.removeEventListener(name, listener);
      }
      source.close();
    },
  };
}
