"""Recipes asked for a week from the recipe pages (data-model.md Sec 18 J33; pages/recipe.js).

The owner asked (2026-10-24) for a button on each recipe page to cook it next week, as the week
file's `cook = [...]` does (model.Request; the owner's decision, 2026-10-23: a recipe cooked at
least once that week, the planner choosing when, how much and who eats the leftovers). A page
cannot write the week file, so a request is kept on the week's MealPlan, MealPlan
-[REQUESTS_RECIPE]-> RecipeIdentity, and planning/extract.build_problem reads it beside the file's.

The week asked for is the next one to plan (next_week_start): the week after the latest one with
meals committed, or, once that has begun, the first on the same weekday from today; with none
committed yet, the coming Monday. tools/plan_week.py finds the week's MealPlan by its name,
"Week of <start>", so a request for a week not yet planned makes the MealPlan by that name, and
the planner fills in its days, targets and baseline when the week is planned.

pages/recipe.js does the same, function by function.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

WEEK_NAME = "Week of {}"
_WEEK = re.compile(r"^Week of (\d{4}-\d{2}-\d{2})$")
SEEN = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False}


class RequestBookingError(ValueError):
    pass


def week_start(meal_plan: dict) -> date | None:
    """The first day of a week named as tools/plan_week.py names it ("Week of 2026-10-26")."""
    found = _WEEK.match(meal_plan.get("name") or "")
    return date.fromisoformat(found.group(1)) if found else None


def next_week_start(client, today: date) -> date:
    """The first day of the next week to plan."""
    starts = [s for m in client.get_all("MealPlan")["result"] if m.get("hasEntry") and (s := week_start(m))]
    if not starts:
        return today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    start = max(starts) + timedelta(days=7)
    while start < today:
        start += timedelta(days=7)
    return start


def _week(client, start: date) -> dict | None:
    name = WEEK_NAME.format(start.isoformat())
    found = [r for r in client.get("/structr/rest/MealPlan", params={"name": name})["result"] if r.get("type") == "MealPlan"]
    if len(found) > 1:
        raise RequestBookingError(f"two MealPlans are named {name!r}")
    return client.get_all("MealPlan", found[0]["id"])["result"] if found else None


def requested(client, start: date) -> list[dict]:
    """The recipes (RecipeIdentity rows: id, name) asked for the week starting `start`."""
    week = _week(client, start)
    return list(week.get("requestsRecipe") or []) if week else []


def ask(client, recipe_id: str, start: date) -> bool:
    """Ask for the recipe in the week starting `start`, making the week's MealPlan if it is not
    there yet. False if it was asked for already (nothing is written)."""
    week = _week(client, start)
    if week is None:
        made = client.post("/structr/rest/MealPlan", {"name": WEEK_NAME.format(start.isoformat()), **SEEN})["result"][0]
        week = client.get_all("MealPlan", made)["result"]
    current = [r["id"] for r in week.get("requestsRecipe") or []]
    if recipe_id in current:
        return False
    client.patch(f"/structr/rest/MealPlan/{week['id']}", {"requestsRecipe": current + [recipe_id]})
    return True


def withdraw(client, recipe_id: str, start: date) -> bool:
    """No longer ask for the recipe that week. False if it was not asked for. The MealPlan stays."""
    week = _week(client, start)
    current = [r["id"] for r in (week or {}).get("requestsRecipe") or []]
    if recipe_id not in current:
        return False
    client.patch(f"/structr/rest/MealPlan/{week['id']}", {"requestsRecipe": [r for r in current if r != recipe_id]})
    return True
