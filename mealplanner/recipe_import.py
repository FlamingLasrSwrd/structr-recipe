"""Recipes from plain data files into the graph, and back out again.

A recipe is written as one TOML file (docs/recipe-format.md) and loaded by
tools/import_recipe.py. The file is the reviewable record of what was
transcribed; the recipe itself lives in Structr. Loading is idempotent: the
same file loaded twice changes nothing, and an edited file updates the recipe
in place, removing Steps and Specifications the file no longer has.

What a file becomes (data-model.md Sec 5, the same shapes scripts/15c builds):

  RecipeIdentity <name>                 meal types; the enduring dish
    Identifier <name> source            the web page it came from (scheme "Web page")
  Plan <name> v<version>                specializationOf the RecipeIdentity; yield in servings,
    QuantitySpecification ... yield     minutes, difficulty, hours made ahead
    Step <plan> step <i> -- <label>     instanceOf a Transformation Method
      Specification ... input <j> <food>   specifies a Food-Identity Type; quantity if stated
      Specification ... output <type>      the Step's product
      Specification ... equipment <k> <x>  instrument role: a tool the Step needs
        StateRequirement ... heat          what the tool is set to: Temperature or Heat Level
      Specification ... output <type> doneness / inside   when it is done: Doneness, Temperature inside
      QuantitySpecification ... working time / waiting time   the Step's minutes (J35)
      the Steps before it                  isPrecededBy (P-Plan); by default the one before

The dish and every intermediate are Food-Identity Types: an existing one is
reused (a known cooked food keeps its own profiles, Sec 8 rule 7(a)), a new one
is created. Every ingredient, method and meal type must already exist: a name
that does not resolve stops the load before anything is written, so a typo can
never become a new food.

A Plan that has been cooked (a Process concretizes it) is history: its
Allocations fulfil its Specifications. A changed file is refused for it, and
the change goes in as a new `version`, a second Plan of the same
RecipeIdentity, which is what the model's Plan versions are for.

Output quantities are not stored. The dish's mass is not needed for its
nutrition per serving (J18), and a stored guess would outlive the ingredient
list it was computed from.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace

from mealplanner.identifier_schema import WEB_PAGE
from mealplanner.nutrition_scope import COUNT_UNITS
from mealplanner.step_facts_schema import DONENESS, HEAT_LEVEL, QUALITY_KIND_HIERARCHY, TEMPERATURE
from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from structr_client.client import UNSAFE_EXACT_MATCH_CHARS

DIFFICULTIES = ("easy", "medium", "hard")
FOOD_HIERARCHY = "Food Identity"
METHOD_HIERARCHY = "Transformation Method"
EQUIPMENT_HIERARCHY = "Equipment Type"
MEAL_TYPE_SCHEME = "Meal Type"
TOP_KEYS = {"name", "version", "source", "servings", "minutes", "ahead_hours", "difficulty", "meal_types", "dish", "steps",
            "baseline"}
STEP_KEYS = {"name", "method", "makes", "inputs", "equipment", "minutes", "wait_minutes", "after", "until", "inside"}
TOOL_KEYS = {"tool", "temp", "unit", "heat"}
HEAT_LEVELS = ("low", "medium-low", "medium", "medium-high", "high")
TEMP_UNITS = {"F": "degF", "C": "degC"}          # as a file says it -> as a QuantitySpecification stores it
UNTIL_MAX = 60                                   # "until golden": a few words of doneness, not instructions
# A step's name is a label of a few words, never the source's instructions, which are not stored
# (docs/recipe-copyright.md): the file has no field for them, and this keeps a name from holding them.
STEP_NAME_MAX = 80
INPUT_KEYS = {"food", "amount", "unit", "optional"}


class RecipeFormatError(ValueError):
    """A recipe file that does not say what a recipe needs. Lists every problem."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


class RecipeResolutionError(LookupError):
    """Names in a recipe file that are not in the vocabulary. Lists every one."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


class RecipeFrozenError(RuntimeError):
    """A changed file for a Plan that has already been cooked."""


@dataclass(frozen=True)
class Ingredient:
    food: str
    amount: float | None = None
    unit: str | None = None
    optional: bool = False


@dataclass(frozen=True)
class Heat:
    """What a tool is set to (J35): a temperature (an oven, `unit` "F" or "C") or a level (a burner)."""
    tool: str
    temp: float | None = None
    unit: str | None = None
    level: str | None = None


@dataclass(frozen=True)
class StepDoc:
    label: str
    method: str | None
    inputs: tuple[Ingredient, ...]
    makes: str
    equipment: tuple[str, ...] = ()   # the tools the step needs: instrument Specifications
    # The step's facts (J35); every one optional
    minutes: float | None = None              # working time: the step takes someone's attention
    wait_minutes: float | None = None         # waiting time: it then needs no one (simmering, baking, resting)
    after: tuple[int, ...] | None = None      # the steps (numbered from 1) done before it; None: the one before it
    heat: tuple[Heat, ...] = ()               # what each tool set is set to, in the tools' order
    until: str | None = None                  # doneness in a few words ("golden")
    inside: tuple[float, str] | None = None   # the temperature the food reaches inside, (temp, "F" or "C")


@dataclass(frozen=True)
class RecipeDoc:
    name: str
    servings: float
    steps: tuple[StepDoc, ...]
    meal_types: tuple[str, ...]
    version: int = 1
    source: str | None = None
    minutes: float | None = None
    difficulty: str | None = None
    ahead_hours: float | None = None    # waiting no one attends, before the meal (J29)

    @property
    def dish(self) -> str:
        return self.steps[-1].makes

    @property
    def plan_name(self) -> str:
        return f"{self.name} v{self.version}"

    def plan_part(self) -> tuple:
        """What a Plan version holds (not the RecipeIdentity's meal types or source)."""
        return (self.servings, self.minutes, self.difficulty, self.steps, self.ahead_hours)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _safe_name(where: str, value, problems: list[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        problems.append(f"{where} must be a non-empty string")
        return False
    if value != value.strip():
        problems.append(f"{where} {value!r} has leading or trailing spaces")
        return False
    bad = [c for c in UNSAFE_EXACT_MATCH_CHARS if c in value]
    if bad:
        problems.append(f"{where} {value!r} contains {' and '.join(repr(c) for c in bad)}, which a name cannot hold")
        return False
    return True


def parse_recipe(data: dict) -> RecipeDoc:
    """A RecipeDoc from a parsed file, or RecipeFormatError naming every problem."""
    problems: list[str] = []
    for key in sorted(set(data) - TOP_KEYS):
        problems.append(f"unknown key {key!r} (allowed: {', '.join(sorted(TOP_KEYS))})")
    name = data.get("name")
    _safe_name("name", name, problems)
    version = data.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        problems.append(f"version must be a whole number from 1, not {version!r}")
    source = data.get("source")
    if source is not None and not (isinstance(source, str) and source.startswith(("http://", "https://"))):
        problems.append(f"source must be a web address, not {source!r}")
    servings = data.get("servings")
    if not _number(servings) or servings <= 0:
        problems.append(f"servings must be a number above 0, not {servings!r}")
    minutes = data.get("minutes")
    if minutes is not None and (not _number(minutes) or minutes < 0):
        problems.append(f"minutes must be a number from 0, not {minutes!r}")
    ahead_hours = data.get("ahead_hours")
    if ahead_hours is not None and (not _number(ahead_hours) or ahead_hours <= 0):
        problems.append(f"ahead_hours must be a number above 0, not {ahead_hours!r}")
    difficulty = data.get("difficulty")
    if difficulty is not None and difficulty not in DIFFICULTIES:
        problems.append(f"difficulty must be one of {', '.join(DIFFICULTIES)}, not {difficulty!r}")
    baseline = data.get("baseline", False)
    if not isinstance(baseline, bool):
        problems.append(f"baseline must be true or false, not {baseline!r}")
        baseline = False
    meal_types = data.get("meal_types", [] if baseline else None)
    if baseline:
        if meal_types:
            problems.append("a baseline is eaten every day, outside the planned meals: it takes no meal_types")
        if servings != 1:
            problems.append("a baseline's servings must be 1: one serving is one day of it")
        meal_types = []
    elif not isinstance(meal_types, list) or not meal_types or not all(isinstance(m, str) for m in meal_types):
        problems.append("meal_types must be a list of at least one meal type (a recipe with none can never be planned)")
        meal_types = []
    dish = data.get("dish", name)
    _safe_name("dish", dish, problems)

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        problems.append("steps must be a list of at least one step")
        raw_steps = []
    steps: list[StepDoc] = []
    for i, raw in enumerate(raw_steps, 1):
        where = f"step {i}"
        if not isinstance(raw, dict):
            problems.append(f"{where} must be a table")
            continue
        for key in sorted(set(raw) - STEP_KEYS):
            problems.append(f"{where}: unknown key {key!r} (allowed: {', '.join(sorted(STEP_KEYS))})")
        label = raw.get("name", f"step {i}")
        if _safe_name(f"{where} name", label, problems) and len(label) > STEP_NAME_MAX:
            problems.append(f"{where}: its name is {len(label)} characters; a step's name is a label of a few words "
                            f"(at most {STEP_NAME_MAX}), not the recipe's instructions, which are not stored "
                            f"(docs/recipe-copyright.md)")
        method = raw.get("method")
        if method is not None:
            _safe_name(f"{where} method", method, problems)
        last = i == len(raw_steps)
        makes = raw.get("makes", dish if last else None)
        if makes is None:
            problems.append(f"{where}: only the last step may leave out `makes` (it makes the dish)")
        elif _safe_name(f"{where} makes", makes, problems) and last and makes != dish:
            problems.append(f"{where}: the last step makes the dish {dish!r}, not {makes!r}")
        inputs: list[Ingredient] = []
        raw_inputs = raw.get("inputs")
        if not isinstance(raw_inputs, list) or not raw_inputs:
            problems.append(f"{where}: inputs must be a list of at least one ingredient")
            raw_inputs = []
        for j, item in enumerate(raw_inputs, 1):
            iw = f"{where} input {j}"
            if not isinstance(item, dict):
                problems.append(f"{iw} must be a table")
                continue
            for key in sorted(set(item) - INPUT_KEYS):
                problems.append(f"{iw}: unknown key {key!r} (allowed: {', '.join(sorted(INPUT_KEYS))})")
            food = item.get("food")
            _safe_name(f"{iw} food", food, problems)
            amount, unit = item.get("amount"), item.get("unit")
            if amount is None and unit is not None:
                problems.append(f"{iw}: a unit without an amount")
            if amount is not None:
                if not _number(amount) or amount <= 0:
                    problems.append(f"{iw}: amount must be a number above 0, not {amount!r}")
                if not isinstance(unit, str) or unit not in UNIT_TABLE:
                    problems.append(f"{iw}: unit {unit!r} is not one of {', '.join(UNIT_TABLE)}")
            optional = item.get("optional", False)
            if not isinstance(optional, bool):
                problems.append(f"{iw}: optional must be true or false")
            inputs.append(Ingredient(food, None if amount is None else float(amount), unit, optional))
        raw_tools = raw.get("equipment", [])
        if not isinstance(raw_tools, list):
            problems.append(f"{where}: equipment must be a list of names")
            raw_tools = []
        equipment, heat = [], []
        for k, item in enumerate(raw_tools, 1):
            tw = f"{where} equipment {k}"
            if isinstance(item, dict):
                for key in sorted(set(item) - TOOL_KEYS):
                    problems.append(f"{tw}: unknown key {key!r} (allowed: {', '.join(sorted(TOOL_KEYS))})")
                tool = item.get("tool")
                setting = _heat(tw, tool, item, problems)
                if setting is not None:
                    heat.append(setting)
            else:
                tool = item
            _safe_name(f"{tw}", tool, problems)
            equipment.append(tool)
        if len(set(equipment)) != len(equipment):
            problems.append(f"{where}: a piece of equipment is listed twice")
        minutes_here, wait = raw.get("minutes"), raw.get("wait_minutes")
        for key, value in (("minutes", minutes_here), ("wait_minutes", wait)):
            if value is not None and (not _number(value) or value < 0):
                problems.append(f"{where}: {key} must be a number from 0, not {value!r}")
        until = raw.get("until")
        if until is not None and (not isinstance(until, str) or not until.strip() or len(until) > UNTIL_MAX or "\n" in until):
            problems.append(f"{where}: until is a few words of doneness (at most {UNTIL_MAX} characters, as \"golden\"), "
                            f"not {until!r}: the recipe's own instructions are not stored (docs/recipe-copyright.md)")
        inside = raw.get("inside")
        if inside is not None:
            if not isinstance(inside, dict) or set(inside) != {"temp", "unit"} or not _number(inside.get("temp")) \
                    or inside.get("temp") <= 0 or inside.get("unit") not in TEMP_UNITS:
                problems.append(f"{where}: inside is a temperature the food reaches, as {{ temp = 165, unit = \"F\" }}, "
                                f"not {inside!r}")
                inside = None
            else:
                inside = (float(inside["temp"]), inside["unit"])
        after_names = raw.get("after")
        if after_names is not None and (not isinstance(after_names, list) or not all(isinstance(a, str) for a in after_names)):
            problems.append(f"{where}: after must be a list of the names of earlier steps")
            after_names = None
        as_minutes = lambda value: float(value) if _number(value) and value >= 0 else None
        steps.append(StepDoc(label, method, tuple(inputs), makes, tuple(equipment), as_minutes(minutes_here), as_minutes(wait),
                             tuple(after_names) if after_names is not None else None, tuple(heat),
                             until.strip() if isinstance(until, str) else None, inside))

    steps = _order(steps, problems)
    made = [s.makes for s in steps]
    if len(set(made)) != len(made):
        problems.append("two steps make the same thing")
    for i, step in enumerate(steps):
        used_later = any(ing.food == step.makes for later in steps[i + 1:] for ing in later.inputs)
        if i < len(steps) - 1 and not used_later:
            problems.append(f"step {i + 1} makes {step.makes!r}, which no later step uses (a recipe has one final dish)")
        for ing in step.inputs:
            if ing.food in made[i:]:
                problems.append(f"step {i + 1} uses {ing.food!r}, which is made at or after it")

    if problems:
        raise RecipeFormatError(problems)
    return RecipeDoc(
        name=name, servings=float(servings), steps=tuple(steps), meal_types=tuple(meal_types), version=version,
        source=source, minutes=None if minutes is None else float(minutes), difficulty=difficulty,
        ahead_hours=None if ahead_hours is None else float(ahead_hours),
    )


def _heat(where: str, tool, item: dict, problems: list[str]) -> Heat | None:
    """A tool's setting from its table: { tool = "Oven", temp = 425, unit = "F" } or { tool = "Skillet",
    heat = "medium-high" }; None when it sets none."""
    temp, unit, level = item.get("temp"), item.get("unit"), item.get("heat")
    if temp is None and level is None:
        if unit is not None:
            problems.append(f"{where}: a unit with no temperature")
        return None
    if temp is not None and level is not None:
        problems.append(f"{where}: a temperature or a heat level, not both")
        return None
    if level is not None:
        if level not in HEAT_LEVELS:
            problems.append(f"{where}: heat must be one of {', '.join(HEAT_LEVELS)}, not {level!r}")
            return None
        return Heat(tool, level=level)
    if not _number(temp) or temp <= 0 or unit not in TEMP_UNITS:
        problems.append(f"{where}: a temperature is a number above 0 with a unit of F or C, not {temp!r} {unit!r}")
        return None
    return Heat(tool, temp=float(temp), unit=unit)


def _order(steps: list[StepDoc], problems: list[str]) -> list[StepDoc]:
    """Each step's `after`, from the names of earlier steps to their numbers, and None where it is the
    default (just the step before; nothing, for the first). A step that uses what another makes must
    come after it, directly or through the steps between."""
    labels = [s.label for s in steps]
    out = []
    for i, step in enumerate(steps, 1):
        default = (i - 1,) if i > 1 else ()
        if step.after is None:
            out.append(step)
            continue
        numbers = []
        for name in step.after:
            earlier = [j for j, label in enumerate(labels[:i - 1], 1) if label == name]
            if len(earlier) != 1:
                problems.append(f"step {i}: after names {name!r}, which is " + (
                    "no earlier step" if not earlier else f"{len(earlier)} earlier steps: name them apart"))
                continue
            numbers.append(earlier[0])
        numbers = tuple(sorted(set(numbers)))
        out.append(replace(step, after=None if numbers == default else numbers))
    before = {}
    for i, step in enumerate(out, 1):
        direct = step.after if step.after is not None else ((i - 1,) if i > 1 else ())
        before[i] = set(direct).union(*(before[j] for j in direct)) if direct else set()
    for j, later in enumerate(out, 1):
        for i, step in enumerate(out[:j - 1], 1):
            if any(ing.food == step.makes for ing in later.inputs) and i not in before[j]:
                problems.append(f"step {j} uses {step.makes!r}, which step {i} makes, so it must come after it (after)")
    return out


def read_recipe(path) -> RecipeDoc:
    with open(path, "rb") as fh:
        return parse_recipe(tomllib.load(fh))


# -- resolving names -------------------------------------------------------

@dataclass
class Resolved:
    foods: dict[str, str]              # ingredient name -> DomainType id
    methods: dict[str, str]
    meal_types: dict[str, str]         # -> Concept id
    products: dict[str, str | None]    # dish and intermediates -> existing DomainType id, or None to create
    food_hierarchy: str
    web_page: str | None               # the "Web page" identifier scheme, if the file has a source
    equipment: dict[str, str] = field(default_factory=dict)   # -> Equipment Type id
    qualities: dict[str, str] = field(default_factory=dict)   # Quality Kind name -> id: heat and doneness (J35)


def _one(client, path: str, name: str) -> list[dict]:
    return client.get(path, params={"name": name})["result"]


def resolve(client, doc: RecipeDoc) -> Resolved:
    """Every name in the file looked up, or RecipeResolutionError listing each
    one that is missing or ambiguous. Nothing is written."""
    problems: list[str] = []
    food_h = _one(client, "/structr/rest/TypeHierarchy", FOOD_HIERARCHY)
    method_h = _one(client, "/structr/rest/TypeHierarchy", METHOD_HIERARCHY)
    equipment_h = _one(client, "/structr/rest/TypeHierarchy", EQUIPMENT_HIERARCHY)
    if len(food_h) != 1 or len(method_h) != 1 or len(equipment_h) != 1:
        raise RecipeResolutionError([f"the {FOOD_HIERARCHY!r}, {METHOD_HIERARCHY!r} and {EQUIPMENT_HIERARCHY!r} "
                                     f"hierarchies must each exist once"])
    food_h, method_h, equipment_h = food_h[0]["id"], method_h[0]["id"], equipment_h[0]["id"]

    def domain_type(name: str, hierarchy: str, what: str, may_be_missing=False) -> str | None:
        matches = _one(client, "/structr/rest/DomainType", name)
        if not matches:
            if not may_be_missing:
                problems.append(f"{what} {name!r} is not in the vocabulary")
            return None
        if len(matches) > 1:
            problems.append(f"{what} {name!r} matches {len(matches)} types")
            return None
        # A query row carries only id, name and type; the hierarchy needs the node itself.
        if (client.get_all("DomainType", matches[0]["id"])["result"].get("hierarchy") or {}).get("id") != hierarchy:
            problems.append(f"{what} {name!r} exists but is not in the right hierarchy")
            return None
        return matches[0]["id"]

    products = {s.makes: domain_type(s.makes, food_h, "product", may_be_missing=True) for s in doc.steps}
    foods = {}
    for step in doc.steps:
        for ing in step.inputs:
            if ing.food not in products and ing.food not in foods:
                foods[ing.food] = domain_type(ing.food, food_h, "ingredient")
    methods = {s.method: domain_type(s.method, method_h, "method") for s in doc.steps if s.method}
    equipment = {tool: domain_type(tool, equipment_h, "equipment") for s in doc.steps for tool in s.equipment}
    wanted_kinds = set()
    for step in doc.steps:
        for setting in step.heat:
            wanted_kinds.add(TEMPERATURE if setting.temp is not None else HEAT_LEVEL)
        if step.until:
            wanted_kinds.add(DONENESS)
        if step.inside:
            wanted_kinds.add(TEMPERATURE)
    qualities = {}
    if wanted_kinds:
        kind_h = _one(client, "/structr/rest/TypeHierarchy", QUALITY_KIND_HIERARCHY)
        if len(kind_h) != 1:
            problems.append(f"the {QUALITY_KIND_HIERARCHY!r} hierarchy must exist once (scripts/05 makes it)")
        else:
            for kind in sorted(wanted_kinds):
                found = domain_type(kind, kind_h[0]["id"], "quality kind", may_be_missing=True)
                if found is None and not any(kind in p for p in problems):
                    problems.append(f"quality kind {kind!r} is not in the vocabulary (scripts/41a makes it)")
                qualities[kind] = found
    meal_types = {}
    for meal in doc.meal_types:
        matches = [c for c in _one(client, "/structr/rest/Concept", meal)
                   if (client.get_all("Concept", c["id"])["result"].get("inScheme") or {}).get("name") == MEAL_TYPE_SCHEME]
        if len(matches) != 1:
            problems.append(f"meal type {meal!r} is not in the {MEAL_TYPE_SCHEME!r} scheme")
        else:
            meal_types[meal] = matches[0]["id"]
    web_page = None
    if doc.source:
        concepts = _one(client, "/structr/rest/Concept", WEB_PAGE)
        if len(concepts) != 1:
            problems.append(f"the {WEB_PAGE!r} identifier scheme is missing (scripts/29a builds it)")
        else:
            web_page = concepts[0]["id"]
    if problems:
        raise RecipeResolutionError(problems)
    return Resolved(foods, methods, meal_types, products, food_h, web_page, equipment, qualities)


# -- reading a Plan back ---------------------------------------------------

def export_plan(client, plan_id: str) -> tuple:
    """A stored Plan in the shape of RecipeDoc.plan_part(), so a file and the
    graph can be compared: equal means the file is already loaded."""
    plan = client.get_all("Plan", plan_id)["result"]
    servings = None
    if plan.get("hasRecipeYield"):
        servings = client.get_all("QuantitySpecification", plan["hasRecipeYield"]["id"])["result"].get("value")
    refs = sorted((_step_index(r["name"], plan["name"]), r) for r in plan.get("steps", []))
    nodes = {index: client.get_all("Step", ref["id"])["result"] for index, ref in refs}
    number_of = {ref["id"]: index for index, ref in refs}
    ordered = any(node.get("isPrecededBy") for node in nodes.values())    # one loaded before J35: in sequence
    steps = []
    for index, ref in refs:
        step = nodes[index]
        inputs, makes, tools, heat, until, inside = [], None, [], [], None, None
        specs = [client.get_all("Specification", s["id"])["result"] for s in step.get("hasSpecification", [])]
        for spec in sorted(specs, key=lambda s: s["name"]):
            wanted = _requirements(client, spec)
            if spec.get("hasParticipationRole") == "output":
                makes = spec["specifies"]["name"]
                until = wanted.get(DONENESS, (None, None, None))[0]
                if TEMPERATURE in wanted:
                    inside = (wanted[TEMPERATURE][1], wanted[TEMPERATURE][2])
                continue
            if spec.get("hasParticipationRole") == "instrument":
                k = int(spec["name"].rsplit(" equipment ", 1)[1].split(" ", 1)[0])
                tool = spec["specifies"]["name"]
                tools.append((k, tool))
                if TEMPERATURE in wanted:
                    heat.append((k, Heat(tool, temp=wanted[TEMPERATURE][1], unit=wanted[TEMPERATURE][2])))
                elif HEAT_LEVEL in wanted:
                    heat.append((k, Heat(tool, level=wanted[HEAT_LEVEL][0])))
                continue
            amount = unit = None
            if spec.get("hasSpecifiedQuantity"):
                qty = client.get_all("QuantitySpecification", spec["hasSpecifiedQuantity"]["id"])["result"]
                amount, unit = qty.get("value"), qty.get("unit")
            inputs.append((_input_index(spec["name"]), Ingredient(spec["specifies"]["name"], amount, unit,
                                                                  bool(spec.get("isOptional")))))
        label = step["name"][len(f"{plan['name']} step {index} -- "):]
        method = (step.get("instanceOf") or {}).get("name")
        after = None
        if ordered:
            numbers = tuple(sorted(number_of[r["id"]] for r in step.get("isPrecededBy") or [] if r["id"] in number_of))
            after = None if numbers == ((index - 1,) if index > 1 else ()) else numbers
        steps.append(StepDoc(label, method, tuple(ing for _, ing in sorted(inputs, key=lambda p: p[0])), makes,
                             tuple(tool for _, tool in sorted(tools)), _minutes(client, step.get("hasWorkingTime")),
                             _minutes(client, step.get("hasWaitingTime")), after, tuple(h for _, h in sorted(heat)),
                             until, inside))
    return (servings, plan.get("estimatedDurationMinutes"), plan.get("difficultyRating"), tuple(steps),
            plan.get("makeAheadHours"))


def _minutes(client, ref: dict | None) -> float | None:
    return client.get_all("QuantitySpecification", ref["id"])["result"].get("value") if ref else None


def _requirements(client, spec: dict) -> dict:
    """A Specification's StateRequirements by the Quality Kind each targets: (words, value, unit as a
    file says it)."""
    out = {}
    back = {stored: said for said, stored in TEMP_UNITS.items()}
    for ref in spec.get("hasStateRequirement") or []:
        req = client.get_all("StateRequirement", ref["id"])["result"]
        kind = (req.get("targetsProperty") or {}).get("name")
        value = unit = None
        if req.get("expectedValueQty"):
            qty = client.get_all("QuantitySpecification", req["expectedValueQty"]["id"])["result"]
            value, unit = qty.get("value"), back.get(qty.get("unit"), qty.get("unit"))
        if kind:
            out[kind] = (req.get("expectedValueLiteral"), value, unit)
    return out


def _step_index(step_name: str, plan_name: str) -> int:
    rest = step_name[len(plan_name) + len(" step "):]
    return int(rest.split(" ", 1)[0])


def _input_index(spec_name: str) -> int:
    return int(spec_name.rsplit(" input ", 1)[1].split(" ", 1)[0])


# -- writing ---------------------------------------------------------------

@dataclass
class ImportReport:
    recipe_id: str
    plan_id: str
    plan_unchanged: bool                                     # the Plan already matched the file
    created_types: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unconvertible: list[str] = field(default_factory=list)   # quantities that do not convert to grams
    without_profiles: list[str] = field(default_factory=list)  # raw ingredients with no nutrient profile at all


def step_name(doc: RecipeDoc, i: int, step: StepDoc) -> str:
    return f"{doc.plan_name} step {i} -- {step.label}"


def input_name(doc: RecipeDoc, i: int, j: int, ing: Ingredient) -> str:
    return f"{doc.plan_name} step {i} input {j} {ing.food}"


def output_name(doc: RecipeDoc, i: int, step: StepDoc) -> str:
    return f"{doc.plan_name} step {i} output {step.makes}"


def import_recipe(client, doc: RecipeDoc, *, check_only: bool = False) -> ImportReport | Resolved:
    """Load `doc`. With check_only, resolve every name and stop (returns the
    Resolved names). Raises RecipeResolutionError before writing anything if a
    name is missing, and RecipeFrozenError if the Plan was cooked and differs."""
    names = resolve(client, doc)
    if check_only:
        return names

    existing_plan = _one(client, "/structr/rest/Plan", doc.plan_name)
    if existing_plan:
        plan = client.get_all("Plan", existing_plan[0]["id"])["result"]
        if plan.get("executions") and export_plan(client, plan["id"]) != doc.plan_part():
            raise RecipeFrozenError(f"{doc.plan_name!r} has been cooked, so it is history; load the changed recipe "
                                    f"as version {doc.version + 1}")
    before = export_plan(client, existing_plan[0]["id"]) if existing_plan else None

    report_types = []
    for product, type_id in names.products.items():
        if type_id is None:
            names.products[product] = client.upsert("DomainType", "name", product,
                                                     {"hierarchy": names.food_hierarchy, "isLookupBearing": True})
            report_types.append(product)

    recipe_fields = {"hasMealType": [names.meal_types[m] for m in doc.meal_types]}
    if not _one(client, "/structr/rest/RecipeIdentity", doc.name):
        recipe_fields["isRetired"] = False           # a re-import never un-retires a recipe
    recipe_id = client.upsert("RecipeIdentity", "name", doc.name, recipe_fields)
    if doc.source:
        client.upsert("Identifier", "name", f"{doc.name} source", {
            "identifierValue": doc.source, "identifierScheme": names.web_page, "denotes": recipe_id})
    else:
        for stale in _one(client, "/structr/rest/Identifier", f"{doc.name} source"):
            client.delete(f"/structr/rest/Identifier/{stale['id']}")
    yield_id = client.upsert("QuantitySpecification", "name", f"{doc.plan_name} yield", {
        "value": doc.servings, "unit": "servings", "status": "specified"})
    plan_id = _write(client, "Plan", doc.plan_name, {
        "specializationOf": recipe_id, "hasRecipeYield": yield_id,
        "estimatedDurationMinutes": doc.minutes, "difficultyRating": doc.difficulty, "makeAheadHours": doc.ahead_hours})

    type_of = {**names.foods, **names.products}
    keep_steps, keep_specs, step_ids = set(), set(), []
    for i, step in enumerate(doc.steps, 1):
        name = step_name(doc, i, step)
        fields = {"plan": plan_id, "instanceOf": names.methods.get(step.method) if step.method else None,
                  "hasWorkingTime": _minutes_quantity(client, f"{name} working time", step.minutes),
                  "hasWaitingTime": _minutes_quantity(client, f"{name} waiting time", step.wait_minutes)}
        step_id = _write(client, "Step", name, fields)
        for kind, value in (("working", step.minutes), ("waiting", step.wait_minutes)):
            if value is None:
                _delete_unused(client, f"{name} {kind} time", f"{kind}TimeOfSteps")
        step_ids.append(step_id)
        keep_steps.add(step_id)
        for j, ing in enumerate(step.inputs, 1):
            spec_name = input_name(doc, i, j, ing)
            qty_id = None
            if ing.amount is not None:
                qty_id = client.upsert("QuantitySpecification", "name", f"{spec_name} quantity", {
                    "value": ing.amount, "unit": ing.unit, "status": "specified"})
            spec_id = _write(client, "Specification", spec_name, {
                "step": step_id, "hasParticipationRole": "input", "specifies": type_of[ing.food],
                "hasSpecifiedQuantity": qty_id, "isOptional": ing.optional})
            keep_specs.add(spec_id)
            if qty_id is None:
                _delete_orphan_quantity(client, f"{spec_name} quantity")
        out_name = output_name(doc, i, step)
        out_id = client.upsert("Specification", "name", out_name, {
            "step": step_id, "hasParticipationRole": "output", "specifies": type_of[step.makes], "isOptional": False})
        keep_specs.add(out_id)
        _requirement(client, out_id, f"{out_name} doneness", names.qualities.get(DONENESS) if step.until else None,
                     literal=step.until)
        _requirement(client, out_id, f"{out_name} inside", names.qualities.get(TEMPERATURE) if step.inside else None,
                     value=step.inside[0] if step.inside else None, unit=step.inside[1] if step.inside else None)
        for k, tool in enumerate(step.equipment, 1):     # instrument role: never a quantity (invariant 6)
            tool_name = f"{doc.plan_name} step {i} equipment {k} {tool}"
            tool_id = client.upsert("Specification", "name", tool_name, {
                "step": step_id, "hasParticipationRole": "instrument", "specifies": names.equipment[tool],
                "isOptional": False})
            keep_specs.add(tool_id)
            setting = next((h for h in step.heat if h.tool == tool), None)
            kind = None if setting is None else names.qualities.get(TEMPERATURE if setting.temp is not None else HEAT_LEVEL)
            _requirement(client, tool_id, f"{tool_name} heat", kind, literal=setting.level if setting else None,
                         value=setting.temp if setting else None, unit=setting.unit if setting else None)
    for i, step in enumerate(doc.steps, 1):              # the steps before each: isPrecededBy (P-Plan), written whole
        first = step.after if step.after is not None else ((i - 1,) if i > 1 else ())
        client.patch(f"/structr/rest/Step/{step_ids[i - 1]}", {"isPrecededBy": [step_ids[j - 1] for j in first]})

    removed = _remove_stale(client, plan_id, keep_steps, keep_specs)
    report = ImportReport(recipe_id, plan_id, plan_unchanged=before == doc.plan_part() and not removed,
                          created_types=report_types, removed=removed)
    for food, type_id in names.foods.items():
        node = client.get_all("DomainType", type_id)["result"]
        if not node.get("nutrientProfilesAbout"):
            report.without_profiles.append(food)
    for step in doc.steps:
        for ing in step.inputs:
            if ing.food not in names.foods or ing.amount is None:
                continue
            if ing.unit in COUNT_UNITS and _counted_per_unit(client, names.foods[ing.food]):
                continue                     # a supplement: its figures are per unit, no weight needed
            if convert_to_grams(client, names.foods[ing.food], ing.amount, ing.unit) is None:
                report.unconvertible.append(f"{ing.amount:g} {ing.unit} {ing.food}")
    return report


def _counted_per_unit(client, type_id: str) -> bool:
    node = client.get_all("DomainType", type_id)["result"]
    return any(client.get_all("NutrientProfile", ref["id"])["result"].get("basis") == "per_unit"
               for ref in node.get("nutrientProfilesAbout", []))


def _write(client, type_name: str, name: str, fields: dict) -> str:
    """upsert, and then clear every field given as None. upsert leaves a None
    out, so on its own an edited file could never remove a Step's method, an
    ingredient's amount or a recipe's minutes: the old value stayed."""
    node_id = client.upsert(type_name, "name", name, fields)
    cleared = {k: None for k, v in fields.items() if v is None}
    if cleared:
        client.patch(f"/structr/rest/{type_name}/{node_id}", cleared)
    return node_id


def _minutes_quantity(client, name: str, minutes: float | None) -> str | None:
    """A step's working or waiting time as a QuantitySpecification in minutes; None when it states none."""
    if minutes is None:
        return None
    return client.upsert("QuantitySpecification", "name", name, {"value": minutes, "unit": "minutes", "status": "specified"})


def _requirement(client, spec_id: str, name: str, kind_id: str | None, *, literal: str | None = None,
                 value: float | None = None, unit: str | None = None) -> None:
    """One StateRequirement of a Specification, by name (J35): targeting `kind_id` with words or a
    temperature, or removed, with its value, when kind_id is None."""
    value_name = f"{name} value"
    if kind_id is None:
        for row in _one(client, "/structr/rest/StateRequirement", name):
            client.delete(f"/structr/rest/StateRequirement/{row['id']}")
        _delete_unused(client, value_name, "expectedValueOfStateReqs")
        return
    qty = None
    if value is not None:
        qty = client.upsert("QuantitySpecification", "name", value_name, {"value": value, "unit": TEMP_UNITS[unit],
                                                                          "status": "specified"})
    _write(client, "StateRequirement", name, {"specification": spec_id, "targetsProperty": kind_id,
                                              "expectedValueQty": qty, "expectedValueLiteral": literal})
    if qty is None:
        _delete_unused(client, value_name, "expectedValueOfStateReqs")


def _delete_unused(client, name: str, used_by: str) -> None:
    """A QuantitySpecification of this name that nothing holds by `used_by` any more."""
    for qty in _one(client, "/structr/rest/QuantitySpecification", name):
        node = client.get_all("QuantitySpecification", qty["id"])["result"]
        if not node.get(used_by):
            client.delete(f"/structr/rest/QuantitySpecification/{qty['id']}")


def _delete_orphan_quantity(client, name: str) -> None:
    """A quantity left behind when an ingredient lost its amount ("to taste")."""
    for qty in _one(client, "/structr/rest/QuantitySpecification", name):
        node = client.get_all("QuantitySpecification", qty["id"])["result"]
        if not node.get("specificationsWithThisQuantity"):
            client.delete(f"/structr/rest/QuantitySpecification/{qty['id']}")


def _remove_stale(client, plan_id: str, keep_steps: set[str], keep_specs: set[str]) -> list[str]:
    """Delete this Plan's Steps and Specifications (with their quantities) that
    the file no longer has. Only ever called on a Plan that was never cooked, or
    whose file matched it."""
    removed = []
    plan = client.get_all("Plan", plan_id)["result"]
    for step_ref in plan.get("steps", []):
        step = client.get_all("Step", step_ref["id"])["result"]
        for spec_ref in step.get("hasSpecification", []):
            if step_ref["id"] in keep_steps and spec_ref["id"] in keep_specs:
                continue
            spec = client.get_all("Specification", spec_ref["id"])["result"]
            if spec.get("hasSpecifiedQuantity"):
                client.delete(f"/structr/rest/QuantitySpecification/{spec['hasSpecifiedQuantity']['id']}")
            for req_ref in spec.get("hasStateRequirement") or []:
                req = client.get_all("StateRequirement", req_ref["id"])["result"]
                if req.get("expectedValueQty"):
                    client.delete(f"/structr/rest/QuantitySpecification/{req['expectedValueQty']['id']}")
                client.delete(f"/structr/rest/StateRequirement/{req_ref['id']}")
            client.delete(f"/structr/rest/Specification/{spec_ref['id']}")
            removed.append(spec["name"])
        if step_ref["id"] not in keep_steps:
            for key in ("hasWorkingTime", "hasWaitingTime"):
                if step.get(key):
                    client.delete(f"/structr/rest/QuantitySpecification/{step[key]['id']}")
            client.delete(f"/structr/rest/Step/{step_ref['id']}")
            removed.append(step["name"])
    return removed
