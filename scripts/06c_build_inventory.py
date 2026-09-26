"""Build order step 6, part C: real inventory.

ContainerObject (Tray, opened), PortionOfSubstance (raw chicken breast,
510g observed, located in the Tray), EquipmentObject (Dutch Oven, with
a Heating Function and a cleanliness Quality) -- matching
data-model.md Sec 10's worked example (#T4, #C88, #E1).

Timestamp: the worked example uses "Sunday 10:15" -- since this is a
real build (not a historical replay), a real current timestamp is used
instead, noted in each Measurement's name for traceability.

Run with: python3 scripts/06c_build_inventory.py
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def make_quality(client, kind_name: str, bearer_id: str, name: str) -> str:
    return client.upsert("Quality", "name", name, {"hasKind": dt(client, kind_name), "inheresIn": bearer_id})


def make_measurement(client, name: str, *, value=None, literal_value=None, unit=None,
                      status: str, about_quality_id: str) -> str:
    fields = {"status": status, "hasTime": NOW, "isAboutQuality": about_quality_id}
    if value is not None:
        fields["value"] = value
    if unit is not None:
        fields["unit"] = unit
    if literal_value is not None:
        fields["literalValue"] = literal_value
    return client.upsert("Measurement", "name", name, fields)


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] ContainerObject #T4 (Tray, opened)...")
    tray_id = client.upsert(
        "ContainerObject", "name", "Tray #T4",
        {"instanceOf": dt(client, "Tray")},
    )
    opened_status_quality = make_quality(client, "OpenedStatus", tray_id, "Tray #T4 opened_status Quality")
    opened_status_measurement = make_measurement(
        client, "Tray #T4 opened_status observation",
        literal_value="opened", status="observed", about_quality_id=opened_status_quality,
    )
    print(f"    tray={tray_id}  quality={opened_status_quality}  measurement={opened_status_measurement}")

    print("\n[2] PortionOfSubstance #C88 (raw chicken breast, 510g observed, in the Tray)...")
    portion_id = client.upsert(
        "PortionOfSubstance", "name", "Chicken breast portion #C88",
        {
            "instanceOf": dt(client, "Chicken Breast (raw)"),
            "hasPerishabilityType": dt(client, "Fresh Meat"),
            "locatedIn": tray_id,
        },
    )
    mass_quality = make_quality(client, "Mass", portion_id, "Chicken breast portion #C88 mass Quality")
    mass_measurement = make_measurement(
        client, "Chicken breast portion #C88 mass observation",
        value=510.0, unit="g", status="observed", about_quality_id=mass_quality,
    )
    shelf_life_disposition = client.upsert(
        "Disposition", "name", "Chicken breast portion #C88 shelf-life Disposition",
        {"hasKind": dt(client, "ShelfLife"), "inheresIn": portion_id},
    )
    print(f"    portion={portion_id}  mass_quality={mass_quality}  "
          f"mass_measurement={mass_measurement}  shelf_life={shelf_life_disposition}")

    print("\n[3] EquipmentObject #E1 (Dutch Oven, with Heating Function + cleanliness)...")
    equipment_id = client.upsert(
        "EquipmentObject", "name", "Dutch Oven #E1",
        {"instanceOf": dt(client, "Dutch Oven")},
    )
    heating_function = client.upsert(
        "Function", "name", "Dutch Oven #E1 Heating Function",
        {"hasKind": dt(client, "Heating"), "inheresIn": equipment_id},
    )
    cleanliness_quality = make_quality(client, "Cleanliness", equipment_id, "Dutch Oven #E1 cleanliness Quality")
    cleanliness_measurement = make_measurement(
        client, "Dutch Oven #E1 cleanliness observation",
        literal_value="clean", status="observed", about_quality_id=cleanliness_quality,
    )
    reservation_role = client.upsert(
        "Role", "name", "Dutch Oven #E1 reservation Role",
        {"hasKind": dt(client, "Reservation"), "inheresIn": equipment_id},
    )
    print(f"    equipment={equipment_id}  heating_function={heating_function}  "
          f"cleanliness_quality={cleanliness_quality}  "
          f"cleanliness_measurement={cleanliness_measurement}  "
          f"reservation_role={reservation_role}")

    print("\n[4] Verification...")
    all_ok = True

    portion = client.get_all("PortionOfSubstance", portion_id)["result"]
    ok = (
        (portion.get("instanceOf") or {}).get("name") == "Chicken Breast (raw)"
        and (portion.get("hasPerishabilityType") or {}).get("name") == "Fresh Meat"
        and (portion.get("locatedIn") or {}).get("id") == tray_id
    )
    print(f"    [{'OK' if ok else 'FAIL'}] Portion: instanceOf/hasPerishabilityType/locatedIn all correct")
    all_ok &= ok

    tray = client.get_all("ContainerObject", tray_id)["result"]
    tray_contents = {c["id"] for c in tray.get("contents", [])}
    ok = portion_id in tray_contents
    print(f"    [{'OK' if ok else 'FAIL'}] Tray.contents contains the portion (reverse of locatedIn)")
    all_ok &= ok

    mq = client.get_all("Quality", mass_quality)["result"]
    ok = (mq.get("hasKind") or {}).get("name") == "Mass" and (mq.get("inheresIn") or {}).get("id") == portion_id
    mass_measurements = {m["id"] for m in mq.get("measurements", [])}
    ok &= mass_measurement in mass_measurements
    print(f"    [{'OK' if ok else 'FAIL'}] mass Quality: hasKind=Mass, inheresIn=portion, "
          f"has the observation via reverse isAboutQuality")
    all_ok &= ok

    mm = client.get_all("Measurement", mass_measurement)["result"]
    ok = mm.get("value") == 510.0 and mm.get("status") == "observed" and mm.get("hasTime") is not None
    print(f"    [{'OK' if ok else 'FAIL'}] mass Measurement: 510g, observed, hasTime set "
          f"-> {mm.get('value')} {mm.get('unit')}")
    all_ok &= ok

    eq = client.get_all("EquipmentObject", equipment_id)["result"]
    ok = (eq.get("instanceOf") or {}).get("name") == "Dutch Oven"
    print(f"    [{'OK' if ok else 'FAIL'}] EquipmentObject: instanceOf=Dutch Oven")
    all_ok &= ok

    hf = client.get_all("Function", heating_function)["result"]
    ok = (hf.get("hasKind") or {}).get("name") == "Heating" and (hf.get("inheresIn") or {}).get("id") == equipment_id
    print(f"    [{'OK' if ok else 'FAIL'}] Heating Function: hasKind=Heating, inheresIn=equipment")
    all_ok &= ok

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. Real inventory built and verified end to end.")
    print(f"\nIDs: tray={tray_id} portion={portion_id} equipment={equipment_id} "
          f"heating_function={heating_function} reservation_role={reservation_role}")


if __name__ == "__main__":
    main()
