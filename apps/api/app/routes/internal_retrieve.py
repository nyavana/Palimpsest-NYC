"""`/internal/retrieve` + `/internal/documents/by_ids` — one-shot retrieval
and grader-side body_excerpt enrichment over the corpus.

`/internal/retrieve` is used by the naive-RAG baseline. It matches whatever
retrieval pipeline the API container is currently configured for via
`RETRIEVAL_MODE` (dense | hybrid | hybrid_reranked), because the lifespan in
`app/main.py` binds `app.state.retriever_for_internal = build_retriever(...)`
to the same retriever instance the agent uses. This keeps Phase 3 (dense
across all systems) and Phase 4 (hybrid across all systems) apples-to-apples.

`/internal/documents/by_ids` is used by the palimpsest baseline AFTER the SSE
stream finishes — it batch-fetches body excerpts for the doc_ids the agent's
tools surfaced, so the grader has document text against which to verify spans.
The agent itself never calls this endpoint; it would be a leak of grader-only
context into the loop.

Mounted on the same app as the rest of the API. Not behind the `/agent/`
namespace because there is no agent involved.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text

from app.agent.tools.search_places import DEFAULT_LIMIT, PostgresRetriever

router = APIRouter(prefix="/internal", tags=["internal"])

# Bodies are stored full-length; we cap the excerpt so the judge prompt stays
# in a sensible token budget. ~1200 chars ≈ 250–300 tokens per doc, × 8 docs
# ≈ 2k judge-prompt tokens for the document context.
BODY_EXCERPT_MAX_CHARS = 1200


class RetrieveRequest(BaseModel):
    query: Annotated[str, Field(min_length=1)]
    top_k: int = DEFAULT_LIMIT


class RetrieveResult(BaseModel):
    doc_id: str
    name: str
    source_type: str
    source_url: str
    lat: float
    lon: float
    score: float
    # First ~1200 chars of the joined `documents.body`. Used by both naive_rag
    # (LLM context) and the grader (span-support evidence). Empty string when
    # no documents row exists for this doc_id (OSM-only places without a
    # corresponding documents entry).
    body_excerpt: str = ""


class RetrieveResponse(BaseModel):
    results: list[RetrieveResult]


class DocsByIdsRequest(BaseModel):
    doc_ids: Annotated[list[str], Field(min_length=1, max_length=64)]


class DocResult(BaseModel):
    doc_id: str
    body_excerpt: str  # "" when no matching documents row


class DocsByIdsResponse(BaseModel):
    documents: list[DocResult]


class _DefaultBodyFetcher:
    """Default body excerpt source — direct documents.body lookup.

    Tests can swap a fake onto `app.state.body_excerpt_fetcher` and skip the DB.
    """
    async def fetch(self, session, doc_ids: list[str], *, max_chars: int) -> dict[str, str]:
        if not doc_ids:
            return {}
        stmt = (
            text(
                "SELECT doc_id, LEFT(body, :n) AS excerpt FROM documents "
                "WHERE doc_id = ANY(:ids)"
            )
            .bindparams(bindparam("ids", expanding=True))
        )
        result = await session.execute(stmt, {"n": max_chars, "ids": doc_ids})
        return {row.doc_id: (row.excerpt or "") for row in result}


def _body_fetcher(request: Request):
    return getattr(request.app.state, "body_excerpt_fetcher", None) or _DefaultBodyFetcher()


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(req: RetrieveRequest, request: Request) -> RetrieveResponse:
    embedder = request.app.state.embedder
    if embedder is None:
        raise HTTPException(503, detail="embedder not loaded")
    session_factory = request.app.state.db_session_factory
    # The lifespan binds `retriever_for_internal` to the active retriever; the
    # PostgresRetriever() fallback is for early-Phase-0 only, before the
    # factory exists.
    retriever = getattr(
        request.app.state, "retriever_for_internal", None
    ) or PostgresRetriever()
    fetcher = _body_fetcher(request)

    async with session_factory() as session:
        hits = await retriever.search(
            session=session,
            embedder=embedder,
            query=req.query,
            near=None,
            radius_m=None,
            limit=int(req.top_k),
        )
        bodies = await fetcher.fetch(
            session, [h.doc_id for h in hits], max_chars=BODY_EXCERPT_MAX_CHARS
        )

    return RetrieveResponse(
        results=[
            RetrieveResult(
                doc_id=h.doc_id,
                name=h.name,
                source_type=h.source_type.value,
                source_url=h.source_url,
                lat=h.lat,
                lon=h.lon,
                score=h.score,
                body_excerpt=bodies.get(h.doc_id, ""),
            )
            for h in hits
        ]
    )


@router.post("/documents/by_ids", response_model=DocsByIdsResponse)
async def documents_by_ids(req: DocsByIdsRequest, request: Request) -> DocsByIdsResponse:
    session_factory = request.app.state.db_session_factory
    fetcher = _body_fetcher(request)

    async with session_factory() as session:
        bodies = await fetcher.fetch(
            session, req.doc_ids, max_chars=BODY_EXCERPT_MAX_CHARS
        )

    # Preserve input order so callers can correlate by index.
    return DocsByIdsResponse(
        documents=[DocResult(doc_id=d, body_excerpt=bodies.get(d, "")) for d in req.doc_ids]
    )
