/**
 * SSE-frame types emitted by `/api/agent/ask`.
 *
 * Mirror of the dataclasses in `apps/api/app/agent/loop.py` and the SSE
 * serializer in `apps/api/app/routes/agent.py`. The five-field Citation
 * contract is locked — see `swap-llm-tiers-and-lock-mvp-decisions`.
 */

export type SourceType = "wikipedia" | "wikidata" | "osm";

export type Citation = {
  doc_id: string;
  source_url: string;
  source_type: SourceType;
  span: string;
  retrieval_turn: number;
};

export type PlannedStop = {
  index: number;
  doc_id: string;
  name: string;
  lat: number;
  lon: number;
  leg_distance_m: number;
};

export type AgentResultPayload = {
  narration: string;
  citations: Citation[];
  verified: boolean;
  warning: string | null;
  turns: number;
  duration_s: number;
};

/** Payload shapes per `event:` name. Keep in sync with `routes/agent.py`. */
export type SsePayloads = {
  turn: { index: number };
  tool_call: { name: string; args: unknown };
  tool_result: { name: string; result: unknown; hits?: number };
  tool_error: { name: string; error: string };
  narration: { delta?: string; text?: string };
  citations: { citations: Citation[] };
  walk: { stops: PlannedStop[] };
  warning: { message: string };
  done: { result: AgentResultPayload | null };
};

export type SseEventName = keyof SsePayloads;
