#!/usr/bin/env bash
# Switch the router to a free OpenRouter model for the §13.6 cost comparison,
# restart the api container, clear LLM telemetry + cache, then run the bench.
# A backup of .env is left at .env.before-swap so the caller can restore.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

FREE_MODEL="${1:-openai/gpt-oss-120b:free}"
LABEL="${2:-router-bench-free-gptoss}"
QUESTIONS="${3:-docs/eval/questions/v1-router-bench.txt}"

echo "→ backing up .env → .env.before-swap"
cp .env .env.before-swap

echo "→ writing model overrides into .env (free model: $FREE_MODEL)"
FREE_MODEL="$FREE_MODEL" .eval-venv/bin/python - <<'PY'
import os, re
from pathlib import Path
free_model = os.environ["FREE_MODEL"]
env = Path(".env")
text = env.read_text()
for var in ("OPENROUTER_STANDARD_MODEL", "OPENROUTER_COMPLEX_MODEL", "LOCAL_LLM_MODEL"):
    text = re.sub(rf"^{var}=.*$", f"{var}={free_model}", text, flags=re.M)
env.write_text(text)
print(f"  wrote .env (model={free_model})")
PY

echo "→ restarting api container so the new env is picked up"
docker compose up -d --force-recreate api

echo "→ waiting for /health"
for i in $(seq 1 30); do
  if curl -sS -o /dev/null -w "%{http_code}" http://localhost:8000/health | grep -q 200; then
    echo "  api up after ${i}s"
    break
  fi
  sleep 1
done

echo "→ running bench: $LABEL"
.eval-venv/bin/python -u docs/eval/scripts/run_eval.py \
    --questions "$QUESTIONS" \
    --label "$LABEL" \
    --out docs/eval/results \
    --clear-telemetry

echo
echo "✔ free-model bench done. To restore the original .env:"
echo "   cp .env.before-swap .env && docker compose up -d --force-recreate api"
