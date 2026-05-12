"""Structured place-discovery endpoints.

These routes complement `/agent/ask` when the product needs a concrete list of
selectable places rather than a narrated answer. The first use case is food
discovery: "I'm hungry, show me a few ramen spots near Columbia."
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

router = APIRouter()

_FOOD_AMENITY_RE = (
    "^(restaurant|cafe|fast_food|bar|pub|bakery|ice_cream)$"
)
_FOOD_SHOP_RE = "^(bakery|coffee)$"


class DiscoverFoodBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
    near: list[float] | None = Field(default=None, min_length=2, max_length=2)
    radius_m: int = Field(default=1200, ge=50, le=5000)
    limit: int = Field(default=5, ge=1, le=8)


class FoodCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    name: str
    source_type: str
    source_url: str
    lat: float
    lon: float
    distance_m: float | None = None
    amenity: str | None = None
    cuisine: str | None = None
    why: str
    tags: dict[str, Any] = Field(default_factory=dict)


class DiscoverFoodResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    results: list[FoodCandidate] = Field(default_factory=list)


def _distance_label(distance_m: float | None) -> str | None:
    if distance_m is None:
        return None
    if distance_m >= 1000:
        return f"{distance_m / 1000:.1f} km away"
    return f"{round(distance_m):.0f} m away"


def _why_for_candidate(
    *,
    cuisine: str | None,
    amenity: str | None,
    distance_m: float | None,
) -> str:
    parts: list[str] = []
    if cuisine:
        pretty_cuisine = cuisine.replace(";", ", ")
        parts.append(f"Good match for {pretty_cuisine}")
    elif amenity:
        parts.append(f"Nearby {amenity.replace('_', ' ')}")
    else:
        parts.append("Nearby food stop")

    distance = _distance_label(distance_m)
    if distance is not None:
        parts.append(distance)
    return " - ".join(parts)


@router.post("/food/discover", response_model=DiscoverFoodResponse, tags=["places"])
async def discover_food(request: Request, body: DiscoverFoodBody) -> DiscoverFoodResponse:
    session_factory = request.app.state.db_session_factory
    embedder = request.app.state.embedder

    if embedder is None:
        raise HTTPException(status_code=503, detail="embedder_not_initialized")

    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="empty query")

    query_vec = embedder.encode([query])[0]
    vec_literal = "[" + ",".join(repr(float(x)) for x in query_vec) + "]"

    bind_params: dict[str, Any] = {
        "qvec": vec_literal,
        "limit": body.limit,
        "food_amenity_re": _FOOD_AMENITY_RE,
        "food_shop_re": _FOOD_SHOP_RE,
        "query_lower": query.lower(),
    }
    distance_sql = "NULL"
    spatial_clause = ""
    if body.near is not None:
        lat, lon = float(body.near[0]), float(body.near[1])
        distance_sql = (
            "ST_Distance(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)"
        )
        spatial_clause = (
            "AND ST_DWithin(geom, "
            "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, "
            ":radius_m)"
        )
        bind_params.update({"lat": lat, "lon": lon, "radius_m": body.radius_m})

    sql = text(
        f"""
        SELECT
            doc_id,
            name,
            source_type,
            source_url,
            ST_Y(geom::geometry) AS lat,
            ST_X(geom::geometry) AS lon,
            {distance_sql} AS distance_m,
            properties->'tags'->>'amenity' AS amenity,
            properties->'tags'->>'cuisine' AS cuisine,
            properties->'tags' AS tags,
            (embedding <=> CAST(:qvec AS vector)) AS distance
        FROM places
        WHERE source_type = 'osm'
          AND embedding IS NOT NULL
          AND (
                COALESCE(properties->'tags'->>'amenity', '') ~ :food_amenity_re
                OR COALESCE(properties->'tags'->>'shop', '') ~ :food_shop_re
              )
          {spatial_clause}
        ORDER BY
            CASE
              WHEN LOWER(COALESCE(properties->'tags'->>'cuisine', '')) LIKE ('%%' || :query_lower || '%%')
                THEN 0
              WHEN LOWER(name) LIKE ('%%' || :query_lower || '%%')
                THEN 1
              ELSE 2
            END,
            embedding <=> CAST(:qvec AS vector)
        LIMIT :limit
        """
    )

    async with session_factory() as session:
        result = await session.execute(sql, bind_params)
        candidates = []
        for row in result.mappings():
            distance_m = (
                float(row["distance_m"])
                if row["distance_m"] is not None
                else None
            )
            cuisine = row["cuisine"] if isinstance(row["cuisine"], str) else None
            amenity = row["amenity"] if isinstance(row["amenity"], str) else None
            tags = row["tags"] if isinstance(row["tags"], dict) else {}
            candidates.append(
                FoodCandidate(
                    doc_id=row["doc_id"],
                    name=row["name"],
                    source_type=str(row["source_type"]),
                    source_url=row["source_url"],
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    distance_m=distance_m,
                    amenity=amenity,
                    cuisine=cuisine,
                    why=_why_for_candidate(
                        cuisine=cuisine,
                        amenity=amenity,
                        distance_m=distance_m,
                    ),
                    tags=tags,
                )
            )

    return DiscoverFoodResponse(query=query, results=candidates)
