#!/usr/bin/env bash
#
# One-shot dev → prod cutover for Palimpsest-NYC.
#
# Default mode is DRY-RUN — prints what it would do without touching the
# stack. Pass --execute to actually run.
#
#   bash infra/host/cutover.sh             # dry-run
#   bash infra/host/cutover.sh --execute   # do it
#
# Run on the prod host, from the repo root. Requires:
#   - .env present in the cwd
#   - docker / docker compose v2
#   - sudo (passwordless)
#   - the new prod images already in ghcr.io (or built locally with the
#     same tags) — i.e. `make build-prod && make push-prod` was run
#
# Preserves the postgres data volume (`palimpsest-postgres-data`).
# Preserves the osrm data volume too: dev and prod compose pin the same
# osrm tag (v5.25.0; upstream Docker Hub has not published anything
# newer), so the existing extract is binary-compatible.

set -euo pipefail

DRY=1
[[ "${1:-}" == "--execute" ]] && DRY=0

run() {
    if (( DRY )); then
        echo "DRY: $*"
    else
        echo "→ $*"
        eval "$*"
    fi
}

prompt() {
    if (( DRY )); then
        echo "DRY: would prompt: $*"
    else
        read -r -p "$* [type yes to continue] " ans
        [[ $ans == yes ]] || { echo "aborted"; exit 1; }
    fi
}

[[ -f .env ]] || { echo "no .env in cwd — run from repo root"; exit 1; }

echo "==> Step 1: pre-flight"
run "chmod 600 .env"
ts=$(date -u +%Y%m%dT%H%M%SZ)
dump=/home/nyavana/palimpsest-pre-cutover-$ts.sql
run "sudo docker exec palimpsest-postgres pg_dumpall -U \$(grep ^POSTGRES_USER= .env | cut -d= -f2) > $dump"
run "chmod 600 $dump"
echo "    backup at: $dump"

echo
echo "==> Step 2: pull prod images"
tag=$(grep '^PALIMPSEST_TAG=' .env | cut -d= -f2 || echo 0.1.0)
if (( DRY )); then
    echo "DRY: would docker compose pull (api/web/postgres at tag $tag, plus osrm and redis)"
else
    PALIMPSEST_TAG=$tag sudo --preserve-env=PALIMPSEST_TAG \
        docker compose -f docker-compose.prod.yml pull \
        || { echo "image pull failed — check 'docker login ghcr.io' and that the tag $tag is published"; exit 1; }
fi

echo
echo "==> Step 3: generate + rotate postgres password"
prompt "About to rotate POSTGRES_PASSWORD in the live db. Continue?"
if (( DRY == 0 )); then
    new_pg=$(openssl rand -base64 36 | tr -d /=+ | cut -c -40)
    old_user=$(grep '^POSTGRES_USER=' .env | cut -d= -f2)
    old_db=$(grep '^POSTGRES_DB='   .env | cut -d= -f2)
    sudo docker exec palimpsest-postgres psql -U "$old_user" -d "$old_db" \
        -c "ALTER ROLE \"$old_user\" WITH PASSWORD '$new_pg';"
    # Update .env: POSTGRES_PASSWORD and APP_ENV
    sed -i.before-cutover -E \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$new_pg|" \
        -e "s|^APP_ENV=.*|APP_ENV=production|" \
        .env
    echo "  .env updated; previous version saved as .env.before-cutover"
fi

echo
echo "==> Step 4: stop dev stack (volumes preserved)"
prompt "About to 'docker compose down' the live dev stack. Continue?"
run "sudo docker compose down"

echo
echo "==> Step 5: start prod stack"
echo "    (osrm-data volume preserved; same v5.25.0 tag as the dev stack)"
run "PALIMPSEST_TAG=$tag sudo --preserve-env=PALIMPSEST_TAG docker compose -f docker-compose.prod.yml up -d"

echo
echo "==> Step 6: wait for healthchecks (up to 5 minutes)"
if (( DRY == 0 )); then
    for i in $(seq 1 60); do
        unhealthy=$(sudo docker compose -f docker-compose.prod.yml ps --format '{{.Name}} {{.Health}}' | grep -E 'starting|unhealthy' || true)
        [[ -z $unhealthy ]] && break
        sleep 5
    done
    sudo docker compose -f docker-compose.prod.yml ps
fi

echo
echo "==> Cutover complete. Next:"
echo "  1. Run verification: make verify-harden"
echo "  2. Install host hardening: sudo bash infra/host/install.sh"
echo "  3. Confirm /api/docs returns 404 from the public URL"
