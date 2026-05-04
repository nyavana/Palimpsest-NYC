"""OSRM maneuver → English step formatter.

The formatter is intentionally tiny and fully deterministic — it never
calls the LLM or any external service. OSRM's structured `maneuver`
objects (`type`, `modifier`, `bearing_after`) carry enough signal to
render natural-sounding English from a closed phrase set.

Spec contract (see `openspec/changes/agent-route-planning/specs/route-planning/spec.md`):

  - `"Head <bearing-cardinal> on <street-name> for <distance> m"` for
    `maneuver.type == "depart"`.
  - `"Continue on <street-name> for <distance> m"` for
    `maneuver.type ∈ {"continue", "new name"}`.
  - `"Turn <left|right|sharp left|sharp right|slight left|slight right>
    onto <street-name>"` for `maneuver.type == "turn"`.
  - `"Arrive at <destination-name>"` for `maneuver.type == "arrive"`.

The formatter rounds DISPLAY distances to the nearest 5 m but the caller
preserves the unrounded `distance_m` integer in the resulting `Step`.
Steps shorter than 5 m are dropped UNLESS they are `depart` or `arrive`.
"""

from __future__ import annotations

# 8-way cardinal split centered on each compass arm: 0±22.5, 45±22.5, ...
# The list aligns with bearings 0, 45, 90, 135, 180, 225, 270, 315.
_CARDINALS: tuple[str, ...] = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

_TURN_PHRASE: dict[str, str] = {
    "left": "left",
    "right": "right",
    "sharp left": "sharp left",
    "sharp right": "sharp right",
    "slight left": "slight left",
    "slight right": "slight right",
    # OSRM emits "uturn" for U-turn maneuvers; render it as a turn.
    "uturn": "around",
}

_BEARING_FALLBACK = "north"

# Drop steps shorter than this (in meters) UNLESS they are depart/arrive.
# Spec: route-planning §"Step-by-step instruction generation".
_MIN_STEP_DISTANCE_M = 5

# Display rounding for distances in step instructions (meters).
_DISPLAY_ROUND_M = 5


def _bearing_to_cardinal(bearing_deg: float | None) -> str:
    """Map a compass bearing (0-360, North=0, clockwise) to an 8-way
    cardinal name suitable for inline narration.

    A `None` or out-of-range bearing falls back to "north" rather than
    erroring out — OSRM's `bearing_after` is well-defined for `depart`
    but the formatter must not crash on malformed input.
    """
    if bearing_deg is None:
        return _BEARING_FALLBACK
    # Normalize to [0, 360) then split into 8 22.5°-wide buckets.
    deg = float(bearing_deg) % 360.0
    bucket = int((deg + 22.5) // 45.0) % 8
    cardinal_short = _CARDINALS[bucket]
    return {
        "N": "north",
        "NE": "northeast",
        "E": "east",
        "SE": "southeast",
        "S": "south",
        "SW": "southwest",
        "W": "west",
        "NW": "northwest",
    }[cardinal_short]


def _round_to_5m(distance_m: int) -> int:
    """Round to the nearest 5 m. Negative inputs clamp to 0 to keep the
    rendered text well-formed."""
    if distance_m <= 0:
        return 0
    return round(distance_m / _DISPLAY_ROUND_M) * _DISPLAY_ROUND_M


def should_keep_step(maneuver_type: str, distance_m: int) -> bool:
    """V1 drop rule for tiny intermediate steps.

    `depart` and `arrive` are always retained — they bookend the route
    and dropping them would leave the user without a "you start here /
    you arrive here" anchor. Everything else with `distance_m < 5` is
    cosmetic noise and is omitted.
    """
    if maneuver_type in ("depart", "arrive"):
        return True
    return distance_m >= _MIN_STEP_DISTANCE_M


def format_step(
    maneuver: dict,
    name: str | None,
    distance_m: int,
) -> str:
    """Render an OSRM maneuver as a single English step instruction.

    Parameters mirror the OSRM step JSON:
      - `maneuver` is OSRM's `step.maneuver` dict (we read `type`,
        `modifier`, `bearing_after`).
      - `name` is OSRM's `step.name` (street name, possibly empty).
      - `distance_m` is OSRM's `step.distance` rounded to int.

    The returned string is byte-equal across calls with identical input
    — the formatter is fully deterministic.
    """
    mtype = (maneuver.get("type") or "").lower()
    modifier = (maneuver.get("modifier") or "").lower()
    bearing_after = maneuver.get("bearing_after")
    street = (name or "").strip() or "the route"
    rounded = _round_to_5m(distance_m)

    if mtype == "depart":
        cardinal = _bearing_to_cardinal(bearing_after)
        return f"Head {cardinal} on {street} for {rounded} m"

    if mtype in ("continue", "new name"):
        return f"Continue on {street} for {rounded} m"

    if mtype == "turn":
        # Special-case U-turn so the preposition reads naturally.
        if modifier == "uturn":
            return f"Make a U-turn onto {street}"
        phrase = _TURN_PHRASE.get(modifier, modifier or "right")
        return f"Turn {phrase} onto {street}"

    if mtype == "arrive":
        # `name` doubles as the destination label when the caller has it
        # (the route planner passes the final stop's display name in).
        destination = (name or "").strip() or "your destination"
        return f"Arrive at {destination}"

    # Unknown maneuver types — keep the output readable rather than
    # crashing. OSRM has a small closed set of types (~10) so this is
    # mostly a defensive fallback.
    return _format_unknown(street, rounded)


def _format_unknown(street: str, rounded: int) -> str:
    """Defensive fallback render for OSRM maneuver types not in the closed set."""
    if rounded > 0 and street != "the route":
        return f"Continue on {street} for {rounded} m"
    return f"Continue for {rounded} m"
