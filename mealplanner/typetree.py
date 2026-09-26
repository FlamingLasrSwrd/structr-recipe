"""Walks of the DomainType hierarchy (SUBCLASS_OF), shared by the modules
that need to answer "what is below / above this type". They live here, not in
inventory.py, so defaults.py, unit_conversion.py and inventory.py can all use
them without importing each other in a cycle.
"""

from __future__ import annotations


def subtypes_of(client, domain_type_id: str) -> set[str]:
    """domain_type_id and every descendant, walking SUBCLASS_OF downward."""
    result = {domain_type_id}
    frontier = [domain_type_id]
    while frontier:
        current = frontier.pop()
        node = client.get_all("DomainType", current)["result"]
        for child in node.get("children", []):
            if child["id"] not in result:
                result.add(child["id"])
                frontier.append(child["id"])
    return result


def ancestors_or_self(client, domain_type_id: str) -> list[str]:
    """[domain_type_id, its parent, grandparent, ..., root], nearest first."""
    chain, seen, current = [], set(), domain_type_id
    while current and current not in seen:
        seen.add(current)
        chain.append(current)
        parent = client.get_all("DomainType", current)["result"].get("parent")
        current = parent["id"] if parent else None
    return chain
