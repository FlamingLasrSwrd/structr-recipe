"""StructrClient behaviour that needs no server: what it refuses to send,
what it does with ambiguous matches, and how wait_until_ready treats errors."""

import time
import unittest

import requests

from structr_client import DuplicateMatchError, StructrClient, StructrError, validate_exact_match_value


class Recording(StructrClient):
    """Records writes instead of sending them; get() returns a scripted result."""

    def __init__(self, matches=()):
        super().__init__("http://unused", "u", "p")
        self.matches, self.writes = list(matches), []

    def get(self, path, params=None):
        return {"result": self.matches}

    def post(self, path, json):
        self.writes.append(("POST", path, json))
        return {"result": ["new-id"]}

    def patch(self, path, json):
        self.writes.append(("PATCH", path, json))
        return {}


class ExactMatchValues(unittest.TestCase):
    def test_comma_and_semicolon_are_refused(self):
        for bad in ("TEST -- a, b", "A;B", "a,b;c"):
            with self.assertRaises(ValueError, msg=bad):
                validate_exact_match_value("here", bad)

    def test_ordinary_names_and_non_strings_pass(self):
        for fine in ("TEST -- Chicken Breast (raw)", "0.75 yield ratio", "a - b", 5, None):
            validate_exact_match_value("here", fine)

    def test_the_real_post_patch_and_upsert_all_refuse_them(self):
        real = StructrClient("http://unused", "u", "p")
        with self.assertRaises(ValueError):
            real.post("/structr/rest/Role", {"name": "a, b"})
        with self.assertRaises(ValueError):
            real.patch("/structr/rest/Role/x", {"name": "a;b"})      # a rename into the same trap
        with self.assertRaises(ValueError):
            real.upsert("Role", "name", "a, b", {})

    def test_a_patch_that_leaves_the_name_alone_is_fine(self):
        class Sent(StructrClient):
            def _request(self, method, path, **kw):
                return {"sent": (method, path, kw.get("json"))}
        self.assertEqual(Sent("http://unused", "u", "p").patch("/structr/rest/Role/x", {"weight": 1})["sent"][2], {"weight": 1})


class Upsert(unittest.TestCase):
    def test_no_match_creates(self):
        c = Recording([])
        c.upsert("Role", "name", "r", {"a": 1})
        self.assertEqual([w[0] for w in c.writes], ["POST"])

    def test_one_match_patches_it(self):
        c = Recording([{"id": "abc"}])
        self.assertEqual(c.upsert("Role", "name", "r", {"a": 1}), "abc")
        self.assertEqual([(w[0], w[1]) for w in c.writes], [("PATCH", "/structr/rest/Role/abc")])

    def test_several_matches_is_an_error_and_writes_nothing(self):
        c = Recording([{"id": "abc"}, {"id": "def"}])
        with self.assertRaises(DuplicateMatchError) as caught:
            c.upsert("Role", "name", "r", {"a": 1})
        self.assertEqual(caught.exception.ids, ["abc", "def"])
        self.assertEqual(c.writes, [])          # it used to patch whichever came first


class Scripted(StructrClient):
    """get() raises or returns each scripted outcome in turn."""

    def __init__(self, outcomes):
        super().__init__("http://unused", "u", "p")
        self.outcomes, self.calls = list(outcomes), 0

    def get(self, path, params=None):
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def http(status):
    return StructrError("GET", "http://unused", status, {"message": "x"})


class WaitUntilReady(unittest.TestCase):
    def test_a_bad_password_fails_immediately_not_after_the_timeout(self):
        c = Scripted([http(401)])
        started = time.monotonic()
        with self.assertRaises(StructrError) as caught:
            c.wait_until_ready(timeout_s=30, interval_s=10)
        self.assertEqual(caught.exception.status, 401)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(c.calls, 1)

    def test_other_client_errors_also_fail_fast(self):
        for status in (403, 404):
            c = Scripted([http(status)])
            with self.assertRaises(StructrError):
                c.wait_until_ready(timeout_s=30, interval_s=10)
            self.assertEqual(c.calls, 1, status)

    def test_a_starting_server_is_retried_until_it_answers(self):
        c = Scripted([requests.exceptions.ConnectionError("refused"), requests.exceptions.ReadTimeout("slow"), http(503), {"result": []}])
        c.wait_until_ready(timeout_s=10, interval_s=0.01)
        self.assertEqual(c.calls, 4)

    def test_a_server_that_never_recovers_times_out(self):
        c = Scripted([http(503)])
        with self.assertRaises(TimeoutError):
            c.wait_until_ready(timeout_s=0.1, interval_s=0.02)


class RequestTimeout(unittest.TestCase):
    def test_every_request_carries_a_timeout(self):
        seen = {}

        class Session:
            headers = {}

            def request(self, method, url, **kw):
                seen.update(kw)
                raise requests.exceptions.ConnectionError("stop here")

        c = StructrClient("http://unused", "u", "p", timeout=(1.5, 9.0))
        c.session = Session()
        with self.assertRaises(requests.exceptions.ConnectionError):
            c.get("/x")
        self.assertEqual(seen["timeout"], (1.5, 9.0))

    def test_there_is_a_default(self):
        self.assertEqual(len(StructrClient("http://unused", "u", "p").timeout), 2)


if __name__ == "__main__":
    unittest.main()
