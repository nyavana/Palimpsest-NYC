#!/usr/bin/env bash
#
# One-time host-side installer for the production hardening pieces.
# Run with sudo after the Palimpsest stack cutover is healthy:
#
#   sudo bash infra/host/install.sh
#
# What this installs:
#   /usr/local/sbin/refresh-cf-ufw     — Cloudflare-IP UFW allowlist refresher
#   /etc/systemd/system/refresh-cf-ufw.service
#   /etc/systemd/system/refresh-cf-ufw.timer
#
# Idempotent. Safe to re-run after upgrades.

set -euo pipefail

[[ $(id -u) -eq 0 ]] || { echo "must run as root (sudo)"; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"
SBIN=/usr/local/sbin
UNITS=/etc/systemd/system

echo "→ installing refresh-cf-ufw to $SBIN/"
install -m 0755 "$SRC/refresh-cf-ufw.sh" "$SBIN/refresh-cf-ufw"

echo "→ installing systemd units to $UNITS/"
install -m 0644 "$SRC/refresh-cf-ufw.service" "$UNITS/refresh-cf-ufw.service"
install -m 0644 "$SRC/refresh-cf-ufw.timer"   "$UNITS/refresh-cf-ufw.timer"

echo "→ systemctl daemon-reload"
systemctl daemon-reload

echo "→ enabling refresh-cf-ufw.timer"
systemctl enable --now refresh-cf-ufw.timer

echo "→ seeding rules now (one-shot service run)"
if systemctl start refresh-cf-ufw.service; then
    echo "  seed succeeded"
else
    echo "  WARNING: seed run failed — check 'journalctl -u refresh-cf-ufw'"
    exit 1
fi

echo
echo "Installed. Current cf-allowlist rule count:"
ufw status numbered | grep -c cf-allowlist || echo 0
echo
echo "Next run scheduled by:"
systemctl list-timers refresh-cf-ufw.timer --no-pager | tail -3 || true
