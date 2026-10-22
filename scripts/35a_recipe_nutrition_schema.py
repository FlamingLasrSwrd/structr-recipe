"""Let a recipe version keep its own nutrition per serving (data-model.md Sec 18 J28).

The owner decided (2026-10-22) that a recipe's nutrition per serving is calculated
once and stored, not worked out from every ingredient each time a week is planned.
This adds what that needs to an instance built before it:

  - NutrientProfile.basis gains "per_serving" (it was "per_100g,per_unit"). The
    drift-refusing schema helper will not widen an enum, so the SchemaProperty's
    format is changed here, once, as scripts/30a did for provenance.
  - NutrientProfile -[SERVING_OF]-> Plan (mealplanner/recipe_nutrition_schema.py).

Schema only and idempotent, so like 30a to 34a it must also run against the owner's
instance (owner_data_ok=True). Restart Structr before trusting a check made right
after it (hard rule 8).

Run with: python3 scripts/35a_recipe_nutrition_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.nutrition_schema import BASIS_FORMAT, OLD_BASIS_FORMAT
from mealplanner.recipe_nutrition_schema import RELATIONSHIPS


def schema_node(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()

    print("[1] NutrientProfile.basis values...")
    node = schema_node(client, "NutrientProfile")
    (prop,) = client.get("/structr/rest/SchemaProperty", params={"schemaNode": node, "name": "basis"})["result"]
    live = client.get_all("SchemaProperty", prop["id"])["result"].get("format")
    if live == OLD_BASIS_FORMAT:
        client.patch(f"/structr/rest/SchemaProperty/{prop['id']}", {"format": BASIS_FORMAT})
        print(f"    widened: {OLD_BASIS_FORMAT!r} -> {BASIS_FORMAT!r}")
    elif live == BASIS_FORMAT:
        print("    already widened")
    else:
        print(f"    [FAIL] unexpected format {live!r}; nothing changed")
        sys.exit(1)

    print("\n[2] Relationships...")
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        _, created = client.ensure_relationship(
            source_id=schema_node(client, source), target_id=schema_node(client, target), relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  (source.{tgt_json}, target.{src_json})  created={created}")

    print("\n[3] Check...")
    live = client.get_all("SchemaProperty", prop["id"])["result"].get("format")
    ok = live == BASIS_FORMAT
    print(f"    [{'OK' if ok else 'FAIL'}] NutrientProfile.basis is {live!r}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
