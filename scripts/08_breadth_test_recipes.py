"""Breadth test, part 1: two full recipes (plan + inventory + cook),
each exercising a mechanism the chicken-breast worked example didn't
touch. See mealplanner/breadth_test.py for what and why.

Everything created here is TEST data, name-prefixed accordingly.

Run with: python3 scripts/08_breadth_test_recipes.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.breadth_test import (
    P, PASTA_YIELD, PASTA_INPUT_MASS_G, PASTA_EXPECTED_OUTPUT_G, PASTA_ACTUAL_OUTPUT_G,
    ONION_MASS_PER_UNIT, ONION_YIELD, ONION_ACTUAL_OUTPUT_G,
)

BASE_URL = os.environ.get("STRUCTR_URL", "http://localhost:8083")
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]
NOW = datetime.now(timezone.utc)
FMT = "%Y-%m-%dT%H:%M:%S+0000"


def dt(client, name: str) -> str:
    return client.get("/structr/rest/DomainType", params={"name": name})["result"][0]["id"]


def by_name(client, type_name: str, name: str) -> str:
    return client.get(f"/structr/rest/{type_name}", params={"name": name})["result"][0]["id"]


def build_default_spec(client, spec: dict, name: str) -> str:
    qty_id = client.upsert(
        "QuantitySpecification", "name", f"{name} value",
        {"value": spec["value"], "unit": "ratio" if "Yield" in spec["has_kind"] else "g", "status": "default"},
    )
    fields = {
        "forType": dt(client, f"{P}{spec['for_type']}"),
        "hasKind": dt(client, spec["has_kind"]),
        "hasValue": qty_id,
    }
    if spec.get("keyed_by"):
        fields["keyedBy"] = [dt(client, f"{P}{k}") for k in spec["keyed_by"]]
    if spec.get("target_type"):
        fields["targetType"] = dt(client, f"{P}{spec['target_type']}")
    return client.upsert("DefaultSpecification", "name", name, fields)


def resolve_default(client, type_domain_id: str, kind_name: str):
    """Call resolveDefault and return the resolved QuantitySpecification's
    FULL record (call_method's raw result only carries id/type/name for
    the nested reference -- same gotcha as script 06d hit)."""
    result = client.call_method(
        "DomainType", type_domain_id, "resolveDefault", {"kindId": dt(client, kind_name)}
    )
    if not isinstance(result, dict) or "id" not in result:
        return result
    return client.get_all("QuantitySpecification", result["id"])["result"]


def build_pasta_recipe(client):
    print("\n" + "=" * 70)
    print("RECIPE 1: Boiled Pasta -- yield > 1 (water absorption)")
    print("=" * 70)

    print("\n[1] Perishability Class member + DomainTypes...")
    food_identity_hier = client.get("/structr/rest/TypeHierarchy", params={"name": "Food Identity"})["result"][0]["id"]
    perish_hier = client.get("/structr/rest/TypeHierarchy", params={"name": "Perishability Class"})["result"][0]["id"]
    xform_hier = client.get("/structr/rest/TypeHierarchy", params={"name": "Transformation Method"})["result"][0]["id"]

    dry_goods_id = client.upsert("DomainType", "name", f"{P}Dry Goods", {"isLookupBearing": True, "hierarchy": perish_hier})
    pasta_dry = client.upsert("DomainType", "name", f"{P}Pasta (dry)", {"isLookupBearing": True, "hierarchy": food_identity_hier})
    pasta_cooked = client.upsert("DomainType", "name", f"{P}Pasta (cooked)", {"isLookupBearing": True, "hierarchy": food_identity_hier})
    boiling = client.upsert("DomainType", "name", f"{P}Boiling", {
        "isLookupBearing": True, "hierarchy": xform_hier, "parent": dt(client, "Wet-Heat Method"),
    })
    print(f"    Dry Goods={dry_goods_id}  Pasta(dry)={pasta_dry}  Pasta(cooked)={pasta_cooked}  Boiling={boiling}")

    print("\n[2] Yield DefaultSpecification (2.00 -- absorption, > 1)...")
    ds_id = build_default_spec(client, PASTA_YIELD, f"{P}Boiling yield factor for Pasta (dry)")
    resolved = resolve_default(client, pasta_dry, "Yield")
    ok = isinstance(resolved, dict) and resolved.get("value") == 2.00
    print(f"    [{'OK' if ok else 'FAIL'}] resolveDefault(Yield) on Pasta (dry) -> {resolved}")
    assert ok

    print("\n[3] Plan side: RecipeIdentity -> Plan -> Step -> 2 Specifications...")
    recipe_id = client.upsert("RecipeIdentity", "name", f"{P}Boiled Pasta", {"isRetired": False})
    yield_qty = client.upsert("QuantitySpecification", "name", f"{P}recipe yield for Boiled Pasta", {"value": 1.0, "unit": "batch", "status": "specified"})
    plan_id = client.upsert("Plan", "name", f"{P}Boiled Pasta v1", {"specializationOf": recipe_id, "hasRecipeYield": yield_qty})
    step_id = client.upsert("Step", "name", f"{P}Boil the pasta", {"plan": plan_id, "instanceOf": boiling})
    s1_qty = client.upsert("QuantitySpecification", "name", f"{P}pasta input quantity -- 454g dry", {"value": PASTA_INPUT_MASS_G, "unit": "g", "status": "specified"})
    s1_id = client.upsert("Specification", "name", f"{P}pasta S1 input dry pasta", {
        "step": step_id, "hasParticipationRole": "input", "specifies": pasta_dry,
        "hasSpecifiedQuantity": s1_qty, "isOptional": False,
    })
    s3_qty = client.upsert("QuantitySpecification", "name", f"{P}pasta output quantity -- {PASTA_EXPECTED_OUTPUT_G:.0f}g cooked default", {"value": PASTA_EXPECTED_OUTPUT_G, "unit": "g", "status": "default"})
    s3_id = client.upsert("Specification", "name", f"{P}pasta S3 output cooked pasta", {
        "step": step_id, "hasParticipationRole": "output", "specifies": pasta_cooked,
        "hasSpecifiedQuantity": s3_qty, "isOptional": False,
    })
    print(f"    recipe={recipe_id} plan={plan_id} step={step_id} s1={s1_id} s3={s3_id}")

    print("\n[4] Inventory: PortionOfSubstance dry pasta, 454g observed...")
    portion_in = client.upsert("PortionOfSubstance", "name", f"{P}Pasta portion (dry)", {
        "instanceOf": pasta_dry, "hasPerishabilityType": dry_goods_id,
    })
    mass_q = client.upsert("Quality", "name", f"{P}Pasta portion (dry) mass Quality", {"hasKind": dt(client, "Mass"), "inheresIn": portion_in})
    mass_m = client.upsert("Measurement", "name", f"{P}Pasta portion (dry) mass observation", {
        "value": PASTA_INPUT_MASS_G, "unit": "g", "status": "observed", "hasTime": NOW.strftime(FMT), "isAboutQuality": mass_q,
    })
    print(f"    portion={portion_in} mass_quality={mass_q} mass_measurement={mass_m}")

    print("\n[5] Execution: Process (Boiling), Allocations, output portion (900g actual)...")
    temporal = client.upsert("TemporalRegion", "name", f"{P}Boiling session temporal region", {
        "hasBeginning": NOW.strftime(FMT), "hasEnd": (NOW + timedelta(minutes=12)).strftime(FMT),
    })
    process_id = client.upsert("Process", "name", f"{P}Boiling session", {
        "hasKind": boiling, "concretizes": plan_id, "occupiesTemporalRegion": temporal, "hasInput": [portion_in],
    })
    a1_id = client.upsert("Allocation", "name", f"{P}pasta allocation A1 input", {
        "isAbout": portion_in, "hasParticipationRole": "input", "fulfills": s1_id,
        "hasActualQuantity": mass_m, "process": process_id,
    })
    portion_out = client.upsert("PortionOfSubstance", "name", f"{P}Pasta portion (cooked)", {
        "instanceOf": pasta_cooked, "hasPerishabilityType": dt(client, "Cooked Leftover"), "beginsToExistDuring": process_id,
    })
    out_mass_q = client.upsert("Quality", "name", f"{P}Pasta portion (cooked) mass Quality", {"hasKind": dt(client, "Mass"), "inheresIn": portion_out})
    out_mass_m = client.upsert("Measurement", "name", f"{P}Pasta portion (cooked) mass observation", {
        "value": PASTA_ACTUAL_OUTPUT_G, "unit": "g", "status": "observed",
        "hasTime": (NOW + timedelta(minutes=12)).strftime(FMT), "isAboutQuality": out_mass_q,
    })
    a3_id = client.upsert("Allocation", "name", f"{P}pasta allocation A3 output", {
        "isAbout": portion_out, "hasParticipationRole": "output", "fulfills": s3_id,
        "hasActualQuantity": out_mass_m, "generatingProcess": process_id,
    })
    print(f"    process={process_id} a1={a1_id} portion_out={portion_out} a3={a3_id}")

    unaccounted = PASTA_ACTUAL_OUTPUT_G - PASTA_EXPECTED_OUTPUT_G
    print(f"\n[6] Material accounting: expected={PASTA_EXPECTED_OUTPUT_G}g actual={PASTA_ACTUAL_OUTPUT_G}g "
          f"unaccounted={unaccounted}g (negative -- water lost to steam, the opposite sign from the chicken case)")

    a3 = client.get_all("Allocation", a3_id)["result"]
    a3_qty = client.get_all("Measurement", (a3.get("hasActualQuantity") or {}).get("id", ""))["result"]
    ok = a3_qty.get("value") == PASTA_ACTUAL_OUTPUT_G
    print(f"    [{'OK' if ok else 'FAIL'}] Allocation A3 actual quantity = {a3_qty.get('value')}g")
    assert ok
    print("\nRecipe 1 (Boiled Pasta) complete and verified.")


def build_onion_recipe(client):
    print("\n" + "=" * 70)
    print("RECIPE 2: Diced Onion -- DiscreteWholeItem, imputed measurement, "
          "trimming yield < 1")
    print("=" * 70)

    print("\n[1] Perishability + Transformation Method members, Food Identity types...")
    food_identity_hier = client.get("/structr/rest/TypeHierarchy", params={"name": "Food Identity"})["result"][0]["id"]
    perish_hier = client.get("/structr/rest/TypeHierarchy", params={"name": "Perishability Class"})["result"][0]["id"]
    xform_hier = client.get("/structr/rest/TypeHierarchy", params={"name": "Transformation Method"})["result"][0]["id"]

    produce_id = client.upsert("DomainType", "name", f"{P}Produce", {"isLookupBearing": True, "hierarchy": perish_hier})
    mechanical_method = client.upsert("DomainType", "name", f"{P}Mechanical Method", {"isLookupBearing": True, "hierarchy": xform_hier})
    peeling_dicing = client.upsert("DomainType", "name", f"{P}Peeling and Dicing", {
        "isLookupBearing": True, "hierarchy": xform_hier, "parent": mechanical_method,
    })
    yellow_onion = client.upsert("DomainType", "name", f"{P}Yellow Onion", {"isLookupBearing": True, "hierarchy": food_identity_hier})
    prepared_onion = client.upsert("DomainType", "name", f"{P}Prepared Onion", {"isLookupBearing": True, "hierarchy": food_identity_hier})
    print(f"    Produce={produce_id} MechanicalMethod={mechanical_method} PeelingDicing={peeling_dicing} "
          f"YellowOnion={yellow_onion} PreparedOnion={prepared_onion}")

    print("\n[2] MassPerUnit (180g) and Yield (0.90) DefaultSpecifications...")
    mpu_ds = build_default_spec(client, ONION_MASS_PER_UNIT, f"{P}Yellow Onion mass-per-unit default")
    yield_ds = build_default_spec(client, ONION_YIELD, f"{P}Peeling and Dicing yield factor for Yellow Onion")
    mpu_resolved = resolve_default(client, yellow_onion, "MassPerUnit")
    yield_resolved = resolve_default(client, yellow_onion, "Yield")
    ok = mpu_resolved.get("value") == 180.0 and yield_resolved.get("value") == 0.90
    print(f"    [{'OK' if ok else 'FAIL'}] resolveDefault(MassPerUnit)={mpu_resolved.get('value')}g, "
          f"resolveDefault(Yield)={yield_resolved.get('value')}")
    assert ok
    expected_output_g = mpu_resolved["value"] * yield_resolved["value"]
    print(f"    computed expected output = {mpu_resolved['value']} x {yield_resolved['value']} = {expected_output_g}g")

    print("\n[3] Plan side...")
    recipe_id = client.upsert("RecipeIdentity", "name", f"{P}Diced Onion", {"isRetired": False})
    yield_qty = client.upsert("QuantitySpecification", "name", f"{P}recipe yield for Diced Onion", {"value": 1.0, "unit": "batch", "status": "specified"})
    plan_id = client.upsert("Plan", "name", f"{P}Diced Onion v1", {"specializationOf": recipe_id, "hasRecipeYield": yield_qty})
    step_id = client.upsert("Step", "name", f"{P}Peel and dice the onion", {"plan": plan_id, "instanceOf": peeling_dicing})
    s1_id = client.upsert("Specification", "name", f"{P}onion S1 input whole onion", {
        "step": step_id, "hasParticipationRole": "input", "specifies": yellow_onion, "isOptional": False,
    })
    s3_qty = client.upsert("QuantitySpecification", "name", f"{P}onion output quantity -- {expected_output_g:.0f}g prepared default", {"value": expected_output_g, "unit": "g", "status": "default"})
    s3_id = client.upsert("Specification", "name", f"{P}onion S3 output prepared onion", {
        "step": step_id, "hasParticipationRole": "output", "specifies": prepared_onion,
        "hasSpecifiedQuantity": s3_qty, "isOptional": False,
    })
    print(f"    recipe={recipe_id} plan={plan_id} step={step_id} s1={s1_id} s3={s3_id}")

    print("\n[4] Inventory: DiscreteWholeItem onion, NEVER WEIGHED -- mass Quality gets "
          "an IMPUTED Measurement from resolveDefault(MassPerUnit)...")
    onion_instance = client.upsert("DiscreteWholeItem", "name", f"{P}Onion instance #1", {
        "instanceOf": yellow_onion, "hasPerishabilityType": produce_id,
    })
    onion_mass_q = client.upsert("Quality", "name", f"{P}Onion instance #1 mass Quality", {"hasKind": dt(client, "Mass"), "inheresIn": onion_instance})
    onion_mass_m = client.upsert("Measurement", "name", f"{P}Onion instance #1 mass -- imputed from default", {
        "value": mpu_resolved["value"], "unit": "g", "status": "imputed",
        "hasTime": NOW.strftime(FMT), "isAboutQuality": onion_mass_q,
    })
    print(f"    onion={onion_instance} mass_quality={onion_mass_q} "
          f"IMPUTED mass_measurement={onion_mass_m} ({mpu_resolved['value']}g, never actually weighed)")

    print("\n[5] Execution: Process (Peeling and Dicing), output 162g observed...")
    temporal = client.upsert("TemporalRegion", "name", f"{P}Peeling and dicing session temporal region", {
        "hasBeginning": NOW.strftime(FMT), "hasEnd": (NOW + timedelta(minutes=5)).strftime(FMT),
    })
    process_id = client.upsert("Process", "name", f"{P}Peeling and dicing session", {
        "hasKind": peeling_dicing, "concretizes": plan_id, "occupiesTemporalRegion": temporal, "hasInput": [onion_instance],
    })
    a1_id = client.upsert("Allocation", "name", f"{P}onion allocation A1 input", {
        "isAbout": onion_instance, "hasParticipationRole": "input", "fulfills": s1_id,
        "hasActualQuantity": onion_mass_m, "process": process_id,
    })
    portion_out = client.upsert("PortionOfSubstance", "name", f"{P}Prepared onion portion", {
        "instanceOf": prepared_onion, "hasPerishabilityType": produce_id, "beginsToExistDuring": process_id,
    })
    out_mass_q = client.upsert("Quality", "name", f"{P}Prepared onion portion mass Quality", {"hasKind": dt(client, "Mass"), "inheresIn": portion_out})
    out_mass_m = client.upsert("Measurement", "name", f"{P}Prepared onion portion mass observation", {
        "value": ONION_ACTUAL_OUTPUT_G, "unit": "g", "status": "observed",
        "hasTime": (NOW + timedelta(minutes=5)).strftime(FMT), "isAboutQuality": out_mass_q,
    })
    a3_id = client.upsert("Allocation", "name", f"{P}onion allocation A3 output", {
        "isAbout": portion_out, "hasParticipationRole": "output", "fulfills": s3_id,
        "hasActualQuantity": out_mass_m, "generatingProcess": process_id,
    })
    print(f"    process={process_id} a1={a1_id} portion_out={portion_out} a3={a3_id}")

    unaccounted = ONION_ACTUAL_OUTPUT_G - expected_output_g
    print(f"\n[6] Material accounting: expected={expected_output_g}g actual={ONION_ACTUAL_OUTPUT_G}g "
          f"unaccounted={unaccounted}g")
    a3 = client.get_all("Allocation", a3_id)["result"]
    a3_qty = client.get_all("Measurement", (a3.get("hasActualQuantity") or {}).get("id", ""))["result"]
    ok = a3_qty.get("value") == ONION_ACTUAL_OUTPUT_G and abs(unaccounted) < 0.01
    print(f"    [{'OK' if ok else 'FAIL'}] Allocation A3 actual = {a3_qty.get('value')}g, unaccounted ~= 0")
    assert ok

    # cross-check the imputed status held onto the input allocation's
    # quantity correctly -- the whole point of F1 (data-model.md Sec 4.1)
    a1 = client.get_all("Allocation", a1_id)["result"]
    a1_qty = client.get_all("Measurement", (a1.get("hasActualQuantity") or {}).get("id", ""))["result"]
    ok = a1_qty.get("status") == "imputed"
    print(f"    [{'OK' if ok else 'FAIL'}] Allocation A1's actual quantity is the IMPUTED measurement "
          f"(status={a1_qty.get('status')}) -- an onion that was never weighed still has a real "
          f"input allocation, per F1")
    assert ok
    print("\nRecipe 2 (Diced Onion) complete and verified.")


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()
    build_pasta_recipe(client)
    build_onion_recipe(client)
    print("\n" + "=" * 70)
    print("Both breadth-test recipes complete and verified.")


if __name__ == "__main__":
    main()
