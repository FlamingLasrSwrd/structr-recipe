"""Check what the pages show against what the Python tools work out (pages/, tools/install_pages.py).

    python3 tools/check_pages.py

The pages work their figures out again in Structr's JavaScript, so this renders each one as the
superuser (Structr honours the X-User headers for pages) and compares the data block each prints
(#page-data) with Python's answer for the same graph:

  week        every committed entry: cook or leftovers, the recipe, servings cooked and eaten, each
              person's share, and when a dish made ahead must be started (planning/commit.py writes them)
  nutrition   nutrition_scope.nutrition_report: each target's total and status, per meal, day or week;
              week_totals: each daily target's days added up, and its status
  recipes     nutrition_scope.stored_figure for each recipe and nutrient shown
  recipe      one recipe's ingredients and stored figures, for the first recipe in the book; and every
              recipe's instructions, written from its steps' facts, against mealplanner/instructions.py
              for the same Plan as recipe_import.export_plan reads it (J35)
  pantry      inventory.current_magnitude and instance_expiration for every portion on hand
  shopping    shopping.shopping_list: each food to buy, what is needed and on hand, the cost at
              "Home prices" where it exists, and what the pantry covers; a food a StockPolicy
              tops up is left out, since the page applies no policy (and says so)

for every week with entries. Where the Structr methods are installed (tools/install_methods.py), it
compares nutritionReport's and shoppingList's answers with Python's the same way, called as the
superuser. Read-only, so meant for the owner's instance as well as any other. Exits 1 on any difference.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.instructions import instructions
from mealplanner.recipe_import import export_plan
from mealplanner.inventory import current_magnitude, instance_expiration, mass_quality
from mealplanner.prices import price_table
from mealplanner.profiles import ProfileError
from mealplanner.shopping import shopping_list
from mealplanner.nutrition_scope import (
    FMT, _source_plan, active_entries, entry_servings_eaten, nutrition_report, stored_figure, week_totals,
)
from structr_client import ReadCache

TOLERANCE = 1e-6
DATA = re.compile(r'<script type="application/json" id="page-data">(.*?)</script>', re.S)


def page_data(client, path: str):
    r = client.session.get(f"{client.base_url}/structr/html/{path}", timeout=client.timeout)
    r.raise_for_status()
    found = DATA.search(r.text)
    if not found:
        raise ValueError(f"/structr/html/{path} printed no page data")
    return json.loads(found.group(1))


def close(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= TOLERANCE * max(1.0, abs(b))


def utc(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def check_week(client, reads, week: dict, problems: list[str]) -> int:
    shown = {row["entry"]: row for row in page_data(client, f"week/{week['id']}")}
    entries = active_entries(reads, week)
    if set(shown) != {e["name"] for e in entries}:
        problems.append(f"week {week['name']!r}: the page shows {len(shown)} entries, the week has {len(entries)}")
    for entry in entries:
        row = shown.get(entry["name"])
        if row is None:
            continue
        plan = _source_plan(reads, entry)
        start = datetime.strptime(reads.get_all("TemporalRegion", entry["isAbout"]["id"])["result"]["hasBeginning"], FMT)
        start_by = None
        if entry.get("references") and plan.get("makeAheadHours"):
            start_by = start - timedelta(hours=plan["makeAheadHours"])
        shares = {}
        for ref in entry.get("hasShare", []):
            share = reads.get_all("MealShare", ref["id"])["result"]
            shares[reads.get_all("Person", share["eatenBy"]["id"])["result"]["name"]] = entry_servings_eaten(reads, share)[0]
        want = {"kind": "cook" if entry.get("references") else "leftover", "recipe": plan["name"] if plan else None,
                "cooked": entry.get("hasPlannedServings") if entry.get("references") else None,
                "eaten": entry_servings_eaten(reads, entry)[0], "shares": shares, "start": start, "start_by": start_by}
        got = dict(row, start=utc(row["start"]), start_by=utc(row["start_by"]))
        for key, value in want.items():
            if got[key] != value and not (isinstance(value, float) and close(got[key], value)):
                problems.append(f"week {week['name']!r}, {entry['name']}: {key} shown {got[key]!r}, is {value!r}")
    return len(entries)


def method(client, name: str, **arguments):
    """A Structr method's answer, called as the superuser; None when it is not installed."""
    r = client.session.post(f"{client.base_url}/structr/rest/{name}", json=arguments, timeout=client.timeout)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()["result"]


def check_nutrition(client, week: dict, problems: list[str], shown_rows=None, who: str = "the page") -> int:
    if shown_rows is None:
        shown_rows = page_data(client, f"nutrition/{week['id']}")
    shown = {(r["target"], r["group"]): r for r in shown_rows}
    rows = nutrition_report(client, week["id"])
    rows += week_totals(rows)
    if set(shown) != {(r["target"], r["group"]) for r in rows}:
        problems.append(f"nutrition {week['name']!r}: {who} judges {len(shown)} groups, nutrition_report {len(rows)}")
    for r in rows:
        got = shown.get((r["target"], r["group"]))
        if got is None:
            continue
        if got["status"] != r["status"] or not close(got.get("total"), r.get("total")):
            problems.append(f"nutrition {week['name']!r}, {r['target']} {r['group']}: {who} {got.get('total')!r} "
                            f"{got['status']}, nutrition_report {r.get('total')!r} {r['status']}")
    return len(rows)


def check_recipes(client, reads, problems: list[str]) -> int:
    shown, page = [], 1
    while True:                                  # the book, a page at a time
        rows = page_data(client, f"recipes?page={page}")
        if not rows:
            break
        shown, page = shown + rows, page + 1
    nutrients = {}
    for target in sorted(reads.get_all("NutritionTarget")["result"], key=lambda t: (t.get("name") or "", t["id"])):
        if target.get("forNutrient") and target["forNutrient"]["name"] not in nutrients and target.get("hasTargetRange"):
            unit = reads.get_all("QuantitySpecification", target["hasTargetRange"]["id"])["result"].get("unit")
            nutrients[target["forNutrient"]["name"]] = (target["forNutrient"]["id"], unit)
    plans = {p["name"]: p for p in reads.get_all("Plan")["result"]}
    reads.prefetch_where("NutrientProfile", basis="per_serving")      # every stored figure in one listing
    for row in shown:
        plan = plans.get(row["recipe"])
        if plan is None:
            problems.append(f"recipes: {row['recipe']!r} is shown but is no Plan")
            continue
        for name, amount in row["figures"].items():
            nutrient_id, unit = nutrients[name]
            figure = stored_figure(reads, plan, nutrient_id, unit)
            want = None if figure is None else figure.amount
            if not close(amount, want):
                problems.append(f"recipes: {plan['name']}: {name} shown {amount!r}, stored {want!r}")
    if shown:
        plan = plans[shown[0]["recipe"]]
        detail = page_data(client, f"recipe/{plan['id']}")
        stored = [p for p in reads.get_all("NutrientProfile")["result"]
                  if (p.get("servingOf") or {}).get("id") == plan["id"] and p.get("basis") == "per_serving"]
        if len(detail.get("figures", [])) != len(stored):
            problems.append(f"recipe {plan['name']!r}: shows {len(detail.get('figures', []))} figures, {len(stored)} are stored")
    unread = []
    for row in shown:                            # every recipe's instructions, from its steps' facts
        plan = plans.get(row["recipe"])
        if plan is None:
            continue
        try:
            read_back = export_plan(reads, plan["id"])[3]
        except (ValueError, IndexError, KeyError, TypeError):   # not named as the loader names a recipe's parts
            unread.append(plan["name"])
            continue
        written = page_data(client, f"recipe/{plan['id']}").get("instructions")
        if written is None:                      # pages installed before they wrote instructions (J35)
            print("  (the recipe pages here write no instructions yet: tools/install_pages.py)")
            break
        want = instructions(read_back)
        if written != want:
            first = next((k for k, (a, b) in enumerate(zip(want, written or [])) if a != b), None)
            problems.append(f"recipe {plan['name']!r}: the page's instructions differ from Python's"
                            + (f" at step {first + 1}: {written[first]!r}, not {want[first]!r}" if first is not None else
                               f": {len(written or [])} sentences, not {len(want)}"))
    if unread:
        print(f"  ({len(unread)} recipe(s) not made by tools/import_recipe.py, whose instructions are not compared: "
              + ", ".join(unread[:3]) + (", ..." if len(unread) > 3 else "") + ")")
    return len(shown)


def check_pantry(client, reads, problems: list[str]) -> int:
    shown = {row["portion"]: row for row in page_data(client, "pantry")}
    now = datetime.now(timezone.utc)
    counted = 0
    for type_name in ("PortionOfSubstance", "DiscreteWholeItem"):
        for portion in reads.get_all(type_name)["result"]:
            quality = mass_quality(reads, portion)
            grams = current_magnitude(reads, quality["id"], now) if quality else None
            if grams is None or grams <= 1e-9:          # never weighed, or used up: the page leaves it out
                if portion["name"] in shown:
                    problems.append(f"pantry: {portion['name']} is shown, but nothing of it is known to be on hand")
                continue
            counted += 1
            row = shown.get(portion["name"])
            if row is None:
                problems.append(f"pantry: {portion['name']} is on hand ({grams:g} g) but not shown")
                continue
            if not close(row["grams"], grams):
                problems.append(f"pantry: {portion['name']}: shown {row['grams']!r} g, on hand {grams!r} g")
            _, days = instance_expiration(reads, portion, now)
            # the page reads the clock a moment before this does: a day is 86,400 s
            if (days is None) != (row["days"] is None) or (days is not None and abs(row["days"] - days) > 60 / 86400):
                problems.append(f"pantry: {portion['name']}: expires in {row['days']!r} days shown, {days!r} worked out")
    return counted


def check_shopping(client, week: dict, problems: list[str], shown=None, who: str = "the page") -> int:
    if shown is None:
        shown = page_data(client, f"shopping/{week['id']}")
    try:
        prices = price_table(client, "Home prices")
    except ProfileError:
        prices = None
    want = shopping_list(client, week["id"], datetime.now(timezone.utc), prices)
    # the page applies no StockPolicy level, and says so: a food a policy tops up is Python's alone
    topped = {line.food for line in want.to_buy if line.target > 0}
    got = {row["food"]: row for row in shown["to_buy"] if row["food"] not in topped}
    if set(got) != {line.food for line in want.to_buy} - topped:
        problems.append(f"shopping {week['name']!r}: {who} lists "
                        f"{sorted(set(got) ^ ({l.food for l in want.to_buy} - topped))} differently")
    for line in want.to_buy:
        row = got.get(line.food)
        if row is None:
            continue
        for key, value in (("buy", line.buy), ("need", line.need), ("have", line.have), ("cost", line.cost)):
            if not close(row[key], value):
                problems.append(f"shopping {week['name']!r}, {line.food}: {key} by {who} {row[key]!r}, is {value!r}")
        if utc(row["first"]) != line.first_needed:
            problems.append(f"shopping {week['name']!r}, {line.food}: first needed by {who} {row['first']!r}, is {line.first_needed!r}")
    if sorted(r["food"] for r in shown["covered"]) != [line.food for line in want.covered]:
        problems.append(f"shopping {week['name']!r}: the pantry covers differ ({who})")
    if shown["unquantified"] != want.unquantified or sorted(shown["not_bought"]) != want.not_bought:
        problems.append(f"shopping {week['name']!r}: what has no amount, or is not bought, differs ({who})")
    return len(want.to_buy)


def main(argv=None) -> int:
    client = connect(owner_data_ok=True)     # read-only
    client.wait_until_ready()
    reads = ReadCache(client)
    problems: list[str] = []
    weeks = [w for w in reads.get_all("MealPlan")["result"] if w.get("hasEntry")]
    for week in weeks:
        entries = check_week(client, reads, week, problems)
        groups = check_nutrition(client, week, problems)
        bought = check_shopping(client, week, problems)
        print(f"{week['name']}: {entries} entries, {groups} target groups, {bought} foods to buy")
        report = method(client, "nutritionReport", week=week["id"])
        listed = method(client, "shoppingList", week=week["id"])
        if report is None or listed is None:
            print("  (the methods are not installed here: tools/install_methods.py)")
            continue
        for answer in (report, listed):
            if answer.get("problem"):
                problems.append(f"{week['name']!r}: a method answered {answer['problem']}")
        if not report.get("problem"):
            check_nutrition(client, week, problems, report["rows"], "nutritionReport")
        if not listed.get("problem"):
            check_shopping(client, week, problems, {"to_buy": listed["buy"], "covered": listed["covered"],
                                                    "unquantified": listed["unquantified"], "not_bought": listed["not_bought"]},
                           "shoppingList")
        print("  and the same through nutritionReport and shoppingList")
    print(f"recipes: {check_recipes(client, reads, problems)} shown")
    print(f"pantry: {check_pantry(client, reads, problems)} portions on hand")
    for problem in problems:
        print(f"difference: {problem}")
    print(f"{len(problems)} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
