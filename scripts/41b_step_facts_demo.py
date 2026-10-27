"""A recipe step's facts loaded into real Structr and read back (data-model.md Sec 18 J35;
mealplanner/recipe_import.py, scripts/41a).

A TEST recipe of three steps, two of them side by side: rinse and simmer rice on a burner at low
heat, roast chicken in an oven at 425 F until golden and 165 F inside, and serve them together. It
is loaded, loaded again, edited (the oven's heat, a waiting time and the doneness taken out, the
roast put after the rice), and read back each time, then its Steps' facts are checked where the
model keeps them: minutes as QuantitySpecifications, the order as isPrecededBy, heat and doneness as
StateRequirements targeting the Quality Kinds 41a made. Everything is TEST-named, swept before and
deleted after.

Run with: python3 scripts/41b_step_facts_demo.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.recipe_import import export_plan, import_recipe, read_recipe

P = "TEST -- Z41 "
RICE, CHICKEN = P + "Rice", P + "Chicken"
RINSED, COOKED, ROASTED, DISH = P + "Rice (rinsed)", P + "Rice (cooked)", P + "Chicken (roasted)", P + "Chicken and Rice"
STOVE, OVEN = P + "Stove", P + "Oven"
SWEEP_ORDER = ["StateRequirement", "Identifier", "Specification", "Step", "Plan", "RecipeIdentity",
               "QuantitySpecification", "DomainType"]

FILE = f"""
name = "{DISH}"
servings = 2
meal_types = ["Dinner"]

[[steps]]
name = "rinse the rice"
makes = "{RINSED}"
minutes = 2
inputs = [{{ food = "{RICE}", amount = 150, unit = "g" }}]

[[steps]]
name = "simmer the rice"
method = "Boiling"
makes = "{COOKED}"
minutes = 2
wait_minutes = 18
equipment = [{{ tool = "{STOVE}", heat = "low" }}]
inputs = [{{ food = "{RINSED}" }}]

[[steps]]
name = "roast the chicken"
makes = "{ROASTED}"
{{after}}
minutes = 5
{{wait}}
{{until}}
equipment = [{{oven}}]
inputs = [{{ food = "{CHICKEN}", amount = 300, unit = "g" }}]

[[steps]]
name = "serve"
after = ["simmer the rice", "roast the chicken"]
inputs = [{{ food = "{COOKED}" }}, {{ food = "{ROASTED}" }}]
"""


def recipe_file(edited=False):
    text = FILE.replace("{after}", 'after = ["simmer the rice"]' if edited else "after = []")
    text = text.replace("{wait}", "" if edited else "wait_minutes = 25")
    text = text.replace("{until}", "" if edited else 'until = "golden"\ninside = { temp = 165, unit = "F" }')
    text = text.replace("{oven}", f'"{OVEN}"' if edited else f'{{ tool = "{OVEN}", temp = 425, unit = "F" }}')
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

    def named(type_name, name):
        rows = [r for r in client.get(f"/structr/rest/{type_name}", params={"name": name})["result"] if r.get("type") == type_name]
        return client.get_all(type_name, rows[0]["id"])["result"] if len(rows) == 1 else None

    sweep(client)
    try:
        print("[0] Fixture: two TEST foods and two TEST tools...")
        hierarchy = {h: client.get("/structr/rest/TypeHierarchy", params={"name": h})["result"][0]["id"]
                     for h in ("Food Identity", "Equipment Type")}
        for food in (RICE, CHICKEN):
            client.upsert("DomainType", "name", food, {"hierarchy": hierarchy["Food Identity"], "isLookupBearing": True})
        for tool in (STOVE, OVEN):
            client.upsert("DomainType", "name", tool, {"hierarchy": hierarchy["Equipment Type"], "isLookupBearing": True})

        print("\n[1] Load the file...")
        doc = recipe_file()
        report = import_recipe(client, doc)
        check(export_plan(client, report.plan_id) == doc.plan_part(), "the Plan reads back exactly as the file says, facts and all")
        check(import_recipe(client, doc).plan_unchanged, "the same file again changes nothing")

        print("\n[2] Where the model keeps each fact...")
        plan = f"{DISH} v1"
        simmer, roast, serve = (named("Step", f"{plan} step {i} -- {label}")
                                for i, label in ((2, "simmer the rice"), (3, "roast the chicken"), (4, "serve")))
        wait = client.get_all("QuantitySpecification", simmer["hasWaitingTime"]["id"])["result"]
        check((wait.get("value"), wait.get("unit"), wait.get("status")) == (18.0, "minutes", "specified"),
              "a waiting time is a QuantitySpecification in minutes")
        check([r["name"] for r in simmer.get("isPrecededBy") or []] == [f"{plan} step 1 -- rinse the rice"]
              and (roast.get("isPrecededBy") or []) == []
              and sorted(r["name"] for r in serve.get("isPrecededBy") or []) == [f"{plan} step 2 -- simmer the rice", f"{plan} step 3 -- roast the chicken"],
              "isPrecededBy: the rice in order, the roast beside it, the serving after both")
        burner = named("StateRequirement", f"{plan} step 2 equipment 1 {STOVE} heat")
        check(burner is not None and (burner.get("targetsProperty") or {}).get("name") == "Heat Level"
              and burner.get("expectedValueLiteral") == "low", "the burner's heat: Heat Level, low")
        oven = named("StateRequirement", f"{plan} step 3 equipment 1 {OVEN} heat")
        oven_value = client.get_all("QuantitySpecification", oven["expectedValueQty"]["id"])["result"] if oven else {}
        check(oven is not None and (oven.get("targetsProperty") or {}).get("name") == "Temperature"
              and (oven_value.get("value"), oven_value.get("unit")) == (425.0, "degF"), "the oven's: Temperature, 425 degF")
        done = named("StateRequirement", f"{plan} step 3 output {ROASTED} doneness")
        inside = named("StateRequirement", f"{plan} step 3 output {ROASTED} inside")
        check(done is not None and done.get("expectedValueLiteral") == "golden" and inside is not None
              and (inside.get("targetsProperty") or {}).get("name") == "Temperature",
              "the roast's doneness: golden, and a Temperature inside, on its output")

        print("\n[3] An edited file...")
        edited = recipe_file(edited=True)
        changed = import_recipe(client, edited)
        check(not changed.plan_unchanged and export_plan(client, report.plan_id) == edited.plan_part(),
              "the Plan reads back as the edited file")
        check(named("StateRequirement", f"{plan} step 3 equipment 1 {OVEN} heat") is None
              and named("StateRequirement", f"{plan} step 3 output {ROASTED} doneness") is None
              and named("StateRequirement", f"{plan} step 3 output {ROASTED} inside") is None
              and named("QuantitySpecification", f"{plan} step 3 -- roast the chicken waiting time") is None
              and named("QuantitySpecification", f"{plan} step 3 equipment 1 {OVEN} heat value") is None,
              "and the facts it took out are gone, with their values")
        roast = named("Step", f"{plan} step 3 -- roast the chicken")
        check([r["name"] for r in roast.get("isPrecededBy") or []] == [f"{plan} step 2 -- simmer the rice"],
              "the roast now after the rice")
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
