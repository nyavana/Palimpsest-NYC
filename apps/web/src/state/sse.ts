/**
 * Streaming agent transport — POST /agent/ask via fetch + ReadableStream.
 *
 * V1.1 (BYOK): the endpoint is POST so the X-LLM-Credentials header (and
 * the question body) stay out of URLs and access logs. EventSource can't
 * send custom headers, hence the manual fetch-streaming parser below.
 *
 * Frames follow the standard SSE shape:
 *   event: <type>\n
 *   data:  <json>\n
 *   \n
 * Multiple `data:` lines on one frame are joined with `\n` per RFC.
 */

import {
  encodeCredentialsHeader,
  type LlmCredentials,
} from "./llmCredentials";
import type { SseEventName, SsePayloads } from "./types";

export type SseHandlers = {
  [K in SseEventName]?: (payload: SsePayloads[K]) => void;
};

export type SseSession = {
  close: () => void;
};

export type OpenAgentStreamOptions = {
  baseUrl?: string;
  credentials?: LlmCredentials | null;
  onError?: (err: unknown) => void;
};

export function openAgentStream(
  question: string,
  handlers: SseHandlers,
  options: OpenAgentStreamOptions = {},
): SseSession {
  const baseUrl = options.baseUrl ?? "/api";
  const url = `${baseUrl}/agent/ask`;
  const controller = new AbortController();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  if (options.credentials) {
    headers["X-LLM-Credentials"] = encodeCredentialsHeader(options.credentials);
  }

  void (async () => {
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify({ q: question }),
        signal: controller.signal,
      });

      if (!resp.ok) {
        // Surface the structured error body when present so the UI can
        // distinguish 400 byok_required / invalid_credentials_* cases.
        let detail: unknown;
        try {
          detail = await resp.json();
        } catch {
          detail = await resp.text().catch(() => null);
        }
        options.onError?.({
          status: resp.status,
          statusText: resp.statusText,
          detail,
        });
        return;
      }

      const body = resp.body;
      if (body === null) {
        options.onError?.(new Error("response_body_missing"));
        return;
      }

      await consumeStream(body, handlers, options.onError);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      options.onError?.(err);
    }
  })();

  return {
    close: () => {
      controller.abort();
    },
  };
}

async function consumeStream(
  body: ReadableStream<Uint8Array>,
  handlers: SseHandlers,
  onError?: (err: unknown) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. We accept both \n\n and
    // \r\n\r\n so a proxy that rewrites line endings doesn't break us.
    let separatorIdx: number;
    while ((separatorIdx = findFrameBoundary(buffer)) !== -1) {
      const rawFrame = buffer.slice(0, separatorIdx);
      buffer = buffer.slice(separatorIdx + (buffer.startsWith("\r\n", separatorIdx) ? 4 : 2));
      dispatchFrame(rawFrame, handlers, onError);
    }
  }

  // Any trailing content without a terminator is incomplete; ignore.
}

function findFrameBoundary(buffer: string): number {
  const lf = buffer.indexOf("\n\n");
  const crlf = buffer.indexOf("\r\n\r\n");
  if (lf === -1) return crlf;
  if (crlf === -1) return lf;
  return Math.min(lf, crlf);
}

function dispatchFrame(
  rawFrame: string,
  handlers: SseHandlers,
  onError?: (err: unknown) => void,
): void {
  if (rawFrame.length === 0) return;
  let event: string | null = null;
  const dataLines: string[] = [];
  for (const line of rawFrame.split(/\r?\n/)) {
    if (line.startsWith(":")) continue; // SSE comment
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).replace(/^ /, ""));
    }
  }
  if (event === null) return;
  const handler = handlers[event as SseEventName];
  if (handler === undefined) return;

  const dataString = dataLines.join("\n");
  let parsed: unknown;
  try {
    parsed = JSON.parse(dataString);
  } catch (err) {
    onError?.(err);
    return;
  }
  // Handler is keyed by event name; the parsed payload is JSON the backend
  // produced against the typed schema. We trust the backend contract here.
  (handler as (p: unknown) => void)(parsed);
}
