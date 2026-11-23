"""What foods are sold in: package sizes as defaults, the owner's own, and the packages a need takes.

The owner's request (2026-10-31): "This application needs to be aware of the amount that ingredients
are sold in." A package size is a DefaultSpecification of the kind the model has named since
`scripts/05` and nothing used, PurchaseQuantity (data-model.md Sec 8, J24 (5)), on a Type in the
"Package Reference" hierarchy, keyed by a food Type, as a price is on a Price Reference level
(mealplanner/prices.py, docs/prices.md). Its value is a QuantitySpecification in the unit the
package is sold in (14.5 oz, 32 fl_oz, 12 each), converted to grams where it is read, with the
food's density or weight per item. The levels, each a child of the one before:

  US supermarket                  common U.S. supermarket sizes (data/packages.toml): counted from FDC
                                  Branded Foods where a food has a rule (apply_pin), else estimated
    Home packages                 the owner's own (private/packages.toml, instantiate_packages)

A food may be sold in several sizes (a 14.5 oz and a 28 oz can of tomatoes), so a level holds one
default per size, named "<level> -- <food> -- <label>". Several defaults of one kind with one key on
one Type are what defaults.resolve_all refuses as ambiguous, so sizes are resolved here instead: the
nearest level that gives a food any size gives all of its sizes, and a food with none takes its
nearest ancestor food's, as a price does. A food no level gives a size is bought as much as is
needed: loose produce, a deli counter.

What a need takes (choose): the whole packages that leave least over, then the fewest packages,
then the fewest of the sizes listed first. A food the recipes count (eggs, tortillas) with no
package size is bought in whole items. What is left over is reported; the planner weighs what a week
leaves to spoil only when the week file asks (Weights.package_waste, planning/evaluate.package_leftovers).
"""

from __future__ import annotations

import json
import math
import os
import tomllib
from dataclasses import dataclass, replace

from mealplanner import fdc_packages

from mealplanner.profiles import ProfileError, Report, _name_ok, _one_id, check_level, food_types
from mealplanner.typetree import ancestors_or_self
from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from mealplanner.vocabulary_import import Sync

PACKAGES = "data/packages.toml"
PACKAGE_HIERARCHY = "Package Reference"
PACKAGE_KIND = "PurchaseQuantity"
PUBLIC_LEVEL = "US supermarket"
HOME_LEVEL = "Home packages"
PUBLIC_SOURCE = "a common U.S. supermarket size (data/packages.toml), estimated: not checked against a store's shelf"
MAX_SIZES = 4
SLACK = 1e-6            # a need this much over a package (relative) is still one package: rounding in conversions


@dataclass(frozen=True)
class Size:
    amount: float
    unit: str
    label: str
    source: str = ""                # where this size comes from, when not the level's own source


@dataclass(frozen=True)
class Entry:
    food: str
    sizes: tuple[Size, ...]
    note: str = ""
    fdc: dict | None = None         # the rule that counts this food's sizes in FDC Branded Foods
    provenance: str = ""            # when not the level's own: "sourced" for sizes counted from FDC


def size_label(amount: float, unit: str) -> str:
    return f"{amount:g} {unit.replace('_', ' ')}"


def _sizes(where: str, raw, problems: list[str]) -> tuple[Size, ...]:
    """`sizes = [[amount, unit], [amount, unit, label], ...]`: one to MAX_SIZES, each label once."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_SIZES:
        problems.append(f"{where}: sizes must list 1 to {MAX_SIZES} sizes, each [amount, unit] or [amount, unit, label]")
        return ()
    out, labels = [], set()
    for size in raw:
        if not isinstance(size, list) or len(size) not in (2, 3) or not isinstance(size[0], (int, float)) \
                or isinstance(size[0], bool) or not math.isfinite(size[0]) or size[0] <= 0 or not isinstance(size[1], str) \
                or size[1].strip().lower() not in UNIT_TABLE or (len(size) == 3 and not _name_ok(f"{where} label", size[2], [])):
            problems.append(f"{where}: {size!r} is not [amount above 0, a unit the unit table knows] with an optional "
                            "label (no comma or semicolon)")
            continue
        unit = size[1].strip().lower()
        label = size[2] if len(size) == 3 else size_label(float(size[0]), unit)
        if label in labels:
            problems.append(f"{where}: two sizes are labelled {label!r}")
        labels.add(label)
        out.append(Size(float(size[0]), unit, label))
    return tuple(out)


def parse_packages(data: dict) -> tuple[Entry, ...]:
    """data/packages.toml, or ProfileError naming every problem."""
    problems: list[str] = []
    entries, seen = [], set()
    rows = data.get("package")
    if set(data) != {"package"} or not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        # loading removes what the file does not name, so a file read as empty empties the whole level
        raise ProfileError([f"{PACKAGES} is [[package]] tables and nothing else, at least one"])
    for i, raw in enumerate(rows, 1):
        where = f"package {i}"
        if not _name_ok(where, raw.get("food"), problems):
            continue
        where = f"package {i} ({raw['food']!r})"
        unknown = set(raw) - {"food", "sizes", "note", "fdc"}
        if unknown:
            problems.append(f"{where}: unknown key(s) {sorted(unknown)}")
        if raw["food"] in seen:
            problems.append(f"{where}: listed twice")
        seen.add(raw["food"])
        sizes = _sizes(where, raw.get("sizes"), problems)
        rule = fdc_packages.parse_rule(where, raw["fdc"], problems) if "fdc" in raw else None
        if rule and sizes and UNIT_TABLE[sizes[0].unit][0] == "count":
            problems.append(f"{where}: a food sold by count has no FDC rule (labels give weights, not counts)")
        entries.append(Entry(raw["food"], sizes, raw.get("note", ""), rule))
    if problems:
        raise ProfileError(problems)
    return tuple(entries)


def read_packages(root: str) -> tuple[Entry, ...]:
    with open(os.path.join(root, PACKAGES), "rb") as fh:
        return parse_packages(tomllib.load(fh))


def read_pin(root: str) -> dict:
    """data/packages/fdc.json (tools/package_extract.py), or an empty pin if there is none yet."""
    path = os.path.join(root, fdc_packages.PIN)
    if not os.path.exists(path):
        return {"source": {}, "foods": {}}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _ounces(size: Size) -> float:
    kind, factor = UNIT_TABLE[size.unit]
    return size.amount * factor / (fdc_packages.OZ_G if kind == "mass" else fdc_packages.FLOZ_ML)


def apply_pin(entries: tuple[Entry, ...], pin: dict) -> tuple[Entry, ...]:
    """Each food with an FDC rule takes its common sizes from the pin, `sourced`, in the kind of unit
    its estimate is in (oz, or lb for whole pounds from 2 lb; fl_oz for a food sold by volume). A
    size within 2% of an estimated one is that size, with its figure and label ("500 mL bottle",
    16.9 fl_oz, where the count's quarter ounce says 17). A food whose count does
    not stand (fdc_packages.common_sizes) keeps its estimate. ProfileError if a food's rule is not
    the one its count was made with: run tools/package_extract.py again."""
    problems, out = [], []
    release = pin.get("source", {}).get("release", "")
    for e in entries:
        if not e.fdc:
            out.append(e)
            continue
        count = pin.get("foods", {}).get(e.food)
        if count is None or count.get("rule") != e.fdc:
            problems.append(f"{e.food!r}: its FDC rule is not the one {fdc_packages.PIN} was counted with "
                            "(run tools/package_extract.py)")
            continue
        common = fdc_packages.common_sizes(count)
        if not common:
            out.append(replace(e, note=(f"{e.note}; " if e.note else "") + f"{fdc_packages.DATASET} has too few "
                               f"products to count ({count['products']} from {count['owners']} brand owners)"))
            continue
        volume = UNIT_TABLE[e.sizes[0].unit][0] == "volume"
        nearest: dict[float, Size] = {}         # an FDC size -> the estimated size nearest it, within 2%
        for est in e.sizes:
            close = [c[0] for c in common if abs(c[0] - _ounces(est)) <= 0.02 * _ounces(est)]
            if close:
                ounces = min(close, key=lambda oz: abs(oz - _ounces(est)))
                if ounces not in nearest or abs(_ounces(est) - ounces) < abs(_ounces(nearest[ounces]) - ounces):
                    nearest[ounces] = est
        sizes, labels = [], set()
        for ounces, share, products, owners in common:
            if ounces in nearest:               # the same size, as the estimate printed it: "500 mL bottle", 16.9 fl_oz
                amount, unit, label = nearest[ounces].amount, nearest[ounces].unit, nearest[ounces].label
            else:
                if volume:
                    amount, unit = ounces, "fl_oz"
                elif ounces >= 32 and ounces % 16 == 0:
                    amount, unit = ounces / 16, "lb"
                else:
                    amount, unit = ounces, "oz"
                label = size_label(amount, unit)
            if label in labels:
                continue
            labels.add(label)
            sizes.append(Size(amount, unit, label, fdc_packages.describe_share(release, count, share, products, owners)))
        out.append(replace(e, sizes=tuple(sizes), provenance="sourced"))
    if problems:
        raise ProfileError(problems)
    return tuple(out)


def check_against_vocabulary(entries: tuple[Entry, ...], vocabulary: dict) -> list[str]:
    """What the file asks that data/vocabulary.toml cannot give, without an instance: a food it
    does not have, a size by volume for a food with no density, or by count for one with no
    weight per item (each looked for up the food's parents, as a default is resolved)."""
    foods = {f["name"]: f for f in vocabulary.get("food", [])}
    problems = []

    def has(name: str, key: str) -> bool:
        seen = set()
        while name in foods and name not in seen:
            seen.add(name)
            if foods[name].get(key) is not None:
                return True
            name = foods[name].get("parent", "Food")
        return False
    for e in entries:
        if e.food not in foods:
            problems.append(f"{e.food!r} is not a food in the vocabulary")
            continue
        for s in e.sizes:
            kind = UNIT_TABLE[s.unit][0]
            if kind == "volume" and not has(e.food, "volume"):
                problems.append(f"{e.food!r}: {s.label} is a volume, and the food has no density: give a mass")
            if kind == "count" and not has(e.food, "each"):
                problems.append(f"{e.food!r}: {s.label} is a count, and the food has no weight per item: give a mass")
    return problems


# -- loading -------------------------------------------------------------------------

def _write_level(client, sync: Sync, level: str, level_id: str, kind: str, rows: list[tuple[Entry, str]], foods: dict,
                 status: str, provenance: str, source) -> list[str]:
    """Each size of each (entry, source note) as a default on `level`; prune the rest. Returns what it wrote."""
    written = []
    for e, note in rows:
        for s in e.sizes:
            label = f"{level} -- {e.food} -- {s.label}"
            qty = sync.ensure("QuantitySpecification", f"{label} size", {"value": s.amount, "unit": s.unit, "status": status})
            grams = convert_to_grams(client, foods[e.food], s.amount, s.unit)
            sync.ensure("DefaultSpecification", label, {
                "forType": level_id, "hasKind": kind, "hasValue": qty, "keyedBy": [foods[e.food]],
                "provenance": e.provenance or provenance,
                "source": f"{s.source or source}: {s.amount:g} {s.unit} = {grams:g} g" + (f"; {note}" if note else "")})
            written.append(label)
    return written


def _problems_converting(client, entries, foods: dict) -> list[str]:
    problems = []
    for e in entries:
        if e.food not in foods:
            problems.append(f"{e.food!r} is not a food in the vocabulary")
            continue
        for s in e.sizes:
            if not convert_to_grams(client, foods[e.food], s.amount, s.unit):
                need = "weight per item" if UNIT_TABLE[s.unit][0] == "count" else "density"
                problems.append(f"{e.food!r}: {s.label} does not convert to grams (the food has no {need})")
    return problems


def import_packages(client, entries: tuple[Entry, ...]) -> dict[str, int]:
    """Write the public level (idempotent). A size the file no longer names is removed. The vocabulary
    must be loaded first: foods are looked up, never created."""
    foods = food_types(client)
    problems = _problems_converting(client, entries, foods)
    if problems:
        raise ProfileError(sorted(set(problems)))
    sync = Sync(client)
    hierarchy = sync.ensure("TypeHierarchy", PACKAGE_HIERARCHY, {"singleParent": True})
    kind = sync.ensure("DomainType", PACKAGE_KIND, {"hierarchy": _one_id(client, "TypeHierarchy", "Default Kind")})
    level = sync.ensure("DomainType", PUBLIC_LEVEL, {"hierarchy": hierarchy, "isLookupBearing": True, "parent": None})
    written = _write_level(client, sync, PUBLIC_LEVEL, level, kind, [(e, e.note) for e in entries], foods, "default", "estimated",
                           PUBLIC_SOURCE)
    _prune(client, sync, level, kind, set(written))
    return sync.counts


def _prune(client, sync: Sync, level_id: str, kind_id: str, keep: set) -> list[str]:
    """Remove the package sizes on a level that are not in `keep`."""
    removed = []
    for ref in client.get_all("DomainType", level_id)["result"].get("defaultSpecifications", []):
        spec = client.get_all("DefaultSpecification", ref["id"])["result"]
        if (spec.get("hasKind") or {}).get("id") != kind_id or spec["name"] in keep:
            continue
        value = spec.get("hasValue")
        sync.delete("DefaultSpecification", spec)
        if value:
            sync.delete("QuantitySpecification", client.get_all("QuantitySpecification", value["id"])["result"])
        removed.append(spec["name"])
    return removed


def instantiate_packages(client, selection: dict) -> Report:
    """The owner's package level from their selection file:

        name = "Home packages"
        profile = "US supermarket"             # the level to fall back on
        [own]                                  # what the owner's shops sell
        "Olive oil" = { sizes = [[1, "l"]], note = "Costco" }

    The level is a Type below the chosen one, so a food it gives sizes replaces that food's sizes
    there, and every other food falls back. An owner's size is `specified` and `sourced`, and names
    the file. One the file no longer has is removed."""
    report = Report()
    problems: list[str] = []
    name = selection.get("name", HOME_LEVEL)
    if not _name_ok("name", name, problems):
        raise ProfileError(problems)
    if name == PUBLIC_LEVEL:
        raise ProfileError([f"name: {name!r} is the public level; give the owner's level its own name"])
    parent = _one_id(client, "DomainType", selection.get("profile", PUBLIC_LEVEL))
    kind = _one_id(client, "DomainType", PACKAGE_KIND)
    hierarchy = _one_id(client, "TypeHierarchy", PACKAGE_HIERARCHY)
    if parent is None or kind is None or hierarchy is None:
        raise ProfileError([f"no package level {selection.get('profile', PUBLIC_LEVEL)!r} (load the public sizes with "
                            "tools/import_packages.py)"])
    check_level(client, selection, PACKAGE_HIERARCHY, name, parent)
    own = []
    for food, raw in selection.get("own", {}).items():
        where = f"own {food!r}"
        unknown = set(raw) - {"sizes", "note"} if isinstance(raw, dict) else {"(not a table)"}
        if unknown:
            problems.append(f"{where}: unknown key(s) {sorted(unknown)}")
            continue
        own.append(Entry(food, _sizes(where, raw.get("sizes"), problems), raw.get("note", "")))
    foods = food_types(client)
    problems += _problems_converting(client, own, foods)
    if problems:
        raise ProfileError(problems)
    sync = Sync(client)
    level = sync.ensure("DomainType", name, {"hierarchy": hierarchy, "isLookupBearing": True, "parent": parent})
    report.written = _write_level(client, sync, name, level, kind, [(e, e.note) for e in own], foods, "specified", "sourced",
                                  "the owner's package size (private/packages.toml)")
    report.removed = _prune(client, sync, level, kind, set(report.written))
    report.counts = sync.counts
    return report


# -- reading ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Package:
    amount: float
    unit: str
    label: str
    level: str                      # the level it was found on
    estimated: bool


def default_level(client) -> str | None:
    """The owner's level where there is one, else the public one, else None (none loaded)."""
    for name in (HOME_LEVEL, PUBLIC_LEVEL):
        if _one_id(client, "DomainType", name) is not None:
            return name
    return None


def package_table(client, level_name: str) -> dict[str, tuple[Package, ...]]:
    """Food Type id -> the sizes it is sold in, seen from a level: the nearest level that gives the
    food any size gives all of them, ordered by the default's name: stable, and not the file's order,
    which the graph does not keep."""
    level = _one_id(client, "DomainType", level_name)
    kind = _one_id(client, "DomainType", PACKAGE_KIND)
    if level is None or kind is None:
        raise ProfileError([f"no package level {level_name!r}"])
    table: dict[str, tuple[Package, ...]] = {}
    for level_type in ancestors_or_self(client, level):
        node = client.get_all("DomainType", level_type)["result"]
        here: dict[str, list[tuple[str, Package]]] = {}
        for ref in node.get("defaultSpecifications", []):
            spec = client.get_all("DefaultSpecification", ref["id"])["result"]
            if (spec.get("hasKind") or {}).get("id") != kind or len(spec.get("keyedBy") or []) != 1 or not spec.get("hasValue"):
                continue
            food = spec["keyedBy"][0]
            qty = client.get_all("QuantitySpecification", spec["hasValue"]["id"])["result"]
            prefix = f"{node['name']} -- {food.get('name')} -- "
            label = spec["name"][len(prefix):] if spec["name"].startswith(prefix) else size_label(qty["value"], qty["unit"])
            here.setdefault(food["id"], []).append((spec["name"], Package(
                float(qty["value"]), qty["unit"], label, node["name"], spec.get("provenance") == "estimated")))
        for food_id, sizes in here.items():
            if food_id not in table:
                table[food_id] = tuple(p for _, p in sorted(sizes, key=lambda kv: kv[0]))
    return table


def food_packages(client, table: dict, food_id: str) -> tuple[Package, ...]:
    """The sizes a food is sold in, or its nearest ancestor food's; () if none is given any."""
    for type_id in ancestors_or_self(client, food_id):
        if type_id in table:
            return table[type_id]
    return ()


def choose(sizes: list[float], need: float) -> tuple[int, ...]:
    """How many of each size (grams, in order) to buy for `need` grams: the counts that leave least
    over, then the fewest packages, then the smallest counts of the sizes listed first. The last
    size takes whatever the others leave, so the search is over the others' counts only.
    Mirrored by pages/lib/90_shopping.js (choosePackages); compared by tools/check_pages.py."""
    if need <= 0 or not sizes:
        return tuple(0 for _ in sizes)
    target = need * (1 - SLACK)
    best, best_key = None, None

    def visit(i: int, counts: list[int], total: float) -> None:
        nonlocal best, best_key
        if i == len(sizes) - 1:
            last = max(0, math.ceil((target - total) / sizes[i]))
            full = counts + [last]
            bought = total + last * sizes[i]
            key = (math.floor((bought - need) * 1e6 + 0.5), sum(full), tuple(full))
            if best_key is None or key < best_key:
                best, best_key = tuple(full), key
            return
        for n in range(0, max(0, math.ceil((target - total) / sizes[i])) + 1):
            visit(i + 1, counts + [n], total + n * sizes[i])
    visit(0, [], 0.0)
    return best
