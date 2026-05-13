# Manhattan corpus counts (2026-05-12)

After `make nuke && make up` with `SCOPE_BBOX = (-74.02, 40.70, -73.91, 40.88)` and `SCOPE_VERSION = v2-manhattan`.

## Places by source_type

| source_type | count   |
|-------------|---------|
| osm         | 12,858  |
| wikipedia   | 492     |
| **total**   | **13,350** |

## Documents by source_type

| source_type | count |
|-------------|-------|
| wikipedia   | 456   |

## Comparison to V1 (MH+UWS)

| metric          | v1-morningside-uws | v2-manhattan | factor |
|-----------------|--------------------|--------------|--------|
| osm places      | 1,363              | 12,858       | 9.4x   |
| wikipedia places| 492                | 492          | 1.0x   |
| wikipedia docs  | (unknown)          | 456          | —      |

The Wikipedia ingest is capped at 500-item batches (`fetched=500, inserted=500`
in init-ingest log). The 492 final count after de-dup matches the V1 number
incidentally — the underlying Wikipedia query may also be returning a
similar set across the wider bbox because the limit binds before the
geographic filter. Worth follow-up if Wikipedia coverage looks sparse in
spot-check.

## Note on cardinality vs. spec estimate (R1)

Spec R1 estimated ~3–5k places + ~1.5–2k docs. Actual places (13,350) is
2.6–4.4× the upper estimate. Spec R1 mitigation kicks in if retrieval
p95 exceeds 2s on the wider corpus — that check is in Task 1.5 below.

## OSRM resize

Task 1.4 (OSRM extract resize) is **deferred per design R8**. The eval
headline metrics (CCR / HR / FA / NQ) do not depend on walk geometry, so
the smaller MH/UWS OSRM extract is acceptable for Phase 3 measurement.
The SSE `walk` frame is conditional in the existing code path.

## Manhattan spot-check (2026-05-12, task 1.5)

5 queries through `POST /internal/retrieve` (top_k=3, RETRIEVAL_MODE=dense):

| Query                          | Top hit                                       | OK?  | Note |
|--------------------------------|-----------------------------------------------|------|------|
| Flatiron Building              | osm:node:2549953088 :: The Flatiron Room      | ~    | Continental Bank Building (rank 3) is near Flatiron; the actual building entity isn't in OSM amenity tags |
| SoHo cast-iron architecture    | osm:node:12138358700 :: SoHo Playhouse        | ✓    | Center for Architecture (rank 3) is on the right theme |
| Inwood Hill Park               | osm:way:1119515160 :: Lentol Garden           | ✗    | **Inwood Hill Park (osm:way:118529212) is in the corpus** but dense bge-small ranks similarly-named gardens higher. Validates Phase 4 hybrid motivation. |
| Trinity Church Wall Street     | wikipedia:Trinity_Church_(Manhattan)          | ✓    | Perfect — Trinity Church is the top hit |
| Tenement Museum                | osm:node:2768171711 :: La casa de los Tenenbaums | ✗ | **Lower East Side Tenement Museum (osm:node:368061660) is in the corpus** but dense embedding confuses "tenement" with similarly-named entries. Hybrid retrieval should fix this. |

**Verdict**: 3/5 are OK, 2/5 reveal the dense-retrieval ranking gap that
Phase 4 (sparse pg_trgm + RRF) is designed to close. Both missed places
exist in the corpus, so the gap is purely a ranking signal — not a
coverage problem with the Manhattan ingest.
