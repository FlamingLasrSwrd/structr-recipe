"""Schema for the facts of a recipe's steps (data-model.md Sec 18 J35; docs/recipe-format.md).

The owner asked (2026-10-26) for "the missing facts" of a step: how long it takes, at what heat,
until what, and in what order. Every one is a fact, not a source's wording (docs/recipe-copyright.md),
and every one goes on types the model already has:

  Step -[HAS_WORKING_TIME]-> QuantitySpecification (minutes)
      the time the step takes someone's attention: chopping, stirring, flipping
  Step -[HAS_WAITING_TIME]-> QuantitySpecification (minutes)
      the time it then needs no one: simmering covered, baking, resting. A prescribed magnitude is a
      QuantitySpecification (Sec 4.1), as a recipe's yield is; the Transformation Method's own
      Duration default (Sec 8) stays the fallback a planner may use where a step states none
  Step -[IS_PRECEDED_BY]-> Step
      P-Plan's isPreceededBy (Sec 7): the steps that must be done before this one. Two steps neither of
      which precedes the other may run side by side

Heat and doneness need nothing new in the schema: a Specification already has StateRequirements
(recipe_schema.py), each targeting a Quality Kind with an expected quantity or words:

  heat      on an instrument's Specification: Temperature (an oven's, in degF or degC), or Heat Level
            (a burner's: low to high)
  doneness  on an output's Specification: Doneness, in words ("golden"), and Temperature (inside the
            food: 165 degF for poultry, USDA FSIS's safe minimum)

QUALITY_KINDS are the Quality Kinds those name, vocabulary the model needs as it needs Mass
(seed_vocabulary.py), made by scripts/41a.
"""

RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("Step", "HAS_WORKING_TIME", "QuantitySpecification", "*", "1", "workingTimeOfSteps", "hasWorkingTime"),
    ("Step", "HAS_WAITING_TIME", "QuantitySpecification", "*", "1", "waitingTimeOfSteps", "hasWaitingTime"),
    ("Step", "IS_PRECEDED_BY", "Step", "*", "*", "precedes", "isPrecededBy"),
]

QUALITY_KIND_HIERARCHY = "Quality Kind"
TEMPERATURE, HEAT_LEVEL, DONENESS = "Temperature", "Heat Level", "Doneness"
QUALITY_KINDS = (TEMPERATURE, HEAT_LEVEL, DONENESS)
