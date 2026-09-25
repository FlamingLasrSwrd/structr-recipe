"""Unit conversion, per data-model.md Sec 11 invariant 13: "Cross-
quantity-kind conversion requires an explicit density; without one,
unconvertible."

Fixes the "unit-blind" gap found by external review: the selector
(scripts/11c_simple_selector.py) compared a recipe's required quantity
directly against on-hand mass in grams, regardless of what unit the
requirement was actually recorded in -- correct today only because
every recipe input in this project's real test data happens to be
recorded in grams already. This module makes that assumption an
explicit, checked conversion instead of an implicit, unchecked one.

The model already specifies the mechanism (data-model.md Sec 8):
Density and MassPerUnit are named Default-Kind Types, resolved the
same way as Yield/ShelfLife (DefaultSpecification.hasKind, walked via
resolveDefault). Neither is `keyedBy` anything in the model's own
worked example ("hasKind: Density  keyedBy: --"), so this doesn't need
material_accounting.py's post-hoc keyedBy re-check -- there is only
ever one Density/MassPerUnit default to find per Type.

The mass/volume unit table below is UCUM-grounded physical constants,
not food-specific data, so it lives here as a plain lookup rather than
DefaultSpecifications. Crossing BETWEEN quantity kinds (volume -> mass,
count -> mass) is exactly what invariant 13 gates: it requires a
food-specific Density or MassPerUnit default to resolve, and returns
None (unconvertible) rather than guessing if none does -- same
"undefined/unconvertible, never a guess" convention resolveDefault
itself already follows (Sec 8's algorithm, step 3).
"""

from __future__ import annotations

# unit string (lowercased) -> (quantity_kind, factor to that kind's
# canonical unit). Canonical units: grams (mass), milliliters (volume),
# each (count).
UNIT_TABLE: dict[str, tuple[str, float]] = {
    # mass
    "g": ("mass", 1.0),
    "gram": ("mass", 1.0),
    "grams": ("mass", 1.0),
    "kg": ("mass", 1000.0),
    "mg": ("mass", 0.001),
    "oz": ("mass", 28.3495),
    "lb": ("mass", 453.592),
    # volume (UCUM / US customary constants)
    "ml": ("volume", 1.0),
    "l": ("volume", 1000.0),
    "cup": ("volume", 236.588),
    "tbsp": ("volume", 14.7868),
    "tsp": ("volume", 4.92892),
    "fl_oz": ("volume", 29.5735),
    # count -- "how many discrete items", not a physical unit at all
    "each": ("count", 1.0),
    "whole": ("count", 1.0),
    "count": ("count", 1.0),
}


def _resolve_unkeyed_default(client, food_type_id: str, kind_name: str) -> float | None:
    """resolveDefault(kind) for a Default-Kind Sec 8's own worked
    examples show as never keyedBy anything (Density, MassPerUnit) --
    unlike Yield, there's only ever one candidate to find, so this
    doesn't need material_accounting.py's post-hoc keyedBy re-check."""
    kind_id = client.get("/structr/rest/DomainType", params={"name": kind_name})["result"][0]["id"]
    result = client.call_method("DomainType", food_type_id, "resolveDefault", {"kindId": kind_id})
    if not isinstance(result, dict) or "id" not in result:
        return None
    return client.get_all("QuantitySpecification", result["id"])["result"].get("value")


def convert_to_grams(client, food_type_id: str, value: float, unit: str | None) -> float | None:
    """value(unit) of food_type_id -> grams, or None if unconvertible
    (invariant 13: cross-quantity-kind conversion requires an explicit
    density; without one, unconvertible -- never guessed). A mass-to-
    mass conversion never needs a Type-specific default; volume and
    count need Density/MassPerUnit resolved for food_type_id first."""
    if unit is None:
        return None
    entry = UNIT_TABLE.get(unit.strip().lower())
    if entry is None:
        return None  # unrecognized unit string -- unconvertible, not guessed
    kind, factor = entry

    if kind == "mass":
        return value * factor

    if kind == "volume":
        density = _resolve_unkeyed_default(client, food_type_id, "Density")  # g/mL
        if density is None:
            return None
        return value * factor * density

    if kind == "count":
        mass_per_unit = _resolve_unkeyed_default(client, food_type_id, "MassPerUnit")  # g/each
        if mass_per_unit is None:
            return None
        return value * factor * mass_per_unit

    return None
