"""Give every NutrientProfile the unit of its amount (data-model.md Sec 18 J17).

Until now a NutrientProfile had no unit: its amount was grams per 100 g by
convention (J4), which cannot hold an energy in kcal, a mineral in mg or a
vitamin in micrograms. `unit` is now a property (mealplanner/nutrition_schema.py)
and a profile without one is refused when read (nutrition_scope.NutrientUnitError)
rather than assumed to be grams.

This adds the property to an existing instance and writes "g" on every profile
that was created under the old convention: basis per_100g and no unit. A
profile with no unit and any other basis is not guessed at; it is listed and
the script fails. New profiles are created with their unit (12b, 15d, 26a), so
on a fresh build this finds nothing to change.

Numbered 28 because 27 is taken by scripts/27_public_pages.py on the suspended
public-access branch.

Run with: python3 scripts/28a_nutrient_profile_units.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.nutrition_schema import PROPERTIES
from mealplanner.nutrition_scope import NutrientUnitError, nutrient_unit

CONVENTION_UNIT = "g"


def main():
    client = connect()
    client.wait_until_ready()

    print("[1] NutrientProfile.unit...")
    node = client.get("/structr/rest/SchemaNode", params={"name": "NutrientProfile"})["result"][0]
    (prop,) = [p for p in PROPERTIES["NutrientProfile"] if p["name"] == "unit"]
    _, created = client.ensure_property(node["id"], prop["name"], prop["propertyType"])
    print(f"    created={created}")

    print("\n[2] Profiles created under the grams convention...")
    changed, already, refused = [], [], []
    for profile in client.get_all("NutrientProfile")["result"]:
        if profile.get("unit"):
            already.append(profile["name"])
        elif profile.get("basis") == "per_100g":
            client.patch(f"/structr/rest/NutrientProfile/{profile['id']}", {"unit": CONVENTION_UNIT})
            changed.append(profile["name"])
        else:
            refused.append(profile["name"])
    print(f"    set to {CONVENTION_UNIT!r}: {len(changed)}; already had a unit: {len(already)}; "
          f"no unit and not per_100g (not guessed): {len(refused)}")
    for name in refused:
        print(f"        refused: {name}")

    print("\n[3] Check...")
    unreadable = []
    for profile in client.get_all("NutrientProfile")["result"]:
        try:
            nutrient_unit(profile.get("unit"), profile["name"])
        except NutrientUnitError as exc:
            unreadable.append(str(exc))
    ok = not refused and not unreadable
    print(f"    [{'OK' if ok else 'FAIL'}] every NutrientProfile states a nutrient unit")
    for text in unreadable:
        print(f"        {text}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
