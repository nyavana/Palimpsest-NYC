"""Run the LLM-judge over every row in a set of result JSONLs.

Writes one CSV per input JSONL with per-metric scores.

Usage:
    OPENROUTER_API_KEY=... python -m docs.eval.scripts.judge_run \\
        --inputs 'docs/eval/results/phase3-baselines-*.jsonl' \\
        --categories docs/eval/questions/manhattan-100/categories.yaml \\
        --out docs/eval/grades
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import glob
import json
import os
import random
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docs.eval.scripts.graders.llm_judge import grade_row
from docs.eval.scripts.openrouter_client import OpenRouterChatClient


# FA is expensive; we restrict to calibration set + 30 random non-calibration questions.
# NOTE: the canonical plan targets a 100-question bank; our Manhattan-100 bank is actually
# 95 questions (single 0-29, multi 30-54, geographic 55-69, per-neighborhood 70-84,
# out-of-scope 85-94). These 20 calibration indices pick the first 4 of each of the 5
# categories so calibration coverage stays proportional to the bank we actually ship.
CALIBRATION_INDICES_IN_ALL_TXT = {
    0, 1, 2, 3,          # single_place
    30, 31, 32, 33,      # multi_place
    55, 56, 57, 58,      # geographic
    70, 71, 72, 73,      # per_neighborhood
    85, 86, 87, 88,      # out_of_scope
}


def _read_categories(path: Path) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text())["questions"]


def _read_rows(path: Path) -> tuple[dict, list[dict], dict]:
    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    header = lines[0]
    rows = [l for l in lines if l.get("type") == "row"]
    footer = lines[-1]
    return header, rows, footer


def _metrics_for(*, is_oos: bool, run_fa: bool) -> list[str]:
    if is_oos:
        return ["grr"]
    base = ["ccr", "hr", "nq"]
    if run_fa:
        base.insert(2, "fa")
    return base


class _CostTrackingJudgeClient:
    """Wraps the underlying chat client to sum ``cost_usd`` across all calls.

    ``grade_row`` only returns parsed metric JSON, so to enforce the $10 cap
    we have to intercept the raw chat response at the client seam. The
    wrapper is fully transparent — same ``chat`` signature, same dict
    response — and the running ``total_usd`` is what the orchestration
    loop polls between rows.
    """

    def __init__(self, *, inner: OpenRouterChatClient) -> None:
        self._inner = inner
        self.total_usd: float = 0.0
        self.n_calls: int = 0

    async def chat(self, **kwargs: Any) -> dict[str, Any]:
        resp = await self._inner.chat(**kwargs)
        self.n_calls += 1
        try:
            self.total_usd += float(resp.get("cost_usd") or 0.0)
        except (TypeError, ValueError):
            pass
        return resp


async def judge_file(
    *,
    in_path: Path,
    out_path: Path,
    categories: list[dict[str, Any]],
    fa_indices: set[int],
    judge_client: Any,
    judge_model: str,
    max_cost_usd: float | None = None,
    cost_tracker: _CostTrackingJudgeClient | None = None,
) -> bool:
    """Judge every row in ``in_path`` and write per-metric CSV to ``out_path``.

    Returns True if completed normally, False if the cost cap was tripped
    (so the caller can also stop dispatching to remaining systems).
    """
    header, rows, _ = _read_rows(in_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    capped = False
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "system", "index", "question",
            "ccr_score", "hr_score", "fa_score", "nq_score", "grr_score",
            "ccr_reasoning", "hr_reasoning", "fa_reasoning", "nq_reasoning", "grr_reasoning",
            "error",
        ])
        for i, row in enumerate(rows):
            cat = categories[i]
            is_oos = bool(cat.get("is_out_of_scope"))
            run_fa = (i in fa_indices)
            row["is_out_of_scope"] = is_oos
            grades = await grade_row(
                row=row, judge_model=judge_model,
                judge_client=judge_client,
                metrics=_metrics_for(is_oos=is_oos, run_fa=run_fa),
                temperature=0.0,
            )
            w.writerow([
                header["system"], i, row.get("question"),
                grades.get("ccr", {}).get("score"),
                grades.get("hr", {}).get("score"),
                grades.get("fa", {}).get("score"),
                grades.get("nq", {}).get("score"),
                grades.get("grr", {}).get("score"),
                grades.get("ccr", {}).get("reasoning", ""),
                grades.get("hr", {}).get("reasoning", ""),
                grades.get("fa", {}).get("reasoning", ""),
                grades.get("nq", {}).get("reasoning", ""),
                grades.get("grr", {}).get("reasoning", ""),
                "; ".join(
                    f"{m}:{grades[m]['error']}" for m in grades if grades[m].get("error")
                ),
            ])
            fh.flush()
            if (
                max_cost_usd is not None
                and cost_tracker is not None
                and cost_tracker.total_usd > max_cost_usd
            ):
                print(
                    f"!! cost cap tripped: ${cost_tracker.total_usd:.4f} > "
                    f"${max_cost_usd:.2f} after {cost_tracker.n_calls} judge calls; "
                    f"stopping early in {in_path.name} at row {i}",
                    flush=True,
                )
                capped = True
                break
    return not capped


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", required=True, help="Glob of input JSONL files.")
    p.add_argument("--categories", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("docs/eval/grades"))
    p.add_argument("--judge-model", default="anthropic/claude-opus-4-7")
    p.add_argument("--judge-base", default="https://openrouter.ai/api/v1")
    p.add_argument("--fa-extra", type=int, default=30,
                   help="Number of non-calibration indices to sample for FA.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--max-cost-usd", type=float, default=10.0,
                   help="Hard upper bound on total judge spend; stop early once exceeded.")
    args = p.parse_args()

    categories = _read_categories(args.categories)
    rng = random.Random(args.seed)
    non_cal = [i for i in range(len(categories)) if i not in CALIBRATION_INDICES_IN_ALL_TXT]
    rng.shuffle(non_cal)
    fa_indices = CALIBRATION_INDICES_IN_ALL_TXT | set(non_cal[: args.fa_extra])

    api_key = os.environ["OPENROUTER_API_KEY"]
    files = sorted(glob.glob(args.inputs))
    if not files:
        raise SystemExit(f"no files matched: {args.inputs}")

    async with httpx.AsyncClient(base_url=args.judge_base, timeout=120.0) as http:
        inner = OpenRouterChatClient(http_client=http, api_key=api_key)
        judge = _CostTrackingJudgeClient(inner=inner)
        for fp in files:
            in_path = Path(fp)
            out_path = args.out / (in_path.stem + "-judged.csv")
            print(f"-> {in_path} -> {out_path}", flush=True)
            ok = await judge_file(
                in_path=in_path, out_path=out_path,
                categories=categories, fa_indices=fa_indices,
                judge_client=judge, judge_model=args.judge_model,
                max_cost_usd=args.max_cost_usd, cost_tracker=judge,
            )
            print(
                f"   running judge spend: ${judge.total_usd:.4f} "
                f"({judge.n_calls} calls)",
                flush=True,
            )
            if not ok:
                print(
                    f"!! skipping remaining systems after cost cap "
                    f"(${args.max_cost_usd:.2f}) tripped",
                    flush=True,
                )
                break


if __name__ == "__main__":
    asyncio.run(main())
