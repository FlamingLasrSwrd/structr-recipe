"""What may stand in for an ingredient, loaded into real Structr and read back (data-model.md Sec 5.3,
Sec 18 J36; mealplanner/recipe_import.py, scripts/42a).

A one-step TEST recipe whose butter may be margarine, or 0.75 as much olive oil, but never lard. It is
loaded, read back, checked where the model keeps each rule (a SubstitutionRule on the butter's input
Specification, its candidate a food, its ratio, whether it is ruled out), shown on the recipe page if
the pages are installed (pages/lib/75_instructions.js reading the rules back), refused where a rule
breaks invariant 21 or 22 (scripts/42a's SubstitutionRule.onCreate), edited down to one
substitute, and its ingredient then removed, each time leaving no rule behind it. Everything is
TEST-named, swept before and deleted after.

Run with: python3 scripts/42b_substitution_demo.py
"""

import os
import sys
import tempfile

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from structr_client import StructrError
from mealplanner.recipe_import import export_plan, import_recipe, read_recipe
from tools.check_pages import page_data

P = "TEST -- Z42 "
RICE, BUTTER, MARGARINE, OIL, LARD, DISH, WHISK = (P + n for n in ("Rice", "Butter", "Margarine", "Olive Oil", "Lard",
                                                                    "Buttered Rice", "Whisk"))
SWEEP_ORDER = ["SubstitutionRule", "Specification", "Step", "Plan", "RecipeIdentity", "QuantitySpecification", "DomainType"]


def recipe_file(substitutes, butter=True):
    lines = f'{{ food = "{BUTTER}", amount = 3, unit = "tbsp", substitutes = [{substitutes}] }},' if butter else ""
    text = f"""
name = "{DISH}"
servings = 2
meal_types = ["Dinner"]

[[steps]]
name = "toss"
inputs = [{{ food = "{RICE}", amount = 150, unit = "g" }}, {lines}]
"""
    handle = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False)
    handle.write(text)
    handle.close()
    try:
        return read_recipe(handle.name)
    finally:
        os.unlink(handle.name)


def sweep(client):
    for type_name in SWEEP_ORDER:
        for node in client.get_all(type_name)["result"]:
            if (node.get("name") or "").startswith(P):
                client.delete(f"/structr/rest/{type_name}/{node['id']}")


def main():
    client = connect()
    client.wait_until_ready()
    failures = []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    def rules():
        return sorted((r["name"], client.get_all("SubstitutionRule", r["id"])["result"])
                      for r in client.get_all("SubstitutionRule")["result"] if (r.get("name") or "").startswith(P))

    sweep(client)
    try:
        print("[0] Fixture: five TEST foods and a TEST tool...")
        hierarchy = lambda name: client.get("/structr/rest/TypeHierarchy", params={"name": name})["result"][0]["id"]
        food_h = hierarchy("Food Identity")
        for food in (RICE, BUTTER, MARGARINE, OIL, LARD):
            client.upsert("DomainType", "name", food, {"hierarchy": food_h, "isLookupBearing": True})
        whisk = client.upsert("DomainType", "name", WHISK, {"hierarchy": hierarchy("Equipment Type")})

        print("\n[1] Load the file...")
        doc = recipe_file(f'{{ food = "{MARGARINE}" }}, {{ food = "{OIL}", ratio = 0.75 }}, {{ food = "{LARD}", never = true }}')
        report = import_recipe(client, doc)
        check(export_plan(client, report.plan_id) == doc.plan_part(), "the Plan reads back exactly as the file says, substitutes and all")
        check(import_recipe(client, doc).plan_unchanged, "the same file again changes nothing")
        found = rules()
        spec = f"{DISH} v1 step 1 input 2 {BUTTER}"
        check([name for name, _ in found] == [f"{spec} or 1 {MARGARINE}", f"{spec} or 2 {OIL}", f"{spec} or 3 {LARD}"],
              "a SubstitutionRule per substitute, in the file's order")
        oil = dict(found)[f"{spec} or 2 {OIL}"]
        lard = dict(found)[f"{spec} or 3 {LARD}"]
        check((oil.get("forSpecification") or {}).get("name") == spec and (oil.get("candidateType") or {}).get("name") == OIL
              and oil.get("substitutionRatio") == 0.75 and not oil.get("isExcluded") and lard.get("isExcluded") is True,
              "for the butter's input Specification, the olive oil at 0.75, the lard ruled out")

        print("\n[2] The recipe page...")
        try:
            written = page_data(client, f"recipe/{report.plan_id}").get("instructions")
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 404:
                raise
            written = None
        if written is None:
            print("    (no recipe page writing instructions here: tools/install_pages.py)")
        else:
            check(written == [f"Toss: 150 g {RICE.lower()} and 3 tbsp {BUTTER.lower()} (or {MARGARINE.lower()}, "
                              f"or 2.25 tbsp {OIL.lower()})."],
                  "says what may stand in, the olive oil scaled, the lard left out")

        print("\n[3] Rules the model forbids, refused as they are written (invariants 21, 22)...")
        specs = {n["name"]: n["id"] for n in client.get_all("Specification")["result"] if (n.get("name") or "").startswith(DISH)}
        output = next(node_id for name, node_id in specs.items() if " output " in name)
        margarine = client.get("/structr/rest/DomainType", params={"name": MARGARINE})["result"][0]["id"]

        def refused(label, fields, token):
            try:
                client.post("/structr/rest/SubstitutionRule", {"name": P + label, "visibleToAuthenticatedUsers": True, **fields})
            except StructrError as e:
                check(e.status == 422 and token in str(e.body), f"{label}: refused, {token}")
                return
            check(False, f"{label}: refused (ACCEPTED!)")

        refused("for what the step makes", {"forSpecification": output, "candidateType": margarine},
                "substitution_rule_must_be_for_an_input")
        refused("a tool for the butter", {"forSpecification": specs[spec], "candidateType": whisk},
                "candidate_must_come_from_the_hierarchy_the_input_specifies")
        refused("no candidate", {"forSpecification": specs[spec]}, "candidate_must_come_from_the_hierarchy_the_input_specifies")
        refused("for nothing", {"candidateType": margarine}, "substitution_rule_must_be_for_an_input")

        print("\n[4] Edited down to one substitute, then without the butter...")
        edited = recipe_file(f'{{ food = "{OIL}", ratio = 0.75 }}')
        import_recipe(client, edited)
        check(export_plan(client, report.plan_id) == edited.plan_part() and [n for n, _ in rules()] == [f"{spec} or 1 {OIL}"],
              "one rule left, the others deleted")
        import_recipe(client, recipe_file("", butter=False))
        check(rules() == [], "with the ingredient gone, so is its rule")
    finally:
        sweep(client)
    left = [n["name"] for t in SWEEP_ORDER for n in client.get_all(t)["result"] if (n.get("name") or "").startswith(P)]
    check(not left, "nothing TEST-named is left behind")
    if failures:
        print(f"\n{len(failures)} check(s) FAILED")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
