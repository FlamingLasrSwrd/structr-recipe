"""Small builders for planning problems, shared by the planner's tests."""

from datetime import datetime, timedelta, timezone

from mealplanner.planning.model import Candidate, Fixed, PlanningProblem, Slot, Target, Weights


def when(day: int, hour: int = 18, minute: int = 0) -> datetime:
    """Day 1 is 2026-09-01; days past the 30th roll into October."""
    return datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=day - 1, hours=hour, minutes=minute)


def cand(name: str, protein: float | None = None, minutes: float | None = None, **kw) -> Candidate:
    nutrients = dict(kw.pop("nutrients", {}))
    if protein is not None:
        nutrients["protein"] = protein
    return Candidate(id=name, name=name, minutes=minutes, nutrients=nutrients, **kw)


def slot(key: str, start, meal_type=None, fixed: Fixed | None = None) -> Slot:
    return Slot(key=key, start=start, meal_type=meal_type, fixed=fixed)


def protein_target(minimum=None, maximum=None, *, hard=True, scope="daily", weight=0.0) -> Target:
    return Target("protein target", "protein", scope, minimum, maximum, hard, weight, "Protein")


def problem(slots, candidates, targets=(), lots=(), **kw) -> PlanningProblem:
    weights = kw.pop("weights", Weights(time=0.6, variety=0.0, stock=0.0, waste=0.0, time_budget_minutes=30.0))
    return PlanningProblem(slots=tuple(slots), candidates={c.id: c for c in candidates}, targets=tuple(targets),
                           lots=tuple(lots), weights=weights, **kw)


# The one-day, three-slot case of docs/optimizer-design.md Sec 2 (protein per serving, minutes):
MEALS = (
    cand("buttered pasta", 12, 20),
    cand("veggie stir-fry", 10, 25),
    cand("omelette", 24, 35),
    cand("chicken salad", 30, 40),
    cand("braised chicken", 45, 90),
)


def day_of_three(targets, candidates=MEALS, **kw):
    return problem([slot("breakfast", when(28, 8)), slot("lunch", when(28, 12)), slot("dinner", when(28, 18))],
                   candidates, targets, **kw)
