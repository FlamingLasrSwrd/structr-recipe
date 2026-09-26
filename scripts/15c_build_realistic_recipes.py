"""Three realistic, full-lifecycle recipes for the stress-test pass,
chosen to exercise mechanisms never tried before:

  A. Braised Chicken Breast -- single input (rebuilt, was deleted).
  B. Buttered Pasta with Parmesan -- THREE inputs, one output. First
     real test of "combination" material accounting (data-model.md
     Sec 5.1: "two inputs and one output is a combination") -- every
     prior recipe in this project had exactly one real ingredient.
  C. Beef and Broccoli Stir-Fry -- TWO inputs, a new protein and a new
     vegetable, exercising the same combination shape with different
     vocabulary.

All instance data (recipes, inventory, cooks) is TEST-marked. The
underlying vocabulary (Butter, Parmesan, Beef, Broccoli, Stir-Frying,
etc., seeded in 15b) is real.

Combination output quantities are directly AUTHORED (status="specified"
on the output Specification), not derived via a single yield factor --
the model has no clean mechanism for a combined yield across several
differently-transforming inputs (pasta absorbs water, cheese doesn't),
and forcing one would be inventing structure the model doesn't have.
Flagged as a finding, not silently worked around.

Run with: python3 scripts/15c_build_realistic_recipes.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.typetree import dt
from mealplanner.material_accounting import expected_combination_output

P = "TEST -- "
FMT = "%Y-%m-%dT%H:%M:%S+0000"


def concept(client, name: str) -> str:
    return client.get("/structr/rest/Concept", params={"name": name})["result"][0]["id"]


def make_quality(client, kind_name, bearer_id, name):
    return client.upsert("Quality", "name", name, {"hasKind": dt(client, kind_name), "inheresIn": bearer_id})


def make_mass_measurement(client, name, value, when, quality_id, status="observed"):
    return client.upsert("Measurement", "name", name, {
        "value": value, "unit": "g", "status": status, "hasTime": when.strftime(FMT), "isAboutQuality": quality_id,
    })


def build_recipe_plan(client, *, recipe_name, plan_name, step_name, xform_kind,
                       inputs, output_type_name, output_qty, output_status,
                       duration_min, difficulty, meal_types, servings):
    """inputs: [(food_type_name, qty_grams, spec_name), ...]

    servings: what the recipe yields, stored as unit "servings" (data-model.md
    Rev 4.3 H3). Scripts used to store an arbitrary "1.0 batch" here and the
    real counts were patched onto the live instance by hand, so a fresh build
    didn't match it.

    output_qty=None: compute the expected output from the inputs' own yield
    defaults (material_accounting.expected_combination_output, data-model.md
    Sec 5.1.1) and store it with status "default". Needs those yield defaults
    to exist already (15b seeds them). Same story: the computed 958 g / 610 g
    were patched onto the live instance by hand."""
    recipe_id = client.upsert("RecipeIdentity", "name", f"{P}{recipe_name}", {
        "isRetired": False, "hasMealType": [concept(client, mt) for mt in meal_types],
    })
    yield_qty = client.upsert("QuantitySpecification", "name", f"{P}recipe yield for {recipe_name}", {
        "value": servings, "unit": "servings", "status": "specified",
    })
    plan_id = client.upsert("Plan", "name", f"{P}{plan_name}", {
        "specializationOf": recipe_id, "hasRecipeYield": yield_qty,
        "estimatedDurationMinutes": duration_min, "difficultyRating": difficulty,
    })
    step_id = client.upsert("Step", "name", f"{P}{step_name}", {"plan": plan_id, "instanceOf": dt(client, xform_kind)})

    spec_ids = []
    for food_name, qty_g, spec_name in inputs:
        qty_id = client.upsert("QuantitySpecification", "name", f"{P}{spec_name} quantity", {
            "value": qty_g, "unit": "g", "status": "specified",
        })
        spec_id = client.upsert("Specification", "name", f"{P}{spec_name}", {
            "step": step_id, "hasParticipationRole": "input", "specifies": dt(client, food_name),
            "hasSpecifiedQuantity": qty_id, "isOptional": False,
        })
        spec_ids.append((food_name, qty_g, spec_id))

    if output_qty is None:
        output_qty = expected_combination_output(client, client.get_all("Plan", plan_id)["result"])
        output_status = "default"
    output_qty_id = client.upsert("QuantitySpecification", "name", f"{P}{recipe_name} output quantity", {
        "value": output_qty, "unit": "g", "status": output_status,
    })
    output_spec_id = client.upsert("Specification", "name", f"{P}{recipe_name} output", {
        "step": step_id, "hasParticipationRole": "output", "specifies": dt(client, output_type_name),
        "hasSpecifiedQuantity": output_qty_id, "isOptional": False,
    })

    return {"recipe_id": recipe_id, "plan_id": plan_id, "step_id": step_id,
            "input_specs": spec_ids, "output_spec_id": output_spec_id}


def cook(client, *, recipe_name, plan_id, xform_kind, input_specs, output_spec_id,
         output_type_name, perishability_name, actual_output_qty, now,
         input_observed_qtys):
    """input_specs: [(food_name, planned_qty, spec_id), ...]
    input_observed_qtys: {food_name: actual_observed_qty_on_hand}"""
    temporal = client.upsert("TemporalRegion", "name", f"{P}{recipe_name} cook temporal region", {
        "hasBeginning": now.strftime(FMT), "hasEnd": (now + timedelta(hours=1)).strftime(FMT),
    })
    input_portions = []
    for food_name, planned_qty, spec_id in input_specs:
        observed_qty = input_observed_qtys[food_name]
        portion_id = client.upsert("PortionOfSubstance", "name", f"{P}{recipe_name} input -- {food_name}", {
            "instanceOf": dt(client, food_name),
        })
        quality_id = make_quality(client, "Mass", portion_id, f"{P}{recipe_name} input {food_name} mass Quality")
        measurement_id = make_mass_measurement(
            client, f"{P}{recipe_name} input {food_name} mass observation", observed_qty, now, quality_id,
        )
        input_portions.append((food_name, portion_id, measurement_id, spec_id))

    process_id = client.upsert("Process", "name", f"{P}{recipe_name} cooking process", {
        "hasKind": dt(client, xform_kind),
        "concretizes": plan_id, "occupiesTemporalRegion": temporal,
        "hasInput": [p[1] for p in input_portions],
    })

    allocation_ids = []
    for food_name, portion_id, measurement_id, spec_id in input_portions:
        alloc_id = client.upsert("Allocation", "name", f"{P}{recipe_name} allocation input -- {food_name}", {
            "isAbout": portion_id, "hasParticipationRole": "input", "fulfills": spec_id,
            "hasActualQuantity": measurement_id, "process": process_id,
        })
        allocation_ids.append(alloc_id)

    output_portion_id = client.upsert("PortionOfSubstance", "name", f"{P}{recipe_name} output portion", {
        "instanceOf": dt(client, output_type_name), "hasPerishabilityType": dt(client, perishability_name),
        "beginsToExistDuring": process_id,
    })
    out_quality_id = make_quality(client, "Mass", output_portion_id, f"{P}{recipe_name} output mass Quality")
    out_end_time = now + timedelta(hours=1)
    out_measurement_id = make_mass_measurement(
        client, f"{P}{recipe_name} output mass observation", actual_output_qty, out_end_time, out_quality_id,
    )
    output_alloc_id = client.upsert("Allocation", "name", f"{P}{recipe_name} allocation output", {
        "isAbout": output_portion_id, "hasParticipationRole": "output", "fulfills": output_spec_id,
        "hasActualQuantity": out_measurement_id, "generatingProcess": process_id,
    })

    return {"process_id": process_id, "output_portion_id": output_portion_id,
            "output_measurement_id": out_measurement_id, "allocation_ids": allocation_ids + [output_alloc_id]}


def main():
    client = connect()
    client.wait_until_ready()
    now = datetime.now(timezone.utc)

    print("=" * 70)
    print("RECIPE A: Braised Chicken Breast (single input)")
    print("=" * 70)
    a = build_recipe_plan(
        client, recipe_name="Braised Chicken Breast", plan_name="Braised Chicken Breast v1",
        step_name="Braise the chicken breast", xform_kind="Braising",
        inputs=[("Chicken Breast (raw)", 500.0, "chicken S1 input")],
        output_type_name="Chicken Breast (braised)", output_qty=375.0, output_status="default",
        duration_min=140.0, difficulty="medium", meal_types=["Dinner"], servings=2.0,
    )
    a_cook = cook(
        client, recipe_name="Braised Chicken Breast", plan_id=a["plan_id"], xform_kind="Braising",
        input_specs=a["input_specs"], output_spec_id=a["output_spec_id"],
        output_type_name="Chicken Breast (braised)", perishability_name="Cooked Leftover",
        actual_output_qty=383.0, now=now, input_observed_qtys={"Chicken Breast (raw)": 510.0},
    )
    print(f"  recipe={a['recipe_id']} process={a_cook['process_id']} output={a_cook['output_portion_id']}")

    print("\n" + "=" * 70)
    print("RECIPE B: Buttered Pasta with Parmesan (THREE inputs -- combination)")
    print("=" * 70)
    b = build_recipe_plan(
        client, recipe_name="Buttered Pasta with Parmesan", plan_name="Buttered Pasta with Parmesan v1",
        step_name="Boil pasta and toss with butter and parmesan", xform_kind="Boiling",
        inputs=[
            ("Pasta (dry)", 454.0, "pasta S1 input dry pasta"),
            ("Butter", 30.0, "pasta S2 input butter"),
            ("Parmesan", 20.0, "pasta S3 input parmesan"),
        ],
        output_type_name="Buttered Pasta with Parmesan", output_qty=None, output_status="default",
        duration_min=20.0, difficulty="easy", meal_types=["Dinner", "Lunch"], servings=4.0,
    )
    b_cook = cook(
        client, recipe_name="Buttered Pasta with Parmesan", plan_id=b["plan_id"], xform_kind="Boiling",
        input_specs=b["input_specs"], output_spec_id=b["output_spec_id"],
        output_type_name="Buttered Pasta with Parmesan", perishability_name="Cooked Leftover",
        actual_output_qty=940.0, now=now,
        input_observed_qtys={"Pasta (dry)": 454.0, "Butter": 32.0, "Parmesan": 22.0},
    )
    print(f"  recipe={b['recipe_id']} process={b_cook['process_id']} output={b_cook['output_portion_id']}")

    print("\n" + "=" * 70)
    print("RECIPE C: Beef and Broccoli Stir-Fry (TWO inputs -- new protein + vegetable)")
    print("=" * 70)
    c = build_recipe_plan(
        client, recipe_name="Beef and Broccoli Stir-Fry", plan_name="Beef and Broccoli Stir-Fry v1",
        step_name="Stir-fry the beef and broccoli", xform_kind="Stir-Frying",
        inputs=[
            ("Beef (raw)", 400.0, "stirfry S1 input beef"),
            ("Broccoli", 300.0, "stirfry S2 input broccoli"),
        ],
        output_type_name="Beef and Broccoli Stir-Fry", output_qty=None, output_status="default",
        duration_min=25.0, difficulty="medium", meal_types=["Dinner"], servings=2.0,
    )
    c_cook = cook(
        client, recipe_name="Beef and Broccoli Stir-Fry", plan_id=c["plan_id"], xform_kind="Stir-Frying",
        input_specs=c["input_specs"], output_spec_id=c["output_spec_id"],
        output_type_name="Beef and Broccoli Stir-Fry", perishability_name="Cooked Leftover",
        actual_output_qty=610.0, now=now,
        input_observed_qtys={"Beef (raw)": 420.0, "Broccoli": 310.0},
    )
    print(f"  recipe={c['recipe_id']} process={c_cook['process_id']} output={c_cook['output_portion_id']}")

    print("\n" + "=" * 70)
    print("Verification...")
    all_ok = True
    for label, cook_result, expected_inputs in [
        ("A", a_cook, 1), ("B", b_cook, 3), ("C", c_cook, 2),
    ]:
        process = client.get_all("Process", cook_result["process_id"])["result"]
        ok = len(process.get("hasInput", [])) == expected_inputs
        print(f"    [{'OK' if ok else 'FAIL'}] Recipe {label}: Process has {len(process.get('hasInput', []))} "
              f"input(s), expected {expected_inputs}")
        all_ok &= ok

    if not all_ok:
        print("\nFAILED.")
        sys.exit(1)
    print("\nAll checks passed. Three realistic recipes built end to end.")


if __name__ == "__main__":
    main()
