"""Schema for a recipe asked for a week from the recipe pages (data-model.md Sec 18 J33).

  MealPlan -[REQUESTS_RECIPE]-> RecipeIdentity
      The recipes the owner asked to have cooked in a week, at least once each, the planner
      choosing when (model.Request): what the week file's `cook = [...]` says, written from a
      recipe page's "Cook in the week of ..." button (pages/recipe.js, mealplanner/requests.py).
      To the RecipeIdentity, so any version of it answers. Many to many: a week asks for
      several recipes, and a recipe may be asked for in several weeks. One relationship on
      existing types, as MealPlan -[HAS_BASELINE]-> Plan was (J25), not a new type.
"""

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("MealPlan", "REQUESTS_RECIPE", "RecipeIdentity", "*", "*", "requestedIn", "requestsRecipe"),
]
