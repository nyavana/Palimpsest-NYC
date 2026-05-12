# Food Discovery README

This document explains the new "find food, choose a place, then continue the walk" feature that now sits on top of Palimpsest's existing multi-turn agent and map UI.

## What Was Added

The app can now handle a second interaction mode besides archive-grounded narration:

1. The user asks for food or drink nearby.
2. The frontend requests a structured list of candidates from the backend.
3. The map displays those candidates as interactive markers.
4. The user picks one.
5. The app turns that choice into a follow-up agent turn and asks the existing routing flow to continue from there.

This keeps the locked `/agent/ask` terminal contract unchanged while still supporting a two-step "decide, then route" workflow.

## User Experience

Typical flow:

1. User asks:

```text
I want coffee near Columbia
```

2. The right pane renders a `Food Picks` section.
3. The map automatically flies to the first returned candidate and opens its popup.
4. Each candidate supports:
   - `Show on map`
   - `Choose this place`
5. Choosing a place triggers a follow-up prompt to the agent, which then uses the existing search + route planning flow.

If the user already has an active walk, choosing a food candidate asks the agent to continue from the current route instead of starting fresh.

## Backend Changes

### New endpoint

Structured discovery now lives at:

```text
POST /food/discover
```

Implemented in:

- [apps/api/app/routes/places.py](/Users/curtin/python/6895/Palimpsest-NYC/apps/api/app/routes/places.py)

Request shape:

```json
{
  "query": "coffee",
  "near": [40.8075, -73.9626],
  "radius_m": 1200,
  "limit": 5
}
```

Response shape:

```json
{
  "query": "coffee",
  "results": [
    {
      "doc_id": "osm:node:3843956495",
      "name": "Nous Espresso",
      "source_type": "osm",
      "source_url": "https://www.openstreetmap.org/node/3843956495",
      "lat": 40.807525,
      "lon": -73.9608785,
      "distance_m": 145.2,
      "amenity": "cafe",
      "cuisine": "coffee_shop",
      "why": "Good match for coffee_shop - 145 m away",
      "tags": {}
    }
  ]
}
```

### OSM ingestion expansion

The OSM ingestor now includes food-related places:

- `restaurant`
- `cafe`
- `fast_food`
- `bar`
- `pub`
- `bakery`
- `ice_cream`
- `shop=bakery`
- `shop=coffee`

Implemented in:

- [apps/api/app/ingest/osm.py](/Users/curtin/python/6895/Palimpsest-NYC/apps/api/app/ingest/osm.py)

The embed text for OSM places now also includes food-relevant tags such as:

- `shop`
- `cuisine`
- `outdoor_seating`
- `takeaway`
- `opening_hours`

### Raw-cache fix

OSM raw responses were previously cached only by bbox. That meant query expansions could silently reuse stale Overpass responses.

The cache key now includes a digest of the actual Overpass query text, so ingestion changes correctly produce fresh cached payloads.

## Frontend Changes

### New food discovery state

Food discovery lives outside the SSE reducer so it can stay structured and selectable.

Implemented in:

- [apps/web/src/state/useFoodDiscovery.ts](/Users/curtin/python/6895/Palimpsest-NYC/apps/web/src/state/useFoodDiscovery.ts)

Responsibilities:

- detect food-intent prompts
- call `/food/discover`
- store candidate results
- clear candidates when returning to regular agent flow

### New UI components

- [apps/web/src/components/FoodCandidateList.tsx](/Users/curtin/python/6895/Palimpsest-NYC/apps/web/src/components/FoodCandidateList.tsx)
- [apps/web/src/components/FoodCandidateCard.tsx](/Users/curtin/python/6895/Palimpsest-NYC/apps/web/src/components/FoodCandidateCard.tsx)

These render:

- candidate name
- amenity / cuisine / distance
- short recommendation reason
- map action
- choose action

### Chat integration

Implemented in:

- [apps/web/src/components/ChatPane.tsx](/Users/curtin/python/6895/Palimpsest-NYC/apps/web/src/components/ChatPane.tsx)

Behavior:

- food-style prompts go to discovery first
- normal prompts still go to `/agent/ask`
- choosing a candidate generates a follow-up prompt for the existing multi-turn session

### Map integration

Implemented in:

- [apps/web/src/components/MapView.tsx](/Users/curtin/python/6895/Palimpsest-NYC/apps/web/src/components/MapView.tsx)
- [apps/web/src/components/MarkerInfoCard.tsx](/Users/curtin/python/6895/Palimpsest-NYC/apps/web/src/components/MarkerInfoCard.tsx)

Behavior:

- food candidates render as a separate marker layer
- results auto-focus the first candidate
- candidate markers use the same shared focus model as citations and walk stops
- candidate popups show place-specific summary text even when there is no citation card yet

## Why This Design

The existing agent loop has a strict terminal contract:

```json
{ "narration": "...", "citations": [...] }
```

That contract is intentionally narrow and should stay narrow.

Food discovery is different from narration:

- it returns a set of options
- the user needs to choose one
- it is better represented as structured data than as prose

So the new feature was designed as:

- structured discovery first
- agent continuation second

That keeps the current agent architecture intact and makes the new workflow easier to test.

## How To Test

Good prompts:

```text
I want coffee near Columbia
Find me a cheap lunch near Columbia
Find me a cafe after that
```

Expected behavior:

1. `Food Picks` appears in the chat pane.
2. The map flies to the first candidate automatically.
3. The first candidate popup opens on the map.
4. Clicking `Show on map` moves focus between candidates.
5. Clicking `Choose this place` starts a follow-up agent turn.
6. If routing succeeds, the normal walk UI appears afterward.

## Known Limits

- Result quality depends on OSM tags, especially `cuisine`.
- Broad categories like `coffee` and `cafe` work better than very specific cuisine queries.
- This is still OSM-backed place discovery, not a live business directory.
- Ratings, price bands, and real-time open/closed status are not part of V1.

## Local Data Note

If the food discovery UI is present but results are empty, re-run OSM ingestion after pulling the latest code:

```bash
docker compose exec api python -m app.ingest.cli osm run
```

This is required because the new feature depends on food places being present in the local `places` table.
