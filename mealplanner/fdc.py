"""Reading USDA FoodData Central downloads, and the subset this project pins.

FoodData Central (fdc.nal.usda.gov) publishes each dataset as a zip of CSV
files; the data are public domain (CC0 1.0), and USDA asks to be credited as
the source. Only the foods named in data/vocabulary.toml are extracted, into a
small, sorted JSON file (data/fdc/<dataset>.json) that is committed, so loading
the vocabulary never needs the network or the 50 MB download
(tools/fdc_extract.py).

What is kept per food: its description, every nutrient amount per 100 g of
edible portion (food_nutrient.csv), and its household portions
(food_portion.csv: "1 cup, chopped = 160 g"), which is where a Density or a
MassPerUnit comes from. Per nutrient: its name, unit and USDA number
(nutrient.csv).
"""

from __future__ import annotations

import csv
import io
import zipfile

CITATION = ("U.S. Department of Agriculture, Agricultural Research Service. FoodData Central. "
            "fdc.nal.usda.gov. Public domain (CC0 1.0).")
UNDETERMINED_MEASURE = "9999"      # SR Legacy's measure_unit_id when the portion is described by `modifier` alone


def _rows(archive: zipfile.ZipFile, table: str):
    (member,) = [n for n in archive.namelist() if n.endswith("/" + table) or n == table]
    with archive.open(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))


def _number(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


def extract(zip_path: str, fdc_ids: set[int]) -> dict:
    """The pinned subset for these foods from one FoodData Central CSV zip.
    Raises KeyError naming any id the zip does not have."""
    wanted = {str(i) for i in fdc_ids}
    with zipfile.ZipFile(zip_path) as archive:
        foods = {r["fdc_id"]: {"description": r["description"], "data_type": r["data_type"], "nutrients": {},
                               "portions": []}
                 for r in _rows(archive, "food.csv") if r["fdc_id"] in wanted}
        missing = wanted - set(foods)
        if missing:
            raise KeyError(f"{zip_path} has no food with fdc_id {sorted(missing)}")
        for r in _rows(archive, "food_nutrient.csv"):
            if r["fdc_id"] in foods and r["amount"] != "":
                foods[r["fdc_id"]]["nutrients"][r["nutrient_id"]] = float(r["amount"])
        units = {r["id"]: r["name"] for r in _rows(archive, "measure_unit.csv")}
        for r in _rows(archive, "food_portion.csv"):
            if r["fdc_id"] not in foods or r["gram_weight"] == "":
                continue
            words = [] if r["measure_unit_id"] in ("", UNDETERMINED_MEASURE) else [units.get(r["measure_unit_id"], "")]
            words += [r["portion_description"], r["modifier"]]
            foods[r["fdc_id"]]["portions"].append({
                "amount": _number(r["amount"]) or 1.0,
                "label": " ".join(w for w in words if w).strip(),
                "grams": float(r["gram_weight"]),
            })
        used = {n for food in foods.values() for n in food["nutrients"]}
        nutrients = {r["id"]: {"name": r["name"], "unit": r["unit_name"], "number": r["nutrient_nbr"]}
                     for r in _rows(archive, "nutrient.csv") if r["id"] in used}
    for food in foods.values():
        food["portions"].sort(key=lambda p: (p["label"], p["amount"], p["grams"]))
    return {"source": {"file": zip_path.rsplit("/", 1)[-1], "citation": CITATION},
            "nutrients": dict(sorted(nutrients.items(), key=lambda kv: int(kv[0]))),
            "foods": dict(sorted(foods.items(), key=lambda kv: int(kv[0])))}
