"""Domain invariants that became checkable once the meal-planning
schema existed. See mealplanner/domain_invariants.py for the sources
and reasoning. Extends (does not replace) script 07's original set.

Run with: python3 scripts/10b_meal_planning_invariants.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import StructrClient
from mealplanner.domain_invariants import (
    QUANTITY_SPECIFICATION_ONCREATE,
    MEAL_PLAN_ENTRY_ONCREATE,
    STOCK_POLICY_ONCREATE,
)

BASE_URL = "http://localhost:8083"
USERNAME = "superadmin"
PASSWORD = os.environ["STRUCTR_SUPERUSER_PASSWORD"]


def node_id(client, name: str) -> str:
    return client.get("/structr/rest/SchemaNode", params={"name": name})["result"][0]["id"]


def main():
    client = StructrClient(BASE_URL, USERNAME, PASSWORD)
    client.wait_until_ready()

    for type_name, source in [
        ("QuantitySpecification", QUANTITY_SPECIFICATION_ONCREATE),
        ("MealPlanEntry", MEAL_PLAN_ENTRY_ONCREATE),
        ("StockPolicy", STOCK_POLICY_ONCREATE),
    ]:
        method_id, created = client.ensure_method(node_id(client, type_name), "onCreate", source, return_raw_result=False)
        print(f"{type_name}.onCreate: id={method_id}, created={created}")


if __name__ == "__main__":
    main()
