"""What a recipe's steps need that a kitchen does not have (J37, docs/recipe-format.md).

The owner's decision (2026-10-31): the tools are checked when a recipe is imported, not when a week
is planned. tools/import_recipe.py asks before loading a recipe that needs something missing.

A kitchen is a UtensilSet whose members are EquipmentObjects, each an instance of an Equipment Type
(tools/instantiate_profile.py kitchen). A step names its tools in two ways (recipe_import.StepDoc):

- an Equipment Type, met by a member of that type or of a narrower one: a recipe asking for a
  "Skillet" is met by a "Cast-iron skillet" when that type's parent is Skillet;
- a capability (a Function type, J37), met by a member whose type, or a broader type above it, can
  give that capability or a narrower one (`mayBearFunction`): "Oven heat" by an Oven.

The same reading as the recipe page's sentence (recipe_import.capability_bearers names the types
that can give a capability). A kitchen with no members needs everything; an instance with no kitchen
has nothing to check against, which kitchens() reports as an empty list.
"""

from __future__ import annotations

from dataclasses import dataclass

from mealplanner.typetree import ancestors_or_self


@dataclass(frozen=True)
class Missing:
    step: str        # the step's label
    need: str        # the tool or capability, by the name the recipe file gives it
    capability: bool


def kitchens(client) -> list[dict]:
    """Every kitchen on the instance: {"id", "name", "types"}, `types` the Equipment Type ids its
    members are instances of, each with every type above it."""
    out = []
    for kitchen in sorted(client.get_all("UtensilSet")["result"], key=lambda k: k["name"]):
        members = client.get_all("UtensilSet", kitchen["id"])["result"].get("hasMemberPart") or []
        types = set()
        for ref in members:
            instance_of = client.get_all("EquipmentObject", ref["id"])["result"].get("instanceOf")
            if instance_of:
                types.update(ancestors_or_self(client, instance_of["id"]))
        out.append({"id": kitchen["id"], "name": kitchen["name"], "types": frozenset(types)})
    return out


def bearers(client, capability_id: str) -> frozenset[str]:
    """The Equipment Type ids that can give a capability or any narrower one (`functionBorneBy`)."""
    found, todo, seen = set(), [capability_id], set()
    while todo:
        node = client.get_all("DomainType", todo.pop())["result"]
        seen.add(node["id"])
        found |= {b["id"] for b in node.get("functionBorneBy") or []}
        todo += [c["id"] for c in node.get("children") or [] if c["id"] not in seen]
    return frozenset(found)


def missing(client, steps, equipment: dict[str, str], kitchen: dict) -> list[Missing]:
    """What `steps` (recipe_import.StepDoc) need that `kitchen` (from kitchens()) lacks, in step order.
    `equipment` maps each name the steps give to its DomainType id (recipe_import.Resolved.equipment)."""
    out, can_give = [], {}
    for step in steps:
        for need in step.equipment:
            type_id = equipment[need]
            if need in step.capabilities:
                if type_id not in can_give:
                    can_give[type_id] = bearers(client, type_id)
                met = bool(can_give[type_id] & kitchen["types"])
            else:
                met = type_id in kitchen["types"]
            if not met:
                out.append(Missing(step.label, need, need in step.capabilities))
    return out


def describe(item: Missing) -> str:
    return f"step {item.step!r}: {'something that gives ' if item.capability else ''}{item.need}"
