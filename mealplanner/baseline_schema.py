"""Schema for the daily baseline (data-model.md Sec 18 J25).

  MealPlan -[HAS_BASELINE]-> Plan
      The Plans a MealPlan counts as eaten every day, outside its planned meals:
      supplements, the morning coffee. A baseline Plan is written like a recipe
      (recipe-format.md, `baseline = true`), one serving being one day of it, and
      is attached to a MealPlan as its standing NutritionTargets are. Many to
      many: one baseline serves every week, and a week may count several.
"""

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("MealPlan", "HAS_BASELINE", "Plan", "*", "*", "baselineOf", "hasBaseline"),
]
