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


# Manhattan island bbox (V2 — widening from MH+UWS to all of Manhattan).
# Range chosen to enclose Inwood Hill in the north and Battery Park in the
# south, with a small western buffer to catch waterfront landmarks and an
# eastern buffer that stops short of Long Island City / Roosevelt Island.
SCOPE_BBOX = ScopeBbox(
    min_lat=40.7000,
    max_lat=40.8800,
    min_lon=-74.0200,
    max_lon=-73.9100,
)

# Schema version for ingestion records. Bumped any time SCOPE_BBOX widens.
SCOPE_VERSION = "v2-manhattan"

# Historical window for Chronicling America and similar archives.
HISTORICAL_START_YEAR = 1850
HISTORICAL_END_YEAR = 1950
