"""Load data/vocabulary.toml into Structr (mealplanner/vocabulary_import.py).

    python3 tools/import_vocabulary.py            # load
    python3 tools/import_vocabulary.py --check    # validate the file against the pinned FDC subset; write nothing

Idempotent: a second run changes nothing. Meant for the owner's instance as well
as any other; needs STRUCTR_SUPERUSER_PASSWORD and STRUCTR_URL.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from mealplanner.vocabulary_import import VOCABULARY, VocabularyError, import_vocabulary, read_vocabulary

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="validate only; write nothing")
    args = parser.parse_args(argv)
    try:
        vocabulary = read_vocabulary(os.path.join(ROOT, VOCABULARY))
    except VocabularyError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(f"{VOCABULARY}: {len(vocabulary.foods)} foods, {len(vocabulary.methods)} methods, "
          f"{len(vocabulary.fdc['nutrients'])} FDC nutrients")
    if args.check:
        return 0
    client = connect(owner_data_ok=True)      # the vocabulary goes into the owner's instance too
    client.wait_until_ready()
    try:
        counts = import_vocabulary(client, vocabulary)
    except VocabularyError as exc:
        for problem in exc.problems:
            print(f"problem: {problem}")
        return 1
    print(", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
