"""Spikes: does the Structr this project runs (6.0.0) do what the 7.x documentation describes?

Each spike asks one question that docs/structr-features.md left open, and answers it on a
THROWAWAY instance: it makes types of its own (named Spk...), users named spike-..., and functions
named spk..., checks the accepted and the refused case, and reports what it saw. Some need settings
at start (the changelog, a scheduled task, how unknown input keys are treated): tools/spikes/
run_spikes.sh starts a throwaway stack with them (docker-compose.spike.yml), runs `setup`, restarts
Structr, since a check made straight after a schema change is not to be trusted (hard rule 8), runs
`verify`, and destroys the stack.

    STRUCTR_URL=http://localhost:8084 python3 tools/spikes/structr_feature_spikes.py setup|verify|cleanup
        [--only cascade,compound,...] [--json results.json]

It refuses the development (8083) and owner (8085) ports, and connect() refuses the owner's instance.
Answers: OK (behaves as documented), DIFFERENT (it does not), INFO (a fact found), ERROR (the spike
itself failed: read its detail).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from mealplanner.connection import SUPERUSER, connect

REFUSED_PORTS = {8083, 8085}
# The spike users' password: generated, never shown. run_spikes.sh passes one to both phases;
# a phase run by hand without it makes its own, so set SPIKE_USER_PASSWORD to run them apart.
PASSWORD = os.environ.get("SPIKE_USER_PASSWORD") or secrets.token_urlsafe(18)
USERS = ("spike-a", "spike-b")
GROUP = "spike-group"
COMPOSE_PROJECT = os.environ.get("SPIKE_COMPOSE_PROJECT", "structr-spike")


# -- plumbing ------------------------------------------------------------------------------

class Ctx:
    def __init__(self, client):
        self.c = client
        self.base = client.base_url

    def raw(self, method, path, body=None, user=None, auth=True, timeout=120):
        """(status, parsed body or text), never raising on an HTTP error."""
        headers = {"Content-Type": "application/json"}
        if auth:
            name, password = user if user else (SUPERUSER, os.environ["STRUCTR_SUPERUSER_PASSWORD"])
            headers.update({"X-User": name, "X-Password": password})
        r = requests.request(method, self.base + path, headers=headers,
                             data=None if body is None else json.dumps(body), timeout=timeout)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text

    def ok(self, method, path, body=None, user=None):
        status, out = self.raw(method, path, body, user)
        if status >= 400:
            raise RuntimeError(f"{method} {path} -> {status}: {str(out)[:300]}")
        return out

    def one(self, type_name, name):
        found = self.ok("GET", f"/structr/rest/{type_name}?name={requests.utils.quote(name)}")["result"]
        return found[0]["id"] if found else None

    def node(self, type_name, node_id, user=None):
        status, out = self.raw("GET", f"/structr/rest/{type_name}/{node_id}/all", user=user)
        return out.get("result") if status == 200 and isinstance(out, dict) else None

    def schema_type(self, name, **fields):
        existing = self.one("SchemaNode", name)
        if existing:
            return existing
        return self.ok("POST", "/structr/rest/SchemaNode", {"name": name, **fields})["result"][0]

    def schema_prop(self, type_id, name, property_type, **flags):
        found = self.ok("GET", f"/structr/rest/SchemaProperty?schemaNode={type_id}&name={name}")["result"]
        if found:
            return found[0]["id"]
        return self.ok("POST", "/structr/rest/SchemaProperty",
                       {"schemaNode": type_id, "name": name, "propertyType": property_type, **flags})["result"][0]

    def schema_rel(self, source_id, target_id, rel_type, source_mult, target_mult, source_json, target_json, **extra):
        found = self.ok("GET", f"/structr/rest/SchemaRelationshipNode?relationshipType={rel_type}")["result"]
        if found:
            return found[0]["id"]
        return self.ok("POST", "/structr/rest/SchemaRelationshipNode", {
            "sourceId": source_id, "targetId": target_id, "relationshipType": rel_type,
            "sourceMultiplicity": source_mult, "targetMultiplicity": target_mult,
            "sourceJsonName": source_json, "targetJsonName": target_json, **extra})["result"][0]

    def function(self, name, source, **extra):
        found = [m for m in self.ok("GET", f"/structr/rest/SchemaMethod?name={name}")["result"]]
        if found:
            self.ok("PATCH", f"/structr/rest/SchemaMethod/{found[0]['id']}", {"source": source, **extra})
            return found[0]["id"]
        return self.ok("POST", "/structr/rest/SchemaMethod", {"name": name, "source": source, **extra})["result"][0]

    def call(self, name, body=None, user=None, method="POST", suffix=""):
        return self.raw(method, f"/structr/rest/{name}{suffix}", body if method != "GET" else None, user)

    def create(self, type_name, fields, flags=True):
        payload = dict(fields)
        if flags:
            payload.setdefault("visibleToAuthenticatedUsers", True)
        return self.ok("POST", f"/structr/rest/{type_name}", payload)["result"][0]

    def user(self, name):
        existing = self.one("User", name)
        if existing:
            return existing
        return self.ok("POST", "/structr/rest/User", {"name": name, "password": PASSWORD,
                                                     "visibleToAuthenticatedUsers": True})["result"][0]

    def resource(self, signature, flags=255):
        found = self.ok("GET", f"/structr/rest/ResourceAccess?signature={signature}")["result"]
        if found:
            return found[0]["id"]
        return self.ok("POST", "/structr/rest/ResourceAccess", {"signature": signature, "flags": flags,
                                                               "visibleToAuthenticatedUsers": True,
                                                               "visibleToPublicUsers": True})["result"][0]

    def schema_keys(self, type_name):
        status, out = self.raw("GET", f"/structr/rest/_schema/{type_name}")
        if status != 200:
            return None
        res = out["result"][0] if isinstance(out["result"], list) else out["result"]
        return sorted((p.get("jsonName") or k) for k, p in res.get("views", {}).get("all", {}).items())


def exec_in_structr(command: str, timeout=120) -> str:
    """Run a shell command in the throwaway stack's Structr container; its output, or why not."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        done = subprocess.run(["docker", "compose", "-p", COMPOSE_PROJECT, "exec", "-T", "structr", "sh", "-c", command],
                              cwd=root, capture_output=True, text=True, timeout=timeout)
        return (done.stdout + done.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(could not run in the container: {exc})"


def as_user(name):
    return (name, PASSWORD)


def count(ctx, type_name, user=None):
    status, out = ctx.raw("GET", f"/structr/rest/{type_name}", user=user)
    return len(out["result"]) if status == 200 else f"HTTP {status}"


def answer(ok_when: bool, documented: str, found: str):
    return {"answer": "OK" if ok_when else "DIFFERENT", "documented": documented, "found": found}


# -- the spikes ------------------------------------------------------------------------------
# Each is (name, question, setup, verify). setup makes schema; verify makes data and checks.

def cascade_setup(ctx):
    parent, child, keep = (ctx.schema_type(n) for n in ("SpkParent", "SpkChild", "SpkKeep"))
    ctx.schema_rel(parent, child, "SPK_HAS_CHILD", "1", "*", "parent", "children", cascadingDeleteFlag=1)
    ctx.schema_rel(parent, keep, "SPK_HAS_KEEP", "1", "*", "keeper", "kept", cascadingDeleteFlag=0)


def cascade_verify(ctx):
    rel = ctx.ok("GET", "/structr/rest/SchemaRelationshipNode?relationshipType=SPK_HAS_CHILD")["result"][0]
    flag = ctx.node("SchemaRelationshipNode", rel["id"]).get("cascadingDeleteFlag")
    child = ctx.create("SpkChild", {"name": "spike child"})
    keep = ctx.create("SpkKeep", {"name": "spike keep"})
    parent = ctx.create("SpkParent", {"name": "spike parent", "children": [child], "kept": [keep]})
    ctx.ok("DELETE", f"/structr/rest/SpkParent/{parent}")
    child_gone = ctx.node("SpkChild", child) is None
    keep_there = ctx.node("SpkKeep", keep) is not None
    return answer(child_gone and keep_there, "SOURCE_TO_TARGET deletes the target with its source; NONE does not",
                  f"stored cascadingDeleteFlag={flag!r}; child deleted with its parent: {child_gone}; "
                  f"the other relationship's target kept: {keep_there}")


def cascade_more_setup(ctx):
    """What a migration that turns cascading on for a populated relationship needs to know: nodes are
    made while the flag is 0, then it is set to 1 (the restart comes after setup)."""
    parent, child, grand, other = (ctx.schema_type(n) for n in ("SpkOwner", "SpkPart", "SpkSubPart", "SpkOther"))
    rel = ctx.schema_rel(parent, child, "SPK_HAS_PART", "*", "*", "owners", "parts", cascadingDeleteFlag=0)
    ctx.schema_rel(child, grand, "SPK_HAS_SUB_PART", "1", "*", "part", "subParts", cascadingDeleteFlag=1)
    ctx.schema_rel(other, child, "SPK_OTHER_PART", "*", "*", "others", "otherParts", cascadingDeleteFlag=0)
    if not ctx.one("SpkOwner", "spike owner old"):
        grandchild = ctx.create("SpkSubPart", {"name": "spike sub part"})
        old = ctx.create("SpkPart", {"name": "spike part old", "subParts": [grandchild]})
        shared = ctx.create("SpkPart", {"name": "spike part shared"})
        held = ctx.create("SpkPart", {"name": "spike part also held"})
        ctx.create("SpkOwner", {"name": "spike owner old", "parts": [old, shared, held]})
        ctx.create("SpkOwner", {"name": "spike owner second", "parts": [shared]})
        ctx.create("SpkOther", {"name": "spike other", "otherParts": [held]})
    ctx.ok("PATCH", f"/structr/rest/SchemaRelationshipNode/{rel}", {"cascadingDeleteFlag": 1})


def cascade_more_verify(ctx):
    flag = ctx.node("SchemaRelationshipNode", ctx.ok(
        "GET", "/structr/rest/SchemaRelationshipNode?relationshipType=SPK_HAS_PART")["result"][0]["id"]).get("cascadingDeleteFlag")
    ids = {n: ctx.one(t, n) for t, n in (("SpkOwner", "spike owner old"), ("SpkPart", "spike part old"),
                                          ("SpkPart", "spike part shared"), ("SpkPart", "spike part also held"),
                                          ("SpkSubPart", "spike sub part"), ("SpkOwner", "spike owner second"))}
    status = ctx.raw("DELETE", f"/structr/rest/SpkOwner/{ids['spike owner old']}")[0]
    gone = {n: ctx.node("SpkPart" if "part" in n and "sub" not in n else "SpkSubPart", ids[n]) is None
            for n in ("spike part old", "spike sub part", "spike part shared", "spike part also held")}
    second = ctx.node("SpkOwner", ids["spike owner second"]) or {}
    return {"answer": "OK" if gone["spike part old"] and gone["spike sub part"] else "DIFFERENT",
            "documented": "a flag set on a populated relationship applies to edges made before it; cascades chain",
            "found": f"flag now {flag!r}; deleting the owner: {status}; deleted with it: {gone}; the second "
                     f"owner's parts after: {[p.get('name') for p in second.get('parts') or []]}"}


def visibility_setup(ctx):
    ctx.schema_type("SpkVisible", defaultVisibleToAuth=True)
    ctx.schema_type("SpkPlain")
    for u in USERS:
        ctx.user(u)
    for sig in ("SpkVisible", "SpkPlain"):
        ctx.resource(sig)


def visibility_verify(ctx):
    v = ctx.create("SpkVisible", {"name": "spike default visible"}, flags=False)
    p = ctx.create("SpkPlain", {"name": "spike plain"}, flags=False)
    stored = ctx.node("SpkVisible", v).get("visibleToAuthenticatedUsers")
    seen_v = count(ctx, "SpkVisible", as_user("spike-a"))
    seen_p = count(ctx, "SpkPlain", as_user("spike-a"))
    return answer(seen_v == 1 and seen_p == 0,
                  "defaultVisibleToAuth makes every instance visible to signed-in users",
                  f"created without flags: visibleToAuthenticatedUsers={stored!r}; a signed-in user sees "
                  f"{seen_v} of 1 (the type without a default: {seen_p} of 1)")


def compound_setup(ctx):
    t = ctx.schema_type("SpkCompound")
    ctx.schema_prop(t, "a", "String", compound=True, indexed=True)
    ctx.schema_prop(t, "b", "String", compound=True, indexed=True)


def compound_verify(ctx):
    first = ctx.raw("POST", "/structr/rest/SpkCompound", {"a": "x", "b": "y", "visibleToAuthenticatedUsers": True})
    again = ctx.raw("POST", "/structr/rest/SpkCompound", {"a": "x", "b": "y", "visibleToAuthenticatedUsers": True})
    other = ctx.raw("POST", "/structr/rest/SpkCompound", {"a": "x", "b": "z", "visibleToAuthenticatedUsers": True})
    tokens = [e.get("token") for e in (again[1].get("errors") or [])] if isinstance(again[1], dict) else []
    return answer(first[0] == 201 and again[0] == 422 and other[0] == 201,
                  "compound uniqueness refuses a second (a, b) pair and allows a new combination",
                  f"(x,y) {first[0]}, (x,y) again {again[0]} {tokens}, (x,z) {other[0]}")


def format_setup(ctx):
    t = ctx.schema_type("SpkRange")
    ctx.schema_prop(t, "closed", "Double", format="[0,100]")
    found = {}
    ctx.schema_prop(t, "decimal", "Double", format="[0.0,100.0]")
    ctx.schema_prop(t, "whole", "Integer", format="[0,100]")
    for name, fmt in (("open", "[0,]"), ("halfopen", "[0,100[")):
        try:
            ctx.schema_prop(t, name, "Double", format=fmt)
            found[name] = "accepted"
        except RuntimeError as exc:
            found[name] = str(exc)[:160]
    ctx.ok("PATCH", f"/structr/rest/SchemaNode/{t}", {"summary": json.dumps(found)})
    pattern = ctx.schema_type("SpkPattern")            # a type of its own: a pattern also refuses a missing value
    ctx.schema_prop(pattern, "code", "String", format="[A-Z]{3}")


def format_verify(ctx):
    def status(fields, type_name="SpkRange"):
        return ctx.raw("POST", f"/structr/rest/{type_name}", {**fields, "visibleToAuthenticatedUsers": True})[0]
    t = ctx.one("SchemaNode", "SpkRange")
    declared = ctx.node("SchemaNode", t).get("summary")
    results = {"closed -1": status({"closed": -1.0}), "closed 50": status({"closed": 50.0}),
               "closed 150": status({"closed": 150.0}), "open -1": status({"open": -1.0}),
               "open 1e6": status({"open": 1e6}), "halfopen 100": status({"halfopen": 100.0}),
               "halfopen 99.9": status({"halfopen": 99.9}), "decimal 50": status({"decimal": 50.0}),
               "decimal -1": status({"decimal": -1.0}), "whole 50": status({"whole": 50}),
               "whole -1": status({"whole": -1}), "nothing": status({}),
               "code abc": status({"code": "abc"}, "SpkPattern"), "code ABC": status({"code": "ABC"}, "SpkPattern"),
               "code missing": status({}, "SpkPattern")}
    sample = ctx.raw("POST", "/structr/rest/SpkRange", {"closed": 150.0, "visibleToAuthenticatedUsers": True})[1]
    results["why closed 150"] = str(sample)[:200]
    ok = (results["closed -1"] == 422 and results["closed 50"] == 201 and results["closed 150"] == 422
          and results["code abc"] == 422 and results["code ABC"] == 201)
    return answer(ok, "a numeric interval and a string pattern in `format` refuse values outside them",
                  f"declaring the formats: {declared}; statuses: {results}")


def onsave_setup(ctx):
    t = ctx.schema_type("SpkSaved")
    ctx.schema_prop(t, "v", "Integer")
    source = """{
  const m = $.retrieve('modifications');
  if (!m) { $.error('v', 'no_modifications'); }
  else if (m.after && m.after.v !== undefined && m.after.v !== null) {
    if (m.after.v < 0) { $.error('v', 'negative_on_save'); }
    if (m.after.v === 999) { $.error('v', 'before_' + (m.before ? m.before.v : 'none')); }
  }
}"""
    if not ctx.ok("GET", f"/structr/rest/SchemaMethod?schemaNode={t}&name=onSave")["result"]:
        ctx.ok("POST", "/structr/rest/SchemaMethod", {"schemaNode": t, "name": "onSave", "source": source})


def onsave_verify(ctx):
    node = ctx.create("SpkSaved", {"name": "spike saved", "v": 1})
    neg = ctx.raw("PUT", f"/structr/rest/SpkSaved/{node}", {"v": -1})
    before = ctx.raw("PUT", f"/structr/rest/SpkSaved/{node}", {"v": 999})
    fine = ctx.raw("PUT", f"/structr/rest/SpkSaved/{node}", {"v": 5})
    tok = lambda r: [e.get("token") for e in (r[1].get("errors") or [])] if isinstance(r[1], dict) else r[1]
    return answer(neg[0] == 422 and "negative_on_save" in tok(neg) and "before_1" in tok(before) and fine[0] == 200,
                  "onSave sees $.retrieve('modifications') with before and after, and can refuse an edit",
                  f"v=-1: {neg[0]} {tok(neg)}; v=999: {before[0]} {tok(before)}; v=5: {fine[0]}")


def grant_setup(ctx):
    t = ctx.schema_type("SpkGranted")
    for u in USERS:
        ctx.user(u)
    group = ctx.one("Group", GROUP) or ctx.ok("POST", "/structr/rest/Group", {
        "name": GROUP, "members": [ctx.one("User", "spike-a")], "visibleToAuthenticatedUsers": True})["result"][0]
    ctx.resource("SpkGranted")
    ctx.resource("SpkGranted/_id")
    keys = ctx.schema_keys("SchemaGrant") or []
    fields = {k: True for k in ("allowRead", "allowWrite") if k in keys}
    try:
        ctx.ok("POST", "/structr/rest/SchemaGrant", {"schemaNode": t, "principal": group, **fields})
        note = f"created with {sorted(fields)}"
    except RuntimeError as exc:
        note = f"refused: {exc}"
    ctx.ok("PATCH", f"/structr/rest/SchemaNode/{t}", {"summary": f"SchemaGrant keys {keys}; {note}"})


def grant_verify(ctx):
    t = ctx.one("SchemaNode", "SpkGranted")
    note = ctx.node("SchemaNode", t).get("summary")
    n = ctx.create("SpkGranted", {"name": "spike granted"}, flags=False)
    seen_a, seen_b = count(ctx, "SpkGranted", as_user("spike-a")), count(ctx, "SpkGranted", as_user("spike-b"))
    write_a = ctx.raw("PUT", f"/structr/rest/SpkGranted/{n}", {"name": "renamed by a"}, user=as_user("spike-a"))[0]
    return answer(seen_a == 1 and seen_b == 0 and write_a == 200,
                  "a SchemaGrant gives a group read and write on every instance of a type, without per-node grants",
                  f"{note}; a member sees {seen_a} of 1, a non-member {seen_b}; the member's write: {write_a}")


def propagation_setup(ctx):
    folder, doc = ctx.schema_type("SpkFolder"), ctx.schema_type("SpkDoc")
    for u in USERS:
        ctx.user(u)
    try:
        ctx.schema_rel(folder, doc, "SPK_FOLDER_HAS_DOC", "1", "*", "folder", "docs", permissionPropagation="Out",
                       readPropagation="Add", writePropagation="Keep", deletePropagation="Keep",
                       accessControlPropagation="Keep")
        note = "declared with permissionPropagation=Out, readPropagation=Add"
    except RuntimeError as exc:
        note = f"refused: {exc}"
        ctx.schema_rel(folder, doc, "SPK_FOLDER_HAS_DOC", "1", "*", "folder", "docs")
    ctx.ok("PATCH", f"/structr/rest/SchemaNode/{folder}", {"summary": note})
    for sig in ("SpkFolder", "SpkDoc", "SpkDoc/_id"):
        ctx.resource(sig)
    ctx.function("spkGrant", """{
  const u = $.find('User', {name: $.args.user})[0];
  const n = $.find($.args.type, {id: $.args.id})[0];
  $.grant(u, n, $.args.perms);
  return 'granted';
}""")


def propagation_verify(ctx):
    note = ctx.node("SchemaNode", ctx.one("SchemaNode", "SpkFolder")).get("summary")
    doc = ctx.create("SpkDoc", {"name": "spike doc"}, flags=False)
    folder = ctx.create("SpkFolder", {"name": "spike folder", "docs": [doc]}, flags=False)
    before = count(ctx, "SpkDoc", as_user("spike-a"))
    ctx.call("spkGrant", {"user": "spike-a", "type": "SpkFolder", "id": folder, "perms": "read"})
    after_a, after_b = count(ctx, "SpkDoc", as_user("spike-a")), count(ctx, "SpkDoc", as_user("spike-b"))
    return answer(before == 0 and after_a == 1 and after_b == 0,
                  "read on a folder propagates to its docs along a relationship set to propagate",
                  f"{note}; the user sees the doc before the folder grant: {before}, after: {after_a}; "
                  f"a user without the grant: {after_b}")


def labels_setup(ctx):
    trait = ctx.schema_type("SpkTrait", isAbstract=True)
    typed, holder = ctx.schema_type("SpkTyped"), ctx.schema_type("SpkHolder")
    ctx.schema_rel(holder, trait, "SPK_HOLDS", "*", "1", "holders", "held")
    if not ctx.one("SpkTyped", "spike old typed"):
        ctx.create("SpkTyped", {"name": "spike old typed"})
    ctx.ok("PATCH", f"/structr/rest/SchemaNode/{typed}", {"inheritedTraits": ["SpkTrait"]})
    ctx.function("spkLabels", """{
  return $.cypher('MATCH (n) WHERE n.id = $id RETURN labels(n) AS labels', {id: $.args.id})
    .map((row) => String(row && row.labels !== undefined ? row.labels : row)).join(';');
}""")


def labels_verify(ctx):
    old = ctx.one("SpkTyped", "spike old typed")
    new = ctx.create("SpkTyped", {"name": "spike new typed"})
    holder = ctx.create("SpkHolder", {"name": "spike holder"})
    labels = lambda node_id: ctx.call("spkLabels", {"id": node_id})[1].get("result")
    old_before, new_labels = labels(old), labels(new)
    refused = ctx.raw("PUT", f"/structr/rest/SpkHolder/{holder}", {"held": old})
    control = ctx.raw("PUT", f"/structr/rest/SpkHolder/{holder}", {"held": new})
    run = ctx.raw("POST", "/structr/rest/maintenance/createLabels", {"type": "SpkTyped"})
    old_after = labels(old)
    retried = ctx.raw("PUT", f"/structr/rest/SpkHolder/{holder}", {"held": old})
    return answer(refused[0] >= 400 and control[0] == 200 and retried[0] == 200,
                  "createLabels adds the labels a type gained after its nodes were made",
                  f"old node's labels {old_before} (new node's {new_labels}); relating the old node: {refused[0]} "
                  f"{str(refused[1])[:120]}; a new one: {control[0]}; createLabels: {run[0]}; old node's labels after "
                  f"{old_after}; relating the old node again: {retried[0]}")


def bulk_setup(ctx):
    t = ctx.schema_type("SpkBulk")
    ctx.schema_prop(t, "name", "String", unique=True, indexed=True)
    ctx.schema_prop(t, "note", "String")


def bulk_verify(ctx):
    flags = {"visibleToAuthenticatedUsers": True}
    bad = ctx.raw("POST", "/structr/rest/SpkBulk", [{"name": "b1", **flags}, {"name": "b2", **flags}, {"name": "b1", **flags}])
    left = sorted(r["name"] for r in ctx.ok("GET", "/structr/rest/SpkBulk")["result"])
    good = ctx.raw("POST", "/structr/rest/SpkBulk", [{"name": "b3", **flags}, {"name": "b4", **flags}])
    ids = good[1].get("result") if isinstance(good[1], dict) else None
    patched = ctx.raw("PATCH", "/structr/rest/SpkBulk", [{"id": ids[0], "note": "bulk patched"}]) if ids else (None, None)
    note = (ctx.node("SpkBulk", ids[0]) or {}).get("note") if ids else None
    return answer(bad[0] == 422 and left == [] and good[0] == 201 and len(ids or []) == 2 and note == "bulk patched",
                  "an array POST is one transaction (all or none); a PATCH array updates many",
                  f"array with a duplicate: {bad[0]}, nodes left after it: {left}; a good array: {good[0]} "
                  f"({len(ids or [])} ids); PATCH array: {patched[0]}, note read back {note!r}")


def unknown_verify(ctx):
    status, out = ctx.raw("POST", "/structr/rest/SpkBulk", {"name": "u1", "notAProperty": 1,
                                                          "visibleToAuthenticatedUsers": True})
    stored = None
    if status == 201:
        stored = (ctx.node("SpkBulk", out["result"][0]) or {}).get("notAProperty", "(not a key)")
    return answer(status == 422, "with jsonrestservlet.unknowninput.validation.mode=reject an unknown key is refused",
                  f"POST with an unknown key: {status} {str(out)[:160] if status != 201 else ''}; stored: {stored!r}")


def changelog_setup(ctx):
    t = ctx.schema_type("SpkLogged")
    ctx.schema_prop(t, "note", "String")
    ctx.function("spkChangelog", "{ return $.changelog($.args.id, false); }")
    ctx.function("spkUserChangelog", "{ return $.userChangelog($.find('User', {name: $.args.user})[0], false); }")
    ctx.user("spike-a")


def changelog_verify(ctx):
    node = ctx.create("SpkLogged", {"name": "spike logged", "note": "one"})
    ctx.ok("PUT", f"/structr/rest/SpkLogged/{node}", {"note": "two"})
    ctx.ok("PUT", f"/structr/rest/SpkLogged/{node}", {"note": "three"})
    status, out = ctx.call("spkChangelog", {"id": node})
    entries = out.get("result") if isinstance(out, dict) else out
    changes = [e for e in (entries or []) if isinstance(e, dict) and e.get("verb") == "change" and e.get("key") == "note"]
    verbs = sorted({e.get("verb") for e in (entries or []) if isinstance(e, dict)})
    users = sorted({e.get("userName") for e in (entries or []) if isinstance(e, dict)})
    files = exec_in_structr("ls -la /var/lib/structr/changelog 2>&1 | head -5; find /var/lib/structr -maxdepth 2 -iname '*changelog*' | head")
    return answer(status == 200 and len(changes) >= 2,
                  "with application.changelog.enabled, changelog(node) lists creates and changes with old and new values",
                  f"call: {status}; verbs {verbs}; note changes {[(e.get('prev'), e.get('val')) for e in changes]}; "
                  f"users {users}; on disk: {files[:300]}")


def cron_setup(ctx):
    ctx.schema_type("SpkCronTick")
    ctx.function("spkCron", "{ $.create('SpkCronTick', {name: 'tick ' + new Date().toISOString(), visibleToAuthenticatedUsers: true}); }")


def cron_verify(ctx):
    first = count(ctx, "SpkCronTick")
    time.sleep(16)
    second = count(ctx, "SpkCronTick")
    grew = isinstance(first, int) and isinstance(second, int) and second > first
    return answer(grew, "CronService.tasks with a six-field cronExpression (every 5 s) runs the function",
                  f"ticks {first}, then {second} sixteen seconds later")


def polyglot_setup(ctx):
    ctx.function("spkPython", "{ return Polyglot.eval('python', '6 * 7'); }")


def polyglot_verify(ctx):
    timings = []
    out = None
    for _ in range(2):
        start = time.time()
        status, out = ctx.call("spkPython")
        timings.append((status, round(time.time() - start, 2)))
    value = out.get("result") if isinstance(out, dict) and "result" in out else out
    why = exec_in_structr("grep -h -A3 'spkPython' /var/lib/structr/logs/*.log 2>/dev/null | head -8")
    return answer(str(value).startswith("42"), "Polyglot.eval('python', ...) runs Python inside a JavaScript method",
                  f"(status, seconds) per call {timings}; value {str(value)[:200]}; the server log: {why[:600]}")


def params_setup(ctx):
    for name, verb in (("spkTypedPost", None), ("spkTypedGet", "GET")):
        extra = {"returnRawResult": True}
        if verb:
            extra["httpVerb"] = verb
        method = ctx.function(name, "{ return {count: $.args.count, kind: typeof $.args.count, "
                                    "extra: $.args.extra === undefined ? null : $.args.extra}; }", **extra)
        if not ctx.ok("GET", f"/structr/rest/SchemaMethodParameter?schemaMethod={method}")["result"]:
            ctx.ok("POST", "/structr/rest/SchemaMethodParameter",
                   {"schemaMethod": method, "name": "count", "parameterType": "Integer", "index": 0})


def params_verify(ctx):
    post = ctx.call("spkTypedPost", {"count": "7", "extra": "x"})
    get = ctx.call("spkTypedGet", method="GET", suffix="/5")
    wrong = ctx.call("spkTypedGet", {"count": 5})
    converted = isinstance(post[1], dict) and post[1].get("kind") == "number"
    return answer(converted and get[0] == 200 and wrong[0] == 405,
                  "declared parameters convert values; httpVerb GET takes path segments and refuses POST",
                  f"POST {{count:'7', extra:'x'}}: {post[0]} {post[1]}; GET /5: {get[0]} {get[1]}; POST to the GET "
                  f"method: {wrong[0]} {str(wrong[1])[:100]}")


def cache_setup(ctx):
    ctx.function("spkCache", "{ return $.cache('spk-cache-key', 300, () => String(Math.random())); }")


def cache_verify(ctx):
    one, two = ctx.call("spkCache"), ctx.call("spkCache")
    a = one[1].get("result") if isinstance(one[1], dict) else one[1]
    b = two[1].get("result") if isinstance(two[1], dict) else two[1]
    return answer(one[0] == 200 and a == b, "cache(key, seconds, fn) computes once and returns the same value",
                  f"first {one[0]} {a!r}, second {two[0]} {b!r}")


def doas_setup(ctx):
    ctx.user("spike-a")
    ctx.schema_type("SpkDoAsPrivate")
    ctx.function("spkDoAs", "{ const u = $.find('User', {name: 'spike-a'})[0]; "
                            "let asUser = null, me = null; "
                            "$.doAs(u, () => { asUser = $.find('SpkDoAsPrivate').length; me = $.me ? $.me.name : null; }); "
                            "return {asAdmin: $.find('SpkDoAsPrivate').length, asUser: asUser, me: me}; }")


def doas_verify(ctx):
    ctx.create("SpkDoAsPrivate", {"name": "spike private"}, flags=False)     # no flags, no owner: admins only
    status, out = ctx.call("spkDoAs")
    value = out.get("result") if isinstance(out, dict) else out
    ok = isinstance(value, dict) and value.get("asAdmin") == 1 and value.get("asUser") == 0
    return answer(ok, "doAs(user, fn) runs fn with that user's rights", f"{status} {value!r}")


def schedule_setup(ctx):
    ctx.schema_type("SpkScheduled")
    ctx.function("spkSchedule", "{ $.schedule(() => { $.create('SpkScheduled', {name: 'scheduled', "
                                "visibleToAuthenticatedUsers: true}); }, 'spike job'); return 'queued'; }")


def schedule_verify(ctx):
    status, out = ctx.call("spkSchedule")
    seen = 0
    for _ in range(10):
        time.sleep(1)
        seen = count(ctx, "SpkScheduled")
        if isinstance(seen, int) and seen:
            break
    return answer(status == 200 and seen == 1, "schedule(fn) runs fn outside the request, soon after",
                  f"call {status} {out.get('result') if isinstance(out, dict) else out}; nodes it made: {seen}")


def prefetch_setup(ctx):
    ctx.function("spkPrefetch", "{ $.prefetch('(:SpkParent)-[]->(:SpkChild)', ['SPK_HAS_CHILD']); return 'ok'; }")


def prefetch_verify(ctx):
    status, out = ctx.call("spkPrefetch")
    value = out.get("result") if isinstance(out, dict) else out
    return answer(status == 200 and value == "ok", "prefetch(pattern, keys) exists in scripts",
                  f"{status} {str(value)[:160]}")


def sync_verify(ctx):
    status, out = ctx.raw("POST", "/structr/rest/maintenance/sync",
                          {"mode": "export", "file": "/tmp/spike-sync.zip", "query": "MATCH (n:SpkBulk) RETURN n"})
    listing = exec_in_structr("ls -l /tmp/spike-sync.zip 2>&1; (unzip -l /tmp/spike-sync.zip 2>/dev/null || "
                              "jar tf /tmp/spike-sync.zip 2>/dev/null) | head -8")
    return answer(status == 200 and "spike-sync.zip" in listing and "No such file" not in listing,
                  "maintenance sync exports the subgraph a Cypher query selects into one ZIP",
                  f"{status} {str(out)[:120]}; in the container: {listing[:400]}")


def health_verify(ctx):
    ready = ctx.raw("GET", "/structr/health/ready", auth=False)[0]
    status, out = ctx.raw("GET", "/structr/health", auth=False)
    inside = exec_in_structr("(curl -s -o /dev/null -w '%{http_code}' 'http://localhost:8082/structr/histogram?top=3' "
                             "|| wget -qO- 'http://localhost:8082/structr/histogram?top=3' | head -c 300) 2>&1")
    return {"answer": "INFO", "documented": "readiness without credentials; health and histogram whitelisted",
            "found": f"/structr/health/ready {ready}; /structr/health from the host {status} "
                     f"{list(out)[:8] if isinstance(out, dict) else str(out)[:80]}; histogram from inside the container: "
                     f"{inside[:200]}"}


def eam_verify(ctx):
    status, out = ctx.raw("GET", "/structr/js/frontend/frontend.js", auth=False)
    keys = [k for k in (ctx.schema_keys("DOMElement") or []) if any(w in k.lower() for w in ("action", "event", "mapping", "reload"))]
    return answer(status == 200 and bool(keys), "Event Action Mapping: the frontend library and element settings exist",
                  f"/structr/js/frontend/frontend.js {status} ({len(out) if isinstance(out, str) else '?'} bytes); "
                  f"DOMElement keys {keys}")


def nothing(ctx):
    return None


SPIKES = [
    ("cascade", "Does a relationship's cascadingDeleteFlag delete dependents?", cascade_setup, cascade_verify),
    ("cascade_more", "Does a flag set on a populated relationship cascade, through chains and shared targets?",
     cascade_more_setup, cascade_more_verify),
    ("visibility", "Does a type's defaultVisibleToAuth make new nodes visible?", visibility_setup, visibility_verify),
    ("compound", "Does compound uniqueness refuse a repeated pair?", compound_setup, compound_verify),
    ("format", "Do numeric intervals and string patterns in `format` validate?", format_setup, format_verify),
    ("onsave", "Does onSave see the modifications and refuse an edit?", onsave_setup, onsave_verify),
    ("grant", "Does a SchemaGrant share a whole type with a group?", grant_setup, grant_verify),
    ("propagation", "Does read access propagate along a relationship?", propagation_setup, propagation_verify),
    ("labels", "Does createLabels fix the labels of nodes older than their trait?", labels_setup, labels_verify),
    ("bulk", "Is an array POST one transaction; does a PATCH array update many?", bulk_setup, bulk_verify),
    ("unknown", "Does validation mode `reject` refuse unknown input keys?", nothing, unknown_verify),
    ("changelog", "Does the changelog record changes, and where?", changelog_setup, changelog_verify),
    ("cron", "Does a scheduled task configured by environment run?", cron_setup, cron_verify),
    ("polyglot", "Can a JavaScript method run Python?", polyglot_setup, polyglot_verify),
    ("params", "Do declared parameters and httpVerb GET work?", params_setup, params_verify),
    ("cache", "Does cache() keep a value?", cache_setup, cache_verify),
    ("doas", "Does doAs() run code as another user?", doas_setup, doas_verify),
    ("schedule", "Does schedule() run code after the request?", schedule_setup, schedule_verify),
    ("prefetch", "Does prefetch() exist?", prefetch_setup, prefetch_verify),
    ("sync", "Does maintenance sync export a query's subgraph?", nothing, sync_verify),
    ("health", "What do the health and histogram endpoints answer?", nothing, health_verify),
    ("eam", "Is Event Action Mapping there?", nothing, eam_verify),
]


def cleanup(ctx):
    """Delete everything the spikes made (a throwaway stack is destroyed anyway)."""
    for node in ctx.ok("GET", "/structr/rest/SchemaNode")["result"]:
        if node["name"].startswith("Spk"):
            for row in ctx.ok("GET", f"/structr/rest/{node['name']}")["result"]:
                ctx.raw("DELETE", f"/structr/rest/{node['name']}/{row['id']}")
    for method in ctx.ok("GET", "/structr/rest/SchemaMethod")["result"]:
        if (method.get("name") or "").startswith("spk"):
            ctx.raw("DELETE", f"/structr/rest/SchemaMethod/{method['id']}")
    for rel in ctx.ok("GET", "/structr/rest/SchemaRelationshipNode")["result"]:
        if (rel.get("relationshipType") or "").startswith("SPK_"):
            ctx.raw("DELETE", f"/structr/rest/SchemaRelationshipNode/{rel['id']}")
    for node in ctx.ok("GET", "/structr/rest/SchemaNode")["result"]:
        if node["name"].startswith("Spk"):
            ctx.raw("DELETE", f"/structr/rest/SchemaNode/{node['id']}")
    for type_name, names in (("User", USERS), ("Group", (GROUP,))):
        for name in names:
            node_id = ctx.one(type_name, name)
            if node_id:
                ctx.raw("DELETE", f"/structr/rest/{type_name}/{node_id}")
    for grant in ctx.ok("GET", "/structr/rest/ResourceAccess")["result"]:
        if (grant.get("signature") or "").startswith("Spk") or grant.get("signature") in ("spkGrant",):
            ctx.raw("DELETE", f"/structr/rest/ResourceAccess/{grant['id']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("phase", choices=["setup", "verify", "cleanup"])
    parser.add_argument("--only", help="comma-separated spike names")
    parser.add_argument("--json", help="write the verify results here")
    args = parser.parse_args(argv)
    url = os.environ.get("STRUCTR_URL", "http://localhost:8083")
    if (urlparse(url).port or 80) in REFUSED_PORTS:
        print(f"refused: {url} is the development or the owner's instance; the spikes make schema of their own "
              f"and belong on a throwaway stack (tools/spikes/run_spikes.sh)")
        return 2
    ctx = Ctx(connect())
    chosen = [s for s in SPIKES if not args.only or s[0] in args.only.split(",")]
    if args.phase == "cleanup":
        cleanup(ctx)
        print("cleaned up")
        return 0
    results = []
    for name, question, setup, verify in chosen:
        try:
            if args.phase == "setup":
                setup(ctx)
                print(f"[set up] {name}")
                continue
            result = verify(ctx)
        except Exception as exc:                      # a spike that breaks says so, and the rest still run
            result = {"answer": "ERROR", "documented": "", "found": f"{type(exc).__name__}: {str(exc)[:400]}"}
            if args.phase == "setup":
                print(f"[ERROR in setup] {name}: {result['found']}")
                continue
        result.update(spike=name, question=question)
        results.append(result)
        print(f"[{result['answer']}] {name}: {question}\n    documented: {result['documented']}\n    found: {result['found']}")
    if args.phase == "verify":
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(root, "docker-compose.yml")) as handle:
            image = next((line.split("image:")[1].strip() for line in handle if "structr/structr:" in line), None)
        if args.json:
            with open(args.json, "w") as handle:
                json.dump({"structr": image, "run": time.strftime("%Y-%m-%d %H:%M"), "results": results},
                          handle, indent=1, ensure_ascii=False)
                handle.write("\n")
        print(f"\n{sum(r['answer'] == 'OK' for r in results)} OK, {sum(r['answer'] == 'DIFFERENT' for r in results)} "
              f"different, {sum(r['answer'] == 'INFO' for r in results)} info, {sum(r['answer'] == 'ERROR' for r in results)} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
