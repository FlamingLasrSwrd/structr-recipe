"""Instructions written from a recipe's steps (docs/todo.md, "Instructions written from the steps";
data-model.md J35).

A source's instructions are never stored (docs/recipe-copyright.md). What is stored is the steps'
facts: each step's method, what goes in and how much, what it makes, its tools and their heat, its
working and waiting minutes, the steps before it and when what it makes is done. This writes each
step as one plain sentence of our own from those facts:

  "Simmer the rice (rinsed) on the stove over low heat, about 20 minutes, 2 of them hands-on."
  "Meanwhile, roast 300 g chicken in the oven at 425 °F until golden and 165 °F inside, about 30 minutes."

The verb is the method's (VERBS); a step with no method, or one the list does not know, starts with
its own label of a few words instead. "Meanwhile" marks a step that does not follow the one before it.
pages/lib/75_instructions.js writes the same sentences, word for word, on the recipe page;
tools/check_instructions.py and tools/check_pages.py compare the two.
"""

from __future__ import annotations

import math

VERBS = {
    "Boiling": "Boil", "Simmering": "Simmer", "Braising": "Braise", "Stir-Frying": "Stir-fry", "Searing": "Sear",
    "Sauteing": "Sauté", "Roasting": "Roast", "Baking": "Bake", "Broiling": "Broil", "Soaking": "Soak",
    "Marinating": "Marinate", "Mixing": "Mix", "Chopping": "Chop", "Dicing": "Dice", "Mincing": "Mince",
    "Slicing": "Slice", "Grating": "Grate", "Peeling": "Peel", "Mashing": "Mash",
}
COUNTED = ("each", "whole", "count")          # "4 garlic", not "4 each garlic"


def number(x: float) -> str:
    """A number as the JavaScript twin writes it: to three places at most, rounded by the same
    arithmetic (half up), then the shortest form of that double ("400", "1.5", "0.125")."""
    r = math.floor(x * 1000 + 0.5) / 1000
    return str(int(r)) if r == int(r) else repr(r)


def join(items: list[str]) -> str:
    """"a", "a and b", "a, b and c"."""
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def ingredient(ing, made: set) -> str:
    name = ing.food.lower()
    if ing.food in made:
        return "the " + name
    unit = "" if ing.unit in COUNTED else " " + (ing.unit or "")
    alternatives = []
    for sub in getattr(ing, "substitutes", ()):           # what may stand in, by its ratio; never one ruled out
        if sub.never:
            continue
        scaled = "" if ing.amount is None or sub.ratio == 1 else number(ing.amount * sub.ratio) + unit + " "
        alternatives.append("or " + scaled + sub.food.lower())
    other = f" ({', '.join(alternatives)})" if alternatives else ""
    if ing.amount is None:
        return name + other + (", to taste" if ing.optional else "")
    return f"{number(ing.amount)}{unit} {name}" + other + (" (optional)" if ing.optional else "")


def sentence(i: int, step, made: set) -> str:
    """Step i (from 1), knowing what the steps before it made."""
    what = join([ingredient(ing, made) for ing in step.inputs])
    verb = VERBS.get(step.method or "")
    parts = [f"{verb} {what}" if verb else f"{step.label[:1].upper()}{step.label[1:]}: {what}"]
    heated = {h.tool: h for h in step.heat}
    for tool in step.equipment:
        setting = heated.get(tool)
        if setting is not None and setting.temp is not None:
            parts.append(f"in the {tool.lower()} at {number(setting.temp)} °{setting.unit}")
        elif setting is not None:
            parts.append(f"on the {tool.lower()} over {setting.level} heat")
    plain = [tool.lower() for tool in step.equipment if tool not in heated]
    if plain:
        parts.append("using the " + join(plain))
    done = []
    if step.until:
        done.append(step.until[6:] if step.until.lower().startswith("until ") else step.until)
    if step.inside:
        done.append(f"{number(step.inside[0])} °{step.inside[1]} inside")
    if done:
        parts.append("until " + " and ".join(done))
    text = " ".join(parts)
    total = (step.minutes or 0) + (step.wait_minutes or 0)
    if total:
        text += f", about {number(total)} minutes"
        if step.minutes and step.wait_minutes:
            text += f", {number(step.minutes)} of them hands-on"
    if i > 1 and step.after is not None and (i - 1) not in step.after:
        text = "Meanwhile, " + text[:1].lower() + text[1:]
    return text + "."


def instructions(steps) -> list[str]:
    """One sentence per step, in order: `steps` as recipe_import.StepDoc, from a file or from
    export_plan."""
    out, made = [], set()
    for i, step in enumerate(steps, 1):
        out.append(sentence(i, step, made))
        made.add(step.makes)
    return out


def as_data(steps) -> list[dict]:
    """Steps as plain data, the shape the writeInstructions method and pages/lib/75_instructions.js read."""
    return [{"label": s.label, "method": s.method, "makes": s.makes, "equipment": list(s.equipment),
             "inputs": [{"food": i.food, "amount": i.amount, "unit": i.unit, "optional": i.optional,
                         "substitutes": [{"food": x.food, "ratio": x.ratio, "never": x.never} for x in i.substitutes]}
                        for i in s.inputs],
             "heat": [{"tool": h.tool, "temp": h.temp, "unit": h.unit, "level": h.level} for h in s.heat],
             "minutes": s.minutes, "wait_minutes": s.wait_minutes,
             "after": list(s.after) if s.after is not None else None, "until": s.until,
             "inside": list(s.inside) if s.inside is not None else None} for s in steps]
