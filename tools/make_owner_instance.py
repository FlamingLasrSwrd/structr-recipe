"""Turn a freshly built instance into the one that holds the owner's data.

    STRUCTR_URL=http://localhost:8085 python3 tools/make_owner_instance.py

tools/owner_stack.sh build runs this after a full build; it is not meant to be
run by hand on anything else. The full build (every script, checked against
tools/expected_state.json) is the only proven way to build the schema, and it
leaves demo recipes, cooks, meal plans and placeholder figures behind. This
removes all of that, keeping the schema and the curated vocabulary, then marks
the instance (mealplanner/connection.OWNER_MARKER) so no demo or test script
can run against it again.

Removed:
  - every instance of a content type (the list scripts/15a resets, plus
    Identifier and NutrientProfile: every profile a build leaves is a placeholder);
  - every DefaultSpecification, since every one a build leaves is a placeholder
    ("[PLACEHOLDER -- not sourced ...]") or TEST data, and every
    QuantitySpecification (after the above, none is referenced);
  - TEST-named vocabulary, and the two demo dishes, which are food types only
    because a demo cooked them.
Unknown stays unknown: without the placeholder shelf lives, yields and
densities, those figures are simply absent until sourced ones are loaded.

It refuses an instance that does not match the golden full build exactly, so it
never deletes anything it has not been told about, and checks the result
against tools/expected_state_owner.json.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mealplanner.connection import OWNER_MARKER, connect, is_owner_instance
from snapshot_state import render, snapshot

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FULL_BUILD = os.path.join(ROOT, "tools", "expected_state.json")
OWNER_GOLDEN = os.path.join(ROOT, "tools", "expected_state_owner.json")

CONTENT_TYPES = [   # scripts/15a_reset_instance_data.py's list, then the two types it did not need
    "MealPlanEntry", "MealPlan", "AcquisitionList",
    "StockPolicy", "NutritionTarget", "ExclusionConstraint",
    "Allocation", "Process", "TemporalRegion",
    "Measurement", "Quality", "Disposition", "Function", "Role",
    "PortionOfSubstance", "DiscreteWholeItem", "ContainerObject", "EquipmentObject",
    "StateRequirement", "Specification", "Step", "Plan", "RecipeIdentity",
    "Identifier", "NutrientProfile",
]
FIGURE_TYPES = ["DefaultSpecification", "QuantitySpecification"]
VOCAB_TYPES = ["DomainType", "TypeHierarchy", "Concept", "ConceptScheme"]
DEMO_DISHES = ["Beef and Broccoli Stir-Fry", "Buttered Pasta with Parmesan"]
TEST = "TEST -- "


def purge(client) -> dict[str, int]:
    counts = {}
    for type_name in CONTENT_TYPES + FIGURE_TYPES:
        rows = client.get_all(type_name)["result"]
        for row in rows:
            client.delete(f"/structr/rest/{type_name}/{row['id']}")
        counts[type_name] = len(rows)
    for type_name in VOCAB_TYPES:
        rows = [r for r in client.get_all(type_name)["result"]
                if (r.get("name") or "").startswith(TEST) or (type_name == "DomainType" and r.get("name") in DEMO_DISHES)]
        for row in rows:
            client.delete(f"/structr/rest/{type_name}/{row['id']}")
        counts[type_name] = len(rows)
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write-golden", action="store_true",
                        help="write the result to tools/expected_state_owner.json instead of comparing (review the diff)")
    args = parser.parse_args(argv)

    client = connect(owner_data_ok=True)
    client.wait_until_ready()
    if is_owner_instance(client):
        print("This instance already holds the owner's data; nothing done.")
        return 1
    with open(FULL_BUILD) as fh:
        if render(snapshot(client)) + "\n" != fh.read():
            print("This instance is not exactly a full build (tools/expected_state.json), so what it holds is not "
                  "known; nothing done. Build it with tools/owner_stack.sh build.")
            return 1

    counts = purge(client)
    for type_name, count in counts.items():
        if count:
            print(f"    removed {count:4d} {type_name}")
    client.upsert("Concept", "name", OWNER_MARKER, {})

    result = render(snapshot(client)) + "\n"
    leftovers = [line.strip() for line in result.splitlines() if TEST in line or "[PLACEHOLDER" in line]
    if leftovers:
        print(f"[FAIL] {len(leftovers)} TEST or placeholder line(s) remain, e.g. {leftovers[:3]}")
        return 1
    if args.write_golden:
        with open(OWNER_GOLDEN, "w") as fh:
            fh.write(result)
        print(f"wrote {OWNER_GOLDEN}: review it")
        return 0
    with open(OWNER_GOLDEN) as fh:
        same = result == fh.read()
    print(f"[{'OK' if same else 'FAIL'}] the instance matches tools/expected_state_owner.json, and is marked as the owner's")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
