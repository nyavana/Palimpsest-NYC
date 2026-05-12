from __future__ import annotations

from typing import Any

import pytest

from docs.eval.scripts.graders import rubric
from docs.eval.scripts.graders.llm_judge import grade_row


class _FakeJudge:
    def __init__(self, *, responses: list[dict[str, Any]]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)

    async def chat(self, *, model: str, messages: list[dict], temperature: float) -> dict[str, Any]:
        self.calls.append({"model": model, "messages": messages, "temperature": temperature})
        return self._responses.pop(0)


def _row(**overrides: Any) -> dict[str, Any]:
    base = {
        "system": "palimpsest-dense",
        "question": "Tell me about the Cathedral.",
        "narration": "Built in 1892, the Cathedral of Saint John the Divine is on Amsterdam Avenue.",
        "citations": [{"doc_id": "wikipedia:Cathedral", "source_url": "x", "source_type": "wikipedia", "span": "Built in 1892"}],
        "retrieved_docs": [{"doc_id": "wikipedia:Cathedral", "source_url": "x", "source_type": "wikipedia", "name": "Cathedral", "score": 0.7}],
        "is_out_of_scope": False,
    }
    base.update(overrides)
    return base


def test_rubric_prompts_cover_all_metrics():
    for metric in ("ccr", "hr", "fa", "nq", "grr"):
        assert metric in rubric.METRIC_PROMPTS
        prompt = rubric.METRIC_PROMPTS[metric]
        assert "JSON" in prompt
        assert len(prompt) > 100


async def test_grade_row_returns_per_metric_grades():
    fake = _FakeJudge(responses=[
        {"content": '{"score": 1.0, "reasoning": "ok"}'},
        {"content": '{"score": 0.0, "n_claims": 2, "n_unsupported": 0, "reasoning": ""}'},
        {"content": '{"score": 1.0, "n_checked": 1, "n_correct": 1, "reasoning": ""}'},
        {"content": '{"score": 4.5, "coherence": 5, "informativeness": 4, "geographic_plausibility": 5, "style_fit": 4, "reasoning": ""}'},
    ])
    grades = await grade_row(row=_row(), judge_model="m", judge_client=fake, metrics=["ccr", "hr", "fa", "nq"], temperature=0.0)
    assert grades["ccr"]["score"] == 1.0
    assert grades["hr"]["score"] == 0.0
    assert grades["fa"]["score"] == 1.0
    assert grades["nq"]["score"] == 4.5
    assert len(fake.calls) == 4
