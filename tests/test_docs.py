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


class OperatingDocsPointAtRealFiles(unittest.TestCase):
    """CLAUDE.md and CLOUD.md tell a session what to run. A path that no longer exists there is a
    session that fails on its first command, so every repo path they name must exist."""

    PREFIXES = ("tools/", "cloud/", "scripts/", "docs/", "mealplanner/", "tests/", "structr_client/")

    def named_paths(self, filename):
        text = (ROOT / filename).read_text()
        found = set()
        for token in re.findall(r"`([^`\s]+)`", text):
            if token.startswith(self.PREFIXES) and not any(c in token for c in "*<>{}"):
                found.add(token.rstrip(".,:;"))
        return found

    def test_every_path_named_in_the_operating_docs_exists(self):
        for filename in ("CLAUDE.md", "CLOUD.md"):
            paths = self.named_paths(filename)
            self.assertTrue(paths, f"{filename} names no repo paths: is the pattern wrong?")
            missing = sorted(p for p in paths if not (ROOT / p).exists())
            self.assertEqual(missing, [], f"{filename} names files that do not exist: {missing}")

    def test_the_setup_script_is_the_one_the_guide_tells_you_to_paste(self):
        self.assertIn("cloud/setup.sh", (ROOT / "CLOUD.md").read_text())


if __name__ == "__main__":
    unittest.main()
