"""What a recipe's Step owns, deleted with it by Structr, on real Structr (docs/structr-features.md,
batch 2; mealplanner/cascade_schema.py, scripts/44a).

A two-step TEST recipe whose first step has everything a step can own: an ingredient's quantity, a
substitute's rule, working and waiting minutes, an oven's temperature and what the step makes, with
its doneness and its temperature inside. It is loaded, and every node the first step owns is noted.
Then:

  [1] the instance has the flags (44a);
  [2] the file loaded again without the first step: the importer deletes the Step alone, and every node
      it owned is gone with it;
  [3] one Specification deleted through REST: its quantity and its rule go with it, its Step stays;
  [4] a TEST quantity given to two Specifications is found by shared_targets(), which 44a refuses over.

Everything is TEST-named, swept before and deleted after.

Run with: python3 scripts/44b_cascading_delete_demo.py
"""

import os
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.cascade_schema import not_cascading, owned_by, shared_targets
from mealplanner.connection import connect
from mealplanner.recipe_import import export_plan, import_recipe, read_recipe
from structr_client import StructrError

P = "TEST -- Z44 "
RICE, BUTTER, OIL, CHICKEN = P + "Rice", P + "Butter", P + "Olive Oil", P + "Chicken"
ROASTED, DISH, OVEN = P + "Chicken (roasted)", P + "Roast Chicken", P + "Oven"
SWEEP_ORDER = ["SubstitutionRule", "StateRequirement", "Specification", "Step", "Plan", "RecipeIdentity",
               "QuantitySpecification", "DomainType"]

ROAST = f"""
[[steps]]
name = "roast the chicken"
makes = "{ROASTED}"
minutes = 5
wait_minutes = 40
until = "golden"
inside = {{ temp = 165, unit = "F" }}
equipment = [{{ tool = "{OVEN}", temp = 425, unit = "F" }}]
inputs = [{{ food = "{CHICKEN}", amount = 300, unit = "g" }},
          {{ food = "{BUTTER}", amount = 1, unit = "tbsp", substitutes = [{{ food = "{OIL}" }}] }}]
"""
SERVE = f"""
[[steps]]
name = "serve"
inputs = [{{ food = "{RICE}", amount = 150, unit = "g" }}, {{ food = "{ROASTED}" }}]
"""


def recipe_file(roast=True):
    text = f'name = "{DISH}"\nservings = 2\nmeal_types = ["Dinner"]\n' + (ROAST if roast else "") + SERVE
    if not roast:
        text = text.replace(f'{{ food = "{ROASTED}" }}', f'{{ food = "{CHICKEN}", amount = 300, unit = "g" }}')
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

    def exists(type_name, node_id):
        try:
            client.get(f"/structr/rest/{type_name}/{node_id}")
            return True
        except StructrError as e:
            if e.status == 404:
                return False
            raise

    def owned(type_name, node_id):
        """Every (type, id) the node owns, and what those own in turn, by cascade_schema's properties."""
        node = client.get_all(type_name, node_id)["result"]
        out = []
        for key in owned_by().get(type_name, []):
            value = node.get(key)
            for ref in [value] if isinstance(value, dict) else value or []:
                out.append((ref["type"], ref["id"]))
                out.extend(owned(ref["type"], ref["id"]))
        return out

    sweep(client)
    try:
        print("[0] Fixture: four TEST foods and a TEST oven, and the recipe loaded...")
        hierarchy = lambda name: client.get("/structr/rest/TypeHierarchy", params={"name": name})["result"][0]["id"]
        food_h = hierarchy("Food Identity")
        for food in (RICE, BUTTER, OIL, CHICKEN):
            client.upsert("DomainType", "name", food, {"hierarchy": food_h, "isLookupBearing": True})
        client.upsert("DomainType", "name", OVEN, {"hierarchy": hierarchy("Equipment Type")})
        report = import_recipe(client, recipe_file())
        steps = {s["name"]: s["id"] for s in client.get_all("Plan", report.plan_id)["result"]["steps"]}
        roast = steps[f"{DISH} v1 step 1 -- roast the chicken"]
        roast_owns = owned("Step", roast)
        # By hand: Specifications for the chicken, the butter, the roasted chicken and the oven (4);
        # quantities for the chicken, the butter, 5 and 40 minutes, 425 and 165 F (6); requirements for the
        # oven's heat, the doneness and the inside temperature (3); the olive oil's rule (1).
        kinds = Counter(t for t, _ in roast_owns)
        check(kinds == {"Specification": 4, "QuantitySpecification": 6, "StateRequirement": 3, "SubstitutionRule": 1},
              f"the roasting step owns 14 nodes: {dict(kinds)}")

        print("\n[1] The flags...")
        check(not_cascading(client) == [], "every cascading relationship has its flag (scripts/44a)")

        print("\n[2] The file again, without the roasting step...")
        edited = recipe_file(roast=False)
        again = import_recipe(client, edited)
        check(export_plan(client, again.plan_id) == edited.plan_part(), "the Plan reads back as the edited file says")
        check(not exists("Step", roast), "the roasting Step is gone")
        left = [(t, i) for t, i in roast_owns if exists(t, i)]
        check(not left, f"and everything it owned with it, {len(roast_owns)} nodes ({len(left)} left)")

        print("\n[3] One Specification deleted through REST...")
        import_recipe(client, recipe_file())
        steps = {s["name"]: s["id"] for s in client.get_all("Plan", report.plan_id)["result"]["steps"]}
        roast = steps[f"{DISH} v1 step 1 -- roast the chicken"]
        butter = next(s for s in client.get_all("Step", roast)["result"]["hasSpecification"] if BUTTER in s["name"])
        butter_owns = owned("Specification", butter["id"])
        check(sorted(t for t, _ in butter_owns) == ["QuantitySpecification", "SubstitutionRule"],
              "the butter's Specification owns a quantity and a rule")
        client.delete(f"/structr/rest/Specification/{butter['id']}")
        check(not any(exists(t, i) for t, i in butter_owns), "both went with it")
        check(exists("Step", roast), "its Step stays")

        print("\n[4] A quantity held by two Specifications...")
        specs = client.get_all("Step", roast)["result"]["hasSpecification"]
        chicken = next(s for s in specs if CHICKEN in s["name"] and " input " in s["name"])
        quantity = client.get_all("Specification", chicken["id"])["result"]["hasSpecifiedQuantity"]
        output = next(s for s in specs if " output " in s["name"])
        client.patch(f"/structr/rest/Specification/{output['id']}", {"hasSpecifiedQuantity": quantity["id"]})
        found = [line for line in shared_targets(client) if P in line]
        check(len(found) == 1 and quantity["name"] in found[0] and "held by 2" in found[0],
              f"shared_targets() names it, and 44a would refuse: {found}")
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
