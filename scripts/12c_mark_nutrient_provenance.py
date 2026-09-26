"""Migrate NutrientProfile provenance from a naming convention to data.

Until now the only sign that a nutrient profile's number was a placeholder was
the text "[PLACEHOLDER -- not sourced from USDA/FDC yet]" in its name. The
planner will not decide a hard NutritionTarget on placeholder data (data-model.md
Sec 18 J15), and a rule like that cannot rest on a substring of a name, so the
profile now carries `provenance` ("placeholder" or "sourced").

This marks every existing profile whose name carries the placeholder note as
`placeholder`, and leaves any profile without the note UNSET, which the planner
treats as untrusted. Nothing is ever marked `sourced` by this script: only a
person who has checked a figure against a source can say that. New profiles are
created with provenance already set (12b, 15d), so on a fresh build this finds
nothing to change.

Run with: python3 scripts/12c_mark_nutrient_provenance.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect

PLACEHOLDER_MARKER = "[PLACEHOLDER"


def main():
    client = connect()
    client.wait_until_ready()
    changed, already, unmarked = [], [], []
    for profile in client.get_all("NutrientProfile")["result"]:
        name = profile["name"]
        if profile.get("provenance"):
            already.append(name)
        elif PLACEHOLDER_MARKER in name:
            client.patch(f"/structr/rest/NutrientProfile/{profile['id']}", {"provenance": "placeholder"})
            changed.append(name)
        else:
            unmarked.append(name)
    print(f"marked placeholder: {len(changed)}; already set: {len(already)}; left unset (untrusted): {len(unmarked)}")
    for name in unmarked:
        print(f"    unset: {name}")

    failures = [
        p["name"] for p in client.get_all("NutrientProfile")["result"]
        if PLACEHOLDER_MARKER in p["name"] and p.get("provenance") != "placeholder"
    ]
    print(f"    [{'OK' if not failures else 'FAIL'}] every profile carrying the placeholder note is marked placeholder")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
