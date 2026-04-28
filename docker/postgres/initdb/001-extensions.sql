-- Run once on first container boot (docker-entrypoint-initdb.d).
-- Enables the three extensions Palimpsest depends on.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Sanity-check the installation.
DO $$
BEGIN
    RAISE NOTICE 'postgis version:  %', (SELECT postgis_version());
    RAISE NOTICE 'pgvector installed: %', (
        SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')
    );
    RAISE NOTICE 'pg_trgm installed: %', (
        SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm')
    );
END$$;
