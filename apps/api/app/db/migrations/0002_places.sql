-- 0002_places.sql — V1 base tables: places + documents.
-- Both carry full provenance + a 384-dim embedding column for pgvector
-- semantic retrieval (BAAI/bge-small-en-v1.5; locked in
-- swap-llm-tiers-and-lock-mvp-decisions). Embedding dim MUST track the
-- EMBEDDING_DIM env var; changing the model requires a new migration that
-- drops and recreates the column at the new dim.

-- ── source_type enum (V1 = wikipedia | wikidata | osm) ────────────────
-- Adding a value in v2 requires a new migration:
--   ALTER TYPE source_type_enum ADD VALUE 'chronicling-america';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'source_type_enum') THEN
        CREATE TYPE source_type_enum AS ENUM ('wikipedia', 'wikidata', 'osm');
    END IF;
END$$;

-- ── places ────────────────────────────────────────────────────────────
-- A point of interest in NYC. Geometry stored as geography(Point, 4326)
-- so PostGIS distance functions return meters by default.
CREATE TABLE IF NOT EXISTS places (
    id                 BIGSERIAL PRIMARY KEY,
    doc_id             TEXT NOT NULL UNIQUE,
    name               TEXT NOT NULL,
    geom               geography(Point, 4326) NOT NULL,
    source_type        source_type_enum NOT NULL,
    source_url         TEXT NOT NULL,
    source_retrieved_at TIMESTAMPTZ NOT NULL,
    license            TEXT NOT NULL,
    properties         JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding          vector(384),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS places_geom_gist  ON places USING GIST (geom);
CREATE INDEX IF NOT EXISTS places_name_trgm  ON places USING GIN  (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS places_source_typ ON places (source_type);
-- ivfflat needs ANALYZE on populated data; the index can stay empty until
-- §11 ingestion lands enough rows for `lists` tuning to matter.
CREATE INDEX IF NOT EXISTS places_embedding_ivfflat
    ON places USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ── documents ─────────────────────────────────────────────────────────
-- A text source attached to a place. One place may have many documents
-- (e.g., a Wikipedia article + several OSM tags).
CREATE TABLE IF NOT EXISTS documents (
    id                 BIGSERIAL PRIMARY KEY,
    doc_id             TEXT NOT NULL UNIQUE,
    place_id           BIGINT REFERENCES places(id) ON DELETE CASCADE,
    title              TEXT NOT NULL,
    body               TEXT NOT NULL,
    source_type        source_type_enum NOT NULL,
    source_url         TEXT NOT NULL,
    source_retrieved_at TIMESTAMPTZ NOT NULL,
    license            TEXT NOT NULL,
    embedding          vector(384),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS documents_place_id    ON documents (place_id);
CREATE INDEX IF NOT EXISTS documents_source_typ  ON documents (source_type);
CREATE INDEX IF NOT EXISTS documents_body_trgm   ON documents USING GIN (body gin_trgm_ops);
CREATE INDEX IF NOT EXISTS documents_embedding_ivfflat
    ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ── updated_at trigger ────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS places_touch_updated_at    ON places;
DROP TRIGGER IF EXISTS documents_touch_updated_at ON documents;

CREATE TRIGGER places_touch_updated_at
    BEFORE UPDATE ON places
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER documents_touch_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
