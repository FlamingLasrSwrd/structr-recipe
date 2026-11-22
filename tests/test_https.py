"""HTTPS for the owner's stack: tools/make_https_cert.py with the real openssl, judged by openssl's own
verifier and by a TLS handshake, and tools/owner_stack.sh up with Docker faked (docs/pages.md).
"""

import contextlib
import hashlib
import importlib.util
import io
import os
import pathlib
import re
import shutil
import socket
import ssl
import stat
import subprocess
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("https_cert_tool", ROOT / "tools" / "make_https_cert.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

ADDRESS, OTHER = "192.0.2.8", "192.0.2.9"       # documentation addresses (RFC 5737)
NAME = "planner.test"


def openssl(*args, env=None):
    return subprocess.run(["openssl", *map(str, args)], capture_output=True, text=True, env={**os.environ, **(env or {})})


@unittest.skipUnless(shutil.which("openssl"), "needs openssl")
class Certificate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.work = pathlib.Path(tmp.name)
        cls.out = cls.work / "https"
        cls.fingerprint = tool.make(cls.out, [ADDRESS, NAME])
        key, _, cls.password = (cls.out / "structr.env").read_text().strip().partition("=")
        cls.setting = key
        env = {"P": cls.password}
        for target, options in (("leaf.crt", ["-clcerts", "-nokeys"]), ("leaf.key", ["-nocerts", "-nodes"])):
            done = openssl("pkcs12", "-in", cls.out / "keystore.p12", "-passin", "env:P", *options,
                           "-out", cls.work / target, env=env)
            if done.returncode:
                raise RuntimeError(done.stderr)

    def verify(self, *check):
        return openssl("verify", "-x509_strict", "-CAfile", self.out / "ca.crt", "-purpose", "sslserver", *check,
                       self.work / "leaf.crt")

    def test_it_is_good_for_the_hosts_given_and_no_other(self):
        self.assertEqual(self.verify("-verify_ip", ADDRESS).returncode, 0)
        self.assertEqual(self.verify("-verify_hostname", NAME).returncode, 0)
        self.assertNotEqual(self.verify("-verify_ip", OTHER).returncode, 0)
        self.assertNotEqual(self.verify("-verify_hostname", "other.test").returncode, 0)

    def test_it_expires_within_what_apple_accepts_and_not_before_two_years(self):
        day, cert = 86400, self.work / "leaf.crt"
        self.assertEqual(openssl("x509", "-in", cert, "-noout", "-checkend", 730 * day).returncode, 0)
        self.assertNotEqual(openssl("x509", "-in", cert, "-noout", "-checkend", 825 * day).returncode, 0)

    def test_the_authoritys_key_is_not_kept(self):
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["ca.crt", "keystore.p12", "structr.env"])
        self.assertNotIn("PRIVATE KEY", (self.out / "ca.crt").read_text())
        held = openssl("pkcs12", "-in", self.out / "keystore.p12", "-passin", "env:P", "-nocerts", "-nodes",
                       env={"P": self.password}).stdout
        self.assertEqual(held.count("BEGIN PRIVATE KEY"), 1)
        authority = openssl("x509", "-in", self.out / "ca.crt", "-pubkey", "-noout").stdout
        self.assertNotEqual(openssl("pkey", "-in", self.work / "leaf.key", "-pubout").stdout, authority)

    def test_only_the_owner_reads_the_secrets(self):
        modes = {p.name: stat.S_IMODE(p.stat().st_mode) for p in self.out.iterdir()}
        self.assertEqual(modes, {"ca.crt": 0o644, "keystore.p12": 0o600, "structr.env": 0o600})
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o700)

    def test_the_password_is_the_setting_structr_reads_and_opens_the_keystore(self):
        self.assertEqual(self.setting, "STRUCTR_application_keystore_password")
        self.assertRegex(self.password, r"^[0-9a-f]{48}$")      # safe through compose and docker.sh's shell
        wrong = openssl("pkcs12", "-in", self.out / "keystore.p12", "-passin", "pass:wrong", "-noout")
        self.assertNotEqual(wrong.returncode, 0)

    def test_the_fingerprint_is_the_authoritys(self):
        der = ssl.PEM_cert_to_DER_cert((self.out / "ca.crt").read_text())
        self.assertEqual(self.fingerprint.replace(":", "").lower(), hashlib.sha256(der).hexdigest())

    def handshake(self, host):
        """A TLS 1.2 handshake (Structr's only protocol by default) with the key, checked as a browser would."""
        server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.maximum_version = ssl.TLSVersion.TLSv1_2
        server.load_cert_chain(self.work / "leaf.crt", self.work / "leaf.key")
        ours, theirs = socket.socketpair()
        ours.settimeout(10)
        theirs.settimeout(10)

        def serve():
            try:
                with server.wrap_socket(theirs, server_side=True) as s:
                    s.sendall(b"ok")
            except OSError:
                pass
            finally:
                theirs.close()

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            with ssl.create_default_context(cafile=self.out / "ca.crt").wrap_socket(ours, server_hostname=host) as s:
                return s.recv(2)
        finally:
            ours.close()
            thread.join(10)

    def test_a_client_that_trusts_the_authority_connects(self):
        self.assertEqual(self.handshake(ADDRESS), b"ok")
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.handshake(OTHER)


@unittest.skipUnless(shutil.which("openssl"), "needs openssl")
class Constraints(unittest.TestCase):
    """What a stolen authority key could still sign for: only the hosts it was made for."""

    def forged(self, made_for, forged_for):
        with tempfile.TemporaryDirectory() as tmp:
            work = pathlib.Path(tmp)
            tool.make_authority(work, *made_for)
            tool.sign_server(work, *forged_for)
            return openssl("verify", "-CAfile", work / "ca.crt", work / "server.crt").returncode

    def test_made_for_an_address_it_vouches_for_no_name_and_no_other_address(self):
        made_for = ([ADDRESS], [])
        self.assertEqual(self.forged(made_for, ([ADDRESS], [])), 0)
        self.assertNotEqual(self.forged(made_for, ([], ["bank.example"])), 0)
        self.assertNotEqual(self.forged(made_for, ([OTHER], [])), 0)
        self.assertNotEqual(self.forged(made_for, (["2001:db8::8"], [])), 0)

    def test_made_for_a_name_it_vouches_for_no_address_and_no_other_name(self):
        made_for = ([], [NAME])
        self.assertEqual(self.forged(made_for, ([], [NAME])), 0)
        self.assertNotEqual(self.forged(made_for, ([ADDRESS], [])), 0)
        self.assertNotEqual(self.forged(made_for, ([], ["bank.example"])), 0)


class Hosts(unittest.TestCase):
    def test_what_other_devices_can_open_is_accepted(self):
        self.assertEqual(tool.parse_hosts([ADDRESS, " Planner.Test "]), ([ADDRESS], [NAME]))

    def test_what_they_cannot_or_what_would_enter_openssls_configuration_is_refused(self):
        for bad in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "2001:db8::8", "", "999.1.1.1", "a,DNS:bank.example",
                    "a b", "a\nb", "*.test", "a_b", "https://planner.test", "192.0.2.8:8443"):
            with self.subTest(bad), self.assertRaises(tool.CertError):
                tool.parse_hosts([bad])


@unittest.skipUnless(shutil.which("openssl"), "needs openssl")
class Again(unittest.TestCase):
    def test_a_certificate_is_replaced_only_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            args, out = ["--host", ADDRESS, "--out", tmp], pathlib.Path(tmp) / "keystore.p12"
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                self.assertEqual(tool.main(args), 0)
                first = out.read_bytes()
                self.assertEqual(tool.main(args), 1)
                self.assertEqual(out.read_bytes(), first)
                self.assertEqual(tool.main([*args, "--force"]), 0)
            self.assertNotEqual(out.read_bytes(), first)
            password = (out.parent / "structr.env").read_text().strip().partition("=")[2]
            self.assertNotIn(password, printed.getvalue())


class OwnerStack(unittest.TestCase):
    """tools/owner_stack.sh in a throwaway folder, with a docker that records what it was asked."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        (self.root / "tools").mkdir()
        shutil.copy(ROOT / "tools" / "owner_stack.sh", self.root / "tools")
        for name in ("image_guard.sh", "wait_for_structr.sh"):
            (self.root / "tools" / name).write_text("exit 0\n")
        (self.root / "bin").mkdir()
        self.log = self.root / "docker.log"
        for name, body in (("docker", f'#!/bin/sh\necho "$@" >> "{self.log}"\n'),
                           ("openssl", '#!/bin/sh\nexit "${EXPIRY_STATUS:-0}"\n')):
            fake = self.root / "bin" / name
            fake.write_text(body)
            fake.chmod(0o755)

    def certificate(self, *names):
        (self.root / "private" / "https").mkdir(parents=True)
        for name in names:
            (self.root / "private" / "https" / name).write_text("x")

    def run_stack(self, command, **extra):
        env = {**os.environ, "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}", "NO_BACKUP": "1",
               "STRUCTR_SUPERUSER_PASSWORD": "test", "STRUCTR_TOOLS_PASSWORD": "test-tools", **extra}
        env.pop("STRUCTR_HTTPS_PORT", None)
        done = subprocess.run(["bash", str(self.root / "tools" / "owner_stack.sh"), command],
                              capture_output=True, text=True, env=env)
        return done, self.log.read_text() if self.log.exists() else ""

    def test_without_a_certificate_up_is_what_it_was(self):
        done, asked = self.run_stack("up")
        self.assertEqual((done.returncode, asked), (0, "compose -p mealplanner-owner up -d\n"))
        self.assertNotIn("https://", done.stdout)

    def test_with_one_up_adds_the_https_file(self):
        self.certificate("ca.crt", "keystore.p12", "structr.env")
        done, asked = self.run_stack("up")
        self.assertEqual((done.returncode, asked),
                         (0, "compose -p mealplanner-owner -f docker-compose.yml -f docker-compose.https.yml up -d\n"))
        self.assertIn(":8443/structr/html/login", done.stdout)
        self.assertNotIn("warning", done.stderr)

    def test_one_near_its_end_warns_and_still_starts(self):
        self.certificate("ca.crt", "keystore.p12", "structr.env")
        done, asked = self.run_stack("up", EXPIRY_STATUS="1")
        self.assertEqual(done.returncode, 0)
        self.assertIn("expires within a month", done.stderr)
        self.assertIn("up -d", asked)

    def test_an_incomplete_one_is_refused_before_docker_is_touched(self):
        for kept in ((), ("keystore.p12",), ("structr.env",)):
            with self.subTest(kept):
                shutil.rmtree(self.root / "private", ignore_errors=True)
                self.certificate(*kept)
                done, asked = self.run_stack("up")
                self.assertEqual((done.returncode, asked), (1, ""))

    def test_stop_works_whatever_state_the_certificate_is_in(self):
        self.certificate()
        done, asked = self.run_stack("stop")
        self.assertEqual((done.returncode, asked), (0, "compose -p mealplanner-owner stop\n"))


class ComposeFile(unittest.TestCase):
    def test_structr_gets_the_settings_the_port_and_the_keystore_read_only(self):
        text = (ROOT / "docker-compose.https.yml").read_text()
        settings = dict(re.findall(r"^ +- (STRUCTR_\w+)=(\S+)$", text, re.M))
        self.assertEqual(settings, {
            "STRUCTR_application_https_enabled": "true",
            "STRUCTR_application_https_port": "8443",
            "STRUCTR_application_keystore_path": "/var/lib/structr/https/keystore.p12",
            "STRUCTR_httpservice_cookies_secure": "true"})
        self.assertIn('- "${STRUCTR_HTTPS_PORT:-8443}:8443"', text)
        self.assertIn("- ./private/https/keystore.p12:/var/lib/structr/https/keystore.p12:ro", text)
        self.assertIn("- ./private/https/structr.env", text)

    def test_every_other_stack_is_left_without_it(self):
        base = (ROOT / "docker-compose.yml").read_text()
        self.assertNotIn("8443", base)
        self.assertNotIn("https_enabled", base)


if __name__ == "__main__":
    unittest.main()
