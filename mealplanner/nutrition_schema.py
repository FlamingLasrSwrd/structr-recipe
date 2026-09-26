"""NutrientProfile schema -- type-level nutrition reference data, per
data-model.md Sec 4.2: "Protein per 100g" is reference data about a
TYPE, not the magnitude of anything inhering in a particular portion.

This is what makes nutrition scoring possible at PLANNING time: the
selector needs to know a candidate recipe's likely nutrition BEFORE
anyone cooks it, so it can't read from a cooked instance's derived
Measurement (that only exists after cooking, per invariant 29). It has
to read from type-level reference data attached to the DomainType the
recipe's output Specification names.

Sec 8 rule 7 gives two ways to get a cooked output's nutrition:
  (a) the cooked Food-Identity Type's OWN NutrientProfile (analytically
      measured values) -- preferred.
  (b) apply yield + retention factors to the raw ingredient's profile.

Only (a) is implemented here. (b) needs RetentionFactor
DefaultSpecifications wired up per-ingredient-per-transformation, which
is real additional curation work, not implemented -- noted as a
deferred v2 path, not silently skipped.
"""

PROPERTIES: dict[str, list[dict]] = {
    "NutrientProfile": [
        {"name": "amount", "propertyType": "Double"},
        {"name": "basis", "propertyType": "Enum", "format": "per_100g,per_unit"},
        # Where the number came from. Left unset, a profile is treated as
        # untrusted: the planner will not let a hard NutritionTarget be decided
        # on data that is placeholder or of unknown origin (REVIEW.md round 1
        # #24; data-model.md Sec 18 J15).
        {"name": "provenance", "propertyType": "Enum", "format": "placeholder,sourced"},
    ],
}

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    # is_about: reuses the ABOUT label (already used by Allocation and
    # MealPlan/MealPlanEntry), new declaration, distinct reverse name.
    ("NutrientProfile", "ABOUT", "DomainType", "*", "1", "nutrientProfilesAbout", "isAbout"),
    # for_nutrient: reuses the FOR_NUTRIENT label already declared for
    # NutritionTarget -> DomainType.
    ("NutrientProfile", "FOR_NUTRIENT", "DomainType", "*", "1", "nutrientProfilesForNutrient", "forNutrient"),
]
