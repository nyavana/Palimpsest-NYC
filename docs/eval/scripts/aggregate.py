"""Aggregate per-system metrics from judge CSVs (+ optional hand-grade CSV).

Outputs (when invoked as a script):

* ``docs/eval/results/ablation_table.md`` — the headline table with per-system
  means and 95% bootstrap CIs, plus Cohen's kappa on the calibration subset
  when hand grades are supplied.
* ``docs/eval/results/per_region-<system>.csv`` — only when ``--categories``
  is passed; one CSV per system grouped by ``region`` from categories.yaml
  (Phase 6.1).
* ``docs/eval/results/per_source-<system>.csv`` — only when
  ``--inputs-jsonl`` is set; one CSV per system grouped by the dominant
  citation ``source_type`` per row (Phase 6.2).

Project-specific deviation from the canonical plan (L3365-3660):
``--hand-grades`` is optional. The plan assumed a 20-row calibration CSV
existed alongside the judged CSVs; for this project we skip human review
entirely. When no hand grades are supplied the aggregator still writes
``ablation_table.md`` and records ``kappa: null (no hand grades)`` in
place of a kappa value.

The row count is also derived from the actual judged CSVs rather than
being hard-coded to 100, because the Manhattan-100 bank ships 95 rows.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Loading + parsing
# ---------------------------------------------------------------------------


def _maybe_float(v: Any) -> float | None:
    """Permissive float parser. Empty strings, ``None``, and the literal
    ``"None"`` (which is what ``csv.writer`` emits when handed a Python
    ``None``) all collapse to ``None`` so the downstream means ignore them.
    """
    if v is None or v == "" or v == "None":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_judge_grades(path: Path) -> list[dict[str, Any]]:
    """Read one ``*-judged.csv`` file emitted by ``judge_run.py``."""
    out: list[dict[str, Any]] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out.append({
                "system": row["system"],
                "index": int(row["index"]),
                "question": row.get("question"),
                "ccr_score": _maybe_float(row.get("ccr_score")),
                "hr_score": _maybe_float(row.get("hr_score")),
                "fa_score": _maybe_float(row.get("fa_score")),
                "nq_score": _maybe_float(row.get("nq_score")),
                "grr_score": _maybe_float(row.get("grr_score")),
            })
    return out


def _read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip() and json.loads(line).get("type") == "row"
    ]


# ---------------------------------------------------------------------------
# Summaries (means + 95% bootstrap CIs)
# ---------------------------------------------------------------------------


_METRICS: tuple[str, ...] = ("ccr", "hr", "fa", "nq", "grr")


def _mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return statistics.fmean(xs)


def bootstrap_ci95_mean(
    sample: list[float],
    *,
    seed: int = 0,
    n_resamples: int = 1000,
) -> tuple[float | None, float | None]:
    """Nonparametric percentile bootstrap CI for the sample mean.

    Returns ``(lo, hi)`` covering the central 95% of resampled means, or
    ``(None, None)`` for an empty sample. Bootstrap was picked over the
    normal-approximation CI because several metrics in our bank (CCR, GRR)
    are bounded [0, 1] and often near a boundary, where the normal CI
    misbehaves. ``seed`` is fixed in the CLI for reproducibility.
    """
    n = len(sample)
    if n == 0:
        return (None, None)
    if n == 1:
        return (sample[0], sample[0])
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_resamples):
        resample = [sample[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.fmean(resample))
    means.sort()
    lo = means[max(0, int(math.floor(0.025 * n_resamples)))]
    hi = means[min(n_resamples - 1, int(math.ceil(0.975 * n_resamples)) - 1)]
    return (lo, hi)


def summarize_system(
    rows: list[dict[str, Any]],
    *,
    ci_seed: int = 42,
    ci_resamples: int = 1000,
) -> dict[str, Any]:
    """Per-system means + 95% CIs for each metric. Missing scores are dropped
    per-metric, so e.g. FA (sparse by design) doesn't drag CCR's n down.
    """
    def _col(name: str) -> list[float]:
        return [r[name] for r in rows if r[name] is not None]

    out: dict[str, Any] = {
        "system": rows[0]["system"] if rows else None,
        "n": len(rows),
    }
    for m in _METRICS:
        col = _col(f"{m}_score")
        out[f"{m}_mean"] = _mean(col)
        out[f"{m}_ci95"] = bootstrap_ci95_mean(
            col, seed=ci_seed + hash(m) % 10_000, n_resamples=ci_resamples,
        )
    return out


# ---------------------------------------------------------------------------
# Cohen's kappa
# ---------------------------------------------------------------------------


def cohen_kappa_binary(hand: list[int], judge: list[int]) -> float:
    """Cohen's kappa for two raters on binary labels.

    Formula:
        kappa = (p_o - p_e) / (1 - p_e)

    where ``p_o`` is the observed agreement rate and ``p_e`` is the
    chance-agreement rate computed from the marginal class probabilities.

    Edge cases:
    * Empty inputs raise ``AssertionError`` (matches canonical plan).
    * If ``p_e == 1.0`` (both raters always pick the same class) the
      denominator vanishes; we return 1.0 when ``p_o == 1.0`` and 0.0
      otherwise so the function never returns NaN.
    """
    assert len(hand) == len(judge) and len(hand) > 0
    n = len(hand)
    po = sum(1 for h, j in zip(hand, judge) if h == j) / n
    p_hand_1 = sum(hand) / n
    p_judge_1 = sum(judge) / n
    pe = p_hand_1 * p_judge_1 + (1 - p_hand_1) * (1 - p_judge_1)
    if math.isclose(pe, 1.0):
        return 1.0 if math.isclose(po, 1.0) else 0.0
    return (po - pe) / (1.0 - pe)


# Calibration subset is shared with judge_run.py; duplicated here so this
# module can be imported without dragging in httpx/openrouter at import time.
CALIBRATION_INDICES_IN_ALL_TXT: set[int] = {
    0, 1, 2, 3,
    30, 31, 32, 33,
    55, 56, 57, 58,
    70, 71, 72, 73,
    85, 86, 87, 88,
}


def _binary(score: float | None, threshold: float = 0.5) -> int | None:
    if score is None:
        return None
    return 1 if score >= threshold else 0


def compute_calibration_kappa(
    hand_csv: Path,
    judge_rows_by_system: dict[str, dict[int, dict[str, Any]]],
    *,
    threshold: float = 0.5,
    restrict_to_calibration: bool = True,
) -> tuple[float | None, int]:
    """Pair hand grades with judge grades on the CCR axis and return (kappa, n).

    ``judge_rows_by_system`` is keyed by system and then row index — the
    same shape ``kappa.py`` builds in the canonical plan. Pairs are kept
    only when both the hand and judge CCR scores are non-null.
    """
    pairs: list[tuple[int, int]] = []
    with hand_csv.open(newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                idx = int(row["index"])
            except (KeyError, TypeError, ValueError):
                continue
            if restrict_to_calibration and idx not in CALIBRATION_INDICES_IN_ALL_TXT:
                continue
            sys_name = row.get("system")
            jr = judge_rows_by_system.get(sys_name, {}).get(idx) if sys_name else None
            if jr is None:
                continue
            h = _binary(_maybe_float(row.get("ccr_hand")), threshold)
            j = _binary(jr.get("ccr_score"), threshold)
            if h is not None and j is not None:
                pairs.append((h, j))
    if not pairs:
        return (None, 0)
    hs = [h for h, _ in pairs]
    js = [j for _, j in pairs]
    return (cohen_kappa_binary(hs, js), len(pairs))


# ---------------------------------------------------------------------------
# Phase 6 helpers
# ---------------------------------------------------------------------------


def per_region_breakdown(
    rows: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group rows by ``region`` from categories.yaml and compute per-region
    means. Rows whose ``index`` exceeds the categories list are dropped
    rather than silently mapped to ``unknown``.
    """
    by_region: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        idx = r["index"]
        if idx < 0 or idx >= len(categories):
            continue
        region = categories[idx].get("region", "unknown")
        by_region.setdefault(region, []).append(r)
    return [
        {
            "region": region,
            **{
                f"{m}_mean": _mean([r[f"{m}_score"] for r in rs if r[f"{m}_score"] is not None])
                for m in _METRICS
            },
            "n": len(rs),
        }
        for region, rs in sorted(by_region.items())
    ]


def attach_citation_source_types(
    judge_rows: list[dict[str, Any]],
    jsonl_path: Path,
) -> list[dict[str, Any]]:
    """Read the original JSONL and copy each row's citation source_types
    onto the matching judge row, keyed by ``index``.
    """
    payload_rows = _read_jsonl_rows(jsonl_path)
    payload_by_index = {p["index"]: p for p in payload_rows if "index" in p}
    out: list[dict[str, Any]] = []
    for r in judge_rows:
        p = payload_by_index.get(r["index"], {})
        types = [c.get("source_type") for c in (p.get("citations") or [])]
        out.append({**r, "citation_source_types": [t for t in types if t]})
    return out


def per_source_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group rows by the dominant citation ``source_type`` (most frequent in
    that row's citations; ties broken alphabetically). Rows with no
    citations are skipped.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        types = r.get("citation_source_types") or []
        if not types:
            continue
        c = Counter(types)
        max_count = max(c.values())
        dominant = sorted(t for t, k in c.items() if k == max_count)[0]
        buckets.setdefault(dominant, []).append(r)

    return [
        {
            "dominant_source": source,
            **{
                f"{m}_mean": _mean([r[f"{m}_score"] for r in rs if r[f"{m}_score"] is not None])
                for m in _METRICS
            },
            "n": len(rs),
        }
        for source, rs in sorted(buckets.items())
    ]


# ---------------------------------------------------------------------------
# Markdown writer
# ---------------------------------------------------------------------------


def _fmt(v: float | None, places: int = 3) -> str:
    return "—" if v is None else f"{v:.{places}f}"


def _fmt_ci(ci: tuple[float | None, float | None] | None, places: int = 3) -> str:
    if ci is None:
        return "—"
    lo, hi = ci
    if lo is None or hi is None:
        return "—"
    return f"[{lo:.{places}f}, {hi:.{places}f}]"


def write_ablation_markdown(
    out_path: Path,
    summaries: list[dict[str, Any]],
    *,
    kappa: float | None = None,
    kappa_n: int = 0,
) -> None:
    """Write the headline ablation table.

    ``kappa=None`` records ``kappa: null (no hand grades)`` per the
    project deviation. ``kappa`` of any numeric value is recorded with
    its sample size.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Ablation table - manhattan-100",
        "",
        "| System | n | CCR (mean [95% CI]) | HR (mean [95% CI]) | "
        "FA (mean [95% CI]) | NQ (mean [95% CI]) | GRR (mean [95% CI]) |",
        "|---|---:|---|---|---|---|---|",
    ]
    for s in summaries:
        lines.append(
            f"| {s['system']} | {s['n']} | "
            f"{_fmt(s['ccr_mean'])} {_fmt_ci(s.get('ccr_ci95'))} | "
            f"{_fmt(s['hr_mean'])} {_fmt_ci(s.get('hr_ci95'))} | "
            f"{_fmt(s['fa_mean'])} {_fmt_ci(s.get('fa_ci95'))} | "
            f"{_fmt(s['nq_mean'], 2)} {_fmt_ci(s.get('nq_ci95'), 2)} | "
            f"{_fmt(s['grr_mean'])} {_fmt_ci(s.get('grr_ci95'))} |"
        )
    lines.append("")
    if kappa is None:
        lines.append("kappa: null (no hand grades)")
    else:
        lines.append(f"kappa(CCR, threshold=0.5) = {kappa:.3f} (n={kappa_n})")
    lines.append("")
    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------


def _write_breakdown_csv(out_csv: Path, table: list[dict[str, Any]]) -> None:
    if not table:
        return
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0].keys()))
        w.writeheader()
        for r in table:
            w.writerow(r)


# ---------------------------------------------------------------------------
# Orchestration (callable from tests + CLI)
# ---------------------------------------------------------------------------


def run_aggregate(
    *,
    inputs_glob: str,
    out_path: Path,
    hand_grades_path: Path | None = None,
    categories_path: Path | None = None,
    inputs_jsonl_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the full aggregation pipeline. Returns a dict describing what
    was written so tests can assert on the result without re-parsing the
    markdown.
    """
    files = sorted(glob.glob(inputs_glob))
    summaries: list[dict[str, Any]] = []
    judge_rows_by_system: dict[str, dict[int, dict[str, Any]]] = {}
    parsed_by_file: dict[str, list[dict[str, Any]]] = {}

    for fp in files:
        rows = load_judge_grades(Path(fp))
        parsed_by_file[fp] = rows
        summaries.append(summarize_system(rows))
        for r in rows:
            judge_rows_by_system.setdefault(r["system"], {})[r["index"]] = r

    # Optional Cohen's kappa --- skipped per project deviation when hand
    # grades are absent or the file is missing on disk.
    kappa: float | None = None
    kappa_n = 0
    if hand_grades_path is not None and Path(hand_grades_path).exists():
        kappa, kappa_n = compute_calibration_kappa(
            Path(hand_grades_path), judge_rows_by_system,
        )

    write_ablation_markdown(out_path, summaries, kappa=kappa, kappa_n=kappa_n)

    # Optional per-region CSVs.
    per_region_paths: list[Path] = []
    if categories_path is not None and Path(categories_path).exists():
        try:
            import yaml  # imported lazily so tests that don't need it stay light.
        except ImportError as exc:  # pragma: no cover - dev env safeguard
            raise RuntimeError("PyYAML is required for --categories") from exc
        categories = yaml.safe_load(Path(categories_path).read_text())["questions"]
        for fp, rows in parsed_by_file.items():
            if not rows:
                continue
            sys_name = rows[0]["system"]
            br = per_region_breakdown(rows, categories)
            csv_out = out_path.with_name(f"per_region-{sys_name}.csv")
            _write_breakdown_csv(csv_out, br)
            per_region_paths.append(csv_out)

    # Optional per-source CSVs.
    per_source_paths: list[Path] = []
    if inputs_jsonl_dir is not None:
        jsonl_dir = Path(inputs_jsonl_dir)
        for fp, rows in parsed_by_file.items():
            if not rows:
                continue
            stem = Path(fp).stem
            if stem.endswith("-judged"):
                stem = stem[: -len("-judged")]
            jsonl_candidates = list(jsonl_dir.glob(f"{stem}.jsonl"))
            if not jsonl_candidates:
                continue
            enriched = attach_citation_source_types(rows, jsonl_candidates[0])
            ps = per_source_breakdown(enriched)
            if not ps:
                continue
            sys_name = enriched[0]["system"]
            csv_out = out_path.with_name(f"per_source-{sys_name}.csv")
            _write_breakdown_csv(csv_out, ps)
            per_source_paths.append(csv_out)

    return {
        "out_path": out_path,
        "summaries": summaries,
        "kappa": kappa,
        "kappa_n": kappa_n,
        "per_region_csvs": per_region_paths,
        "per_source_csvs": per_source_paths,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inputs", required=True, help="Glob of judge CSVs.")
    p.add_argument(
        "--out",
        type=Path,
        default=Path("docs/eval/results/ablation_table.md"),
    )
    p.add_argument(
        "--hand-grades",
        type=Path,
        default=None,
        help=(
            "Optional CSV with hand grades on the calibration subset "
            "(columns: system, index, ccr_hand). When omitted, kappa is "
            "recorded as null."
        ),
    )
    p.add_argument(
        "--categories",
        type=Path,
        default=None,
        help="Optional categories.yaml; enables per-region CSVs.",
    )
    p.add_argument(
        "--inputs-jsonl-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory holding the original JSONL result files. "
            "When set, per-source CSVs (dominant citation source_type) "
            "are emitted alongside the markdown table."
        ),
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    result = run_aggregate(
        inputs_glob=args.inputs,
        out_path=args.out,
        hand_grades_path=args.hand_grades,
        categories_path=args.categories,
        inputs_jsonl_dir=args.inputs_jsonl_dir,
    )
    print(f"-> {result['out_path']}")
    for p in result["per_region_csvs"]:
        print(f"-> {p}")
    for p in result["per_source_csvs"]:
        print(f"-> {p}")
    if result["kappa"] is None:
        print("kappa: null (no hand grades)")
    else:
        print(f"kappa(CCR, threshold=0.5) = {result['kappa']:.3f} (n={result['kappa_n']})")


if __name__ == "__main__":
    main()
