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

This means expected_combination_output() is really just
resolveDefault(Yield) applied per input and summed -- no new relations,
no schema change, just the existing mechanism used correctly for N
inputs instead of assumed to only ever see one.
"""

from __future__ import annotations

from mealplanner.unit_conversion import convert_to_grams


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def resolve_yield_or_default(client, input_type_id: str, transformation_kind_id: str) -> float:
    """resolveDefault(Yield) for one input type; 1.0 (mass-conserving)
    if none resolves, matching Sec 5.1's explicit fallback rule."""
    yield_kind = dt(client, "Yield")
    result = client.call_method("DomainType", input_type_id, "resolveDefault", {"kindId": yield_kind})
    if not isinstance(result, dict) or "id" not in result:
        return 1.0
    qty = client.get_all("QuantitySpecification", result["id"])["result"]
    # A resolved default with no keyedBy restriction would incorrectly
    # apply to every transformation; DefaultSpecification.keyedBy is
    # checked here explicitly rather than trusting resolveDefault alone,
    # since resolveDefault's own kind-matching doesn't currently
    # consider keyedBy (a limitation noted, not silently assumed away --
    # see the module docstring's caveat below).
    default_spec_ref = qty.get("defaultSpecification")
    if default_spec_ref:
        spec = client.get_all("DefaultSpecification", default_spec_ref["id"])["result"]
        keyed_by_ids = {k["id"] for k in spec.get("keyedBy", [])}
        if keyed_by_ids and transformation_kind_id not in keyed_by_ids:
            return 1.0
    return qty.get("value") or 1.0


def expected_combination_output(client, plan: dict) -> float:
    """Sum of each input's (quantity x its own resolved yield for its
    OWN step's transformation), across every Step of the Plan, matching
    Sec 5.1 applied per-input.

    BUG FIXED (found by external review): an earlier version put
    `return total` inside the outer per-Step loop, so a multi-Step Plan
    only ever computed the first Step's inputs. Not caught by this
    project's own data because every recipe built so far uses exactly
    one Step per Plan (a "combination recipe" here means one Step with
    several input Specifications, e.g. pasta + butter + parmesan all
    input to one "Combining" transformation) -- and because this
    function isn't wired into any script yet (dead code). Fixed to
    accumulate across all Steps and look up each Step's own
    instanceOf transformation independently, rather than leaking the
    previous Step's transformation kind forward.

    OPEN QUESTION, not resolved here: for a genuinely chained multi-Step
    Plan (Step 1 boils raw pasta into "boiled pasta"; Step 2 combines
    that intermediate output with butter/parmesan), summing every
    Step's raw inputs would double-count material that flows from one
    Step's output into the next Step's input. This project has no such
    recipe yet, so the fix above doesn't attempt to solve that case --
    flagging it rather than silently assuming multi-Step Plans are
    always "flat" (independent ingredient lists sharing one final
    output).

    CAVEAT: resolveDefault() walks a single DomainType's own
    SUBCLASS_OF* chain; it does not itself filter by keyedBy (this
    module does that filtering afterward, once, on the single resolved
    result). If TWO DefaultSpecifications existed for the same input
    type under different keyedBy transformations, resolveDefault would
    only ever surface whichever one it happens to find first walking
    upward -- not necessarily the one matching THIS Plan's
    transformation. Not hit by this project's data (no input type has
    more than one Yield default yet), but a real limitation worth
    fixing in resolveDefault itself before this pattern is trusted at
    scale.
    """
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
            qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"].get("value") or 0.0
            yield_factor = resolve_yield_or_default(client, specifies["id"], xform_kind_id) if xform_kind_id else 1.0
            total += qty * yield_factor
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
    qty = client.get_all("QuantitySpecification", yield_ref["id"])["result"]
    return qty.get("value") or 1.0


def candidate_input_requirements(client, plan: dict) -> list[tuple[str, float]]:
    """[(input DomainType id, required quantity IN GRAMS), ...] for a
    Plan's input-role Specifications that carry a quantity and convert
    to a comparable mass (mealplanner/unit_conversion.py -- Sec 11
    invariant 13). Instrument-role Specifications never have a quantity
    (invariant 6); input Specifications without one, or whose declared
    unit doesn't resolve to grams for this ingredient (e.g. "1 whole
    onion" with no MassPerUnit default), are skipped here since there's
    no comparable magnitude to check against on-hand stock -- same
    "skip, don't guess" convention used throughout this module.

    Moved here from scripts/11c_simple_selector.py (originally added to
    fix a "unit-blind" bug found by external review) so
    mealplanner/reservation.py can share it too."""
    requirements = []
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        for spec_ref in step.get("hasSpecification", []):
            spec = client.get_all("Specification", spec_ref["id"])["result"]
            if spec.get("hasParticipationRole") != "input":
                continue
            specifies = spec.get("specifies")
            qty_ref = spec.get("hasSpecifiedQuantity")
            if not specifies or not qty_ref:
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


def candidate_output(client, plan: dict) -> tuple[str | None, float | None]:
    """(output DomainType id, output quantity IN GRAMS) for a Plan's
    FIRST output-role Specification. (None, None) if it has none; the
    quantity alone is None if it's missing or doesn't convert to grams
    for the output type (unit_conversion.py, invariant 13).

    Moved here from scripts/11c_simple_selector.py so
    mealplanner/nutrition_scope.py can share it. Now unit-converts like
    candidate_input_requirements() does; it used to return the raw
    numeric value regardless of unit. Still FIRST-output-only, a known
    gap: the model allows several outputs per Step."""
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        for spec_ref in step.get("hasSpecification", []):
            spec = client.get_all("Specification", spec_ref["id"])["result"]
            if spec.get("hasParticipationRole") != "output":
                continue
            specifies = spec.get("specifies")
            if not specifies:
                continue
            grams = None
            qty_ref = spec.get("hasSpecifiedQuantity")
            if qty_ref:
                qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"]
                if qty.get("value") is not None:
                    grams = convert_to_grams(client, specifies["id"], qty["value"], qty.get("unit"))
            return specifies["id"], grams
    return None, None
