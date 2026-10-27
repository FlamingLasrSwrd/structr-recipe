"""tools/install_methods.py: methods/ installed as Structr user-defined functions, replaced whole, its own
only. What the methods work out is checked against Python on a live instance (tools/check_households.py)."""

import importlib.util
import io
import os
import re
import unittest
from contextlib import redirect_stdout
from unittest import mock

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_tool", os.path.join(TOOLS, f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Methods:
    """SchemaMethods by REST path, as Structr keeps them."""

    def __init__(self):
        self.nodes, self.next = {}, 0

    def post(self, path, payload):
        self.next += 1
        self.nodes[f"m{self.next}"] = {"id": f"m{self.next}", **payload}
        return {"result": [f"m{self.next}"]}

    def patch(self, path, payload):
        self.nodes[path.rsplit("/", 1)[-1]].update(payload)

    def delete(self, path):
        del self.nodes[path.rsplit("/", 1)[-1]]

    def get(self, path, params=None):
        return {"result": list(self.nodes.values())}

    def wait_until_ready(self):
        pass


def run(tool, argv, g):
    with mock.patch.object(tool, "connect", return_value=g), redirect_stdout(io.StringIO()):
        return tool.main(argv)


class InstallMethods(unittest.TestCase):
    tool = load("install_methods")

    def files(self):
        return sorted(f[:-3] for f in os.listdir(self.tool.METHODS_DIR) if f.endswith(".js"))

    def test_each_file_is_one_javascript_function_after_the_shared_library(self):
        g = Methods()
        self.assertEqual(run(self.tool, [], g), 0)
        installed = {m["name"]: m for m in g.nodes.values()}
        self.assertEqual(sorted(installed), self.files())
        for name, m in installed.items():
            source = m["source"]
            self.assertTrue(source.startswith("{\n" + self.tool.MARK + f"methods/{name}.js\n") and source.endswith("\n}"))
            self.assertIn(self.tool.read(self.tool.COMMON), source)
            self.assertNotIn("schemaNode", m)                              # a user-defined function, no type

    def test_a_second_run_changes_nothing_and_a_changed_one_is_replaced(self):
        g = Methods()
        run(self.tool, [], g)
        before = {k: dict(v) for k, v in g.nodes.items()}
        run(self.tool, [], g)
        self.assertEqual(g.nodes, before)
        first = next(iter(g.nodes.values()))
        first["source"] = first["source"].replace("return", "return /* edited */", 1)
        run(self.tool, [], g)
        self.assertEqual(g.nodes, before)

    def test_it_removes_its_own_whose_file_is_gone_and_never_touches_another(self):
        g = Methods()
        validator = g.post("/structr/rest/SchemaMethod", {"name": "onCreate", "schemaNode": {"id": "x"}, "source": "error()"})["result"][0]
        foreign = g.post("/structr/rest/SchemaMethod", {"name": "someoneElses", "source": "{\n// not ours\nreturn 1;\n}"})["result"][0]
        gone = g.post("/structr/rest/SchemaMethod", {"name": "oldOne", "source": "{\n" + self.tool.MARK + "methods/oldOne.js\n}"})["result"][0]
        run(self.tool, [], g)
        self.assertIn(validator, g.nodes)
        self.assertIn(foreign, g.nodes)                                       # a user-defined function of no file of ours
        self.assertNotIn(gone, g.nodes)
        run(self.tool, ["--remove"], g)
        self.assertEqual(sorted(g.nodes), sorted([validator, foreign]))

    def test_a_function_of_the_same_name_it_did_not_install_is_left_alone(self):
        g = Methods()
        name = self.files()[0]
        theirs = g.post("/structr/rest/SchemaMethod", {"name": name, "source": "{ return 1; }"})["result"][0]
        with mock.patch.object(self.tool, "connect", return_value=g), redirect_stdout(io.StringIO()):
            with self.assertRaises(self.tool.MethodError):
                self.tool.main([])
        self.assertEqual(g.nodes[theirs]["source"], "{ return 1; }")

    def test_no_method_declares_a_name_the_shared_library_has(self):
        """A method runs as one script after pages/common.js, as a page does (test_pages_tools)."""
        declared = lambda text: set(re.findall(r"^(?:const|let|var|function)\s+([A-Za-z_$][\w$]*)", text, re.M))
        shared = declared(self.tool.read(self.tool.COMMON))
        for name in self.files():
            self.assertEqual(declared(self.tool.read(os.path.join(self.tool.METHODS_DIR, name + ".js"))) & shared, set(), name)


class TheSnapshotLeavesThemOut(unittest.TestCase):
    def test_the_snapshot_knows_the_installers_mark(self):
        installer, snapshot = load("install_methods"), load("snapshot_state")
        self.assertEqual(snapshot.INSTALLED_METHOD, installer.MARK)
        self.assertTrue(snapshot.installed_method({"source": "{\n" + installer.MARK + "methods/x.js\n}"}))
        self.assertFalse(snapshot.installed_method({"source": "{\n// a validator\n}"}))
        self.assertFalse(snapshot.installed_method({"source": "error()"}))


if __name__ == "__main__":
    unittest.main()
