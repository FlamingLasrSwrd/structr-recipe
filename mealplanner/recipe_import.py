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
    QuantitySpecification ... yield     minutes, difficulty
    Step <plan> step <i> -- <label>     instanceOf a Transformation Method
      Specification ... input <j> <food>   specifies a Food-Identity Type; quantity if stated
      Specification ... output <type>      the Step's product

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
from dataclasses import dataclass, field

from mealplanner.identifier_schema import WEB_PAGE
from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from structr_client.client import UNSAFE_EXACT_MATCH_CHARS

DIFFICULTIES = ("easy", "medium", "hard")
FOOD_HIERARCHY = "Food Identity"
METHOD_HIERARCHY = "Transformation Method"
MEAL_TYPE_SCHEME = "Meal Type"
TOP_KEYS = {"name", "version", "source", "servings", "minutes", "difficulty", "meal_types", "dish", "steps"}
STEP_KEYS = {"name", "method", "makes", "inputs"}
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
class StepDoc:
    label: str
    method: str | None
    inputs: tuple[Ingredient, ...]
    makes: str


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

    @property
    def dish(self) -> str:
        return self.steps[-1].makes

    @property
    def plan_name(self) -> str:
        return f"{self.name} v{self.version}"

    def plan_part(self) -> tuple:
        """What a Plan version holds (not the RecipeIdentity's meal types or source)."""
        return (self.servings, self.minutes, self.difficulty, self.steps)


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
    difficulty = data.get("difficulty")
    if difficulty is not None and difficulty not in DIFFICULTIES:
        problems.append(f"difficulty must be one of {', '.join(DIFFICULTIES)}, not {difficulty!r}")
    meal_types = data.get("meal_types")
    if not isinstance(meal_types, list) or not meal_types or not all(isinstance(m, str) for m in meal_types):
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
        _safe_name(f"{where} name", label, problems)
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
        steps.append(StepDoc(label, method, tuple(inputs), makes))

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
    )


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


def _one(client, path: str, name: str) -> list[dict]:
    return client.get(path, params={"name": name})["result"]


def resolve(client, doc: RecipeDoc) -> Resolved:
    """Every name in the file looked up, or RecipeResolutionError listing each
    one that is missing or ambiguous. Nothing is written."""
    problems: list[str] = []
    food_h = _one(client, "/structr/rest/TypeHierarchy", FOOD_HIERARCHY)
    method_h = _one(client, "/structr/rest/TypeHierarchy", METHOD_HIERARCHY)
    if len(food_h) != 1 or len(method_h) != 1:
        raise RecipeResolutionError([f"the {FOOD_HIERARCHY!r} and {METHOD_HIERARCHY!r} hierarchies must each exist once"])
    food_h, method_h = food_h[0]["id"], method_h[0]["id"]

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
    return Resolved(foods, methods, meal_types, products, food_h, web_page)


# -- reading a Plan back ---------------------------------------------------

def export_plan(client, plan_id: str) -> tuple:
    """A stored Plan in the shape of RecipeDoc.plan_part(), so a file and the
    graph can be compared: equal means the file is already loaded."""
    plan = client.get_all("Plan", plan_id)["result"]
    servings = None
    if plan.get("hasRecipeYield"):
        servings = client.get_all("QuantitySpecification", plan["hasRecipeYield"]["id"])["result"].get("value")
    steps = []
    for index, ref in sorted((_step_index(r["name"], plan["name"]), r) for r in plan.get("steps", [])):
        step = client.get_all("Step", ref["id"])["result"]
        inputs, makes = [], None
        specs = [client.get_all("Specification", s["id"])["result"] for s in step.get("hasSpecification", [])]
        for spec in sorted(specs, key=lambda s: s["name"]):
            if spec.get("hasParticipationRole") == "output":
                makes = spec["specifies"]["name"]
                continue
            amount = unit = None
            if spec.get("hasSpecifiedQuantity"):
                qty = client.get_all("QuantitySpecification", spec["hasSpecifiedQuantity"]["id"])["result"]
                amount, unit = qty.get("value"), qty.get("unit")
            inputs.append((_input_index(spec["name"]), Ingredient(spec["specifies"]["name"], amount, unit,
                                                                  bool(spec.get("isOptional")))))
        label = step["name"][len(f"{plan['name']} step {index} -- "):]
        method = (step.get("instanceOf") or {}).get("name")
        steps.append(StepDoc(label, method, tuple(ing for _, ing in sorted(inputs, key=lambda p: p[0])), makes))
    return (servings, plan.get("estimatedDurationMinutes"), plan.get("difficultyRating"), tuple(steps))


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
        "estimatedDurationMinutes": doc.minutes, "difficultyRating": doc.difficulty})

    type_of = {**names.foods, **names.products}
    keep_steps, keep_specs = set(), set()
    for i, step in enumerate(doc.steps, 1):
        fields = {"plan": plan_id, "instanceOf": names.methods.get(step.method) if step.method else None}
        step_id = _write(client, "Step", step_name(doc, i, step), fields)
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
        keep_specs.add(client.upsert("Specification", "name", output_name(doc, i, step), {
            "step": step_id, "hasParticipationRole": "output", "specifies": type_of[step.makes], "isOptional": False}))

    removed = _remove_stale(client, plan_id, keep_steps, keep_specs)
    report = ImportReport(recipe_id, plan_id, plan_unchanged=before == doc.plan_part() and not removed,
                          created_types=report_types, removed=removed)
    for food, type_id in names.foods.items():
        node = client.get_all("DomainType", type_id)["result"]
        if not node.get("nutrientProfilesAbout"):
            report.without_profiles.append(food)
    for step in doc.steps:
        for ing in step.inputs:
            if ing.food in names.foods and ing.amount is not None and \
                    convert_to_grams(client, names.foods[ing.food], ing.amount, ing.unit) is None:
                report.unconvertible.append(f"{ing.amount:g} {ing.unit} {ing.food}")
    return report


def _write(client, type_name: str, name: str, fields: dict) -> str:
    """upsert, and then clear every field given as None. upsert leaves a None
    out, so on its own an edited file could never remove a Step's method, an
    ingredient's amount or a recipe's minutes: the old value stayed."""
    node_id = client.upsert(type_name, "name", name, fields)
    cleared = {k: None for k, v in fields.items() if v is None}
    if cleared:
        client.patch(f"/structr/rest/{type_name}/{node_id}", cleared)
    return node_id


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
            client.delete(f"/structr/rest/Specification/{spec_ref['id']}")
            removed.append(spec["name"])
        if step_ref["id"] not in keep_steps:
            client.delete(f"/structr/rest/Step/{step_ref['id']}")
            removed.append(step["name"])
    return removed
