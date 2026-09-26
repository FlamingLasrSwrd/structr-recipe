"""Seeds Fresh Meat's shelf life keyed by (storage condition, opened status),
the compound key data-model.md Sec 8 describes and Rev 4.3 H4/H5 made
usable, and retires the single-key default scripts/14a created.

Why a separate script after 17a: the keys include the Opened/Sealed types,
which 17a creates. Why it exists at all: these four defaults were seeded onto
the live instance by hand and never captured in a script, so a from-scratch
build had only 14a's Fridge-only default, which mealplanner/inventory.py's
exact-key lookup (shelf_life_days) can never match -- every perishable then
had no expiry at all. Found by rebuilding from scratch.

Run with: python3 scripts/17b_seed_shelf_life_defaults.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.inventory import shelf_life_days
from mealplanner.seed_vocabulary import FRESH_MEAT_SHELF_LIFE, PLACEHOLDER_NOTE

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]


def dt(client, name):
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] Compound-key ShelfLife defaults for Fresh Meat...")
    fresh_meat = dt(client, "Fresh Meat")
    for storage, opened, days in FRESH_MEAT_SHELF_LIFE:
        value_id = client.upsert("QuantitySpecification", "name",
                                 f"{days:g} day shelf life for Fresh Meat in {storage} {opened} {PLACEHOLDER_NOTE}",
                                 {"value": days, "unit": "days", "status": "default"})
        spec_id = client.upsert("DefaultSpecification", "name",
                                f"Fresh Meat shelf life default -- {storage} {opened} {PLACEHOLDER_NOTE}",
                                {"forType": fresh_meat, "hasKind": dt(client, "ShelfLife"),
                                 "keyedBy": [dt(client, storage), dt(client, opened)], "hasValue": value_id})
        print(f"    {storage} + {opened}: {days:g} days ({spec_id})")

    print("\n[2] Retiring 14a's single-key default (superseded by the four above)...")
    old = client.get("/structr/rest/DefaultSpecification",
                     params={"name": f"Fresh Meat shelf life default {PLACEHOLDER_NOTE}"})["result"]
    for spec in old:
        client.delete(f"/structr/rest/DefaultSpecification/{spec['id']}")
    print(f"    removed {len(old)} (0 is fine on a re-run)")
    for orphan in client.get("/structr/rest/QuantitySpecification",
                             params={"name": f"5 day shelf life for Fresh Meat in Fridge {PLACEHOLDER_NOTE}"})["result"]:
        client.delete(f"/structr/rest/QuantitySpecification/{orphan['id']}")

    print("\n[3] Verification: the exact-key lookup the inventory engine uses...")
    all_ok = True
    for storage, opened, days in FRESH_MEAT_SHELF_LIFE:
        got = shelf_life_days(client, fresh_meat, opened, storage)
        ok = got == days
        print(f"    [{'OK' if ok else 'FAIL'}] shelf_life_days(Fresh Meat, {opened}, {storage}) = {got} (expected {days:g})")
        all_ok &= ok
    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
