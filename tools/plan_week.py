"""Plan a week of the owner's meals: propose every slot, report the nutrients, and (with --commit) write it.

    python3 tools/plan_week.py private/week.toml            # propose; writes only the week's MealPlan
    python3 tools/plan_week.py private/week.toml --commit   # also write the proposed meals as entries

private/week.toml:
    start = 2026-10-05                  # the first day
    days = 7
    timezone = "America/Denver"         # the meal times are local
    household = "Home"                  # the household the week feeds (tools/instantiate_household.py):
                                        # its people, each with their own targets and baseline
    meals = [{ type = "Breakfast", at = "08:00", eaters = ["Elijah"] },    # eaters: who eats it (default: all)
             { type = "Lunch", at = "12:30" }, { type = "Dinner", at = "18:30" }]
    targets = "Daily "                  # the standing NutritionTargets: names starting with this
    leftovers = true
    leftover_days = 3                   # how long cooked food keeps, if the data gives no ShelfLife for it
    portions = [0.75, 1, 1.25, 1.5]     # servings a meal may be; default: one serving each
    [portions_by_person]                # someone's own levels, where they differ
    Cass = [0.5, 0.75, 1]
    time_limit_s = 30
    prices = "Home prices"              # optional: report the week's cost at this price level
    [weights]                           # optional: written onto the MealPlan (optimizer-design Sec 4.5)
    time = 0.5
    variety = 0.5
    time_budget_minutes = 60

Without `household`, the week has one eater, as before households: `baseline = [...]` names
what is counted every day, and the targets are those with the prefix that belong to no one.
The week's MealPlan is "Week of <start>", about a TemporalRegion spanning its days, with
the targets and the baseline attached. Meals already committed to it are kept and planned
around (a slot they hold is not proposed again). After the plan, the nutrient report
(mealplanner/planning/nutrients.py): what the week meets, misses, or cannot meet with the
recipes there are, and how the weeks committed so far have done on each target; then, if
the file names a price level, what the week's meals cost (mealplanner/prices.py).
"""

import argparse
import os
import sys
import tomllib
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.household import latest_plan as household_latest_plan
from mealplanner.profiles import ProfileError
from mealplanner.nutrition_scope import active_entries, entry_start, nutrition_report
from mealplanner.planning.extract import SlotSpec
from mealplanner.planning.nutrients import describe_nutrients
from mealplanner.planning.plan import plan_week
from mealplanner.prices import describe_cost
from mealplanner.vocabulary_import import Sync

STRUCTR_TIME = "%Y-%m-%dT%H:%M:%S%z"


class WeekError(ValueError):
    pass


def read_week(path: str) -> dict:
    with open(path, "rb") as fh:
        week = tomllib.load(fh)
    problems = []
    if not isinstance(week.get("start"), date):
        problems.append("start must be a date, like 2026-10-05")
    try:
        week["zone"] = ZoneInfo(week.get("timezone", "UTC"))
    except Exception:
        problems.append(f"timezone {week.get('timezone')!r} is not an IANA zone name (for example America/Denver)")
    for meal in week.get("meals", []):
        try:
            meal["time"] = time.fromisoformat(meal["at"])
        except (KeyError, ValueError):
            problems.append(f"meal {meal!r}: `at` must be a time like \"18:30\"")
    def servings_list(value) -> bool:
        return isinstance(value, list) and all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in value)

    portions = week.get("portions", [])
    if not servings_list(portions):
        problems.append(f"portions must be a list of servings above 0, like [0.75, 1, 1.5], not {portions!r}")
    for person, levels in week.get("portions_by_person", {}).items():
        if not servings_list(levels) or not levels:
            problems.append(f"portions_by_person {person!r} must be a list of servings above 0, not {levels!r}")
    household = week.get("household")
    if household is None:
        if week.get("portions_by_person") or any("eaters" in meal for meal in week.get("meals", [])):
            problems.append("eaters and portions_by_person need a household (household = \"Home\")")
    elif week.get("baseline"):
        problems.append("in a household's week each person's baseline is their own (private/household.toml), not the week's")
    for meal in week.get("meals", []):
        eaters = meal.get("eaters")
        if eaters is not None and (not isinstance(eaters, list) or not eaters or not all(isinstance(e, str) for e in eaters)):
            problems.append(f"meal {meal!r}: eaters is a list of names")
    if not week.get("meals"):
        problems.append("meals: give at least one, like { type = \"Dinner\", at = \"18:30\" }")
    if problems:
        raise WeekError(problems)
    return week


def latest_plan(client, name: str) -> dict:
    """The newest version of the recipe (or baseline) with this name: "<name> v<n>"."""
    try:
        return household_latest_plan(client, name)
    except ProfileError as exc:
        raise WeekError(exc.problems) from exc


def ensure_week(client, week: dict) -> str:
    """The week's MealPlan, its region, targets and baseline, written by name (idempotent)."""
    sync = Sync(client)
    name = week.get("name") or f"Week of {week['start'].isoformat()}"
    zone = week["zone"]
    begin = datetime.combine(week["start"], time(0), zone)
    end = begin + timedelta(days=week.get("days", 7))
    region = sync.ensure("TemporalRegion", f"{name} region", {
        "hasBeginning": begin.strftime(STRUCTR_TIME), "hasEnd": end.strftime(STRUCTR_TIME)})
    prefix = week.get("targets", "Daily ")
    household = None
    if week.get("household"):
        household = sync.rows("Household").get(week["household"])
        if household is None:
            raise WeekError([f"no household {week['household']!r} (tools/instantiate_household.py)"])
        members = {m["id"] for m in client.get_all("Household", household["id"])["result"].get("members", [])}
        targets = sorted(r["id"] for r in sync.rows("NutritionTarget").values()
                         if r["name"].startswith(prefix) and (r.get("forPerson") or {}).get("id") in members)
    else:
        targets = sorted(r["id"] for r in sync.rows("NutritionTarget").values()
                         if r["name"].startswith(prefix) and not r.get("forPerson"))
    if not targets:
        raise WeekError([f"no NutritionTarget named {prefix!r}... for this week's eaters "
                         f"(tools/instantiate_profile.py nutrition, or tools/instantiate_household.py)"])
    baseline = sorted(latest_plan(client, b)["id"] for b in week.get("baseline", []))
    fields = {"isAbout": region, "hasConstraint": targets, "hasBaseline": baseline,
              "forHousehold": household["id"] if household else None}
    weights = week.get("weights", {})
    for key, field_name in (("time", "timeBudgetWeight"), ("variety", "varietyWeight"),
                            ("time_budget_minutes", "timeBudgetMinutes")):
        if key in weights:
            fields[field_name] = float(weights[key])
    return sync.ensure("MealPlan", name, fields)


def template(client, meal_plan_id: str, week: dict) -> list[SlotSpec]:
    """A slot for every meal of every day, except where a committed meal already is."""
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    taken = {entry_start(client, e) for e in active_entries(client, meal_plan)}
    slots = []
    for d in range(week.get("days", 7)):
        day = week["start"] + timedelta(days=d)
        for meal in week["meals"]:
            start = datetime.combine(day, meal["time"], week["zone"])
            if start.astimezone(timezone.utc) in {t.astimezone(timezone.utc) for t in taken if t}:
                continue
            eaters = tuple(meal["eaters"]) if meal.get("eaters") else None
            slots.append(SlotSpec(start, meal["type"], f"{day.strftime('%a %d %b')} {meal['type']}", eaters))
    return slots


def history(client, this_week: str) -> str:
    """How the committed weeks so far have done on each target: the part of the report
    that says which nutrients keep being missed."""
    rows = []
    for plan in client.get_all("MealPlan")["result"]:
        if plan["id"] == this_week or not plan.get("hasEntry"):
            continue
        rows.extend(nutrition_report(client, plan["id"]))
    if not rows:
        return "No committed weeks yet: nothing to say about what keeps being missed."
    tally: dict[str, list[int]] = {}
    for row in rows:
        if row.get("status") in ("ok", "below_min", "above_max"):
            counts = tally.setdefault(row["nutrient"], [0, 0, 0])
            counts[("ok", "below_min", "above_max").index(row["status"])] += 1
    lines = ["Committed weeks so far:"]
    for nutrient, (ok, low, high) in sorted(tally.items(), key=lambda kv: -(kv[1][1] + kv[1][2])):
        if low or high:
            parts = ([f"under on {low}"] if low else []) + ([f"over on {high}"] if high else [])
            lines.append(f"  {nutrient}: {' and '.join(parts)} of {ok + low + high} days")
    return "\n".join(lines if len(lines) > 1 else lines + ["  every target met on every committed day"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("week", help="the week file, e.g. private/week.toml")
    parser.add_argument("--commit", action="store_true", help="write the proposed meals as MealPlanEntries")
    args = parser.parse_args(argv)
    client = connect(owner_data_ok=True)     # the owner's weeks are their own data
    client.wait_until_ready()
    try:
        week = read_week(args.week)
        meal_plan_id = ensure_week(client, week)
        slots = template(client, meal_plan_id, week)
    except WeekError as exc:
        for problem in exc.args[0]:
            print(f"problem: {problem}")
        return 1
    result = plan_week(client, meal_plan_id, slots, datetime.now(timezone.utc), commit=args.commit,
                       leftovers=week.get("leftovers", True), leftover_days=week.get("leftover_days"),
                       portions=tuple(week.get("portions", [])),
                       eater_portions={p: tuple(v) for p, v in week.get("portions_by_person", {}).items()},
                       time_limit_s=float(week.get("time_limit_s", 30)))
    print(result.text())
    if result.evaluation is not None:
        print()
        print(describe_nutrients(result.problem, result.evaluation))
        if week.get("prices"):
            print()
            print(describe_cost(client, result.problem, result.evaluation, week["prices"], week.get("days", 7)))
        if args.commit:
            print(f"\ncommitted {len(result.committed)} entries")
        else:
            print("\n(proposed only: run with --commit to write it)")
    print()
    print(history(client, meal_plan_id))
    return 0 if result.evaluation is not None else 1


if __name__ == "__main__":
    sys.exit(main())
