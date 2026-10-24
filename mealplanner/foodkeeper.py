"""USDA FSIS FoodKeeper data, read, pinned and turned into shelf lives (data-model.md J31).

FoodKeeper (foodsafety.gov's storage guidance; the data at fsis.usda.gov/shared/data/EN/foodkeeper.json,
CC0) gives, for some 650 products, how long each keeps in the pantry, the refrigerator and the
freezer, before and after opening, as a range in a unit ("1", "2", "Days"). The file is a workbook
as JSON: sheets of rows, each row a list of one-key objects. A column with "DOP_" counts from the
date of purchase, which is where the model starts the clock (Sec 5.5); one without counts from
when the food is stored, which for a food bought and put away is the same moment.

tools/foodkeeper_extract.py pins the products data/vocabulary.toml names into
data/foodkeeper/foodkeeper.json, and tools/import_vocabulary.py writes their shelf lives as
ShelfLife defaults on the foods (mealplanner/vocabulary_import.py).
"""

from __future__ import annotations

import hashlib
import json

CITATION = ("USDA Food Safety and Inspection Service, FoodKeeper data (fsis.usda.gov/shared/data/EN/foodkeeper.json), "
            "CC0 1.0.")
DAYS = {"hours": 1 / 24, "days": 1.0, "weeks": 7.0, "months": 30.0, "month": 30.0, "year": 365.0, "years": 365.0}
INDEFINITELY_DAYS = 3650.0          # "Indefinitely", taken as ten years
# storage condition: (the columns for it unopened, the first that has a figure wins; the column after opening)
COLUMNS = {
    "Pantry": (("DOP_Pantry", "Pantry"), "Pantry_After_Opening"),
    "Fridge": (("DOP_Refrigerate", "Refrigerate"), "Refrigerate_After_Opening"),
    "Freezer": (("DOP_Freeze", "Freeze"), None),
}
WORDS = {"Pantry": "in the pantry", "Fridge": "in the refrigerator", "Freezer": "in the freezer"}


def _sheet(data: dict, name: str) -> list[dict]:
    sheet = next(s for s in data["sheets"] if s["name"] == name)
    return [{k: v for cell in row for k, v in cell.items()} for row in sheet["data"]]


def read_products(path: str) -> tuple[dict, dict]:
    """({product id: its row, with "Category"}, {"version", "modified"}) from the downloaded file."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    categories = {c["ID"]: c["Category_Name"] + (f" / {c['Subcategory_Name']}" if c.get("Subcategory_Name") else "")
                  for c in _sheet(data, "Category")}
    products = {}
    for row in _sheet(data, "Product"):
        products[int(row["ID"])] = {**row, "Category": categories.get(row.get("Category_ID"))}
    current = [v for v in _sheet(data, "Version") if v.get("Current_Version") == "Yes"]
    version = current[-1] if current else {}
    return products, {"version": version.get("Data_Version_Number"), "modified": version.get("Modified_Date")}


def pin(path: str, ids: set[int]) -> dict:
    """The products `ids`, with their storage columns only (no tips), sorted, and the file's checksum.
    An id the file lacks is an error."""
    products, version = read_products(path)
    missing = sorted(ids - set(products))
    if missing:
        raise KeyError(f"FoodKeeper has no products {missing}")
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    keep = {"ID", "Name", "Name_subtitle", "Category"} | {
        f"{column}_{part}" for sealed, opened in COLUMNS.values() for column in (*sealed, opened) if column
        for part in ("Min", "Max", "Metric")}
    return {"source": CITATION, "file": "foodkeeper.json", "sha256": digest, **version,
            "products": {str(i): {k: v for k, v in sorted(products[i].items()) if k in keep} for i in sorted(ids)}}


def figure(product: dict, column: str) -> tuple[float, str] | None:
    """(days, how FoodKeeper puts it) for one column, the least of its range; None where it gives no
    number of days (not recommended, the package's use-by date, when ripe, or nothing)."""
    metric = product.get(f"{column}_Metric")
    low, high = product.get(f"{column}_Min"), product.get(f"{column}_Max")
    if metric == "Indefinitely":
        return INDEFINITELY_DAYS, "indefinitely (taken as 10 years)"
    unit = DAYS.get(str(metric or "").strip().lower())
    if unit is None or low is None:
        return None
    span = f"{low:g}" if high in (None, low) else f"{low:g}-{high:g}"
    return float(low) * unit, f"{span} {str(metric).lower()}"


def shelf_lives(product: dict) -> list[tuple[tuple[str, ...], float, str]]:
    """((storage condition[, opened status]), days, where it comes from) for each way the product keeps.
    A storage with one figure is keyed by the storage alone, so it holds opened or not; one with a
    figure before and after opening is keyed by both."""
    name = product["Name"] + (f" ({product['Name_subtitle']})" if product.get("Name_subtitle") else "")
    out = []
    for storage, (sealed_columns, opened_column) in COLUMNS.items():
        sealed = next(((c, f) for c in sealed_columns if (f := figure(product, c))), None)
        opened = figure(product, opened_column) if opened_column else None

        def said(column, f, after=False):
            when = " after opening" if after else (" from purchase" if column.startswith("DOP_") else "")
            return (f"USDA FoodKeeper product {product['ID']} {name}: {f[1]} {WORDS[storage]}{when}; "
                    "the least of its range is used")

        if sealed and opened:
            out.append(((storage, "Sealed"), sealed[1][0], said(sealed[0], sealed[1])))
            out.append(((storage, "Opened"), opened[0], said(opened_column, opened, True)))
        elif sealed:
            out.append(((storage,), sealed[1][0], said(sealed[0], sealed[1])))
        elif opened:
            out.append(((storage, "Opened"), opened[0], said(opened_column, opened, True)))
    return out
