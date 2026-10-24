"""USDA's Table of Nutrient Retention Factors, Release 6 (2007), read and pinned.

The table (retn06.txt, from ars.usda.gov) gives, for a food group cooked one way (a row: "VEG,GREENS,
BOILED,WATER COVER DRAIN"), the percent of each nutrient left after cooking. One line per row and
nutrient, caret-separated, each field in tildes:

    ~3005~^~11~^~VEG,GREENS,BOILED,WATER COVER DRAIN~^~401~^~Vitamin C, total ascorbic acid~^~55~^~05/2003~

that is: row code, food group, description, SR nutrient number, nutrient name, percent, date. A blank
percent is no figure. tools/retention_extract.py pins the rows data/vocabulary.toml uses into
data/retention/usda_r6.json, which tools/import_vocabulary.py reads (mealplanner/vocabulary_import.py).
"""

from __future__ import annotations

import hashlib

CITATION = ("USDA Table of Nutrient Retention Factors, Release 6 (2007), U.S. Department of Agriculture, "
            "Agricultural Research Service, Nutrient Data Laboratory. Public domain.")


def read_table(path: str) -> dict:
    """{"rows": {code: {"description", "group", "factors": {SR number: percent}}}, "nutrients": {SR number: name}}."""
    rows: dict[str, dict] = {}
    nutrients: dict[str, str] = {}
    with open(path, encoding="latin-1") as fh:
        for line in fh:
            fields = [f.strip().strip("~") for f in line.rstrip("\r\n").split("^")]
            if len(fields) < 6:
                continue
            code, group, description, number, name, percent = fields[:6]
            row = rows.setdefault(code, {"description": description, "group": group, "factors": {}})
            nutrients.setdefault(number, name)
            if percent:
                row["factors"][number] = float(percent)
    return {"rows": rows, "nutrients": nutrients}


def pin(path: str, codes: set[str], numbers: set[str]) -> dict:
    """The rows `codes` with only the nutrients `numbers`, sorted, with the file's checksum. An
    unknown code is an error: the vocabulary names a row the table does not have."""
    table = read_table(path)
    missing = sorted(codes - set(table["rows"]))
    if missing:
        raise KeyError(f"the table has no rows {missing}")
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return {
        "source": CITATION, "file": "retn06.txt", "sha256": digest,
        "nutrients": {n: table["nutrients"][n] for n in sorted(numbers) if n in table["nutrients"]},
        "rows": {code: {**table["rows"][code],
                        "factors": {n: p for n, p in sorted(table["rows"][code]["factors"].items()) if n in numbers}}
                 for code in sorted(codes)},
    }
