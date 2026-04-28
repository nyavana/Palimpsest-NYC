"""`search_places` — the only LLM-callable tool in V1.

Hybrid retrieval over the `places` corpus:
  - cosine ANN on `places.embedding` (pgvector ivfflat)
  - optional spatial filter via `ST_DWithin(geom, point, radius_m)`
  - returns top-K with citation-shape provenance

The hit shape carries `doc_id`, `source_url`, `source_type` exactly as the
locked citation contract expects, so the LLM can copy them straight into
its narration `citations[]` array with no transformation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import bindparam, text

from app.agent.tools.base import Tool, ToolExecutionContext
from app.db.models import SourceType

DEFAULT_LIMIT = 8
DEFAULT_RADIUS_M = 800

# JSON Schema (also used by the LLM tools= parameter and by jsonschema validation)
_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "minLength": 1,
            "description": "Free-form natural language search string.",
        },
        "near": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
            "description": "[lat, lon] anchor for proximity-biased results.",
        },
        "radius_m": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5000,
            "default": DEFAULT_RADIUS_M,
            "description": "Spatial filter radius in meters. Ignored without `near`.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 25,
            "default": DEFAULT_LIMIT,
            "description": "Max number of results.",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}


# ── Hit shape ───────────────────────────────────────────────────────


@dataclass(slots=True)
class SearchPlaceHit:
    doc_id: str
    name: str
    source_type: SourceType
    source_url: str
    lat: float
    lon: float
    distance_m: float | None  # None when `near` not provided
    score: float  # cosine similarity in [0, 1]; higher = better

    def as_llm_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "name": self.name,
            "source_type": self.source_type.value,
            "source_url": self.source_url,
            "lat": self.lat,
            "lon": self.lon,
            "distance_m": self.distance_m,
            "score": round(self.score, 4),
        }


# ── Retriever protocol (the postgres path lives in the concrete class below) ──


class _RetrieverProtocol(Protocol):
    async def search(
        self,
        *,
        session: Any,
        embedder: Any,
        query: str,
        near: tuple[float, float] | None,
        radius_m: int | None,
        limit: int,
    ) -> list[SearchPlaceHit]: ...


class PostgresRetriever:
    """Hybrid retriever — cosine ANN over `places.embedding` + ST_DWithin."""

    async def search(  # noqa: PLR0913 — args mirror the tool's surface
        self,
        *,
        session: Any,
        embedder: Any,
        query: str,
        near: tuple[float, float] | None,
        radius_m: int | None,
        limit: int,
    ) -> list[SearchPlaceHit]:
        if embedder is None:
            raise RuntimeError("embedder not available in execution context")
        if session is None:
            raise RuntimeError("db session not available in execution context")

        query_vec = embedder.encode([query])[0]
        # pgvector accepts the literal '[a,b,c,...]' string for a vector value.
        vec_literal = "[" + ",".join(repr(float(x)) for x in query_vec) + "]"

        bind_params: dict[str, Any] = {
            "qvec": vec_literal,
            "limit": int(limit),
        }
        spatial_clause = ""
        if near is not None:
            lat, lon = near
            spatial_clause = (
                "AND ST_DWithin(geom, "
                "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, "
                ":radius_m) "
            )
            bind_params["lat"] = float(lat)
            bind_params["lon"] = float(lon)
            bind_params["radius_m"] = int(radius_m or DEFAULT_RADIUS_M)

        # cosine_distance = embedding <=> qvec (range 0..2; smaller = more similar)
        # similarity score in [0, 1] = 1 - distance/2 (clamped)
        sql = text(
            f"""
            SELECT
                doc_id,
                name,
                source_type,
                source_url,
                ST_Y(geom::geometry) AS lat,
                ST_X(geom::geometry) AS lon,
                {(
                    "ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
                    if near is not None
                    else "NULL"
                )} AS distance_m,
                (embedding <=> CAST(:qvec AS vector)) AS distance
            FROM places
            WHERE embedding IS NOT NULL
              {spatial_clause}
            ORDER BY embedding <=> CAST(:qvec AS vector)
            LIMIT :limit
            """
        )
        result = await session.execute(sql, bind_params)
        hits: list[SearchPlaceHit] = []
        for row in result.mappings():
            distance = float(row["distance"])
            score = max(0.0, min(1.0, 1.0 - distance / 2.0))
            hits.append(
                SearchPlaceHit(
                    doc_id=row["doc_id"],
                    name=row["name"],
                    source_type=SourceType(row["source_type"]),
                    source_url=row["source_url"],
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    distance_m=(
                        float(row["distance_m"])
                        if row["distance_m"] is not None
                        else None
                    ),
                    score=score,
                )
            )
        return hits


# ── Tool ────────────────────────────────────────────────────────────


class SearchPlacesTool(Tool):
    """Search the Palimpsest places corpus by query + optional location."""

    name = "search_places"
    description = (
        "Search the Palimpsest NYC places corpus for landmarks, churches, "
        "parks, museums, and other points of interest in Morningside Heights "
        "and the Upper West Side. Returns up to `limit` hits with `doc_id`, "
        "`source_url`, and `source_type` so cited results can be referenced "
        "verbatim in the final narration's `citations[]` array. Optional "
        "`near=[lat,lon]` and `radius_m` constrain results to a walking radius."
    )
    parameters = _PARAMETERS

    def __init__(self, *, retriever: _RetrieverProtocol | None = None) -> None:
        self._retriever = retriever or PostgresRetriever()

    async def execute(
        self, args: dict[str, Any], context: ToolExecutionContext
    ) -> dict[str, Any]:
        near_raw = args.get("near")
        near: tuple[float, float] | None = None
        if near_raw is not None:
            near = (float(near_raw[0]), float(near_raw[1]))

        hits = await self._retriever.search(
            session=context.session,
            embedder=context.embedder,
            query=args["query"],
            near=near,
            radius_m=args.get("radius_m"),
            limit=int(args.get("limit", DEFAULT_LIMIT)),
        )
        return {"results": [h.as_llm_dict() for h in hits]}


_ = bindparam  # silence unused-import linter without removing the symbol
