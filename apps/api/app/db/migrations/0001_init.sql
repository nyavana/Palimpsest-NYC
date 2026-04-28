-- 0001_init.sql — extensions only.
-- Mounted into postgres via docker-entrypoint-initdb.d on first volume init.
-- Per spec: V1 has a single migration execution surface; the api does not
-- run migrations on startup. Schema changes during V1 require dropping the
-- volume (`docker compose down -v`) and re-initializing.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
