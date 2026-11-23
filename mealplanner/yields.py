"""Purchased-form yields: what a food is bought as, and how much of what is bought a recipe weighs.

Stage 3 of "What ingredients are sold in" (docs/todo.md, docs/packages.md, data-model.md J41). A recipe
weighs the part of a food it uses: the vocabulary's figures are FDC's, per 100 g of the edible part,
and FDC's household portions weigh the edible part too (Avocados, raw: "fruit, without skin and
seed"). A shop sells the food as it grows, or as something else: an onion with its skin, juice
inside a lemon. Both are the Yield default data-model.md Sec 5.1 and Sec 8 already name, "trimming
is a transformation like any other, and its edible fraction is its yield factor", and the
AcquisitionList "walks the same yield chain in reverse (required / yield)". No schema change: a
Yield DefaultSpecification has had `targetType` since scripts/05.

  trim         a Yield on the food, keyed by the mechanical method Trimming, whose target is the
               food itself: of a gram of it as bought, this much is what a recipe weighs (an onion
               0.90: its skin and ends are the rest). Read only when buying by weight or volume: a
               count of items is of the edible part already, as FDC's portion is.
  yield_from   a Yield on another food (the one bought), keyed by the method that makes this one
               (Juicing, Separating), whose target is this food: a gram of the food bought gives
               this much of it. Lemon juice is bought as lemons, 48 g of juice from a lemon of 58 g.

Where the figures come from (data/vocabulary.toml): a yield from another food is worked out from
two FDC portions, the yield of one item ("lemon yields", 48 g) over the item's own weight (the
bought food's `each`), `calculated`; or stated, with its source. A food's refuse is USDA's: SR28's
FOOD_DES file gives each SR food's refuse as a percentage of the food as purchased, and what it is
("Skin, ends"). That file was not reachable from the session that built this, so the vocabulary
states each refuse as an estimate; tools/yield_extract.py pins SR28's own figures into
data/yields/sr28.json, and where the pin has a food's FDC record, its figure is used, `sourced`.

What the shopping list does with them (mealplanner/shopping.py, pages/lib/90_shopping.js): a food
that another yields, and that no package level sells in a size of its own, is bought as that other
food, its need divided by the yield; whatever is bought of a food with a trim is bought as it is
sold, so a package's weight holds that fraction of what a recipe weighs, and a need bought loose is
divided by it. One step only: a food yielded by a food yielded by another is not followed.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

YIELD_KIND = "Yield"
TRIM_METHOD = "Trimming"
TRIM_SUFFIX = " as bought"                    # "Yellow Onion as bought": the name of a food's trim default
STATUSES = ("sourced", "estimated", "calculated")
SR28_PIN = "data/yields/sr28.json"
SR28_RELEASE = "SR28 (2015, revised 2018)"
SR28_URL = "https://www.ars.usda.gov/ARSUserFiles/80400535/DATA/SR/sr28/dnload/sr28asc.zip"
SR_LEGACY_ZIP = "FoodData_Central_sr_legacy_food_csv_2018-04.zip"


@dataclass(frozen=True)
class Trim:
    """Of the food as bought, `refuse` percent is cut away (`what`) before a recipe weighs it."""
    refuse: float
    what: str
    status: str
    source: str

    @property
    def factor(self) -> float:
        return round(1.0 - self.refuse / 100.0, 6)


@dataclass(frozen=True)
class YieldFrom:
    """A gram of `food` gives `factor` grams of the food this is on, by `method`: stated, or worked out
    from `portion`, a portion of this food's own FDC record that one item of `food` yields."""
    food: str
    method: str
    factor: float | None = None
    portion: str | None = None
    status: str = "calculated"
    source: str = ""


def yield_name(source: str, method: str, target: str) -> str:
    return f"{source} -- {method} -- {target}"


def _text(raw, key: str) -> str | None:
    value = raw.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def parse_trim(raw, where: str, fdc_id: int | None, pin: dict | None, problems: list[str]) -> Trim | None:
    """`trim = { refuse = 10, what = "skin and ends", source = "...", status = "estimated" }`. Where the
    SR28 pin has the food's FDC record, its refuse and description are used instead, `sourced`, and a
    refuse of none there is no trim."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"refuse", "what", "source", "status"}:
        problems.append(f"{where}: trim is {{ refuse, what, source }} (and a status)")
        return None
    refuse, what, source = raw.get("refuse"), _text(raw, "what"), _text(raw, "source")
    status = raw.get("status", "estimated")
    if not isinstance(refuse, (int, float)) or isinstance(refuse, bool) or not math.isfinite(refuse) or not 0 < refuse < 100:
        problems.append(f"{where}: a trim's refuse is a percentage of the food as bought, above 0 and below 100")
        return None
    if what is None or source is None:
        problems.append(f"{where}: a trim says what is cut away (what) and where its figure comes from (source)")
        return None
    if status not in STATUSES:
        problems.append(f"{where}: trim status {status!r} is not one of {STATUSES}")
        return None
    pinned = (pin or {}).get("foods", {}).get(str(fdc_id)) if fdc_id is not None else None
    if pinned is not None and not pinned.get("refuse"):
        return None                         # SR28 says none of it as purchased is refuse
    if pinned is not None:
        release = (pin.get("source") or {}).get("release", SR28_RELEASE)
        return Trim(float(pinned["refuse"]), pinned.get("what") or what, "sourced",
                    f"USDA {release} FOOD_DES, NDB {pinned['ndb']} ({pinned.get('description', '')}): "
                    f"refuse {pinned['refuse']:g}% ({pinned.get('what', '')})")
    return Trim(float(refuse), what, status, source)


def parse_yield_from(raw, where: str, problems: list[str]) -> YieldFrom | None:
    """`yield_from = { food = "Lemon", method = "Juicing", portion = "lemon yields" }`, or with a stated
    `factor` and its `source` (and a status, default estimated) in place of the portion."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"food", "method", "portion", "factor", "source", "status"}:
        problems.append(f"{where}: yield_from is {{ food, method, portion }} or {{ food, method, factor, source }}")
        return None
    food, method, portion, source = _text(raw, "food"), _text(raw, "method"), _text(raw, "portion"), _text(raw, "source")
    factor = raw.get("factor")
    if food is None or method is None:
        problems.append(f"{where}: yield_from names the food bought (food) and the method that makes this one (method)")
        return None
    if (portion is None) == (factor is None):
        problems.append(f"{where}: yield_from gives a portion of this food's FDC record or a factor, one of them")
        return None
    if factor is not None:
        if not isinstance(factor, (int, float)) or isinstance(factor, bool) or not math.isfinite(factor) or factor <= 0:
            problems.append(f"{where}: a yield's factor is a number above zero")
            return None
        if source is None:
            problems.append(f"{where}: a stated yield needs its source")
            return None
        status = raw.get("status", "estimated")
        if status not in STATUSES:
            problems.append(f"{where}: yield_from status {status!r} is not one of {STATUSES}")
            return None
        return YieldFrom(food, method, float(factor), None, status, source)
    if "status" in raw or source is not None:
        problems.append(f"{where}: a yield worked out from a portion is calculated, and says its own source")
        return None
    return YieldFrom(food, method, None, portion)


# -- reading the graph ------------------------------------------------------------

@dataclass(frozen=True)
class Made:
    """A food bought as another: a gram of `source` (a food Type id) gives `factor` grams of it."""
    source: str
    source_name: str
    factor: float
    method: str
    spec: dict


def _kind(client, name: str) -> str | None:
    rows = client.get("/structr/rest/DomainType", params={"name": name})["result"]
    return rows[0]["id"] if len(rows) == 1 else None


def _ratio(client, spec: dict) -> float | None:
    if not spec.get("hasValue"):
        return None
    qty = client.get_all("QuantitySpecification", spec["hasValue"]["id"])["result"]
    value = qty.get("value")
    if qty.get("unit") != "ratio" or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def edible_fraction(client, food_id: str) -> tuple[float, str]:
    """(of a gram of the food as bought, how much a recipe weighs; what is cut away): its own trim, or
    its nearest ancestor food's, a Yield keyed by Trimming alone whose target is the Type it is on.
    (1.0, "") for a food with none."""
    from mealplanner.typetree import ancestors_or_self
    kind, trim = _kind(client, YIELD_KIND), _kind(client, TRIM_METHOD)
    if kind is None or trim is None:
        return 1.0, ""
    for type_id in ancestors_or_self(client, food_id):
        node = client.get_all("DomainType", type_id)["result"]
        for ref in node.get("defaultSpecifications", []):
            spec = client.get_all("DefaultSpecification", ref["id"])["result"]
            if (spec.get("hasKind") or {}).get("id") != kind or [k["id"] for k in spec.get("keyedBy") or []] != [trim] \
                    or (spec.get("targetType") or {}).get("id") != type_id:
                continue
            factor = _ratio(client, spec)
            if factor is not None and factor <= 1:
                return factor, trim_what(spec)
    return 1.0, ""


def trim_what(spec: dict) -> str:
    """What a trim cuts away, as its source states it after "refuse": "skin and ends"."""
    source = spec.get("source") or ""
    marker = "cut away: "
    return source.split(marker, 1)[1].split(";", 1)[0].strip() if marker in source else ""


def made_from(client, food_id: str) -> Made | None:
    """The food this one is bought as: a Yield on another food whose target is this one (its own, not
    an ancestor's), the first by name where there are several. None if no food yields it."""
    kind = _kind(client, YIELD_KIND)
    if kind is None:
        return None
    node = client.get_all("DomainType", food_id)["result"]
    found = []
    for ref in node.get("yieldTargetOf") or []:
        spec = client.get_all("DefaultSpecification", ref["id"])["result"]
        source = spec.get("forType") or {}
        keys = spec.get("keyedBy") or []
        if (spec.get("hasKind") or {}).get("id") != kind or not source or source.get("id") == food_id or len(keys) != 1:
            continue
        factor = _ratio(client, spec)
        if factor is not None:
            found.append(Made(source["id"], source.get("name") or source["id"], factor, keys[0].get("name") or "", spec))
    return min(found, key=lambda m: m.spec.get("name") or "") if found else None


# -- SR28's refuse ------------------------------------------------------------------

def parse_food_des(text: str) -> dict[str, dict]:
    """SR28's FOOD_DES.txt: NDB number -> {description, what, refuse}. Fields are separated by ^ and
    text fields wrapped in ~: NDB_No, FdGrp_Cd, Long_Desc, Shrt_Desc, ComName, ManufacName, Survey,
    Ref_desc, Refuse, SciName, N_Factor, Pro_Factor, Fat_Factor, CHO_Factor."""
    out = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = [f.strip("~") for f in line.rstrip("\r\n").split("^")]
        if len(fields) < 9:
            raise ValueError(f"FOOD_DES: a line with {len(fields)} fields, not 14: {line[:60]!r}")
        refuse = fields[8].strip()
        out[fields[0].strip()] = {"description": fields[2], "what": fields[7], "refuse": float(refuse) if refuse else 0.0}
    return out


def ndb_numbers(csv_text: str) -> dict[str, str]:
    """FDC's sr_legacy_food.csv: FDC id -> NDB number."""
    return {row["fdc_id"]: row["NDB_number"].strip() for row in csv.DictReader(io.StringIO(csv_text))}


def sr28_pin(food_des: dict[str, dict], ndb_of: dict[str, str], fdc_ids, release: str = SR28_RELEASE) -> dict:
    """The pin: each wanted FDC id SR28 knows, with its NDB number, description, refuse and what it is."""
    foods = {}
    for fid in sorted({str(i) for i in fdc_ids}, key=int):
        ndb = ndb_of.get(fid)
        row = food_des.get(ndb.zfill(5)) if ndb else None
        if row is None and ndb:
            row = food_des.get(ndb)
        if row is not None:
            foods[fid] = {"ndb": ndb.zfill(5), "description": row["description"], "refuse": row["refuse"], "what": row["what"]}
    return {"source": {"release": release, "url": SR28_URL, "file": "FOOD_DES.txt",
                       "note": "Refuse: the percentage of the food as purchased that is not eaten (SR28 documentation)"},
            "foods": foods}
