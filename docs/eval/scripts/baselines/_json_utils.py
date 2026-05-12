"""Shared JSON pre-parse helpers for baseline LLM responses.

Some models (notably long-thinking ones like kimi-k2.6) will sometimes wrap
their JSON envelope in a markdown fence — e.g. ``` ```json\n{...}\n``` ``` —
or prepend a short preamble before the JSON, despite an explicit instruction
not to. Rather than failing the whole row with ``JSONDecodeError``, we strip
the most common wrappers and re-try ``json.loads`` upstream.

This helper is intentionally narrow:
* It only handles the cases observed in the Phase 0 smoke run.
* It does not try to repair malformed JSON — if the content is genuinely
  broken, the caller's ``json.loads`` will still raise and the row's
  ``error`` field will record it.
"""

from __future__ import annotations


def strip_json_fences(content: str) -> str:
    """Return ``content`` with surrounding markdown fences / preambles removed.

    Cases handled (in order):

    1. ``` ```json\\n{...}\\n``` ``` — fenced block tagged ``json``.
    2. ``` ```\\n{...}\\n``` ``` — plain fenced block.
    3. Leading/trailing whitespace only.
    4. A leading non-JSON preamble followed by the first ``{`` — slice from
       the first ``{`` to the matching last ``}``.

    Pure-JSON content passes through unchanged. Empty / whitespace-only input
    is returned as the empty string so ``json.loads`` raises a normal
    ``JSONDecodeError`` (not an ``AttributeError``).
    """

    if not content:
        return ""
    stripped = content.strip()
    if not stripped:
        return ""

    # Fenced block: ```json ... ``` or ``` ... ```.
    if stripped.startswith("```"):
        # Drop the opening fence line (``` or ```json[ \t]*).
        first_newline = stripped.find("\n")
        if first_newline == -1:
            # Single-line fence — nothing to recover.
            return stripped
        body = stripped[first_newline + 1 :]
        # Drop the trailing fence if present.
        if body.rstrip().endswith("```"):
            body = body.rstrip()
            body = body[: -len("```")].rstrip()
        stripped = body.strip()

    # Slice from first '{' to last '}' to drop any remaining preamble/epilogue.
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return stripped[first_brace : last_brace + 1]
    return stripped
