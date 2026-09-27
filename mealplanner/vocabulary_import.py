"""The curated vocabulary, from data/vocabulary.toml into the graph.

The file names every food, cooking method, piece of equipment and nutrient this
project knows, and says where each food's figures come from: USDA FoodData
Central foods (mealplanner/fdc.py) or a stated source. Loading it
(tools/import_vocabulary.py) writes, idempotently:

  Nutrient types       one per FDC nutrient the foods report, each with an
                       Identifier holding its FDC nutrient id (the real key: the
                       names are rewritten, since FDC's contain commas, which a
                       Structr name cannot hold)
  Food types           under the root "Food", or the parent the file names, each
                       with an Identifier holding the FDC id of its first source
  NutrientProfiles     per 100 g, in FDC's unit, each carrying its provenance and
                       its source, so any figure can be checked later (J21)
  Density, MassPerUnit from an FDC household portion, several averaged, or a
                       stated weight with its source; with provenance and source
  RetentionFactor 1.0  on "Food" for each nutrient the owner decided is kept
                       through cooking (data-model.md Sec 18 J18)
  Transformation methods and Equipment Types, with their parents

Where a food's figures come from. A food lists its sources in order; each
nutrient comes from the first source that reports it, so a later source fills
the gaps of an earlier one. A source is one FDC food, or several averaged
(brands, say). Its provenance: `sourced` for a published figure for this very
food, `estimated` for anything nearer or rougher (a similar food, an average of
labels, a web figure), `calculated` for a composition worked out from parts.

Existing nodes are matched by name and changed only where they differ. A
food's profiles for nutrients no source reports any longer are deleted. A name
that already exists in another hierarchy is an error, not a rename.
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
EQUIPMENT_HIERARCHY = "Equipment Type"
STATUSES = ("sourced", "estimated", "calculated")
# FDC reports energy twice. The kJ figure is the kcal figure converted, and two
# nutrients with one name cannot both exist, so it is left out.
SKIPPED_NUTRIENTS = {"1062": "Energy in kJ, the same energy as 1008 in kcal"}
FDC_UNITS = {"G": "g", "MG": "mg", "UG": "ug", "KCAL": "kcal", "KJ": "kJ", "IU": "IU"}
VOLUME_WORDS = {"cup": "cup", "tbsp": "tbsp", "tsp": "tsp", "fl oz": "fl_oz", "liter": "l", "tablespoon": "tbsp"}
DATASETS = {"sr_legacy_food": "SR Legacy", "foundation_food": "Foundation", "survey_fndds_food": "FNDDS",
            "branded_food": "Branded"}
# The Nutrition Facts figures. Every food should have them; --check lists the gaps.
CORE_NUTRIENTS = {"1008": "Energy", "1003": "Protein", "1004": "Total fat", "1258": "Saturated fat",
                  "1253": "Cholesterol", "1005": "Carbohydrate", "1079": "Fiber", "2000": "Sugars",
                  "1093": "Sodium", "1087": "Calcium", "1089": "Iron", "1092": "Potassium", "1162": "Vitamin C"}


class VocabularyError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class Source:
    ids: tuple[int, ...]                  # one FDC food, or several to average
    status: str                           # sourced, estimated or calculated
    only: frozenset | None = None         # the FDC nutrient ids it may supply; None: all it reports
    note: str = ""


@dataclass(frozen=True)
class Measure:
    """A Density (per a volume unit) or a MassPerUnit (per "each")."""
    portions: tuple[tuple[int, str], ...] = ()    # FDC (food id, portion label) pairs, averaged
    grams: float | None = None                    # or a stated weight...
    per: str | None = None                        # ...of this much: a volume unit, or "each"
    status: str = "sourced"
    source: str = ""                              # where a stated weight comes from


@dataclass(frozen=True)
class Food:
    name: str
    parent: str
    sources: tuple[Source, ...] = ()
    each: Measure | None = None
    volume: Measure | None = None

    @property
    def fdc(self) -> int | None:
        """The first source's FDC food, when it is a single one: the food's FDC ID."""
        return self.sources[0].ids[0] if self.sources and len(self.sources[0].ids) == 1 else None


@dataclass(frozen=True)
class Named:
    name: str
    parent: str | None = None


@dataclass(frozen=True)
class Vocabulary:
    subsets: tuple[str, ...]
    foods: tuple[Food, ...]
    methods: tuple[Named, ...]
    equipment: tuple[Named, ...]
    kept_in_cooking: tuple[str, ...]      # FDC nutrient ids
    fdc: dict | None = None               # the pinned subsets merged: {"nutrients": ..., "foods": ...}

    def ids(self) -> set[int]:
        """Every FDC food the file refers to."""
        found = {i for f in self.foods for s in f.sources for i in s.ids}
        for f in self.foods:
            for m in (f.each, f.volume):
                if m:
                    found |= {i for i, _ in m.portions}
        return found


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


def merge(subsets: list[dict]) -> dict:
    """Several pinned subsets as one index. A nutrient's name comes from the
    first subset that defines it (list SR Legacy first); units must agree."""
    nutrients, foods = {}, {}
    for subset in subsets:
        for nid, n in subset["nutrients"].items():
            if nid in nutrients and nutrients[nid]["unit"].upper() != n["unit"].upper():
                raise VocabularyError([f"FDC nutrient {nid} is in {nutrients[nid]['unit']} in one dataset and "
                                       f"{n['unit']} in another"])
            nutrients.setdefault(nid, n)
        for fid, food in subset["foods"].items():
            foods[fid] = food
    return {"nutrients": nutrients, "foods": foods}


def _portion(fdc: dict, fdc_id: int, label: str) -> dict | None:
    matches = [p for p in fdc["foods"][str(fdc_id)]["portions"] if p["label"] == label]
    return matches[0] if len(matches) == 1 else None


def measure_value(fdc: dict, measure: Measure) -> float:
    """Grams per mL (a density) or grams per item: stated, or the mean over the named portions."""
    if measure.grams is not None:
        return measure.grams / (1.0 if measure.per == "each" else UNIT_TABLE[measure.per][1])
    values = []
    for fid, label in measure.portions:
        portion = _portion(fdc, fid, label)
        unit = volume_unit(label)
        values.append(portion["grams"] / (portion["amount"] * (UNIT_TABLE[unit][1] if unit else 1.0)))
    return sum(values) / len(values)


def _describe(fdc: dict, fid: int) -> str:
    food = fdc["foods"][str(fid)]
    label = food.get("brand", "")
    label = f"{label} {food['description']}".strip()
    return f"{DATASETS.get(food['data_type'], food['data_type'])} {fid} ({label})"


def measure_source(fdc: dict, measure: Measure) -> str:
    if measure.grams is not None:
        return f"{measure.grams:g} g per {measure.per}: {measure.source}"
    parts = []
    for fid, label in measure.portions:
        portion = _portion(fdc, fid, label)
        parts.append(f"{_describe(fdc, fid)}: {portion['amount']:g} {label} = {portion['grams']:g} g")
    prefix = "mean of " if len(parts) > 1 else ""
    return f"{prefix}USDA FoodData Central " + "; ".join(parts)


def composition(fdc: dict, food: Food) -> dict[str, tuple[float, str, str]]:
    """nutrient id -> (amount per 100 g, provenance, source) for a food: each
    nutrient from the first source that reports it, averaged over that source's
    foods that report it."""
    out: dict[str, tuple[float, str, str]] = {}
    for source in food.sources:
        records = {fid: fdc["foods"][str(fid)] for fid in source.ids}
        reported = sorted({n for r in records.values() for n in r["nutrients"]}, key=int)
        for nid in reported:
            if nid in out or nid in SKIPPED_NUTRIENTS or (source.only is not None and nid not in source.only):
                continue
            having = [fid for fid, r in records.items() if nid in r["nutrients"]]
            amount = sum(records[fid]["nutrients"][nid] for fid in having) / len(having)
            text = "; ".join(_describe(fdc, fid) for fid in having)
            prefix = "mean of " if len(having) > 1 else ""
            kind = f" ({source.status}: {source.note})" if source.note else ""
            out[nid] = (amount, source.status, f"{prefix}USDA FoodData Central {text}{kind}")
    return out


def core_gaps(fdc: dict, food: Food) -> list[str]:
    have = composition(fdc, food) if food.sources else {}
    return [label for nid, label in CORE_NUTRIENTS.items() if nid not in have]


# -- parsing ---------------------------------------------------------------

def _source(raw, where: str, problems: list[str]) -> Source | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: a source is a table")
        return None
    unknown = set(raw) - {"fdc", "mean", "status", "only", "note"}
    if unknown:
        problems.append(f"{where}: unknown key(s) {sorted(unknown)}")
    if ("fdc" in raw) == ("mean" in raw):
        problems.append(f"{where}: give exactly one of fdc or mean")
        return None
    ids = (raw["fdc"],) if "fdc" in raw else tuple(raw["mean"])
    if not ids or not all(isinstance(i, int) for i in ids):
        problems.append(f"{where}: FDC ids are whole numbers")
        return None
    status = raw.get("status", "sourced" if "fdc" in raw else "estimated")
    if status not in STATUSES:
        problems.append(f"{where}: status must be one of {', '.join(STATUSES)}, not {status!r}")
    only = frozenset(str(n) for n in raw["only"]) if "only" in raw else None
    return Source(ids, status, only, raw.get("note", ""))


def _measure(raw, first: Source | None, where: str, want_volume: bool, problems: list[str]) -> Measure | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = {"portion": raw}
    if not isinstance(raw, dict):
        problems.append(f"{where}: a portion label or a table")
        return None
    unknown = set(raw) - {"portion", "fdc", "portions", "grams", "per", "source", "status"}
    if unknown:
        problems.append(f"{where}: unknown key(s) {sorted(unknown)}")
    if "grams" in raw:
        per = raw.get("per")
        ok_per = (per in UNIT_TABLE and UNIT_TABLE[per][0] == "volume") if want_volume else per == "each"
        if not ok_per:
            problems.append(f"{where}: a stated weight is per {'a volume unit' if want_volume else 'each'}, not {per!r}")
        if not raw.get("source"):
            problems.append(f"{where}: a stated weight needs its source")
        return Measure(grams=float(raw["grams"]), per=per, status=raw.get("status", "estimated"),
                       source=raw.get("source", ""))
    if "portions" in raw:
        pairs = tuple((int(p[0]), str(p[1])) for p in raw["portions"])
        return Measure(portions=pairs, status=raw.get("status", "estimated"))
    fid = raw.get("fdc")
    if fid is None:
        if first is None or len(first.ids) != 1:
            problems.append(f"{where}: name the FDC food whose portion to use")
            return None
        fid = first.ids[0]
        default = first.status
    else:
        default = "estimated"
    return Measure(portions=((fid, raw.get("portion", "")),), status=raw.get("status", default))


def parse_vocabulary(data: dict, fdc: dict | None) -> Vocabulary:
    """A Vocabulary, or VocabularyError naming every problem. With `fdc` (the
    pinned subsets merged), every FDC id and portion label is checked against it."""
    problems: list[str] = []

    def name_ok(where, value) -> bool:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            problems.append(f"{where}: a name must be a non-empty string without surrounding spaces")
            return False
        if any(c in value for c in UNSAFE_EXACT_MATCH_CHARS):
            problems.append(f"{where} {value!r}: a name cannot hold a comma or a semicolon")
            return False
        return True

    source_cfg = data.get("source") or {}
    subsets = source_cfg.get("subsets", [source_cfg["subset"]] if "subset" in source_cfg else None)
    if not subsets or not all(isinstance(s, str) for s in subsets):
        problems.append("[source] subsets must list the pinned FDC files")
        subsets = []

    def named(key: str) -> tuple[Named, ...]:
        items = []
        for i, raw in enumerate(data.get(key, []), 1):
            if name_ok(f"{key} {i}", raw.get("name")):
                items.append(Named(raw["name"], raw.get("parent")))
        names = {m.name for m in items}
        for m in items:
            if m.parent is not None and m.parent not in names:
                problems.append(f"{key} {m.name!r}: parent {m.parent!r} is not in the file")
        return tuple(items)

    methods, equipment = named("method"), named("equipment")

    foods = []
    allowed = {"name", "parent", "fdc", "proxy", "sources", "each", "volume", "note"}
    for i, raw in enumerate(data.get("food", []), 1):
        where = f"food {i}"
        for key in sorted(set(raw) - allowed):
            problems.append(f"{where}: unknown key {key!r}")
        if not name_ok(where, raw.get("name")):
            continue
        where = f"food {raw['name']!r}"
        sources = []
        if "fdc" in raw:
            sources.append(Source((raw["fdc"],), "estimated" if raw.get("proxy") else "sourced"))
        elif raw.get("proxy"):
            problems.append(f"{where}: a proxy needs an fdc id")
        for j, s in enumerate(raw.get("sources", []), 1):
            parsed = _source(s, f"{where} source {j}", problems)
            if parsed:
                sources.append(parsed)
        first = sources[0] if sources else None
        each = _measure(raw.get("each"), first, f"{where} each", False, problems)
        volume = _measure(raw.get("volume"), first, f"{where} volume", True, problems)
        food = Food(raw["name"], raw.get("parent", ROOT_FOOD), tuple(sources), each, volume)
        if fdc is not None:
            for fid in sorted(Vocabulary((), (food,), (), (), ()).ids()):
                if str(fid) not in fdc["foods"]:
                    problems.append(f"{where}: FDC {fid} is not in the pinned subsets (run tools/fdc_extract.py)")
            for label, m in (("each", each), ("volume", volume)):
                for fid, portion in (m.portions if m else ()):
                    if str(fid) in fdc["foods"] and _portion(fdc, fid, portion) is None:
                        problems.append(f"{where} {label}: FDC {fid} has no single portion {portion!r}")
                    if label == "volume" and volume_unit(portion) is None:
                        problems.append(f"{where}: portion {portion!r} does not start with a volume unit")
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
                problems.append(f"kept_in_cooking: FDC nutrient {nid} is not in the pinned subsets")
        seen: dict[str, str] = {}
        taken = set(names) | {m.name for m in methods} | {e.name for e in equipment}
        for nid, n in fdc["nutrients"].items():
            if nid in SKIPPED_NUTRIENTS:
                continue
            unit = FDC_UNITS.get(n["unit"].upper())
            if unit is None or unit.lower() not in NUTRIENT_UNITS:
                problems.append(f"FDC nutrient {nid} {n['name']!r} is in {n['unit']!r}, not a nutrient unit")
            name = nutrient_name(n["name"])
            if name in seen:
                problems.append(f"FDC nutrients {seen[name]} and {nid} would both be named {name!r}")
            seen[name] = nid
            if name in taken:
                problems.append(f"nutrient {name!r} has the same name as a food, method or equipment")
    if problems:
        raise VocabularyError(problems)
    return Vocabulary(tuple(subsets), tuple(foods), methods, equipment, tuple(kept), fdc)


def read_vocabulary(path: str, *, check_subset: bool = True) -> Vocabulary:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    fdc = None
    if check_subset:
        root = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        cfg = data.get("source") or {}
        subsets = []
        for rel in cfg.get("subsets", [cfg.get("subset", "")]):
            with open(os.path.join(root, rel)) as fh:
                subsets.append(json.load(fh))
        fdc = merge(subsets)
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


def _tree(sync: Sync, items, hierarchy_id: str) -> dict[str, str]:
    """Methods or equipment, parents first (the file lists parents before children)."""
    ids: dict[str, str] = {}
    for item in items:
        ids[item.name] = sync.ensure("DomainType", item.name, {
            "hierarchy": hierarchy_id, "isLookupBearing": True,
            "parent": ids.get(item.parent) if item.parent else None})
    return ids


def import_vocabulary(client, vocabulary: Vocabulary) -> dict[str, int]:
    """Write `vocabulary` (read with its pinned subsets). Returns what was done."""
    fdc = vocabulary.fdc
    sync = Sync(client)
    names = (FOOD_HIERARCHY, METHOD_HIERARCHY, NUTRIENT_HIERARCHY, EQUIPMENT_HIERARCHY)
    hierarchies = {h: _hierarchy(client, h) for h in names}

    problems = []
    for name, hierarchy in ([(f.name, FOOD_HIERARCHY) for f in vocabulary.foods] + [(ROOT_FOOD, FOOD_HIERARCHY)]
                            + [(m.name, METHOD_HIERARCHY) for m in vocabulary.methods]
                            + [(e.name, EQUIPMENT_HIERARCHY) for e in vocabulary.equipment]):
        row = sync.rows("DomainType").get(name)
        if row and (row.get("hierarchy") or {}).get("id") != hierarchies[hierarchy]:
            problems.append(f"{name!r} already exists outside the {hierarchy!r} hierarchy")
    in_file = {f.name for f in vocabulary.foods} | {ROOT_FOOD}
    for food in vocabulary.foods:
        if food.parent not in in_file and not sync.rows("DomainType").get(food.parent):
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

    _tree(sync, vocabulary.methods, hierarchies[METHOD_HIERARCHY])
    _tree(sync, vocabulary.equipment, hierarchies[EQUIPMENT_HIERARCHY])

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
        fid = food_ids[food.name]
        if food.fdc:
            sync.ensure("Identifier", f"{food.name} FDC ID", {
                "identifierValue": str(food.fdc), "identifierScheme": fdc_id_scheme, "denotesType": fid})
        for nid, (amount, status, source) in composition(fdc, food).items():
            nutrient = nutrient_name(fdc["nutrients"][nid]["name"])
            profile = f"{food.name} -- {nutrient} per 100 g"
            wanted_profiles.add(profile)
            sync.ensure("NutrientProfile", profile, {
                "isAbout": fid, "forNutrient": nutrient_ids[nid], "amount": round(amount, 6), "basis": "per_100g",
                "unit": FDC_UNITS[fdc["nutrients"][nid]["unit"].upper()], "provenance": status, "source": source})
        for kind, measure, unit, label in (("Density", food.volume, "g_per_mL", "density"),
                                           ("MassPerUnit", food.each, "g_per_each", "mass per each")):
            if measure is None:
                continue
            qty = sync.ensure("QuantitySpecification", f"{food.name} {label} value", {
                "value": round(measure_value(fdc, measure), 6), "unit": unit, "status": "default"})
            sync.ensure("DefaultSpecification", f"{food.name} {label}", {
                "forType": fid, "hasKind": kinds[kind], "hasValue": qty, "provenance": measure.status,
                "source": measure_source(fdc, measure)})
    mapped = {f.name for f in vocabulary.foods if f.sources}
    for profile in list(sync.rows("NutrientProfile").values()):
        if (profile.get("isAbout") or {}).get("name") in mapped and profile["name"] not in wanted_profiles:
            sync.delete("NutrientProfile", profile)

    for nid in vocabulary.kept_in_cooking:
        nutrient = nutrient_name(fdc["nutrients"][nid]["name"])
        qty = sync.ensure("QuantitySpecification", f"Retention of {nutrient} in cooking value", {
            "value": 1.0, "unit": "ratio", "status": "default"})
        sync.ensure("DefaultSpecification", f"Retention of {nutrient} in cooking", {
            "forType": food_ids[ROOT_FOOD], "hasKind": kinds["RetentionFactor"], "hasValue": qty,
            "keyedBy": [nutrient_ids[nid]], "provenance": "estimated",
            "source": "the owner's decision of 2026-09-26: kept through cooking, as in USDA recipe calculations"})
    return sync.counts
