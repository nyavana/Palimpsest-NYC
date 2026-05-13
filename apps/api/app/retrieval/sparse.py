"""Sparse retriever — pg_trgm similarity over `places.name`.

Returns SearchPlaceHit objects whose `score` is the trigram similarity
(in [0, 1] where 1 == identical). The score is therefore directly comparable
to DenseRetriever's score, but the underlying signal is lexical — useful for
proper names and rare tokens that embeddings undershoot.

We do NOT JOIN documents.body in V1 because place names are short and the
N*M document scan would dominate latency on the Manhattan-scale corpus.
Bring documents.body in via a follow-up if name-only sparse undershoots.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.agent.tools.search_places import DEFAULT_RADIUS_M, SearchPlaceHit
from app.db.models import SourceType


class SparseRetriever:
    """pg_trgm similarity over places.name with optional spatial filter."""

    async def search(
        self,
        *,
        session: Any,
        embedder: Any,  # unused; protocol compat
        query: str,
        near: tuple[float, float] | None,
        radius_m: int | None,
        limit: int,
    ) -> list[SearchPlaceHit]:
        if session is None:
            raise RuntimeError("db session not available")

        bind: dict[str, Any] = {"q": query, "limit": int(limit)}
        spatial_clause = ""
        if near is not None:
            lat, lon = near
            spatial_clause = (
                "AND ST_DWithin(geom, "
                "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, "
                ":radius_m) "
            )
            bind["lat"] = float(lat)
            bind["lon"] = float(lon)
            bind["radius_m"] = int(radius_m or DEFAULT_RADIUS_M)

        distance_expr = (
            "ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
            if near is not None
            else "NULL"
        )

        sql = text(
            f"""
            SELECT
                doc_id, name, source_type, source_url,
                ST_Y(geom::geometry) AS lat,
                ST_X(geom::geometry) AS lon,
                {distance_expr} AS distance_m,
                similarity(name, :q) AS similarity
            FROM places
            WHERE name % :q
              {spatial_clause}
            ORDER BY similarity(name, :q) DESC
            LIMIT :limit
            """
        )
        result = await session.execute(sql, bind)
        hits: list[SearchPlaceHit] = []
        for row in result.mappings():
            score = float(row["similarity"])
            score = max(0.0, min(1.0, score))
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
