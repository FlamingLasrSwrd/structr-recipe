"""tools/image_guard.sh, which tools/owner_stack.sh up runs first: a container that last ran another
Structr image than docker-compose.yml names is not started (its database would be upgraded) unless
UPGRADE=1. A fake `docker` on the PATH answers what the container runs."""

import os
import pathlib
import re
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD = ROOT / "tools" / "image_guard.sh"
NAMED = re.search(r"^ *image: *(structr/structr:\S+) *$", (ROOT / "docker-compose.yml").read_text(), re.M).group(1)


def guard(current: str | None, **env) -> subprocess.CompletedProcess:
    """Run the guard with a docker that says the container runs `current` (None: no such container)."""
    with tempfile.TemporaryDirectory() as bin_dir:
        fake = pathlib.Path(bin_dir) / "docker"
        fake.write_text("#!/bin/sh\n" + (f"echo '{current}'\n" if current else "exit 1\n"))
        fake.chmod(0o755)
        return subprocess.run(["bash", str(GUARD), "mealplanner-owner-structr-1"], capture_output=True, text=True,
                              env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "UPGRADE": "", **env})


class Guard(unittest.TestCase):
    def test_another_image_is_refused_with_the_way_on(self):
        done = guard("structr/structr:6.0.0")
        self.assertEqual(done.returncode, 1)
        self.assertIn(f"last ran structr/structr:6.0.0; docker-compose.yml now names {NAMED}", done.stderr)
        for step in ("python3 tools/backup.py now", "STRUCTR_MIGRATION_MODE=dry-run UPGRADE=1", "UPGRADE=1 bash tools/owner_stack.sh up"):
            self.assertIn(step, done.stderr)

    def test_the_same_image_starts(self):
        self.assertEqual(guard(NAMED).returncode, 0)

    def test_a_container_not_made_yet_starts(self):
        self.assertEqual(guard(None).returncode, 0)

    def test_asked_for_it_starts(self):
        self.assertEqual(guard("structr/structr:6.0.0", UPGRADE="1").returncode, 0)

    def test_owner_stack_up_runs_it_before_starting(self):
        up = (ROOT / "tools" / "owner_stack.sh").read_text().split("  up)", 1)[1].split(";;", 1)[0]
        self.assertLess(up.index("image_guard.sh"), up.index("compose up -d"))


if __name__ == "__main__":
    unittest.main()
