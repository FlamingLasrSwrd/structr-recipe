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
    """Sum of each input's (quantity x its own resolved yield for this
    Plan's transformation), matching Sec 5.1 applied per-input.

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
    xform_kind_id = None
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        instance_of = step.get("instanceOf")
        if instance_of:
            xform_kind_id = instance_of["id"]
        total = 0.0
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
    return 0.0
