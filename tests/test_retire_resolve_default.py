"""scripts/47a: the StructrScript resolveDefault leaves DomainType, and nothing else goes with it."""

import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "retire_47a", os.path.join(os.path.dirname(__file__), "..", "scripts", "47a_retire_resolve_default.py"))
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


class Schema:
    """SchemaNode and SchemaMethod rows as Structr's REST answers them: a query by name, a method
    carrying its schemaNode as a nested {"id", ...}, and a delete by id."""

    def __init__(self, nodes, methods):
        self.nodes = [{"id": i, "name": n} for i, n in nodes]
        self.methods = [{"id": i, "name": n, "schemaNode": {"id": owner, "type": "SchemaNode"} if owner else None}
                        for i, n, owner in methods]
        self.deleted = []

    def get(self, path, params=None):
        rows = self.nodes if path.endswith("/SchemaNode") else self.methods
        return {"result": [r for r in rows if all(r.get(k) == v for k, v in (params or {}).items())]}

    def delete(self, path):
        method_id = path.rsplit("/", 1)[-1]
        self.deleted.append(method_id)
        self.methods = [m for m in self.methods if m["id"] != method_id]


def instance():
    return Schema(nodes=[("n-dt", "DomainType"), ("n-q", "Quality")],
                  methods=[("m-rd", "resolveDefault", "n-dt"),        # the one to retire
                           ("m-other", "onCreate", "n-dt"),            # another method on DomainType
                           ("m-elsewhere", "resolveDefault", "n-q"),   # the same name on another type
                           ("m-global", "resolveDefault", None)])      # and a global one


class Retire(unittest.TestCase):
    def test_only_domain_types_resolve_default_is_removed(self):
        schema = instance()
        self.assertEqual(migration.retire(schema), 1)
        self.assertEqual(schema.deleted, ["m-rd"])
        self.assertEqual(sorted(m["id"] for m in schema.methods), ["m-elsewhere", "m-global", "m-other"])

    def test_a_second_run_finds_nothing_and_deletes_nothing(self):
        schema = instance()
        migration.retire(schema)
        self.assertEqual(migration.retire(schema), 0)
        self.assertEqual(schema.deleted, ["m-rd"])

    def test_a_fresh_build_without_the_method_is_left_as_it_is(self):
        schema = Schema(nodes=[("n-dt", "DomainType")], methods=[("m-other", "onCreate", "n-dt")])
        self.assertEqual(migration.retire(schema), 0)
        self.assertEqual(schema.deleted, [])

    def test_an_instance_without_the_type_yet_has_nothing_to_retire(self):
        schema = Schema(nodes=[], methods=[("m-elsewhere", "resolveDefault", "n-q")])
        self.assertEqual(migration.retire(schema), 0)
        self.assertEqual(schema.deleted, [])


class NothingCallsIt(unittest.TestCase):
    def test_no_script_tool_or_module_calls_the_method_any_more(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        callers = []
        for folder in ("scripts", "tools", "mealplanner", "methods"):
            for dirpath, _, files in os.walk(os.path.join(root, folder)):
                for name in files:
                    if not name.endswith((".py", ".js")):
                        continue
                    with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                        text = f.read()
                    if '"resolveDefault"' in text and "call_method" in text:
                        callers.append(name)
        self.assertEqual([c for c in callers if not c.startswith("47a_")], [])


if __name__ == "__main__":
    unittest.main()
