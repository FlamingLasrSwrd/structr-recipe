"""The recipe loader against real Structr (mealplanner/recipe_import.py).

A two-step TEST recipe file is loaded, loaded again, edited, frozen by a cook
and versioned, and at each point read back through the same engines the
planner uses: nutrition from ingredients (J18, with units, J17) and raw-
ingredient demand in grams. Everything is TEST-named, swept before and deleted
after.

The fixture and the figures worked out by hand (per 100 g; rice has a density
of 0.8 g/mL, and a cup is 236.588 mL):

                  protein   energy     sodium
  Rice (dry)        7 g     360 kcal     5 mg     1.5 cup = 1.5 x 236.588 x 0.8 = 283.9056 g
  Chickpeas         7 g     139 kcal   250 mg     400 g (300 g after the edit)
  Salt              0 g       0 kcal 38758 mg     6 g (removed by the edit)

  per serving of 4:
    protein  (283.9056 x 0.07 + 400 x 0.07) / 4                    = 11.968348 g
    energy   (283.9056 x 3.60 + 400 x 1.39) / 4                    = 394.51504 kcal
    sodium   (283.9056 x 0.05 + 400 x 2.5 + 6 x 387.58) / 4        = 834.91882 mg
    sodium after the edit  (283.9056 x 0.05 + 300 x 2.5) / 4       = 191.04882 mg

Run with: python3 scripts/29b_recipe_import_demo.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.material_accounting import candidate_input_requirements
from mealplanner.nutrition_scope import serving_nutrient_figure
from mealplanner.recipe_import import RecipeFrozenError, export_plan, import_recipe, read_recipe
from mealplanner.typetree import dt

P = "TEST -- Z29 "
RICE, CHICKPEAS, SALT = P + "Rice (dry)", P + "Chickpeas", P + "Salt"
RICE_COOKED, DISH = P + "Rice (cooked)", P + "Chickpea Rice"
PROFILES = {  # food: {nutrient: (amount per 100 g, unit)}
    RICE: {"Protein": (7.0, "g"), "Energy": (360.0, "kcal"), "Sodium": (5.0, "mg")},
    CHICKPEAS: {"Protein": (7.0, "g"), "Energy": (139.0, "kcal"), "Sodium": (250.0, "mg")},
    SALT: {"Protein": (0.0, "g"), "Energy": (0.0, "kcal"), "Sodium": (38758.0, "mg")},
}
RICE_G = 1.5 * 236.588 * 0.8
SWEEP_ORDER = ["Process", "Identifier", "Specification", "Step", "Plan", "RecipeIdentity", "NutrientProfile",
               "DefaultSpecification", "QuantitySpecification", "DomainType"]

FILE = f"""
name = "{DISH}"
source = "https://example.org/chickpea-rice"
servings = 4
minutes = 35
difficulty = "easy"
meal_types = ["Dinner", "Lunch"]

[[steps]]
name = "boil the rice"
method = "Boiling"
makes = "{RICE_COOKED}"
inputs = [{{ food = "{RICE}", amount = 1.5, unit = "cup" }}]

[[steps]]
name = "fold in"
inputs = [
  {{ food = "{RICE_COOKED}" }},
  {{ food = "{CHICKPEAS}", amount = {{chickpeas}}, unit = "g" }},
  {{salt}}
]
"""


def recipe_file(chickpeas=400, salt=True, version=None):
    text = FILE.replace("{chickpeas}", str(chickpeas))
    text = text.replace("{salt}", f'{{ food = "{SALT}", amount = 6, unit = "g" }}' if salt else "")
    if version:
        text = text.replace("servings = 4", f"version = {version}\nservings = 4")
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

    def close(a, b):
        return a is not None and abs(a - b) < 1e-6

    sweep(client)
    try:
        print("[0] Fixture: three TEST ingredients with sourced profiles, rice with a density...")
        food_h = client.get("/structr/rest/TypeHierarchy", params={"name": "Food Identity"})["result"][0]["id"]
        nutrient_h = client.get("/structr/rest/TypeHierarchy", params={"name": "Nutrient"})["result"][0]["id"]
        nutrients = {"Protein": dt(client, "Protein")}
        for name in ("Energy", "Sodium"):
            nutrients[name] = client.upsert("DomainType", "name", P + name, {"hierarchy": nutrient_h, "isLookupBearing": True})
        foods = {}
        for food, figures in PROFILES.items():
            foods[food] = client.upsert("DomainType", "name", food, {"hierarchy": food_h, "isLookupBearing": True})
            for nutrient, (amount, unit) in figures.items():
                client.upsert("NutrientProfile", "name", f"{food} {nutrient} profile", {
                    "isAbout": foods[food], "forNutrient": nutrients[nutrient], "amount": amount, "basis": "per_100g",
                    "unit": unit, "provenance": "sourced"})
        density = client.upsert("QuantitySpecification", "name", P + "rice density", {
            "value": 0.8, "unit": "g_per_mL", "status": "default"})
        client.upsert("DefaultSpecification", "name", P + "rice density default", {
            "forType": foods[RICE], "hasKind": dt(client, "Density"), "hasValue": density})

        print("\n[1] Load the file...")
        doc = recipe_file()
        report = import_recipe(client, doc)
        plan = client.get_all("Plan", report.plan_id)["result"]
        check(sorted(report.created_types) == sorted([RICE_COOKED, DISH]), "the dish and the cooked rice are new food types")
        check(not report.plan_unchanged and not report.removed, "a first load creates and removes nothing else")
        check(report.unconvertible == [] and report.without_profiles == [], "every quantity converts and every ingredient has profiles")
        check(export_plan(client, report.plan_id) == doc.plan_part(), "the Plan reads back exactly as the file says")
        recipe = client.get_all("RecipeIdentity", report.recipe_id)["result"]
        check(sorted(m["name"] for m in recipe.get("hasMealType", [])) == ["Dinner", "Lunch"], "meal types")
        source = [client.get_all("Identifier", r["id"])["result"] for r in recipe.get("identifiers", [])]
        check([(s.get("identifierValue"), (s.get("identifierScheme") or {}).get("name")) for s in source]
              == [("https://example.org/chickpea-rice", "Web page")], "the source page is an Identifier of the recipe")
        demand = {client.get_all("DomainType", t)["result"]["name"]: g for t, g in candidate_input_requirements(client, plan)}
        check(set(demand) == {RICE, CHICKPEAS, SALT} and close(demand[RICE], RICE_G) and demand[CHICKPEAS] == 400.0,
              f"demand is the raw ingredients in grams, the cooked rice left out ({RICE_G:.4f} g of rice)")

        print("\n[2] Nutrition per serving, from the ingredients...")
        protein = serving_nutrient_figure(client, plan, nutrients["Protein"], "g")
        energy = serving_nutrient_figure(client, plan, nutrients["Energy"], "kcal")
        sodium = serving_nutrient_figure(client, plan, nutrients["Sodium"], "mg")
        check(protein.method == "ingredients" and close(protein.amount, (RICE_G * 0.07 + 400 * 0.07) / 4),
              f"protein {protein.amount} g")
        check(close(energy.amount, (RICE_G * 3.6 + 400 * 1.39) / 4), f"energy {energy.amount} kcal")
        check(close(serving_nutrient_figure(client, plan, nutrients["Energy"], "kJ").amount,
                    (RICE_G * 3.6 + 400 * 1.39) / 4 * 4.184), "the same energy in kJ")
        check(close(sodium.amount, (RICE_G * 0.05 + 400 * 2.5 + 6 * 387.58) / 4), f"sodium {sodium.amount} mg")
        check(not protein.trusted and protein.unadjusted == (RICE, CHICKPEAS),
              "with no retention factors the figure is untrusted, naming the ingredients (salt has no protein)")
        for food in (RICE, CHICKPEAS):
            factor = client.upsert("QuantitySpecification", "name", f"{food} protein retention", {
                "value": 1.0, "unit": "ratio", "status": "default"})
            client.upsert("DefaultSpecification", "name", f"{food} protein retention default", {
                "forType": foods[food], "hasKind": dt(client, "RetentionFactor"), "hasValue": factor,
                "keyedBy": [nutrients["Protein"]]})
        check(serving_nutrient_figure(client, plan, nutrients["Protein"], "g").trusted,
              "with a protein retention factor on each ingredient it is trusted (resolved through real Structr)")

        print("\n[3] Load it again, then an edited file...")
        again = import_recipe(client, doc)
        check(again.plan_unchanged and not again.removed and not again.created_types and again.plan_id == report.plan_id,
              "the same file changes nothing")
        edited = recipe_file(chickpeas=300, salt=False)
        changed = import_recipe(client, edited)
        check(changed.plan_id == report.plan_id and changed.removed == [f"{DISH} v1 step 2 input 3 {SALT}"],
              "an edited file updates the same Plan and removes the dropped ingredient")
        check(not client.get("/structr/rest/QuantitySpecification", params={"name": f"{DISH} v1 step 2 input 3 {SALT} quantity"})["result"],
              "and its quantity")
        check(export_plan(client, report.plan_id) == edited.plan_part(), "the Plan reads back as the edited file")
        plan = client.get_all("Plan", report.plan_id)["result"]
        check(close(serving_nutrient_figure(client, plan, nutrients["Sodium"], "mg").amount, (RICE_G * 0.05 + 300 * 2.5) / 4),
              "sodium follows the edit")

        print("\n[4] Once cooked, a Plan is history...")
        client.upsert("Process", "name", P + "cook", {"concretizes": report.plan_id})
        check(import_recipe(client, edited).plan_unchanged, "the unchanged file still loads")
        try:
            import_recipe(client, recipe_file(chickpeas=250, salt=False))
            check(False, "a changed file is refused")
        except RecipeFrozenError:
            check(True, "a changed file is refused")
        check(export_plan(client, report.plan_id) == edited.plan_part(), "and the cooked Plan is untouched")
        v2 = import_recipe(client, recipe_file(chickpeas=250, salt=False, version=2))
        versions = client.get_all("RecipeIdentity", report.recipe_id)["result"].get("planVersions", [])
        check(v2.plan_id != report.plan_id and v2.recipe_id == report.recipe_id and len(versions) == 2,
              "the change loads as version 2 of the same recipe")
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
