"""tools/backup.py with Docker faked: what a backup does in what order, what it writes, what is kept,
and that a check or a restore touches only what it should (docs/backups.md).
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("backup_tool", os.path.join(os.path.dirname(__file__), "..", "tools", "backup.py"))
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)
COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.yml"


class FakeDocker:
    """Answers the commands backup.py runs, keeps them in order, and writes the files they would."""

    def __init__(self, running=(), counts=(41455, 86653), restored=None, pages_rc=0, fail_on=None):
        self.running, self.counts, self.restored = set(running), counts, restored or counts
        self.pages_rc, self.fail_on, self.calls = pages_rc, fail_on, []

    def __call__(self, args, *, env=None, check=True):
        line = " ".join(args)
        self.calls.append(line)
        out, rc = "", 0
        if self.fail_on and self.fail_on in line:
            raise tool.BackupError(f"{self.fail_on} failed")
        if args[:2] == ["docker", "ps"]:
            project = next((a.rsplit("=", 1)[1] for a in args if a.startswith("label=com.docker.compose.project=")), None)
            names = [n for n in self.running if project is None or n.startswith(f"{project}-")]
            out = "\n".join(names)
        elif args[:2] == ["docker", "exec"]:
            n, r = self.restored if args[2].startswith(tool.VERIFY) else self.counts
            out = f"nodes, relationships\n{n}, {r}\n"
        elif args[:2] == ["docker", "compose"]:
            project, verb = args[3], args[4]
            if verb in ("stop", "down"):
                self.running = {n for n in self.running if not n.startswith(f"{project}-")}
            elif verb in ("start",) or (verb == "up" and "--no-start" not in args):
                self.running |= {f"{project}-neo4j-1"} | ({f"{project}-structr-1"} if "neo4j" not in args[5:] else set())
        elif args[:2] == ["docker", "run"]:
            mount = next((a for a in args if a.endswith(":/backups") or a.endswith(":/out")), None)
            if "dump" in args and mount:
                Path(mount.rsplit(":", 1)[0], "neo4j.dump").write_bytes(b"graph")
            m = re.search(r"tar czf /out/(\S+)", line)
            if m and mount:
                Path(mount.rsplit(":", 1)[0], m.group(1)).write_bytes(b"volume")
        elif args[0] == "tar" and args[1] == "czf":
            Path(args[2]).write_bytes(b"private")
        elif args[0] == "tar" and args[1] == "xzf":
            Path(args[-1], "private").mkdir(parents=True, exist_ok=True)
        elif args[:2] == ["git", "-C"]:
            out = "abc123\n"
        elif args[0] == "bash" and args[1].endswith("owner_stack.sh"):
            self.running |= {f"{tool.OWNER}-neo4j-1", f"{tool.OWNER}-structr-1"}
        elif "check_pages.py" in line:
            out, rc = ("0 difference(s)\n" if self.pages_rc == 0 else "2 difference(s)\n"), self.pages_rc
        return subprocess.CompletedProcess(args, rc, out, "")

    def index(self, fragment: str) -> int:
        return next(i for i, c in enumerate(self.calls) if fragment in c)


class WithATempRepo(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "repo" / "private").mkdir(parents=True)
        shutil.copy(COMPOSE, self.tmp / "repo" / "docker-compose.yml")
        (self.tmp / "repo" / ".env").write_text("NEO4J_PASSWORD=x\nSTRUCTR_SUPERUSER_PASSWORD=y\n")
        self.saved = (tool.REPO, tool.run, os.environ.get("BACKUP_DIR"), os.environ.get("BACKUP_KEEP"))
        tool.REPO = self.tmp / "repo"
        os.environ["BACKUP_DIR"] = str(self.tmp / "backups")
        os.environ.pop("BACKUP_KEEP", None)
        self.addCleanup(self.restore_globals)

    def restore_globals(self):
        tool.REPO, tool.run = self.saved[0], self.saved[1]
        for key, value in (("BACKUP_DIR", self.saved[2]), ("BACKUP_KEEP", self.saved[3])):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def docker(self, **kw):
        tool.run = FakeDocker(**kw)
        return tool.run


OWNER_UP = ("mealplanner-owner-neo4j-1", "mealplanner-owner-structr-1")


class BackingUp(WithATempRepo):
    def test_counted_then_stopped_then_dumped_and_started_again(self):
        docker = self.docker(running=OWNER_UP)
        folder = tool.now()
        self.assertTrue(tool.NAME.match(folder.name))
        self.assertLess(docker.index("cypher-shell"), docker.index("compose -p mealplanner-owner stop"))
        self.assertLess(docker.index("compose -p mealplanner-owner stop"), docker.index("database dump neo4j"))
        self.assertIn("owner_stack.sh up", docker.calls[-1] if "owner_stack" in docker.calls[-1] else " ".join(docker.calls))
        m = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(sorted(m["files"]), ["neo4j.dump", "private.tar.gz", "structr-files.tar.gz", "structr-repository.tar.gz"])
        self.assertEqual((m["counts"], m["commit"], m["images"]["neo4j"]),
                         ({"nodes": 41455, "relationships": 86653}, "abc123", tool.image("neo4j")))
        self.assertEqual(m["files"]["neo4j.dump"]["sha256"], tool.sha256(folder / "neo4j.dump"))
        self.assertFalse([p for p in folder.parent.iterdir() if p.name.startswith(".partial")])
        self.assertNotIn(".env", m["files"])
        self.assertFalse(any("NEO4J_PASSWORD=x" in c or " x " in f" {c} " for c in docker.calls))   # no password on a command line

    def test_from_stop_it_stays_stopped_and_a_stopped_stack_has_nothing_new(self):
        docker = self.docker(running=OWNER_UP)
        tool.now(leave_stopped=True)
        self.assertFalse(any("owner_stack.sh up" in c for c in docker.calls))
        docker = self.docker()
        self.assertIsNone(tool.now(leave_stopped=True))
        self.assertFalse(any(c.startswith("docker compose") for c in docker.calls))

    def test_a_stopped_stack_backed_up_on_purpose_starts_neo4j_alone_to_count(self):
        docker = self.docker()
        folder = tool.now()
        self.assertLess(docker.index("up -d neo4j"), docker.index("cypher-shell"))
        self.assertIsNotNone(json.loads((folder / "manifest.json").read_text())["counts"])
        self.assertFalse(any("owner_stack.sh up" in c for c in docker.calls))
        docker = self.docker(running=("structr-recipe-build-structr-1",))            # another stack: not counted
        folder = tool.now()
        self.assertIsNone(json.loads((folder / "manifest.json").read_text())["counts"])
        self.assertFalse(any("up -d neo4j" in c for c in docker.calls))

    def test_a_failed_backup_leaves_nothing_half_made_and_the_stack_running(self):
        docker = self.docker(running=OWNER_UP, fail_on="database dump")
        with self.assertRaises(tool.BackupError):
            tool.now()
        self.assertEqual(tool.backups(), [])
        self.assertFalse([p for p in (self.tmp / "backups").iterdir()])
        self.assertIn("owner_stack.sh up", docker.calls[-1])

    def test_the_newest_are_kept(self):
        root = self.tmp / "backups"
        for name in ("2026-10-01_090000", "2026-10-02_090000", "2026-10-03_090000-before-restore"):
            (root / name).mkdir(parents=True)
            (root / name / "manifest.json").write_text(json.dumps({"files": {}, "counts": None}))
        (root / "notes").mkdir()
        os.environ["BACKUP_KEEP"] = "2"
        self.docker(running=OWNER_UP)
        newest = tool.now()
        self.assertEqual([p.name for p in tool.backups()], [newest.name, "2026-10-03_090000-before-restore"])
        self.assertTrue((root / "notes").exists())                                   # not a backup: left alone
        self.assertEqual(tool.to_remove(["b", "a", "c"], 1), ["b", "a"])


class Checking(WithATempRepo):
    def made(self):
        self.docker(running=OWNER_UP)
        return tool.now(leave_stopped=True)

    def test_restored_in_the_throwaway_counted_checked_and_removed(self):
        folder = self.made()
        docker = self.docker()
        self.assertTrue(tool.verify(None))
        downs = [c for c in docker.calls if " down" in c]
        self.assertEqual(downs, [f"docker compose -p {tool.VERIFY} down -v"])
        self.assertFalse(any(tool.OWNER in c for c in docker.calls if c.startswith("docker compose")))
        self.assertLess(docker.index("database load neo4j"), docker.index(f"-p {tool.VERIFY} start"))
        check = json.loads((folder / "manifest.json").read_text())["verified"][-1]
        self.assertEqual((check["ok"], check["counts_match"], check["pages"]), (True, True, "0 difference(s)"))

    def test_a_short_count_or_a_page_difference_fails_and_the_throwaway_still_goes(self):
        folder = self.made()
        docker = self.docker(restored=(41000, 86653))
        self.assertFalse(tool.verify(folder.name))
        self.assertIn(f"docker compose -p {tool.VERIFY} down -v", docker.calls)
        self.docker(pages_rc=1)
        self.assertFalse(tool.verify(folder.name))
        self.docker(fail_on="database load")
        self.assertFalse(tool.verify(folder.name))
        checks = json.loads((folder / "manifest.json").read_text())["verified"]
        self.assertEqual([c["ok"] for c in checks], [False, False, False])
        self.assertIn("database load failed", checks[-1]["problem"])

    def test_not_beside_another_stack_nor_from_a_changed_file(self):
        folder = self.made()
        self.docker(running=OWNER_UP)
        with self.assertRaises(tool.BackupError):
            tool.verify(None)
        (folder / "neo4j.dump").write_bytes(b"something else")
        self.docker()
        with self.assertRaises(tool.BackupError):
            tool.verify(None)


class Restoring(WithATempRepo):
    def test_nothing_happens_unless_its_name_is_typed(self):
        self.docker(running=OWNER_UP)
        folder = tool.now(leave_stopped=True)
        docker = self.docker()
        with self.assertRaises(tool.BackupError):
            tool.restore(folder.name, answer=lambda prompt: "yes")
        self.assertFalse(any("compose" in c or "load" in c for c in docker.calls))

    def test_what_is_there_is_backed_up_first_then_replaced_and_private_set_beside(self):
        self.docker(running=OWNER_UP)
        folder = tool.now(leave_stopped=True)
        docker = self.docker(running=OWNER_UP)
        tool.restore(folder.name, answer=lambda prompt: folder.name)
        self.assertEqual(len(tool.backups()), 2)
        self.assertTrue(any(p.name.endswith("-before-restore") for p in tool.backups()))
        self.assertLess(docker.index("database dump"), docker.index("database load"))
        self.assertTrue(any(f"{tool.OWNER}_neo4j-database:/data" in c for c in docker.calls if "database load" in c))
        self.assertTrue((tool.REPO / f"private.restored-{folder.name}" / "private").is_dir())
        self.assertTrue((tool.REPO / "private").is_dir())
        self.assertFalse(any("down -v" in c for c in docker.calls))


class Parsing(unittest.TestCase):
    def test_cypher_shells_plain_output(self):
        self.assertEqual(tool.parse_counts("nodes, relationships\n41455, 86653\n"), (41455, 86653))

    def test_the_stacks_own_images(self):
        self.assertEqual(tool.image("neo4j").split(":")[0], "neo4j")
        self.assertTrue(tool.image("structr").startswith("structr/structr:"))


if __name__ == "__main__":
    unittest.main()
