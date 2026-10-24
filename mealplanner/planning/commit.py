"""A chosen plan as MealPlanEntries (docs/optimizer-design.md Sec 4.8).

Nothing is written until this is called, and only a plan that meets every hard
constraint should be: the caller checks `evaluation.feasible`. The entries it
makes are ordinary ones, checked by the model's own write-time validators
(invariant 7: a fresh entry references a Plan and states planned servings; a
leftover entry only names its source).

The servings a fresh cook is planned for are derived: what is eaten at that slot
plus what the leftover slots pointing at it eat. Entries are upserted by name, so
running the same plan twice is harmless. In a household's week each entry also gets
a MealShare per person who eats it: who, and how many servings (data-model.md Sec 19 K3).

A dish made at a prep session (docs/optimizer-design.md Sec 12) is an entry at the
session, "<session> -- <recipe> (<meal>)", cooking all its servings and eaten by no
one; the meal it was picked for, and every meal eating its leftovers, are leftover
entries of it.
"""

from __future__ import annotations

from datetime import timedelta, timezone

from mealplanner.nutrition_scope import DEFAULT_SERVINGS_EATEN
from mealplanner.planning.evaluate import Evaluation, resolve
from mealplanner.planning.model import PlanningProblem

FMT = "%Y-%m-%dT%H:%M:%S+0000"
DEFAULT_COOK_MINUTES = 60.0


def commit_plan(client, meal_plan_id: str, problem: PlanningProblem, evaluation: Evaluation, *, name_prefix: str = "",
                missing_targets_ok: bool = False) -> list[str]:
    """Create the MealPlanEntries for the open slots of `evaluation` and return
    their ids in slot order. missing_targets_ok: the plan may miss hard nutrition
    targets, as one keeping the owner's requests may (plan.keeps_requests); it must
    still be legal and cook every request."""
    allowed = missing_targets_ok and evaluation.legal and not any(v.kind == "not_cooked" for v in evaluation.violations)
    if not (evaluation.feasible or allowed):
        raise ValueError("refusing to commit a plan that is not legal and feasible: " + "; ".join(evaluation.problems or ["hard constraint violated"]))
    resolved, cooked = resolve(problem, list(evaluation.picks))
    entry_ids = {i: slot.fixed.entry_id for i, slot in enumerate(problem.slots) if slot.fixed and slot.fixed.entry_id}
    cooked_by = dict(entry_ids)      # slot -> the entry its leftovers come from: a prep session's, for a dish made there
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
        if r.kind == "cook" and r.prep is not None:
            session = problem.preps[r.prep]
            prep_name = f"{name_prefix}{session.key} -- {recipe.name} ({slot.key})"
            prep_region = client.upsert("TemporalRegion", "name", f"{prep_name} region", {
                "hasBeginning": session.start.astimezone(timezone.utc).strftime(FMT),
                "hasEnd": (session.start + timedelta(minutes=recipe.minutes or DEFAULT_COOK_MINUTES)).astimezone(timezone.utc).strftime(FMT),
            })
            nobody = client.upsert("QuantitySpecification", "name", f"{prep_name} servings eaten", {
                "value": 0.0, "unit": "servings", "status": "specified"})
            cooked_by[i] = client.upsert("MealPlanEntry", "name", prep_name, {
                "memberOf": meal_plan_id, "isAbout": prep_region, "isSkipped": False, "references": r.candidate,
                "hasPlannedServings": cooked[i], "hasPlannedConsumption": nobody})
            created.append(cooked_by[i])
            fields["consumesLeftoverFrom"] = cooked_by[i]
        elif r.kind == "cook":
            fields["references"] = r.candidate
            fields["hasPlannedServings"] = cooked[i]
        else:
            if r.source not in cooked_by:
                raise ValueError(f"{slot.key}: its leftover source has no entry to point at")
            fields["consumesLeftoverFrom"] = cooked_by[r.source]
        if abs(r.eaten - DEFAULT_SERVINGS_EATEN) > 1e-9:
            fields["hasPlannedConsumption"] = client.upsert("QuantitySpecification", "name", f"{name} servings eaten", {
                "value": r.eaten, "unit": "servings", "status": "specified"})
        entry_ids[i] = client.upsert("MealPlanEntry", "name", name, fields)
        cooked_by.setdefault(i, entry_ids[i])
        created.append(entry_ids[i])
        if problem.eaters:
            for eater, servings in r.shares:
                who = problem.eater_label(eater)
                qty = client.upsert("QuantitySpecification", "name", f"{name} -- {who} servings", {
                    "value": servings, "unit": "servings", "status": "specified"})
                client.upsert("MealShare", "name", f"{name} -- {who}", {
                    "shareOf": entry_ids[i], "eatenBy": eater, "hasPlannedConsumption": qty})
    return created
