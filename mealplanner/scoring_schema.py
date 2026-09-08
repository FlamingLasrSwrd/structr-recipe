"""Schema for the simple-path meal selector: PlanningConstraint's
strictness/weight extension, ExclusionConstraint's own field, and the
scoring inputs (Plan duration/difficulty, MealPlan priority weights).

Design notes:

- strictness/weight go on the ABSTRACT PlanningConstraint trait, not on
  each concrete subtype separately -- StockPolicy, NutritionTarget, and
  ExclusionConstraint all inherit both from one declaration each. Per
  the WCSP literature this session's design conversation drew on: hard
  and soft constraints are the SAME mechanism with a strictness flag,
  not two mechanisms, so this belongs on the shared abstract parent.
  Adding a PROPERTY to an already-inherited trait is a different,
  safe operation from adding a NEW trait to a populated type (hard
  rule #2) -- confirmed by the cheatsheet: trait properties propagate
  correctly to existing subtypes' instances.

- Plan.estimatedDurationMinutes/difficultyRating and
  MealPlan.timeBudgetWeight/varietyWeight are plain properties on
  already-instantiated CONCRETE types (Plan, MealPlan already have real
  data). This is the same kind of safe addition used throughout this
  build (Measurement gained value/unit/status/hasTime long after it
  had instances) -- not the trait-on-populated-type hazard hard rule #2
  warns about, which is specifically about inheritedTraits/labels.

- The weekly "priority profile" proposed in the design conversation is
  deliberately NOT a new structural type -- it's just these two weight
  properties directly on MealPlan. Changing them is a data write, which
  is the whole point: no code path needs to change to shift a week's
  priorities.
"""

PROPERTIES: dict[str, list[dict]] = {
    "PlanningConstraint": [
        {"name": "strictness", "propertyType": "Enum", "format": "hard,soft"},
        {"name": "weight", "propertyType": "Double"},
    ],
    "Plan": [
        {"name": "estimatedDurationMinutes", "propertyType": "Double"},
        {"name": "difficultyRating", "propertyType": "Enum", "format": "easy,medium,hard"},
    ],
    "MealPlan": [
        {"name": "timeBudgetMinutes", "propertyType": "Double"},
        {"name": "timeBudgetWeight", "propertyType": "Double"},
        {"name": "varietyWeight", "propertyType": "Double"},
        # Added when stock-awareness/waste scoring was built (see
        # mealplanner/inventory.py) -- same "priority profile is just
        # data on MealPlan" pattern as the first three.
        {"name": "stockWeight", "propertyType": "Double"},
        {"name": "wasteWeight", "propertyType": "Double"},
    ],
}

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    # Separate declaration from StockPolicy's existing APPLIES_TO
    # (rather than relocating that one onto the trait) -- avoids
    # touching an existing relationship with live data at all;
    # reuses the "APPLIES_TO" label safely, distinct reverse name.
    ("ExclusionConstraint", "APPLIES_TO", "DomainType", "*", "1", "exclusionConstraintsApplying", "appliesTo"),
    # Type-level, not instance-level (unlike hasPerishabilityType/Reading
    # A) -- a Specification's `specifies` points at a DomainType, so
    # exclusion filtering at planning time (before any instance exists)
    # needs the Biological Origin fact on the TYPE. Self-referential on
    # DomainType, distinct relationshipType from SUBCLASS_OF/MAY_BEAR_ROLE
    # so no reverse-name collision despite all three being DomainType-
    # to-DomainType.
    ("DomainType", "HAS_BIOLOGICAL_ORIGIN", "DomainType", "*", "*", "foodsOfThisOrigin", "hasBiologicalOrigin"),
]
