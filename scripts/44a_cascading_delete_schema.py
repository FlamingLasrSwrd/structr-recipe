"""Delete what a recipe's Step owns with it (docs/structr-features.md, batch 2;
mealplanner/cascade_schema.py).

Sets Structr's cascadingDeleteFlag to source-to-target on the seven relationships by which a Step
owns its Specifications and its working and waiting minutes, a Specification its quantity, state
requirements and substitution rules, and a state requirement its value. Deleting a Step or a
Specification then deletes what it owns in the same transaction, which recipe_import did by hand.

Structr deletes a target even when something else still points at it (the cascade_more spike), so
before setting anything this reads every node the seven point at and stops, changing nothing, if
any is held by more than its owner: the cascade would delete it from under the other.

Schema only and idempotent, so like 30a to 43a it must also run against the owner's instance
(owner_data_ok=True). Restart Structr after it before trusting a check (hard rule 8).

Run with: python3 scripts/44a_cascading_delete_schema.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.cascade_schema import CASCADING, SOURCE_TO_TARGET, declarations, relationship_rows, shared_targets
from mealplanner.connection import connect


def main():
    client = connect(owner_data_ok=True)     # schema only; the owner's instance needs it too
    client.wait_until_ready()

    rows = relationship_rows(client)
    missing = [rel_type for rel_type in CASCADING if rel_type not in rows]
    if missing:
        print(f"FAILED: not declared here: {', '.join(missing)} (scripts/06a, 41a and 42a declare them)")
        sys.exit(1)
    to_set = [rel_type for rel_type in CASCADING if rows[rel_type].get("cascadingDeleteFlag") != SOURCE_TO_TARGET]

    print("[1] What the cascades would delete that something else holds too...")
    if to_set:
        shared = shared_targets(client)
        for line in shared:
            print(f"    {line}")
        if shared:
            print(f"FAILED: {len(shared)} node(s) held by more than their owner; nothing was changed. Give each its own "
                  f"node, then run this again")
            sys.exit(1)
        print("    none")
    else:
        print("    (every flag is already set)")

    print("[2] Cascading delete, source to target...")
    for source, rel_type, target, *_ in declarations():
        if rel_type in to_set:
            client.patch(f"/structr/rest/SchemaRelationshipNode/{rows[rel_type]['id']}",
                         {"cascadingDeleteFlag": SOURCE_TO_TARGET})
        print(f"    {source} -[{rel_type}]-> {target}  set={rel_type in to_set}")
    if to_set:
        print("\nRestart Structr before trusting a check of it (hard rule 8).")


if __name__ == "__main__":
    main()
