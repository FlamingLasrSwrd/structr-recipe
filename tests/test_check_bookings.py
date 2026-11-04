"""tools/check_bookings.py removes what an earlier run left (REVIEW.md round 3, #7): every token it books
with begins with MARK, and each run first deletes the nodes whose names hold it. The bookings themselves
are checked against the pages on real Structr."""

import importlib.util
import io
import os
import re
import unittest
from contextlib import redirect_stdout
from unittest import mock

from structr_client import StructrError


def load():
    path = os.path.join(os.path.dirname(__file__), "..", "tools", "check_bookings.py")
    spec = importlib.util.spec_from_file_location("check_bookings_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


class Left:
    """Nodes by type and id, queried as Structr answers `?name=<part>&_inexact=1`: names holding the part in
    any case, and a supertype's query also answering its subtypes' nodes (as a Process query does a
    Cook's); without `_inexact`, names equal to it. A delete of a node not there is answered 404; one in
    `refuse` (id -> status) is refused with that status and stays."""

    def __init__(self, nodes, kinds=None, refuse=None):
        self.nodes, self.deleted, self.kinds = dict(nodes), [], dict(kinds or {})       # kinds: Process id -> kind id
        self.refuse = dict(refuse or {})

    def get_all(self, type_name):
        return {"result": [{"id": i, "type": t, "name": n, "hasKind": {"id": self.kinds[i]} if i in self.kinds else None}
                           for i, (t, n) in self.nodes.items() if t == type_name or (type_name, t) == ("Process", "Cook")]}

    def get(self, path, params=None):
        type_name, part = path.rsplit("/", 1)[-1], (params or {}).get("name", "")
        inexact = (params or {}).get("_inexact") == 1
        return {"result": [{"id": i, "type": t, "name": n} for i, (t, n) in self.nodes.items()
                           if (part.lower() in n.lower() if inexact else part == n)
                           and (t == type_name or (type_name, t) == ("Process", "Cook"))]}

    def delete(self, path):
        type_name, node_id = path.rsplit("/", 2)[-2:]
        if node_id not in self.nodes or self.nodes[node_id][0] != type_name:
            raise StructrError("DELETE", path, 404, {"code": 404})
        if node_id in self.refuse:
            raise StructrError("DELETE", path, self.refuse[node_id], {"code": self.refuse[node_id]})
        self.deleted.append(node_id)
        del self.nodes[node_id]


class Sweep(unittest.TestCase):
    tool, path = load()

    def test_what_holds_the_mark_goes_and_nothing_else(self):
        mark = self.tool.MARK
        g = Left({"p": ("Process", f"Purchase {mark}1a2b3c4d"), "r": ("TemporalRegion", f"Purchase {mark}1a2b3c4d time"),
                  "w": ("MealPlan", f"CHECK menu {mark}99887766"), "q": ("QuantitySpecification", f"Use {mark}00 quantity"),
                  "page": ("Process", "Purchase 1a2b3c4d"), "food": ("DomainType", "Chicken Breast (raw)"),
                  "caps": ("Process", f"Note {mark.upper()}")})
        self.assertEqual(self.tool.sweep(g), 4)
        self.assertEqual(sorted(g.nodes), ["caps", "food", "page"])

    def test_a_node_answered_under_its_supertype_goes_once_by_its_own_type(self):
        g = Left({"c": ("Cook", f"Cook {self.tool.MARK}0000 -- Stew")})
        self.assertEqual(self.tool.sweep(g), 1)
        self.assertEqual(g.deleted, ["c"])

    def kinds(self):
        return {"buy": ("DomainType", "Purchase"), "use": ("DomainType", "Use"), "ops": ("TypeHierarchy", "Pantry Operation")}

    def test_the_bookings_kinds_go_with_the_last_process_of_them(self):
        g = Left({"p": ("Process", f"Purchase {self.tool.MARK}11112222"), **self.kinds()}, kinds={"p": "buy"})
        self.assertEqual(self.tool.sweep(g), 4)
        self.assertEqual(g.nodes, {})

    def test_the_bookings_kinds_stay_while_a_process_of_one_does(self):
        g = Left({"p": ("Process", "Purchase 1a2b3c4d"), **self.kinds()}, kinds={"p": "use"})
        self.assertEqual(self.tool.sweep(g), 0)
        self.assertEqual(sorted(g.nodes), ["buy", "ops", "p", "use"])

    def test_nothing_left_is_nothing_removed(self):
        self.assertEqual(self.tool.sweep(Left({})), 0)

    def test_a_node_already_gone_is_neither_removed_nor_refused(self):
        g = Left({"p": ("Process", "Purchase 1a2b3c4d")})
        self.assertEqual(self.tool._remove(g, {"gone": "Process", "p": "Process"}), (1, []))

    def test_a_refused_delete_is_not_counted_and_the_sweep_says_so_once_the_rest_are_tried(self):
        for status in (401, 422, 500):
            with self.subTest(status=status):
                mark = self.tool.MARK
                g = Left({"p": ("Process", f"Purchase {mark}11112222"), "q": ("Process", f"Use {mark}33334444")},
                         refuse={"p": status})
                self.assertEqual(self.tool._remove(g, {"p": "Process", "q": "Process"}),
                                 (1, [f"Process p: {status} {{'code': {status}}}"]))
                g = Left({"p": ("Process", f"Purchase {mark}11112222"), "q": ("Process", f"Use {mark}33334444")},
                         refuse={"p": status})
                with self.assertRaises(RuntimeError) as caught:
                    self.tool.sweep(g)
                self.assertIn(f"could not remove 1 node(s) an earlier run left: Process p: {status}", str(caught.exception))
                self.assertEqual(sorted(g.nodes), ["p"])

    def test_what_a_run_wrote_is_removed_newest_first_and_a_refusal_reported(self):
        g = Left({"a": ("Process", "A"), "b": ("Process", "B"), "c": ("Process", "C")}, refuse={"b": 500})
        out = io.StringIO()
        with redirect_stdout(out):
            left = self.tool.remove_written(g, [("Process", "a"), ("Process", "b"), ("Process", "gone"), ("Process", "c")])
        self.assertEqual(g.deleted, ["c", "a"])
        self.assertEqual(left, ["Process b: 500 {'code': 500}"])
        self.assertIn("could not remove Process b: 500", out.getvalue())
        self.assertIn("removed 2 of the 4 node(s) written (1 had gone with another); 1 left for the next run's sweep",
                      out.getvalue())

    def test_a_run_sweeps_before_it_books(self):
        g, seen = Left({"old": ("Process", f"Purchase {self.tool.MARK}11112222")}), []

        def first_page(*args, **kwargs):
            seen.append(sorted(g.nodes))
            raise RuntimeError("stopped at the first booking")

        with mock.patch.object(self.tool, "connect", return_value=g), \
                mock.patch.object(self.tool.Check, "page", first_page), redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                self.tool.main([])
        self.assertEqual(seen, [[]])


class Tokens(unittest.TestCase):
    tool, path = load()

    def test_a_token_is_one_the_pages_take_and_begins_with_the_mark(self):
        pattern = re.compile(r"^[0-9a-f]{4,16}$")            # pages/common.js
        for _ in range(20):
            token = self.tool.new_token()
            self.assertRegex(token, pattern)
            self.assertTrue(token.startswith(self.tool.MARK))

    def test_every_token_the_check_books_with_comes_from_new_token(self):
        with open(self.path, encoding="utf-8") as fh:
            source = fh.read()
        self.assertEqual(source.count("secrets.token_hex("), 1)          # new_token()'s own
        self.assertNotIn("token=secrets", source)


if __name__ == "__main__":
    unittest.main()
