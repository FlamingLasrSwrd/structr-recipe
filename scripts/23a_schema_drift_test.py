"""Offline test that ensure_type / ensure_property / ensure_relationship
refuse to reconcile a live schema object that differs from the
declaration. Needs no Structr: runs against an in-memory fake that
mimics the parts of the REST API the helpers use.

Why this exists: external review found the helpers only checked that a
schema object EXISTED, so a live property whose type, uniqueness,
nullability or format had diverged from the code was reported as
"created=False" and everything looked fine. The fake's patch() and
delete() fail the test outright, so any helper that tries to "fix" a
live object rather than raising is caught.

The zero-false-positives half of the claim can't be tested offline: it
was checked by re-running every schema script against the live schema
(see the commit that introduced SchemaDriftError).

Run with: python3 scripts/23a_schema_drift_test.py
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from structr_client import SchemaDriftError, StructrClient


class FakeClient(StructrClient):
    """In-memory stand-in. Skips StructrClient.__init__ (no HTTP session)."""

    def __init__(self):
        self.store = {"SchemaNode": {}, "SchemaProperty": {}, "SchemaRelationshipNode": {}}

    def get(self, path, params=None):
        rows = list(self.store[path.rsplit("/", 1)[-1]].values())
        for key, value in (params or {}).items():
            if key == "schemaNode":
                rows = [r for r in rows if r["schemaNode"]["id"] == value]
            else:
                rows = [r for r in rows if r.get(key) == value]
        return {"result": [dict(r) for r in rows]}

    def post(self, path, json):
        kind = path.rsplit("/", 1)[-1]
        node_id = uuid.uuid4().hex
        record = dict(json, id=node_id)
        if kind == "SchemaNode":
            record.setdefault("isAbstract", False)
            record.setdefault("inheritedTraits", [])
        elif kind == "SchemaProperty":
            record["schemaNode"] = {"id": json["schemaNode"]}
            for flag in ("unique", "indexed", "notNull"):
                record.setdefault(flag, False)
            record.setdefault("format", None)
        self.store[kind][node_id] = record
        return {"result": [node_id]}

    def patch(self, path, json):
        raise AssertionError(f"a schema helper tried to PATCH a live object: {path} {json}")

    def delete(self, path):
        raise AssertionError(f"a schema helper tried to DELETE: {path}")


def snapshot(client):
    return {k: {i: dict(r) for i, r in v.items()} for k, v in client.store.items()}


def main():
    failures = []

    def check(ok, label):
        if not ok:
            failures.append(label)
        print(f"    [{'OK' if ok else 'FAIL'}] {label}")

    def raises_drift(fn, attrs, label):
        """fn raises SchemaDriftError naming exactly `attrs`, and leaves the store untouched."""
        before = snapshot(c)
        try:
            fn()
        except SchemaDriftError as exc:
            check(set(exc.differences) == set(attrs) and snapshot(c) == before, label)
            return
        check(False, label + " (no error raised)")

    c = FakeClient()

    print("[1] ensure_type...")
    tid, created = c.ensure_type("Base", is_abstract=True)
    check(created is True, "creates a new type")
    child, created = c.ensure_type("Child", is_abstract=False, inherited_traits=["Base"])
    check(c.ensure_type("Child", is_abstract=False, inherited_traits=["Base"]) == (child, False), "same declaration again: created=False, no error")
    check(c.ensure_type("Child", is_abstract=False)[1] is False, "traits not declared (None) skips the trait comparison")
    raises_drift(lambda: c.ensure_type("Child", is_abstract=False, inherited_traits=["Other"]), ["inheritedTraits"],
                 "different inheritedTraits raises, names it, and does not patch")
    raises_drift(lambda: c.ensure_type("Child", is_abstract=True, inherited_traits=["Base"]), ["isAbstract"],
                 "different isAbstract raises")

    print("\n[2] ensure_property: every structural attribute is compared...")
    declared = dict(unique=True, indexed=True, not_null=True, format="a,b")
    pid, created = c.ensure_property(child, "kind", "Enum", **declared)
    check(created is True, "creates a new property")
    check(c.ensure_property(child, "kind", "Enum", **declared) == (pid, False), "identical declaration: no error")
    check(c.ensure_property(child, "plain", "String")[1] is True and c.ensure_property(child, "plain", "String")[1] is False,
          "a property with all defaults (format None, flags False) doesn't false-positive against itself")
    for attr, kwargs, arg_type in (
        ("propertyType", declared, "String"),
        ("unique", {**declared, "unique": False}, "Enum"),
        ("indexed", {**declared, "indexed": False}, "Enum"),
        ("notNull", {**declared, "not_null": False}, "Enum"),
        ("format", {**declared, "format": "a,b,c"}, "Enum"),
    ):
        raises_drift(lambda k=kwargs, t=arg_type: c.ensure_property(child, "kind", t, **k), [attr], f"differing {attr} raises, and only {attr}")
    raises_drift(lambda: c.ensure_property(child, "plain", "String", format="x"), ["format"],
                 "declaring a format the live property lacks is drift too")

    print("\n[3] ensure_relationship: every attribute is compared...")
    rel_args = dict(relationship_type="REL", source_multiplicity="*", target_multiplicity="1",
                    source_json_name="things", target_json_name="thing")
    rid, created = c.ensure_relationship(source_id=child, target_id=tid, **rel_args)
    check(created is True, "creates a new relationship")
    check(c.ensure_relationship(source_id=child, target_id=tid, **rel_args) == (rid, False), "identical declaration: no error")
    for attr, override in (
        ("sourceMultiplicity", {"source_multiplicity": "1"}),
        ("targetMultiplicity", {"target_multiplicity": "*"}),
        ("sourceJsonName", {"source_json_name": "others"}),
        ("targetJsonName", {"target_json_name": "other"}),
    ):
        raises_drift(lambda o=override: c.ensure_relationship(source_id=child, target_id=tid, **{**rel_args, **o}),
                     [attr], f"differing {attr} raises")
    other_id, _ = c.ensure_type("Other", is_abstract=False)
    other_rel, created = c.ensure_relationship(source_id=child, target_id=other_id, **{**rel_args, "source_json_name": "x", "target_json_name": "y"})
    check(created is True and other_rel != rid,
          "same relationshipType between a DIFFERENT source/target pair is a new relationship, not drift")

    print("\n[4] the error message says what to do...")
    try:
        c.ensure_property(child, "kind", "String", **declared)
    except SchemaDriftError as exc:
        text = str(exc)
        check("live=" in text and "declared=" in text and "Refusing" in text, "message shows live vs declared and refuses")

    if failures:
        print(f"\nFAILED ({len(failures)}):")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
