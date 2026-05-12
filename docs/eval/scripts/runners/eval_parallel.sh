#!/bin/bash
# Parallel per-system eval wrapper for Phase 3 (and later Phase 4/5).
# Spawns 3 (or N) Python processes — one per system — each pointed at its
# own systems-<name>-only.yaml. The orchestrator (run_eval_v2.py) writes
# JSONL rows incrementally and detects the existing file on relaunch, so
# each wrapper subprocess can be killed and resumed without data loss.
#
# Per-system logs land at /tmp/eval_<name>.log; wrapper-level lifecycle
# events also surface to stdout (which the caller usually tees to
# /tmp/eval_parallel.log). The intent is fail-loud: every Python exit
# emits a `[name] python exit=N` line so a monitor tail can detect
# crashes within a few seconds rather than waiting for milestones.
#
# Usage:
#   bash docs/eval/scripts/runners/eval_parallel.sh [LABEL]
#
# LABEL defaults to "phase3"; JSONL outputs land in docs/eval/results/.
# Per-system YAMLs are auto-detected from
# docs/eval/scripts/systems-<name>-only.yaml. Add a new system by
# committing its yaml + appending its name + yaml path to SYSTEMS below.
#
# Stop with:  pkill -f eval_parallel.sh; pkill -f run_eval_v2

set -u
cd "$(dirname "$0")/../../../.."  # repo root
export OPENROUTER_API_KEY=$(grep ^OPENROUTER_API_KEY .env | cut -d= -f2)
export PYTHONPATH=.
export PYTHONUNBUFFERED=1

LABEL="${1:-phase3}"
QUESTIONS="docs/eval/questions/manhattan-100/all.txt"
OUT="docs/eval/results"

# Edit this list to add more parallel system runners. Each entry is
# "<name>:<yaml-path>". The name MUST match the system's `name` key.
SYSTEMS=(
  "vanilla:docs/eval/scripts/systems-vanilla-only.yaml"
  "naive_rag:docs/eval/scripts/systems-naive-only.yaml"
  "palimpsest-dense:docs/eval/scripts/systems-palimpsest-dense-only.yaml"
)

run_one() {
  local name="$1"
  local yaml="$2"
  local out_jsonl="$OUT/${LABEL}-${name}.jsonl"
  local logf="/tmp/eval_${name}.log"
  local attempt=0
  while true; do
    # Done if footer line present.
    if [ -f "$out_jsonl" ] && grep -q '"type": "footer"' "$out_jsonl" 2>/dev/null; then
      echo "[$name] complete at $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$logf"
      break
    fi
    attempt=$((attempt + 1))
    echo "=== [$name] attempt $attempt at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" \
      | tee -a "$logf"
    docs/eval/.venv/bin/python -u -m docs.eval.scripts.run_eval_v2 \
      --systems "$yaml" --questions "$QUESTIONS" --label "$LABEL" --out "$OUT" \
      >> "$logf" 2>&1
    rc=$?
    echo "[$name] python exit=$rc at $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      | tee -a "$logf"
    if [ "$attempt" -ge 50 ]; then
      echo "[$name] giving up after $attempt attempts" | tee -a "$logf"
      return 1
    fi
    sleep 2
  done
}

# Truncate per-system logs so a fresh run gets clean tail-F output.
for entry in "${SYSTEMS[@]}"; do
  name="${entry%%:*}"
  : > "/tmp/eval_${name}.log"
done

# Launch all systems in parallel.
pids=()
for entry in "${SYSTEMS[@]}"; do
  name="${entry%%:*}"
  yaml="${entry##*:}"
  run_one "$name" "$yaml" &
  pids+=($!)
  echo "[parallel] launched $name pid=$!"
done

echo "[parallel] all systems launched at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Wait for each in the order launched.
for pid in "${pids[@]}"; do
  wait "$pid"
done

echo "[parallel] all done at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
