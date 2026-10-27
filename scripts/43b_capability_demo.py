"""A tool named by what it does, loaded into real Structr and read back (data-model.md Sec 5, Sec 18
J37; mealplanner/recipe_import.py, scripts/43a).

A TEST capability, Broiler heat, under a TEST Heat, which a TEST oven and a TEST grill can give
(`mayBearFunction`). A one-step TEST recipe broils its chicken with it set high, beside a pan. It is
loaded, read back, checked where the model keeps it (an instrument Specification that specifies the
capability), met by both tools, and by the same two when the recipe asks for Heat (they give one of
its subtypes), shown on the recipe page if the pages are installed (pages/lib/75_instructions.js
reading what can give it from the graph), refused where a tool is named as a capability, and edited
to name the oven itself, leaving nothing of the capability behind. Everything is TEST-named, swept
before and deleted after.

Run with: python3 scripts/43b_capability_demo.py
"""

import os
import sys
import tempfile

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.recipe_import import RecipeResolutionError, capability_bearers, export_plan, import_recipe, read_recipe
from tools.check_pages import page_data

P = "TEST -- Z43 "
CHICKEN, PAN, OVEN, GRILL, HEAT, BROILER, DISH = (P + n for n in ("Chicken", "Pan", "Oven", "Grill", "Heat", "Broiler heat",
                                                                  "Broiled Chicken"))
SWEEP_ORDER = ["StateRequirement", "Specification", "Step", "Plan", "RecipeIdentity", "QuantitySpecification", "DomainType"]


def recipe_file(broiler):
    text = f"""
name = "{DISH}"
servings = 2
meal_types = ["Dinner"]

[[steps]]
name = "broil the chicken"
equipment = ["{PAN}", {broiler}]
inputs = [{{ food = "{CHICKEN}", amount = 300, unit = "g" }}]
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

    sweep(client)
    try:
        print("[0] Fixture: a TEST food, three TEST tools, and two TEST capabilities two of them can give...")
        hierarchy = lambda name: client.get("/structr/rest/TypeHierarchy", params={"name": name})["result"][0]["id"]
        client.upsert("DomainType", "name", CHICKEN, {"hierarchy": hierarchy("Food Identity"), "isLookupBearing": True})
        capability_h = hierarchy("Capability")
        heat = client.upsert("DomainType", "name", HEAT, {"hierarchy": capability_h, "isLookupBearing": True})
        broiler = client.upsert("DomainType", "name", BROILER, {"hierarchy": capability_h, "isLookupBearing": True, "parent": heat})
        for tool in (PAN, OVEN, GRILL):
            client.upsert("DomainType", "name", tool, {"hierarchy": hierarchy("Equipment Type"), "isLookupBearing": True,
                                                       "mayBearFunction": [broiler] if tool != PAN else []})

        print("\n[1] Load the file...")
        doc = recipe_file(f'{{ capability = "{BROILER}", heat = "high" }}')
        report = import_recipe(client, doc)
        check(export_plan(client, report.plan_id) == doc.plan_part(), "the Plan reads back exactly as the file says, capability and all")
        check(import_recipe(client, doc).plan_unchanged, "the same file again changes nothing")
        spec = client.get("/structr/rest/Specification", params={"name": f"{DISH} v1 step 1 equipment 2 {BROILER}"})["result"]
        spec = client.get_all("Specification", spec[0]["id"])["result"] if len(spec) == 1 else {}
        check(spec.get("hasParticipationRole") == "instrument" and (spec.get("specifies") or {}).get("name") == BROILER,
              "an instrument Specification that specifies the capability, not a tool")
        check(capability_bearers(client, doc.steps) == {BROILER: (GRILL, OVEN)}, "met by the grill and the oven, not the pan")
        check(capability_bearers(client, recipe_file(f'{{ capability = "{HEAT}" }}').steps) == {HEAT: (GRILL, OVEN)},
              "asking for Heat, met by the same two, through its subtype")

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
            check(written == [f"Broil the chicken: 300 g {CHICKEN.lower()} on the {GRILL.lower()} or {OVEN.lower()} over high heat "
                              f"using the {PAN.lower()}."],
                  "names the tools that can give it, with its setting")

        print("\n[3] A tool named as a capability, refused before anything is written...")
        try:
            import_recipe(client, recipe_file(f'{{ capability = "{OVEN}" }}'))
            check(False, "refused (ACCEPTED!)")
        except RecipeResolutionError as e:
            check(any(f"capability {OVEN!r} exists but is not in the right hierarchy" in p for p in e.problems), "refused, and said why")
        check(export_plan(client, report.plan_id) == doc.plan_part(), "the Plan as it was")

        print("\n[4] Edited to name the oven itself...")
        edited = recipe_file(f'{{ tool = "{OVEN}", heat = "high" }}')
        import_recipe(client, edited)
        check(export_plan(client, report.plan_id) == edited.plan_part(), "reads back as the edited file says")
        left = [n["name"] for n in client.get_all("Specification")["result"] if (n.get("name") or "").endswith(BROILER)]
        check(left == [], "no Specification of the capability is left")
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
