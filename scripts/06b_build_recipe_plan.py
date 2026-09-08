"""Build order step 6, part B: the plan side.

RecipeIdentity -> Plan -> Step -> 3 Specifications, matching
data-model.md Sec 10's worked example exactly (S1 input, S2 instrument,
S3 output).

Plan.hasRecipeYield has no number given in the worked example -- set to
a placeholder (1 batch), flagged the same way the yield factor was.

Run with: python3 scripts/06b_build_recipe_plan.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
PLACEHOLDER_NOTE = "[PLACEHOLDER -- not sourced from USDA/FDC yet]"


def dt(client, name: str) -> str:
    """Look up a DomainType id by name."""
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    print("[1] RecipeIdentity...")
    recipe_id = client.upsert(
        "RecipeIdentity", "name", "Braised Chicken Breast", {"isRetired": False}
    )
    print(f"    {recipe_id}")

    print("\n[2] Plan (recipe yield is a placeholder -- worked example gives no number)...")
    yield_qty = client.upsert(
        "QuantitySpecification", "name",
        f"recipe yield for Braised Chicken Breast {PLACEHOLDER_NOTE}",
        {"value": 1.0, "unit": "batch", "status": "specified"},
    )
    plan_id = client.upsert(
        "Plan", "name", "Braised Chicken Breast v1",
        {"specializationOf": recipe_id, "hasRecipeYield": yield_qty},
    )
    print(f"    yield qty: {yield_qty}")
    print(f"    plan:      {plan_id}")

    print("\n[3] Step (instance_of Braising)...")
    step_id = client.upsert(
        "Step", "name", "Braise the chicken breast",
        {"plan": plan_id, "instanceOf": dt(client, "Braising")},
    )
    print(f"    {step_id}")

    print("\n[4] Specification S1 -- input: 500g raw chicken breast (specified)...")
    s1_qty = client.upsert(
        "QuantitySpecification", "name", "S1 input quantity -- 500g raw chicken breast",
        {"value": 500.0, "unit": "g", "status": "specified"},
    )
    s1_id = client.upsert(
        "Specification", "name", "S1 -- input raw chicken breast",
        {
            "step": step_id,
            "hasParticipationRole": "input",
            "specifies": dt(client, "Chicken Breast (raw)"),
            "hasSpecifiedQuantity": s1_qty,
            "isOptional": False,
        },
    )
    print(f"    qty: {s1_qty}, spec: {s1_id}")

    print("\n[5] Specification S2 -- instrument: Heating capability, requires clean...")
    s2_id = client.upsert(
        "Specification", "name", "S2 -- instrument -- heating capability",
        {
            "step": step_id,
            "hasParticipationRole": "instrument",
            "specifies": dt(client, "Heating"),
            "isOptional": False,
        },
    )
    state_req_id = client.upsert(
        "StateRequirement", "name", "S2 state requirement -- cleanliness must be clean",
        {
            "specification": s2_id,
            "targetsProperty": dt(client, "Cleanliness"),
            "expectedValueLiteral": "clean",
        },
    )
    print(f"    spec: {s2_id}, state requirement: {state_req_id}")

    print("\n[6] Specification S3 -- output: 375g braised chicken breast (default, "
          "500g x 0.75 yield)...")
    s3_qty = client.upsert(
        "QuantitySpecification", "name",
        "S3 output quantity -- 375g braised chicken breast",
        {"value": 375.0, "unit": "g", "status": "default"},
    )
    s3_id = client.upsert(
        "Specification", "name", "S3 -- output braised chicken breast",
        {
            "step": step_id,
            "hasParticipationRole": "output",
            "specifies": dt(client, "Chicken Breast (braised)"),
            "hasSpecifiedQuantity": s3_qty,
            "isOptional": False,
        },
    )
    print(f"    qty: {s3_qty}, spec: {s3_id}")

    print("\n[7] Verification -- read the whole plan back from RecipeIdentity down...")
    all_ok = True

    plan = client.get_all("Plan", plan_id)["result"]
    ok = (plan.get("specializationOf") or {}).get("id") == recipe_id
    print(f"    [{'OK' if ok else 'FAIL'}] Plan.specializationOf -> RecipeIdentity")
    all_ok &= ok

    step = client.get_all("Step", step_id)["result"]
    ok = (step.get("plan") or {}).get("id") == plan_id
    ok &= (step.get("instanceOf") or {}).get("name") == "Braising"
    step_specs = {s["id"] for s in step.get("hasSpecification", [])}
    ok &= step_specs == {s1_id, s2_id, s3_id}
    print(f"    [{'OK' if ok else 'FAIL'}] Step.plan correct, instanceOf=Braising, "
          f"has all 3 Specifications ({len(step_specs)}/3)")
    all_ok &= ok

    s1 = client.get_all("Specification", s1_id)["result"]
    ok = (
        s1.get("hasParticipationRole") == "input"
        and (s1.get("specifies") or {}).get("name") == "Chicken Breast (raw)"
        and (s1.get("hasSpecifiedQuantity") or {}).get("id") == s1_qty
    )
    print(f"    [{'OK' if ok else 'FAIL'}] S1: input, specifies Chicken Breast (raw), 500g")
    all_ok &= ok

    s2 = client.get_all("Specification", s2_id)["result"]
    s2_reqs = s2.get("hasStateRequirement", [])
    ok = (
        s2.get("hasParticipationRole") == "instrument"
        and (s2.get("specifies") or {}).get("name") == "Heating"
        and len(s2_reqs) == 1 and s2_reqs[0]["id"] == state_req_id
    )
    print(f"    [{'OK' if ok else 'FAIL'}] S2: instrument, specifies Heating, "
          f"has 1 StateRequirement")
    all_ok &= ok

    sr = client.get_all("StateRequirement", state_req_id)["result"]
    ok = (sr.get("targetsProperty") or {}).get("name") == "Cleanliness" and sr.get("expectedValueLiteral") == "clean"
    print(f"    [{'OK' if ok else 'FAIL'}] StateRequirement: targets Cleanliness, expects 'clean'")
    all_ok &= ok

    s3 = client.get_all("Specification", s3_id)["result"]
    ok = (
        s3.get("hasParticipationRole") == "output"
        and (s3.get("specifies") or {}).get("name") == "Chicken Breast (braised)"
        and (s3.get("hasSpecifiedQuantity") or {}).get("id") == s3_qty
    )
    print(f"    [{'OK' if ok else 'FAIL'}] S3: output, specifies Chicken Breast (braised), 375g")
    all_ok &= ok

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)

    print("\nAll checks passed. Plan side built and verified end to end.")
    print(f"\nIDs: recipe={recipe_id} plan={plan_id} step={step_id} s1={s1_id} s2={s2_id} s3={s3_id}")


if __name__ == "__main__":
    main()
