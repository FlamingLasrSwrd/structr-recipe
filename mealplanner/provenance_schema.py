"""Provenance and source on DefaultSpecification (data-model.md Sec 18 J21).

A density or a weight per item is a figure like any nutrient amount: it comes
from somewhere, and it may be a published value or an estimate. The owner asked
that every such figure say which, and where it came from, so it can be checked
and replaced later. NutrientProfile carries the same two properties
(mealplanner/nutrition_schema.py). Nothing computes with them yet: they are the
record.
"""

from mealplanner.nutrition_schema import PROVENANCE_FORMAT

PROPERTIES: dict[str, list[dict]] = {
    "DefaultSpecification": [
        {"name": "provenance", "propertyType": "Enum", "format": PROVENANCE_FORMAT},
        {"name": "source", "propertyType": "String"},
    ],
}
