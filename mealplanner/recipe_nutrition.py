"""A recipe version's nutrition per serving, worked out once and stored (data-model.md Sec 18 J28).

The owner decided (2026-10-22) to store it. Working each recipe's figures out from its
ingredients every time a week is planned read every ingredient's profiles, densities and
retention factors for every nutrient of every recipe: on the owner's 40 recipes that was
most of a 169 s read, and it grows with every recipe and every food. So each Plan (one
version of a recipe) keeps one NutrientProfile per targeted nutrient, basis `per_serving`,
`servingOf` the Plan, holding what nutrition_scope.serving_nutrient_figure works out
(stored_fields):

    provenance calculated    a figure on published data throughout
    provenance estimated     one that rests on an estimate; `source` says which (J21)
    provenance placeholder   one that rests on placeholder or unmarked data; `source` says so
    no amount                an unknown figure; `source` says why

Which nutrients: every nutrient a NutritionTarget is about, in the unit of the first target
on it by name. A stored figure for a nutrient no target is about any more is deleted, since
nothing would keep it current.

When: whatever changes what a figure rests on works it out again. tools/import_recipe.py
does it for the recipes it loads, tools/import_vocabulary.py for the recipes using a food
whose profiles, density, weight per item, retention factors or place in the hierarchy
changed (plans_using), and tools/calculate_recipe_nutrition.py by hand; its --check works every figure out again and
lists the stored ones that differ. A change made in Structr's own pages is not seen until
one of them runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mealplanner.material_accounting import plan_specifications
from mealplanner.nutrition_scope import (
    SERVING_BASIS, NutrientUnitError, ServingFigure, nutrient_unit, serving_nutrient_figure, stored_figure,
    stored_serving_profiles,
)
from mealplanner.typetree import ancestors_or_self
from structr_client import ReadCache

RELATIONSHIP = "SERVING_OF"
TOLERANCE = 1e-9            # relative: a stored amount is the same figure if it agrees this closely


@dataclass
class Report:
    plans: int = 0
    counts: dict = field(default_factory=lambda: {"created": 0, "changed": 0, "unchanged": 0, "deleted": 0})
    differences: list = field(default_factory=list)      # what --check found, in words


def schema_ready(client) -> bool:
    """Whether this instance can store them (scripts/35a)."""
    return bool(client.get("/structr/rest/SchemaRelationshipNode", params={"relationshipType": RELATIONSHIP})["result"])


def targeted_nutrients(client) -> dict[str, tuple[str, str]]:
    """{nutrient id: (name, unit)} for every nutrient a NutritionTarget is about, in the unit
    of the first target on it by name. A target whose range is in no nutrient unit is the
    planner's to report, not this."""
    out: dict[str, tuple[str, str]] = {}
    for target in sorted(client.get_all("NutritionTarget")["result"], key=lambda t: (t.get("name") or "", t["id"])):
        nutrient, rng = target.get("forNutrient"), target.get("hasTargetRange")
        if not nutrient or not rng or nutrient["id"] in out:
            continue
        unit = client.get_all("QuantitySpecification", rng["id"])["result"].get("unit")
        try:
            nutrient_unit(unit)
        except NutrientUnitError:
            continue
        out[nutrient["id"]] = (nutrient.get("name") or nutrient["id"], unit)
    return out


def stored_fields(figure: ServingFigure, unit: str) -> dict:
    """The fields a stored profile holds for a worked-out figure; nutrition_scope.stored_figure
    reads them back into the same figure."""
    if figure.amount is None:
        return {"amount": None, "unit": unit, "provenance": "calculated", "source": figure.reason or "unknown"}
    if not figure.trusted:
        return {"amount": figure.amount, "unit": unit, "provenance": "placeholder", "source": figure.reason}
    if figure.estimated:
        return {"amount": figure.amount, "unit": unit, "provenance": "estimated", "source": figure.reason}
    whence = "the dish's own profiles" if figure.method == "dish" else "its ingredients"
    return {"amount": figure.amount, "unit": unit, "provenance": "calculated", "source": f"worked out from {whence}"}


def _same_figure(stored: ServingFigure | None, worked: ServingFigure) -> bool:
    if stored is None:
        return False
    if (stored.amount is None) != (worked.amount is None):
        return False
    if stored.amount is not None and abs(stored.amount - worked.amount) > TOLERANCE * max(1.0, abs(worked.amount)):
        return False
    return (stored.trusted, stored.estimated, stored.reason) == (worked.trusted, worked.estimated, worked.reason)


def _differs(row: dict, fields: dict) -> dict:
    out = {}
    for key, value in fields.items():
        current = row.get(key)
        if isinstance(value, float) and isinstance(current, (int, float)):
            if abs(current - value) <= TOLERANCE * max(1.0, abs(value)):
                continue
        elif current == value:
            continue
        out[key] = value
    return out


def plans_using(client, type_ids) -> list[str]:
    """The ids of the Plans whose figures may rest on any of these food Types: a Plan with a
    Specification about one of them or about a Type below one, since a density, a weight per
    item or a retention factor resolves up the hierarchy (defaults.py), though a profile does
    not. Every Specification counts, input or output, optional or not: a recipe worked out
    again for nothing costs less than one left stale."""
    changed = set(type_ids)
    if not changed:
        return []
    reads = ReadCache(client)
    reads.prefetch("Plan", "Step", "Specification", "DomainType")
    below: dict[str, bool] = {}

    def rests_on(spec: dict) -> bool:
        type_id = (spec.get("specifies") or {}).get("id")
        if type_id is None:
            return False
        if type_id not in below:
            below[type_id] = not changed.isdisjoint(ancestors_or_self(reads, type_id))
        return below[type_id]

    return sorted(plan["id"] for plan in reads.get_all("Plan")["result"]
                  if any(rests_on(spec) for spec in plan_specifications(reads, plan)))


def calculate(client, plan_ids: list[str] | None = None, *, check: bool = False) -> Report:
    """Work out every Plan's figures (or these Plans') and store them. With check, store
    nothing: list each targeted nutrient whose stored figure is missing or differs from
    what it works out to now, and each stored for a nutrient no target is about."""
    reads = ReadCache(client)                     # computing reads only; the writes go to `client`
    reads.prefetch("NutrientProfile", "Specification", "QuantitySpecification", "DomainType")
    nutrients = targeted_nutrients(reads)
    if plan_ids is None:
        plans = reads.get_all("Plan")["result"]
    else:
        plans = [reads.get_all("Plan", pid)["result"] for pid in plan_ids]
    report = Report(plans=len(plans))
    for plan in sorted(plans, key=lambda p: (p["name"], p["id"])):
        kept = dict(stored_serving_profiles(reads, plan))
        for nutrient_id, (name, unit) in nutrients.items():
            worked = serving_nutrient_figure(reads, plan, nutrient_id, unit, stored=False)
            rows = kept.pop(nutrient_id, [])
            if check:
                stored = stored_figure(reads, plan, nutrient_id, unit)
                if not _same_figure(stored, worked):
                    report.differences.append(f"{plan['name']}: {name}: stored {_words(stored)}, works out to {_words(worked)}")
                continue
            fields = stored_fields(worked, unit)
            for extra in rows[1:]:
                client.delete(f"/structr/rest/NutrientProfile/{extra['id']}")
                report.counts["deleted"] += 1
            if rows:
                diff = _differs(rows[0], fields)
                if diff:
                    client.patch(f"/structr/rest/NutrientProfile/{rows[0]['id']}", diff)
                    report.counts["changed"] += 1
                else:
                    report.counts["unchanged"] += 1
                continue
            payload = {k: v for k, v in fields.items() if v is not None}
            payload.update(name=f"{plan['name']} -- {name} per serving", basis=SERVING_BASIS, forNutrient=nutrient_id,
                           servingOf=plan["id"], visibleToAuthenticatedUsers=True, visibleToPublicUsers=False)
            client.post("/structr/rest/NutrientProfile", payload)
            report.counts["created"] += 1
        for rows in kept.values():                # nutrients no target is about any more
            for row in rows:
                if check:
                    report.differences.append(f"{plan['name']}: {row['name']} is stored, but no target is about its nutrient")
                    continue
                client.delete(f"/structr/rest/NutrientProfile/{row['id']}")
                report.counts["deleted"] += 1
    return report


def _words(figure: ServingFigure | None) -> str:
    if figure is None:
        return "nothing"
    if figure.amount is None:
        return f"unknown ({figure.reason})"
    trust = "estimated" if figure.estimated else ("trusted" if figure.trusted else "untrusted")
    return f"{figure.amount:.6g} ({trust}{'; ' + figure.reason if figure.reason else ''})"
