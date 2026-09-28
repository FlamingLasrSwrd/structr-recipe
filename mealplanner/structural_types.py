"""The frozen structural trait layer.

Transcribed directly from structr-build-sketch.md Sec 2 (docs/structr-build-sketch.md)
-- the authoritative source. Do
not edit types here casually: per CLAUDE.md hard rule #1, renaming a
SchemaNode after it has instances orphans them irrecoverably, and hard
rule #3 says the structural layer is frozen after build. Get every name
right against the source doc before running the build script.

Each entry: (name, is_abstract, parent), where parent is a type name, None,
or a tuple of names for a type with more than one trait. Order is top-down
(a parent always appears before its children) so a setup script can walk
the list in order and every `inheritedTraits` reference names an
already-known type, or one of Structr's own traits in BUILTIN_TRAITS.

Note: the build sketch's prose originally said "~35 types, of which ~15 are
abstract scaffolding." The tree below has 16 abstract + 38 concrete = 54 (it
was 50 until ExclusionConstraint was added after the original build sketch,
and 51 until Person, Household and MealShare were added by the owner's
decision of 2026-09-28, data-model.md Sec 19).
The tree itself is what this transcribes and what the documents now quote;
tests/test_docs.py fails if the documents and len(STRUCTURAL_TYPES) disagree.
This comment once said 50 and was copied into two documents, which the same
test caught: do not write the count into prose without that test.
"""

# Structr's own traits a structural type may also inherit. A type that inherits
# `User` is a Structr account (it logs in, owns what it creates, can be a group
# member); one that inherits `Group` is a Structr group. Probed on a throwaway
# 6.0.0 instance before use (structr-cheatsheet.md, "Users, groups and grants"):
# such a node is both the Structr principal and an instance of our own trait,
# and satisfies relationships aimed at that trait.
BUILTIN_TRAITS = frozenset({"User", "Group"})

STRUCTURAL_TYPES: list[tuple[str, bool, str | tuple[str, ...] | None]] = [
    # -- root --
    ("Entity", True, None),
    # -- Continuant branch --
    ("Continuant", True, "Entity"),
    ("IndependentContinuant", True, "Continuant"),
    ("MaterialEntity", True, "IndependentContinuant"),
    ("BfoObject", True, "MaterialEntity"),  # renamed from "Object" -- see cheatsheet Sec 3, reserved-name trap
    ("FoodObject", True, "BfoObject"),
    ("DiscreteWholeItem", False, "FoodObject"),
    ("PortionOfSubstance", False, "FoodObject"),
    ("ContainerObject", False, "BfoObject"),
    ("EquipmentObject", False, "BfoObject"),
    # Added by the owner's decision, 2026-09-28 (data-model.md Sec 19): a human,
    # and the PROV agent of a check, a stock take or a purchase. Also a Structr
    # User, so one node is the person in the model and the account Structr's
    # login and permissions check.
    ("Person", False, ("BfoObject", "User")),
    ("ObjectAggregate", True, "MaterialEntity"),
    ("FoodAggregate", False, "ObjectAggregate"),
    ("UtensilSet", False, "ObjectAggregate"),
    # The same decision: persons sharing a kitchen, its stock and its meals, a BFO
    # object aggregate whose members are Persons. Also a Structr Group, whose
    # members are those Persons, so a grant to it shares the household's data.
    ("Household", False, ("ObjectAggregate", "Group")),
    ("SpecificallyDependentContinuant", True, "Continuant"),
    ("Quality", False, "SpecificallyDependentContinuant"),  # kind-reified, Sec 3
    ("RealizableEntity", True, "SpecificallyDependentContinuant"),
    ("Role", False, "RealizableEntity"),  # kind-reified
    ("Disposition", False, "RealizableEntity"),  # kind-reified
    ("Function", False, "Disposition"),  # kind-reified
    ("GenericallyDependentContinuant", True, "Continuant"),
    ("InformationContentEntity", True, "GenericallyDependentContinuant"),
    ("DirectiveICE", True, "InformationContentEntity"),
    ("RecipeIdentity", False, "DirectiveICE"),
    ("Plan", False, "DirectiveICE"),
    ("Step", False, "DirectiveICE"),
    ("Specification", False, "DirectiveICE"),
    ("QuantitySpecification", False, "DirectiveICE"),
    ("StateRequirement", False, "DirectiveICE"),
    ("SubstitutionRule", False, "DirectiveICE"),
    ("InstantiationPattern", False, "DirectiveICE"),
    ("DefaultSpecification", False, "DirectiveICE"),  # kind-reified, Sec 3
    ("MealPlan", False, "DirectiveICE"),
    ("MealPlanEntry", False, "DirectiveICE"),
    # The same decision: one person's part of a shared meal, how much of a
    # MealPlanEntry they are to eat. Not the deferred MealServing (one serving
    # made differently for one eater), which stays out of scope.
    ("MealShare", False, "DirectiveICE"),
    ("PlanningConstraint", True, "DirectiveICE"),  # abstract trait, NOT kind-reified -- subclassed instead
    ("StockPolicy", False, "PlanningConstraint"),
    ("NutritionTarget", False, "PlanningConstraint"),
    # Added post-hoc (not in the original build-sketch tree): "exclude
    # this ingredient/category entirely" (allergies, dietary
    # restrictions) had nowhere to go -- StockPolicy is inventory-level,
    # NutritionTarget is nutrient-level, neither fits "never select
    # this." Confirmed with the user before adding (hard rule #3).
    ("ExclusionConstraint", False, "PlanningConstraint"),
    ("ExtensionPropertyDefinition", False, "DirectiveICE"),
    ("AcquisitionList", False, "DirectiveICE"),
    ("DesignativeICE", True, "InformationContentEntity"),
    ("Concept", False, "DesignativeICE"),
    ("Identifier", False, "DesignativeICE"),
    ("DescriptiveICE", True, "InformationContentEntity"),
    ("Measurement", False, "DescriptiveICE"),
    ("NutrientProfile", False, "DescriptiveICE"),
    ("Allocation", False, "DescriptiveICE"),
    ("PriceObservation", False, "DescriptiveICE"),
    ("ExtensionPropertyValue", False, "DescriptiveICE"),
    # -- Occurrent branch --
    ("Occurrent", True, "Entity"),
    ("Process", False, "Occurrent"),  # kind-reified
    ("TemporalRegion", False, "Occurrent"),
]

# Sanity check the table itself: every parent must be defined earlier
# in the list (topological order), and every name must be unique.
def parents_of(parent: str | tuple[str, ...] | None) -> list[str]:
    """An entry's parent field as the list `inheritedTraits` takes."""
    if parent is None:
        return []
    return list(parent) if isinstance(parent, tuple) else [parent]


def _validate(table=None) -> None:
    seen: set[str] = set()
    for name, _is_abstract, parent in (STRUCTURAL_TYPES if table is None else table):
        if name in seen:
            raise ValueError(f"duplicate type name in table: {name}")
        for p in parents_of(parent):
            if p not in seen and p not in BUILTIN_TRAITS:
                raise ValueError(f"{name}: parent {p!r} not defined before it")
        if isinstance(parent, tuple) and not any(p in seen for p in parent):
            raise ValueError(f"{name}: at least one parent must be a structural type, not only Structr's own")
        seen.add(name)


_validate()
