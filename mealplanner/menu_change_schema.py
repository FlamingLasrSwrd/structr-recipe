"""Schema for changing a committed week as it goes (data-model.md Sec 18 J34).

  MealPlanEntry.eatenInstead (String)
      What was eaten in place of a skipped meal (isSkipped), when it is not a recipe in the book:
      "takeout", "dinner at Sam's". Its nutrition is not known, so the meal's people's targets for
      that scope are unknown, not short. A recipe from the book eaten instead is an entry of its own.
      A plain property on an already-populated concrete type, the safe kind of addition
      (scoring_schema.py's notes), not a trait.
"""

PROPERTIES: dict[str, list[dict]] = {
    "MealPlanEntry": [
        {"name": "eatenInstead", "propertyType": "String"},
    ],
}
