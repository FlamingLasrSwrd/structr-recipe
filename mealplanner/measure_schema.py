"""Schema for a person's preferred measure (docs/todo.md, "Usable measurements in recipes";
docs/recipe-format.md, "Amounts as weights"; mealplanner/weights.py).

  Person.preferredMeasure    Enum "written" or "weight": how the recipe page shows a recipe's amounts
                             to them. Unset reads as "written". A preference, not a fact about food:
                             nothing about a recipe is stored differently (the owner, 2026-10-31,
                             "I think that should be a personal preference").

A plain property on a type that already has instances: the safe kind of addition (hard rule 2 is
about traits). Set from the household file (`measure = "weight"`, mealplanner/household.py).
"""

MEASURES = ("written", "weight")
PROPERTY = "preferredMeasure"

PROPERTIES: dict[str, list[dict]] = {
    "Person": [{"name": PROPERTY, "propertyType": "Enum", "format": ",".join(MEASURES)}],
}


def schema_ready(client) -> bool:
    """Whether this instance can hold a person's preferred measure (scripts/49a)."""
    nodes = client.get("/structr/rest/SchemaNode", params={"name": "Person"})["result"]
    return bool(nodes) and bool(client.get("/structr/rest/SchemaProperty",
                                           params={"schemaNode": nodes[0]["id"], "name": PROPERTY})["result"])
