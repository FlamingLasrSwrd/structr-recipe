"""The curated vocabulary, from data/vocabulary.toml into the graph.

The file names every food, cooking method and nutrient this project knows, and
maps each food to a USDA FoodData Central food (mealplanner/fdc.py). Loading it
(tools/import_vocabulary.py) writes, idempotently:

  Nutrient types       one per FDC nutrient the mapped foods report, each with an
                       Identifier holding its FDC nutrient id (the real key: the
                       names are rewritten, since FDC's contain commas, which a
                       Structr name cannot hold)
  Food types           under the root "Food", or the parent the file names, each
                       with an Identifier holding its FDC id
  NutrientProfiles     every nutrient FDC reports for the food, per 100 g, in
                       FDC's unit; `sourced` for a direct match, `placeholder`
                       for a stand-in (`proxy = true`: the closest food FDC has)
  Density, MassPerUnit from the FDC household portion the file names
  RetentionFactor 1.0  on "Food" for each nutrient the owner decided is kept
                       through cooking (data-model.md Sec 18 J18)
  Transformation methods, with their parents

Existing nodes are matched by name and changed only where they differ. A
food's profiles that its FDC food no longer reports are deleted. A name that
already exists in another hierarchy is an error, not a rename.
"""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass

from mealplanner.identifier_schema import FDC_ID, SCHEME
from mealplanner.nutrition_scope import NUTRIENT_UNITS
from mealplanner.unit_conversion import UNIT_TABLE
from structr_client.client import UNSAFE_EXACT_MATCH_CHARS

VOCABULARY = "data/vocabulary.toml"
FDC_NUTRIENT_ID = "FDC nutrient id"
ROOT_FOOD = "Food"
FOOD_HIERARCHY = "Food Identity"
METHOD_HIERARCHY = "Transformation Method"
NUTRIENT_HIERARCHY = "Nutrient"
# FDC reports energy twice. The kJ figure is the kcal figure converted, and two
# nutrients with one name cannot both exist, so it is left out.
SKIPPED_NUTRIENTS = {"1062": "Energy in kJ, the same energy as 1008 in kcal"}
FDC_UNITS = {"G": "g", "MG": "mg", "UG": "ug", "KCAL": "kcal", "KJ": "kJ", "IU": "IU"}
VOLUME_WORDS = {"cup": "cup", "tbsp": "tbsp", "tsp": "tsp", "fl oz": "fl_oz", "liter": "l"}


class VocabularyError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class Food:
    name: str
    parent: str
    fdc: int | None = None
    proxy: bool = False
    each: str | None = None           # FDC portion label giving the mass of one
    volume: str | None = None         # FDC portion label giving a density
    density_from: int | None = None   # another FDC food whose portion gives the density (same food, other entry)


@dataclass(frozen=True)
class Method:
    name: str
    parent: str | None = None


@dataclass(frozen=True)
class Vocabulary:
    subset: str
    foods: tuple[Food, ...]
    methods: tuple[Method, ...]
    kept_in_cooking: tuple[str, ...]      # FDC nutrient ids
    fdc: dict | None = None               # the pinned subset, once read


def nutrient_name(fdc_name: str) -> str:
    """An FDC nutrient name a Structr name can hold: "Sodium, Na" -> "Sodium - Na"."""
    return fdc_name.replace(", ", " - ").replace(",", " -").replace(";", " -").strip()


def volume_unit(label: str) -> str | None:
    """The volume unit an FDC portion label starts with ("cup, chopped" -> "cup"), or None."""
    text = label.lower()
    for word, unit in VOLUME_WORDS.items():
        if text == word or text.startswith(word + " ") or text.startswith(word + ","):
            return unit
    return None


def _portion(fdc: dict, fdc_id: int, label: str) -> dict | None:
    matches = [p for p in fdc["foods"][str(fdc_id)]["portions"] if p["label"] == label]
    return matches[0] if len(matches) == 1 else None


def density(fdc: dict, food: Food) -> float | None:
    """Grams per mL from the named volume portion: grams / (amount x mL of the unit)."""
    if not food.volume:
        return None
    portion = _portion(fdc, food.density_from or food.fdc, food.volume)
    return portion["grams"] / (portion["amount"] * UNIT_TABLE[volume_unit(food.volume)][1])


def mass_per_each(fdc: dict, food: Food) -> float | None:
    if not food.each:
        return None
    portion = _portion(fdc, food.fdc, food.each)
    return portion["grams"] / portion["amount"]


def parse_vocabulary(data: dict, fdc: dict | None) -> Vocabulary:
    """A Vocabulary, or VocabularyError naming every problem. With `fdc` (the
    pinned subset), every FDC id and portion label is checked against it."""
    problems: list[str] = []

    def name_ok(where, value) -> bool:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            problems.append(f"{where}: a name must be a non-empty string without surrounding spaces")
            return False
        if any(c in value for c in UNSAFE_EXACT_MATCH_CHARS):
            problems.append(f"{where} {value!r}: a name cannot hold a comma or a semicolon")
            return False
        return True

    subset = (data.get("source") or {}).get("subset")
    if not isinstance(subset, str):
        problems.append("[source] subset must name the pinned FDC file")
    methods = []
    for i, raw in enumerate(data.get("method", []), 1):
        if name_ok(f"method {i}", raw.get("name")):
            methods.append(Method(raw["name"], raw.get("parent")))
    method_names = {m.name for m in methods}
    for m in methods:
        if m.parent is not None and m.parent not in method_names:
            problems.append(f"method {m.name!r}: parent {m.parent!r} is not a method in the file")

    foods = []
    allowed = {"name", "parent", "fdc", "proxy", "each", "volume", "density_from", "note"}
    for i, raw in enumerate(data.get("food", []), 1):
        where = f"food {i}"
        for key in sorted(set(raw) - allowed):
            problems.append(f"{where}: unknown key {key!r}")
        if not name_ok(where, raw.get("name")):
            continue
        where = f"food {raw['name']!r}"
        food = Food(raw["name"], raw.get("parent", ROOT_FOOD), raw.get("fdc"), raw.get("proxy", False),
                    raw.get("each"), raw.get("volume"), raw.get("density_from"))
        if food.proxy and not food.fdc:
            problems.append(f"{where}: a proxy needs an fdc id")
        if (food.each or food.volume) and not food.fdc:
            problems.append(f"{where}: portions need an fdc id")
        if food.volume and volume_unit(food.volume) is None:
            problems.append(f"{where}: portion {food.volume!r} does not start with a volume unit")
        if fdc is not None and food.fdc:
            for fid in filter(None, (food.fdc, food.density_from)):
                if str(fid) not in fdc["foods"]:
                    problems.append(f"{where}: FDC {fid} is not in the pinned subset (run tools/fdc_extract.py)")
            if str(food.fdc) in fdc["foods"]:
                if food.each and _portion(fdc, food.fdc, food.each) is None:
                    problems.append(f"{where}: FDC {food.fdc} has no single portion {food.each!r}")
                if food.volume and str(food.density_from or food.fdc) in fdc["foods"] \
                        and _portion(fdc, food.density_from or food.fdc, food.volume) is None:
                    problems.append(f"{where}: FDC {food.density_from or food.fdc} has no single portion {food.volume!r}")
        foods.append(food)
    names = [f.name for f in foods]
    for dup in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"food {dup!r} is listed twice")
    if ROOT_FOOD in names:
        problems.append(f"{ROOT_FOOD!r} is the root and is not listed")

    kept = [str(k) for k in (data.get("retention") or {}).get("kept_in_cooking", [])]
    if fdc is not None:
        for nid in kept:
            if nid not in fdc["nutrients"]:
                problems.append(f"kept_in_cooking: FDC nutrient {nid} is not in the pinned subset")
        seen: dict[str, str] = {}
        for nid, n in fdc["nutrients"].items():
            if nid in SKIPPED_NUTRIENTS:
                continue
            if FDC_UNITS.get(n["unit"].upper()) is None or FDC_UNITS[n["unit"].upper()].lower() not in NUTRIENT_UNITS:
                problems.append(f"FDC nutrient {nid} {n['name']!r} is in {n['unit']!r}, not a nutrient unit")
            name = nutrient_name(n["name"])
            if name in seen:
                problems.append(f"FDC nutrients {seen[name]} and {nid} would both be named {name!r}")
            seen[name] = nid
            if name in names:
                problems.append(f"nutrient {name!r} has the same name as a food; a Structr name is unique")
    if problems:
        raise VocabularyError(problems)
    return Vocabulary(subset, tuple(foods), tuple(methods), tuple(kept), fdc)


def read_vocabulary(path: str, *, check_subset: bool = True) -> Vocabulary:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    fdc = None
    if check_subset:
        subset = (data.get("source") or {}).get("subset", "")
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))), subset)) as fh:
            fdc = json.load(fh)
    return parse_vocabulary(data, fdc)


# -- writing ---------------------------------------------------------------

def _same(current, desired) -> bool:
    if desired is None:
        return current in (None, [], {})
    if isinstance(desired, list):
        return sorted(c["id"] if isinstance(c, dict) else c for c in (current or [])) == sorted(desired)
    if isinstance(current, dict) and "id" in current:
        return current["id"] == desired
    return current == desired


class Sync:
    """Create or change nodes by name, reading each type once. Counts what it did."""

    def __init__(self, client):
        self.client = client
        self.index: dict[str, dict[str, dict]] = {}
        self.counts = {"created": 0, "changed": 0, "unchanged": 0, "deleted": 0}

    def rows(self, type_name: str) -> dict[str, dict]:
        if type_name not in self.index:
            by_name: dict[str, dict] = {}
            for row in self.client.get_all(type_name)["result"]:
                if row.get("type") != type_name:
                    continue          # a polymorphic listing also returns subtypes
                if row.get("name") in by_name:
                    raise VocabularyError([f"two {type_name} nodes are named {row['name']!r}"])
                by_name[row.get("name")] = row
            self.index[type_name] = by_name
        return self.index[type_name]

    def ensure(self, type_name: str, name: str, fields: dict) -> str:
        current = self.rows(type_name).get(name)
        if current is None:
            payload = {k: v for k, v in fields.items() if v is not None}
            payload.update(name=name, visibleToAuthenticatedUsers=True, visibleToPublicUsers=False)
            node_id = self.client.post(f"/structr/rest/{type_name}", payload)["result"][0]
            # Only the id is needed again in this run: every name is ensured once.
            self.rows(type_name)[name] = {"id": node_id, "name": name, "type": type_name}
            self.counts["created"] += 1
            return node_id
        diff = {k: v for k, v in fields.items() if not _same(current.get(k), v)}
        if diff:
            self.client.patch(f"/structr/rest/{type_name}/{current['id']}", diff)
            self.counts["changed"] += 1
        else:
            self.counts["unchanged"] += 1
        return current["id"]

    def delete(self, type_name: str, node: dict) -> None:
        self.client.delete(f"/structr/rest/{type_name}/{node['id']}")
        self.rows(type_name).pop(node.get("name"), None)
        self.counts["deleted"] += 1


def _hierarchy(client, name: str) -> str:
    rows = client.get("/structr/rest/TypeHierarchy", params={"name": name})["result"]
    if len(rows) != 1:
        raise VocabularyError([f"the {name!r} hierarchy must exist once"])
    return rows[0]["id"]


def import_vocabulary(client, vocabulary: Vocabulary) -> dict[str, int]:
    """Write `vocabulary` (read with its pinned subset). Returns what was done."""
    fdc = vocabulary.fdc
    sync = Sync(client)
    hierarchies = {h: _hierarchy(client, h) for h in (FOOD_HIERARCHY, METHOD_HIERARCHY, NUTRIENT_HIERARCHY)}

    problems = []
    for name, hierarchy in ([(f.name, FOOD_HIERARCHY) for f in vocabulary.foods] + [(ROOT_FOOD, FOOD_HIERARCHY)]
                            + [(m.name, METHOD_HIERARCHY) for m in vocabulary.methods]):
        row = sync.rows("DomainType").get(name)
        if row and (row.get("hierarchy") or {}).get("id") != hierarchies[hierarchy]:
            problems.append(f"{name!r} already exists outside the {hierarchy!r} hierarchy")
    in_file = {f.name for f in vocabulary.foods} | {ROOT_FOOD}
    for food in vocabulary.foods:
        parent = sync.rows("DomainType").get(food.parent)
        if food.parent not in in_file and not parent:
            problems.append(f"food {food.name!r}: parent {food.parent!r} is neither in the file nor in the graph")
    if problems:
        raise VocabularyError(problems)

    scheme = sync.ensure("ConceptScheme", SCHEME, {})
    fdc_id_scheme = sync.ensure("Concept", FDC_ID, {"inScheme": scheme})
    nutrient_scheme = sync.ensure("Concept", FDC_NUTRIENT_ID, {"inScheme": scheme})

    nutrient_ids: dict[str, str] = {}
    for nid, n in fdc["nutrients"].items():
        if nid in SKIPPED_NUTRIENTS:
            continue
        name = nutrient_name(n["name"])
        row = sync.rows("DomainType").get(name)
        if row and (row.get("hierarchy") or {}).get("id") != hierarchies[NUTRIENT_HIERARCHY]:
            raise VocabularyError([f"nutrient {name!r} already exists outside the Nutrient hierarchy"])
        nutrient_ids[nid] = sync.ensure("DomainType", name, {"hierarchy": hierarchies[NUTRIENT_HIERARCHY],
                                                             "isLookupBearing": True})
        sync.ensure("Identifier", f"{name} FDC nutrient id", {
            "identifierValue": nid, "identifierScheme": nutrient_scheme, "denotesType": nutrient_ids[nid]})

    method_ids: dict[str, str] = {}
    for method in vocabulary.methods:      # parents before children: the file lists them so
        method_ids[method.name] = sync.ensure("DomainType", method.name, {
            "hierarchy": hierarchies[METHOD_HIERARCHY], "isLookupBearing": True,
            "parent": method_ids.get(method.parent) if method.parent else None})

    food_ids = {ROOT_FOOD: sync.ensure("DomainType", ROOT_FOOD, {"hierarchy": hierarchies[FOOD_HIERARCHY],
                                                                "isLookupBearing": True, "parent": None})}
    pending = list(vocabulary.foods)
    while pending:                          # parents first, in whatever order the file lists them
        ready = [f for f in pending if f.parent in food_ids or f.parent not in in_file]
        if not ready:
            raise VocabularyError([f"a cycle among the parents of {sorted(f.name for f in pending)}"])
        for food in ready:
            parent = food_ids.get(food.parent) or sync.rows("DomainType")[food.parent]["id"]
            food_ids[food.name] = sync.ensure("DomainType", food.name, {
                "hierarchy": hierarchies[FOOD_HIERARCHY], "isLookupBearing": True, "parent": parent})
            pending.remove(food)

    kinds = {k: sync.rows("DomainType")[k]["id"] for k in ("Density", "MassPerUnit", "RetentionFactor")}
    wanted_profiles: set[str] = set()
    for food in vocabulary.foods:
        if not food.fdc:
            continue
        fid = food_ids[food.name]
        sync.ensure("Identifier", f"{food.name} FDC ID", {
            "identifierValue": str(food.fdc), "identifierScheme": fdc_id_scheme, "denotesType": fid})
        record = fdc["foods"][str(food.fdc)]
        for nid, amount in record["nutrients"].items():
            if nid in SKIPPED_NUTRIENTS:
                continue
            nutrient = nutrient_name(fdc["nutrients"][nid]["name"])
            profile = f"{food.name} -- {nutrient} per 100 g"
            wanted_profiles.add(profile)
            sync.ensure("NutrientProfile", profile, {
                "isAbout": fid, "forNutrient": nutrient_ids[nid], "amount": amount, "basis": "per_100g",
                "unit": FDC_UNITS[fdc["nutrients"][nid]["unit"].upper()],
                "provenance": "placeholder" if food.proxy else "sourced"})
        for kind, value, unit in (("Density", density(fdc, food), "g_per_mL"),
                                  ("MassPerUnit", mass_per_each(fdc, food), "g_per_each")):
            if value is None:
                continue
            label = "density" if kind == "Density" else "mass per each"
            qty = sync.ensure("QuantitySpecification", f"{food.name} {label} value", {
                "value": round(value, 6), "unit": unit, "status": "default"})
            sync.ensure("DefaultSpecification", f"{food.name} {label}", {
                "forType": fid, "hasKind": kinds[kind], "hasValue": qty})
    for profile in list(sync.rows("NutrientProfile").values()):
        about = (profile.get("isAbout") or {}).get("name")
        mapped = {f.name for f in vocabulary.foods if f.fdc}
        if about in mapped and profile["name"] not in wanted_profiles:
            sync.delete("NutrientProfile", profile)

    for nid in vocabulary.kept_in_cooking:
        nutrient = nutrient_name(fdc["nutrients"][nid]["name"])
        qty = sync.ensure("QuantitySpecification", f"Retention of {nutrient} in cooking value", {
            "value": 1.0, "unit": "ratio", "status": "default"})
        sync.ensure("DefaultSpecification", f"Retention of {nutrient} in cooking", {
            "forType": food_ids[ROOT_FOOD], "hasKind": kinds["RetentionFactor"], "hasValue": qty,
            "keyedBy": [nutrient_ids[nid]]})
    return sync.counts
