"""Identifier: a code that refers to a thing, data-model.md Sec 6.

"`Identifier` (Designative ICE): `identifier_scheme` -> a Concept;
`identifier_value` -> literal; `denotes` -> any Entity." The structural type
has existed since step 1 with no properties and no instances; nothing needed a
code until real data arrived. Two schemes are needed now: the web page a
recipe was transcribed from, and (for ingredients) a USDA FoodData Central
food id. Both are Concepts in the "Identifier Scheme" ConceptScheme, which the
model lists among its SKOS schemes (Sec 3).

`identifierValue` is deliberately NOT unique: uniqueness in Structr is global
across every type sharing the property, and invariant 11 wants UUIDs unique
within their scheme while GTINs may be shared (build sketch, "Trait-level
unique is global across subtypes"). DENOTES targets the Entity trait, the same
single polymorphic declaration as Allocation -[ABOUT]-> Entity (step 2), so
any BFO node can carry identifiers; the reverse is `Entity.identifiers`.

A Type needs a second declaration. The build sketch says every concrete type
inherits Entity, but the metamodel types do not: DomainType and TypeHierarchy
have no traits at all (universals reified as data, not BFO particulars), so
`denotes` cannot reach "Chicken Breast (raw)". The model's own examples need
exactly that (Sec 6: a GTIN denotes a packaged-offering Type; Sec 5.2: a Type
"with an FDC mapping"). So an Identifier denotes an instance through `denotes`
or a Type through `denotesType`, never both; the reverse is
`DomainType.identifiers`. Recorded in docs/structr-build-sketch.md.
"""

PROPERTIES: dict[str, list[dict]] = {
    "Identifier": [
        {"name": "identifierValue", "propertyType": "String", "indexed": True},
    ],
}

# (source, rel_type, target, source_mult, target_mult, source_json_name, target_json_name)
RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("Identifier", "IDENTIFIER_SCHEME", "Concept", "*", "1", "identifiersInScheme", "identifierScheme"),
    ("Identifier", "DENOTES", "Entity", "*", "1", "identifiers", "denotes"),
    ("Identifier", "DENOTES", "DomainType", "*", "1", "identifiers", "denotesType"),
]

SCHEME = "Identifier Scheme"
WEB_PAGE = "Web page"            # the URL of the page a recipe was transcribed from
FDC_ID = "FDC ID"                # a USDA FoodData Central food id
SCHEME_CONCEPTS = [WEB_PAGE, FDC_ID]
