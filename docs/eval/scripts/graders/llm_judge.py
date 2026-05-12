"""LLM-judge grader. Runs each per-metric prompt and parses the JSON.

Public: async grade_row(*, row, judge_model, judge_client, metrics, temperature) -> dict.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from docs.eval.scripts.graders.rubric import METRIC_PROMPTS


class JudgeClient(Protocol):
    async def chat(self, *, model: str, messages: list[dict], temperature: float) -> dict[str, Any]: ...


def _user_payload(row: dict[str, Any]) -> str:
    return json.dumps(
        {
            "question": row.get("question"),
            "narration": row.get("narration"),
            "citations": row.get("citations") or [],
            "retrieved_docs": row.get("retrieved_docs") or [],
        },
        ensure_ascii=False, indent=2,
    )


async def grade_row(
    *,
    row: dict[str, Any],
    judge_model: str,
    judge_client: JudgeClient,
    metrics: list[str],
    temperature: float = 0.0,
) -> dict[str, dict[str, Any]]:
    payload = _user_payload(row)
    out: dict[str, dict[str, Any]] = {}
    for metric in metrics:
        prompt = METRIC_PROMPTS.get(metric)
        if prompt is None:
            out[metric] = {"score": None, "error": f"unknown metric: {metric}"}
            continue
        try:
            resp = await judge_client.chat(
                model=judge_model,
                messages=[{"role": "system", "content": prompt}, {"role": "user", "content": payload}],
                temperature=temperature,
            )
            parsed = json.loads(resp.get("content") or "")
            if not isinstance(parsed, dict):
                raise ValueError("judge did not return JSON object")
            out[metric] = {**parsed, "error": None}
        except json.JSONDecodeError as exc:
            out[metric] = {"score": None, "error": f"JSONDecodeError: {exc}"}
        except Exception as exc:  # noqa: BLE001
            out[metric] = {"score": None, "error": f"{type(exc).__name__}: {exc}"}
    return out
