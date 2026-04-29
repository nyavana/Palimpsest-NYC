/**
 * `useAgentSession` — React state for one agent question/answer cycle.
 *
 * One reducer turns the SSE event stream into a flat `SessionState` that
 * every visual component can read declaratively. The hook owns the
 * EventSource lifecycle: opening on `ask()`, closing on `done`, on error,
 * and on unmount.
 *
 * See `docs/frontend/ui-design-brief.md` §5 for the role of each field.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";

import type { SseSession } from "./sse";
import { openAgentStream } from "./sse";
import type {
  AgentResultPayload,
  Citation,
  PlannedStop,
  SsePayloads,
} from "./types";

export type SessionStatus = "idle" | "asking" | "streaming" | "done" | "error";

export type SessionState = {
  status: SessionStatus;
  question: string | null;
  turn: number;
  lastToolCall: { name: string } | null;
  narration: string;
  citations: Citation[];
  walk: PlannedStop[];
  warnings: string[];
  result: AgentResultPayload | null;
};

const initialState: SessionState = {
  status: "idle",
  question: null,
  turn: 0,
  lastToolCall: null,
  narration: "",
  citations: [],
  walk: [],
  warnings: [],
  result: null,
};

type Action =
  | { type: "ask"; question: string }
  | { type: "turn"; payload: SsePayloads["turn"] }
  | { type: "tool_call"; payload: SsePayloads["tool_call"] }
  | { type: "narration"; payload: SsePayloads["narration"] }
  | { type: "citations"; payload: SsePayloads["citations"] }
  | { type: "walk"; payload: SsePayloads["walk"] }
  | { type: "warning"; payload: SsePayloads["warning"] }
  | { type: "done"; payload: SsePayloads["done"] }
  | { type: "error"; message: string }
  | { type: "cancel" }
  | { type: "reset" };

function reducer(state: SessionState, action: Action): SessionState {
  switch (action.type) {
    case "ask":
      return {
        ...initialState,
        status: "asking",
        question: action.question,
      };
    case "turn":
      return {
        ...state,
        status: "streaming",
        turn: action.payload.index,
      };
    case "tool_call":
      return {
        ...state,
        status: "streaming",
        lastToolCall: { name: action.payload.name },
      };
    case "narration": {
      // The backend currently emits narration as the terminal terminal-result
      // payload (`text` carries the full string). Support both `delta` (token
      // streaming if/when the loop is rewired for it) and `text` so the hook
      // works under either shape.
      const next =
        action.payload.delta !== undefined
          ? state.narration + action.payload.delta
          : (action.payload.text ?? state.narration);
      return { ...state, status: "streaming", narration: next };
    }
    case "citations":
      return {
        ...state,
        status: "streaming",
        citations: action.payload.citations,
      };
    case "walk":
      return {
        ...state,
        status: "streaming",
        walk: action.payload.stops,
      };
    case "warning":
      return {
        ...state,
        warnings: [...state.warnings, action.payload.message],
      };
    case "done": {
      const result = action.payload.result;
      // The terminal `done` carries the canonical result. Fold its narration
      // and citations in, since per-event narration may not have streamed.
      if (result) {
        return {
          ...state,
          status: "done",
          narration: result.narration || state.narration,
          citations: result.citations.length > 0 ? result.citations : state.citations,
          warnings: result.warning ? [...state.warnings, result.warning] : state.warnings,
          result,
        };
      }
      return { ...state, status: "done", result: null };
    }
    case "error":
      return {
        ...state,
        status: "error",
        warnings: [...state.warnings, action.message],
      };
    case "cancel":
      // The user closed the connection mid-stream. Whatever we already
      // received (turns, narration, citations, walk) stays on screen so
      // they can read it; the composer just unsticks.
      return state.status === "asking" || state.status === "streaming"
        ? { ...state, status: "done" }
        : state;
    case "reset":
      return initialState;
    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
}

export type UseAgentSession = {
  state: SessionState;
  ask: (question: string) => void;
  cancel: () => void;
  reset: () => void;
};

export function useAgentSession(baseUrl?: string): UseAgentSession {
  const [state, dispatch] = useReducer(reducer, initialState);
  const sessionRef = useRef<SseSession | null>(null);
  const doneRef = useRef(false);

  const cancel = useCallback(() => {
    sessionRef.current?.close();
    sessionRef.current = null;
    dispatch({ type: "cancel" });
  }, []);

  const ask = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (trimmed.length === 0) return;
      cancel();
      doneRef.current = false;
      dispatch({ type: "ask", question: trimmed });

      sessionRef.current = openAgentStream(
        trimmed,
        {
          turn: (p) => dispatch({ type: "turn", payload: p }),
          tool_call: (p) => dispatch({ type: "tool_call", payload: p }),
          narration: (p) => dispatch({ type: "narration", payload: p }),
          citations: (p) => dispatch({ type: "citations", payload: p }),
          walk: (p) => dispatch({ type: "walk", payload: p }),
          warning: (p) => dispatch({ type: "warning", payload: p }),
          done: (p) => {
            doneRef.current = true;
            dispatch({ type: "done", payload: p });
            sessionRef.current?.close();
            sessionRef.current = null;
          },
        },
        {
          baseUrl,
          onError: () => {
            // EventSource fires `error` when the server closes the stream.
            // If we already saw `done`, that's a normal close — drop it.
            if (doneRef.current) return;
            dispatch({ type: "error", message: "Connection lost." });
            sessionRef.current?.close();
            sessionRef.current = null;
          },
        },
      );
    },
    [baseUrl, cancel],
  );

  const reset = useCallback(() => {
    cancel();
    dispatch({ type: "reset" });
  }, [cancel]);

  useEffect(() => () => cancel(), [cancel]);

  return { state, ask, cancel, reset };
}
