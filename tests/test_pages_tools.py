"""tools/install_pages.py: the pages' element trees, replacing them whole, and the sign-in grant.
What the pages show is checked against Python by tools/check_pages.py on a live instance."""

import importlib.util
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

ELEMENTS = {"Html", "Head", "Meta", "Title", "Style", "Body", "Content", "Div"}


def load():
    spec = importlib.util.spec_from_file_location("install_pages_tool", os.path.join(os.path.dirname(__file__), "..", "tools", "install_pages.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PageGraph:
    """Pages, their elements (all DOMNodes, as on Structr) and ResourceAccess grants, by REST path."""

    def __init__(self):
        self.nodes, self.next = {}, 0

    def post(self, path, payload):
        self.next += 1
        node_id = f"n{self.next}"
        self.nodes[node_id] = {"id": node_id, "type": path.rsplit("/", 1)[-1], **payload}
        return {"result": [node_id]}

    def delete(self, path):
        del self.nodes[path.rsplit("/", 1)[-1]]

    def of(self, type_name):
        return [n for n in self.nodes.values() if n["type"] == type_name or (type_name == "DOMNode" and n["type"] in ELEMENTS)]

    def get(self, path, params=None):
        return {"result": [n for n in self.of(path.rsplit("/", 1)[-1]) if all(n.get(k) == v for k, v in (params or {}).items())]}

    def get_all(self, type_name, node_id=None, where=None):
        return {"result": [n for n in self.of(type_name) if all(n.get(k) == v for k, v in (where or {}).items())]}

    def wait_until_ready(self):
        pass


def run(tool, argv, g):
    with mock.patch.object(tool, "connect", return_value=g), redirect_stdout(io.StringIO()):
        return tool.main(argv)


class InstallPages(unittest.TestCase):
    tool = load()

    def test_every_page_is_one_tree_with_a_tag_on_every_element(self):
        g = PageGraph()
        self.assertEqual(run(self.tool, [], g), 0)
        pages = {p["name"]: p for p in g.of("Page")}
        self.assertEqual(set(pages), {"week", "recipes", "recipe", "nutrition", "pantry"})
        for name, page in pages.items():
            elements = [n for n in g.of("DOMNode") if n["pageId"] == page["id"]]
            self.assertEqual(len(elements), 10, name)
            for n in elements:
                if n["type"] != "Content":
                    self.assertEqual(n["tag"], n["type"].lower())              # without one Structr 6 renders nothing
                self.assertEqual((n["visibleToAuthenticatedUsers"], n["visibleToPublicUsers"]), (True, False))
            (body,) = [n for n in elements if n["type"] == "Content" and n["contentType"] == "text/html"]
            self.assertTrue(body["content"].startswith("${{\n// Shared by every page") and body["content"].endswith("\n}}"))
            self.assertIn(self.tool.read(self.tool.PAGES[name][1]), body["content"])
        self.assertEqual(g.of("ResourceAccess"), [])                          # no sign-in grant unless asked

    def test_a_second_run_replaces_each_page_whole(self):
        g = PageGraph()
        run(self.tool, [], g)
        before = len(g.nodes)
        stale = g.post("/structr/rest/Div", {"pageId": g.of("Page")[0]["id"], "tag": "div"})["result"][0]
        run(self.tool, [], g)
        self.assertEqual(len(g.nodes), before)                               # the extra element went with its page
        self.assertNotIn(stale, g.nodes)

    def test_the_sign_in_page_and_its_grant_once_and_removing_everything(self):
        g = PageGraph()
        run(self.tool, ["--login"], g)
        run(self.tool, ["--login"], g)
        (grant,) = g.of("ResourceAccess")
        self.assertEqual((grant["signature"], grant["flags"], grant["visibleToPublicUsers"]), ("_login", 64, True))
        (login,) = [p for p in g.of("Page") if p["name"] == "login"]
        self.assertTrue(all(n["visibleToPublicUsers"] for n in g.of("DOMNode") if n["pageId"] == login["id"]))
        run(self.tool, ["--remove"], g)
        self.assertEqual(g.nodes, {})


if __name__ == "__main__":
    unittest.main()
