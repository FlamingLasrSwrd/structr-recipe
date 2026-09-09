"""Closes the smaller sibling of the opened-status gap: §8's ShelfLife
compound key is (Storage Condition, opened status), but this project
had only ever hardcoded "Fridge" everywhere -- no ContainerObject
recorded which storage condition it actually sits in. Same pattern as
mealplanner/opened_status_schema.py, same reasoning: an independent
instance-level classification on ContainerObject, orthogonal to
instanceOf (what KIND of container) and hasOpenedStatus (is it open).

Storage Condition vocabulary (Fridge/Freezer/Pantry) already exists
(seeded in step 5) -- this just adds the relation that lets a real
container carry one.
"""

PROPERTIES: dict[str, list[dict]] = {}

RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("ContainerObject", "HAS_STORAGE_CONDITION", "DomainType", "*", "1", "containersWithThisStorageCondition", "hasStorageCondition"),
]
