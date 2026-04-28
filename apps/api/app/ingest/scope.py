"""Geographic and temporal scope constants for v1 ingestion.

Widening the bounding box or date range requires an explicit OpenSpec change
so all ingestors agree on the same filter.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScopeBbox:
    """Axis-aligned latitude/longitude bounding box."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def contains(self, lat: float, lon: float) -> bool:
        return (
            self.min_lat <= lat <= self.max_lat
            and self.min_lon <= lon <= self.max_lon
        )

    def as_tuple(self) -> tuple[float, float, float, float]:
        """Return (west, south, east, north) — the OSM Overpass order."""
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)


# Morningside Heights + Upper West Side + adjacent Riverside / Central Park slivers.
# Roughly: south of W 125th, north of W 59th, west of Central Park West (~-73.97),
# east of Hudson (~-74.00). Slightly generous to catch edge places.
SCOPE_BBOX = ScopeBbox(
    min_lat=40.7680,
    max_lat=40.8150,
    min_lon=-74.0050,
    max_lon=-73.9550,
)

# Historical window for Chronicling America and similar archives.
HISTORICAL_START_YEAR = 1850
HISTORICAL_END_YEAR = 1950
