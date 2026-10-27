"""Schema for a tool named by what it does (data-model.md Sec 5, Sec 18 J37; docs/recipe-format.md).

  DomainType -[MAY_BEAR_FUNCTION]-> DomainType
      an Equipment Type's capabilities: Function types in the Capability hierarchy (Sec 3), a
      type-level claim of what its tools can do ("an oven can give broiler heat"), as `may_bear_role`
      (Sec 5.3) is a food's. An instrument Specification may specify a capability instead of a tool
      (Sec 5's `specifies`), and any tool whose type bears it, or one of its subtypes, will do.

The Capability hierarchy, with Capability and Heating in it, has been seeded since scripts/05; its
other types are vocabulary (data/vocabulary.toml, tools/import_vocabulary.py). A plain relationship
between DomainTypes, the safe kind of addition (scoring_schema.py's notes).
"""

CAPABILITY_HIERARCHY = "Capability"
RELATIONSHIP = "MAY_BEAR_FUNCTION"

RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("DomainType", RELATIONSHIP, "DomainType", "*", "*", "functionBorneBy", "mayBearFunction"),
]


def schema_ready(client) -> bool:
    """Whether this instance can say what a tool can do (scripts/43a)."""
    return bool(client.get("/structr/rest/SchemaRelationshipNode", params={"relationshipType": RELATIONSHIP})["result"])
