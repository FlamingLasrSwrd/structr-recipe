"""The frozen structural trait layer.

Transcribed directly from structr-build-sketch.md Sec 2 (docs/structr-build-sketch.md)
-- the authoritative source. Do
not edit types here casually: per CLAUDE.md hard rule #1, renaming a
SchemaNode after it has instances orphans them irrecoverably, and hard
rule #3 says the structural layer is frozen after build. Get every name
right against the source doc before running the build script.

Each entry: (name, is_abstract, parent_name_or_None).
Order is top-down (a parent always appears before its children) so a
setup script can walk the list in order and every `inheritedTraits`
reference names an already-known type.

Note: the build sketch's prose originally said "~35 types, of which ~15 are
abstract scaffolding." The tree below has 16 abstract + 35 concrete = 51 (it
was 50 until ExclusionConstraint was added after the original build sketch).
The tree itself is what this transcribes and what the documents now quote;
tests/test_docs.py fails if the documents and len(STRUCTURAL_TYPES) disagree.
This comment once said 50 and was copied into two documents, which the same
test caught: do not write the count into prose without that test.
"""

STRUCTURAL_TYPES: list[tuple[str, bool, str | None]] = [
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
    ("ObjectAggregate", True, "MaterialEntity"),
    ("FoodAggregate", False, "ObjectAggregate"),
    ("UtensilSet", False, "ObjectAggregate"),
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
def _validate() -> None:
    seen: set[str] = set()
    for name, _is_abstract, parent in STRUCTURAL_TYPES:
        if name in seen:
            raise ValueError(f"duplicate type name in table: {name}")
        if parent is not None and parent not in seen:
            raise ValueError(f"{name}: parent {parent!r} not defined before it")
        seen.add(name)


_validate()
