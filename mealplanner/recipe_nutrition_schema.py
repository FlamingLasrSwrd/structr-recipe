"""Schema for a recipe version's stored nutrition per serving (data-model.md Sec 18 J28).

  NutrientProfile -[SERVING_OF]-> Plan
      A NutrientProfile with basis `per_serving` describes one serving of what a Plan
      (one version of a recipe) makes, rather than 100 g of a food Type. Its figure is
      calculated from the Plan's ingredients by tools/calculate_recipe_nutrition.py and
      read in place of that calculation. Many to one: a Plan has one per nutrient. A new
      label rather than ABOUT, which NutrientProfile already uses for its food Type: one
      source type with ABOUT edges to two kinds of target has not been tried here.
"""

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("NutrientProfile", "SERVING_OF", "Plan", "*", "1", "servingProfiles", "servingOf"),
]
