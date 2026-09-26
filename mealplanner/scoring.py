"""The selector's scoring shapes, shared by the selector and the planner.

These lived in scripts/11c_simple_selector.py, which made a demo script the
library the rest of the code imported from. The planner (mealplanner/planning)
must score a meal exactly the way the selector does, so the shapes live here
once and both import them.
"""

from __future__ import annotations

VARIETY_CAP_DAYS = 14.0
WASTE_URGENCY_WINDOW_DAYS = 5.0


def number(value, default: float) -> float:
    """`default` only when the value is MISSING. `value or default` also
    replaced a legitimate 0 -- a zero weight (ignore this term) became 0.5,
    and a zero time budget became 60 -- which is domain data being overwritten
    by a fallback (found by external review)."""
    return default if value is None else value


def time_fit_score(duration_minutes: float | None, budget_minutes: float) -> float:
    """1 within the budget, falling linearly to 0 at twice the budget. An unknown
    duration is neutral (0.5), neither a penalty nor a reward."""
    if duration_minutes is None:
        return 0.5
    if duration_minutes <= budget_minutes:
        return 1.0
    if budget_minutes <= 0:
        return 0.0  # any time at all overshoots a zero budget; don't divide by it
    overage = duration_minutes - budget_minutes
    return max(0.0, 1.0 - overage / budget_minutes)


def nutrition_fit_score(actual: float, min_val: float | None, max_val: float | None) -> float:
    """1 inside [min, max]; falling linearly with the relative deviation outside."""
    if min_val is not None and actual < min_val:
        return max(0.0, 1.0 - (min_val - actual) / min_val) if min_val else 0.0
    if max_val is not None and actual > max_val:
        return max(0.0, 1.0 - (actual - max_val) / max_val) if max_val else 0.0
    return 1.0


def variety_bonus(days_to_nearest_use: float | None) -> float:
    """1.0 for a recipe with no other use within the cap, else the distance in
    days to the nearest other use over VARIETY_CAP_DAYS (see
    scripts/11c_simple_selector.variety_score for what counts as a use)."""
    if days_to_nearest_use is None:
        return 1.0
    return min(1.0, days_to_nearest_use / VARIETY_CAP_DAYS)


def waste_urgency(days_until_expiry: float | None) -> float:
    """How urgently stock expiring in this many days wants using: 1 today,
    falling linearly to 0 at WASTE_URGENCY_WINDOW_DAYS; 0 if already expired
    or unknown."""
    if days_until_expiry is None or days_until_expiry < 0:
        return 0.0
    return max(0.0, 1.0 - days_until_expiry / WASTE_URGENCY_WINDOW_DAYS)
