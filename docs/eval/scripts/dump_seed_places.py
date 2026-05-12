"""Dump a TSV of corpus places suitable for the question synthesizer.

Reads from postgres directly via the same async engine the API uses.
Neighborhood is estimated from coordinate buckets — this is rough but
fine for question synthesis (the human curator can correct anything weird).
"""

from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps/api"))

from app.config import get_settings
from app.db.engine import build_engine, build_session_factory
from sqlalchemy import text

# Lon/lat -> rough neighborhood. Rectangles overlap; first match wins.
_NEIGHBORHOOD_BOXES = [
    # name, min_lat, max_lat, min_lon, max_lon
    ("Inwood",              40.860, 40.880, -73.930, -73.910),
    ("Washington Heights",  40.830, 40.860, -73.945, -73.915),
    ("Harlem",              40.795, 40.830, -73.960, -73.925),
    ("Morningside Heights", 40.800, 40.815, -73.970, -73.955),
    ("Upper West Side",     40.768, 40.800, -73.990, -73.965),
    ("Upper East Side",     40.768, 40.800, -73.965, -73.940),
    ("Midtown",             40.745, 40.770, -73.995, -73.965),
    ("Hell's Kitchen",      40.755, 40.775, -74.005, -73.985),
    ("Chelsea",             40.735, 40.755, -74.010, -73.985),
    ("Flatiron District",   40.735, 40.750, -73.995, -73.980),
    ("Greenwich Village",   40.725, 40.740, -74.010, -73.990),
    ("SoHo",                40.715, 40.730, -74.010, -73.990),
    ("Tribeca",             40.710, 40.725, -74.020, -74.000),
    ("Lower East Side",     40.710, 40.725, -73.995, -73.975),
    ("Financial District",  40.700, 40.715, -74.020, -73.995),
]


def _neighborhood(lat: float, lon: float) -> str:
    for name, min_lat, max_lat, min_lon, max_lon in _NEIGHBORHOOD_BOXES:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            return name
    return "unknown"


async def main(out_path: Path) -> None:
    settings = get_settings()
    engine = build_engine(settings.postgres)
    factory = build_session_factory(engine)
    async with factory() as session:
        result = await session.execute(text("""
            SELECT name, source_type::text AS source_type,
                   ST_Y(geom::geometry) AS lat,
                   ST_X(geom::geometry) AS lon
            FROM places
            WHERE name IS NOT NULL AND length(name) > 3
            ORDER BY random()
            LIMIT 400
        """))
        rows: list[dict[str, Any]] = []
        for row in result.mappings():
            rows.append({
                "name": row["name"],
                "neighborhood": _neighborhood(float(row["lat"]), float(row["lon"])),
                "source_type": row["source_type"],
            })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["name", "neighborhood", "source_type"], delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {len(rows)} seed places → {out_path}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(Path("docs/eval/questions/manhattan-100/seed_places.tsv")))
