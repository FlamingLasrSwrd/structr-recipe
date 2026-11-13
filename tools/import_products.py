"""Load products, with their barcodes and package sizes, into Structr (mealplanner/products.py).

    python3 tools/import_products.py private/products.toml            # load (after tools/import_vocabulary.py)
    python3 tools/import_products.py private/products.toml --check    # read the file; write nothing
    python3 tools/import_products.py --find BARCODE                   # the product a barcode names

A product is a packaged food: a Type below the food it is a kind of, which its barcodes denote, with
what one package holds (docs/pantry.md, "Products and barcodes"). Idempotent. Which products a
household buys is its own data, so the file lives in private/, which git ignores. Writes the
instance's data, the owner's included; needs STRUCTR_TOOLS_PASSWORD and STRUCTR_URL.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner import products
from mealplanner.connection import connect
from mealplanner.vocabulary_import import VocabularyError


def show(found: products.Found) -> str:
    size = "no package size" if found.amount is None else f"{found.amount:g} {found.unit} a package"
    return f"{found.gtin}: {found.product} ({found.food}), {size}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("file", nargs="?", help="the products file")
    parser.add_argument("--check", action="store_true", help="read the file only; write nothing")
    parser.add_argument("--find", metavar="BARCODE", help="say which product a barcode names")
    args = parser.parse_args(argv)
    if bool(args.file) == bool(args.find):
        parser.error("give a products file, or --find BARCODE")
    try:
        if args.find:
            products.normalize(args.find)
            client = connect(owner_data_ok=True)
            client.wait_until_ready()
            found = products.find(client, args.find)
            print(show(found) if found else f"no product has barcode {products.normalize(args.find)}")
            return 0 if found else 1
        listed = products.read_products(args.file)
        print(f"{len(listed)} product(s), {sum(len(p.barcodes) for p in listed)} barcode(s)")
        if args.check:
            return 0
        client = connect(owner_data_ok=True)        # a household's own products: the owner's too
        client.wait_until_ready()
        counts = products.import_products(client, listed)
    except (products.ProductError, VocabularyError) as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    except (OSError, ValueError) as exc:
        print(f"problem: {exc}")
        return 1
    print(", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
