"""A food bought in place of what the shopping list says, in real Structr, through Python and through the
pages alike (data-model.md Sec 18 J42; mealplanner/substitutes.py, mealplanner/alternatives.py,
pages/lib/92_substitutes.js, scripts/51a).

A TEST recipe whose noodles may be rice noodles at 0.8 as much, but never udon, is planned in two TEST
weeks alike, one booked through Python and one through the pages (as a test Person in no household, so
the page books as the superuser for them). Then:

  [2] the alternatives for the noodles, best first: the same food, the recipe's rice noodles, the
      spaghetti beside them (one to one by weight), planning again; never the udon. The page's list is
      compared with Python's where the pages are installed (tools/check_pages.py's comparison);
  [3] spaghetti bought instead, in each week: a purchase each, and one rule of the week's (isOneOff) for
      the recipe's input, the same rule for both weeks' meals; sending the same again changes nothing;
      the shopping list says the spaghetti is bought in place of the noodles, and the week page names the
      swap; each compared with Python where the pages are installed;
  [4] undone, in Python and then on the week page: the rule stays while the other week's meal uses it,
      and is deleted with the last;
  [5] the recipe's own rice noodles bought instead: the meal uses the recipe's rule, no rule is made;
  [6] each meal cooked, through the week page and through Python: each draws 160 g of rice noodles,
      its draw saying which rule it followed (viaSubstitution), and an undo is refused once cooked.

Nutrition is not checked here (the TEST foods have no figures): tests/test_substitutes.py and
tests/test_substitutes_page.py cover it offline. Everything is TEST-named or carries MARK, swept before
and deleted after, and the bookings' kinds are removed again if this run made them.

Run with: python3 scripts/51b_swap_demo.py
"""

import os
import secrets
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import ownership, pantry
from mealplanner.alternatives import alternatives
from mealplanner.connection import connect
from mealplanner.inventory import FMT
from mealplanner.recipe_import import import_recipe, read_recipe
from mealplanner.shopping import shopping_list
from mealplanner.substitutes import SwapError, buy_instead, one_off_name, stop_using, use_instead
from structr_client import StructrError
from tools.check_bookings import SWEPT, Check
from tools.check_pages import check_alternatives, check_shopping, check_week

P = "TEST -- Z51 "
MARK = "51b051b0"            # begins every token this demo books with (pages/common.js takes 4 to 16 hex digits)
PASTA, NOODLES, SPAGHETTI, RICE, UDON, DISH = (P + n for n in ("Pasta", "Noodles", "Spaghetti", "Rice Noodles", "Udon",
                                                               "Noodle Bowl"))
TYPES = ("SubstitutionRule", *SWEPT, "Specification", "Step", "Plan", "RecipeIdentity")


def token() -> str:
    return MARK + secrets.token_hex(2)


def recipe_file():
    text = f"""
name = "{DISH}"
servings = 2
meal_types = ["Dinner"]

[[steps]]
name = "boil"
inputs = [{{ food = "{NOODLES}", amount = 200, unit = "g", substitutes = [{{ food = "{RICE}", ratio = 0.8 }}, {{ food = "{UDON}", never = true }}] }}]
"""
    handle = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
    handle.write(text)
    handle.close()
    try:
        return read_recipe(handle.name)
    finally:
        os.unlink(handle.name)


def sweep(client) -> list[str]:
    """Delete every node TEST-named here or carrying MARK; what Structr refused, by name."""
    found = {}
    for type_name in TYPES:
        for row in client.get_all(type_name)["result"]:
            name = row.get("name") or ""
            if name.startswith(P) or MARK in name:
                found[row["id"]] = (row.get("type") or type_name, name)
    refused = []
    for _ in range(3):                         # a node another hangs on goes on a later pass
        left = {}
        for node_id, (type_name, name) in found.items():
            try:
                client.delete(f"/structr/rest/{type_name}/{node_id}")
            except StructrError as exc:
                if exc.status != 404:
                    left[node_id] = (type_name, name)
        found = left
    refused += [f"{t} {n}" for t, n in found.values()]
    return refused


def kinds(client) -> dict:
    """The bookings' kinds and their hierarchy, which pantry.py makes on first use: id -> type."""
    out = {row["id"]: "DomainType" for name in ownership.KINDS
           for row in client.get("/structr/rest/DomainType", params={"name": name})["result"] if row.get("type") == "DomainType"}
    out.update({row["id"]: "TypeHierarchy" for row in client.get("/structr/rest/TypeHierarchy",
                                                                 params={"name": pantry.OPERATIONS})["result"]})
    return out


def main():
    client = connect()
    client.wait_until_ready()
    failures = []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    def entry(entry_id):
        return client.get_all("MealPlanEntry", entry_id)["result"]

    def uses(entry_id):
        return sorted(r["id"] for r in entry(entry_id).get("usesSubstitution") or [])

    def rules_named(name):
        return [r for r in client.get("/structr/rest/SubstitutionRule", params={"name": name})["result"] if r.get("name") == name]

    def compared(label, run):
        problems = []
        try:
            run(problems)
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 404:
                raise
            print(f"    (no {label} page here: tools/install_pages.py)")
            return
        for p in problems:
            print(f"      {p}")
        check(not problems, f"the {label} page agrees with Python")

    left = sweep(client)
    if left:
        print(f"could not remove what an earlier run left: {left}")
        sys.exit(1)
    kinds_before = set(kinds(client))
    booker = Check(client)
    try:
        print("[0] Fixture: TEST foods, and a TEST recipe whose noodles may be rice noodles but never udon...")
        food_h = client.get("/structr/rest/TypeHierarchy", params={"name": "Food Identity"})["result"][0]["id"]
        pasta = client.upsert("DomainType", "name", PASTA, {"hierarchy": food_h, "isLookupBearing": True})
        for food in (NOODLES, SPAGHETTI, RICE, UDON):
            client.upsert("DomainType", "name", food, {"hierarchy": food_h, "isLookupBearing": True, "parent": pasta})
        report = import_recipe(client, recipe_file())
        spec = client.get("/structr/rest/Specification", params={"name": f"{DISH} v1 step 1 input 1 {NOODLES}"})["result"][0]
        rice_rule = rules_named(f"{spec['name']} or 1 {RICE}")[0]["id"]

        print("\n[1] Two weeks alike, a dinner of it tomorrow in each...")
        start = datetime.now(timezone.utc) + timedelta(days=1)
        weeks, meals = {}, {}
        for side in ("page", "python"):
            weeks[side] = client.post("/structr/rest/MealPlan", {"name": f"{P}{side} week", "visibleToAuthenticatedUsers": True,
                                                     "visibleToPublicUsers": False})["result"][0]
            region = client.post("/structr/rest/TemporalRegion", {"name": f"{P}{side} dinner region", "hasBeginning": start.strftime(FMT),
                                                      "visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False})["result"][0]
            meals[side] = client.post("/structr/rest/MealPlanEntry", {
                "name": f"{P}{side} Dinner -- {DISH}", "references": report.plan_id, "hasPlannedServings": 2.0, "isAbout": region,
                "memberOf": weeks[side], "isSkipped": False, "visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False})["result"][0]
        week_rows = {side: client.get_all("MealPlan", w)["result"] for side, w in weeks.items()}

        print("\n[2] What could take the noodles' place...")
        alts = alternatives(client, weeks["python"], NOODLES, datetime.now(timezone.utc))
        check([(o.kind, o.food) for o in alts.options] == [("same", None), ("recipe", RICE), ("similar", SPAGHETTI), ("replan", None)],
              "the same food, the recipe's rice noodles, the spaghetti beside them, planning again; never the udon")
        check(alts.grams == 200.0 and alts.options[1].grams == 160.0 and alts.options[1].ratio == 0.8
              and alts.options[2].grams == 200.0 and not alts.options[2].checked,
              "200 g of noodles; 160 g of rice noodles by the recipe's 0.8; 200 g of spaghetti, by weight, not checked")
        compared("alternatives", lambda problems: check_alternatives(client, week_rows["page"], [NOODLES], problems))

        print("\n[3] Spaghetti bought instead, in each week...")
        now = datetime.now(timezone.utc)
        bought, swapped = buy_instead(client, weeks["python"], NOODLES, SPAGHETTI, 250, "g", now, token())
        one_off = rules_named(one_off_name(spec, SPAGHETTI))
        check(len(one_off) == 1 and uses(meals["python"]) == [one_off[0]["id"]], "Python: the meal uses a rule of the week's")
        rule = client.get_all("SubstitutionRule", one_off[0]["id"])["result"] if one_off else {}
        check(rule.get("isOneOff") is True and rule.get("substitutionRatio") == 1.0 and not rule.get("isExcluded")
              and (rule.get("candidateType") or {}).get("name") == SPAGHETTI
              and (rule.get("forSpecification") or {}).get("id") == spec["id"],
              "for the recipe's noodles, spaghetti one to one, marked the week's own")
        again = use_instead(client, weeks["python"], NOODLES, SPAGHETTI)
        check(not again.created and not again.meals and len(rules_named(one_off_name(spec, SPAGHETTI))) == 1,
              "the same swap again changes nothing")
        try:
            use_instead(client, weeks["python"], PASTA, NOODLES)
            check(False, "a kind of the listed food is refused as a swap (ACCEPTED!)")
        except SwapError:
            check(True, "a kind of the listed food is refused as a swap: it is the same food")
        want = shopping_list(client, weeks["python"], datetime.now(timezone.utc))
        lines = {line.food: line for line in want.to_buy + want.covered}
        check(NOODLES not in lines and SPAGHETTI in lines and lines[SPAGHETTI].instead == [NOODLES]
              and lines[SPAGHETTI].need == 200.0,
              "the shopping list: 200 g of spaghetti, bought in place of the noodles, and no noodles")
        try:
            got = booker.page(f"alternatives/{weeks['page']}", do="instead", token=token(), week=weeks["page"], listed=NOODLES,
                              food=SPAGHETTI, amount=250, unit="g", entries=meals["page"])
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 404:
                raise
            got = None
            print("    (no alternatives page here: tools/install_pages.py; the rest of the page's side is not checked)")
        if got is not None:
            check(not got["problem"], f"the page: bought instead ({got['problem'] or 'booked'})")
            check(uses(meals["page"]) == [r["id"] for r in one_off] and len(rules_named(one_off_name(spec, SPAGHETTI))) == 1,
                  "the page's meal uses the same rule, and no second one is made")
            check(any(n.startswith("Purchase ") and SPAGHETTI in n for n in got["created"]), "the page booked the purchase")
            for side in ("page", "python"):
                compared(f"{side} week's shopping", lambda problems, s=side: check_shopping(client, week_rows[s], problems))
                compared(f"{side} week's week", lambda problems, s=side: check_week(client, client, week_rows[s], problems))

            print("\n[4] Undone, in Python and then on the week page...")
            stop_using(client, meals["python"], one_off[0]["id"])
            check(uses(meals["python"]) == [] and len(rules_named(one_off_name(spec, SPAGHETTI))) == 1,
                  "Python: the meal uses the noodles again; the rule stays, the other week's meal uses it")
            got = booker.page(f"week/{weeks['page']}", do="unswap", token=token(), entry=meals["page"], rule=one_off[0]["id"])
            check(not got["problem"] and uses(meals["page"]) == [] and rules_named(one_off_name(spec, SPAGHETTI)) == [],
                  f"the page: the meal uses the noodles again, and the rule no meal uses is deleted ({got['problem'] or 'booked'})")

            print("\n[5] The recipe's own rice noodles bought instead...")
            buy_instead(client, weeks["python"], NOODLES, RICE, 200, "g", datetime.now(timezone.utc), token())
            got = booker.page(f"alternatives/{weeks['page']}", do="instead", token=token(), week=weeks["page"], listed=NOODLES,
                              food=RICE, amount=160, unit="g", entries=meals["page"])
            check(not got["problem"] and uses(meals["python"]) == [rice_rule] and uses(meals["page"]) == [rice_rule]
                  and rules_named(one_off_name(spec, RICE)) == [],
                  f"both meals use the recipe's rule; no rule of the week's is made ({got['problem'] or 'booked'})")

            print("\n[6] Each meal cooked, through the week page and through Python...")
            cook_token = token()
            got = booker.page(f"week/{weeks['page']}", do="cook", entry=meals["page"], token=cook_token)
            check(not got["problem"], f"the page cooked it ({got['problem'] or 'booked'})")
            booking, short = pantry.cook(client, meals["python"], datetime.now(timezone.utc), token())
            check(not short, "Python cooked it, short of nothing")

            def draws(names):
                out = []
                for name in names:
                    for row in client.get("/structr/rest/Allocation", params={"name": name})["result"]:
                        a = client.get_all("Allocation", row["id"])["result"]
                        portion = client.get_all("PortionOfSubstance", a["isAbout"]["id"])["result"]
                        grams = client.get_all("Measurement", a["hasActualQuantity"]["id"])["result"]["value"]
                        out.append((portion["instanceOf"]["name"], grams, (a.get("viaSubstitution") or {}).get("id")))
                return out

            for side, names in (("the page", got["created"]), ("Python", booking.created)):
                drawn = draws(names)
                check(drawn and {f for f, _, _ in drawn} == {RICE} and abs(sum(g for _, g, _ in drawn) - 160.0) < 1e-6
                      and {v for _, _, v in drawn} == {rice_rule},
                      f"{side}: drew 160 g of rice noodles, by the recipe's rule ({drawn})")
            try:
                stop_using(client, meals["python"], rice_rule)
                check(False, "Python: undo refused once cooked (ACCEPTED!)")
            except SwapError:
                check(True, "Python: undo refused once cooked")
            got = booker.page(f"week/{weeks['page']}", do="unswap", token=token(), entry=meals["page"], rule=rice_rule)
            check(bool(got["problem"]) and "cooked already" in got["problem"] and uses(meals["page"]) == [rice_rule],
                  "the page: undo refused once cooked")
    finally:
        refused = sweep(client)
        if booker.booker_id:
            client.delete(f"/structr/rest/Person/{booker.booker_id}")
        made = {k: v for k, v in kinds(client).items() if k not in kinds_before}
        if made and not any((p.get("hasKind") or {}).get("id") in made for p in client.get_all("Process")["result"]):
            for node_id, type_name in sorted(made.items(), key=lambda kv: kv[1] == "TypeHierarchy"):
                client.delete(f"/structr/rest/{type_name}/{node_id}")
    check(not refused, f"nothing TEST-named is left behind{'' if not refused else ': ' + ', '.join(refused)}")
    if failures:
        print(f"\n{len(failures)} check(s) FAILED")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
