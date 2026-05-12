"""Dense retriever — cosine ANN over `places.embedding` (pgvector).

Extracted from the previous inline `PostgresRetriever` in
`app.agent.tools.search_places`. Behavior is identical: same SQL, same
score formula, same SearchPlaceHit shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from app.db.models import SourceType

if TYPE_CHECKING:
    from app.agent.tools.search_places import SearchPlaceHit


class DenseRetriever:
    """pgvector top-K with optional ST_DWithin spatial filter."""

    async def search(
        self,
        *,
        session: Any,
        embedder: Any,
        query: str,
        near: tuple[float, float] | None,
        radius_m: int | None,
        limit: int,
    ) -> list[SearchPlaceHit]:
        # Imported lazily to avoid an import cycle: search_places imports
        # DenseRetriever to declare the back-compat PostgresRetriever subclass,
        # and dense.py needs SearchPlaceHit / DEFAULT_RADIUS_M from there. By
        # the time .search() is invoked, both modules are fully loaded.
        from app.agent.tools.search_places import (  # noqa: PLC0415 — see comment
            DEFAULT_RADIUS_M,
            SearchPlaceHit,
        )

        if embedder is None:
            raise RuntimeError("embedder not available in execution context")
        if session is None:
            raise RuntimeError("db session not available in execution context")

        query_vec = embedder.encode([query])[0]
        # pgvector accepts the literal '[a,b,c,...]' string for a vector value.
        vec_literal = "[" + ",".join(repr(float(x)) for x in query_vec) + "]"

        bind_params: dict[str, Any] = {"qvec": vec_literal, "limit": int(limit)}
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
