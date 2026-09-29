"""An in-memory stand-in for the parts of StructrClient that mealplanner/ reads
through: get_all(type, id), get_all(type) and get(path, params={"name": ...}), whose rows,
as on Structr, carry only id, type and name.
It lets the pure logic be tested without a Structr instance.

Relationships are written as Ref("id") (or a list of them) and rendered the way
Structr renders a nested reference: {"id", "type", "name"} only. Both directions
of a relationship are just properties, so a test sets both (for example a
DomainType's `children` AND its child's `parent`), which keeps the fixture
explicit about the graph it is asserting against.
"""

from __future__ import annotations

from datetime import datetime, timezone


class Ref:
    def __init__(self, node_id: str):
        self.id = node_id


def at(day: int, hour: int = 0) -> str:
    """A Structr timestamp string on 2026-09-<day>."""
    return f"2026-09-{day:02d}T{hour:02d}:00:00+0000"


def when(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, tzinfo=timezone.utc)


class FakeGraph:
    def __init__(self):
        self.nodes: dict[str, dict] = {}

    def add(self, type_name: str, node_id: str, name: str | None = None, **props) -> str:
        self.nodes[node_id] = {"id": node_id, "type": type_name, "name": name or node_id, **props}
        return node_id

    def _render(self, value):
        if isinstance(value, Ref):
            node = self.nodes[value.id]
            return {"id": node["id"], "type": node["type"], "name": node["name"]}
        if isinstance(value, list):
            return [self._render(v) for v in value]
        return value

    def _row(self, node: dict) -> dict:
        return {k: self._render(v) for k, v in node.items()}

    def get_all(self, type_name: str, node_id: str | None = None) -> dict:
        if node_id is not None:
            return {"result": self._row(self.nodes[node_id])}
        return {"result": [self._row(n) for n in self.nodes.values() if n["type"] == type_name]}

    def get(self, path: str, params: dict | None = None) -> dict:
        """A query: rows filtered on their properties, then rendered as Structr's default view
        renders them, id, type and name only. Anything else needs get_all(type, id), as on Structr."""
        rows = self.get_all(path.rsplit("/", 1)[-1])["result"]
        for key, value in (params or {}).items():
            rows = [r for r in rows if r.get(key) == value]
        return {"result": [{"id": r["id"], "type": r["type"], "name": r["name"]} for r in rows]}


def type_tree(graph: FakeGraph, tree: dict, parent: str | None = None) -> None:
    """Add DomainTypes from a nested dict: {"Poultry": {"Chicken": {}, "Turkey": {}}}.
    Node ids are the names."""
    for name, children in tree.items():
        graph.add("DomainType", name, parent=Ref(parent) if parent else None,
                  children=[Ref(c) for c in children], defaultSpecifications=[], stockPoliciesApplying=[])
        type_tree(graph, children, name)


class WritableGraph(FakeGraph):
    """FakeGraph with the write side the loaders use (post, patch, delete). Relationship
    fields are stored as Refs, so they render as Structr renders them, and the reverse
    side of the relationships the code reads back is kept up to date."""

    RELATIONS = {"hierarchy", "parent", "isAbout", "forNutrient", "identifierScheme", "denotesType", "inScheme",
                 "forType", "hasKind", "hasValue", "keyedBy", "hasTargetRange", "instanceOf", "memberOfSet",
                 "inheresIn", "isAboutQuality", "wasDerivedFrom", "forPerson", "members", "hasBaseline"}
    REVERSES = {"forType": "defaultSpecifications", "memberOfSet": "hasMemberPart", "parent": "children",
                "inheresIn": "bearerOf", "isAboutQuality": "measurements", "wasDerivedFrom": "imputedMeasurements",
                "forPerson": "nutritionTargets"}

    def __init__(self):
        super().__init__()
        self.posts = self.patches = 0

    def _link(self, node_id, key, old, new):
        reverse = self.REVERSES.get(key)
        if not reverse:
            return
        if isinstance(old, Ref) and old.id in self.nodes:
            self.nodes[old.id].setdefault(reverse, [])
            self.nodes[old.id][reverse] = [r for r in self.nodes[old.id][reverse] if r.id != node_id]
        if isinstance(new, Ref):
            self.nodes[new.id].setdefault(reverse, []).append(Ref(node_id))

    def _store(self, node_id, fields):
        for key, value in fields.items():
            if key in self.RELATIONS and value is not None:
                value = [Ref(v) for v in value] if isinstance(value, list) else Ref(value)
            self._link(node_id, key, self.nodes[node_id].get(key), value)
            self.nodes[node_id][key] = value

    def post(self, path, payload):
        type_name = path.rsplit("/", 1)[-1]
        node_id = f"{type_name}:{payload['name']}"
        self.add(type_name, node_id, name=payload["name"])
        self._store(node_id, {k: v for k, v in payload.items() if k != "name"})
        self.posts += 1
        return {"result": [node_id]}

    def patch(self, path, payload):
        self._store(path.rsplit("/", 1)[-1], payload)
        self.patches += 1

    def delete(self, path):
        node_id = path.rsplit("/", 1)[-1]
        for key in self.REVERSES:
            self._link(node_id, key, self.nodes[node_id].get(key), None)
        del self.nodes[node_id]
