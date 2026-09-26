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

SCRIPTS = ["tools/wait_for_structr.sh", "tools/rebuild.sh", "cloud/bootstrap.sh", "cloud/setup.sh", "tools/tunnel.sh"]


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
                                 env_extra={"DRY_RUN": "1", "STRUCTR_SUPERUSER_PASSWORD": "x"})
        self.assertEqual(result.returncode, 0, result.stderr)
        listed = result.stdout.split()
        self.assertEqual(listed, sorted(listed, key=lambda p: [int(t) if t.isdigit() else t for t in
                                                                __import__("re").split(r"(\d+)", p)]))
        self.assertLess(listed.index("scripts/03a_build_metamodel_schema.py"), listed.index("scripts/03b_seed_domaintype_chain.py"))
        self.assertLess(listed.index("scripts/09_culinary_role_test.py"), listed.index("scripts/10a_build_meal_planning_schema.py"))
        self.assertEqual(listed[0], "scripts/00_verify_client.py")
        self.assertEqual(len(listed), len(list((ROOT / "scripts").glob("*.py"))))

    def test_rebuild_refuses_to_run_without_a_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            # a copy of the tools with no .env beside them, and the variable unset
            (pathlib.Path(tmp) / "tools").mkdir()
            for name in ("rebuild.sh", "wait_for_structr.sh"):
                (pathlib.Path(tmp) / "tools" / name).write_text((ROOT / "tools" / name).read_text())
            result = self.run_script(str(pathlib.Path(tmp) / "tools/rebuild.sh"), cwd=tmp, env_drop=("STRUCTR_SUPERUSER_PASSWORD",))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("STRUCTR_SUPERUSER_PASSWORD", result.stderr)

    def bootstrap_copy(self, tmp):
        tmp = pathlib.Path(tmp)
        (tmp / "cloud").mkdir()
        (tmp / "cloud" / "bootstrap.sh").write_text((ROOT / "cloud" / "bootstrap.sh").read_text())
        return tmp

    def test_bootstrap_generates_passwords_and_hides_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.bootstrap_copy(tmp)
            result = self.run_script(str(tmp / "cloud/bootstrap.sh"), "--env-only", cwd=tmp,
                                     env_drop=("NEO4J_PASSWORD", "STRUCTR_SUPERUSER_PASSWORD"))
            self.assertEqual(result.returncode, 0, result.stderr)
            values = dict(line.split("=", 1) for line in (tmp / ".env").read_text().split())
            self.assertEqual(set(values), {"NEO4J_PASSWORD", "STRUCTR_SUPERUSER_PASSWORD"})
            self.assertTrue(all(len(v) >= 24 for v in values.values()))
            self.assertNotIn(values["NEO4J_PASSWORD"], result.stdout + result.stderr)
            self.assertEqual(oct((tmp / ".env").stat().st_mode & 0o777), "0o600")

    def test_bootstrap_uses_the_environments_variables_when_they_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.bootstrap_copy(tmp)
            result = self.run_script(str(tmp / "cloud/bootstrap.sh"), "--env-only", cwd=tmp,
                                     env_extra={"NEO4J_PASSWORD": "from-the-environment-a",
                                                "STRUCTR_SUPERUSER_PASSWORD": "from-the-environment-b"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((tmp / ".env").read_text(),
                             "NEO4J_PASSWORD=from-the-environment-a\nSTRUCTR_SUPERUSER_PASSWORD=from-the-environment-b\n")
            self.assertIn("taken from the environment", result.stdout)

    def test_bootstrap_never_overwrites_an_existing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.bootstrap_copy(tmp)
            (tmp / ".env").write_text("NEO4J_PASSWORD=mine\nSTRUCTR_SUPERUSER_PASSWORD=mine\n")
            result = self.run_script(str(tmp / "cloud/bootstrap.sh"), "--env-only", cwd=tmp)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((tmp / ".env").read_text(), "NEO4J_PASSWORD=mine\nSTRUCTR_SUPERUSER_PASSWORD=mine\n")

    def test_bootstrap_rejects_an_unknown_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = self.bootstrap_copy(tmp)
            self.assertEqual(self.run_script(str(tmp / "cloud/bootstrap.sh"), "--frobnicate", cwd=tmp).returncode, 2)

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
        env = {**os.environ, "STRUCTR_URL": url, "STRUCTR_SUPERUSER_PASSWORD": "secret-pw"}
        return subprocess.run(["bash", str(ROOT / "tools/wait_for_structr.sh"), *args], env=env, capture_output=True, text=True)

    def test_it_returns_as_soon_as_structr_answers_and_sends_the_credentials(self):
        fake = FakeStructr()
        self.addCleanup(fake.close)
        result = self.run_wait(fake.url, "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Structr answered", result.stdout)
        self.assertEqual(fake.seen[0], ("/structr/rest/SchemaNode", "superadmin", "secret-pw"))

    def test_it_gives_up_after_the_timeout_when_nothing_answers(self):
        fake = FakeStructr()
        url = fake.url
        fake.close()                                                   # nothing listens any more
        result = self.run_wait(url, "3")
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not answer", result.stderr)

    def test_a_server_that_answers_with_an_error_is_not_ready(self):
        fake = FakeStructr(status=401)
        self.addCleanup(fake.close)
        result = self.run_wait(fake.url, "3")
        self.assertEqual(result.returncode, 1)
        self.assertIn("401", result.stderr)


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
        self.fake = FakeStructr()
        self.addCleanup(self.fake.close)

    def script(self, name, body="pass"):
        (self.repo / "scripts" / name).write_text(f"open({str(self.ran)!r}, 'a').write({name!r} + '\\n')\n{body}\n")

    def run_rebuild(self, **extra):
        env = {**os.environ, "STRUCTR_URL": self.fake.url, "STRUCTR_SUPERUSER_PASSWORD": "pw",
               "LOG_DIR": str(self.repo / "logs"), "WAIT_S": "10", **extra}
        return subprocess.run(["bash", str(self.repo / "tools/rebuild.sh")], env=env, capture_output=True, text=True)

    def test_all_scripts_run_in_version_order_then_the_snapshot_is_checked(self):
        for name in ("10_last.py", "2_second.py", "1_first.py"):
            self.script(name)
        result = self.run_rebuild()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.ran.read_text().split(), ["1_first.py", "2_second.py", "10_last.py"])     # 10 after 2, not before
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
        self.assertEqual(self.ran.read_text().split(), ["1_ok.py", "2_broken.py"])
        self.assertNotIn("SNAPSHOT", result.stdout)

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
        self.assertEqual(self.ran.read_text().split(), ["1_a.py"])

    def test_it_will_not_start_when_structr_never_answers(self):
        self.script("1_ok.py")
        self.fake.close()
        result = self.run_rebuild(WAIT_S="3")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.ran.exists())                                # nothing ran against a dead instance


class TunnelScript(unittest.TestCase):
    """tools/tunnel.sh's own logic (start/stop/status bookkeeping), never actually
    installing or running cloudflared -- that needs real network access and is
    exercised by hand (CLOUD.md "Public access via Cloudflare Tunnel")."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = pathlib.Path(self.tmp.name)
        (self.repo / "tools").mkdir()
        (self.repo / "tools" / "tunnel.sh").write_text((ROOT / "tools" / "tunnel.sh").read_text())
        self.pid_file = self.repo / "cloudflared.pid"
        self.log_file = self.repo / "cloudflared.log"

    def run_tunnel(self, *args, **extra):
        env = {**os.environ, "TUNNEL_PID_FILE": str(self.pid_file), "TUNNEL_LOG_FILE": str(self.log_file), **extra}
        env.pop("CLOUDFLARE_TUNNEL_TOKEN", None)
        return subprocess.run(["bash", str(self.repo / "tools/tunnel.sh"), *args], cwd=self.repo,
                              env=env, capture_output=True, text=True)

    def spawn_long_running_process(self):
        proc = subprocess.Popen(["sleep", "100"])

        def cleanup():
            if proc.poll() is None:
                proc.kill()
            proc.wait()                                                    # reap it -- avoid a zombie/ResourceWarning

        self.addCleanup(cleanup)
        return proc

    def test_start_refuses_without_a_token(self):
        result = self.run_tunnel("start")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN", result.stderr)
        self.assertFalse(self.pid_file.exists())                            # nothing left behind by the refusal

    def test_rejects_an_unknown_command(self):
        for args in ([], ["frobnicate"]):
            result = self.run_tunnel(*args)
            self.assertEqual(result.returncode, 2, args)
            self.assertIn("usage", result.stderr)

    def test_status_reports_not_running_with_no_pid_file(self):
        result = self.run_tunnel("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not running", result.stdout)

    def test_stop_is_a_safe_no_op_when_not_running(self):
        result = self.run_tunnel("stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not running", result.stdout)

    def test_status_reports_running_for_a_live_pid(self):
        proc = self.spawn_long_running_process()
        self.pid_file.write_text(str(proc.pid))
        result = self.run_tunnel("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("running", result.stdout)
        self.assertIn(str(proc.pid), result.stdout)

    def test_status_reports_not_running_for_a_stale_pid_file(self):
        proc = self.spawn_long_running_process()
        dead_pid = proc.pid
        proc.kill()
        proc.wait()
        self.pid_file.write_text(str(dead_pid))
        result = self.run_tunnel("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not running", result.stdout)

    def test_stop_kills_the_running_process_and_removes_the_pid_file(self):
        proc = self.spawn_long_running_process()
        self.pid_file.write_text(str(proc.pid))
        result = self.run_tunnel("stop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stopped", result.stdout)
        self.assertIsNotNone(proc.wait(timeout=5))                          # actually terminated, not just forgotten
        self.assertFalse(self.pid_file.exists())

    def test_start_is_a_no_op_when_already_running(self):
        proc = self.spawn_long_running_process()
        self.pid_file.write_text(str(proc.pid))
        result = self.run_tunnel("start", CLOUDFLARE_TUNNEL_TOKEN="unused-because-already-running")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already running", result.stdout)
        self.assertEqual(self.pid_file.read_text(), str(proc.pid))          # untouched, not restarted


if __name__ == "__main__":
    unittest.main()
