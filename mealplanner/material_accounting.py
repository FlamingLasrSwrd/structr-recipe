"""Fixes the headline finding from the holes-and-gaps analysis: the
yield mechanism (DefaultSpecification.hasKind=Yield) is single-input
shaped, and combination recipes -- most of real cooking -- had no way
to compute an expected output at all. Every combination recipe in this
project so far had its output quantity hand-authored (status=
"specified") rather than computed, breaking the "compute, don't store"
discipline that governs everything else.

The fix is NOT a new DefaultSpecification shape. Re-deriving from
data-model.md Sec 5.1's own formula: "expected output mass = summed
input mass x yield[transformation]" already sums inputs before
applying a factor -- the natural generalization to heterogeneous
inputs is to apply EACH input's own yield (independently resolved,
same mechanism as any single-ingredient recipe) BEFORE summing, not to
invent one combined factor. Pasta absorbing water when boiled is a
fact about pasta, not about "pasta combined with butter and parmesan"
-- it should resolve the exact same way whether pasta is boiled alone
or as part of a bigger dish. Ingredients with no yield default for the
given transformation (butter, parmesan -- they don't meaningfully
transform) correctly default to 1.0 (mass-conserving), exactly as
Sec 5.1 already specifies for the single-input case.

This means expected_combination_output() is really just the Yield
default (mealplanner/defaults.py, resolved by kind and keyedBy) applied per
input and summed -- no new relations, no schema change, just the existing
mechanism used correctly for N inputs instead of assumed to only ever see one.
"""

from __future__ import annotations

from mealplanner.defaults import resolve_default
from mealplanner.unit_conversion import QuantityError, convert_to_grams


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def resolve_yield_or_default(client, input_type_id: str, transformation_kind_id: str | None) -> float:
    """The Yield default for one input Type under one transformation, or 1.0
    (mass-conserving) if none applies, matching Sec 5.1's explicit fallback.

    Resolved by (kind, keyedBy) via mealplanner/defaults.py. The StructrScript
    resolveDefault this used to call ignored keyedBy, so a Type with Yield
    defaults for two transformations got whichever came back first, and the
    key check afterwards could not recover the right one."""
    keys = {transformation_kind_id} if transformation_kind_id else set()
    resolved = resolve_default(client, input_type_id, dt(client, "Yield"), keys)
    if resolved is None:
        return 1.0
    value, unit = resolved.quantity.get("value"), resolved.quantity.get("unit")
    if value is None or unit != "ratio":
        raise ValueError(f"Yield default {resolved.default_name!r} must be a ratio; got {value!r} {unit!r}")
    return value


def expected_combination_output(client, plan: dict) -> float:
    """Expected output mass in grams: the sum, over every input Specification
    of every Step, of (its quantity in grams x that input's own Yield default
    for ITS Step's transformation), matching Sec 5.1 applied per input.

    Called by scripts/15c to compute the combination recipes' outputs rather
    than hand-typing them. (An earlier docstring called this dead code, which
    stopped being true when 15c started using it.)

    Two bugs fixed along the way, both found by external review: `return
    total` sat inside the per-Step loop so a multi-Step Plan counted only its
    first Step, and each input's quantity was read as a bare number, ignoring
    its unit. An input whose quantity has no value or won't convert to grams
    raises QuantityError: an expected output that silently omitted an
    ingredient would just be a wrong number.

    STILL OPEN, not solved here: a genuinely CHAINED Plan (Step 1 boils raw
    pasta into boiled pasta; Step 2 takes the boiled pasta plus butter) would
    count material twice, once as Step 1's raw input and again through Step
    2's. Every recipe built so far is one Step with several inputs, so this
    never happens yet. The right model is a material-flow graph over the
    Steps (each transformation's yield applied along its edge), not a sum over
    the whole Plan; see REVIEW.md."""
    total = 0.0
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        # Each step's transformation kind is looked up fresh (not carried
        # over from a previous step) -- a step's inputs are yielded
        # against THAT step's own transformation, per Sec 5.1.
        instance_of = step.get("instanceOf")
        xform_kind_id = instance_of["id"] if instance_of else None
        for spec_ref in step.get("hasSpecification", []):
            spec = client.get_all("Specification", spec_ref["id"])["result"]
            if spec.get("hasParticipationRole") != "input":
                continue
            specifies = spec.get("specifies")
            qty_ref = spec.get("hasSpecifiedQuantity")
            if not specifies or not qty_ref:
                continue
            qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"]
            grams = None if qty.get("value") is None else convert_to_grams(client, specifies["id"], qty["value"], qty.get("unit"))
            if grams is None:
                raise QuantityError(
                    f"input Specification {spec.get('name')!r}: {qty.get('value')} {qty.get('unit')!r} "
                    f"cannot be converted to grams, so the expected output cannot be computed"
                )
            total += grams * resolve_yield_or_default(client, specifies["id"], xform_kind_id)
    return total


def recipe_servings(client, plan: dict) -> float:
    """Plan.hasRecipeYield, in servings -- data-model.md's AcquisitionList
    formula ("planned-servings / recipe-yield") only makes sense if
    recipe-yield is denominated in servings, which settles what was
    previously an unresolved unit ambiguity (see data-model.md Rev 4.3).
    Defaults to 1.0 if unset, same neutral-fallback convention as
    duration/nutrition elsewhere in this project.

    Moved here from scripts/11c_simple_selector.py so
    mealplanner/reservation.py can share it without a script importing
    another script -- this and candidate_input_requirements() below are
    both about walking a Plan's own structure, the same job
    expected_combination_output() does above."""
    yield_ref = plan.get("hasRecipeYield")
    if not yield_ref:
        return 1.0
    value = client.get_all("QuantitySpecification", yield_ref["id"])["result"].get("value")
    return 1.0 if value is None else value


def plan_specifications(client, plan: dict) -> list[dict]:
    """Every Specification of every Step of a Plan, fully loaded."""
    specs = []
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        for spec_ref in step.get("hasSpecification", []):
            specs.append(client.get_all("Specification", spec_ref["id"])["result"])
    return specs


def _type_ids(specs: list[dict], role: str) -> set[str]:
    return {s["specifies"]["id"] for s in specs if s.get("hasParticipationRole") == role and s.get("specifies")}


def candidate_input_requirements(client, plan: dict) -> list[tuple[str, float]]:
    """[(input DomainType id, required quantity IN GRAMS), ...] for a
    Plan's RAW input-role Specifications that carry a quantity and
    convert to a comparable mass (mealplanner/unit_conversion.py -- Sec
    11 invariant 13). Instrument-role Specifications never have a
    quantity (invariant 6); input Specifications without one, or whose
    declared unit doesn't resolve to grams for this ingredient (e.g. "1
    whole onion" with no MassPerUnit default), are skipped since there's
    no comparable magnitude to check against on-hand stock -- same "skip,
    don't guess" convention used throughout.

    RAW means an input whose type no Step of the same Plan produces. An
    intermediate (step 1 braises chicken, step 2 takes the braised
    chicken as an input) is made during the cook, not bought or stocked;
    counting it as a requirement made stock coverage read 0% forever for
    any multi-Step recipe. Not hit by the current single-Step recipes.

    Moved here from scripts/11c_simple_selector.py (originally added to
    fix a "unit-blind" bug found by external review) so
    mealplanner/reservation.py can share it too."""
    specs = plan_specifications(client, plan)
    produced = _type_ids(specs, "output")
    requirements = []
    for spec in specs:
        if spec.get("hasParticipationRole") != "input":
            continue
        specifies = spec.get("specifies")
        qty_ref = spec.get("hasSpecifiedQuantity")
        if not specifies or not qty_ref or specifies["id"] in produced:
            continue
        qty_spec = client.get_all("QuantitySpecification", qty_ref["id"])["result"]
        qty = qty_spec.get("value")
        if qty is None:
            continue
        qty_grams = convert_to_grams(client, specifies["id"], qty, qty_spec.get("unit"))
        if qty_grams:
            requirements.append((specifies["id"], qty_grams))
    return requirements


def recipe_servings_strict(client, plan: dict) -> float | None:
    """Plan.hasRecipeYield in servings, or None if it isn't stated as a
    positive number of servings. Unlike recipe_servings() this never
    falls back to 1.0: for nutrition, "1 serving" is a factual claim
    about how much one person eats, and an unset or non-serving yield
    (e.g. a "batch") must make the per-serving amount unknown rather
    than a guess. Found by external review (missing information turning
    into a plausible-looking default)."""
    yield_ref = plan.get("hasRecipeYield")
    if not yield_ref:
        return None
    qty = client.get_all("QuantitySpecification", yield_ref["id"])["result"]
    value = qty.get("value")
    if value is None or value <= 0 or qty.get("unit") != "servings":
        return None
    return value


def candidate_outputs(client, plan: dict) -> list[tuple[str, float | None]]:
    """[(output DomainType id, quantity IN GRAMS or None), ...] for
    every FINAL output of a Plan. The quantity is None if it's missing
    or doesn't convert to grams for that type (unit_conversion.py,
    invariant 13).

    FINAL means an output whose type no Step of the same Plan consumes
    as an input; an intermediate is a means, not something anyone eats.
    Replaces candidate_output(), which returned only the FIRST output
    found -- found by external review, since the model allows several
    per Step (a broth and the meat it cooked, a divided dough) and every
    later one was silently ignored. Deriving "final" from the Plan's own
    structure keeps it computed rather than stored, but it does assume a
    type is identified by its DomainType: a Plan that both consumes and
    produces the same type in different roles would read as having no
    final output of that type.

    Moved here from scripts/11c_simple_selector.py so
    mealplanner/nutrition_scope.py can share it. Unit-converts like the
    input path does; it used to return the raw numeric value."""
    specs = plan_specifications(client, plan)
    consumed = _type_ids(specs, "input")
    outputs = []
    for spec in specs:
        if spec.get("hasParticipationRole") != "output":
            continue
        specifies = spec.get("specifies")
        if not specifies or specifies["id"] in consumed:
            continue
        grams = None
        qty_ref = spec.get("hasSpecifiedQuantity")
        if qty_ref:
            qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"]
            if qty.get("value") is not None:
                grams = convert_to_grams(client, specifies["id"], qty["value"], qty.get("unit"))
        outputs.append((specifies["id"], grams))
    return outputs
