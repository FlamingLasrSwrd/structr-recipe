"""Resolving a DefaultSpecification by (kind, keyedBy), data-model.md Sec 8.

Sec 8's algorithm: start at the Type; if it has no applicable default, walk
subsumption upward; reaching the root with nothing yields "undefined, never a
guess"; and "each DefaultSpecification resolves independently by its
(hasKind, keyedBy) signature".

The StructrScript `resolveDefault` SchemaMethod (scripts/03c) only filters by
hasKind. Given a Type with Yield defaults keyed by Braising AND by Grilling,
it returns whichever it happens to find first, and callers then had to check
the key afterwards -- which cannot recover the right one if the wrong one came
back (found by external review; the material-accounting code had a comment
saying as much). Two code paths (shelf life and density/mass-per-unit)
already bypassed it with their own lookups. This is the one place the
algorithm now lives, in Python, where it has no depth limit.

Precedence, most to least important:
  1. the nearest Type (the Type itself, then its parent, and so on) that has
     ANY applicable default of this kind wins -- a more specific Type beats a
     more specific key;
  2. within that Type, an applicable default is one whose keys are all among
     the requested keys (a default keyed by something the caller doesn't have
     never applies); the one with the MOST keys wins, so an exact match beats
     a partial one, which beats an unkeyed one;
  3. two applicable defaults tied on key count are ambiguous and raise
     AmbiguousDefaultError rather than picking one.
"""

from __future__ import annotations

from dataclasses import dataclass

from mealplanner.typetree import ancestors_or_self


class AmbiguousDefaultError(RuntimeError):
    """Two defaults of one kind, on one Type, equally specific for the
    requested keys."""


@dataclass
class ResolvedDefault:
    quantity: dict            # the QuantitySpecification, fully loaded
    default_name: str         # the DefaultSpecification's name
    found_at_type_id: str     # the Type the default is attached to
    keyed_by: frozenset       # its keys (DomainType ids)


def resolve_default(client, type_id: str, kind_id: str, keys=frozenset()) -> ResolvedDefault | None:
    """The default of `kind_id` that applies to `type_id` in the context
    `keys` (a set of DomainType ids, e.g. the Transformation or the Storage
    Condition and opened status), or None."""
    keys = frozenset(keys)
    for level_type in ancestors_or_self(client, type_id):
        node = client.get_all("DomainType", level_type)["result"]
        applicable = []
        for ref in node.get("defaultSpecifications", []):
            spec = client.get_all("DefaultSpecification", ref["id"])["result"]
            if (spec.get("hasKind") or {}).get("id") != kind_id:
                continue
            spec_keys = frozenset(k["id"] for k in spec.get("keyedBy", []))
            if spec_keys <= keys:
                applicable.append((spec_keys, spec))
        if not applicable:
            continue
        most = max(len(k) for k, _ in applicable)
        best = [(k, s) for k, s in applicable if len(k) == most]
        if len(best) > 1:
            raise AmbiguousDefaultError(
                f"{len(best)} defaults of one kind on {node.get('name')!r} are equally specific for the requested "
                f"keys: {sorted(s['name'] for _, s in best)}"
            )
        spec_keys, spec = best[0]
        value_ref = spec.get("hasValue")
        if not value_ref:
            raise ValueError(f"DefaultSpecification {spec['name']!r} has no value")
        return ResolvedDefault(
            quantity=client.get_all("QuantitySpecification", value_ref["id"])["result"],
            default_name=spec["name"], found_at_type_id=level_type, keyed_by=spec_keys,
        )
    return None
