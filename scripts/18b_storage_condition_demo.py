"""Demonstrates the storage-condition half of Fresh Meat's compound shelf-life
key (data-model.md Rev 4.3 H5): frozen stock 30 days old is far inside a
180-day freezer shelf life, but would be long expired if it were treated as
fridge stock. Also the fixture the commit that introduced
ContainerObject.hasStorageCondition described, built by hand on the live
instance and never committed.

Expected values come from the shelf-life constants and the age, not the
engine. Eligibility is a DIFFERENCE between filtered and unfiltered totals.

Run with: python3 scripts/18b_storage_condition_demo.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.fixtures import dt, make_container, make_portion, usable_grams_in_containers
from mealplanner.inventory import eligible_on_hand_with_urgency, instance_expiration
from mealplanner.seed_vocabulary import FRESH_MEAT_SHELF_LIFE

P = "TEST -- "
AGE_DAYS = 30


def main():
    client = connect()
    client.wait_until_ready()
    now = datetime.now(timezone.utc)
    days = {(storage, opened): d for storage, opened, d in FRESH_MEAT_SHELF_LIFE}
    failures = []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    print("[1] A sealed freezer tray holding 500 g of chicken measured 30 days ago...")
    tray = make_container(client, f"{P}storage-condition demo -- freezer tray", opened="Sealed", storage="Freezer")
    frozen = make_portion(client, f"{P}frozen chicken -- 30 days old", "Chicken Breast (raw)", 500.0,
                          age_days=AGE_DAYS, now=now, container_id=tray)

    print("\n[2] Expiry uses the freezer shelf life, not the fridge one...")
    expired, left = instance_expiration(client, client.get_all("PortionOfSubstance", frozen)["result"], now)
    want = days[("Freezer", "Sealed")] - AGE_DAYS
    check(left is not None and abs(left - want) < 0.01 and not expired,
          f"{days[('Freezer', 'Sealed')]:g} d freezer shelf life - {AGE_DAYS} d = {want:g} d left, usable (engine: {left})")
    as_fridge = days[("Fridge", "Sealed")] - AGE_DAYS
    check(as_fridge < 0, f"the same portion treated as fridge stock would be {-as_fridge:g} days expired ({days[('Fridge', 'Sealed')]:g} d - {AGE_DAYS} d)")

    print("\n[3] A Fridge-only storage filter removes the usable stock in non-fridge containers...")
    chicken = dt(client, "Chicken Breast (raw)")
    everything, _ = eligible_on_hand_with_urgency(client, chicken, now)
    fridge_only, _ = eligible_on_hand_with_urgency(client, chicken, now, eligible_storage_condition_names={"Fridge"})
    elsewhere = usable_grams_in_containers(
        client, chicken, now, lambda c: (c.get("hasStorageCondition") or {}).get("name") not in (None, "Fridge"))
    check(elsewhere >= 500.0 and abs((everything - fridge_only) - elsewhere) < 0.01,
          f"eligibleStorageConditions={{Fridge}} removes {everything - fridge_only:g} g = the usable stock stored "
          f"somewhere other than the fridge ({elsewhere:g} g, at least this demo's 500 g)")

    if failures:
        print(f"\nFAILED ({len(failures)}).")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
