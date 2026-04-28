# Migrations

Plain SQL files. Naming: `NNNN_description.sql` (zero-padded 4-digit prefix).

V1 has a single execution surface: the postgres container mounts this
directory at `/docker-entrypoint-initdb.d/` and runs every `.sql` file
in lexicographic order on first volume creation. The api process does
**not** run migrations on startup.

## Adding a migration

1. Pick the next number: `0003_…`, `0004_…`, etc.
2. Write the migration. Forward-only — no `down` migrations.
3. Drop the dev volume and re-init:
   ```bash
   make nuke   # docker compose down -v
   make up
   ```
   New rows ingested from `raw/` cache come back in minutes.

The runtime applier with `schema_migrations` ledger is deferred to v2.
