"""Walk-intent classifier — regex/keyword preflight that biases the
agent's system prompt without gating tool visibility.

See specs/agent-tools/spec.md::Walk-intent soft hint biases the system prompt
and design.md §11 for the canonical rules.
"""

from __future__ import annotations

import re
from typing import Literal

WalkIntent = Literal["positive", "negative", "neutral"]

# ── Compiled patterns (module-load time, no import cost at call site) ─────────

# Positive: walk-keyword OR "from X to Y" framing.
# Word boundaries prevent partial matches ("routing" → no, "route" → yes).
_POSITIVE_KEYWORD = re.compile(
    r"\b(walk|tour|route|directions|itinerary)\b",
    re.IGNORECASE,
)

# "from <non-whitespace> ... to <non-whitespace>" — captures directional intent.
# Requires at least one non-whitespace character on each side so bare
# "from to" does not match.
_POSITIVE_FROM_TO = re.compile(
    r"\bfrom\s+\S.*?\s+to\s+\S",
    re.IGNORECASE | re.DOTALL,
)

# Negative: query starts with an informational-prefix keyword.
# Anchored at the beginning of the (stripped) query.
_NEGATIVE_PREFIX = re.compile(
    r"^(tell\s+me|what\s+is|what\s+was|who\s+is|who\s+was|describe|why|when|how\s+does|how\s+is)\b",
    re.IGNORECASE,
)

# ── Intent NOTE strings (appended to the agent system prompt) ─────────────────

INTENT_NOTE_POSITIVE = (
    "NOTE: The user appears to want a route. "
    "After 1-2 search_places calls, strongly prefer calling plan_walk."
)

INTENT_NOTE_NEGATIVE = (
    "NOTE: The user appears to want information about a place. "
    "Strongly prefer NOT calling plan_walk."
)

INTENT_NOTE_NEUTRAL = ""


def intent_note_for(label: WalkIntent) -> str:
    """Return the NOTE string to append to the system prompt for *label*.

    Returns an empty string for the neutral label (nothing is appended).
    """
    if label == "positive":
        return INTENT_NOTE_POSITIVE
    if label == "negative":
        return INTENT_NOTE_NEGATIVE
    return INTENT_NOTE_NEUTRAL


# ── Public classifier ──────────────────────────────────────────────────────────


def classify_walk_intent(query: str) -> WalkIntent:
    """Classify *query* as ``"positive"``, ``"negative"``, or ``"neutral"``.

    Rules (evaluated in order; first match wins):

    1. **positive** — query contains a walk-keyword
       ``{walk, tour, route, directions, itinerary}`` at a word boundary
       (case-insensitive), OR matches the pattern ``from <X> ... to <Y>``.
    2. **negative** — no positive pattern matched AND the query begins with one
       of the informational-prefix phrases (case-insensitive).
    3. **neutral** — neither rule fired.

    The classifier is fully deterministic and offline; it MUST NOT call any
    LLM or external service.
    """
    stripped = query.strip()

    # 1. Positive check — keyword or directional framing.
    if _POSITIVE_KEYWORD.search(stripped) or _POSITIVE_FROM_TO.search(stripped):
        return "positive"

    # 2. Negative check — informational prefix.
    if _NEGATIVE_PREFIX.match(stripped):
        return "negative"

    # 3. Neutral fallback.
    return "neutral"
