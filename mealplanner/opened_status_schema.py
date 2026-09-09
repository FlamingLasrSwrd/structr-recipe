"""Fixes the opened-status gap from the holes-and-gaps analysis: §8's
own worked example keys ShelfLife by [Fridge, Opened] / [Fridge, Sealed]
-- meaning Opened/Sealed are meant to be DomainType entries usable in a
keyedBy list, the same way Fridge is. This project had only ever
implemented the Storage-Condition half of that compound key; opened
status was modeled as ad hoc Booleans on StockPolicy
(eligibleWhenOpened/eligibleWhenSealed) with nothing behind them.

ContainerObject.hasOpenedStatus is the same "independent instance-level
classification" pattern already used for FoodObject.hasPerishabilityType
(Reading A, the multi-hierarchy resolution from the meal-planning
session) -- a container's opened/sealed state is a fact orthogonal to
what KIND of container it is (ContainerObject.instanceOf already covers
that, e.g. "Tray").
"""

PROPERTIES: dict[str, list[dict]] = {}

RELATIONSHIPS: list[tuple[str, str, str, str, str, str, str]] = [
    ("ContainerObject", "HAS_OPENED_STATUS", "DomainType", "*", "1", "containersWithThisOpenedStatus", "hasOpenedStatus"),
]

OPENED_STATUS_HIERARCHY = "Opened Status"
OPENED_STATUS_VALUES = ["Opened", "Sealed"]
