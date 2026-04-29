#!/usr/bin/env bash
# Restore the original .env (saved by swap-to-free-model.sh) and recreate
# the api container.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

if [[ ! -f .env.before-swap ]]; then
  echo "✗ no .env.before-swap found — was the swap actually run?"
  exit 1
fi

cp .env.before-swap .env
echo "→ restored .env"
docker compose up -d --force-recreate api
echo "✔ api restarted with restored .env"
