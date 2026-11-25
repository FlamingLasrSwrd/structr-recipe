"""Schema for a food bought in place of what the shopping list says (mealplanner/substitutes.py;
data-model.md Sec 18 J42, Sec 5's via_substitution and invariant 18).

  MealPlanEntry -[USES_SUBSTITUTION]-> SubstitutionRule
      the rules a planned meal uses: for that meal, a rule's input is its candidate. Many meals may use
      one rule, and one meal several (one per input)
  Allocation -[VIA_SUBSTITUTION]-> SubstitutionRule
      the model's via_substitution (Sec 5, optional): the rule a cook's draw followed
  SubstitutionRule.isOneOff (Boolean)
      a rule made for the meals that use it, not one of the recipe's own: the recipe's sentences leave it
      out, a recipe loaded again keeps it, and its ratio is by weight

Plain properties and relationships on structural types that already exist (SubstitutionRule,
MealPlanEntry, Allocation), the safe kind of addition (scoring_schema.py's notes); no trait, no new type
(hard rules 2 and 3).
"""

PROPERTIES: dict[str, list[dict]] = {
    "SubstitutionRule": [
        {"name": "isOneOff", "propertyType": "Boolean"},
    ],
}

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name); the json names
# are inverted (hard rule 6): the source reads the target as target_json_name
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("MealPlanEntry", "USES_SUBSTITUTION", "SubstitutionRule", "*", "*", "usedByEntries", "usesSubstitution"),
    ("Allocation", "VIA_SUBSTITUTION", "SubstitutionRule", "*", "1", "allocationsVia", "viaSubstitution"),
]
