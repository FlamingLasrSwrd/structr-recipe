"""Meal Type tagging: Concept-scheme based, per data-model.md Sec 1/Sec 3
("Cuisine and Meal Type never drove a lookup and need only thesaurus
semantics, so they remain Concept schemes") -- NOT a new DomainType
hierarchy and NOT a plain enum property. See the design conversation
this followed for the full reasoning.

New structural type: ConceptScheme. Not invented on the spot -- named
explicitly in structr-build-sketch.md Sec 4 ("Concept ... IN_SCHEME ->
ConceptScheme") but deferred when scoping step 6, since nothing needed
it yet. Standalone, no inheritedTraits -- same pattern as DomainType/
TypeHierarchy/RelationKind (a metamodel container, not itself a BFO
particular, so it sits outside the Entity trait tree).

Concept already exists as a structural type (step 1, under
DesignativeICE) with zero properties/relations built so far -- this is
the first time it's actually used. IN_SCHEME is the only relation
added; DENOTES (Concept -> DomainType, for lookup-bearing facets like
Food Identity labels) is out of scope here since Meal Type concepts
don't denote a DomainType at all.

HAS_MEAL_TYPE lives on RecipeIdentity, not Plan -- same reasoning
Sec 5.2 already used for defines_output_type: meal-type is a property
of the enduring dish, not of one edited version.
"""

NEW_TYPES = ["ConceptScheme"]

PROPERTIES: dict[str, list[dict]] = {
    "ConceptScheme": [
        {"name": "name", "propertyType": "String", "unique": True, "indexed": True, "notNull": True},
    ],
}

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("Concept", "IN_SCHEME", "ConceptScheme", "*", "1", "concepts", "inScheme"),
    ("RecipeIdentity", "HAS_MEAL_TYPE", "Concept", "*", "*", "taggedRecipes", "hasMealType"),
]

MEAL_TYPES = ["Breakfast", "Lunch", "Dinner", "Snack"]
