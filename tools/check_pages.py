"""Check what the pages show against what the Python tools work out (pages/, tools/install_pages.py).

    python3 tools/check_pages.py

The pages work their figures out again in Structr's JavaScript, so this renders each one as the
tools' account (mealplanner-tools, the admin tools/create_tools_user.py makes, signed in with a
session) and compares the data block each prints (#page-data) with Python's answer for the same graph:

  week        every committed entry: cook or leftovers, the recipe, servings cooked and eaten, each
              person's share, and when a dish made ahead must be started (planning/commit.py writes them)
  nutrition   nutrition_scope.nutrition_report: each target's total and status, per meal, day or week;
              week_totals: each daily target's days added up, and its status
  recipes     nutrition_scope.stored_figure for each recipe and nutrient shown
  recipe      one recipe's ingredients and stored figures, for the first recipe in the book; and every
              recipe's instructions, written from its steps' facts, against mealplanner/instructions.py
              for the same Plan as recipe_import.export_plan reads it (J35), as written and as weights
              (?measure=weight; mealplanner/weights.py)
  pantry      inventory.current_magnitude and instance_expiration for every portion on hand; and what
              Buy offers (#buy-data), against products.buyable, and the unit it picks (#buy-units), buy_unit;
              and what its barcode box names (#scan-data) for every product's barcode, against products.find
  alternatives  alternatives.alternatives for the first three foods to buy by name: each option, the meals
              it is for, its grams, stock on hand, ratio, and its effect on cost and on each targeted nutrient
  shopping    shopping.shopping_list: each food to buy, what it is bought in place of (substitutes.py), what is needed and on hand, the packages it is
              bought in at the default package level (packages.default_level) and their weight as
              bought, what it is bought to make (a food another is bought as), what is left of them,
              its cost and until when it keeps, the cost at "Home prices" where it exists, and what
              the pantry covers; a food a StockPolicy tops up is left out, since the page applies no
              policy (and says so)

for every week with entries. Where the Structr methods are installed (tools/install_methods.py), it
compares nutritionReport's and shoppingList's answers with Python's the same way, called as the
tools' account. Read-only, so meant for the owner's instance as well as any other. Exits 1 on any difference.
"""

import json
import os
import re
import sys
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.instructions import instructions
from mealplanner.weights import food_weights
from mealplanner.pantry import USED_UP_G
from mealplanner.products import buy_units, buyable, check_digit, find, gtin_identifiers, normalize
from mealplanner.recipe_import import capability_bearers, export_plan
from mealplanner.inventory import current_magnitude, instance_expiration, mass_quality
from mealplanner.packages import default_level, package_table
from mealplanner.prices import price_table
from mealplanner.profiles import ProfileError
from mealplanner.shopping import shopping_list
from mealplanner.alternatives import alternatives
from mealplanner.substitutes import entry_swaps
from mealplanner.nutrition_scope import (
    FMT, _source_plan, active_entries, entry_servings_eaten, nutrition_report, stored_figure, week_totals,
)
from structr_client import ReadCache

TOLERANCE = 1e-6
ALTERNATIVES_CHECKED = 3                     # foods per week whose alternatives page is compared (each is a long read)
DATA = re.compile(r'<script type="application/json" id="page-data">(.*?)</script>', re.S)
BUY_DATA = re.compile(r'<script type="application/json" id="buy-data">(.*?)</script>', re.S)
BUY_UNITS = re.compile(r'<script type="application/json" id="buy-units">(.*?)</script>', re.S)
SCAN_DATA = re.compile(r'<script type="application/json" id="scan-data">(.*?)</script>', re.S)


def page_data(client, path: str):
    r = client.request("GET", f"/structr/html/{path}")
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
        swaps = entry_swaps(reads, entry) if entry.get("references") and entry.get("usesSubstitution") else {}
        labels = sorted(f"{swap.food_name} for {reads.get_all('Specification', spec)['result']['specifies']['name']}"
                        for spec, swap in swaps.items())
        want = {"kind": "cook" if entry.get("references") else "leftover", "recipe": plan["name"] if plan else None,
                "cooked": entry.get("hasPlannedServings") if entry.get("references") else None,
                "eaten": entry_servings_eaten(reads, entry)[0], "shares": shares, "start": start, "start_by": start_by,
                "swaps": labels}
        got = dict(row, start=utc(row["start"]), start_by=utc(row["start_by"]))
        for key, value in want.items():
            if got[key] != value and not (isinstance(value, float) and close(got[key], value)):
                problems.append(f"week {week['name']!r}, {entry['name']}: {key} shown {got[key]!r}, is {value!r}")
    return len(entries)


def method(client, name: str, **arguments):
    """A Structr method's answer, called as the tools' account; None when it is not installed."""
    r = client.request("POST", f"/structr/rest/{name}", json=arguments)
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
        elif sorted(got.get("estimated") or []) != sorted(r.get("estimated") or []):
            problems.append(f"nutrition {week['name']!r}, {r['target']} {r['group']}: {who} marks estimates "
                            f"{sorted(got.get('estimated') or [])}, nutrition_report {sorted(r.get('estimated') or [])}")
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
    type_ids = {t["name"]: t["id"] for t in reads.get_all("DomainType")["result"]}
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
        bearers = capability_bearers(reads, read_back)
        compare_instructions(plan, written, instructions(read_back, bearers), "", problems)
        weighed = page_data(client, f"recipe/{plan['id']}?measure=weight")
        if weighed.get("measure") != "weight":    # pages installed before they showed weights
            print("  (the recipe pages here show no weights yet: tools/install_pages.py)")
            continue
        foods = {i.food for step in read_back for i in step.inputs} | {
            sub.food for step in read_back for i in step.inputs for sub in i.substitutes}
        weights = {food: reads.memo(("weights", food), lambda food=food: food_weights(reads, type_ids[food]))
                   for food in foods if food in type_ids}
        compare_instructions(plan, weighed.get("instructions"), instructions(read_back, bearers, weights), " as weights", problems)
    if unread:
        print(f"  ({len(unread)} recipe(s) not made by tools/import_recipe.py, whose instructions are not compared: "
              + ", ".join(unread[:3]) + (", ..." if len(unread) > 3 else "") + ")")
    return len(shown)


def compare_instructions(plan: dict, written, want: list[str], how: str, problems: list[str]) -> None:
    if written != want:
        first = next((k for k, (a, b) in enumerate(zip(want, written or [])) if a != b), None)
        problems.append(f"recipe {plan['name']!r}: the page's instructions{how} differ from Python's"
                        + (f" at step {first + 1}: {written[first]!r}, not {want[first]!r}" if first is not None else
                           f": {len(written or [])} sentences, not {len(want)}"))


def check_pantry(client, reads, problems: list[str]) -> int:
    shown = {row["portion"]: row for row in page_data(client, "pantry")}
    now = datetime.now(timezone.utc)
    counted = 0
    for type_name in ("PortionOfSubstance", "DiscreteWholeItem"):
        for portion in reads.get_all(type_name)["result"]:
            quality = mass_quality(reads, portion)
            grams = current_magnitude(reads, quality["id"], now) if quality else None
            if grams is None or grams < USED_UP_G:      # never weighed, or used up: the page leaves it out
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


def buy_data(client) -> tuple[list[str], dict[str, str]]:
    """What the pantry page's Buy offers, and the unit it picks for each that is not grams."""
    r = client.request("GET", "/structr/html/pantry")
    r.raise_for_status()
    found, units = BUY_DATA.search(r.text), BUY_UNITS.search(r.text)
    if not found or not units:
        raise ValueError("/structr/html/pantry printed no buy data")
    return json.loads(found.group(1)), json.loads(units.group(1))


def check_buyable(client, reads, problems: list[str]) -> int:
    """What the pantry page's Buy offers, against products.buyable: a food that only products sit under is
    still offered, and so is each product. And the unit it picks for each, against products.buy_unit."""
    (shown, units), want = buy_data(client), buyable(reads)
    for name in sorted(set(want) - set(shown)):
        problems.append(f"pantry: {name} can be bought, but Buy does not offer it")
    for name in sorted(set(shown) - set(want)):
        problems.append(f"pantry: Buy offers {name}, which is a group of foods or no food")
    for name, unit in sorted(buy_units(reads).items()):
        if units.get(name, "g") != unit:
            problems.append(f"pantry: Buy picks {units.get(name, 'g')} for {name}, buy_unit {unit}")
    for name in sorted(set(units) - set(want)):
        problems.append(f"pantry: Buy picks a unit for {name}, which it does not offer")
    return len(want)


def scan_data(client, barcode: str):
    """What the pantry page's barcode box names for a barcode (#scan-data)."""
    r = client.request("GET", "/structr/html/pantry", params={"scan": barcode})
    r.raise_for_status()
    found = SCAN_DATA.search(r.text)
    if not found:
        raise ValueError("/structr/html/pantry?scan= printed no scan data")
    return json.loads(found.group(1))


def check_scans(client, problems: list[str]) -> int:
    """The pantry page's barcode box against products.find: each product's barcodes, as stored and as a
    UPC-A or EAN-13 prints it, one no product has, one misread and one a shop gives its own packs."""
    codes = [row["identifierValue"] for row in gtin_identifiers(client) if row.get("denotesType")]
    printed = [code.lstrip("0").rjust(12, "0") for code in codes]       # a UPC-A, or an EAN-13
    unknown = "952000000000" + str(check_digit("952000000000"))         # GS1's demonstration prefix: no package's
    for code in codes + printed + [unknown, "036000291453", "212345678992"]:
        try:
            found = find(client, code)
            want = {"gtin": normalize(code), "product": found and found.product, "food": found and found.food,
                    "amount": found and found.amount, "unit": found and found.unit}
        except ValueError as exc:                   # ProductError is one
            want = {"problem": str(exc)}
        shown = scan_data(client, code)
        if shown != want:
            problems.append(f"pantry: scanning {code} names {shown}, products.find {want}")
    return len(codes)


def check_shopping(client, week: dict, problems: list[str], shown=None, who: str = "the page") -> int:
    if shown is None:
        shown = page_data(client, f"shopping/{week['id']}")
    try:
        prices = price_table(client, "Home prices")
    except ProfileError:
        prices = None
    level = default_level(client)
    want = shopping_list(client, week["id"], datetime.now(timezone.utc), prices, package_table(client, level) if level else None)
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
        for key, value in (("buy", line.buy), ("need", line.need), ("have", line.have), ("cost", line.cost),
                           ("bought", line.bought), ("left", line.left), ("left_cost", line.left_cost),
                           ("as_bought", line.as_bought)):
            if not close(row[key], value):
                problems.append(f"shopping {week['name']!r}, {line.food}: {key} by {who} {row[key]!r}, is {value!r}")
        made, want_made = sorted((food, grams) for food, grams in row["made"]), sorted(line.made)  # the two walk foods in their own order
        if [f for f, _ in made] != [f for f, _ in want_made] or not all(close(a, b) for (_, a), (_, b) in zip(made, want_made)):
            problems.append(f"shopping {week['name']!r}, {line.food}: bought to make {made!r} by {who}, is {line.made!r}")
        if [(p["count"], p["label"]) for p in row["packages"]] != line.packages or row["keeps_opened"] != line.keeps_opened:
            problems.append(f"shopping {week['name']!r}, {line.food}: packages by {who} {row['packages']!r} "
                            f"(opened {row['keeps_opened']!r}), are {line.packages!r} (opened {line.keeps_opened!r})")
        # with no day set, what is left keeps from now, which the page read a moment before this did
        shown_until, until = utc(row["keeps_until"]), line.keeps_until
        if (shown_until is None) != (until is None) or (until is not None and abs((shown_until - until).total_seconds()) > 60):
            problems.append(f"shopping {week['name']!r}, {line.food}: keeps until by {who} {row['keeps_until']!r}, is {until!r}")
        if sorted(row.get("instead", [])) != line.instead:
            problems.append(f"shopping {week['name']!r}, {line.food}: bought in place of {row.get('instead')!r} by {who}, "
                            f"is {line.instead!r}")
        if utc(row["first"]) != line.first_needed:
            problems.append(f"shopping {week['name']!r}, {line.food}: first needed by {who} {row['first']!r}, is {line.first_needed!r}")
    # a food a policy tops up may be covered on the page, which applies no policy, and bought in Python
    if sorted(r["food"] for r in shown["covered"] if r["food"] not in topped) != [line.food for line in want.covered]:
        problems.append(f"shopping {week['name']!r}: the pantry covers differ ({who})")
    # the page walks the week in time order and Python as Structr lists it: which recipes, not their order
    by_food = lambda found: {food: sorted(recipes) for food, recipes in found.items()}
    if by_food(shown["unquantified"]) != by_food(want.unquantified) or sorted(shown["not_bought"]) != want.not_bought:
        problems.append(f"shopping {week['name']!r}: what has no amount, or is not bought, differs ({who})")
    return len(want.to_buy)


def check_alternatives(client, week: dict, foods: list[str], problems: list[str]) -> int:
    """The alternatives page for each food against alternatives.alternatives, at "Home prices"."""
    try:
        prices = price_table(client, "Home prices")
    except ProfileError:
        prices = None
    for food in foods:
        shown = page_data(client, f"alternatives/{week['id']}?food={quote(food)}")
        want = alternatives(client, week["id"], food, datetime.now(timezone.utc), prices)
        where = f"alternatives {week['name']!r}, {food}"
        if not close(shown["grams"], want.grams) or sorted(map(tuple, shown["meals"])) != sorted(want.meals):
            problems.append(f"{where}: {shown['grams']!r} g for {shown['meals']!r} by the page, is {want.grams!r} for {want.meals!r}")
        got = [(o["kind"], o["food"]) for o in shown["options"]]
        if got != [(o.kind, o.food) for o in want.options]:
            problems.append(f"{where}: the page offers {got!r}, is {[(o.kind, o.food) for o in want.options]!r}")
            continue
        for row, option in zip(shown["options"], want.options):
            label = f"{where}, {option.kind} {option.food}"
            if sorted(row["meals"]) != sorted(option.meals) or row["kinds"] != option.kinds or row["checked"] != option.checked:
                problems.append(f"{label}: meals, kinds or checked differ: {row!r}")
            for key, value in (("grams", option.grams), ("have", option.have), ("ratio", option.ratio)):
                if not close(row[key], value):
                    problems.append(f"{label}: {key} by the page {row[key]!r}, is {value!r}")
            if option.effect is None or row["effect"] is None:
                if (option.effect is None) != (row["effect"] is None):
                    problems.append(f"{label}: an effect on one side only")
                continue
            if not close(row["effect"]["cost"], option.effect.cost):
                problems.append(f"{label}: cost by the page {row['effect']['cost']!r}, is {option.effect.cost!r}")
            nutrients = [(n, u, c) for n, u, c in row["effect"]["nutrients"]]
            if [(n, u) for n, u, _ in nutrients] != [(n, u) for n, u, _ in option.effect.nutrients] or not all(
                    close(a, b) for (_, _, a), (_, _, b) in zip(nutrients, option.effect.nutrients)):
                problems.append(f"{label}: nutrients by the page {nutrients!r}, are {option.effect.nutrients!r}")
    return len(foods)


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
        foods = sorted({line.food for line in shopping_list(client, week["id"], datetime.now(timezone.utc)).to_buy})[:ALTERNATIVES_CHECKED]
        print(f"  alternatives: {check_alternatives(client, week, foods, problems)} foods")
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
    print(f"pantry: {check_buyable(client, reads, problems)} foods and products to buy")
    print(f"pantry: {check_scans(client, problems)} barcodes scanned, and three that name no product")
    for problem in problems:
        print(f"difference: {problem}")
    print(f"{len(problems)} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
