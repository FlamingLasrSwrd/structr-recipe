"""Seeds vocabulary for the realistic full-lifecycle test pass. See
mealplanner/seed_vocabulary.py's REALISTIC_PASS_* lists.

Run with: python3 scripts/15b_seed_realistic_vocab.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.seed_vocabulary import REALISTIC_PASS_HIERARCHIES, REALISTIC_PASS_DOMAIN_TYPES

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    hierarchy_ids = {}
    for name, single_parent in REALISTIC_PASS_HIERARCHIES:
        hierarchy_ids[name] = client.upsert("TypeHierarchy", "name", name, {"singleParent": single_parent})
        print(f"hierarchy {name}: {hierarchy_ids[name]}")

    domain_type_ids = {}
    for name, hierarchy_name, parent_name, is_lookup_bearing in REALISTIC_PASS_DOMAIN_TYPES:
        hierarchy_id = hierarchy_ids.get(hierarchy_name) or client.get(
            "/structr/rest/TypeHierarchy", params={"name": hierarchy_name}
        )["result"][0]["id"]
        fields = {"hierarchy": hierarchy_id, "isLookupBearing": is_lookup_bearing}
        if parent_name is not None:
            fields["parent"] = domain_type_ids.get(parent_name) or client.get(
                "/structr/rest/DomainType", params={"name": parent_name}
            )["result"][0]["id"]
        domain_type_ids[name] = client.upsert("DomainType", "name", name, fields)
        print(f"domain type {name}: {domain_type_ids[name]}")

    print("\nDone.")


if __name__ == "__main__":
    main()
