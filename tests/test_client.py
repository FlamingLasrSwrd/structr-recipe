"""StructrClient behaviour that needs no server: what it refuses to send,
what it does with ambiguous matches, and how wait_until_ready treats errors."""

import time
import unittest

import requests

from structr_client import DuplicateMatchError, ReadCache, StructrClient, StructrError, validate_exact_match_value


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


class ServerWithASmallDefaultPage(StructrClient):
    """Structr returns at most its default page size unless asked for more, and says how many pages there are."""

    def __init__(self, rows, default_page_size=2):
        super().__init__("http://unused", "u", "p")
        self.rows, self.default, self.requests = rows, default_page_size, []

    def get(self, path, params=None):
        self.requests.append((path, dict(params or {})))
        size = (params or {}).get("_pageSize", self.default)
        page = (params or {}).get("_page", 1)
        chunk = self.rows[(page - 1) * size: page * size]
        return {"result": chunk, "result_count": len(self.rows), "page_count": -(-len(self.rows) // size), "page": page}


class CollectionReadsAreComplete(unittest.TestCase):
    def test_every_row_comes_back_even_past_the_servers_default_page(self):
        rows = [{"id": str(i)} for i in range(7)]
        got = ServerWithASmallDefaultPage(rows).get_all("Portion", page_size=3)
        self.assertEqual([r["id"] for r in got["result"]], [str(i) for i in range(7)])   # 3 pages: 3 + 3 + 1

    def test_a_single_page_collection_costs_one_request(self):
        server = ServerWithASmallDefaultPage([{"id": "a"}, {"id": "b"}])
        server.get_all("Portion", page_size=500)
        self.assertEqual(len(server.requests), 1)

    def test_one_node_is_still_a_single_unpaged_read(self):
        server = ServerWithASmallDefaultPage([{"id": "a"}])
        server.get_all("Portion", "a")
        self.assertEqual(server.requests, [("/structr/rest/Portion/a/all", {})])


class CountingReader:
    """Stands in for a client and counts what reaches it."""

    def __init__(self, rows_by_type):
        self.rows, self.calls = rows_by_type, []

    def get_all(self, type_name, node_id=None):
        self.calls.append(("get_all", type_name, node_id))
        rows = self.rows[type_name]
        if node_id is None:
            return {"result": [dict(r) for r in rows]}
        return {"result": dict(next(r for r in rows if r["id"] == node_id))}

    def get(self, path, params=None):
        self.calls.append(("get", path, tuple(sorted((params or {}).items()))))
        return {"result": [{"id": "x", "name": (params or {}).get("name")}]}


class ReadCaching(unittest.TestCase):
    def setUp(self):
        self.source = CountingReader({"Quality": [{"id": "q1", "name": "one"}, {"id": "q2", "name": "two"}]})
        self.cache = ReadCache(self.source)

    def test_the_same_node_is_fetched_once(self):
        for _ in range(3):
            self.assertEqual(self.cache.get_all("Quality", "q1")["result"]["name"], "one")
        self.assertEqual(len(self.source.calls), 1)

    def test_a_listing_also_answers_later_lookups_by_id(self):
        self.cache.get_all("Quality")
        self.assertEqual(self.cache.get_all("Quality", "q2")["result"]["name"], "two")
        self.assertEqual(len(self.source.calls), 1)

    def test_the_same_query_is_asked_once(self):
        self.cache.get("/structr/rest/DomainType", params={"name": "Mass"})
        self.cache.get("/structr/rest/DomainType", params={"name": "Mass"})
        self.cache.get("/structr/rest/DomainType", params={"name": "Yield"})
        self.assertEqual(len(self.source.calls), 2)

    def test_what_a_caller_does_to_a_result_does_not_reach_the_cache(self):
        self.cache.get_all("Quality", "q1")["result"]["name"] = "changed"
        self.cache.get_all("Quality")["result"].clear()
        self.assertEqual(self.cache.get_all("Quality", "q1")["result"]["name"], "one")
        self.assertEqual(len(self.cache.get_all("Quality")["result"]), 2)

    def test_it_is_read_only(self):
        for write in ("post", "patch", "delete", "upsert"):
            self.assertFalse(hasattr(self.cache, write), write)


if __name__ == "__main__":
    unittest.main()
