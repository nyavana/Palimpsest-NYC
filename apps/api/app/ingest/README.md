# Data ingestion — Palimpsest NYC

Every source listed here is free or public-domain. Adding a new source requires
documenting its license AND citation format below, and is gated on an OpenSpec
change update.

## Tiers

```
raw/     ← dev-box only, not committed, not on VPS
bronze/  ← parquet on dev-box, partitioned by {source, year}
silver/  ← Postgres on dev-box for local dev
gold/    ← Postgres on VPS, dump/restored from silver via pg_dump
```

Raw archives NEVER leave the dev box. The RackNerd VPS has 45 GB of disk and
cannot host the full Chronicling America zips.

## v1 scope

Manhattan, roughly Morningside Heights + Upper West Side. See
`apps/api/app/ingest/scope.py` for the exact bounding box. Widening the scope
requires an explicit OpenSpec change.

## Approved sources

| Source | License | Citation format | Notes |
|---|---|---|---|
| Wikipedia (English) | CC BY-SA 4.0 | `wikipedia:<page_id>:<rev_id>` | Dump download or REST API |
| Wikidata | CC0 1.0 | `wikidata:<qid>` | Structured entities with coordinates |
| Chronicling America | Public domain | `chronicling-america:<lccn>:<issue>:<page>` | OCR'd NY papers 1850–1950 |
| NYPL Digital Collections | CC / public domain (filter) | `nypl:<item_uuid>` | Historic photos, filter by rightsstatements.org |
| OpenStreetMap (Overpass) | ODbL 1.0 | `osm:<element>:<id>` | POIs, buildings, amenities |
| NYC Open Data (Socrata) | CC0 / varies | `nycopendata:<dataset_id>:<row_id>` | Events, inspections, 311 |
| MTA GTFS-RT | Open | `mta:<feed>:<timestamp>` | Real-time subway positions |
| NOAA Weather API | Public domain | `noaa:<station>:<obs_time>` | Forecasts + observations |
| Wikimedia Commons | Free (filter) | `commons:<file_name>` | Photos (historical and current) |

## Cost policy

Bulk NLP work (OCR cleanup, relevance filters, entity extraction) SHALL
route through the LLM router with `complexity="simple"` so it lands on the
local Gemma-4 backend and costs $0 in API fees.

## Idempotency

Every ingestor MUST support repeated runs without creating duplicates.
Natural-key upserts use the source-specific ID (Wikipedia page_id+rev_id,
Chronicling America LCCN+issue+page, etc.).
