"""The operational tooling: the shell scripts a fresh environment runs.

The shell scripts are checked without Docker or Structr: their syntax, their environment
handling, and the order they would run the build scripts in. What they do to a real stack is
exercised by running them (see CLOUD.md's first-run checklist)."""

import http.server
import os
import pathlib
import subprocess
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

SCRIPTS = ["tools/wait_for_structr.sh", "tools/rebuild.sh", "tools/owner_stack.sh", "cloud/bootstrap.sh", "cloud/setup.sh",
           ".githooks/pre-push"]


def write(directory, name, text):
    (directory / name).write_text(text)


class ShellScripts(unittest.TestCase):
    def test_each_script_is_valid_bash_and_executable(self):
        for name in SCRIPTS:
            path = ROOT / name
            self.assertTrue(path.exists(), name)
            self.assertTrue(os.access(path, os.X_OK), f"{name} is not executable")
            self.assertEqual(subprocess.run(["bash", "-n", str(path)]).returncode, 0, name)

    def test_each_script_starts_with_a_shebang(self):
        for name in SCRIPTS:
            self.assertTrue((ROOT / name).read_text().startswith("#!"), name)

    def run_script(self, *args, cwd, env_extra=None, env_drop=()):
        env = {k: v for k, v in os.environ.items() if k not in env_drop}
        env.update(env_extra or {})
        return subprocess.run(["bash", *args], cwd=cwd, env=env, capture_output=True, text=True)

    def test_rebuild_lists_the_scripts_in_build_order_without_running_them(self):
        result = self.run_script(str(ROOT / "tools/rebuild.sh"), cwd=ROOT,
                                 env_extra={"DRY_RUN": "1", "STRUCTR_SUPERUSER_PASSWORD": "x", "STRUCTR_TOOLS_PASSWORD": "y"})
        self.assertEqual(result.returncode, 0, result.stderr)
        listed = result.stdout.split()
        self.assertEqual(listed, sorted(listed, key=lambda p: [int(t) if t.isdigit() else t for t in
                                                                __import__("re").split(r"(\d+)", p)]))
        self.assertLess(listed.index("scripts/03a_build_metamodel_schema.py"), listed.index("scripts/03b_seed_domaintype_chain.py"))
        self.assertLess(listed.index("scripts/09_culinary_role_test.py"), listed.index("scripts/10a_build_meal_planning_schema.py"))
        self.assertEqual(listed[0], "scripts/00_verify_client.py")
        self.assertEqual(len(listed), len(list((ROOT / "scripts").glob("*.py"))))

    def test_rebuild_refuses_to_run_without_either_password(self):
        for missing, present in (("STRUCTR_SUPERUSER_PASSWORD", "STRUCTR_TOOLS_PASSWORD"),
                                 ("STRUCTR_TOOLS_PASSWORD", "STRUCTR_SUPERUSER_PASSWORD")):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                # a copy of the tools with no .env beside them, and the one variable unset
                (pathlib.Path(tmp) / "tools").mkdir()
                for name in ("rebuild.sh", "wait_for_structr.sh"):
                    (pathlib.Path(tmp) / "tools" / name).write_text((ROOT / "tools" / name).read_text())
                result = self.run_script(str(pathlib.Path(tmp) / "tools/rebuild.sh"), cwd=tmp,
                                         env_drop=(missing,), env_extra={present: "x"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(missing, result.stderr)

    def bootstrap_copy(self, tmp):
        tmp = pathlib.Path(tmp)
        (tmp / "cloud").mkdir()
        (tmp / "cloud" / "bootstrap.sh").write_text((ROOT / "cloud" / "bootstrap.sh").read_text())
        return tmp

    def test_bootstrap_generates_passwords_and_hides_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.bootstrap_copy(tmp)
            result = self.run_script(str(tmp / "cloud/bootstrap.sh"), "--env-only", cwd=tmp,
                                     env_drop=("NEO4J_PASSWORD", "STRUCTR_SUPERUSER_PASSWORD", "STRUCTR_TOOLS_PASSWORD"))
            self.assertEqual(result.returncode, 0, result.stderr)
            values = dict(line.split("=", 1) for line in (tmp / ".env").read_text().split())
            self.assertEqual(set(values), {"NEO4J_PASSWORD", "STRUCTR_SUPERUSER_PASSWORD", "STRUCTR_TOOLS_PASSWORD"})
            self.assertTrue(all(len(v) >= 24 for v in values.values()))
            self.assertEqual(len(set(values.values())), 3)                     # three passwords, not one thrice
            for value in values.values():
                self.assertNotIn(value, result.stdout + result.stderr)
            self.assertEqual(oct((tmp / ".env").stat().st_mode & 0o777), "0o600")

    def test_bootstrap_uses_the_environments_variables_when_they_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.bootstrap_copy(tmp)
            result = self.run_script(str(tmp / "cloud/bootstrap.sh"), "--env-only", cwd=tmp,
                                     env_extra={"NEO4J_PASSWORD": "from-the-environment-a",
                                                "STRUCTR_SUPERUSER_PASSWORD": "from-the-environment-b",
                                                "STRUCTR_TOOLS_PASSWORD": "from-the-environment-c"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((tmp / ".env").read_text(),
                             "NEO4J_PASSWORD=from-the-environment-a\nSTRUCTR_SUPERUSER_PASSWORD=from-the-environment-b\n"
                             "STRUCTR_TOOLS_PASSWORD=from-the-environment-c\n")
            self.assertIn("taken from the environment", result.stdout)

    def test_bootstrap_never_overwrites_an_existing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.bootstrap_copy(tmp)
            mine = "NEO4J_PASSWORD=mine\nSTRUCTR_SUPERUSER_PASSWORD=mine\nSTRUCTR_TOOLS_PASSWORD=mine\n"
            (tmp / ".env").write_text(mine)
            result = self.run_script(str(tmp / "cloud/bootstrap.sh"), "--env-only", cwd=tmp,
                                     env_extra={"STRUCTR_TOOLS_PASSWORD": "not-this-one"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((tmp / ".env").read_text(), mine)

    def test_bootstrap_adds_the_tools_password_to_an_older_env_and_changes_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.bootstrap_copy(tmp)
            older = "NEO4J_PASSWORD=mine\nSTRUCTR_SUPERUSER_PASSWORD=mine\n"
            (tmp / ".env").write_text(older)
            (tmp / ".env").chmod(0o600)
            result = self.run_script(str(tmp / "cloud/bootstrap.sh"), "--env-only", cwd=tmp,
                                     env_drop=("STRUCTR_TOOLS_PASSWORD",))
            self.assertEqual(result.returncode, 0, result.stderr)
            text = (tmp / ".env").read_text()
            self.assertTrue(text.startswith(older))
            added = text[len(older):].split()
            self.assertEqual(len(added), 1)
            name, value = added[0].split("=", 1)
            self.assertEqual(name, "STRUCTR_TOOLS_PASSWORD")
            self.assertGreaterEqual(len(value), 24)
            self.assertNotIn(value, result.stdout + result.stderr)
            self.assertEqual(oct((tmp / ".env").stat().st_mode & 0o777), "0o600")
            again = self.run_script(str(tmp / "cloud/bootstrap.sh"), "--env-only", cwd=tmp)
            self.assertEqual((tmp / ".env").read_text(), text)                 # added once, not each run
            self.assertIn("leaving it alone", again.stdout)

    def test_bootstrap_rejects_an_unknown_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.bootstrap_copy(tmp)
            self.assertEqual(self.run_script(str(tmp / "cloud/bootstrap.sh"), "--frobnicate", cwd=tmp).returncode, 2)

    def test_the_owner_stack_has_its_own_project_and_port_and_never_deletes_volumes(self):
        result = self.run_script(str(ROOT / "tools/owner_stack.sh"), "url", cwd=ROOT)
        self.assertEqual(result.stdout.strip(), "http://localhost:8085")
        result = self.run_script(str(ROOT / "tools/owner_stack.sh"), "url", cwd=ROOT, env_extra={"OWNER_PORT": "9001"})
        self.assertEqual(result.stdout.strip(), "http://localhost:9001")
        text = (ROOT / "tools/owner_stack.sh").read_text()
        commands = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
        self.assertFalse(any("down" in line for line in commands), "the owner stack's script must never take it down")
        self.assertIn('docker compose -p "$project"', text)

    def test_the_owner_stack_shows_its_usage_for_an_unknown_command(self):
        result = self.run_script(str(ROOT / "tools/owner_stack.sh"), "frobnicate", cwd=ROOT)
        self.assertEqual(result.returncode, 2)
        self.assertIn("down -v", result.stdout)                    # the warning is part of the usage

    def test_the_setup_script_always_exits_zero_and_pins_what_the_repo_pins(self):
        text = (ROOT / "cloud/setup.sh").read_text()
        self.assertTrue(text.rstrip().endswith("exit 0"))
        solver = (ROOT / "requirements-solver.txt").read_text()
        pin = next(line for line in solver.splitlines() if line.startswith("ortools=="))
        self.assertIn(pin, text)                                    # the pin here must match requirements-solver.txt
        compose = (ROOT / "docker-compose.yml").read_text()
        for line in compose.splitlines():
            if line.strip().startswith("image:"):
                self.assertIn(line.split("image:")[1].strip(), text)   # every image the stack uses is pre-pulled


class PrePushHook(unittest.TestCase):
    """.githooks/pre-push in a throwaway repository whose checks are stand-ins that pass or fail as told."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = pathlib.Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / ".githooks").mkdir()
        (self.repo / ".githooks" / "pre-push").write_text((ROOT / ".githooks" / "pre-push").read_text())
        for folder in ("tests", "tools", "scripts"):
            (self.repo / folder).mkdir()
        (self.repo / "tests" / "__init__.py").write_text("")
        self.ran = self.repo / "ran.txt"
        self.check("tests/test_stand_in.py", "import unittest\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        {body}\n")
        self.check("tools/check_names.py")
        self.check("scripts/23a_schema_drift_test.py")

    def check(self, name, template="{body}\n", fails=False):
        record = f"open({str(self.ran)!r}, 'a').write({name!r} + '\\n')"
        body = record + ("; raise SystemExit('broken on purpose')" if fails else "")
        if name.startswith("tests/"):
            body = record + ("; self.fail('broken on purpose')" if fails else "")
        (self.repo / name).write_text(template.format(body=body))

    def run_hook(self, **env):
        return subprocess.run(["bash", str(self.repo / ".githooks" / "pre-push")], cwd=self.repo, capture_output=True, text=True,
                              env={**os.environ, "SOLVER_PYTHON": "python3", **env})

    def test_every_check_runs_and_the_push_goes_ahead(self):
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.ran.read_text().split(), ["tests/test_stand_in.py", "tests/test_stand_in.py",   # both interpreters
                                                        "tools/check_names.py", "scripts/23a_schema_drift_test.py"])
        self.assertIn("all checks passed", result.stdout)

    def test_a_failing_test_stops_the_push_and_shows_why(self):
        self.check("tests/test_stand_in.py", "import unittest\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        {body}\n",
                   fails=True)
        result = self.run_hook()
        self.assertEqual(result.returncode, 1)
        self.assertIn("tests (python3) FAILED", result.stdout)
        self.assertIn("broken on purpose", result.stdout)
        self.assertEqual(self.ran.read_text().split(), ["tests/test_stand_in.py"])      # it stops at the first failure

    def test_each_later_check_also_stops_it(self):
        for name in ("tools/check_names.py", "scripts/23a_schema_drift_test.py"):
            with self.subTest(name=name):
                self.setUp()
                self.check(name, fails=True)
                result = self.run_hook()
                self.assertEqual(result.returncode, 1, name)
                self.assertIn("FAILED", result.stdout)

    def test_without_an_interpreter_that_has_or_tools_it_says_so(self):
        hook = self.repo / ".githooks" / "pre-push"            # the cloud's place for one, made to point nowhere
        hook.write_text(hook.read_text().replace("/opt/solver-venv/bin/python", str(self.repo / "no-such-venv/python")))
        result = self.run_hook(SOLVER_PYTHON="")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no interpreter with OR-tools", result.stdout)
        self.assertEqual(self.ran.read_text().split().count("tests/test_stand_in.py"), 1)


FAKE_DOCKER = """#!/usr/bin/env bash
# stands in for docker: the daemon answers once $FAKE_STATE/daemon exists; an image is here once
# $FAKE_STATE/have-<image> exists; a pull succeeds from its FAKE_PULL_OK_AT-th try on
state="$FAKE_STATE"
echo "$*" >> "$state/calls"
case "$1" in
  info) [ -f "$state/daemon" ] ;;
  compose) case "$2" in config) printf 'neo4j:test\\nstructr:test\\n' ;; up) exit 0 ;; esac ;;
  image) [ -f "$state/have-$3" ] ;;
  pull) n=$(( $(cat "$state/pulls-$3" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$state/pulls-$3"
        if [ "$n" -ge "${FAKE_PULL_OK_AT:-1}" ]; then touch "$state/have-$3"; else exit 1; fi ;;
esac
"""


class BootstrapStartsTheStack(unittest.TestCase):
    """cloud/bootstrap.sh past --env-only, against stand-ins for docker, service and dockerd."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = pathlib.Path(self.tmp.name)
        for name in ("cloud/bootstrap.sh", "tools/wait_for_structr.sh"):
            (self.repo / name).parent.mkdir(exist_ok=True)
            (self.repo / name).write_text((ROOT / name).read_text())
        self.bin = self.repo / "bin"
        self.state = self.repo / "state"
        self.bin.mkdir()
        self.state.mkdir()
        for name, body in (("docker", FAKE_DOCKER), ("service", "#!/usr/bin/env bash\nexit 1\n"),
                           ("dockerd", '#!/usr/bin/env bash\ntouch "$FAKE_STATE/daemon"\n')):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.fake = FakeStructr()
        self.addCleanup(self.fake.close)

    def run_bootstrap(self, **extra):
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "FAKE_STATE": str(self.state),
               "STRUCTR_URL": self.fake.url, "TMPDIR": str(self.repo), "DOCKER_START_WAIT_S": "0",
               "PULL_RETRY_BASE_S": "0", "NEO4J_PASSWORD": "a", "STRUCTR_SUPERUSER_PASSWORD": "b",
               "STRUCTR_TOOLS_PASSWORD": "c", **extra}
        return subprocess.run(["bash", str(self.repo / "cloud/bootstrap.sh")], cwd=self.repo, env=env,
                              capture_output=True, text=True)

    def calls(self):
        return (self.state / "calls").read_text().splitlines()

    def test_when_the_service_fails_it_starts_the_daemon_itself(self):
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.state / "daemon").exists())
        self.assertIn("starting dockerd directly", result.stderr)
        self.assertIn("compose up -d", self.calls())

    def test_a_running_daemon_is_left_alone(self):
        (self.state / "daemon").touch()
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("starting dockerd", result.stderr)

    def test_a_refused_pull_is_tried_again_and_a_present_image_not_asked_for(self):
        (self.state / "daemon").touch()
        (self.state / "have-neo4j:test").touch()
        result = self.run_bootstrap(FAKE_PULL_OK_AT="3")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        pulls = [c for c in self.calls() if c.startswith("pull")]
        self.assertEqual(pulls, ["pull -q structr:test"] * 3)            # two refusals, then it came
        self.assertEqual(self.calls()[-1], "compose up -d")             # started only once it had both

    def test_an_image_that_never_comes_stops_it_before_starting_anything(self):
        (self.state / "daemon").touch()
        result = self.run_bootstrap(FAKE_PULL_OK_AT="99")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not pull neo4j:test", result.stderr)
        self.assertEqual(len([c for c in self.calls() if c.startswith("pull")]), 5)
        self.assertNotIn("compose up -d", self.calls())


class FakeStructr:
    """Answers 200 on the schema endpoint when the right credentials arrive, and remembers who asked."""

    def __init__(self, status=200):
        self.seen = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append((self.path, self.headers.get("X-User"), self.headers.get("X-Password")))
                self.send_response(status)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class WaitForStructr(unittest.TestCase):
    def run_wait(self, url, *args):
        env = {**os.environ, "STRUCTR_URL": url, "STRUCTR_SUPERUSER_PASSWORD": "secret-pw", "STRUCTR_TOOLS_PASSWORD": "pw"}
        return subprocess.run(["bash", str(ROOT / "tools/wait_for_structr.sh"), *args], env=env, capture_output=True, text=True)

    def test_it_returns_as_soon_as_structr_is_ready_and_sends_no_password(self):
        fake = FakeStructr()
        self.addCleanup(fake.close)
        result = self.run_wait(fake.url, "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Structr answered", result.stdout)
        # the health endpoint, with no credentials: a wait is never a login attempt
        self.assertEqual(fake.seen, [("/structr/health/ready", None, None)])

    def test_it_gives_up_after_the_timeout_when_nothing_answers(self):
        fake = FakeStructr()
        url = fake.url
        fake.close()                                                   # nothing listens any more
        result = self.run_wait(url, "3")
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not answer", result.stderr)

    def test_a_server_that_answers_with_an_error_is_not_ready(self):
        fake = FakeStructr(status=503)
        self.addCleanup(fake.close)
        result = self.run_wait(fake.url, "3")
        self.assertEqual(result.returncode, 1)
        self.assertIn("503", result.stderr)


class RebuildLoop(unittest.TestCase):
    """tools/rebuild.sh over a throwaway repository of fake build scripts."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = pathlib.Path(self.tmp.name)
        (self.repo / "tools").mkdir()
        (self.repo / "scripts").mkdir()
        for name in ("rebuild.sh", "wait_for_structr.sh"):
            (self.repo / "tools" / name).write_text((ROOT / "tools" / name).read_text())
        self.ran = self.repo / "ran.txt"
        (self.repo / "tools" / "snapshot_state.py").write_text('print(\'{"state": 1}\')\n')
        (self.repo / "tools" / "expected_state.json").write_text('{"state": 1}\n')
        self.account(ok=True)
        self.fake = FakeStructr()
        self.addCleanup(self.fake.close)

    def account(self, ok):
        """A stand-in for tools/create_tools_user.py that records that it ran, and fails if told to."""
        (self.repo / "tools" / "create_tools_user.py").write_text(
            f"open({str(self.ran)!r}, 'a').write('account\\n')\n" + ("" if ok else "raise SystemExit('wrong superuser password')\n"))

    def script(self, name, body="pass"):
        (self.repo / "scripts" / name).write_text(f"open({str(self.ran)!r}, 'a').write({name!r} + '\\n')\n{body}\n")

    def run_rebuild(self, **extra):
        env = {**os.environ, "STRUCTR_URL": self.fake.url, "STRUCTR_SUPERUSER_PASSWORD": "pw", "STRUCTR_TOOLS_PASSWORD": "pw2",
               "LOG_DIR": str(self.repo / "logs"), "WAIT_S": "10", **extra}
        return subprocess.run(["bash", str(self.repo / "tools/rebuild.sh")], env=env, capture_output=True, text=True)

    def test_all_scripts_run_in_version_order_then_the_snapshot_is_checked(self):
        for name in ("10_last.py", "2_second.py", "1_first.py"):
            self.script(name)
        result = self.run_rebuild()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.ran.read_text().split(), ["account", "1_first.py", "2_second.py", "10_last.py"])     # 10 after 2, not before
        self.assertIn("all 3 scripts ran", result.stdout)
        self.assertIn("SNAPSHOT IDENTICAL", result.stdout)

    def test_it_stops_at_the_first_failure_and_shows_why(self):
        self.script("1_ok.py")
        self.script("2_broken.py", "raise SystemExit('the schema drifted')")
        self.script("3_never.py")
        result = self.run_rebuild()
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAILED at scripts/2_broken.py", result.stdout)
        self.assertIn("the schema drifted", result.stdout)                 # the tail of its log is shown
        self.assertEqual(self.ran.read_text().split(), ["account", "1_ok.py", "2_broken.py"])
        self.assertNotIn("SNAPSHOT", result.stdout)

    def test_no_script_runs_when_the_account_cannot_be_made(self):
        self.account(ok=False)
        self.script("1_never.py")
        result = self.run_rebuild()
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAILED to make the tools' account", result.stdout)
        self.assertEqual(self.ran.read_text().split(), ["account"])

    def test_a_different_snapshot_fails_the_run(self):
        self.script("1_ok.py")
        (self.repo / "tools" / "expected_state.json").write_text('{"state": 2}\n')
        result = self.run_rebuild()
        self.assertEqual(result.returncode, 1)
        self.assertIn("SNAPSHOT DIFFERS", result.stderr)
        self.assertNotIn("SNAPSHOT IDENTICAL", result.stdout)

    def test_a_partial_run_and_skipping_the_snapshot(self):
        self.script("1_a.py")
        self.script("2_b.py")
        (self.repo / "tools" / "expected_state.json").write_text('{"state": 2}\n')      # would differ, but is skipped
        result = self.run_rebuild(SCRIPTS_GLOB="scripts/1_*.py", SKIP_SNAPSHOT="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.ran.read_text().split(), ["account", "1_a.py"])

    def test_it_will_not_start_when_structr_never_answers(self):
        self.script("1_ok.py")
        self.fake.close()
        result = self.run_rebuild(WAIT_S="3")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.ran.exists())                                # nothing ran against a dead instance


if __name__ == "__main__":
    unittest.main()
