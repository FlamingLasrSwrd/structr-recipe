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
input -- no new relations, no schema change, just the existing mechanism used
correctly for N inputs instead of assumed to only ever see one. For a Plan
whose Steps chain, each input's yielded mass is routed through the Steps
(total_output_grams, data-model.md Sec 18 J11) rather than summed over the
whole Plan, which would count an intermediate twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from mealplanner.defaults import resolve_default
from mealplanner.typetree import dt
from mealplanner.unit_conversion import QuantityError, convert_to_grams


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


@dataclass
class FlowStep:
    """One Step as far as material flow is concerned. `inputs` holds
    (type id, grams or None when the recipe states no amount); `outputs` the
    type ids the Step produces."""

    name: str
    kind_id: str | None
    inputs: list[tuple[str, float | None]]
    outputs: list[str]


def total_output_grams(steps: list[FlowStep], yield_of: Callable[[str, str | None], float]) -> float:
    """Expected mass, in grams, leaving a Plan: material flowed through its
    Steps, with each input's own yield applied at the Step that takes it.

    A Step's flow is the sum over its inputs of (amount x yield of that input
    under that Step's transformation). An input's amount is
      - its stated quantity, if it has one;
      - otherwise, if a DIFFERENT Step of the Plan produces its type (an
        intermediate: step 1 boils pasta, step 2 tosses the boiled pasta with
        butter), that producing Step's flow;
      - otherwise nothing (a raw input with no stated amount, such as salt
        "to taste", contributes zero).
    The Plan's output is the summed flow of its terminal Steps, those whose
    output no other Step consumes. Because an intermediate is taken up by the
    Step that consumes it, and only terminal Steps are summed, nothing is
    counted twice; summing over every input of every Step (which this used to
    do) counted boiled pasta once as raw pasta and again as boiled pasta.

    Where the flow cannot be traced without guessing, this raises
    QuantityError rather than choosing: an intermediate consumed by several
    Steps with no stated amounts (how is it divided?), a Step producing both
    an intermediate and a final output (how much goes where?), a cycle.

    Two assumptions, inherited from candidate_outputs(): a type is identified
    by its DomainType, so a Plan that both consumes and produces one type in
    different roles reads as a chain; and the stated amount of an intermediate
    is taken as authoritative even when it disagrees with what the producing
    Step's own flow works out to (a recipe that says "use 250 g of the boiled
    pasta" means 250 g)."""
    producers: dict[str, list[int]] = {}
    consumers: dict[str, list[int]] = {}
    for i, step in enumerate(steps):
        for type_id in step.outputs:
            producers.setdefault(type_id, []).append(i)
        for type_id, _ in step.inputs:
            consumers.setdefault(type_id, []).append(i)

    def consumed_outputs(i: int) -> list[str]:
        return [t for t in steps[i].outputs if any(c != i for c in consumers.get(t, []))]

    for i, step in enumerate(steps):
        taken = consumed_outputs(i)
        if taken and len(taken) < len(set(step.outputs)):
            raise QuantityError(
                f"step {step.name!r} produces both an intermediate that a later step consumes and a final output; "
                f"how its material divides between them is not stated"
            )

    flows: dict[int, float] = {}
    in_progress: set[int] = set()

    def flow(i: int) -> float:
        if i in flows:
            return flows[i]
        if i in in_progress:
            raise QuantityError(f"step {steps[i].name!r} is part of a cycle: its material flows back into itself")
        in_progress.add(i)
        step = steps[i]
        total = 0.0
        for type_id, grams in step.inputs:
            if grams is None:
                others = [p for p in producers.get(type_id, []) if p != i]
                if not others:
                    continue                      # raw, no stated amount: contributes nothing
                if len(consumers[type_id]) > 1:
                    raise QuantityError(
                        f"an intermediate consumed by {len(consumers[type_id])} steps (including {step.name!r}) "
                        f"states no amount, so how it divides between them is undecided"
                    )
                if len(others) > 1:
                    raise QuantityError(f"an intermediate produced by {len(others)} steps states no amount")
                grams = flow(others[0])
            total += grams * yield_of(type_id, step.kind_id)
        in_progress.discard(i)
        flows[i] = total
        return total

    # Every Step is traced, not only the terminal ones, so a cycle or an
    # ambiguity anywhere in the Plan raises instead of being ignored: two Steps
    # feeding each other have no terminal Step at all and would otherwise
    # sum to a silent 0.
    all_flows = [flow(i) for i in range(len(steps))]
    return sum(all_flows[i] for i in range(len(steps)) if not consumed_outputs(i))


def expected_combination_output(client, plan: dict) -> float:
    """Expected output mass in grams of a Plan (Sec 5.1 applied per input,
    routed through the Plan's Steps by total_output_grams()).

    Called by scripts/15c to compute the combination recipes' outputs rather
    than hand-typing them. Bugs fixed along the way, all found by external
    review: `return total` sat inside the per-Step loop so a multi-Step Plan
    counted only its first Step; each input's quantity was read as a bare
    number, ignoring its unit; and a chained Plan (one Step's output consumed
    by the next) counted the same material twice. An input whose quantity has
    a value but won't convert to grams raises QuantityError: an expected
    output that silently omitted an ingredient would just be a wrong number.
    An input with no quantity at all is a raw ingredient stated without an
    amount and contributes nothing."""
    steps = []
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        # Each Step's transformation kind is looked up fresh (not carried
        # over from a previous Step) -- a Step's inputs are yielded
        # against THAT Step's own transformation, per Sec 5.1.
        instance_of = step.get("instanceOf")
        inputs, outputs = [], []
        for spec_ref in step.get("hasSpecification", []):
            spec = client.get_all("Specification", spec_ref["id"])["result"]
            specifies = spec.get("specifies")
            if not specifies:
                continue
            role = spec.get("hasParticipationRole")
            if role == "output":
                outputs.append(specifies["id"])
                continue
            if role != "input":
                continue
            qty_ref = spec.get("hasSpecifiedQuantity")
            if not qty_ref:
                inputs.append((specifies["id"], None))
                continue
            qty = client.get_all("QuantitySpecification", qty_ref["id"])["result"]
            grams = None if qty.get("value") is None else convert_to_grams(client, specifies["id"], qty["value"], qty.get("unit"))
            if grams is None:
                raise QuantityError(
                    f"input Specification {spec.get('name')!r}: {qty.get('value')} {qty.get('unit')!r} "
                    f"cannot be converted to grams, so the expected output cannot be computed"
                )
            inputs.append((specifies["id"], grams))
        steps.append(FlowStep(step.get("name") or step["id"], instance_of["id"] if instance_of else None, inputs, outputs))
    return total_output_grams(steps, lambda type_id, kind_id: resolve_yield_or_default(client, type_id, kind_id))


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
    positive number of servings. It never falls back to 1.0: "1 serving" is a
    factual claim, and an unset or non-serving yield (e.g. a "batch") must
    make the answer unknown rather than a guess. Both users of a yield rely on
    that: nutrition (the amount per serving) and reservation (planned servings
    / recipe yield, data-model.md Sec 7). A lenient reader that returned 1.0
    used to serve reservation and has been removed. Found by external review
    (missing information turning into a plausible-looking default)."""
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
