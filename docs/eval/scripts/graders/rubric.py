"""Per-metric grading prompts. Bumped via judge.yaml's prompt_version."""

from __future__ import annotations

_CCR = """You are evaluating Citation Correctness Rate (CCR).
Definition: fraction of citations whose doc_id appears in retrieved_docs AND whose `span` is plausibly supported by that document's `body_excerpt`. If there are no citations, score 0.
If retrieved_docs is empty for the row, FIRST check whether the system is a no-retrieval baseline (e.g. vanilla_llm) — in that case treat the citations themselves as the system's bibliography and judge each `span` against general knowledge of Manhattan. For retrieval-using systems with empty retrieved_docs, score 0 (the system cited without retrieving).
Return EXACTLY one JSON object: {"score": <float in [0,1]>, "reasoning": "<one sentence>"}.
You will receive: question, narration, citations, retrieved_docs (each with body_excerpt). Use `body_excerpt` as the authoritative source for span support."""

_HR = """You are evaluating Hallucination Rate (HR). Lower is better.
Extract up to 8 factual claims from the narration (first 8 in order). For each claim, decide if it is supported by any retrieved document's `body_excerpt` (preferred) or, when retrieved_docs is empty AND the system is a no-retrieval baseline, by general knowledge of Manhattan.
Return EXACTLY one JSON object: {"score": <n_unsupported/n_claims>, "n_claims": <int>, "n_unsupported": <int>, "reasoning": "<one sentence>"}.
Do NOT auto-assign HR=1.0 just because retrieved_docs is empty — that punishes vanilla_llm by construction. The score reflects whether the claims are unsupported, not whether retrieval was used."""

_FA = """You are evaluating Factual Accuracy (FA). Stricter than HR: claims are checked against real-world knowledge about Manhattan, not against retrievals (but you MAY consult body_excerpt as corroborating evidence).
Extract up to 8 factual claims. For each, decide if it is factually correct.
Return EXACTLY one JSON object: {"score": <n_correct/n_checked>, "n_checked": <int>, "n_correct": <int>, "reasoning": "<one sentence>"}."""

_NQ = """You are evaluating Narration Quality (NQ) on a 1-5 scale.
Rate four dimensions each 1-5: coherence, informativeness, geographic_plausibility, style_fit (walking-tour register).
Return EXACTLY one JSON object: {"score": <mean of four>, "coherence": <int>, "informativeness": <int>, "geographic_plausibility": <int>, "style_fit": <int>, "reasoning": "<one sentence>"}."""

_GRR = """You are evaluating Graceful Refusal (GRR) on an OUT-OF-SCOPE question (place outside Manhattan or fictional).
Correct behavior is to refuse or redirect, not confabulate.
Return EXACTLY one JSON object: {"score": 0 or 1, "reasoning": "<one sentence>"}."""


METRIC_PROMPTS: dict[str, str] = {
    "ccr": _CCR, "hr": _HR, "fa": _FA, "nq": _NQ, "grr": _GRR,
}
