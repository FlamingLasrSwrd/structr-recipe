"""The documents and the code must agree on the few facts both state.

Each of these drifted at some point and was found by a reviewer, not by us:
CLAUDE.md said the model was Rev 4.2 while the model said 4.3, "~35" structural
types while the code has 50, and the invariant tracker silently omitted four of
the thirty invariants."""

import pathlib
import re
import unittest

from mealplanner.structural_types import STRUCTURAL_TYPES

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


class DocumentsAgree(unittest.TestCase):
    def test_claude_md_names_the_revision_the_model_is_at(self):
        model = re.search(r"\(Rev\. ([0-9.]+)\)", (DOCS / "data-model.md").read_text().splitlines()[0])
        table = re.search(r"`data-model\.md` \(Rev\. ([0-9.]+)\)", (DOCS / "CLAUDE.md").read_text())
        self.assertIsNotNone(model, "data-model.md's title should end with its revision")
        self.assertIsNotNone(table, "CLAUDE.md's status table should name the model's revision")
        self.assertEqual(table.group(1), model.group(1))

    def test_the_model_has_a_section_recording_its_current_revision(self):
        revision = re.search(r"\(Rev\. ([0-9.]+)\)", (DOCS / "data-model.md").read_text().splitlines()[0]).group(1)
        self.assertRegex((DOCS / "data-model.md").read_text(), rf"(?m)^## \d+\. Rev {re.escape(revision)}\b")

    def test_the_documented_structural_type_count_is_the_real_one(self):
        n = len(STRUCTURAL_TYPES)
        self.assertIn(f"Get the {n} structural type names", (DOCS / "CLAUDE.md").read_text())
        self.assertIn(f"{n} types", (DOCS / "structr-build-sketch.md").read_text())


class InvariantTrackerIsComplete(unittest.TestCase):
    def test_every_invariant_from_1_to_30_appears_in_the_tracker(self):
        source = (ROOT / "mealplanner" / "domain_invariants.py").read_text()
        mentioned = set()
        for line in source.splitlines():
            entry = re.match(r"^# (\d+[a-z]?\b[^:]*):", line)
            if entry:
                mentioned |= {int(n) for n in re.findall(r"\b(\d+)[a-z]?\b", entry.group(1))}
        missing = sorted(set(range(1, 31)) - mentioned)
        self.assertEqual(missing, [], f"invariants with no entry in domain_invariants.py: {missing}")


if __name__ == "__main__":
    unittest.main()
