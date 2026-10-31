"""Each recipe's energy per serving as its source prints it (the file's `source_kcal`) against what the
instance works out from its ingredients: the one check of a transcription and of the vocabulary's
matches that rests on neither (docs/recipe-format.md). Run it again after the vocabulary changes.

    python3 tools/check_source_energy.py                         # data/recipes/*.toml
    python3 tools/check_source_energy.py private/recipes/*.toml --over 30

A file without source_kcal is skipped, and said so. Each figure is worked out afresh from the recipe's
ingredients, as the instance would store it now, not read from what it stored (J28). The source's
figure is an estimate from other data too, so a difference is a question about a match, not a
verdict on it. Read-only, so meant for the owner's instance as well. Exits 1 when a recipe is not
loaded or its energy is unknown, and with --over when one is further than PCT% from its source.
"""

import argparse
import glob
import os
import statistics
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.nutrition_scope import serving_nutrient_figure
from mealplanner.recipe_import import RecipeFormatError, read_recipe
from structr_client import ReadCache

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENERGY = "Energy"               # the vocabulary's FDC nutrient, read in kcal
TOLERANCE = 0.30                # the owner's: "the error rate on calories is +-30% anyway" (J21)


@dataclass(frozen=True)
class Row:
    plan: str
    source_kcal: float
    kcal: float | None          # worked out here; None when not loaded or unknown
    why: str = ""               # why it is None, or what the figure rests on

    @property
    def off(self) -> float | None:
        """How far from the source, as a fraction of it: +0.1 is 10% more."""
        return None if self.kcal is None else (self.kcal - self.source_kcal) / self.source_kcal


def compare(client, docs) -> list[Row]:
    """A Row for each RecipeDoc with a source_kcal, its Plan found by name."""
    energy = client.get("/structr/rest/DomainType", params={"name": ENERGY})["result"]
    if len(energy) != 1:
        raise LookupError(f"{len(energy)} nutrients named {ENERGY!r} here: import the vocabulary (tools/import_vocabulary.py)")
    rows = []
    for doc in docs:
        plans = client.get("/structr/rest/Plan", params={"name": doc.plan_name})["result"]
        if len(plans) != 1:
            rows.append(Row(doc.plan_name, doc.source_kcal, None, "not loaded" if not plans else f"{len(plans)} Plans of that name"))
            continue
        plan = client.get_all("Plan", plans[0]["id"])["result"]
        figure = serving_nutrient_figure(client, plan, energy[0]["id"], "kcal", stored=False)
        rows.append(Row(doc.plan_name, doc.source_kcal, figure.amount, figure.reason or ""))
    return rows


def summary(rows: list[Row]) -> str:
    """The median distance from the sources, and how many are within 15% and within TOLERANCE."""
    offs = [abs(r.off) for r in rows if r.off is not None]
    if not offs:
        return "no recipe's energy worked out"
    return (f"{len(offs)} of {len(rows)} worked out: median {statistics.median(offs) * 100:.0f}% from the source, "
            f"{sum(o <= 0.15 for o in offs)} within 15%, {sum(o <= TOLERANCE for o in offs)} within {TOLERANCE * 100:.0f}%")


def line(row: Row) -> str:
    ours = "unknown" if row.kcal is None else f"{row.kcal:.0f}"
    off = "" if row.off is None else f"{row.off * 100:+.0f}%"
    return f"{row.plan[:52]:52} source {row.source_kcal:5.0f}  here {ours:>7} {off:>6}  {row.why}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("files", nargs="*", help="recipe files (default data/recipes/*.toml)")
    parser.add_argument("--over", type=float, metavar="PCT", help="exit 1 if a recipe is further than PCT%% from its source")
    args = parser.parse_args(argv)
    files = args.files or sorted(glob.glob(os.path.join(ROOT, "data", "recipes", "*.toml")))
    docs = []
    for path in files:
        try:
            doc = read_recipe(path)
        except RecipeFormatError as exc:
            print(f"problem: {path}: {exc}")
            return 1
        if doc.source_kcal is None:
            print(f"skipped: {path} gives no source_kcal")
        else:
            docs.append(doc)
    client = connect(owner_data_ok=True)        # read-only
    client.wait_until_ready()
    try:
        rows = compare(ReadCache(client), docs)
    except LookupError as exc:
        print(f"problem: {exc}")
        return 1
    for row in rows:
        print(line(row))
    print(summary(rows))
    failed = [r for r in rows if r.kcal is None]
    if args.over is not None:
        failed += [r for r in rows if r.off is not None and abs(r.off) * 100 > args.over]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
