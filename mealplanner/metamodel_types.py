"""The metamodel layer: data-node types (not schema), per
structr-build-sketch.md Sec 4.

These ARE Structr SchemaNodes (DomainType, TypeHierarchy, RelationKind
are structural, created once and frozen) but their INSTANCES are the
mutable metamodel data -- individual domain types like "AP Flour" or
"Braising" are DomainType data nodes, not separate SchemaNodes. This is
the whole point of the three-layer split (build sketch Sec 1): a new
domain type costs a data write, never a schema change.

FOR_TYPE is a bespoke relation not named anywhere in data-model.md --
the model says "InstantiationPattern holds DefaultSpecifications for
one Type" but never names the Type<->pattern/spec relation (Sec 7's
relation list has no entry for it). This is the same category of gap
as bfo-reference.md's E9 (the undocumented Concept-to-instance tagging
relation). For this spike, DefaultSpecification points directly at the
DomainType it describes via FOR_TYPE, bypassing InstantiationPattern
entirely -- InstantiationPattern exists as a structural type already
but is not wired into this minimal resolveDefault test. Worth deciding
properly (does a DefaultSpec go through InstantiationPattern, or point
at its Type directly?) before this pattern is used for real vocabulary.
"""

PROPERTIES: dict[str, list[dict]] = {
    "DomainType": [
        {"name": "name", "propertyType": "String", "unique": True, "indexed": True, "notNull": True},
        {"name": "isLookupBearing", "propertyType": "Boolean"},
    ],
    "TypeHierarchy": [
        {"name": "name", "propertyType": "String", "unique": True, "indexed": True, "notNull": True},
        {"name": "singleParent", "propertyType": "Boolean"},
    ],
    "RelationKind": [
        {"name": "name", "propertyType": "String", "unique": True, "indexed": True, "notNull": True},
    ],
    "QuantitySpecification": [
        {"name": "value", "propertyType": "Double"},
        {"name": "unit", "propertyType": "String"},
        {"name": "status", "propertyType": "Enum", "format": "specified,default"},
    ],
}

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    # DomainType self-reference: a child (source) has at most one direct
    # parent (target_mult=1); a parent (target) may have many children
    # (source_mult=*).
    ("DomainType", "SUBCLASS_OF", "DomainType", "*", "1", "children", "parent"),
    # A DomainType belongs to exactly one TypeHierarchy for this spike --
    # see the module docstring's note on the unresolved cross-hierarchy
    # multi-parent question (AP Flour case in data-model.md Sec 1).
    ("DomainType", "IN_HIERARCHY", "TypeHierarchy", "*", "1", "domainTypes", "hierarchy"),
    ("RelationKind", "SUBCLASS_OF", "RelationKind", "*", "1", "children", "parent"),
    # DefaultSpecification's three-ish fields (Sec 8): hasKind, keyedBy,
    # hasValue, plus FOR_TYPE (this spike's bridge, see docstring).
    ("DefaultSpecification", "HAS_KIND", "DomainType", "*", "1", "defaultSpecsByKind", "hasKind"),
    ("DefaultSpecification", "KEYED_BY", "DomainType", "*", "*", "defaultSpecsKeyedBy", "keyedBy"),
    ("DefaultSpecification", "HAS_VALUE", "QuantitySpecification", "1", "1", "defaultSpecification", "hasValue"),
    ("DefaultSpecification", "FOR_TYPE", "DomainType", "*", "1", "defaultSpecifications", "forType"),
    # targetType: Yield-kind DefaultSpecifications only (data-model.md
    # Sec 8's DefaultSpecification field table) -- what the
    # transformation produces. Distinct reverse name from the other
    # three DomainType-targeting relations above (see the cheatsheet's
    # JSON-name-collision warning: reusing HAS_KIND's "hasKind" forward
    # name across different source types is fine, reusing a reverse
    # name landing on the same shared target type is not).
    ("DefaultSpecification", "TARGET_TYPE", "DomainType", "*", "1", "yieldTargetOf", "targetType"),
]
