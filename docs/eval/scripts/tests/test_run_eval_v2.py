from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from docs.eval.scripts.run_eval_v2 import dispatch_system, write_run_jsonl


async def test_dispatch_vanilla_calls_run_vanilla(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_run_vanilla(**kwargs):
        captured.update(kwargs)
        return {"system": "vanilla", "question": kwargs["question"], "narration": "x"}

    monkeypatch.setattr("docs.eval.scripts.run_eval_v2.run_vanilla", fake_run_vanilla)
    cfg = {"name": "vanilla", "kind": "vanilla_llm", "model": "m", "temperature": 0.0}
    row = await dispatch_system(
        system=cfg, question="Q?", chat_client=object(),
        retrieve_client=None, api_http_client=None,
    )
    assert row["system"] == "vanilla"
    assert captured["question"] == "Q?"


async def test_dispatch_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown system kind"):
        await dispatch_system(
            system={"name": "x", "kind": "no_such"}, question="Q?",
            chat_client=None, retrieve_client=None, api_http_client=None,
        )


def test_write_run_jsonl_emits_header_and_footer(tmp_path: Path):
    rows = [
        {"system": "vanilla", "question": "Q1", "narration": "n1"},
        {"system": "vanilla", "question": "Q2", "narration": "n2"},
    ]
    out = tmp_path / "out.jsonl"
    write_run_jsonl(out, system_name="vanilla", label="t", rows=rows)
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert lines[0]["type"] == "header"
    assert lines[1]["type"] == "row"
    assert lines[-1]["type"] == "footer"
