"""v2 eval orchestrator. Reads systems.yaml + a question file, dispatches each
question to each system, writes one JSONL per system.

Palimpsest configurations require the API container to be running with the
matching RETRIEVAL_MODE env — this orchestrator does NOT swap container env.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from docs.eval.scripts.baselines.naive_rag import run_naive_rag
from docs.eval.scripts.baselines.palimpsest import run_palimpsest
from docs.eval.scripts.baselines.vanilla_llm import run_vanilla
from docs.eval.scripts.document_client import DocumentClient
from docs.eval.scripts.openrouter_client import OpenRouterChatClient
from docs.eval.scripts.retrieve_client import InternalRetrieveClient


async def dispatch_system(
    *,
    system: dict[str, Any],
    question: str,
    chat_client: Any,
    retrieve_client: Any,
    api_http_client: httpx.AsyncClient | None,
    doc_client: Any | None = None,
) -> dict[str, Any]:
    kind = system.get("kind")
    if kind == "vanilla_llm":
        return await run_vanilla(
            question=question, model=system["model"],
            chat_client=chat_client, temperature=float(system.get("temperature", 0.0)),
        )
    if kind == "naive_rag":
        return await run_naive_rag(
            question=question, model=system["model"],
            chat_client=chat_client, retrieve_client=retrieve_client,
            top_k=int(system.get("retrieve_top_k", 8)),
            temperature=float(system.get("temperature", 0.0)),
        )
    if kind == "palimpsest":
        if api_http_client is None or doc_client is None:
            raise ValueError("palimpsest dispatch requires api_http_client and doc_client")
        return await run_palimpsest(
            question=question,
            api_http_client=api_http_client,
            doc_client=doc_client,
            system_name=system["name"],
            retrieval_mode=system.get("retrieval_mode", "unknown"),
        )
    raise ValueError(f"unknown system kind: {kind!r}")


def write_run_jsonl(
    out_path: Path, *, system_name: str, label: str, rows: list[dict[str, Any]]
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "type": "header", "system": system_name, "label": label,
            "started_at": started_at, "n_rows": len(rows),
        }) + "\n")
        for i, r in enumerate(rows):
            fh.write(json.dumps({**r, "type": "row", "index": i}) + "\n")
        fh.write(json.dumps({
            "type": "footer", "system": system_name, "label": label,
            "ended_at": time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime()),
        }) + "\n")


def _read_questions(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


async def _run_one_system(
    system: dict[str, Any], questions: list[str],
    *, chat_client: Any, retrieve_client: Any,
    api_http_client: httpx.AsyncClient | None,
    doc_client: Any | None,
    out_path: Path, label: str,
) -> None:
    # Incremental write: open the file once, emit header + each row as it's
    # produced, then footer at the end. If the process is killed mid-run, we
    # keep N-1 rows on disk — and `--resume` can detect the partial state.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Resume support: if file exists and looks well-formed up through some
    # rows, skip ahead. We detect by counting existing `type=row` lines.
    skip = 0
    if out_path.exists():
        try:
            existing = [
                json.loads(l) for l in out_path.read_text().splitlines() if l.strip()
            ]
            skip = sum(1 for l in existing if l.get("type") == "row")
            # If footer present, this system already complete; bail early.
            if any(l.get("type") == "footer" for l in existing):
                print(
                    f"  [{system['name']}] already complete (rows={skip}); skipping",
                    flush=True,
                )
                return
        except (json.JSONDecodeError, OSError):
            skip = 0  # malformed file; start over below
    started_at = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    mode = "a" if skip > 0 else "w"
    with out_path.open(mode, encoding="utf-8") as fh:
        if skip == 0:
            fh.write(json.dumps({
                "type": "header", "system": system["name"], "label": label,
                "started_at": started_at, "n_rows": len(questions),
            }) + "\n")
            fh.flush()
        elif skip:
            print(f"  [{system['name']}] resuming after row {skip}", flush=True)
        for i, q in enumerate(questions, 1):
            if i <= skip:
                continue
            print(f"  [{system['name']} {i}/{len(questions)}] {q[:70]}", flush=True)
            row = await dispatch_system(
                system=system, question=q, chat_client=chat_client,
                retrieve_client=retrieve_client, api_http_client=api_http_client,
                doc_client=doc_client,
            )
            fh.write(json.dumps({**row, "type": "row", "index": i - 1}) + "\n")
            fh.flush()
            await asyncio.sleep(0.5)
        fh.write(json.dumps({
            "type": "footer", "system": system["name"], "label": label,
            "ended_at": time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime()),
        }) + "\n")


async def run(systems_yaml: Path, questions_path: Path, label: str, out_dir: Path) -> None:
    cfg = yaml.safe_load(systems_yaml.read_text())
    questions = _read_questions(questions_path)
    or_base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    api_base = os.environ.get("API_BASE_URL", "http://localhost:8000")

    async with httpx.AsyncClient(base_url=or_base, timeout=120.0) as or_http, \
               httpx.AsyncClient(base_url=api_base, timeout=300.0) as api_http:
        chat = OpenRouterChatClient(http_client=or_http, api_key=or_key)
        retrieve = InternalRetrieveClient(http_client=api_http)
        doc_client = DocumentClient(http_client=api_http)
        for system in cfg["systems"]:
            out = out_dir / f"{label}-{system['name']}.jsonl"
            await _run_one_system(
                system, questions, chat_client=chat, retrieve_client=retrieve,
                api_http_client=api_http, doc_client=doc_client,
                out_path=out, label=label,
            )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--systems", type=Path, required=True)
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--out", type=Path, default=Path("docs/eval/results"))
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    asyncio.run(run(args.systems, args.questions, args.label, args.out))


if __name__ == "__main__":
    main()
