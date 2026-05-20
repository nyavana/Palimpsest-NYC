# Runbook: dev → prod cutover

The first time the live stack on a host moves from `docker-compose.yml` (dev — `palimpsest/api:dev` images, `uvicorn --reload`, source bind-mounted) to `docker-compose.prod.yml` (prod — pinned GHCR images, hardened compose blocks).

## Pre-flight

You should be SSHed into the prod host, at the repo root (`/home/nyavana/git/Palimpsest-NYC` on `racknerd-2.5g`), with `docker compose ps` showing the dev stack healthy.

Both data volumes (`palimpsest-postgres-data` and `palimpsest-osrm-data`) have the **same name** in dev and prod compose, and both pin OSRM to the same tag (`v5.25.0` — the upstream Docker Hub repo has not published anything newer since 2021), so swapping compose files reuses both volumes intact.

Required:

- `make build-prod && make push-prod` already done from a build host (publishes `ghcr.io/nyavana/palimpsest-{api,web,postgres}:0.1.0`), OR locally-tagged images present on the host.
- `docker login ghcr.io` if pulling rather than building.
- `~30 minutes` of acceptable downtime for the osrm re-extract on the first up.

## Procedure

Run from the host repo root:

```bash
bash infra/host/cutover.sh              # dry-run first — prints every step
bash infra/host/cutover.sh --execute    # do it
```

What `--execute` runs, in order:

1. **Pre-flight.** `chmod 600 .env`. Take a pre-cutover `pg_dumpall` dump to `/home/nyavana/palimpsest-pre-cutover-<UTC>.sql`, mode 600.
2. **Pull prod images.** `docker compose -f docker-compose.prod.yml pull` for all services at `$PALIMPSEST_TAG`.
3. **Postgres password rotation.** Generates a 40-char random password, runs `ALTER ROLE palimpsest WITH PASSWORD '...'` on the **live** db (so existing connections aren't disturbed), then verifies the new password authenticates by opening a fresh `psql` connection with `PGPASSWORD=$new_pg`. **Only if that verification succeeds** does it rewrite `.env` with the new `POSTGRES_PASSWORD` and `APP_ENV=production`; original `.env` is saved as `.env.before-cutover`. If the verify fails, the script bails with `.env` left intact — operator can re-run `ALTER ROLE` with the old password by hand.
4. **Stop dev stack.** `docker compose down` — NOT `down -v`. Both data volumes persist (`palimpsest-postgres-data`, `palimpsest-osrm-data`).
5. **Start prod stack.** `docker compose -f docker-compose.prod.yml up -d`.
6. **Wait for health.** Polls `docker compose ps` for up to 5 minutes. Fails fast (does NOT spin out the timeout) if any container is `exited`, `dead`, or `restarting`. Returns once nothing is `starting`/`unhealthy`.

## Verification

After cutover:

```bash
make verify-harden
```

This is a read-only batch that confirms:

- `.env` mode is `600`
- No publicly-listening sockets on 5432/6379/8000 (postgres/redis/api are now docker-network-only)
- `palimpsest-api` has `CapDrop=[ALL]`, `ReadonlyRootfs=true`, `Memory>0`
- `https://palimpsest-demo.nyavana.io/api/docs` returns 404 (FastAPI Swagger disabled in prod)

Manual extras worth running once:

```bash
# nginx really is non-root inside the web container
sudo docker exec palimpsest-web id

# osrm tag (pinned to v5.25.0; bumping this is tracked as a follow-up)
sudo docker inspect palimpsest-osrm --format '{{.Config.Image}}'

# api/worker can talk to postgres on the new password
sudo docker logs --tail 50 palimpsest-api  | grep -i 'error\|auth' || echo "no auth errors"
```

## Rollback

If the prod stack is broken after step 6:

```bash
# 1. Stop the prod stack, keep volumes.
sudo docker compose -f docker-compose.prod.yml down

# 2. Restore the old POSTGRES_PASSWORD value. (postgres now has the NEW
#    password in its data dir; you must either keep the new password or
#    rotate back.)
#    Easier: bring prod postgres alone back up to ALTER ROLE back:
sudo docker compose -f docker-compose.prod.yml up -d postgres
NEW_PG=$(grep ^POSTGRES_PASSWORD= .env       | cut -d= -f2)
OLD_PG=$(grep ^POSTGRES_PASSWORD= .env.before-cutover | cut -d= -f2)
sudo docker exec palimpsest-postgres psql -U palimpsest -d palimpsest \
    -c "ALTER ROLE palimpsest WITH PASSWORD '$OLD_PG';"
sudo docker compose -f docker-compose.prod.yml down

# 3. Restore .env from the snapshot the script left.
cp .env.before-cutover .env

# 4. Bring the dev stack back up. Same volume re-attaches.
sudo docker compose up -d
```

If postgres itself is corrupt (rare — the volume isn't touched by the cutover):

```bash
sudo docker volume rm palimpsest-postgres-data
sudo docker compose up -d postgres
cat /home/nyavana/palimpsest-pre-cutover-*.sql \
    | sudo docker exec -i palimpsest-postgres psql -U palimpsest -d palimpsest
```

## After cutover succeeds

```bash
sudo bash infra/host/install.sh         # CF allowlist + weekly timer
```

Verify the CF allowlist with `sudo ufw status numbered | grep -c cf-allowlist` — Cloudflare currently publishes 15 IPv4 + 7 IPv6 CIDRs, so the count is **(15 + 7) × 2 ports = 44**. The exact number will change as Cloudflare adds/removes ranges; the weekly timer keeps it fresh. Then test that direct-origin requests are rejected:

```bash
curl --resolve palimpsest-demo.nyavana.io:443:198.46.175.245 \
     -kI https://palimpsest-demo.nyavana.io/   # should time out
```
