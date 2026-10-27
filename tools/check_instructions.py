"""Check that the recipe page writes a recipe's instructions word for word as Python does
(pages/lib/75_instructions.js, mealplanner/instructions.py; data-model.md J35).

    python3 tools/check_instructions.py [--count 400]

Generates steps with every kind of fact (methods the verb list knows and does not, labels, amounts,
units, optional and "to taste" ingredients, what earlier steps made, tools with a temperature or a heat
level or none, working and waiting minutes, the steps before, doneness in words and inside), sends them
to the writeInstructions method, and compares each sentence with mealplanner/instructions.py's. It reads
nothing of the instance, so it may be run on any. tools/check_pages.py compares each recipe page's
instructions, read from the graph, with Python's for the same Plan. Exits 1 on any difference.
Needs STRUCTR_SUPERUSER_PASSWORD and STRUCTR_URL, and the methods installed (tools/install_methods.py).
"""

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.instructions import VERBS, as_data, instructions
from mealplanner.recipe_import import HEAT_LEVELS, Heat, Ingredient, StepDoc

FOODS = ["Rice", "Chicken Breast (raw)", "Garlic", "Jalapeño", "Olive Oil", "Salt", "Crème Fraîche", "Black Pepper"]
TOOLS = ["Oven", "Skillet", "Saucepan", "Wok", "Tongs", "Sheet Pan"]
UNITS = ["g", "kg", "tbsp", "tsp", "cup", "each", "whole", "oz", "pinch"]
NUMBERS = [1, 2, 0.5, 0.125, 0.0625, 1 / 3, 2.5, 283.9056, 400, 1.75, 12, 0.333]


def random_steps(rng: random.Random) -> list[StepDoc]:
    steps = []
    for i in range(1, rng.randint(1, 5) + 1):
        made = [s.makes for s in steps]
        inputs = []
        for _ in range(rng.randint(1, 4)):
            if made and rng.random() < 0.3:
                inputs.append(Ingredient(rng.choice(made)))
            elif rng.random() < 0.2:
                inputs.append(Ingredient(rng.choice(FOODS), optional=rng.random() < 0.6))
            else:
                inputs.append(Ingredient(rng.choice(FOODS), float(rng.choice(NUMBERS)), rng.choice(UNITS), rng.random() < 0.2))
        tools = rng.sample(TOOLS, rng.randint(0, 3))
        heat = []
        for tool in tools:
            roll = rng.random()
            if roll < 0.3:
                heat.append(Heat(tool, temp=float(rng.choice([350, 425, 220, 180.5])), unit=rng.choice(["F", "C"])))
            elif roll < 0.5:
                heat.append(Heat(tool, level=rng.choice(HEAT_LEVELS)))
        after = None
        if i > 1 and rng.random() < 0.4:
            after = tuple(sorted(rng.sample(range(1, i), rng.randint(0, i - 1))))
        steps.append(StepDoc(
            label=rng.choice(["mix it", "Rest the dough", "plate", "étape finale", "toss well"]),
            method=rng.choice(list(VERBS) + ["Smoking", None, None]),
            inputs=tuple(inputs), makes=f"Thing {i}", equipment=tuple(tools),
            minutes=rng.choice([None, 0.0, 2.0, 5.5, 15.0]), wait_minutes=rng.choice([None, 0.0, 18.0, 480.0, 0.25]),
            after=after, heat=tuple(heat),
            until=rng.choice([None, "golden", "until tender", "Until set", "the rice is soft"]),
            inside=rng.choice([None, (165.0, "F"), (74.0, "C"), (62.5, "C")]),
        ))
    return steps


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--count", type=int, default=400, help="how many recipes' worth of steps to compare")
    args = parser.parse_args(argv)
    client = connect(owner_data_ok=True)     # reads nothing: the method only writes sentences
    client.wait_until_ready()
    rng = random.Random(35)
    differences = compared = 0
    for n in range(args.count):
        steps = random_steps(rng)
        want = instructions(steps)
        r = client.session.post(f"{client.base_url}/structr/rest/writeInstructions", json={"steps": as_data(steps)},
                                timeout=client.timeout)
        if r.status_code == 404:
            print("problem: the writeInstructions method is not installed here (tools/install_methods.py)")
            return 1
        r.raise_for_status()
        got = r.json()["result"]
        compared += len(want)
        for k, (a, b) in enumerate(zip(want, got + [None] * len(want)), 1):
            if a != b:
                differences += 1
                if differences <= 10:
                    print(f"recipe {n}, step {k}:\n  Python: {a!r}\n  page:   {b!r}")
        if len(got) != len(want):
            differences += 1
            print(f"recipe {n}: {len(want)} sentences from Python, {len(got)} from the page")
    print(f"{compared} sentences compared, {differences} difference(s)")
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
