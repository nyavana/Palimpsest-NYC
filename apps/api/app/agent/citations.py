"""Citation contract: parse narration response → verify against retrieval ledger.

Single source of truth for the locked V1 contract from `agent-tools/spec.md`.
The verifier is intentionally strict: its job is to fail closed on any of
the documented rejection scenarios so the agent loop's one-retry-then-warn
flow has a clean signal to act on.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

V1_SOURCE_TYPES = frozenset({"wikipedia", "wikidata", "osm"})


class CitationError(ValueError):
    """Raised when the narration response is malformed or fails verification."""


# ── Parsed response shape ───────────────────────────────────────────


@dataclass(slots=True)
class Citation:
    doc_id: str
    source_url: str
    source_type: str
    span: str
    retrieval_turn: int


@dataclass(slots=True)
class NarrationResponse:
    narration: str
    citations: list[Citation]


# ── Retrieval ledger ────────────────────────────────────────────────


@dataclass
class _LedgerEntry:
    doc_id: str
    source_type: str
    source_url: str


@dataclass
class RetrievalLedger:
    """Records what each retrieval turn returned.

    The agent loop appends a turn's hits here right after dispatching a tool
    call. The verifier asks `is_known(doc_id)`, then cross-checks
    source_type / source_url consistency against what was actually retrieved.
    """

    by_turn: dict[int, list[_LedgerEntry]] = field(default_factory=dict)

    def add(self, *, turn: int, hits: Iterable[dict[str, Any]]) -> None:
        normalized = [
            _LedgerEntry(
                doc_id=hit["doc_id"],
                source_type=hit["source_type"]
                if isinstance(hit["source_type"], str)
                else getattr(hit["source_type"], "value", str(hit["source_type"])),
                source_url=hit["source_url"],
            )
            for hit in hits
        ]
        self.by_turn.setdefault(turn, []).extend(normalized)

    def lookup(self, doc_id: str, *, on_or_before_turn: int) -> _LedgerEntry | None:
        for t in sorted(self.by_turn.keys()):
            if t > on_or_before_turn:
                break
            for entry in self.by_turn[t]:
                if entry.doc_id == doc_id:
                    return entry
        return None


# ── Parsing ─────────────────────────────────────────────────────────


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> str:
    """Find the first balanced JSON object in `text`. LLMs sometimes wrap
    JSON in prose, ```json fences, or apologies; this strips that wrapping.
    """
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    match = _JSON_OBJECT_RE.search(text)
    if match is None:
        raise CitationError("response does not contain a JSON object")
    return match.group(0)


def parse_narration_response(text: str) -> NarrationResponse:
    """Parse the LLM's terminal response into a typed NarrationResponse.

    Raises `CitationError` for any structural failure — the agent loop turns
    that into a one-shot retry with a corrective system message.
    """
    raw = _extract_json(text)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CitationError(f"narration response is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise CitationError("narration response is not a JSON object")
    if "narration" not in obj:
        raise CitationError("narration response missing required field: narration")
    if "citations" not in obj:
        raise CitationError("narration response missing required field: citations")
    if not isinstance(obj["citations"], list):
        raise CitationError("'citations' must be a JSON array")

    citations: list[Citation] = []
    for i, c in enumerate(obj["citations"]):
        if not isinstance(c, dict):
            raise CitationError(f"citation #{i} is not an object")
        try:
            citations.append(
                Citation(
                    doc_id=str(c["doc_id"]),
                    source_url=str(c["source_url"]),
                    source_type=str(c["source_type"]),
                    span=str(c.get("span", "")),
                    retrieval_turn=int(c["retrieval_turn"]),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise CitationError(f"citation #{i} is missing or malformed: {exc}") from exc

    return NarrationResponse(narration=str(obj["narration"]), citations=citations)


# ── Verifier ────────────────────────────────────────────────────────


def verify_citations(
    response: NarrationResponse,
    *,
    ledger: RetrievalLedger,
    current_turn: int,
) -> None:
    """Apply the locked V1 contract. Raises `CitationError` on rejection.

    Per spec rules (in order, fail-fast):
      - narration non-empty
      - citations non-empty
      - each citation: doc_id known to ledger on or before retrieval_turn
      - source_type matches ledger entry's source_type
      - source_url matches ledger entry's source_url
      - source_type ∈ V1 enum
      - retrieval_turn ≤ current_turn (no future references)
      - source_url is https://
      - span is a string (opaque — we do NOT validate its content)
    """
    if not response.narration.strip():
        raise CitationError("narration is empty — uncited narration is forbidden")
    if not response.citations:
        raise CitationError("citations is empty — uncited narration is forbidden")

    for i, c in enumerate(response.citations):
        if not isinstance(c.span, str):
            raise CitationError(f"citation #{i}: span must be a string (opaque)")
        if c.source_type not in V1_SOURCE_TYPES:
            raise CitationError(
                f"citation #{i}: source_type {c.source_type!r} not in V1 enum "
                f"{sorted(V1_SOURCE_TYPES)}"
            )
        if not c.source_url.startswith("https://"):
            raise CitationError(
                f"citation #{i}: source_url must be https:// (got {c.source_url!r})"
            )
        if c.retrieval_turn > current_turn:
            raise CitationError(
                f"citation #{i}: future retrieval_turn={c.retrieval_turn} "
                f"exceeds current_turn={current_turn}"
            )
        entry = ledger.lookup(c.doc_id, on_or_before_turn=c.retrieval_turn)
        if entry is None:
            raise CitationError(
                f"citation #{i}: doc_id {c.doc_id!r} was not retrieved "
                f"on or before turn {c.retrieval_turn}"
            )
        if entry.source_type != c.source_type:
            raise CitationError(
                f"citation #{i}: source_type mismatch — citation says "
                f"{c.source_type!r}, retrieved row says {entry.source_type!r}"
            )
        if entry.source_url != c.source_url:
            raise CitationError(
                f"citation #{i}: source_url mismatch for {c.doc_id!r}"
            )
