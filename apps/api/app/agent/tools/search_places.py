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

from sqlalchemy import bindparam

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


# Imported here (after SearchPlaceHit + DEFAULT_RADIUS_M are defined) because
# `app.retrieval.dense` imports those names back from this module. Module-level
# import order:
#   1. search_places defines SearchPlaceHit, DEFAULT_RADIUS_M
#   2. search_places imports DenseRetriever from app.retrieval.dense
#   3. dense.py imports SearchPlaceHit, DEFAULT_RADIUS_M from search_places (now present)
#   4. PostgresRetriever is declared as a thin alias for back-compat.
from app.retrieval.dense import DenseRetriever  # noqa: E402


class PostgresRetriever(DenseRetriever):
    """Back-compat alias for the dense pgvector retriever.

    Kept so existing import paths (`/internal/retrieve.py`, tests) still work
    while new code targets `app.retrieval.dense.DenseRetriever` directly.
    Behavior — SQL, score formula, SearchPlaceHit shape — is unchanged.
    """


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

    def __init__(
        self,
        *,
        retriever: _RetrieverProtocol | None = None,
        mode: str = "dense",
        reranker: Any = None,
    ) -> None:
        if retriever is not None:
            self._retriever = retriever
        else:
            from app.retrieval.factory import build_retriever
            self._retriever = build_retriever(mode=mode, reranker=reranker)

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
