"""Let a recipe say what may stand in for an ingredient (data-model.md Sec 5.3, Sec 18 J36;
mealplanner/substitution_schema.py), and check each rule as it is written: for an input
Specification, its candidate from the same hierarchy (invariants 21 and 22,
mealplanner/domain_invariants.py).

Schema only and idempotent, so like 30a to 41a it must also run against the owner's instance
(owner_data_ok=True). Restart Structr before trusting a check made right after it (hard rule 8).

Run with: python3 scripts/42a_substitution_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.domain_invariants import SUBSTITUTION_RULE_ONCREATE
from mealplanner.substitution_schema import PROPERTIES, RELATIONSHIPS


def schema_node(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()

    print("[1] Properties...")
    for type_name, props in PROPERTIES.items():
        node = schema_node(client, type_name)
        for prop in props:
            _, created = client.ensure_property(node, prop["name"], prop["propertyType"], format=prop.get("format"))
            print(f"    {type_name}.{prop['name']} ({prop['propertyType']})  created={created}")

    print("[2] Relationships...")
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in RELATIONSHIPS:
        _, created = client.ensure_relationship(
            source_id=schema_node(client, source), target_id=schema_node(client, target), relationship_type=rel_type,
            source_multiplicity=src_mult, target_multiplicity=tgt_mult,
            source_json_name=src_json, target_json_name=tgt_json,
        )
        print(f"    {source} -[{rel_type}]-> {target}  (source.{tgt_json}, target.{src_json})  created={created}")

    print("[3] Invariants 21 and 22, as each rule is written...")
    method_id, created = client.ensure_method(schema_node(client, "SubstitutionRule"), "onCreate", SUBSTITUTION_RULE_ONCREATE,
                                              return_raw_result=False)
    print(f"    SubstitutionRule.onCreate: id={method_id}, created={created}")


if __name__ == "__main__":
    main()
