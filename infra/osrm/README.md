# OSRM Routing Backend — OSM Extract Refresh Guide

This directory holds the OSM extract (`extract.osm.pbf`) that backs the
`osrm-prepare` and `osrm` Docker services. The extract covers the V1 corpus
bounding box: **Morningside Heights + Upper West Side, Manhattan**.

## Bounding Box

```
west  = -74.000
south =  40.795
east  = -73.955
north =  40.825
```

This bbox is intentionally slightly larger than the corpus extent so that
walking paths do not dead-end at the border for places near the edge
(e.g., Riverside Park trails, Cathedral close, Columbia campus periphery).

---

## Where to Download the Extract

### Option A — BBBike (recommended for precise bbox)

1. Go to https://extract.bbbike.org
2. Select **PBF** as the output format.
3. Enter the bbox above (the form accepts W/S/E/N in decimal degrees).
4. Provide your e-mail address; BBBike will send a download link within a
   few minutes.
5. Download the `.osm.pbf` file (~3-8 MB for this bbox).

### Option B — Geofabrik (download New York metro, then clip)

1. Download the New York state extract:
   https://download.geofabrik.de/north-america/us/new-york-latest.osm.pbf
   (~1.2 GB — only use this route if you have `osmium-tool` available to clip).
2. Clip to the bbox with osmium:
   ```bash
   osmium extract \
     --bbox -74.000,40.795,-73.955,40.825 \
     new-york-latest.osm.pbf \
     -o extract.osm.pbf
   ```
3. The resulting file is ~3-8 MB.

**Expected file size:** 3-8 MB raw `.osm.pbf`. After OSRM preprocessing the
docker volume grows to roughly 30-60 MB.

---

## Drop the File Here

Place the downloaded file at:

```
infra/osrm/extract.osm.pbf
```

The file is gitignored (see `.gitignore` in this directory). Do not commit
it to the repository — it would bloat the git history and the file changes
over time as OSM contributors update the map.

---

## OSRM Profile: `foot.lua`

We use OSRM's bundled **`foot.lua`** walking profile (shipped inside the
`osrm/osrm-backend:v5.27.1` image at `/opt/foot.lua`). This profile:

- Follows pedestrian ways, footpaths, sidewalks, park trails, and
  crossing nodes.
- Excludes motor roads, trunk/primary roads without footways, and
  private/service ways.
- Is appropriate for a neighbourhood walking tour — it produces street-
  following paths that match what a pedestrian would actually walk.

Do **not** switch to `car.lua` or `bicycle.lua` — they route on different
graph edges and produce nonsensical walking routes.

---

## OSRM Preprocessing Pipeline

OSRM requires a one-time preprocessing step before it can serve routes.
The `osrm-prepare` Docker service runs this pipeline automatically on
first startup. It is idempotent: if the output files already exist on the
`osrm-data` volume it exits 0 immediately.

The three steps are:

### 1. Extract

```bash
osrm-extract -p /opt/foot.lua /data/extract.osm.pbf
```

Reads the raw `.osm.pbf`, applies the walking profile, and writes a set
of intermediate binary files (including `extract.osrm`). Runtime: ~30-90 s
for this bbox. Memory: ~200-400 MB peak.

### 2. Partition

```bash
osrm-partition /data/extract.osrm
```

Partitions the graph for the Multi-Level Dijkstra (MLD) algorithm.
Runtime: ~10-30 s. Output: `extract.osrm.partition` and related files.

### 3. Customize

```bash
osrm-customize /data/extract.osrm
```

Applies the metric (edge weights) to the partition. This is the step that
produces `extract.osrm.cnbg` — the final output the runtime service reads.
Runtime: ~10-20 s.

After all three steps the `osrm-prepare` container exits 0 and the
`osrm` runtime service (which depends on `osrm-prepare` completing
successfully) starts serving routes via the MLD algorithm on port 5000.

### Idempotency Check

The `osrm-prepare` service wraps the pipeline in a bash conditional:

```bash
if [ -f /data/extract.osrm.cnbg ]; then
  echo "OSRM data already prepared — skipping."
  exit 0
fi
```

If `extract.osrm.cnbg` is present on the volume, the entire pipeline is
skipped. To force a re-run (e.g., after refreshing the `.osm.pbf`):

```bash
make nuke   # drops the osrm-data volume along with all other volumes
make up     # rebuilds and re-preprocesses
```

Or, to drop only the OSRM volume:

```bash
docker volume rm palimpsest-osrm-data
make up
```

---

## Refreshing the Extract

OSM data changes over time. To pick up new pedestrian paths, building
footprints, or renamed streets:

1. Re-download the `.osm.pbf` from BBBike or re-clip from Geofabrik.
2. Replace `infra/osrm/extract.osm.pbf` with the new file.
3. Drop and recreate the OSRM volume:
   ```bash
   docker volume rm palimpsest-osrm-data
   make up
   ```
4. `osrm-prepare` will reprocess the new extract (~2 min total) before
   `osrm` starts.

For the V1 demo dataset (Morningside Heights + UWS), a quarterly refresh
cadence is more than sufficient — OSM coverage in this area is excellent
and stable.

---

## Smoke Test

After `make up` completes with a real extract in place:

```bash
curl "http://localhost:5000/route/v1/foot/-73.962,40.804;-73.964,40.811?overview=full&geometries=geojson&steps=true"
```

A successful response looks like:

```json
{
  "code": "Ok",
  "routes": [{ "distance": ..., "duration": ..., "geometry": { "type": "LineString", ... } }]
}
```

See `make extract` for the one-liner to get the BBBike URL and download command.
