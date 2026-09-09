"""Fixes the third occurrence of a recurring pattern in this build: an
invariant's own prose describes a relationship that was never formally
named in data-model.md Sec 7. Invariant 27a says "the Role's target
entry must be the one whose consumes_leftover_from names the entry
whose Process generated that portion" -- but no relation from Role to
MealPlanEntry exists anywhere in the model's vocabulary. This names
one (targets_entry / TARGETS_ENTRY) and builds it.

Additive to Role (already exists, already kind-reified via the shared
SDC trait) -- no new structural type, matching hard rule #3.
"""

PROPERTIES: dict[str, list[dict]] = {}

RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    # A reservation Role on a physical portion optionally targets the
    # MealPlanEntry that will consume it as a leftover. Many Roles could
    # in principle target the same entry is nonsensical (one physical
    # reservation per entry), so target_mult=1 keeps this a single ref;
    # source_mult=1 too, since one entry has at most one reserving Role.
    ("Role", "TARGETS_ENTRY", "MealPlanEntry", "1", "1", "reservationRole", "targetsEntry"),
]
