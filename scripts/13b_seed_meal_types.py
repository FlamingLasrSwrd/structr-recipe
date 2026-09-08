"""Seed the Meal Type ConceptScheme and its four Concepts, and tag the
existing recipes -- including deliberately NOT tagging the prep-step
and structural-test recipes, so they fall out of the selector's
candidate pool without needing a separate "is this a real meal" concept.

Run with: python3 scripts/13b_seed_meal_types.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.meal_type_schema import MEAL_TYPES

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] Meal Type ConceptScheme + Concepts...")
    scheme_id = client.upsert("ConceptScheme", "name", "Meal Type", {})
    concept_ids = {}
    for name in MEAL_TYPES:
        concept_ids[name] = client.upsert("Concept", "name", name, {"inScheme": scheme_id})
    print(f"    scheme={scheme_id}")
    for name, cid in concept_ids.items():
        print(f"    {name}: {cid}")

    print("\n[2] Tagging recipes -- Diced Onion (prep step) and Simple Saute "
          "(structural test fixture) are deliberately left UNTAGGED...")
    taggings = {
        "Braised Chicken Breast": ["Dinner"],
        "TEST -- Boiled Pasta": ["Lunch", "Dinner"],
        "TEST -- Almond Snack": ["Snack"],
    }
    for recipe_name, meal_types in taggings.items():
        recipe_id = client.get("/structr/rest/RecipeIdentity", params={"name": recipe_name})["result"][0]["id"]
        client.patch(f"/structr/rest/RecipeIdentity/{recipe_id}", {
            "hasMealType": [concept_ids[mt] for mt in meal_types],
        })
        print(f"    {recipe_name} -> {meal_types}")

    print("\n[3] Verification...")
    all_ok = True

    dinner = client.get_all("Concept", concept_ids["Dinner"])["result"]
    dinner_recipes = {r["name"] for r in dinner.get("taggedRecipes", [])}
    ok = dinner_recipes == {"Braised Chicken Breast", "TEST -- Boiled Pasta"}
    print(f"    [{'OK' if ok else 'FAIL'}] Dinner.taggedRecipes = {dinner_recipes}")
    all_ok &= ok

    onion = client.get_all("RecipeIdentity", client.get("/structr/rest/RecipeIdentity", params={"name": "TEST -- Diced Onion"})["result"][0]["id"])["result"]
    ok = not onion.get("hasMealType")
    print(f"    [{'OK' if ok else 'FAIL'}] Diced Onion has no meal-type tags (hasMealType={onion.get('hasMealType')})")
    all_ok &= ok

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
