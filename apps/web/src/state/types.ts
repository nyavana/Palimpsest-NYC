/**
 * SSE-frame types emitted by `/api/agent/ask`.
 *
 * Mirror of the dataclasses in `apps/api/app/agent/loop.py` and the SSE
 * serializer in `apps/api/app/routes/agent.py`. The five-field Citation
 * contract is locked — see `swap-llm-tiers-and-lock-mvp-decisions`.
 *
 * Route geometry uses GeoJSON LineString on the wire (RFC 7946: `[lon, lat]`).
 * No polyline encoding — see `agent-route-planning` design §2.
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
  /**
   * Legacy V1 field — straight-line haversine distance from the previous stop.
   * Superseded by `legs[stop.index - 1].distance_m` when `legs` is present.
   */
  leg_distance_m?: number;
};

/**
 * GeoJSON LineString per RFC 7946.
 *
 * Coordinates are ordered `[longitude, latitude]`, NOT `[lat, lon]`. Anywhere
 * we hand these to the map engine we convert to `{lat, lng}` first.
 */
export type GeoJSONLineString = {
  type: "LineString";
  coordinates: [number, number][];
};

/**
 * One turn-by-turn step inside a leg. The OSRM maneuver is rendered to English
 * by the api's step formatter; per-step `geometry` is optional in V1.
 */
export type RouteStep = {
  instruction: string;
  distance_m: number;
  duration_s: number;
  maneuver_type: string;
  geometry?: GeoJSONLineString;
};

/**
 * One leg connects consecutive stops `from_index → to_index`. The leg from
 * stop `i-1` to stop `i` lives at `legs[i - 1]`; stop 0 has no incoming leg.
 */
export type RouteLeg = {
  from_index: number;
  to_index: number;
  distance_m: number;
  duration_s: number;
  geometry: GeoJSONLineString;
  steps: RouteStep[];
};

/**
 * Walk frame payload. The V1 `stops[]` field is preserved; everything below
 * is additive so older `walk` frames carrying only stops continue to render
 * (the timeline omits the footer total and per-leg disclosures, the map
 * falls back to a straight-line path between markers).
 */
export type PlannedRoute = {
  stops: PlannedStop[];
  geometry?: GeoJSONLineString;
  legs?: RouteLeg[];
  total_distance_m?: number;
  total_duration_s?: number;
  stop_ordering?: "input_order" | "tsp_optimized";
  routing_backend?: "osrm" | "haversine_fallback";
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
  walk: PlannedRoute;
  warning: { message: string };
  done: { result: AgentResultPayload | null };
};

export type SseEventName = keyof SsePayloads;
