"""Tests for the OSRM maneuver → English step formatter.

The formatter is fully deterministic and offline — no network or LLM is
involved — so the tests are pure-Python over fixture maneuver dicts.
The contract surface is the closed phrase set in the route-planning
spec; the scenarios below cover each branch of that set.
"""

from __future__ import annotations

from app.routing.steps import format_step, should_keep_step

# ── depart ─────────────────────────────────────────────────────────


def test_depart_renders_cardinal_street_and_rounded_distance():
    """Spec scenario: depart bearing renders cardinal + name + rounded distance."""
    out = format_step(
        {"type": "depart", "bearing_after": 90},
        name="West 110th Street",
        distance_m=82,
    )
    assert out == "Head east on West 110th Street for 80 m"


def test_depart_north_bearing():
    out = format_step(
        {"type": "depart", "bearing_after": 0},
        name="Broadway",
        distance_m=42,
    )
    # 42 → 40 (rounded to nearest 5)
    assert out == "Head north on Broadway for 40 m"


def test_depart_with_missing_bearing_falls_back_gracefully():
    out = format_step(
        {"type": "depart"},
        name="Riverside Drive",
        distance_m=30,
    )
    # Defensive fallback uses "north" rather than crashing.
    assert "Head" in out
    assert "Riverside Drive" in out
    assert out.endswith("30 m")


def test_depart_southwest_bearing_rounds_to_nearest_45():
    """Bearing 220 falls in the SW bucket (centered on 225)."""
    out = format_step(
        {"type": "depart", "bearing_after": 220},
        name="Amsterdam Avenue",
        distance_m=150,
    )
    assert out == "Head southwest on Amsterdam Avenue for 150 m"


# ── continue ───────────────────────────────────────────────────────


def test_continue_renders_with_street_and_distance():
    out = format_step(
        {"type": "continue"},
        name="Broadway",
        distance_m=235,
    )
    # 235 → 235 (already a multiple of 5)
    assert out == "Continue on Broadway for 235 m"


def test_new_name_renders_as_continue():
    """OSRM emits `new name` when the road name changes mid-segment;
    the formatter renders it identically to `continue`."""
    out = format_step(
        {"type": "new name"},
        name="West 113th Street",
        distance_m=100,
    )
    assert out == "Continue on West 113th Street for 100 m"


# ── turn ───────────────────────────────────────────────────────────


def test_turn_left_renders_modifier_and_street():
    out = format_step(
        {"type": "turn", "modifier": "left"},
        name="Amsterdam Avenue",
        distance_m=10,
    )
    assert out == "Turn left onto Amsterdam Avenue"


def test_turn_sharp_right_renders_with_modifier():
    out = format_step(
        {"type": "turn", "modifier": "sharp right"},
        name="Riverside Drive",
        distance_m=5,
    )
    assert out == "Turn sharp right onto Riverside Drive"


def test_turn_uturn_renders_as_make_a_uturn():
    out = format_step(
        {"type": "turn", "modifier": "uturn"},
        name="Broadway",
        distance_m=50,
    )
    assert out == "Make a U-turn onto Broadway"


# ── arrive ─────────────────────────────────────────────────────────


def test_arrive_step_renders_destination_name():
    """Spec scenario: arrive step renders 'Arrive at <name>'."""
    out = format_step(
        {"type": "arrive"},
        name="Cathedral of St. John the Divine",
        distance_m=0,
    )
    assert out == "Arrive at Cathedral of St. John the Divine"


def test_arrive_with_missing_name_falls_back():
    out = format_step({"type": "arrive"}, name=None, distance_m=0)
    assert out == "Arrive at your destination"


# ── drop rule (should_keep_step) ───────────────────────────────────


def test_drop_rule_keeps_depart_at_zero_distance():
    """Spec scenario: depart never drops regardless of distance."""
    assert should_keep_step("depart", 0) is True
    assert should_keep_step("depart", 1) is True


def test_drop_rule_keeps_arrive_at_zero_distance():
    """Spec scenario: arrive never drops regardless of distance."""
    assert should_keep_step("arrive", 0) is True
    assert should_keep_step("arrive", 1) is True


def test_drop_rule_drops_tiny_intermediate_step():
    """Spec scenario: tiny intermediate steps (<5 m) drop."""
    assert should_keep_step("continue", 2) is False
    assert should_keep_step("turn", 4) is False
    assert should_keep_step("new name", 0) is False


def test_drop_rule_keeps_steps_at_or_above_5m():
    assert should_keep_step("continue", 5) is True
    assert should_keep_step("turn", 100) is True


# ── distance rounding ──────────────────────────────────────────────


def test_distance_rounds_to_nearest_5m():
    out = format_step(
        {"type": "continue"},
        name="Broadway",
        distance_m=82,
    )
    assert "80 m" in out


def test_distance_rounds_up_at_half_threshold():
    """3 → 5 (round-half-to-even, but Python's bankers rounding makes 2.5 → 2,
    so we test a clearly-rounding-up case; 7.5 → 10, 8 → 10)."""
    out = format_step({"type": "continue"}, name="Broadway", distance_m=8)
    assert "10 m" in out


def test_distance_zero_renders_zero():
    out = format_step({"type": "continue"}, name="Broadway", distance_m=0)
    assert "0 m" in out


# ── determinism ────────────────────────────────────────────────────


def test_format_step_is_deterministic_byte_equal():
    """Spec scenario: calling format_step twice with identical input
    yields byte-equal strings."""
    args = ({"type": "depart", "bearing_after": 45}, "Broadway", 100)
    assert format_step(*args) == format_step(*args)


def test_format_step_no_state_between_calls():
    """The formatter must not carry state across calls — calling with one
    set of inputs then another must not contaminate the second."""
    a = format_step({"type": "depart", "bearing_after": 90}, "X", 50)
    _ = format_step({"type": "turn", "modifier": "left"}, "Y", 20)
    a_again = format_step({"type": "depart", "bearing_after": 90}, "X", 50)
    assert a == a_again


# ── unknown maneuver types (defensive) ─────────────────────────────


def test_unknown_maneuver_type_does_not_crash():
    """OSRM's maneuver type set is closed but new versions could add
    types; the formatter must remain readable rather than crashing."""
    out = format_step(
        {"type": "rotary", "modifier": "left"},
        name="Columbus Circle",
        distance_m=40,
    )
    assert "40 m" in out
    assert "Columbus Circle" in out
