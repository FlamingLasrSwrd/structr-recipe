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

    def get_all(self, type_name: str, node_id: str | None = None, where: dict | None = None, view: str = "all") -> dict:
        if node_id is not None:
            return {"result": self._row(self.nodes[node_id])}
        return {"result": [self._row(n) for n in self.nodes.values() if n["type"] == type_name
                           and all(n.get(k) == v for k, v in (where or {}).items())]}

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
                 "inheresIn", "isAboutQuality", "wasDerivedFrom", "forPerson", "members", "hasBaseline", "servingOf",
                 "requestsRecipe", "memberOf", "references", "hasPlannedConsumption", "shareOf", "eatenBy",
                 "consumesLeftoverFrom", "mayBearFunction"}
    REVERSES = {"forType": "defaultSpecifications", "memberOfSet": "hasMemberPart", "parent": "children",
                "inheresIn": "bearerOf", "isAboutQuality": "measurements", "wasDerivedFrom": "imputedMeasurements",
                "forPerson": "nutritionTargets", "servingOf": "servingProfiles", "memberOf": "hasEntry",
                "shareOf": "hasShare", "consumesLeftoverFrom": "sourceForLeftoverEntries"}

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
        """As on Structr: what the node owns through a relationship whose cascadingDeleteFlag the graph's
        SchemaRelationshipNode rows set (cascading_schema below) goes with it, even if something else holds it."""
        node_id = path.rsplit("/", 1)[-1]
        node = self.nodes[node_id]
        owned = [ref.id for key in self._cascades().get(node["type"], ())
                 for ref in (node.get(key) if isinstance(node.get(key), list) else [node.get(key)]) if isinstance(ref, Ref)]
        for key in self.REVERSES:
            self._link(node_id, key, node.get(key), None)
        del self.nodes[node_id]
        for other in self.nodes.values():        # its relationships go with it, so no other node still names it
            for key, value in other.items():
                if isinstance(value, Ref) and value.id == node_id:
                    other[key] = None
                elif isinstance(value, list) and any(isinstance(v, Ref) and v.id == node_id for v in value):
                    other[key] = [v for v in value if not (isinstance(v, Ref) and v.id == node_id)]
        for target in owned:                  # inside Structr: not a request, so past any wrapper a test puts on delete
            if target in self.nodes:
                WritableGraph.delete(self, f"/structr/rest/{self.nodes[target]['type']}/{target}")

    def _cascades(self) -> dict[str, list[str]]:
        """{source type: the properties on it of its relationships set to cascade}, from the schema rows."""
        names = {n["id"]: n["name"] for n in self.nodes.values() if n["type"] == "SchemaNode"}
        out: dict[str, list[str]] = {}
        for row in self.nodes.values():
            if row["type"] == "SchemaRelationshipNode" and row.get("cascadingDeleteFlag") == 1:
                out.setdefault(names[row["sourceId"]], []).append(row["targetJsonName"])
        return out


def cascading_schema(graph: FakeGraph, flag: int = 1) -> None:
    """The schema rows of mealplanner/cascade_schema.py's relationships, with their cascadingDeleteFlag
    (1 as scripts/44a leaves them; 0 as before it)."""
    from mealplanner.cascade_schema import declarations
    for source, rel_type, target, src_mult, tgt_mult, src_json, tgt_json in declarations():
        for type_name in (source, target):
            graph.nodes.setdefault(f"schema:{type_name}", {"id": f"schema:{type_name}", "type": "SchemaNode",
                                                           "name": type_name, "inheritedTraits": []})
        graph.add("SchemaRelationshipNode", f"schema:{rel_type}", name=rel_type, relationshipType=rel_type,
                  sourceId=f"schema:{source}", targetId=f"schema:{target}", sourceMultiplicity=src_mult,
                  targetMultiplicity=tgt_mult, sourceJsonName=src_json, targetJsonName=tgt_json,
                  cascadingDeleteFlag=flag)
