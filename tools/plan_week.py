"""Plan a week of the owner's meals: propose every slot, report the nutrients, and (with --commit) write it.

    python3 tools/plan_week.py private/week.toml            # propose; writes only the week's MealPlan
    python3 tools/plan_week.py private/week.toml --commit   # write the week proposed last as entries
    python3 tools/plan_week.py private/week.toml --commit --fresh   # search again and write that

A proposal is kept beside the week file (private/week.proposal.json; planning/proposal.py), and
--commit writes that week, the one the owner reviewed, after reading the graph again and checking
it still meets every hard target (the owner's decision, 2026-10-23): a search under a time limit
is not repeatable to the meal. With no proposal kept for the week, or with --fresh, it searches
and writes what it finds, as before. The proposal file is removed once it is committed.

private/week.toml:
    start = 2026-10-05                  # the first day
    days = 7
    timezone = "America/Edmonton"         # the meal times are local
    household = "Home"                  # the household the week feeds (tools/instantiate_household.py):
                                        # its people, each with their own targets and baseline
    meals = [{ type = "Breakfast", at = "08:00", eaters = ["Jamie"] },    # eaters: who eats it (default: all)
             { type = "Lunch", at = "12:30" }, { type = "Dinner", at = "18:30" }]
    targets = "Daily "                  # the standing NutritionTargets: names starting with this
    leftovers = true
    leftover_days = 3                   # how long cooked food keeps, if the data gives no ShelfLife for it
    portions = [0.75, 1, 1.25, 1.5]     # servings a meal may be; default: one serving each
    [portions_by_person]                # someone's own levels, where they differ
    Alex = [0.5, 0.75, 1]
    total_time_s = 300                  # the whole run, about five minutes: the search has what reading leaves
                                        # (or time_limit_s = 30: the search's own limit, whatever reading takes)
    shortlist_above = 60                # optional: a larger recipe book is searched through a shortlist
                                        # of the best fits to the week (mealplanner/planning/shortlist.py)
    prices = "Home prices"              # optional: report the week's cost at this price level
    cook = ["Adobo loco steak", { recipe = "Balsamic fig chicken", on = "Wed Dinner" }]
                                        # optional: recipes to cook this week, each at least once (twice if
                                        # listed twice); the planner picks the meal, portions and leftovers,
                                        # unless `on` names the meal ("Wed Dinner" or "Wed 28 Oct Dinner").
                                        # The recipes asked for the week from the recipe pages' "Cook in
                                        # the week of ..." button are added, once each (mealplanner/requests.py)
    repeat_tolerance = 2                # optional: how many meals of the week one recipe may be, fresh, as
                                        # leftovers or made at a prep session, before each more costs
                                        # [weights] repeats points (1 unless given); this week only. 1: the same
                                        # meal twice costs; 2: cook once, eat twice; left out: nothing counted,
                                        # the variety weight alone spacing repeats
    prep = [{ at = "Sun 14:00", minutes = 180, dishes = 3 }]
                                        # optional: meal-prep sessions. A dish may be made at one and eaten at
                                        # later meals while it keeps; the session's minutes of work and number
                                        # of dishes are hard limits. The weekday is the first such day from the
                                        # day before `start` (so "Sun" before a Monday start is the day before)
    [weights]                           # optional: written onto the MealPlan (optimizer-design Sec 4.5)
    time = 0.5
    variety = 0.5
    time_budget_minutes = 60
    stock = 0.5                         # optional: how much using what the pantry holds counts, and using
    waste = 0.5                         # what will expire soonest (both 0 unless given); with a week under
                                        # way, they steer the free meals to what was bought for skipped ones
    repeats = 1                         # this week only, not written: points off per meal over repeat_tolerance;
                                        # 1 weighs a meal over about as cooking_time = 1 weighs an hour of work
    cooking_time = 1                    # this week only, not written: points off per hour of the week's
                                        # cooking. 0 (the default) ignores it; about 0.5 a little, 1 a busy
                                        # week, 2-4 a very busy one (measured: 610 min of cooking fell to
                                        # 465 at 0.5-2 and 415 at 4, a 0.3-0.4 lower score otherwise)

Changing the menu as the week goes (the week page's "Didn't make it"; mealplanner/menu_changes.py): a
skipped meal with nothing eaten instead is free. Once the week has meals committed, running this again
plans only the free meals still to come, around everything else, and --commit writes them.

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
import json
import os
import sys
import tomllib
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.household import latest_plan as household_latest_plan
from mealplanner.profiles import ProfileError
from mealplanner.nutrition_scope import active_entries, eaten_instead_entries, entry_start, nutrition_report
from mealplanner.planning.extract import RequestError, SlotSpec
from mealplanner.planning.model import PrepSession
from mealplanner.planning.nutrients import describe_nutrients
from mealplanner.planning.plan import plan_week
from mealplanner.planning.proposal import ProposalError, to_data
from mealplanner.prices import describe_cost
from mealplanner.requests import week_start
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
        problems.append(f"timezone {week.get('timezone')!r} is not an IANA zone name (for example America/Edmonton)")
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
    total = week.get("total_time_s")
    if total is not None:
        if isinstance(total, bool) or not isinstance(total, (int, float)) or total <= 0:
            problems.append(f"total_time_s must be a number of seconds above 0, like 300, not {total!r}")
        elif "time_limit_s" in week:
            problems.append("give total_time_s (the whole run) or time_limit_s (the search alone), not both")
    requests = []
    for item in week.get("cook", []):
        if isinstance(item, str):
            item = {"recipe": item}
        if not isinstance(item, dict) or not isinstance(item.get("recipe"), str) or set(item) - {"recipe", "on"} \
                or not isinstance(item.get("on", ""), str):
            problems.append(f"cook: {item!r} is a recipe's name, or {{ recipe = \"...\", on = \"Wed Dinner\" }}")
            continue
        requests.append((item["recipe"], item.get("on")))
    week["requests"] = tuple(requests)
    week["preps"] = ()
    if isinstance(week.get("start"), date) and "zone" in week:
        try:
            week["preps"] = prep_sessions(week)
        except WeekError as exc:
            problems.extend(exc.args[0])
    cooking = week.get("weights", {}).get("cooking_time", 0)
    if isinstance(cooking, bool) or not isinstance(cooking, (int, float)) or cooking < 0:
        problems.append(f"[weights] cooking_time is points an hour, 0 or more, like 1, not {cooking!r}")
    for key in ("stock", "waste"):
        value = week.get("weights", {}).get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            problems.append(f"[weights] {key} is a weight, 0 or more, like 0.5, not {value!r}")
    tolerance = week.get("repeat_tolerance")
    if tolerance is not None and (isinstance(tolerance, bool) or not isinstance(tolerance, int) or tolerance < 1):
        problems.append(f"repeat_tolerance is how many meals of the week one recipe may be, like 2, not {tolerance!r}")
    repeats = week.get("weights", {}).get("repeats", 1)
    if isinstance(repeats, bool) or not isinstance(repeats, (int, float)) or repeats < 0:
        problems.append(f"[weights] repeats is points off per meal over the repeat_tolerance, 0 or more, like 1, not {repeats!r}")
    above = week.get("shortlist_above")
    if above is not None and (isinstance(above, bool) or not isinstance(above, int) or above < 1):
        problems.append(f"shortlist_above must be a whole number of recipes, like 60, not {above!r}")
    if problems:
        raise WeekError(problems)
    return week


def prep_sessions(week: dict) -> tuple:
    """The week file's prep sessions: `at` a weekday and time, its `minutes` and `dishes`."""
    sessions, problems = [], []
    first = week["start"] - timedelta(days=1)
    for raw in week.get("prep", []):
        day, _, at = str(raw.get("at", "")).partition(" ") if isinstance(raw, dict) else ("", "", "")
        try:
            clock = time.fromisoformat(at.strip())
        except ValueError:
            problems.append(f"prep {raw!r}: `at` is a weekday and a time, like \"Sun 14:00\"")
            continue
        dates = [first + timedelta(days=d) for d in range(week.get("days", 7) + 1)
                 if (first + timedelta(days=d)).strftime("%a").lower() == day[:3].lower()]
        minutes, dishes = raw.get("minutes"), raw.get("dishes", 2)
        if not dates:
            problems.append(f"prep {raw!r}: {day!r} is not a weekday of this week")
        elif isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes <= 0:
            problems.append(f"prep {raw!r}: `minutes` is the working time it has, like 180")
        elif isinstance(dishes, bool) or not isinstance(dishes, int) or dishes < 1:
            problems.append(f"prep {raw!r}: `dishes` is how many dishes at most, like 3")
        else:
            key = f"{dates[0].strftime('%a %d %b')} Prep"
            if any(s.key == key for s in sessions):
                problems.append(f"prep: two sessions on {dates[0]:%a %d %b}; plan one")
                continue
            sessions.append(PrepSession(key, datetime.combine(dates[0], clock, week["zone"]), float(minutes), dishes))
    if problems:
        raise WeekError(problems)
    return tuple(sorted(sessions, key=lambda s: s.start))


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
    for key, field_name in (("time", "timeBudgetWeight"), ("variety", "varietyWeight"), ("stock", "stockWeight"),
                            ("waste", "wasteWeight"), ("time_budget_minutes", "timeBudgetMinutes")):
        if key in weights:
            fields[field_name] = float(weights[key])
    return sync.ensure("MealPlan", name, fields)


def requests_elsewhere(client, meal_plan_id: str, today: date) -> list[str]:
    """Recipes asked for from the recipe pages for a week not yet planned and not yet over, other
    than this one (mealplanner/requests.py): a week file starting on another day leaves them out."""
    lines = []
    for plan in client.get_all("MealPlan")["result"]:
        if plan["id"] == meal_plan_id or plan.get("hasEntry") or not plan.get("requestsRecipe"):
            continue
        start = week_start(plan)
        if start is None or start + timedelta(days=7) <= today:
            continue
        names = ", ".join(sorted(r["name"] for r in plan["requestsRecipe"]))
        lines.append(f"note: {plan['name']}, not this week, has recipes asked for from the recipe pages: {names}")
    return lines


def template(client, meal_plan_id: str, week: dict, now: datetime | None = None, notes: list | None = None) -> list[SlotSpec]:
    """A slot for every meal of every day, except where a committed meal already is, or a skipped
    one with something else eaten in its place (mealplanner/menu_changes.py). Once the week has
    meals committed, it is under way: a meal skipped before `now` is not planned again, only the
    free meals still to come."""
    meal_plan = client.get_all("MealPlan", meal_plan_id)["result"]
    taken = {entry_start(client, e) for e in active_entries(client, meal_plan) + eaten_instead_entries(client, meal_plan)}
    taken = {t.astimezone(timezone.utc) for t in taken if t}
    under_way = now is not None and bool(meal_plan.get("hasEntry"))
    slots, past = [], 0
    for d in range(week.get("days", 7)):
        day = week["start"] + timedelta(days=d)
        for meal in week["meals"]:
            start = datetime.combine(day, meal["time"], week["zone"])
            if start.astimezone(timezone.utc) in taken:
                continue
            if under_way and start < now:
                past += 1
                continue
            eaters = tuple(meal["eaters"]) if meal.get("eaters") else None
            slots.append(SlotSpec(start, meal["type"], f"{day.strftime('%a %d %b')} {meal['type']}", eaters))
    if past and notes is not None:
        notes.append(f"the week is under way: {past} free meal{'s' if past != 1 else ''} already past "
                     f"{'are' if past != 1 else 'is'} not planned again")
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
    started = monotonic()                    # total_time_s counts from here
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("week", help="the week file, e.g. private/week.toml")
    parser.add_argument("--commit", action="store_true", help="write the week proposed last as MealPlanEntries")
    parser.add_argument("--fresh", action="store_true", help="with --commit: search again instead of writing the proposal")
    args = parser.parse_args(argv)
    kept = os.path.splitext(args.week)[0] + ".proposal.json"
    client = connect(owner_data_ok=True)     # the owner's weeks are their own data
    client.wait_until_ready()
    try:
        week = read_week(args.week)
        meal_plan_id = ensure_week(client, week)
        under_way: list[str] = []
        slots = template(client, meal_plan_id, week, datetime.now(timezone.utc), under_way)
        for line in under_way:
            print(f"note: {line}")
        for line in requests_elsewhere(client, meal_plan_id, datetime.now(week["zone"]).date()):
            print(line)
    except WeekError as exc:
        for problem in exc.args[0]:
            print(f"problem: {problem}")
        return 1
    if week.get("total_time_s") is not None:
        limits = {"deadline": started + float(week["total_time_s"])}
    else:
        limits = {"time_limit_s": float(week.get("time_limit_s", 30))}
    proposal = None
    if args.commit and not args.fresh and os.path.exists(kept):
        with open(kept, encoding="utf-8") as fh:
            proposal = json.load(fh)
        if proposal.get("week") != week["start"].isoformat():
            print(f"problem: {kept} is the proposal for the week of {proposal.get('week')}, not {week['start']}; "
                  f"propose this week first, or use --fresh")
            return 1
        print(f"committing the week proposed at {proposal.get('proposed')} (score then {proposal.get('score', 0):.3f}), kept in {kept}")
    try:
        result = plan_week(client, meal_plan_id, slots, datetime.now(timezone.utc), commit=args.commit,
                           leftovers=week.get("leftovers", True), leftover_days=week.get("leftover_days"),
                           portions=tuple(week.get("portions", [])),
                           eater_portions={p: tuple(v) for p, v in week.get("portions_by_person", {}).items()},
                           proposal=proposal, requests=week["requests"], preps=week["preps"],
                           cooking_time=float(week.get("weights", {}).get("cooking_time", 0)),
                           repeat_tolerance=week.get("repeat_tolerance"),
                           repeat_weight=float(week.get("weights", {}).get("repeats", 1)),
                           **limits, **({"shortlist_above": week["shortlist_above"]} if "shortlist_above" in week else {}))
    except RequestError as exc:
        print(f"problem: {exc}")
        return 1
    except ProposalError as exc:
        print(f"problem: the kept proposal cannot be committed: {exc}")
        print("nothing was written; propose the week again, or commit with --fresh")
        return 1
    print(result.text())
    if result.evaluation is not None:
        print()
        print(describe_nutrients(result.problem, result.evaluation))
        if week.get("prices"):
            print()
            print(describe_cost(client, result.problem, result.evaluation, week["prices"], week.get("days", 7)))
        if args.commit:
            print(f"\ncommitted {len(result.committed)} entries")
            if proposal is not None:
                os.remove(kept)
        else:
            with open(kept, "w", encoding="utf-8") as fh:
                json.dump(to_data(result.problem, result.evaluation, week["start"].isoformat()), fh, indent=1)
            print(f"\n(proposed only: run with --commit to write this week; it is kept in {kept})")
    print()
    print(history(client, meal_plan_id))
    return 0 if result.evaluation is not None else 1


if __name__ == "__main__":
    sys.exit(main())
