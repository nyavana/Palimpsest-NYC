"""Tests for the walk-intent classifier (§5.3).

Covers:
- All hand-labeled fixture queries in tests/fixtures/walk_intent_queries.json.
- Every Scenario in specs/agent-tools/spec.md §"Walk-intent soft hint biases
  the system prompt".
- Byte-determinism (same query → same label across two calls).
- intent_note_for("neutral") returns an empty string.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.agent.intent import (
    INTENT_NOTE_NEGATIVE,
    INTENT_NOTE_NEUTRAL,
    INTENT_NOTE_POSITIVE,
    classify_walk_intent,
    intent_note_for,
)

# ── Fixture loading ────────────────────────────────────────────────────────────

_FIXTURE_PATH = (
    pathlib.Path(__file__).parent / "fixtures" / "walk_intent_queries.json"
)


def _load_fixtures() -> list[dict]:
    with _fixture_path_open() as fh:
        return json.load(fh)


def _fixture_path_open():
    return _FIXTURE_PATH.open(encoding="utf-8")


_FIXTURES: list[dict] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


# ── Parametrized fixture test ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "item",
    _FIXTURES,
    ids=[item["query"][:60] for item in _FIXTURES],
)
def test_fixture_label(item: dict) -> None:
    """Each fixture query must map to its hand-labeled intent."""
    assert classify_walk_intent(item["query"]) == item["label"], (
        f"query={item['query']!r}  expected={item['label']!r}"
    )


# ── Spec Scenarios (explicit assertions) ──────────────────────────────────────


def test_tour_style_query_is_positive() -> None:
    """Scenario: Tour-style query gets a positive hint."""
    assert classify_walk_intent("plan a walk through Morningside Heights") == "positive"


def test_informational_query_is_negative() -> None:
    """Scenario: Informational query gets a negative hint."""
    assert (
        classify_walk_intent("tell me about the Cathedral of St. John the Divine")
        == "negative"
    )


def test_ambiguous_query_is_neutral() -> None:
    """Scenario: Ambiguous query gets a neutral hint and no NOTE line."""
    assert classify_walk_intent("Cathedral of St. John the Divine") == "neutral"


def test_neutral_intent_note_is_empty() -> None:
    """intent_note_for("neutral") must return an empty string (no NOTE line)."""
    assert intent_note_for("neutral") == ""
    assert INTENT_NOTE_NEUTRAL == ""


# ── Byte-determinism ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "plan a walk through Morningside Heights",
        "tell me about the Cathedral of St. John the Divine",
        "Cathedral of St. John the Divine",
        "from Riverside Church to Grant's Tomb",
        "what is Riverside Church?",
        "interesting places near Columbia University",
    ],
)
def test_classification_is_deterministic(query: str) -> None:
    """Same query must return the same label on every call (byte-deterministic)."""
    assert classify_walk_intent(query) == classify_walk_intent(query)


# ── intent_note_for helper ────────────────────────────────────────────────────


def test_intent_note_for_positive() -> None:
    note = intent_note_for("positive")
    assert note == INTENT_NOTE_POSITIVE
    assert "route" in note.lower() or "plan_walk" in note


def test_intent_note_for_negative() -> None:
    note = intent_note_for("negative")
    assert note == INTENT_NOTE_NEGATIVE
    assert "plan_walk" in note


def test_intent_note_for_neutral() -> None:
    assert intent_note_for("neutral") == ""


# ── Additional edge-case coverage ─────────────────────────────────────────────


def test_from_x_to_y_is_positive() -> None:
    """The 'from X to Y' directional framing is positive regardless of walk keywords."""
    assert classify_walk_intent("from Grant's Tomb to the Cathedral") == "positive"
    assert classify_walk_intent("from Morningside Park to Riverside Church") == "positive"


def test_keyword_case_insensitive() -> None:
    """Walk-intent keywords are case-insensitive."""
    assert classify_walk_intent("WALK around Morningside Heights") == "positive"
    assert classify_walk_intent("Give me a TOUR of Columbia") == "positive"
    assert classify_walk_intent("ITINERARY for the afternoon") == "positive"


def test_informational_prefix_case_insensitive() -> None:
    """Informational prefixes are case-insensitive."""
    assert classify_walk_intent("TELL ME about the Cathedral") == "negative"
    assert classify_walk_intent("WHAT IS the Cathedral?") == "negative"
    assert classify_walk_intent("DESCRIBE the architecture") == "negative"


def test_walk_keyword_takes_priority_over_informational_prefix() -> None:
    """A query that starts with an informational prefix but contains a walk keyword
    is still positive — the positive check runs first."""
    # "tell me from a historical perspective" would be negative (no keyword).
    assert classify_walk_intent("tell me about a walk through Morningside Heights") == "positive"


def test_from_to_historical_perspective_is_negative() -> None:
    """'from a historical perspective' does NOT match 'from X to Y' because
    'to Y' requires a non-whitespace token after 'to', and the phrase
    'from a historical perspective' has no 'to' clause at all."""
    result = classify_walk_intent("tell me from a historical perspective about the Cathedral")
    # No walk keyword, no 'from X to Y', starts with "tell me" → negative.
    assert result == "negative"


def test_partial_word_no_match() -> None:
    """Partial matches inside other words must not trigger positive classification."""
    # "routing" contains "route" as a substring but NOT at a word boundary from the end.
    # Python's \b matches between \w and \W; "routing" → no \b after "route".
    assert classify_walk_intent("I'm interested in routing algorithms") == "neutral"


def test_informational_prefix_only_at_start() -> None:
    """An informational prefix embedded in the middle of a sentence is not negative."""
    assert classify_walk_intent("The guide will tell me about this later") == "neutral"


def test_who_was_is_negative() -> None:
    assert classify_walk_intent("who was buried at Grant's Tomb?") == "negative"


def test_why_is_negative() -> None:
    assert classify_walk_intent("why was Riverside Church built?") == "negative"


def test_when_is_negative() -> None:
    assert classify_walk_intent("when was the Cathedral founded?") == "negative"


def test_fixture_count_per_label() -> None:
    """Sanity check: fixture has ~10 entries per label."""
    labels = [item["label"] for item in _FIXTURES]
    for label in ("positive", "negative", "neutral"):
        count = labels.count(label)
        assert count >= 9, f"Expected >=9 fixtures for label={label!r}, got {count}"
