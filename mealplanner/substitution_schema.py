"""Schema for what may stand in for an ingredient (data-model.md Sec 5.3, Sec 18 J36; docs/recipe-format.md).

  Specification -[HAS_SUBSTITUTION_RULE]-> SubstitutionRule
      the model's has_substitution_rule (Sec 5) and, read the other way, the rule's for_specification:
      an input Specification only (invariant 22)
  SubstitutionRule -[CANDIDATE_TYPE]-> DomainType
      what may stand in: a Food-Identity Type, the hierarchy the Specification's own food is in (invariant 21)
  SubstitutionRule.substitutionRatio (Double)
      how much of it for one of the original, by the original's unit: 0.75 tbsp of oil for a tbsp of butter
  SubstitutionRule.isExcluded (Boolean)
      a rule that it must not stand in, whatever similarity suggests (Sec 5.3: the authored rule decides)

SubstitutionRule has been a structural type since the build (structural_types.py) with nothing on it;
these are plain properties and relationships on it, the safe kind of addition (scoring_schema.py's notes).
"""

PROPERTIES: dict[str, list[dict]] = {
    "SubstitutionRule": [
        {"name": "substitutionRatio", "propertyType": "Double"},
        {"name": "isExcluded", "propertyType": "Boolean"},
    ],
}

RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("Specification", "HAS_SUBSTITUTION_RULE", "SubstitutionRule", "1", "*", "forSpecification", "hasSubstitutionRule"),
    ("SubstitutionRule", "CANDIDATE_TYPE", "DomainType", "*", "1", "candidateOfRules", "candidateType"),
]
