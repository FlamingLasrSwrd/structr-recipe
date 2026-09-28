"""Schema for people, households and shared meals (data-model.md Sec 19, the owner's decision
of 2026-09-28; docs/verification-and-sharing.md Sec 3.3 and 3.5).

The three structural types (mealplanner/structural_types.py): Person (BfoObject and Structr's
User), Household (ObjectAggregate and Structr's Group) and MealShare (DirectiveICE). A household's
members are its Group members: Structr's own membership, not a relation of ours.

  Process -[WAS_ASSOCIATED_WITH]-> Person
      PROV `wasAssociatedWith`: who carried out a check, a stock take or a purchase.
  NutritionTarget -[TARGET_FOR]-> Person, ExclusionConstraint -[EXCLUSION_FOR]-> Person
      whose target or exclusion it is; each person has their own.
  Person -[HAS_BASELINE]-> Plan
      what a person eats every day outside the planned meals (J25), now per person.
  MealPlan -[FOR_HOUSEHOLD]-> Household
      the household a week feeds.
  MealPlanEntry -[HAS_SHARE]-> MealShare -[EATEN_BY]-> Person, MealShare -[HAS_PLANNED_CONSUMPTION]->
  QuantitySpecification
      a shared meal's shares: who is to eat it and how many servings, as an entry says today
      for its one eater.
"""

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("Process", "WAS_ASSOCIATED_WITH", "Person", "*", "*", "activities", "wasAssociatedWith"),
    ("NutritionTarget", "TARGET_FOR", "Person", "*", "1", "nutritionTargets", "forPerson"),
    ("ExclusionConstraint", "EXCLUSION_FOR", "Person", "*", "1", "exclusions", "forPerson"),
    ("Person", "HAS_BASELINE", "Plan", "*", "*", "baselineOfPeople", "hasBaseline"),
    ("MealPlan", "FOR_HOUSEHOLD", "Household", "*", "1", "mealPlans", "forHousehold"),
    ("MealPlanEntry", "HAS_SHARE", "MealShare", "1", "*", "shareOf", "hasShare"),
    ("MealShare", "EATEN_BY", "Person", "*", "1", "mealShares", "eatenBy"),
    ("MealShare", "HAS_PLANNED_CONSUMPTION", "QuantitySpecification", "*", "1", "plannedConsumptionOfShares",
     "hasPlannedConsumption"),
]

TYPES = ("Person", "Household", "MealShare")
