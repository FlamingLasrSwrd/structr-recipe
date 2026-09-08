"""Schema additions for the meal-planning structural layer:
MealPlan, MealPlanEntry, StockPolicy, NutritionTarget, AcquisitionList.

All five SchemaNodes already exist (step 1's structural_types.py) --
this is properties and relationships only, per hard rule #3 (the
structural trait layer is frozen after build; nothing here adds a new
structural type).

Design notes:

- QuantitySpecification gains minValue/maxValue, extending the
  scalar-only `value` from step 4. Invariant 3 ("exactly one of
  value/closed range/open-bounded range/unconvertible") was deferred
  as a gap back in domain_invariants.py -- NutritionTarget.hasTargetRange
  can't function at all without it ("may be open-bounded" is explicit
  in the model), so this is the point where deferring it stops being
  reasonable. An onCreate check enforces "exactly one of value OR
  min/max" (not both scalar and range on the same QuantitySpecification).

- MealPlan.hasConstraint targets the ABSTRACT PlanningConstraint trait
  polymorphically (Sec 13: "MealPlan.has_constraint -> PlanningConstraint
  becomes one polymorphic declaration") -- covers both StockPolicy and
  NutritionTarget through one relationship declaration, the same
  proven abstract-target pattern from REALIZES->RealizableEntity.

- has_entry / member_of are the two directions of ONE relationship
  (MealPlan -[HAS_ENTRY]-> MealPlanEntry), not two separate ones.

- eligible_opened_statuses is modeled as two booleans
  (eligibleWhenOpened/eligibleWhenSealed) rather than a DomainType
  relation -- it's a genuine two-valued flag in the model's own
  language ("opened"/"sealed"), not a lookup hierarchy the way Storage
  Condition is (Sec 3's table lists Storage Condition as a real,
  lookup-bearing Type hierarchy; it does not list an Opened-Status
  hierarchy). Storage Condition gets the fuller DomainType treatment
  since it's explicitly named there.

- AcquisitionList is deliberately left with minimal structure (just a
  link to the MealPlan it's for). Its real content -- the netRequirements
  computation (build-sketch Sec 5) -- depends on currentMagnitude()/
  physicalOnHand(), which are themselves deferred (domain_invariants.py's
  invariant-15 note). Building AcquisitionList's actual computation now
  would mean building that whole compute-don't-store engine first;
  out of scope for this pass, flagged rather than faked with a stored
  field.
"""

PROPERTIES: dict[str, list[dict]] = {
    "QuantitySpecification": [
        {"name": "minValue", "propertyType": "Double"},
        {"name": "maxValue", "propertyType": "Double"},
    ],
    "MealPlanEntry": [
        {"name": "isSkipped", "propertyType": "Boolean"},
        {"name": "hasPlannedServings", "propertyType": "Double"},
    ],
    "StockPolicy": [
        {"name": "includesSubtypes", "propertyType": "Boolean"},
        {"name": "eligibleWhenOpened", "propertyType": "Boolean"},
        {"name": "eligibleWhenSealed", "propertyType": "Boolean"},
    ],
    "NutritionTarget": [
        {"name": "hasTimeScope", "propertyType": "Enum", "format": "daily,weekly,per_meal"},
        {"name": "dayBoundaryRule", "propertyType": "String"},
    ],
}

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("MealPlan", "HAS_ENTRY", "MealPlanEntry", "1", "*", "memberOf", "hasEntry"),
    ("MealPlan", "ABOUT", "TemporalRegion", "*", "1", "mealPlansAbout", "isAbout"),
    ("MealPlanEntry", "ABOUT", "TemporalRegion", "*", "1", "mealPlanEntriesAbout", "isAbout"),
    # source_mult="*" -- a StockPolicy/NutritionTarget is a standing rule
    # ("keep 2lbs chicken breast on hand"), not scoped to one week; many
    # MealPlans can share the same PlanningConstraint.
    ("MealPlan", "HAS_CONSTRAINT", "PlanningConstraint", "*", "*", "constrainedPlans", "hasConstraint"),
    ("MealPlanEntry", "FULFILLED_BY", "Process", "*", "1", "fulfillsMealPlanEntries", "fulfilledBy"),
    ("MealPlanEntry", "HAS_PLANNED_CONSUMPTION", "QuantitySpecification", "*", "1", "plannedConsumptionOfEntries", "hasPlannedConsumption"),
    ("MealPlanEntry", "REFERENCES", "Plan", "*", "1", "referencedByEntries", "references"),
    ("MealPlanEntry", "CONSUMES_LEFTOVER_FROM", "MealPlanEntry", "*", "1", "sourceForLeftoverEntries", "consumesLeftoverFrom"),
    ("StockPolicy", "APPLIES_TO", "DomainType", "*", "1", "stockPoliciesApplying", "appliesTo"),
    ("StockPolicy", "HAS_REORDER_THRESHOLD", "QuantitySpecification", "*", "1", "reorderThresholdOfPolicies", "hasReorderThreshold"),
    ("StockPolicy", "HAS_TARGET_LEVEL", "QuantitySpecification", "*", "1", "targetLevelOfPolicies", "hasTargetLevel"),
    ("StockPolicy", "ELIGIBLE_STORAGE_CONDITIONS", "DomainType", "*", "*", "eligibleForStockPolicies", "eligibleStorageConditions"),
    ("NutritionTarget", "FOR_NUTRIENT", "DomainType", "*", "1", "nutritionTargetsForNutrient", "forNutrient"),
    ("NutritionTarget", "HAS_TARGET_RANGE", "QuantitySpecification", "*", "1", "targetRangeOfNutritionTargets", "hasTargetRange"),
    ("AcquisitionList", "FOR_MEAL_PLAN", "MealPlan", "*", "1", "acquisitionLists", "forMealPlan"),
]
