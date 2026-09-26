"""A chosen plan as MealPlanEntries (docs/optimizer-design.md Sec 4.8).

Nothing is written until this is called, and only a plan that meets every hard
constraint should be: the caller checks `evaluation.feasible`. The entries it
makes are ordinary ones, checked by the model's own write-time validators
(invariant 7: a fresh entry references a Plan and states planned servings; a
leftover entry only names its source).

The servings a fresh cook is planned for are derived: what is eaten at that slot
plus what the leftover slots pointing at it eat. Entries are upserted by name, so
running the same plan twice is harmless.
"""

from __future__ import annotations

from datetime import timedelta, timezone

from mealplanner.nutrition_scope import DEFAULT_SERVINGS_EATEN
from mealplanner.planning.evaluate import Evaluation, resolve
from mealplanner.planning.model import PlanningProblem

FMT = "%Y-%m-%dT%H:%M:%S+0000"
DEFAULT_COOK_MINUTES = 60.0


def commit_plan(client, meal_plan_id: str, problem: PlanningProblem, evaluation: Evaluation, *, name_prefix: str = "") -> list[str]:
    """Create the MealPlanEntries for the open slots of `evaluation` and return
    their ids in slot order."""
    if not evaluation.feasible:
        raise ValueError("refusing to commit a plan that is not legal and feasible: " + "; ".join(evaluation.problems or ["hard constraint violated"]))
    resolved, cooked = resolve(problem, list(evaluation.picks))
    entry_ids = {i: slot.fixed.entry_id for i, slot in enumerate(problem.slots) if slot.fixed and slot.fixed.entry_id}
    created = []
    for i, slot in enumerate(problem.slots):
        if slot.fixed is not None:
            continue
        r = resolved[i]
        recipe = problem.candidates[r.candidate]
        name = f"{name_prefix}{slot.key} -- {recipe.name}"
        minutes = recipe.minutes if (r.kind == "cook" and recipe.minutes) else DEFAULT_COOK_MINUTES
        region = client.upsert("TemporalRegion", "name", f"{name} region", {
            "hasBeginning": slot.start.astimezone(timezone.utc).strftime(FMT),
            "hasEnd": (slot.start + timedelta(minutes=minutes)).astimezone(timezone.utc).strftime(FMT),
        })
        fields = {"memberOf": meal_plan_id, "isAbout": region, "isSkipped": False}
        if r.kind == "cook":
            fields["references"] = r.candidate
            fields["hasPlannedServings"] = cooked[i]
        else:
            if r.source not in entry_ids:
                raise ValueError(f"{slot.key}: its leftover source has no entry to point at")
            fields["consumesLeftoverFrom"] = entry_ids[r.source]
        if abs(r.eaten - DEFAULT_SERVINGS_EATEN) > 1e-9:
            fields["hasPlannedConsumption"] = client.upsert("QuantitySpecification", "name", f"{name} servings eaten", {
                "value": r.eaten, "unit": "servings", "status": "specified"})
        entry_ids[i] = client.upsert("MealPlanEntry", "name", name, fields)
        created.append(entry_ids[i])
    return created
