# Postgres 16 with PostGIS, pgvector, and pg_trgm — the single datastore
# for the Palimpsest project. We extend the official postgis image because
# PostGIS is awkward to install at runtime, then layer pgvector on top.

FROM postgis/postgis:16-3.4

ARG PG_MAJOR=16

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-${PG_MAJOR}-pgvector \
    && rm -rf /var/lib/apt/lists/*

# Healthcheck is defined at compose level (pg_isready).
