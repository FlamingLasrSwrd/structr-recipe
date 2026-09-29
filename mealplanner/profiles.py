"""Profiles: patterns defined once on a Type and instantiated into the owner's own data.

A profile is a Type in its own hierarchy ("Dietary Reference Profile", "Kitchen
Profile", "Pantry Profile") carrying DefaultSpecifications keyed by what they
are about: a nutrient, an equipment type, a food. A child profile inherits its parent's and
overrides any it restates (defaults.resolve_all). Instantiating one copies the
resolved pattern into the owner's data, where it is theirs to change:

  a dietary profile  -> the owner's standing NutritionTargets, one per nutrient,
                        daily; their range's status is `default`, or `specified`
                        where the owner's selection file overrides it
  a kitchen profile  -> the owner's kitchen, a UtensilSet whose members
                        (`has member part`) are EquipmentObjects, one per item
  a pantry profile   -> the owner's stock on hand: a PortionOfSubstance per food,
                        with an `imputed` Measurement of its amount (Sec 4.1), an
                        assumption until a weighing replaces it

The owner's choices live in a selection file in private/ (the profile, and what
to add, remove or override), so instantiating again reproduces them. A target
the owner changed in Structr is not overwritten unless asked (reset), and a
piece of equipment or stock with a history is never deleted. The mechanism and
its other uses: docs/profiles.md, data-model.md Sec 18 J22.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from mealplanner.defaults import resolve_all
from mealplanner.nutrition_scope import convert_nutrient, day_zone, nutrient_unit
from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from mealplanner.vocabulary_import import FOOD_HIERARCHY, Sync
from structr_client.client import UNSAFE_EXACT_MATCH_CHARS

DIETARY = "data/profiles/dietary.toml"
KITCHEN = "data/profiles/kitchen.toml"
PANTRY = "data/profiles/pantry.toml"
DIET_HIERARCHY = "Dietary Reference Profile"
KITCHEN_HIERARCHY = "Kitchen Profile"
PANTRY_HIERARCHY = "Pantry Profile"
BASIS_HIERARCHY = "Intake Basis"
EQUIPMENT_HIERARCHY = "Equipment Type"
INTAKE_KIND = "Recommended Daily Intake"
EQUIPMENT_KIND = "Kitchen Equipment"
STOCK_KIND = "Pantry Stock"
STRUCTR_TIME = "%Y-%m-%dT%H:%M:%S+0000"
SHARE, PER_1000 = "share of energy", "per 1000 kcal"
BASIS_TYPES = {SHARE: "Share of energy", PER_1000: "Per 1000 kcal"}
ENERGY = "1008"
# kcal per gram, for a share of energy (Atwater general factors)
KCAL_PER_G = {"1003": 4.0, "1005": 4.0, "2000": 4.0, "1235": 4.0, "1004": 9.0, "1258": 9.0, "1269": 9.0, "1270": 9.0}
STATUSES = ("sourced", "estimated", "calculated")


class ProfileError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


# -- definitions -----------------------------------------------------------

@dataclass(frozen=True)
class Intake:
    nutrient: str                 # FDC nutrient id
    basis: str                    # "amount", SHARE or PER_1000
    minimum: float | None
    maximum: float | None
    unit: str | None              # for an amount or per 1000 kcal
    status: str
    source: str


@dataclass(frozen=True)
class Item:
    equipment: str                # an Equipment Type name
    count: int


@dataclass(frozen=True)
class Stock:
    food: str                     # a Food Type name
    amount: float
    unit: str                     # any unit_conversion.UNIT_TABLE knows


@dataclass(frozen=True)
class Profile:
    name: str
    parent: str | None
    intakes: tuple[Intake, ...] = ()
    items: tuple[Item, ...] = ()
    note: str = ""
    stock: tuple[Stock, ...] = ()


def _name_ok(where, value, problems) -> bool:
    if not isinstance(value, str) or not value.strip() or value != value.strip() \
            or any(c in value for c in UNSAFE_EXACT_MATCH_CHARS):
        problems.append(f"{where}: a name must be a non-empty string with no comma or semicolon")
        return False
    return True


def _amount(where, entry, problems) -> tuple[float, str] | None:
    """An item's amount and unit: a number above 0 in a unit the unit table knows."""
    amount, unit = entry.get("amount"), entry.get("unit")
    ok = True
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
        problems.append(f"{where}: amount must be a number above 0, not {amount!r}")
        ok = False
    if not isinstance(unit, str) or unit.strip().lower() not in UNIT_TABLE:
        problems.append(f"{where}: unit {unit!r} is not one of {', '.join(UNIT_TABLE)}")
        ok = False
    return (float(amount), unit.strip().lower()) if ok else None


def parse_profiles(data: dict, kind: str) -> tuple[Profile, ...]:
    """Profiles from a dietary ("dietary"), kitchen ("kitchen") or pantry ("pantry")
    file, or ProfileError naming every problem. Parents must come before children."""
    if kind not in ("dietary", "kitchen", "pantry"):
        raise ValueError(f"no profile kind {kind!r}")
    problems: list[str] = []
    profiles: list[Profile] = []
    seen: set[str] = set()
    for i, raw in enumerate(data.get("profile", []), 1):
        if not _name_ok(f"profile {i}", raw.get("name"), problems):
            continue
        name, parent = raw["name"], raw.get("parent")
        where = f"profile {name!r}"
        if name in seen:
            problems.append(f"{where} is listed twice")
        if parent is not None and parent not in seen:
            problems.append(f"{where}: parent {parent!r} must be listed before it")
        seen.add(name)
        intakes, items, stock = [], [], []
        if kind == "dietary":
            keys = set()
            for j, it in enumerate(raw.get("intakes", []), 1):
                iw = f"{where} intake {j}"
                basis = it.get("basis", "amount")
                if basis not in ("amount", SHARE, PER_1000):
                    problems.append(f"{iw}: basis must be amount, {SHARE!r} or {PER_1000!r}")
                    continue
                nid = str(it.get("nutrient", ""))
                lo, hi = it.get("min"), it.get("max")
                if lo is None and hi is None:
                    problems.append(f"{iw}: give min, max or both")
                if lo is not None and hi is not None and lo > hi:
                    problems.append(f"{iw}: min {lo} is above max {hi}")
                unit = it.get("unit")
                if basis == SHARE:
                    if nid not in KCAL_PER_G:
                        problems.append(f"{iw}: no kcal-per-gram factor for FDC nutrient {nid}, so no share of energy")
                    if unit is not None:
                        problems.append(f"{iw}: a share of energy is a percent and takes no unit")
                else:
                    try:
                        nutrient_unit(unit, iw)
                    except ValueError as exc:
                        problems.append(str(exc))
                status = it.get("status", "sourced")
                if status not in STATUSES:
                    problems.append(f"{iw}: status must be one of {', '.join(STATUSES)}")
                if not it.get("source"):
                    problems.append(f"{iw}: every intake names its source")
                if (nid, basis) in keys:
                    problems.append(f"{iw}: FDC nutrient {nid} with basis {basis!r} is listed twice")
                keys.add((nid, basis))
                intakes.append(Intake(nid, basis, lo, hi, unit, status, it.get("source", "")))
        elif kind == "kitchen":
            names = set()
            for j, it in enumerate(raw.get("equipment", []), 1):
                iw = f"{where} item {j}"
                if not _name_ok(iw, it.get("item"), problems):
                    continue
                count = it.get("count", 1)
                if not isinstance(count, int) or count < 1:
                    problems.append(f"{iw}: count is a whole number from 1")
                if it["item"] in names:
                    problems.append(f"{iw}: {it['item']!r} is listed twice")
                names.add(it["item"])
                items.append(Item(it["item"], count))
        else:
            names = set()
            for j, it in enumerate(raw.get("stock", []), 1):
                iw = f"{where} item {j}"
                if not _name_ok(iw, it.get("item"), problems):
                    continue
                if it["item"] in names:
                    problems.append(f"{iw}: {it['item']!r} is listed twice")
                names.add(it["item"])
                amount = _amount(iw, it, problems)
                if amount:
                    stock.append(Stock(it["item"], *amount))
        profiles.append(Profile(name, parent, tuple(intakes), tuple(items), raw.get("note", ""), tuple(stock)))
    if problems:
        raise ProfileError(problems)
    return tuple(profiles)


def read_profiles(root: str) -> tuple[tuple[Profile, ...], tuple[Profile, ...], tuple[Profile, ...]]:
    """(dietary, kitchen, pantry) profiles from data/profiles/."""
    out = []
    for rel, kind in ((DIETARY, "dietary"), (KITCHEN, "kitchen"), (PANTRY, "pantry")):
        with open(os.path.join(root, rel), "rb") as fh:
            out.append(parse_profiles(tomllib.load(fh), kind))
    return out[0], out[1], out[2]


def _one_id(client, type_name: str, name: str) -> str | None:
    rows = client.get(f"/structr/rest/{type_name}", params={"name": name})["result"]
    if len(rows) > 1:
        raise ProfileError([f"{len(rows)} {type_name} nodes are named {name!r}"])
    return rows[0]["id"] if rows else None


def nutrient_types(client) -> dict[str, tuple[str, str]]:
    """FDC nutrient id -> (Nutrient Type id, name), from the vocabulary's Identifiers."""
    out = {}
    for ident in client.get_all("Identifier")["result"]:
        target = ident.get("denotesType")
        if target and (ident.get("identifierScheme") or {}).get("name") == "FDC nutrient id":
            out[str(ident.get("identifierValue"))] = (target["id"], target["name"])
    return out


def food_types(client) -> dict[str, str]:
    """Food Type name -> id, every Type in the vocabulary's Food Identity hierarchy."""
    return {row["name"]: row["id"] for row in Sync(client).rows("DomainType").values()
            if (row.get("hierarchy") or {}).get("name") == FOOD_HIERARCHY}


def _unconvertible(client, food_id: str, food: str, amount: float, unit: str) -> str | None:
    """Why an amount of a food cannot be counted in grams, or None if it can. Stock is
    counted in grams (invariant 13), so a volume needs the food's density and `each`
    its weight per item, from the vocabulary."""
    if convert_to_grams(client, food_id, amount, unit) is not None:
        return None
    need = "weight per item" if UNIT_TABLE[unit][0] == "count" else "density"
    return f"{amount:g} {unit} of {food!r} does not convert to grams: the vocabulary gives it no {need}; give a mass"


def import_profiles(client, dietary: tuple[Profile, ...], kitchen: tuple[Profile, ...],
                    pantry: tuple[Profile, ...] = ()) -> dict[str, int]:
    """Write the profile definitions (idempotent). The vocabulary must be loaded
    first: nutrients, equipment types and foods are looked up, never created here."""
    sync = Sync(client)
    nutrients = nutrient_types(client)
    problems = []
    for p in dietary:
        for it in p.intakes:
            if it.nutrient not in nutrients:
                problems.append(f"profile {p.name!r}: FDC nutrient {it.nutrient} is not in the vocabulary")
    equipment = {row["name"]: row["id"] for row in sync.rows("DomainType").values()
                 if (row.get("hierarchy") or {}).get("name") == EQUIPMENT_HIERARCHY}
    for p in kitchen:
        for item in p.items:
            if item.equipment not in equipment:
                problems.append(f"profile {p.name!r}: equipment {item.equipment!r} is not in the vocabulary")
    foods = food_types(client) if pantry else {}
    for p in pantry:
        for st in p.stock:
            if st.food not in foods:
                problems.append(f"profile {p.name!r}: food {st.food!r} is not in the vocabulary")
                continue
            why = _unconvertible(client, foods[st.food], st.food, st.amount, st.unit)
            if why:
                problems.append(f"profile {p.name!r}: {why}")
    if problems:
        raise ProfileError(problems)

    hierarchies = {h: sync.ensure("TypeHierarchy", h, {"singleParent": True})
                   for h in (DIET_HIERARCHY, KITCHEN_HIERARCHY, BASIS_HIERARCHY)
                   + ((PANTRY_HIERARCHY,) if pantry else ())}
    default_kind = _one_id(client, "TypeHierarchy", "Default Kind")
    kinds = {k: sync.ensure("DomainType", k, {"hierarchy": default_kind})
             for k in (INTAKE_KIND, EQUIPMENT_KIND) + ((STOCK_KIND,) if pantry else ())}
    bases = {b: sync.ensure("DomainType", name, {"hierarchy": hierarchies[BASIS_HIERARCHY], "isLookupBearing": True})
             for b, name in BASIS_TYPES.items()}

    for profiles, hierarchy in ((dietary, DIET_HIERARCHY), (kitchen, KITCHEN_HIERARCHY), (pantry, PANTRY_HIERARCHY)):
        ids: dict[str, str] = {}
        for p in profiles:
            ids[p.name] = sync.ensure("DomainType", p.name, {
                "hierarchy": hierarchies[hierarchy], "isLookupBearing": True,
                "parent": ids[p.parent] if p.parent else None})
            for it in p.intakes:
                nid, nname = nutrients[it.nutrient]
                label = f"{p.name} -- {nname}" + ("" if it.basis == "amount" else f" ({it.basis})")
                unit = "percent_of_energy" if it.basis == SHARE else \
                    (f"{it.unit}_per_1000_kcal" if it.basis == PER_1000 else it.unit)
                qty = sync.ensure("QuantitySpecification", f"{label} value", {
                    "minValue": it.minimum, "maxValue": it.maximum, "unit": unit, "status": "default"})
                keys = [nid] + ([bases[it.basis]] if it.basis != "amount" else [])
                sync.ensure("DefaultSpecification", label, {
                    "forType": ids[p.name], "hasKind": kinds[INTAKE_KIND], "hasValue": qty, "keyedBy": keys,
                    "provenance": it.status, "source": it.source})
            for item in p.items:
                label = f"{p.name} -- {item.equipment}"
                qty = sync.ensure("QuantitySpecification", f"{label} count", {
                    "value": float(item.count), "unit": "each", "status": "default"})
                sync.ensure("DefaultSpecification", label, {
                    "forType": ids[p.name], "hasKind": kinds[EQUIPMENT_KIND], "hasValue": qty,
                    "keyedBy": [equipment[item.equipment]], "provenance": "estimated",
                    "source": f"kitchen profile {p.name!r} in data/profiles/kitchen.toml, curated (see its header)"})
            for st in p.stock:
                label = f"{p.name} -- {st.food}"
                qty = sync.ensure("QuantitySpecification", f"{label} amount", {
                    "value": st.amount, "unit": st.unit, "status": "default"})
                sync.ensure("DefaultSpecification", label, {
                    "forType": ids[p.name], "hasKind": kinds[STOCK_KIND], "hasValue": qty,
                    "keyedBy": [foods[st.food]], "provenance": "estimated",
                    "source": f"pantry profile {p.name!r} in data/profiles/pantry.toml, curated (see its header)"})
    return sync.counts


# -- resolving a profile ---------------------------------------------------

@dataclass
class TargetSpec:
    nutrient_id: str              # Nutrient Type id
    nutrient: str                 # its name
    minimum: float | None
    maximum: float | None
    unit: str
    status: str                   # sourced, calculated or estimated
    sources: list[str] = field(default_factory=list)


def _rank(statuses) -> str:
    return "estimated" if "estimated" in statuses else "calculated" if "calculated" in statuses else "sourced"


def dietary_targets(client, profile_name: str) -> list[TargetSpec]:
    """The daily targets a dietary profile resolves to, one per nutrient. For a
    nutrient with several goals (an RDA in grams and an AMDR share of energy),
    the minimum is the greatest floor and the maximum the smallest ceiling. A
    share of energy or an amount per 1000 kcal is worked out from the profile's
    energy (the middle of its range), which makes the figure `calculated`."""
    profile_id = _one_id(client, "DomainType", profile_name)
    kind_id = _one_id(client, "DomainType", INTAKE_KIND)
    if profile_id is None or kind_id is None:
        raise ProfileError([f"no dietary profile {profile_name!r} (load it with tools/import_profiles.py)"])
    resolved = resolve_all(client, profile_id, kind_id)
    basis_of = {}
    for basis, name in BASIS_TYPES.items():
        basis_of[_one_id(client, "DomainType", name)] = basis
    by_nutrient: dict[str, list] = {}
    for keys, default in resolved.items():
        basis_ids = [k for k in keys if k in basis_of]
        nutrient_ids = [k for k in keys if k not in basis_of]
        if len(nutrient_ids) != 1 or len(basis_ids) > 1:
            raise ProfileError([f"default {default.default_name!r} must be keyed by one nutrient and at most one basis"])
        basis = basis_of[basis_ids[0]] if basis_ids else "amount"
        by_nutrient.setdefault(nutrient_ids[0], []).append((basis, default.quantity, default.spec))

    index = nutrient_types(client)
    names = {type_id: name for type_id, name in index.values()}
    fdc_of = {type_id: fdc for fdc, (type_id, _) in index.items()}
    energy_id = index.get(ENERGY, (None, None))[0]
    energy = None
    if energy_id in by_nutrient:
        amounts = [q for basis, q, _ in by_nutrient[energy_id] if basis == "amount"]
        if len(amounts) != 1:
            raise ProfileError([f"profile {profile_name!r} needs exactly one energy amount"])
        q = amounts[0]
        lo, hi = q.get("minValue"), q.get("maxValue")
        energy = (lo + hi) / 2 if lo is not None and hi is not None else (lo if lo is not None else hi)
        energy = convert_nutrient(energy, q["unit"], "kcal")

    targets = []
    for nid, goals in by_nutrient.items():
        amount_units = [q["unit"] for basis, q, _ in goals if basis == "amount"]
        unit = amount_units[0] if amount_units else ("kcal" if nid == energy_id else "g")
        floors, ceilings, statuses, sources = [], [], [], []
        for basis, q, spec in goals:
            lo, hi = q.get("minValue"), q.get("maxValue")
            status = spec.get("provenance") or "estimated"
            text = spec.get("source") or spec["name"]
            if basis == "amount":
                factor = convert_nutrient(1.0, q["unit"], unit)
            else:
                if energy is None:
                    raise ProfileError([f"profile {profile_name!r} has a {basis} goal but no energy"])
                if basis == SHARE:
                    grams_per_percent = energy / 100.0 / KCAL_PER_G[fdc_of[nid]]
                    factor = convert_nutrient(grams_per_percent, "g", unit)
                    text += f"; {lo if lo is not None else ''}-{hi if hi is not None else ''}% of {energy:g} kcal at " \
                            f"{KCAL_PER_G[fdc_of[nid]]:g} kcal/g"
                else:
                    factor = convert_nutrient(energy / 1000.0, q["unit"].split("_per_")[0], unit)
                    text += f"; for {energy:g} kcal"
                status = "calculated" if status == "sourced" else status
            if factor is None:
                raise ProfileError([f"{spec['name']!r}: unit {q['unit']!r} does not convert to {unit!r}"])
            if lo is not None:
                floors.append(lo * factor)
            if hi is not None:
                ceilings.append(hi * factor)
            statuses.append(status)
            sources.append(text)
        lo, hi = (max(floors) if floors else None), (min(ceilings) if ceilings else None)
        if lo is not None and hi is not None and lo > hi:
            raise ProfileError([f"profile {profile_name!r}: the goals for {names[nid]!r} conflict ({lo:g} > {hi:g})"])
        targets.append(TargetSpec(nid, names[nid], _round(lo), _round(hi), unit, _rank(statuses), sources))
    return sorted(targets, key=lambda t: t.nutrient)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def kitchen_items(client, profile_name: str) -> dict[str, tuple[str, int]]:
    """Equipment Type id -> (name, how many) for a kitchen profile, inherited and overridden."""
    profile_id = _one_id(client, "DomainType", profile_name)
    kind_id = _one_id(client, "DomainType", EQUIPMENT_KIND)
    if profile_id is None or kind_id is None:
        raise ProfileError([f"no kitchen profile {profile_name!r} (load it with tools/import_profiles.py)"])
    out = {}
    for keys, default in resolve_all(client, profile_id, kind_id).items():
        (equipment_id,) = keys
        out[equipment_id] = (client.get_all("DomainType", equipment_id)["result"]["name"],
                             int(default.quantity.get("value") or 0))
    return out


def pantry_stock(client, profile_name: str) -> dict[str, tuple[str, dict]]:
    """Food Type id -> (name, its amount: the QuantitySpecification) for a pantry
    profile, inherited and overridden."""
    profile_id = _one_id(client, "DomainType", profile_name)
    kind_id = _one_id(client, "DomainType", STOCK_KIND)
    if profile_id is None or kind_id is None:
        raise ProfileError([f"no pantry profile {profile_name!r} (load it with tools/import_profiles.py)"])
    out = {}
    for keys, default in resolve_all(client, profile_id, kind_id).items():
        (food_id,) = keys
        out[food_id] = (client.get_all("DomainType", food_id)["result"]["name"], default.quantity)
    return out


# -- the owner's selection -------------------------------------------------

@dataclass
class Report:
    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)       # owner's own values, not overwritten
    removed: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)    # would have removed something with history
    adopted: list[str] = field(default_factory=list)    # a single user's targets, now a person's
    counts: dict = field(default_factory=dict)


OWNER_SET = "set by the owner in the selection file (private/nutrition.toml)"


def target_name(nutrient: str, person: str | None = None) -> str:
    """A standing daily target's name: "Daily Protein target", or a person's "Daily Protein target (Cass)"."""
    return f"Daily {nutrient} target" + (f" ({person})" if person else "")


def _adopt(client, sync: Sync, nutrients, person: str, person_id: str, report: Report) -> None:
    """Make the targets set up before there were people (named "Daily X target", for no one) this
    person's: renamed in place with their range, and linked to them. The nodes stay the same, so
    whatever uses them (a MealPlan's constraints) is undisturbed. One that is already someone's,
    or whose person-scoped name is taken, is left alone."""
    targets, ranges = sync.rows("NutritionTarget"), sync.rows("QuantitySpecification")
    for nutrient in sorted(nutrients):
        old, new = target_name(nutrient), target_name(nutrient, person)
        row = targets.get(old)
        if row is None or new in targets or row.get("forPerson"):
            continue
        client.patch(f"/structr/rest/NutritionTarget/{row['id']}", {"name": new, "forPerson": person_id})
        targets[new] = {**targets.pop(old), "name": new, "forPerson": {"id": person_id}}
        rng = ranges.get(f"{old} range")
        if rng is not None and f"{new} range" not in ranges:
            client.patch(f"/structr/rest/QuantitySpecification/{rng['id']}", {"name": f"{new} range"})
            ranges[f"{new} range"] = {**ranges.pop(f"{old} range"), "name": f"{new} range"}
        report.adopted.append(new)


def instantiate_nutrition(client, selection: dict, *, reset: bool = False, person: tuple[str, str] | None = None,
                          adopt: bool = False) -> Report:
    """The owner's standing daily NutritionTargets from their selection file:

        profile = "Adult male 31-50 moderately active"
        timezone = "America/Denver"  # a day ends at local midnight (default: UTC)
        strictness = "soft"          # default for every target
        weight = 0.1                 # default for every soft target
        hard = ["Protein"]           # nutrient names made hard
        leave_out = ["Sugars - added"]
        [overrides]                  # the owner's own range, status `specified`
        "Sodium - Na" = { max = 2000, unit = "mg" }

    Targets are named "Daily <nutrient> target" and are standing rules, attached
    to a MealPlan when one is planned (MealPlan.hasConstraint is many-to-many).
    For a person of a household (`person` = (name, Person id), data-model.md Sec 19
    K4) they are "Daily <nutrient> target (<name>)" and linked to them
    (TARGET_FOR); with `adopt`, the targets set up before there were people become
    this person's first, renamed in place.
    A range that differs from the profile is kept unless reset: the owner may
    have changed it in Structr. One that came from an override the file no
    longer has goes back to the profile. A target left out is deleted, unless a
    MealPlan uses it, which is history and is kept and reported."""
    report = Report()
    targets = {t.nutrient: t for t in dietary_targets(client, selection["profile"])}
    unknown = [n for n in list(selection.get("hard", [])) + list(selection.get("leave_out", []))
               + list(selection.get("overrides", {})) if n not in targets]
    if unknown:
        raise ProfileError([f"no target for nutrient {n!r} in profile {selection['profile']!r}" for n in unknown])
    strictness, weight = selection.get("strictness", "soft"), selection.get("weight", 0.1)
    day_boundary = "midnight"                  # midnight UTC, unless the owner names their zone
    if selection.get("timezone"):
        day_boundary = f"midnight {selection['timezone']}"
        if day_zone(day_boundary) is None:
            raise ProfileError([f"timezone {selection['timezone']!r} is not an IANA zone name (for example America/Denver)"])
    person_name, person_id = person or (None, None)
    sync = Sync(client)
    if person_id and adopt:
        _adopt(client, sync, targets, person_name, person_id, report)
    for name, t in sorted(targets.items()):
        tname = target_name(name, person_name)
        existing = sync.rows("NutritionTarget").get(tname)
        if name in selection.get("leave_out", []):
            if existing and existing.get("constrainedPlans"):
                report.refused.append(tname)
            elif existing:
                rng = sync.rows("QuantitySpecification").get(f"{tname} range")
                sync.delete("NutritionTarget", existing)
                if rng:
                    sync.delete("QuantitySpecification", rng)
                report.removed.append(tname)
            continue
        override = selection.get("overrides", {}).get(name)
        lo, hi, unit, status = t.minimum, t.maximum, t.unit, "default"
        source = f"dietary profile {selection['profile']!r} ({t.status}): " + " | ".join(t.sources)
        if override:
            lo, hi, unit, status = override.get("min"), override.get("max"), override.get("unit", t.unit), "specified"
            source = OWNER_SET
        if existing and not reset and not override and existing.get("source") != OWNER_SET \
                and existing.get("hasTargetRange"):
            current = client.get_all("QuantitySpecification", existing["hasTargetRange"]["id"])["result"]
            if (current.get("minValue"), current.get("maxValue"), current.get("unit")) != (lo, hi, unit):
                report.kept.append(f"{tname}: {current.get('minValue')}-{current.get('maxValue')} "
                                   f"{current.get('unit')} (the profile says {lo}-{hi} {unit})")
                continue
        rng = sync.ensure("QuantitySpecification", f"{tname} range", {
            "minValue": lo, "maxValue": hi, "unit": unit, "status": status})
        hard = name in selection.get("hard", [])
        fields = {"forNutrient": t.nutrient_id, "hasTargetRange": rng, "hasTimeScope": "daily",
                  "dayBoundaryRule": day_boundary, "strictness": "hard" if hard else strictness,
                  "weight": None if hard else weight, "source": source}
        if person_id:
            fields["forPerson"] = person_id
        sync.ensure("NutritionTarget", tname, fields)
        report.written.append(tname)
    report.counts = sync.counts
    return report


def instantiate_kitchen(client, selection: dict) -> Report:
    """The owner's kitchen from their selection file:

        name = "Home kitchen"                 # the UtensilSet
        profile = "Everyday home kitchen"
        add = ["Wok", { item = "Chef's knife", count = 2 }]
        remove = ["Microwave"]

    Members are named "<kitchen> -- <equipment> <n>". A member the selection no
    longer includes is deleted, unless a cook used it (it has Allocations),
    which is history and is kept and reported."""
    report = Report()
    wanted = {name: count for name, count in kitchen_items(client, selection["profile"]).values()}
    sources = {name: f"kitchen profile {selection['profile']!r}" for name in wanted}
    equipment = {row["name"]: row["id"] for row in Sync(client).rows("DomainType").values()
                 if (row.get("hierarchy") or {}).get("name") == EQUIPMENT_HIERARCHY}
    problems = []
    for entry in selection.get("add", []):
        item, count = (entry, 1) if isinstance(entry, str) else (entry.get("item"), entry.get("count", 1))
        if item not in equipment:
            problems.append(f"add: {item!r} is not an equipment type (tools/instantiate_profile.py kitchen --list)")
            continue
        wanted[item] = count
        sources[item] = "added by the owner in the selection file (private/kitchen.toml)"
    for item in selection.get("remove", []):
        if item not in wanted:
            problems.append(f"remove: {item!r} is not in the kitchen")
        wanted.pop(item, None)
    if problems:
        raise ProfileError(problems)

    sync = Sync(client)
    kitchen = selection.get("name", "Home kitchen")
    set_id = sync.ensure("UtensilSet", kitchen, {})
    keep = set()
    for item, count in sorted(wanted.items()):
        for n in range(1, count + 1):
            member = f"{kitchen} -- {item} {n}"
            keep.add(sync.ensure("EquipmentObject", member, {
                "instanceOf": equipment[item], "memberOfSet": set_id, "source": sources[item]}))
            report.written.append(member)
    members = client.get_all("UtensilSet", set_id)["result"].get("hasMemberPart", [])
    for ref in members:
        if ref["id"] in keep:
            continue
        node = client.get_all("EquipmentObject", ref["id"])["result"]
        if node.get("allocationsAbout") or node.get("processesWithParticipant"):
            report.refused.append(node["name"])
            continue
        sync.delete("EquipmentObject", node)
        report.removed.append(node["name"])
    report.counts = sync.counts
    return report



def instantiate_pantry(client, selection: dict, *, reset: bool = False, now: datetime | None = None) -> Report:
    """The owner's stock on hand from their selection file:

        name = "Home pantry"
        profile = "Basic pantry"
        add = [{ item = "Sesame oil", amount = 5, unit = "fl_oz" }]   # or a profile item's own amount
        remove = ["Honey"]

    Each item becomes a PortionOfSubstance "<pantry> -- <food>" bearing a Mass Quality,
    and an `imputed` Measurement of its amount (data-model.md Sec 4.1): what is assumed
    to be there, not a count. It `wasDerivedFrom` the QuantitySpecification it came
    from: the profile's, or, for an amount the file gives, the owner's own (status
    `specified`). It is dated when written, so only cooking after that uses it up, and
    a weighing (an `observed` Measurement) replaces it as any later one does.

    An amount that differs from its source is kept unless reset: the owner may have
    changed it in Structr. One whose source changed (an override added or dropped)
    is rewritten and dated again. An item the selection no longer includes is
    deleted, unless it has history (a cook used it, or it was weighed), which is
    kept and reported."""
    report = Report()
    now = now or datetime.now(timezone.utc)
    foods = food_types(client)
    wanted = {name: qty for name, qty in pantry_stock(client, selection["profile"]).values()}
    problems, own = [], {}
    for i, entry in enumerate(selection.get("add", []), 1):
        item = entry.get("item") if isinstance(entry, dict) else entry
        if item not in foods:
            problems.append(f"add: {item!r} is not a food in the vocabulary (tools/instantiate_profile.py pantry --list)")
            continue
        if not isinstance(entry, dict):
            problems.append(f"add: {item!r} needs an amount, like {{ item = {item!r}, amount = 500, unit = \"g\" }}")
            continue
        amount = _amount(f"add {i} ({item!r})", entry, problems)
        if amount:
            why = _unconvertible(client, foods[item], item, *amount)
            if why:
                problems.append(f"add: {why}")
            own[item] = amount
    for item in selection.get("remove", []):
        if item not in wanted and item not in own:
            problems.append(f"remove: {item!r} is not in the pantry")
        wanted.pop(item, None)
        own.pop(item, None)
    if problems:
        raise ProfileError(problems)

    pantry = selection.get("name", "Home pantry")
    if not _name_ok("name", pantry, problems):
        raise ProfileError(problems)
    sync = Sync(client)
    mass = _one_id(client, "DomainType", "Mass")
    plan = {name: (qty["value"], qty["unit"], qty["id"]) for name, qty in wanted.items() if name not in own}
    for item, (amount, unit) in own.items():
        qty = sync.ensure("QuantitySpecification", f"{pantry} -- {item} amount", {
            "value": amount, "unit": unit, "status": "specified"})
        plan[item] = (amount, unit, qty)
    keep = set()
    for item, (amount, unit, qty) in sorted(plan.items()):
        name = f"{pantry} -- {item}"
        portion = sync.ensure("PortionOfSubstance", name, {"instanceOf": foods[item]})
        keep.add(portion)
        quality = sync.ensure("Quality", f"{name} mass Quality", {"hasKind": mass, "inheresIn": portion})
        label = f"{name} mass assumed"
        current = sync.rows("Measurement").get(label)
        fields = {"value": amount, "unit": unit, "status": "imputed", "isAboutQuality": quality, "wasDerivedFrom": qty}
        if current is not None:
            same_source = (current.get("wasDerivedFrom") or {}).get("id") == qty
            if same_source and (current.get("value"), current.get("unit")) == (amount, unit):
                sync.ensure("Measurement", label, fields)
                report.written.append(name)
                continue
            if same_source and not reset:
                said = "the selection file" if item in own else f"pantry profile {selection['profile']!r}"
                report.kept.append(f"{name}: {current.get('value'):g} {current.get('unit')} ({said} says {amount:g} {unit})")
                continue
        fields["hasTime"] = now.strftime(STRUCTR_TIME)
        sync.ensure("Measurement", label, fields)
        report.written.append(name)

    prefix = f"{pantry} -- "
    for row in list(sync.rows("PortionOfSubstance").values()):
        if not row["name"].startswith(prefix) or row["id"] in keep:
            continue
        portion = client.get_all("PortionOfSubstance", row["id"])["result"]
        qualities = [client.get_all("Quality", r["id"])["result"] for r in portion.get("bearerOf", [])
                     if r.get("type") == "Quality"]
        measurements = [m for q in qualities for m in q.get("measurements", [])]
        if portion.get("allocationsAbout") or portion.get("processesWithParticipant") \
                or any(m["name"] != f"{row['name']} mass assumed" for m in measurements):
            report.refused.append(row["name"])
            continue
        for m in measurements:
            sync.delete("Measurement", m)
        for q in qualities:
            sync.delete("Quality", q)
        sync.delete("PortionOfSubstance", portion)
        report.removed.append(row["name"])
    for row in list(sync.rows("QuantitySpecification").values()):
        # only the owner's own amounts: a profile's are `default`, and a pantry may share a profile's name
        if row["name"].startswith(prefix) and row["name"].endswith(" amount") and row.get("status") == "specified" \
                and row["name"][len(prefix):-len(" amount")] not in own:
            node = client.get_all("QuantitySpecification", row["id"])["result"]
            if not node.get("imputedMeasurements"):
                sync.delete("QuantitySpecification", node)
    report.counts = sync.counts
    return report
