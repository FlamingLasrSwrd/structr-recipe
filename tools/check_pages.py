"""Check what the pages show against what the Python tools work out (pages/, tools/install_pages.py).

    python3 tools/check_pages.py

The pages work their figures out again in Structr's JavaScript, so this renders each one as the
superuser (Structr honours the X-User headers for pages) and compares the data block each prints
(#page-data) with Python's answer for the same graph:

  week        every committed entry: cook or leftovers, the recipe, servings cooked and eaten, each
              person's share, and when a dish made ahead must be started (planning/commit.py writes them)
  nutrition   nutrition_scope.nutrition_report: each target's total and status, per meal, day or week
  recipes     nutrition_scope.stored_figure for each recipe and nutrient shown
  recipe      one recipe's ingredients and stored figures, for the first recipe in the book
  pantry      inventory.current_magnitude and instance_expiration for every portion on hand
  shopping    shopping.shopping_list: each food to buy, what is needed and on hand, the cost at
              "Home prices" where it exists, and what the pantry covers

for every week with entries. Read-only, so meant for the owner's instance as well as any other.
Exits 1 on any difference.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.inventory import current_magnitude, instance_expiration, mass_quality
from mealplanner.prices import price_table
from mealplanner.profiles import ProfileError
from mealplanner.shopping import shopping_list
from mealplanner.nutrition_scope import (
    FMT, _source_plan, active_entries, entry_servings_eaten, nutrition_report, stored_figure,
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


def check_nutrition(client, week: dict, problems: list[str]) -> int:
    shown = {(r["target"], r["group"]): r for r in page_data(client, f"nutrition/{week['id']}")}
    rows = nutrition_report(client, week["id"])
    if set(shown) != {(r["target"], r["group"]) for r in rows}:
        problems.append(f"nutrition {week['name']!r}: the page judges {len(shown)} groups, nutrition_report {len(rows)}")
    for r in rows:
        got = shown.get((r["target"], r["group"]))
        if got is None:
            continue
        if got["status"] != r["status"] or not close(got.get("total"), r.get("total")):
            problems.append(f"nutrition {week['name']!r}, {r['target']} {r['group']}: shown {got.get('total')!r} "
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
    return len(shown)


def check_pantry(client, reads, problems: list[str]) -> int:
    shown = {row["portion"]: row for row in page_data(client, "pantry")}
    now = datetime.now(timezone.utc)
    counted = 0
    for type_name in ("PortionOfSubstance", "DiscreteWholeItem"):
        for portion in reads.get_all(type_name)["result"]:
            quality = mass_quality(reads, portion)
            grams = current_magnitude(reads, quality["id"], now) if quality else None
            if grams is None:
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


def check_shopping(client, week: dict, problems: list[str]) -> int:
    shown = page_data(client, f"shopping/{week['id']}")
    try:
        prices = price_table(client, "Home prices")
    except ProfileError:
        prices = None
    want = shopping_list(client, week["id"], datetime.now(timezone.utc), prices)
    got = {row["food"]: row for row in shown["to_buy"]}
    if set(got) != {line.food for line in want.to_buy}:
        problems.append(f"shopping {week['name']!r}: the page lists {sorted(set(got) ^ {l.food for l in want.to_buy})} differently")
    for line in want.to_buy:
        row = got.get(line.food)
        if row is None:
            continue
        for key, value in (("buy", line.buy), ("need", line.need), ("have", line.have), ("cost", line.cost)):
            if not close(row[key], value):
                problems.append(f"shopping {week['name']!r}, {line.food}: {key} shown {row[key]!r}, is {value!r}")
        if utc(row["first"]) != line.first_needed:
            problems.append(f"shopping {week['name']!r}, {line.food}: first needed {row['first']!r}, is {line.first_needed!r}")
    if sorted(r["food"] for r in shown["covered"]) != [line.food for line in want.covered]:
        problems.append(f"shopping {week['name']!r}: the pantry covers differ")
    if shown["unquantified"] != want.unquantified or sorted(shown["not_bought"]) != want.not_bought:
        problems.append(f"shopping {week['name']!r}: what has no amount, or is not bought, differs")
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
    print(f"recipes: {check_recipes(client, reads, problems)} shown")
    print(f"pantry: {check_pantry(client, reads, problems)} portions on hand")
    for problem in problems:
        print(f"difference: {problem}")
    print(f"{len(problems)} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
