"""Seeds a ShelfLife DefaultSpecification (Fresh Meat, keyed by Fridge
only -- see module docstring in mealplanner/inventory.py for why the
opened-status half of the compound key isn't implemented) and one new
raw chicken breast portion, observed 4 days ago against a 5-day shelf
life -- on hand, not yet expired, but close, to make stock-awareness
and waste scoring demonstrable rather than uniformly zero.

Run with: python3 scripts/14a_seed_shelf_life_and_stock.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
PLACEHOLDER_NOTE = "[PLACEHOLDER -- not sourced from USDA/FDC yet]"
FMT = "%Y-%m-%dT%H:%M:%S+0000"


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    now = datetime.now(timezone.utc)

    print("[1] ShelfLife default: Fresh Meat, keyed by Fridge, 5 days...")
    shelf_life_qty = client.upsert(
        "QuantitySpecification", "name", f"5 day shelf life for Fresh Meat in Fridge {PLACEHOLDER_NOTE}",
        {"value": 5.0, "unit": "days", "status": "default"},
    )
    shelf_life_ds = client.upsert(
        "DefaultSpecification", "name", f"Fresh Meat shelf life default {PLACEHOLDER_NOTE}",
        {
            "forType": dt(client, "Fresh Meat"), "hasKind": dt(client, "ShelfLife"),
            "keyedBy": [dt(client, "Fridge")], "hasValue": shelf_life_qty,
        },
    )
    print(f"    qty={shelf_life_qty} default_spec={shelf_life_ds}")

    print("\n[2] New raw chicken breast portion, 600g, observed 4 days ago "
          "(1 day left on a 5-day shelf life)...")
    observed_time = now - timedelta(days=4)
    portion_id = client.upsert(
        "PortionOfSubstance", "name", "TEST -- Chicken breast portion #C99 (on-hand -- near expiry)",
        {"instanceOf": dt(client, "Chicken Breast (raw)"), "hasPerishabilityType": dt(client, "Fresh Meat")},
    )
    mass_quality = client.upsert(
        "Quality", "name", "TEST -- Chicken breast portion #C99 mass Quality",
        {"hasKind": dt(client, "Mass"), "inheresIn": portion_id},
    )
    mass_measurement = client.upsert(
        "Measurement", "name", "TEST -- Chicken breast portion #C99 mass observation",
        {"value": 600.0, "unit": "g", "status": "observed", "hasTime": observed_time.strftime(FMT), "isAboutQuality": mass_quality},
    )
    print(f"    portion={portion_id} quality={mass_quality} measurement={mass_measurement}")

    print("\n[3] Verification: resolveDefault(ShelfLife) on Fresh Meat...")
    resolved = client.call_method("DomainType", dt(client, "Fresh Meat"), "resolveDefault", {"kindId": dt(client, "ShelfLife")})
    resolved_full = client.get_all("QuantitySpecification", resolved["id"])["result"] if isinstance(resolved, dict) else None
    ok = resolved_full and resolved_full.get("value") == 5.0
    print(f"    [{'OK' if ok else 'FAIL'}] resolveDefault(ShelfLife) -> {resolved_full}")

    if not ok:
        print("\nFAILED.")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
