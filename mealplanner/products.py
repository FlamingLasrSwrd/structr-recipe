"""Products: a packaged food with its barcodes and what one package holds (docs/pantry.md, "Products
and barcodes").

The model already says what a barcode is (data-model.md Sec 3, Sec 6, Sec 10): "a GTIN denotes a
packaged-offering Type", and the Food Identity hierarchy holds "branded/packaged forms". So a product
is written with what the schema has had since scripts/29a, and needs no schema change:

  a DomainType           in the Food Identity hierarchy, directly below the food it is a kind of
  an Identifier          for each barcode, in the scheme "GTIN", that `denotesType` it; its value
                         is the GTIN as 14 digits, whatever length the package prints
  a DefaultSpecification of kind PurchaseQuantity on it: what one package holds (Sec 8)

Sitting below its food, a product is that food to everything that already walks the hierarchy: a
portion of it counts as stock of the food (inventory.py, the shopping list, a cook's draws), and it
takes the food's density, weight per item and shelf life, having none of its own
(defaults.resolve_default). A recipe names the food, not a product: nutrition reads a Type's own
figures only. A product is optional: the food itself is still bought as before.

What marks a Type as a product is that a GTIN denotes it. The pantry page offers every food nothing
sits under, since a food others sit under is a group ("Eggs", "Poultry"); with products that rule
becomes `buyable`: a food nothing but products sits under, and each product.

A barcode is read as a GTIN (GS1 General Specifications, Sec 7.9: the check digit; Sec 2.1: the
lengths):
  12 digits  a UPC-A      13 digits  an EAN-13      14 digits  a GTIN-14
   8 digits  a UPC-E when it starts with 0 or 1 (GS1 keeps those GTIN-8 prefixes for it), spelled out
             to its UPC-A; else an EAN-8
A number a shop gives its own packs (UPC-A starting 2 or 4, EAN-13 starting 02, 04 or 2, EAN-8 starting
2) is refused:
it is no product's, and on meat, cheese or produce it holds the pack's own weight or price.

Products come from a file (tools/import_products.py). Which products a household buys is its own
data, so the owner's file is private/products.toml, which git ignores:

    [[product]]
    name = "Brand X chickpeas 400 g"      # how it is named in the pantry
    food = "Chickpeas (canned)"           # the food it is a kind of
    barcodes = ["0 36000 29145 2"]        # one or more; spaces and hyphens are ignored
    amount = 400                          # what one package holds
    unit = "g"

Loading is idempotent and writes only what differs. A barcode a product of the file no longer lists
is removed. A product the file no longer names is left as it is, since stock may be of it. A name
that is already a food and not a product is refused, so a run interrupted between a product's Type
and its first barcode leaves a Type the next run refuses: delete it in Structr and run again.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass

from mealplanner.defaults import resolve_default
from mealplanner.identifier_schema import GTIN, SCHEME
from mealplanner.typetree import dt
from mealplanner.unit_conversion import UNIT_TABLE, convert_to_grams
from mealplanner.vocabulary_import import FOOD_HIERARCHY, Sync
from structr_client.client import UNSAFE_EXACT_MATCH_CHARS

PACKAGE_SIZE = "PurchaseQuantity"       # the Default-Kind Type (seed_vocabulary.py, data-model.md Sec 8)
SOURCE = "the package, as the products file states it"
# The first digits of a GTIN-13 that GS1 leaves to each shop for its own packs (restricted circulation).
SHOP_PREFIXES = ("02", "04", "2")


class ProductError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


@dataclass(frozen=True)
class Product:
    name: str
    food: str
    barcodes: tuple[str, ...]       # as 14 digits
    amount: float
    unit: str


@dataclass(frozen=True)
class Found:
    """What a barcode names: the product, the food it is a kind of, and what one package holds."""
    gtin: str
    product: str
    product_id: str
    food: str | None
    amount: float | None
    unit: str | None


def check_digit(digits: str) -> int:
    """The check digit of a GTIN's other digits: from the right, they weigh 3, 1, 3, ..."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10


def _upc_a_of(upc_e: str) -> str:
    """A UPC-E (number system, six digits, check digit) spelled out to the UPC-A it shortens."""
    n, d, check = upc_e[0], upc_e[1:7], upc_e[7]
    if d[5] in "012":
        body = d[0:2] + d[5] + "0000" + d[2:5]
    elif d[5] == "3":
        body = d[0:3] + "00000" + d[3:5]
    elif d[5] == "4":
        body = d[0:4] + "00000" + d[4]
    else:
        body = d[0:5] + "0000" + d[5]
    return n + body + check


def normalize(barcode) -> str:
    """A barcode as its GTIN in 14 digits, or ValueError saying what is wrong with it."""
    text = str(barcode).replace(" ", "").replace("-", "")
    if not (text.isascii() and text.isdigit()):
        raise ValueError(f"barcode {barcode!r} is not a number")
    if len(text) not in (8, 12, 13, 14):
        raise ValueError(f"barcode {barcode!r} has {len(text)} digits: a product's has 8, 12, 13 or 14")
    if len(text) == 8 and text[0] in "01":
        text = _upc_a_of(text)
    if check_digit(text[:-1]) != int(text[-1]):
        raise ValueError(f"barcode {barcode!r} is misread or mistyped: its last digit should be {check_digit(text[:-1])}")
    gtin = text.zfill(14)
    if text.startswith("2") if len(text) == 8 else gtin[1:].startswith(SHOP_PREFIXES):
        raise ValueError(f"barcode {barcode!r} is a shop's own number for a pack (often with its weight or price in it), "
                         "not a product's")
    return gtin


def parse_products(data: dict, where: str = "the products file") -> list[Product]:
    """The products of a parsed file, or ProductError naming every problem. Reads no instance."""
    problems: list[str] = []
    unknown = set(data) - {"product"}
    if unknown:
        problems.append(f"{where} has sections it does not use: {', '.join(sorted(unknown))}")
    products: list[Product] = []
    names: set[str] = set()
    owner_of: dict[str, str] = {}
    rows = data.get("product", [])
    for row in rows if isinstance(rows, list) else []:
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append("a product has no name")
            continue
        before = len(problems)
        extra = set(row) - {"name", "food", "barcodes", "amount", "unit"}
        if extra:
            problems.append(f"{name}: it has fields it does not use: {', '.join(sorted(extra))}")
        if any(c in name for c in UNSAFE_EXACT_MATCH_CHARS):
            problems.append(f"{name}: a name cannot hold a comma or a semicolon")
        if name in names:
            problems.append(f"{name}: named twice")
        names.add(name)
        food = row.get("food")
        if not isinstance(food, str) or not food:
            problems.append(f"{name}: it names no food")
        elif food == name:
            problems.append(f"{name}: a product is named apart from its food")
        amount, unit = row.get("amount"), row.get("unit")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            problems.append(f"{name}: what a package holds (amount) must be more than 0")
        if not isinstance(unit, str) or unit.strip().lower() not in UNIT_TABLE:
            problems.append(f"{name}: unit {unit!r} is not one of {', '.join(sorted(UNIT_TABLE))}")
        barcodes = row.get("barcodes")
        gtins: list[str] = []
        if not isinstance(barcodes, list) or not barcodes:
            problems.append(f"{name}: it lists no barcode (barcodes = [...]); without one it is its food")
        for barcode in barcodes if isinstance(barcodes, list) else []:
            try:
                gtin = normalize(barcode)
            except ValueError as exc:
                problems.append(f"{name}: {exc}")
                continue
            if owner_of.get(gtin, name) != name:
                problems.append(f"{name}: barcode {barcode!r} is also {owner_of[gtin]}'s")
            owner_of[gtin] = name
            if gtin not in gtins:
                gtins.append(gtin)
        if len(problems) == before:
            products.append(Product(name, food, tuple(gtins), float(amount), unit.strip().lower()))
    if problems:
        raise ProductError(problems)
    return products


def read_products(path: str) -> list[Product]:
    with open(path, "rb") as fh:
        return parse_products(tomllib.load(fh), path)


def _gtin_identifiers(client) -> list[dict]:
    """Every Identifier of the GTIN scheme, fully loaded."""
    return [row for row in client.get_all("Identifier")["result"]
            if row.get("type") == "Identifier" and (row.get("identifierScheme") or {}).get("name") == GTIN]


def product_ids(client) -> set[str]:
    """The Types a GTIN denotes: the products."""
    return {row["denotesType"]["id"] for row in _gtin_identifiers(client) if row.get("denotesType")}


def _foods(client) -> list[dict]:
    return [t for t in client.get_all("DomainType")["result"] if (t.get("hierarchy") or {}).get("name") == FOOD_HIERARCHY]


def buyable(client) -> list[str]:
    """What the pantry's Buy offers, by name: each food nothing but products sits under (a food others sit
    under is a group, not something bought), and each product. pages/pantry.js follows this."""
    products = product_ids(client)
    return sorted(t["name"] for t in _foods(client) if all(c["id"] in products for c in t.get("children") or []))


def import_products(client, products: list[Product]) -> dict[str, int]:
    """Write the products, or raise ProductError naming every problem before anything is written."""
    sync = Sync(client)
    types = sync.rows("DomainType")
    in_scheme = {row["identifierValue"]: row for row in _gtin_identifiers(client)}
    is_product = {row["denotesType"]["id"] for row in in_scheme.values() if row.get("denotesType")}
    in_file = {p.name for p in products}
    problems: list[str] = []
    for p in products:
        food = types.get(p.food)
        if food is None or (food.get("hierarchy") or {}).get("name") != FOOD_HIERARCHY:
            problems.append(f"{p.name}: {p.food!r} is not a food of this instance")
            continue
        if food["id"] in is_product or p.food in in_file:
            problems.append(f"{p.name}: {p.food!r} is a product itself; name the food it is a kind of")
            continue
        others = sorted(c["name"] for c in food.get("children") or [] if c["id"] not in is_product and c["name"] not in in_file)
        if others:
            problems.append(f"{p.name}: {p.food!r} is a group of foods ({', '.join(others[:3])}"
                            f"{', ...' if len(others) > 3 else ''}), not a food that is bought")
        mine = types.get(p.name)
        if mine is not None and mine["id"] not in is_product:
            problems.append(f"{p.name}: that name is already a food here, not a product")
        for gtin in p.barcodes:
            held = (in_scheme.get(gtin) or {}).get("denotesType")
            if held and held["name"] != p.name and held["name"] not in in_file:
                problems.append(f"{p.name}: barcode {gtin} already belongs to {held['name']!r}, which this file does not name")
        if convert_to_grams(client, food["id"], p.amount, p.unit) is None:
            problems.append(f"{p.name}: {p.amount:g} {p.unit} of {p.food} does not convert to grams "
                            "(the food has no density or weight per item)")
    if PACKAGE_SIZE not in types:
        problems.append(f"this instance has no {PACKAGE_SIZE!r} kind of default (scripts/05_seed_vocabulary.py makes it)")
    if problems:
        raise ProductError(problems)

    listed = {gtin for p in products for gtin in p.barcodes}
    scheme = sync.ensure("ConceptScheme", SCHEME, {})
    gtin_scheme = sync.ensure("Concept", GTIN, {"inScheme": scheme})
    hierarchy = types[products[0].food]["hierarchy"]["id"] if products else None
    for p in products:
        product = sync.ensure("DomainType", p.name, {"hierarchy": hierarchy, "isLookupBearing": True,
                                                     "parent": types[p.food]["id"]})
        for gtin in p.barcodes:
            sync.ensure("Identifier", f"{GTIN} {gtin}", {"identifierValue": gtin, "identifierScheme": gtin_scheme,
                                                         "denotesType": product})
        for gtin, row in in_scheme.items():       # one another product of the file lists now was moved, above or later
            if (row.get("denotesType") or {}).get("id") == product and gtin not in listed:
                sync.delete("Identifier", row)
        size = sync.ensure("QuantitySpecification", f"{p.name} package size value", {
            "value": p.amount, "unit": p.unit, "status": "default"})
        sync.ensure("DefaultSpecification", f"{p.name} package size", {
            "forType": product, "hasKind": types[PACKAGE_SIZE]["id"], "hasValue": size, "provenance": "sourced",
            "source": SOURCE})
    return sync.counts


def find(client, barcode) -> Found | None:
    """The product a barcode names, or None if no product has it. ValueError for what is not a product's
    barcode at all (normalize)."""
    gtin = normalize(barcode)
    rows = []
    for ref in client.get("/structr/rest/Identifier", params={"identifierValue": gtin})["result"]:
        row = client.get_all("Identifier", ref["id"])["result"]
        if (row.get("identifierScheme") or {}).get("name") == GTIN and row.get("denotesType"):
            rows.append(row)
    if not rows:
        return None
    if len(rows) > 1:
        raise ProductError([f"barcode {gtin} names {len(rows)} products: "
                            + ", ".join(sorted(r["denotesType"]["name"] for r in rows))])
    product = client.get_all("DomainType", rows[0]["denotesType"]["id"])["result"]
    size = resolve_default(client, product["id"], dt(client, PACKAGE_SIZE))
    return Found(gtin=gtin, product=product["name"], product_id=product["id"],
                 food=(product.get("parent") or {}).get("name"),
                 amount=size.quantity.get("value") if size else None, unit=size.quantity.get("unit") if size else None)
