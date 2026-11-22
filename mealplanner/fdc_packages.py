"""Package sizes from FoodData Central's Branded Foods: what is common, counted from labels.

The owner asked (2026-11-22) for an online source of common package sizes in place of Claude's
estimates. USDA FoodData Central's Branded Foods dataset (public domain, CC0 1.0) records, for each
product a manufacturer or Label Insight submitted, the net weight printed on its package in
`package_weight` ("15 oz/425 g", "32 fl oz/1 Quart/946 mL", "5 LBR"). About 875,000 of its 2.0
million records give one (the 2026-10-29 release). No other open dataset was found that does.

A food in data/packages.toml may name a rule, `fdc = { category = ..., match = ..., exclude = ... }`:
regular expressions (case ignored) on the record's `branded_food_category` and on its description.
tools/package_extract.py applies the rules to the bulk file and pins, for each food, how many
products and brand owners come in each size (data/packages/fdc.json); tools/import_packages.py loads
the common sizes from the pin as `sourced`, and a food with no rule, or too few products, keeps its
estimate. These are the rules of the count, each a proposal for the owner to retune:

  - one record per product (GTIN), its latest; U.S. market only; not discontinued; not sold only to
    food service (a trade channel naming FOOD_SERVICE alone);
  - a size is counted in ounces as the label prints it, to the nearest quarter ounce: U.S. labels are
    designed in ounces and pounds and the metric figure beside them is a rounded conversion. Weight
    and fluid ounces are counted together (labels and data entry conflate them: a carton of broth is
    "32 oz" on one record and "32 fl oz" on the next). A size within MERGE of a more common one is
    that size: a label giving only "1.81 kg" (63.85 oz) is the 4 lb bag, "1 L" (33.8) the 33.8 fl oz
    bottle; a 15.25 oz can is not a 15 oz one (1.7% apart);
  - a size is common when at least MIN_SHARE of the food's products and MIN_OWNERS brand owners sell
    it; at most MAX_SIZES, the most common first; and a food needs MIN_PRODUCTS products and
    MIN_OWNERS owners in all, or its estimate stands.

A count is of products on the market, not of sales: a store brand's can counts once, as a national
brand's does. It says what a shopper commonly finds, which is what the shopping list needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DATASET = "FoodData Central Branded Foods"
CITATION = ("U.S. Department of Agriculture, Agricultural Research Service. FoodData Central: Branded Foods. "
            "fdc.nal.usda.gov. Public domain (CC0 1.0).")
PIN = "data/packages/fdc.json"
MIN_SHARE = 0.10
MIN_OWNERS = 5
MIN_PRODUCTS = 20
MAX_SIZES = 4
MERGE = 0.015
KEEP_BINS = 8           # sizes pinned per food, most common first: enough to retune MIN_SHARE without a re-run
RULE_KEYS = ("category", "match", "exclude")

OZ_G = 28.3495
FLOZ_ML = 29.5735
# a unit as the dataset spells it -> (ounces in one, "us"), or (grams or mL in one, "metric")
_UNITS = {
    "oz": (1, "us"), "onz": (1, "us"), "ounce": (1, "us"), "ounces": (1, "us"),
    "fl oz": (1, "us"), "floz": (1, "us"), "oza": (1, "us"), "fz": (1, "us"),
    "lb": (16, "us"), "lbs": (16, "us"), "lbr": (16, "us"), "pound": (16, "us"), "pounds": (16, "us"),
    "pt": (16, "us"), "pint": (16, "us"), "quart": (32, "us"), "qt": (32, "us"), "gal": (128, "us"), "gll": (128, "us"),
    "g": (1 / OZ_G, "metric"), "grm": (1 / OZ_G, "metric"), "gram": (1 / OZ_G, "metric"), "grams": (1 / OZ_G, "metric"),
    "kg": (1000 / OZ_G, "metric"),
    "ml": (1 / FLOZ_ML, "metric"), "mlt": (1 / FLOZ_ML, "metric"), "l": (1000 / FLOZ_ML, "metric"),
    "ltr": (1000 / FLOZ_ML, "metric"),
}
_PART = re.compile(r"([0-9]*\.?[0-9]+)\s*([a-z][a-z ]*?)\.?")
# "1/2 gal", "1 1/2 lb": the slash of a fraction, where elsewhere one separates figures ("15 oz/425 g")
_FRACTION = re.compile(r"(^|/)\s*(?:(\d+)[ -]+)?(1/2|1/3|2/3|1/4|3/4|1/8|3/8|5/8|7/8)(?=\s*[a-z])")


def _decimal(match: re.Match) -> str:
    over, under = match.group(3).split("/")
    return f"{match.group(1)}{int(match.group(2) or 0) + int(over) / int(under)}"


def package_ounces(text: str) -> float | None:
    """A `package_weight` in ounces (weight or fluid, as printed), or None when it gives no mass or
    volume ("1 EA", "12 CT", blank). The first U.S. figure wins ("16 oz/1 lb/454 g" is 16); a label
    with only a metric figure is converted ("500 mL" is 16.9)."""
    us = metric = None
    for part in _FRACTION.sub(_decimal, (text or "").lower()).split("/"):
        m = _PART.fullmatch(part.strip())
        if not m or m.group(2).strip() not in _UNITS:
            continue
        factor, system = _UNITS[m.group(2).strip()]
        value = float(m.group(1)) * factor
        if value <= 0:
            continue
        if system == "us" and us is None:
            us = value
        elif system == "metric" and metric is None:
            metric = value
    return us if us is not None else metric


def size_bin(ounces: float) -> float:
    """To the nearest quarter ounce: 14.46 (410 g) and 14.5 are one size."""
    return round(ounces * 4) / 4


@dataclass(frozen=True)
class Rule:
    category: re.Pattern
    match: re.Pattern
    exclude: re.Pattern | None

    def takes(self, category: str, description: str) -> bool:
        return bool(self.category.search(category or "") and self.match.search(description or "")
                    and not (self.exclude and self.exclude.search(description or "")))


def parse_rule(where: str, raw, problems: list[str]) -> dict | None:
    """`fdc = { category = "...", match = "...", exclude = "..." }`, exclude optional; the strings
    as written (they are pinned beside the counts, so a changed rule shows the pin is stale)."""
    if not isinstance(raw, dict):
        problems.append(f"{where}: fdc must be a table with category, match and optionally exclude")
        return None
    unknown = set(raw) - set(RULE_KEYS)
    missing = {"category", "match"} - set(raw)
    if unknown or missing:
        problems.append(f"{where}: fdc " + "; ".join(
            ([f"unknown key(s) {sorted(unknown)}"] if unknown else []) + ([f"needs {sorted(missing)}"] if missing else [])))
        return None
    out = {}
    for key in RULE_KEYS:
        if key not in raw:
            continue
        if not isinstance(raw[key], str) or not raw[key]:
            problems.append(f"{where}: fdc {key} must be a non-empty string")
            continue
        try:
            re.compile(raw[key], re.I)
        except re.error as exc:
            problems.append(f"{where}: fdc {key} is not a regular expression ({exc})")
            continue
        out[key] = raw[key]
    return out if len(out) == len([k for k in RULE_KEYS if k in raw]) else None


def compile_rule(rule: dict) -> Rule:
    return Rule(re.compile(rule["category"], re.I), re.compile(rule["match"], re.I),
                re.compile(rule["exclude"], re.I) if rule.get("exclude") else None)


def counted(record: dict) -> bool:
    """A record a shopper could find: U.S. market, not discontinued, not for food service only."""
    channel = record.get("trade_channel") or ""
    return (record.get("market_country") or "United States") in ("United States", "US") \
        and not (record.get("discontinued_date") or "").strip() \
        and not ("FOOD_SERVICE" in channel and "GROCERY" not in channel and "ONLINE" not in channel)


def owner_key(owner: str) -> str:
    """'[[Conagra Brands, Inc]]' and 'CONAGRA BRANDS, INC.' are one owner."""
    return re.sub(r"[^a-z0-9]+", " ", (owner or "").lower()).strip()


def tally(products, rules: dict[str, dict]) -> dict[str, dict]:
    """Each food's count from `products`, one dict per GTIN (its latest record) with
    branded_food_category, description, brand_owner, package_weight and the fields `counted` reads.
    -> {food: {"products": n, "owners": m, "sizes": [[ounces, products, owners], ...]}} with the
    KEEP_BINS most common sizes, most products first, then most owners, then the smaller size."""
    compiled = {food: compile_rule(rule) for food, rule in rules.items()}
    bins: dict[str, dict[float, list]] = {food: {} for food in rules}
    owners: dict[str, set] = {food: set() for food in rules}
    for p in products:
        if not counted(p):
            continue
        ounces = package_ounces(p.get("package_weight", ""))
        if ounces is None:
            continue
        for food, rule in compiled.items():
            if rule.takes(p.get("branded_food_category", ""), p.get("description", "")):
                owner = owner_key(p.get("brand_owner", ""))
                cell = bins[food].setdefault(size_bin(ounces), [0, set()])
                cell[0] += 1
                cell[1].add(owner)
                owners[food].add(owner)
    out = {}
    for food in rules:
        rows = sorted(([size, n, len(o)] for size, (n, o) in merged(bins[food]).items()), key=lambda r: (-r[1], -r[2], r[0]))
        out[food] = {"products": sum(r[1] for r in rows), "owners": len(owners[food]), "sizes": rows[:KEEP_BINS]}
    return out


def merged(bins: dict[float, list]) -> dict[float, list]:
    """Each size folded into the most common size within MERGE of it, most common first (most
    products, then the smaller size): 63.75 oz into 64, 79.75 into 80."""
    kept: dict[float, list] = {}
    for size, (n, owners) in sorted(bins.items(), key=lambda kv: (-kv[1][0], kv[0])):
        home = next((k for k in kept if abs(size - k) <= MERGE * k), None)
        if home is None:
            kept[size] = [n, set(owners)]
        else:
            kept[home][0] += n
            kept[home][1] |= owners
    return kept


def common_sizes(count: dict) -> list[tuple[float, float, int, int]]:
    """The sizes a pinned count calls common -> [(ounces, share, products, owners)], most common
    first; [] when the food has too few products or owners for its count to stand."""
    if count["products"] < MIN_PRODUCTS or count["owners"] < MIN_OWNERS:
        return []
    out = [(size, n / count["products"], n, o) for size, n, o in count["sizes"]
           if n / count["products"] >= MIN_SHARE and o >= MIN_OWNERS]
    return out[:MAX_SIZES]


def describe_share(release: str, count: dict, share: float, products: int, owners: int) -> str:
    return (f"{DATASET} ({release}): {products} of {count['products']} U.S. products ({share:.0%}), from "
            f"{owners} of {count['owners']} brand owners, come in this size; public domain")
