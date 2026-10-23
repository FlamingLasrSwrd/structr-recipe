"""Schema for a dish made ahead (data-model.md Sec 18 J29).

  Plan.makeAheadHours (Double)
      How long before the meal a recipe must be started, for the waiting no one
      attends: overnight oats soaking 8 hours, a dough rising, a marinade. Its
      minutes (estimatedDurationMinutes) stay the time spent working, which the
      time budget scores. The planner will not plan it for a meal less than this
      long after the plan is made, and the week's report says when to start it.
      A plain property on an already-populated concrete type, the safe kind of
      addition (scoring_schema.py's notes), not a trait.
"""

PROPERTIES: dict[str, list[dict]] = {
    "Plan": [
        {"name": "makeAheadHours", "propertyType": "Double"},
    ],
}
