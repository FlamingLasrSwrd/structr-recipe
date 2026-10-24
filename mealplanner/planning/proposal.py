"""A proposed week, kept between proposing it and committing it (tools/plan_week.py).

The owner reviews a proposal, then commits it. Searching again to commit could give another
week, since a search under a time limit is not repeatable to the meal, so the tool keeps the week
it proposed, and --commit writes that week: read against the graph as it is then, and only if
evaluate() still finds it legal and meeting every hard target (the owner's decision, 2026-10-23).

The file names everything as the owner reads it: meals by their slot ("Mon 26 Oct Breakfast"),
recipes by name, people by name. Fixed meals (entries already in the MealPlan) are not in it; they
are read from the graph as always.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mealplanner.planning.evaluate import Evaluation, initial_partial
from mealplanner.planning.model import Pick, PlanningProblem

FORMAT = 1


class ProposalError(ValueError):
    """A saved proposal that no longer fits the week as the graph now has it."""


def to_data(problem: PlanningProblem, evaluation: Evaluation, week_start: str) -> dict:
    meals = []
    for i, (slot, pick) in enumerate(zip(problem.slots, evaluation.picks)):
        if slot.fixed is not None:
            continue
        meal: dict = {"slot": slot.key}
        if pick.candidate is not None:
            meal["cook"] = problem.candidates[pick.candidate].name
            if pick.prep is not None:
                meal["made_at"] = problem.preps[pick.prep].key
        else:
            meal["leftover_of"] = problem.slots[pick.source].key
        if pick.shares is not None:
            meal["shares"] = {problem.eater_label(e): servings for e, servings in zip(problem.slot_eaters(i), pick.shares)}
        elif pick.portion is not None:
            meal["portion"] = pick.portion
        meals.append(meal)
    return {"format": FORMAT, "week": week_start, "score": evaluation.objective,
            "proposed": datetime.now(timezone.utc).isoformat(timespec="seconds"), "meals": meals}


def picks_from(problem: PlanningProblem, data: dict) -> tuple:
    """The proposal's Picks for this problem, or ProposalError saying what no longer fits."""
    if data.get("format") != FORMAT:
        raise ProposalError(f"a proposal of format {data.get('format')!r}, not {FORMAT}")
    index = {slot.key: i for i, slot in enumerate(problem.slots)}
    sessions = {session.key: k for k, session in enumerate(problem.preps)}
    recipes: dict = {}
    for c in problem.candidates.values():
        recipes.setdefault(c.name, []).append(c.id)
    picks = initial_partial(problem)
    open_slots, problems = set(problem.open_slots()), []
    for meal in data.get("meals", []):
        key = meal.get("slot")
        i = index.get(key)
        if i is None or i not in open_slots:
            problems.append(f"{key}: no longer an open meal of this week")
            continue
        labels = {problem.eater_label(e): e for e in problem.slot_eaters(i)}
        shares = None
        if "shares" in meal:
            if set(meal["shares"]) != set(labels):
                problems.append(f"{key}: eaten by {sorted(meal['shares'])}, but the meal is now {sorted(labels)}'s")
                continue
            shares = tuple(float(meal["shares"][problem.eater_label(e)]) for e in problem.slot_eaters(i))
        portion = float(meal["portion"]) if "portion" in meal else None
        if "cook" in meal:
            ids = recipes.get(meal["cook"], [])
            if len(ids) != 1:
                problems.append(f"{key}: {meal['cook']!r} is {'not' if not ids else 'more than once'} in the recipe book now")
                continue
            prep = sessions.get(meal["made_at"]) if "made_at" in meal else None
            if "made_at" in meal and prep is None:
                problems.append(f"{key}: made at {meal['made_at']!r}, which is not a prep session of this week now")
                continue
            picks[i] = Pick(candidate=ids[0], portion=portion, shares=shares, prep=prep)
        else:
            source = index.get(meal.get("leftover_of"))
            if source is None:
                problems.append(f"{key}: its leftovers' meal {meal.get('leftover_of')!r} is not in this week")
                continue
            picks[i] = Pick(source=source, portion=portion, shares=shares)
    missing = [problem.slots[i].key for i in sorted(open_slots) if picks[i] is None]
    if missing:
        problems.append(f"not in the proposal: {', '.join(missing)}")
    if problems:
        raise ProposalError("; ".join(problems))
    return tuple(picks)
