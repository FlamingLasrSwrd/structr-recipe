"""Reading USDA FoodData Central data, and the subset this project pins.

FoodData Central (fdc.nal.usda.gov) data are public domain (CC0 1.0), and USDA
asks to be credited as the source. Only the foods data/vocabulary.toml names
are extracted, into small, sorted JSON files (data/fdc/<dataset>.json) that are
committed, so loading the vocabulary never needs the network or a download
(tools/fdc_extract.py). Four datasets, one record shape:

  SR Legacy, Foundation   CSV zips (extract)
  FNDDS (survey foods)    a JSON zip (extract_survey); 65 nutrients, complete for every food
  Branded                 label data, from saved FDC API search results (extract_branded);
                          per 100 g as FDC derives it from the label, so a small serving's
                          rounding (a 0.5 g spice serving reads 0 kcal) makes it unreliable

A record: its description, every nutrient amount per 100 g of edible portion,
and its household portions ("1 cup, chopped = 160 g"), which is where a Density
or a MassPerUnit comes from. Per nutrient: its name, unit and USDA number.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import zipfile

CITATION = ("U.S. Department of Agriculture, Agricultural Research Service. FoodData Central. "
            "fdc.nal.usda.gov. Public domain (CC0 1.0).")
UNDETERMINED_MEASURE = "9999"      # SR Legacy's measure_unit_id when the portion is described by `modifier` alone


def _rows(archive: zipfile.ZipFile, table: str):
    (member,) = [n for n in archive.namelist() if n.endswith("/" + table) or n == table]
    with archive.open(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"))


def unit_name(text: str) -> str:
    """FDC's unit names, one spelling: "µg", "mcg" and "UG" are all "UG"."""
    text = (text or "").strip().replace("µ", "u").replace("μ", "u").upper()
    return "UG" if text == "MCG" else text


def _number(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


def extract(zip_path: str, fdc_ids: set[int], strict: bool = True) -> dict:
    """The pinned subset for these foods from one FoodData Central CSV zip.
    Raises KeyError naming any id the zip does not have, unless not strict (then
    it returns the ones it has)."""
    wanted = {str(i) for i in fdc_ids}
    with zipfile.ZipFile(zip_path) as archive:
        foods = {r["fdc_id"]: {"description": r["description"], "data_type": r["data_type"], "nutrients": {},
                               "portions": []}
                 for r in _rows(archive, "food.csv") if r["fdc_id"] in wanted}
        missing = wanted - set(foods)
        if missing and strict:
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
        nutrients = {r["id"]: {"name": r["name"], "unit": unit_name(r["unit_name"]), "number": r["nutrient_nbr"]}
                     for r in _rows(archive, "nutrient.csv") if r["id"] in used}
    return _subset(zip_path, nutrients, foods)


def _subset(path: str, nutrients: dict, foods: dict) -> dict:
    for food in foods.values():
        food["portions"].sort(key=lambda p: (p["label"], p["amount"], p["grams"]))
    return {"source": {"file": os.path.basename(path.rstrip("/")), "citation": CITATION},
            "nutrients": dict(sorted(nutrients.items(), key=lambda kv: int(kv[0]))),
            "foods": dict(sorted(foods.items(), key=lambda kv: int(kv[0])))}


_AMOUNT = re.compile(r"^\s*(\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)\s*(.*)$")
_UNIT_WORDS = {"tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp", "tsp": "tsp", "teaspoon": "tsp",
               "teaspoons": "tsp", "cup": "cup", "cups": "cup", "oz": "oz", "onz": "oz", "fl oz": "fl oz"}


def household(text: str | None) -> tuple[float, str] | None:
    """("1/4 tsp" -> (0.25, "tsp")), ("1 Tbsp" -> (1.0, "tbsp")), ("1 tsp (5g)" -> (1.0, "tsp")),
    ("1 cup, shredded" -> (1.0, "cup, shredded")); None if it does not start with an amount."""
    match = _AMOUNT.match(text or "")
    if not match:
        return None
    number, rest = match.groups()
    if " " in number:
        whole, fraction = number.split()
        amount = float(whole) + _fraction(fraction)
    else:
        amount = _fraction(number) if "/" in number else float(number)
    rest = re.sub(r"\s*\(.*\)\s*$", "", rest).strip().rstrip(".").strip()
    if not rest or amount <= 0:
        return None
    lower = rest.lower()
    for word, unit in sorted(_UNIT_WORDS.items(), key=lambda kv: -len(kv[0])):
        if lower == word or lower.startswith(word + " ") or lower.startswith(word + ",") or lower.startswith(word + "."):
            return amount, unit + rest[len(word):].rstrip(".")
    return amount, rest


def _fraction(text: str) -> float:
    top, bottom = text.split("/")
    return float(top) / float(bottom)


def extract_survey(zip_path: str, fdc_ids: set[int], strict: bool = True) -> dict:
    """The pinned subset for these foods from the FNDDS (survey foods) JSON zip."""
    wanted = {int(i) for i in fdc_ids}
    with zipfile.ZipFile(zip_path) as archive:
        (member,) = [n for n in archive.namelist() if n.endswith(".json")]
        records = json.load(archive.open(member))["SurveyFoods"]
    foods, nutrients = {}, {}
    for record in records:
        if record["fdcId"] not in wanted:
            continue
        food = {"description": record["description"], "data_type": "survey_fndds_food", "nutrients": {},
                "portions": []}
        for n in record.get("foodNutrients", []):
            if n.get("amount") is None:
                continue
            nid = str(n["nutrient"]["id"])
            food["nutrients"][nid] = float(n["amount"])
            nutrients[nid] = {"name": n["nutrient"]["name"], "unit": unit_name(n["nutrient"]["unitName"]),
                              "number": n["nutrient"].get("number", "")}
        for p in record.get("foodPortions", []):
            parsed = household(p.get("portionDescription"))
            if parsed and p.get("gramWeight"):
                food["portions"].append({"amount": parsed[0], "label": parsed[1], "grams": float(p["gramWeight"])})
        foods[str(record["fdcId"])] = food
    missing = {str(i) for i in wanted} - set(foods)
    if missing and strict:
        raise KeyError(f"{zip_path} has no food with fdc_id {sorted(missing)}")
    return _subset(zip_path, nutrients, foods)


class ImplausibleRecord(ValueError):
    """A branded record whose label cannot be right (more than 100 g of nutrients in 100 g)."""


GRAM_UNITS = {"g", "grm"}


def plausible(food: dict, nutrients: dict) -> str | None:
    """Why a label record cannot be right, or None. Labels are typed by hand and
    rescaled to 100 g by FDC; a serving entered as 100 g, say, gives carbohydrate
    of 184 g per 100 g, which is impossible."""
    grams = sum(v for k, v in food["nutrients"].items()
                if k in ("1003", "1004", "1005") and (nutrients.get(k) or {}).get("unit") == "G")
    if grams > 100.5:
        return f"protein, fat and carbohydrate add up to {grams:g} g per 100 g"
    energy = food["nutrients"].get("1008")
    if energy is not None and energy > 900:
        return f"{energy:g} kcal per 100 g is more than pure fat"
    return None


def extract_branded(search_dir: str, fdc_ids: set[int], strict: bool = True) -> dict:
    """The pinned subset for these branded foods, from saved FDC API search results
    (tools/fdc_extract.py --search writes them). A record sold by volume (a serving
    in mL) is refused: its figures are per 100 mL, not per 100 g. So is an implausible one."""
    wanted = {int(i) for i in fdc_ids}
    foods, nutrients = {}, {}
    for name in sorted(os.listdir(search_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(search_dir, name)) as fh:
            results = json.load(fh).get("foods", [])
        for record in results:
            if record["fdcId"] not in wanted or str(record["fdcId"]) in foods:
                continue
            if (record.get("servingSizeUnit") or "").lower() not in GRAM_UNITS:
                raise ImplausibleRecord(f"branded {record['fdcId']} is served in {record.get('servingSizeUnit')!r}, "
                                        f"so its figures are not per 100 g")
            food = {"description": record["description"], "data_type": "branded_food",
                    "brand": record.get("brandName") or record.get("brandOwner") or "",
                    "gtin": record.get("gtinUpc", ""), "nutrients": {}, "portions": []}
            for n in record.get("foodNutrients", []):
                if n.get("value") is None:
                    continue
                nid = str(n["nutrientId"])
                food["nutrients"][nid] = float(n["value"])
                nutrients.setdefault(nid, {"name": n["nutrientName"], "unit": unit_name(n["unitName"]),
                                           "number": n.get("nutrientNumber", "")})
            parsed = household(record.get("householdServingFullText"))
            if parsed and record.get("servingSize"):
                food["portions"].append({"amount": parsed[0], "label": parsed[1], "grams": float(record["servingSize"])})
            problem = plausible(food, nutrients)
            if problem:
                raise ImplausibleRecord(f"branded {record['fdcId']} ({food['brand']} {food['description']}): {problem}")
            foods[str(record["fdcId"])] = food
    missing = {str(i) for i in wanted} - set(foods)
    if missing and strict:
        raise KeyError(f"no saved search result has branded fdc_id {sorted(missing)}")
    used = {n for food in foods.values() for n in food["nutrients"]}
    return _subset(search_dir, {k: v for k, v in nutrients.items() if k in used}, foods)
