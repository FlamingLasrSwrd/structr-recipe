"""Build order step 6, part D: the first real cook (execution).

Process P1 (Braising), Allocations A1 (input) + A3 (output), and the
resulting output PortionOfSubstance #C91 with its derived NutrientContent
-- matching data-model.md Sec 10's EXECUTION block.

Material accounting sanity check (Sec 5.1): expected output = actual
input x yield factor = 510 x 0.75 = 382.5 =~ 383g, matching the worked
example's own numbers exactly (unaccounted = 0).

Run with: python3 scripts/06d_execute_cook.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]

START = datetime.now(timezone.utc)
END = START + timedelta(hours=2)
FMT = "%Y-%m-%dT%H:%M:%S+0000"


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def by_name(client, type_name: str, name: str) -> str:
    return client.get(f"/structr/rest/{type_name}", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    # Look up everything built in prior phases, by name -- keeps this
    # script independently re-runnable rather than depending on
    # hardcoded ids from an earlier run's console output.
    plan_id = by_name(client, "Plan", "Braised Chicken Breast v1")
    step_id = by_name(client, "Step", "Braise the chicken breast")
    s1_id = by_name(client, "Specification", "S1 -- input raw chicken breast")
    s3_id = by_name(client, "Specification", "S3 -- output braised chicken breast")
    portion_in_id = by_name(client, "PortionOfSubstance", "Chicken breast portion #C88")
    input_mass_measurement = by_name(client, "Measurement", "Chicken breast portion #C88 mass observation")
    equipment_id = by_name(client, "EquipmentObject", "Dutch Oven #E1")
    reservation_role_id = by_name(client, "Role", "Dutch Oven #E1 reservation Role")

    print("[1] TemporalRegion for the cook (2-hour window, starting now)...")
    temporal_region_id = client.upsert(
        "TemporalRegion", "name", "Braising session temporal region",
        {"hasBeginning": START.strftime(FMT), "hasEnd": END.strftime(FMT)},
    )
    print(f"    {temporal_region_id}")

    print("\n[2] Process P1 (instance_of Braising, concretizes the Plan)...")
    process_id = client.upsert(
        "Process", "name", "Braising session P1",
        {
            "hasKind": dt(client, "Braising"),
            "concretizes": plan_id,
            "occupiesTemporalRegion": temporal_region_id,
            "hasInput": [portion_in_id],
            "hasParticipant": [equipment_id],
            "realizes": [reservation_role_id],
        },
    )
    print(f"    {process_id}")

    print("\n[3] Allocation A1 (input, fulfills S1, reuses the 510g observed mass "
          "measurement -- same physical fact, both roles)...")
    a1_id = client.upsert(
        "Allocation", "name", "Allocation A1 -- input -- chicken breast portion #C88",
        {
            "isAbout": portion_in_id,
            "hasParticipationRole": "input",
            "fulfills": s1_id,
            "hasActualQuantity": input_mass_measurement,
            "process": process_id,  # reverse of QUALIFIED_USAGE
        },
    )
    print(f"    {a1_id}")

    print("\n[4] Output PortionOfSubstance #C91 (braised chicken breast, "
          "begins to exist during P1)...")
    portion_out_id = client.upsert(
        "PortionOfSubstance", "name", "Chicken breast portion #C91 (braised)",
        {
            "instanceOf": dt(client, "Chicken Breast (braised)"),
            "hasPerishabilityType": dt(client, "Cooked Leftover"),
            "beginsToExistDuring": process_id,
        },
    )
    print(f"    {portion_out_id}")

    print("\n[5] Output mass: 383g observed (510g x 0.75 yield =~ 382.5, "
          "matching the worked example's own rounding)...")
    output_mass_quality = client.upsert(
        "Quality", "name", "Chicken breast portion #C91 mass Quality",
        {"hasKind": dt(client, "Mass"), "inheresIn": portion_out_id},
    )
    output_mass_measurement = client.upsert(
        "Measurement", "name", "Chicken breast portion #C91 mass observation",
        {
            "value": 383.0, "unit": "g", "status": "observed",
            "hasTime": END.strftime(FMT), "isAboutQuality": output_mass_quality,
        },
    )
    print(f"    quality={output_mass_quality}  measurement={output_mass_measurement}")

    print("\n[6] Allocation A3 (output, fulfills S3)...")
    a3_id = client.upsert(
        "Allocation", "name", "Allocation A3 -- output -- chicken breast portion #C91",
        {
            "isAbout": portion_out_id,
            "hasParticipationRole": "output",
            "fulfills": s3_id,
            "hasActualQuantity": output_mass_measurement,
            "generatingProcess": process_id,  # reverse of QUALIFIED_GENERATION
        },
    )
    print(f"    {a3_id}")

    print("\n[7] Derived NutrientContent (protein) on the output -- invariant 29: "
          "a cooking output's NutrientContent is always derived...")
    protein_quality = client.upsert(
        "Quality", "name", "Chicken breast portion #C91 NutrientContent:Protein",
        {"hasKind": dt(client, "Protein"), "inheresIn": portion_out_id},
    )
    protein_measurement = client.upsert(
        "Measurement", "name", "Chicken breast portion #C91 protein content (derived)",
        {
            "value": 84.0, "unit": "g", "status": "derived",
            "hasTime": END.strftime(FMT), "isAboutQuality": protein_quality,
        },
    )
    print(f"    quality={protein_quality}  measurement={protein_measurement}")

    print("\n[8] Verification...")
    all_ok = True

    process = client.get_all("Process", process_id)["result"]
    ok = (
        (process.get("hasKind") or {}).get("name") == "Braising"
        and (process.get("concretizes") or {}).get("id") == plan_id
        and {e["id"] for e in process.get("hasInput", [])} == {portion_in_id}
        and {e["id"] for e in process.get("hasParticipant", [])} == {equipment_id}
        and {e["id"] for e in process.get("realizes", [])} == {reservation_role_id}
    )
    print(f"    [{'OK' if ok else 'FAIL'}] Process: hasKind/concretizes/hasInput/hasParticipant/realizes all correct")
    all_ok &= ok

    # Nested relationship objects only carry id/type/name, not the
    # related node's own properties -- re-fetch to check `value`.
    a1 = client.get_all("Allocation", a1_id)["result"]
    a1_qty = client.get_all("Measurement", (a1.get("hasActualQuantity") or {}).get("id", ""))["result"]
    ok = (
        (a1.get("isAbout") or {}).get("id") == portion_in_id
        and a1.get("hasParticipationRole") == "input"
        and (a1.get("fulfills") or {}).get("id") == s1_id
        and a1_qty.get("value") == 510.0
    )
    print(f"    [{'OK' if ok else 'FAIL'}] Allocation A1: isAbout/role/fulfills/actualQuantity(510g) correct")
    all_ok &= ok

    a3 = client.get_all("Allocation", a3_id)["result"]
    a3_qty = client.get_all("Measurement", (a3.get("hasActualQuantity") or {}).get("id", ""))["result"]
    ok = (
        (a3.get("isAbout") or {}).get("id") == portion_out_id
        and a3.get("hasParticipationRole") == "output"
        and (a3.get("fulfills") or {}).get("id") == s3_id
        and a3_qty.get("value") == 383.0
    )
    print(f"    [{'OK' if ok else 'FAIL'}] Allocation A3: isAbout/role/fulfills/actualQuantity(383g) correct")
    all_ok &= ok

    portion_out = client.get_all("PortionOfSubstance", portion_out_id)["result"]
    ok = (
        (portion_out.get("instanceOf") or {}).get("name") == "Chicken Breast (braised)"
        and (portion_out.get("hasPerishabilityType") or {}).get("name") == "Cooked Leftover"
        and (portion_out.get("beginsToExistDuring") or {}).get("id") == process_id
    )
    print(f"    [{'OK' if ok else 'FAIL'}] Output portion: instanceOf/hasPerishabilityType/beginsToExistDuring correct")
    all_ok &= ok

    protein_q = client.get_all("Quality", protein_quality)["result"]
    protein_meas_ids = {m["id"] for m in protein_q.get("measurements", [])}
    ok = (
        (protein_q.get("hasKind") or {}).get("name") == "Protein"
        and protein_measurement in protein_meas_ids
    )
    pm = client.get_all("Measurement", protein_measurement)["result"]
    ok &= pm.get("value") == 84.0 and pm.get("status") == "derived"
    print(f"    [{'OK' if ok else 'FAIL'}] NutrientContent: Protein Quality on output, "
          f"84g derived Measurement")
    all_ok &= ok

    print("\n[9] Material accounting sanity check (Sec 5.1, informational only, "
          "never a validity condition per invariant 14a)...")
    actual_input = 510.0
    yield_factor = 0.75
    expected_output = actual_input * yield_factor
    actual_output = 383.0
    unaccounted = actual_output - expected_output
    print(f"    expected = {actual_input} x {yield_factor} = {expected_output}g")
    print(f"    actual   = {actual_output}g")
    print(f"    unaccounted = {unaccounted}g  (matches the worked example's own 0.5g rounding)")

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. First real recipe, inventory, and cook: complete end to end.")
    print(f"\nIDs: process={process_id} a1={a1_id} a3={a3_id} portion_out={portion_out_id}")


if __name__ == "__main__":
    main()
