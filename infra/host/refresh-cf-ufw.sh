#!/usr/bin/env bash
#
# Refresh the UFW allowlist for ports 80 and 443 to match Cloudflare's
# published IP ranges. Installs to /usr/local/sbin/refresh-cf-ufw via
# infra/host/install.sh, and is run weekly by refresh-cf-ufw.timer.
#
# Why: this host's origin IP is reachable directly on 80/443 even though
# DNS for the public hostnames is on Cloudflare orange-cloud. Restricting
# 80/443 to CF IP ranges forces all real traffic through the CF edge
# (which keeps the WAF, rate limits, and bot management in the path).
#
# Anti-lockout: this script touches only ports 80 and 443. It refuses to
# run if the resulting ruleset would have zero ALLOW rules for port 22.
#
# Logs to journald via `logger -t refresh-cf-ufw`.

set -euo pipefail

LOGGER_TAG="refresh-cf-ufw"
CF_V4_URL="https://www.cloudflare.com/ips-v4"
CF_V6_URL="https://www.cloudflare.com/ips-v6"
RULE_COMMENT="cf-allowlist"
PORTS=(80 443)
MIN_CIDRS=5   # bail if either list comes back this short

log()  { logger -t "$LOGGER_TAG" -- "$*"; echo "[$LOGGER_TAG] $*"; }
fail() { log "ERROR: $*"; exit 1; }

# CIDR validation: anchored, IPv4 OR IPv6, /N prefix.
cidr_v4_re='^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$'
cidr_v6_re='^[0-9a-fA-F:]+(/[0-9]{1,3})?$'

[[ $(id -u) -eq 0 ]] || fail "must run as root"
command -v ufw >/dev/null   || fail "ufw not installed"
command -v curl >/dev/null  || fail "curl not installed"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

log "fetching $CF_V4_URL"
curl --fail --max-time 10 --silent -o "$tmp/ipv4" "$CF_V4_URL" \
    || fail "fetch failed: $CF_V4_URL"

log "fetching $CF_V6_URL"
curl --fail --max-time 10 --silent -o "$tmp/ipv6" "$CF_V6_URL" \
    || fail "fetch failed: $CF_V6_URL"

mapfile -t v4 < <(grep -v '^$' "$tmp/ipv4" || true)
mapfile -t v6 < <(grep -v '^$' "$tmp/ipv6" || true)

(( ${#v4[@]} >= MIN_CIDRS )) || fail "IPv4 list too short (${#v4[@]} entries; expected >= $MIN_CIDRS)"
(( ${#v6[@]} >= MIN_CIDRS )) || fail "IPv6 list too short (${#v6[@]} entries; expected >= $MIN_CIDRS)"

for c in "${v4[@]}"; do
    [[ $c =~ $cidr_v4_re ]] || fail "bad IPv4 CIDR: $c"
done
for c in "${v6[@]}"; do
    [[ $c =~ $cidr_v6_re ]] || fail "bad IPv6 CIDR: $c"
done

log "validated ${#v4[@]} IPv4 + ${#v6[@]} IPv6 CIDRs"

# Anti-lockout pre-check: SSH (port 22) must be ALLOWed after we finish.
# We never touch the port-22 rules, but verify they exist before changing
# anything else.
if ! ufw status | grep -E '^22(/tcp)?[[:space:]]+(ALLOW|LIMIT)' >/dev/null; then
    fail "no ALLOW/LIMIT rule for port 22 detected; refusing to change UFW (would risk SSH lockout)"
fi

# Delete prior cf-allowlist rules. UFW numbers shift as we delete, so
# loop until none remain.
while true; do
    line=$(ufw status numbered | grep "$RULE_COMMENT" | head -n1 || true)
    [[ -z $line ]] && break
    num=$(echo "$line" | sed -E 's/^\[ *([0-9]+)\].*/\1/')
    [[ $num =~ ^[0-9]+$ ]] || fail "could not parse rule number from: $line"
    log "deleting rule [$num]"
    # `echo y`, not `yes`: `yes` gets SIGPIPE'd when ufw exits, which
    # under `set -euo pipefail` aborts the whole script after the first
    # successful delete.
    echo y | ufw delete "$num" >/dev/null
done

# Re-add allow rules.
added=0
for port in "${PORTS[@]}"; do
    for cidr in "${v4[@]}" "${v6[@]}"; do
        ufw allow from "$cidr" to any port "$port" proto tcp comment "$RULE_COMMENT" >/dev/null
        ((added++))
    done
done

# Post-check: SSH still allowed?
if ! ufw status | grep -E '^22(/tcp)?[[:space:]]+(ALLOW|LIMIT)' >/dev/null; then
    fail "post-write check failed: SSH no longer allowed. UFW is in an unknown state — investigate immediately"
fi

log "applied $added cf-allowlist rules across ports ${PORTS[*]}"
