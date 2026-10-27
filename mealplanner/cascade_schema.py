"""Cascading delete on the relationships that hold what a recipe's Step owns (scripts/44a;
docs/structr-features.md, batch 2).

A Step owns its Specifications and its working and waiting minutes; a Specification owns its
quantity, its state requirements and its substitution rules; a state requirement owns its value.
With Structr's cascadingDeleteFlag set to source-to-target on these, deleting a Step or a
Specification deletes what it owns in the same transaction: what recipe_import._remove_stale used
to do by hand, one request each, so that an interrupted import could leave a quantity or a rule
behind. On an instance before 44a (a rebuild's earlier scripts) delete_owned() does the same by
hand.

Structr deletes a target even when another node still points at it (the cascade_more spike,
docs/structr-features.md section 3). So every target here must belong to its source alone:
recipe_import names each after what owns it, and shared_targets() finds any that does not, which
scripts/44a refuses to turn the flags on over.
"""

from __future__ import annotations

from mealplanner import recipe_schema, step_facts_schema, substitution_schema

SOURCE_TO_TARGET = 1      # Structr's cascadingDeleteFlag: 1 deletes the target with its source

CASCADING = ("HAS_SPECIFICATION", "HAS_WORKING_TIME", "HAS_WAITING_TIME", "HAS_SPECIFIED_QUANTITY",
             "HAS_STATE_REQUIREMENT", "HAS_SUBSTITUTION_RULE", "EXPECTED_VALUE_QTY")

# Relationships that only refer to what a Step owns: a cook's Allocation fulfilling a Specification, an
# Identifier denoting it, a Process's input or participant, an Allocation about it, a Measurement derived
# from a quantity. When the owner goes, such a reference goes with what it names, as it did when the importer
# deleted by hand (and the importer never removes a cooked Plan's steps). Any other relationship into a
# target, a default's value or a target's range among them, and any added later, holds it: a node so held
# is not its owner's alone.
REFERENCES = ("FULFILLS", "DENOTES", "HAS_INPUT", "HAS_PARTICIPANT", "ABOUT", "WAS_DERIVED_FROM")


def declarations() -> list[tuple[str, str, str, str, str, str, str]]:
    """The cascading relationships as their schema modules declare them, in CASCADING's order:
    (source, type, target, source multiplicity, target multiplicity, source json name, target json name)."""
    declared = {rel[1]: rel for rel in (recipe_schema.RELATIONSHIPS + step_facts_schema.RELATIONSHIPS
                                        + substitution_schema.RELATIONSHIPS) if rel[1] in CASCADING}
    return [declared[rel_type] for rel_type in CASCADING]


def owned_by() -> dict[str, list[str]]:
    """For each source type, the properties naming what it owns (the target json name is the property on
    the source, hard rule 6): {"Step": ["hasSpecification", ...], ...}."""
    out: dict[str, list[str]] = {}
    for source, _, _, _, _, _, target_json in declarations():
        out.setdefault(source, []).append(target_json)
    return out


def relationship_rows(client) -> dict[str, dict]:
    """The live SchemaRelationshipNode of each cascading relationship, by type (from its source and target
    as declared, since a relationship type may be declared between other types too)."""
    names = {n["id"]: n["name"] for n in client.get_all("SchemaNode")["result"]}
    rows = {}
    for source, rel_type, target, *_ in declarations():
        for row in client.get_all("SchemaRelationshipNode", where={"relationshipType": rel_type})["result"]:
            if names.get(row.get("sourceId")) == source and names.get(row.get("targetId")) == target:
                rows[rel_type] = row
    return rows


def not_cascading(client) -> list[str]:
    """The cascading relationships whose flag this instance does not have yet (empty once 44a has run)."""
    rows = relationship_rows(client)
    return [rel_type for rel_type in CASCADING if (rows.get(rel_type) or {}).get("cascadingDeleteFlag") != SOURCE_TO_TARGET]


def delete_owned(client, type_name: str, node_id: str) -> None:
    """Delete what the node owns, and what that owns, by hand: what Structr's cascade does where 44a has
    set the flags. The node itself stays."""
    node = client.get_all(type_name, node_id)["result"]
    for key in owned_by().get(type_name, []):
        for ref in _refs(node.get(key)):
            delete_owned(client, ref["type"], ref["id"])
            client.delete(f"/structr/rest/{ref['type']}/{ref['id']}")


def shared_targets(client) -> list[str]:
    """Every node a cascading relationship points at that something else holds too: another owner, or a node
    of any relationship into its type but the REFERENCES. Deleting its owner would delete it from under the
    other (the cascade_more spike). Read-only; one line per such node."""
    incoming = _incoming_properties(client)
    found = []
    for target_type in sorted({rel[2] for rel in declarations()}):
        for node in client.get_all(target_type)["result"]:
            holders = {ref["id"] for key in incoming.get(target_type, ()) for ref in _refs(node.get(key))}
            owners = {ref["id"] for rel in declarations() if rel[2] == target_type for ref in _refs(node.get(rel[5]))}
            if owners and len(holders) > 1:
                found.append(f"{target_type} {node.get('name') or node['id']}: held by {len(holders)} nodes")
    return found


def _incoming_properties(client) -> dict[str, list[str]]:
    """For each cascade target type, the property on it of every relationship that ends there, its own or
    a trait's it inherits, but the REFERENCES (the source json name is the property on the target, hard
    rule 6)."""
    nodes = client.get_all("SchemaNode")["result"]
    by_id = {n["id"]: n for n in nodes}
    by_name = {n["name"]: n for n in nodes}

    def lineage(name: str) -> set[str]:
        seen, todo = set(), [name]
        while todo:
            current = todo.pop()
            if current in seen or current not in by_name:
                continue
            seen.add(current)
            todo.extend(by_name[current].get("inheritedTraits") or [])
        return seen

    rels = client.get_all("SchemaRelationshipNode")["result"]
    out = {}
    for target_type in {rel[2] for rel in declarations()}:
        types = lineage(target_type)
        out[target_type] = sorted({r["sourceJsonName"] for r in rels
                                   if (by_id.get(r.get("targetId")) or {}).get("name") in types and r.get("sourceJsonName")
                                   and r.get("relationshipType") not in REFERENCES})
    return out


def _refs(value) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    return [v for v in value or [] if isinstance(v, dict)]
