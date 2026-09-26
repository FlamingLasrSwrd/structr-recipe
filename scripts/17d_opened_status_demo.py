"""Demonstrates the opened-status half of Fresh Meat's compound shelf-life
key (data-model.md Rev 4.3 H4): the same food, the same age, a different
container state, a different expiry. Also the fixtures the commit that
introduced ContainerObject.hasOpenedStatus described verifying, which were
built by hand on the live instance and never committed.

Three chicken portions in two trays:
  400 g, 3 days old, sealed tray   -> shelf life 5 d, so 2 days left
  400 g, 3 days old, opened tray   -> shelf life 2 d, so already expired
  250 g, just measured, opened tray-> shelf life 2 d, so 2 days left
Expected values come from the shelf-life constants and the ages above, not
from the engine. Eligibility is checked as a DIFFERENCE between filtered and
unfiltered totals, so other chicken already in stock doesn't matter.

Run with: python3 scripts/17d_opened_status_demo.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.fixtures import dt, make_container, make_portion, usable_grams_in_containers
from mealplanner.inventory import eligible_on_hand_with_urgency, instance_expiration
from mealplanner.seed_vocabulary import FRESH_MEAT_SHELF_LIFE

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
P = "TEST -- "


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    now = datetime.now(timezone.utc)
    days = {(storage, opened): d for storage, opened, d in FRESH_MEAT_SHELF_LIFE}
    failures = []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    print("[1] Two trays and three portions...")
    sealed = make_container(client, f"{P}opened-status demo -- sealed tray", opened="Sealed")
    opened = make_container(client, f"{P}opened-status demo -- opened tray", opened="Opened")
    in_sealed = make_portion(client, f"{P}opened-status demo -- chicken in sealed tray", "Chicken Breast (raw)", 400.0,
                             age_days=3, now=now, container_id=sealed)
    in_opened = make_portion(client, f"{P}opened-status demo -- chicken in opened tray", "Chicken Breast (raw)", 400.0,
                             age_days=3, now=now, container_id=opened)
    fresh_opened = make_portion(client, f"{P}fresh portion in opened container", "Chicken Breast (raw)", 250.0,
                                age_days=0, now=now, container_id=opened)

    print("\n[2] Expiry depends on the container's opened status...")
    for label, portion, age, key in (
        ("sealed tray, 3 d old", in_sealed, 3, ("Fridge", "Sealed")),
        ("opened tray, 3 d old", in_opened, 3, ("Fridge", "Opened")),
        ("opened tray, fresh", fresh_opened, 0, ("Fridge", "Opened")),
    ):
        expired, left = instance_expiration(client, client.get_all("PortionOfSubstance", portion)["result"], now)
        want = days[key] - age
        check(left is not None and abs(left - want) < 0.01 and expired == (want < 0),
              f"{label}: {days[key]:g} d shelf life - {age} d = {want:g} d left"
              f" ({'expired' if want < 0 else 'usable'}) (engine: {left})")

    print("\n[3] The opened-status filters remove exactly the usable stock in containers of that status...")
    chicken = dt(client, "Chicken Breast (raw)")
    everything, _ = eligible_on_hand_with_urgency(client, chicken, now)
    not_opened, _ = eligible_on_hand_with_urgency(client, chicken, now, eligible_when_opened=False)
    not_sealed, _ = eligible_on_hand_with_urgency(client, chicken, now, eligible_when_sealed=False)
    status = lambda wanted: (lambda c: (c.get("hasOpenedStatus") or {}).get("name") == wanted)
    in_opened = usable_grams_in_containers(client, chicken, now, status("Opened"))
    in_sealed = usable_grams_in_containers(client, chicken, now, status("Sealed"))
    check(in_opened >= 250.0 and abs((everything - not_opened) - in_opened) < 0.01,
          f"eligibleWhenOpened=False removes {everything - not_opened:g} g = the usable stock in opened containers "
          f"({in_opened:g} g, at least this demo's 250 g; its 400 g had expired anyway)")
    check(in_sealed >= 400.0 and abs((everything - not_sealed) - in_sealed) < 0.01,
          f"eligibleWhenSealed=False removes {everything - not_sealed:g} g = the usable stock in sealed containers "
          f"({in_sealed:g} g, at least this demo's 400 g)")

    if failures:
        print(f"\nFAILED ({len(failures)}).")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
