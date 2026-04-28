## ADDED Requirements

### Requirement: File-based, lexicographic SQL migrations

The project SHALL maintain its database schema as plain `.sql` files at `apps/api/app/db/migrations/`, named `NNNN_description.sql` where `NNNN` is a zero-padded 4-digit integer. Migrations SHALL be applied in lexicographic order. No migration framework (Alembic, Flyway, etc.) is permitted in V1.

#### Scenario: Migration files exist and follow the naming convention
- **WHEN** the repository is checked out
- **THEN** every file under `apps/api/app/db/migrations/` matches the pattern `^[0-9]{4}_[a-z0-9_]+\.sql$`

#### Scenario: Migration order is purely filename-driven
- **WHEN** two migrations `0002_places.sql` and `0010_add_index.sql` exist
- **THEN** `0002_places.sql` is applied before `0010_add_index.sql`, regardless of mtime or commit order

### Requirement: All V1 migrations apply via postgres entrypoint on first volume creation

V1 SHALL use a single migration execution surface: every `.sql` file under `apps/api/app/db/migrations/` is mounted into the postgres container at `/docker-entrypoint-initdb.d/` and executed by the official postgres image's entrypoint when the data volume is first initialized. There is **no second runtime applier** in V1; the api process does NOT run migrations on startup.

These init migrations are responsible for:

- enabling required extensions (`postgis`, `vector`, `pg_trgm`);
- creating the base tables (`places`, `documents`, etc.);
- creating any indexes, views, or seed data needed for V1.

Schema changes during V1 development require **dropping and recreating the postgres data volume** (`docker compose down -v && docker compose up postgres`). This is acceptable because V1 has no persistent production data — any "real" corpus is re-ingested from `raw/` cache in minutes.

A startup-time runtime migration applier (with a `schema_migrations` ledger and idempotent re-application) is **deferred to v2** when a deployed instance with persistent data needs to upgrade in place.

#### Scenario: First volume creation runs all V1 migrations
- **WHEN** `docker compose up postgres` is run with no existing volume
- **THEN** the postgres container reports applying every `.sql` file under `apps/api/app/db/migrations/` from `/docker-entrypoint-initdb.d/` in lexicographic order, and api startup succeeds against the resulting schema

#### Scenario: Existing volume does not re-run migrations
- **WHEN** the postgres container is restarted with an existing data volume
- **THEN** init migrations are not re-applied (postgres entrypoint skips them) and no schema changes occur

#### Scenario: Schema change during V1 dev requires volume reset
- **WHEN** a developer adds `0003_add_index.sql` to the migrations directory
- **THEN** the developer MUST run `docker compose down -v` before `docker compose up`, otherwise `0003_*.sql` will not execute against the existing volume; the api SHALL document this requirement in its README

#### Scenario: api does NOT run migrations on startup in V1
- **WHEN** the api container starts
- **THEN** no `psql -f` or equivalent migration code is executed by the api process; the api expects the schema to be already in place from postgres entrypoint

### Requirement: Forward-only, no down migrations

Migrations SHALL be forward-only. `down` migrations are not supported in V1. Recovery from a bad migration is via dropping the postgres volume and re-running from `0001_init.sql`. There is no production data to preserve in V1.

#### Scenario: A migration cannot be reverted in V1
- **WHEN** a developer wants to undo `0004_*.sql`
- **THEN** the developer either edits `0004_*.sql` directly and re-creates the volume, or adds `0005_undo.sql` as a forward fix; there is no rollback mechanism

### Requirement: Migrations directory is the single source of truth

There SHALL be exactly one location where schema is defined: `apps/api/app/db/migrations/`. Schema MUST NOT be created via SQLAlchemy `metadata.create_all()` or any ORM-driven `CREATE TABLE` calls in production code paths. ORM models in `apps/api/app/db/models.py` are read-only mirrors of what migrations define.

#### Scenario: ORM cannot mutate the schema
- **WHEN** the api code is grepped for `metadata.create_all` or `Base.metadata.create`
- **THEN** no production call site exists; tests MAY create a clean schema via the migration files, not via ORM metadata
