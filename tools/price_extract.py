"""Pin the public prices data/prices.toml refers to (mealplanner/prices.py).

    python3 tools/price_extract.py --fetch     # ask the BLS API for the named items and the CPI first
    python3 tools/price_extract.py             # pin from what is in .cache/prices/

Reads, from the git-ignored .cache/prices/:

  pp_national_average_prices_csv.csv   USDA ERS Purchase to Plate National Average Prices
                                       (unzipped from www.ers.usda.gov/media/6557/...)
  bls/api.json                         BLS Public Data API answers, saved by --fetch

and writes data/prices/ppnap.json (the 2017-18 prices of the FNDDS codes the file names) and
data/prices/bls.json (for each named BLS item the latest price for the U.S. city average and,
if it is within a year of that, for the West region; and the CPI for food at home, the mean
of 2017-18 and the latest month, which bring the 2017-18 prices forward). Sorted, so a re-run
changes nothing unless the file or the data did. Commit the data/prices files.

--fetch uses the API without registration (version 1: 25 series a request, 25 requests a day),
since the BLS download site refuses scripted requests that do not give a contact address.
"""

import argparse
import csv
import json
import os
import sys
import tomllib
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.prices import BLS_PIN, PPNAP_PIN, PRICES, parse_prices

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "prices")
PPNAP_CSV = os.path.join(CACHE, "pp_national_average_prices_csv.csv")
BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
CPI_SERIES = "CUUR0000SAF11"          # CPI-U, food at home, U.S. city average, not seasonally adjusted
PPNAP_YEAR = "2017/2018"
AREAS = {"US": "0000", "West": "0400"}


def _post(series: list[str], start: int, end: int) -> list[dict]:
    body = json.dumps({"seriesid": series, "startyear": str(start), "endyear": str(end)}).encode()
    request = urllib.request.Request(BLS_API, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        answer = json.load(response)
    if answer.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API: {answer.get('status')} {answer.get('message')}")
    return answer["Results"]["series"]


def fetch(book, year: int) -> str:
    series = sorted(f"APU{area}{code}" for code in book.bls_items for area in AREAS.values())
    answers = []
    for k in range(0, len(series), 25):
        answers.extend(_post(series[k:k + 25], year - 1, year))
    answers.extend(_post([CPI_SERIES], 2017, year))
    os.makedirs(os.path.join(CACHE, "bls"), exist_ok=True)
    path = os.path.join(CACHE, "bls", "api.json")
    with open(path, "w") as fh:
        json.dump({"series": answers}, fh)
    return path


def _points(data: list[dict]) -> list[tuple[str, float]]:
    """(YYYY-MM, value) for every monthly figure, newest first; '-' (not published) is skipped."""
    out = []
    for d in data:
        if not d["period"].startswith("M") or d["period"] == "M13":
            continue
        try:
            out.append((f"{d['year']}-{d['period'][1:]}", float(d["value"])))
        except ValueError:
            continue
    return sorted(out, reverse=True)


def _months(period: str) -> int:
    year, month = period.split("-")
    return int(year) * 12 + int(month)


def pin_bls(book, answers: dict) -> dict:
    by_id = {s["seriesID"]: _points(s["data"]) for s in answers["series"]}
    cpi = by_id[CPI_SERIES]
    base = [v for p, v in cpi if p[:4] in ("2017", "2018")]
    if len(base) != 24:
        raise RuntimeError(f"expected 24 months of {CPI_SERIES} for 2017-18, found {len(base)}")
    items = {}
    for code in sorted(book.bls_items):
        figures = {}
        us = by_id.get(f"APU{AREAS['US']}{code}") or []
        if us:
            figures["US"] = {"period": us[0][0], "value": us[0][1]}
            west = by_id.get(f"APU{AREAS['West']}{code}") or []
            if west and _months(us[0][0]) - _months(west[0][0]) <= 12:
                figures["West"] = {"period": west[0][0], "value": west[0][1]}
        items[code] = figures
    return {
        "source": "U.S. Bureau of Labor Statistics, CPI Average Price Data (series APU<area><item>) and "
                  f"CPI-U food at home ({CPI_SERIES}), via the BLS Public Data API",
        "cpi": {"series": CPI_SERIES, "base": {"period": "2017-2018 mean", "value": round(sum(base) / 24, 4)},
                "latest": {"period": cpi[0][0], "value": cpi[0][1]}},
        "items": items,
    }


def pin_ppnap(book) -> dict:
    wanted = {e.ppnap for e in book.entries if e.ppnap}
    foods = {}
    with open(PPNAP_CSV, encoding="latin-1") as fh:
        for row in csv.DictReader(fh):
            if row["year"] == PPNAP_YEAR and row["food_code"] in wanted:
                foods[row["food_code"]] = {"description": row["food_description"], "price_100g": float(row["price_100gm"])}
    missing = sorted(wanted - set(foods))
    if missing:
        raise RuntimeError(f"FNDDS codes not in Purchase to Plate {PPNAP_YEAR}: {missing}")
    return {"source": "USDA Economic Research Service, Purchase to Plate National Average Prices for NHANES "
                      "(PP-NAP), March 2023; price per 100 edible grams in nominal dollars of the scanner data's year",
            "year": PPNAP_YEAR, "foods": dict(sorted(foods.items()))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fetch", action="store_true", help="ask the BLS API first")
    parser.add_argument("--year", type=int, default=None, help="with --fetch: the latest year to ask for (default: this year)")
    args = parser.parse_args(argv)
    with open(os.path.join(ROOT, PRICES), "rb") as fh:
        book = parse_prices(tomllib.load(fh))
    if args.fetch:
        from datetime import date
        print(f"saved {fetch(book, args.year or date.today().year)}")
    with open(os.path.join(CACHE, "bls", "api.json")) as fh:
        bls = pin_bls(book, json.load(fh))
    ppnap = pin_ppnap(book)
    os.makedirs(os.path.join(ROOT, "data", "prices"), exist_ok=True)
    for rel, body in ((BLS_PIN, bls), (PPNAP_PIN, ppnap)):
        with open(os.path.join(ROOT, rel), "w") as fh:
            json.dump(body, fh, indent=1, sort_keys=True)
            fh.write("\n")
    west = sum("West" in f for f in bls["items"].values())
    print(f"wrote {BLS_PIN}: {len(bls['items'])} items ({west} with a West price), CPI {bls['cpi']['latest']['period']} "
          f"{bls['cpi']['latest']['value']:g} over {bls['cpi']['base']['value']:g}; {PPNAP_PIN}: {len(ppnap['foods'])} foods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
