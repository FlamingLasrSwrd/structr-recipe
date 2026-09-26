"""Generic Structr REST client.

Project-agnostic: knows how to talk to a Structr 6.x instance (auth,
idempotent schema setup, CRUD, upsert). Carries no knowledge of any
particular project's types or field mappings — see structr-cheatsheet.md
in the Obsidian vault for the empirical findings this implements.
"""

from __future__ import annotations

import time
from typing import Any

import requests


class StructrError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, body: Any):
        self.method = method
        self.url = url
        self.status = status
        self.body = body
        super().__init__(f"{method} {url} -> {status}: {body}")


class SchemaDriftError(RuntimeError):
    """A schema object already exists but differs from what the code
    declares. Raised instead of reconciling: a SchemaNode/SchemaProperty/
    SchemaRelationshipNode change on a populated schema can orphan or
    silently reinterpret existing data (CLAUDE.md hard rules #1-#3), and
    a setup script reporting success while the live schema disagrees
    with the code is worse than one that stops.

    `differences` maps each attribute to (live value, declared value)."""

    def __init__(self, kind: str, name: str, differences: dict[str, tuple[Any, Any]]):
        self.kind = kind
        self.name = name
        self.differences = differences
        detail = "; ".join(f"{attr}: live={live!r} declared={declared!r}" for attr, (live, declared) in differences.items())
        super().__init__(
            f"{kind} {name!r} already exists but differs from the declared schema ({detail}). "
            f"Refusing to change a live schema object automatically -- resolve it deliberately "
            f"(a migration, or correct the declaration if the live value is the intended one)."
        )


def _drift(declared: dict[str, Any], live: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """{attribute: (live, declared)} for every declared attribute whose
    live value differs."""
    return {k: (live.get(k), v) for k, v in declared.items() if live.get(k) != v}


# Characters that change what an exact-match REST query means. A comma
# silently returns 0 results even when a match exists (confirmed empirically,
# structr-cheatsheet.md Sec 4); a semicolon is Structr's documented OR
# separator in a search value, so "A;B" would match A or B, not the literal
# "A;B" (documented, not separately reproduced here).
UNSAFE_EXACT_MATCH_CHARS = (",", ";")


def validate_exact_match_value(where: str, value: Any) -> None:
    """Refuse a string that cannot be reliably found again by an exact-match
    query. A node created with one can never be looked up by that name, so
    a re-run creates a duplicate instead of finding it, with no error.

    Applied wherever a value may later be used as a query key: POST and PATCH
    (`name`) and upsert (its key). One function, not a growing list of checks
    in unrelated methods: the comma guard once covered only upsert(), and a
    Role and three Measurements were created with commas through direct POSTs,
    and a PATCH could rename a node into the same trap."""
    if isinstance(value, str):
        bad = [c for c in UNSAFE_EXACT_MATCH_CHARS if c in value]
        if bad:
            raise ValueError(
                f"{where}: {value!r} contains {' and '.join(repr(c) for c in bad)}, which changes or breaks "
                f"Structr's exact-match query, so this node could never be found by name again and a "
                f"re-run would silently create a duplicate. Rephrase without it."
            )


class DuplicateMatchError(RuntimeError):
    """An exact-match query for what should be a unique value returned
    several nodes. Treated as a data-integrity incident, not resolved by
    picking one: patching an arbitrary "first" match would quietly corrupt
    whichever node happened to come back first."""

    def __init__(self, type_name: str, prop: str, value: Any, ids: list[str]):
        self.type_name, self.prop, self.value, self.ids = type_name, prop, value, ids
        super().__init__(
            f"{len(ids)} {type_name} nodes have {prop}={value!r} (ids: {', '.join(ids)}). "
            f"Refusing to guess which one is meant; find out how the duplicate arose and remove it."
        )


class StructrClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: tuple[float, float] = (5.0, 120.0)):
        """timeout is (connect, read) seconds for EVERY request. Without one, a
        single hung connection blocks forever and wait_until_ready's own
        deadline is never reached. The read side is generous because a schema
        change recompiles and can legitimately take many seconds."""
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-User": username,
                "X-Password": password,
                "Content-Type": "application/json",
            }
        )

    # -- low-level HTTP -----------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"

    def _request(self, method: str, path: str, **kwargs) -> dict | list | None:
        url = self._url(path)
        kwargs.setdefault("timeout", self.timeout)
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise StructrError(method, url, resp.status_code, body)
        if not resp.content:
            return None
        return resp.json()

    def get(self, path: str, params: dict | None = None):
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict):
        if isinstance(json, dict):
            validate_exact_match_value(f"POST {path}", json.get("name"))
        return self._request("POST", path, json=json)

    def patch(self, path: str, json: dict):
        if isinstance(json, dict):
            validate_exact_match_value(f"PATCH {path}", json.get("name"))
        return self._request("PATCH", path, json=json)

    def delete(self, path: str):
        return self._request("DELETE", path)

    def wait_until_ready(self, timeout_s: float = 60.0, interval_s: float = 2.0) -> None:
        """Poll the schema endpoint until it answers.

        Retries what a starting server produces: refused/reset connections,
        timeouts, and 5xx. Fails IMMEDIATELY on any other HTTP error (401,
        403, 404, ...): those are configuration mistakes (wrong password,
        wrong URL), not "not ready yet", and retrying them made a bad
        password look like a slow start for the whole timeout."""
        deadline = time.monotonic() + timeout_s
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.get("/structr/rest/SchemaNode")
                return
            except StructrError as exc:
                if exc.status < 500:
                    raise
                last_err = exc
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_err = exc
            time.sleep(interval_s)
        raise TimeoutError(f"Structr not ready after {timeout_s}s") from last_err

    # -- idempotent schema setup ---------------------------------------
    # Structr's schema endpoints are not idempotent by default: POSTing
    # the same SchemaNode/SchemaProperty/SchemaRelationshipNode twice
    # duplicates or errors. These wrappers check-then-create so a setup
    # script is safe to re-run after adding one new type. They also
    # COMPARE an existing object against the declaration and raise
    # SchemaDriftError on any difference, never patching it: "already
    # exists" is not "matches", and a schema change on a populated type
    # must be a deliberate act (scripts/23a_schema_drift_test.py).

    def ensure_type(
        self,
        name: str,
        is_abstract: bool = False,
        inherited_traits: list[str] | None = None,
    ) -> tuple[str, bool]:
        """Return (schema_node_id, created)."""
        existing = self.get("/structr/rest/SchemaNode", params={"name": name})
        if existing and existing.get("result"):
            live = existing["result"][0]
            # Never reconcile a live type. A SchemaNode's label set in
            # Neo4j is fixed at instance-creation time (CLAUDE.md hard
            # rule #2): silently PATCHing inheritedTraits on a type that
            # already has instances orphans every one of them from
            # polymorphic-target lookups, with no error at write time.
            differences = {}
            if inherited_traits is not None:
                live_traits = set(live.get("inheritedTraits") or [])
                if live_traits != set(inherited_traits):
                    differences["inheritedTraits"] = (sorted(live_traits), sorted(inherited_traits))
            if bool(live.get("isAbstract")) != is_abstract:
                differences["isAbstract"] = (bool(live.get("isAbstract")), is_abstract)
            if differences:
                raise SchemaDriftError("SchemaNode", name, differences)
            return live["id"], False

        payload: dict[str, Any] = {"name": name, "isAbstract": is_abstract}
        if inherited_traits:
            payload["inheritedTraits"] = inherited_traits
        created = self.post("/structr/rest/SchemaNode", payload)
        return created["result"][0], True

    def ensure_property(
        self,
        schema_node_id: str,
        name: str,
        property_type: str,
        *,
        unique: bool = False,
        indexed: bool = False,
        not_null: bool = False,
        format: str | None = None,
    ) -> tuple[str, bool]:
        existing = self.get(
            "/structr/rest/SchemaProperty",
            params={"schemaNode": schema_node_id, "name": name},
        )
        if existing and existing.get("result"):
            live = existing["result"][0]
            differences = _drift(
                {"propertyType": property_type, "unique": unique, "indexed": indexed,
                 "notNull": not_null, "format": format},
                live,
            )
            if differences:
                raise SchemaDriftError(f"SchemaProperty on {schema_node_id}", name, differences)
            return live["id"], False

        payload: dict[str, Any] = {
            "schemaNode": schema_node_id,
            "name": name,
            "propertyType": property_type,
            "unique": unique,
            "indexed": indexed,
            "notNull": not_null,
        }
        if format is not None:
            payload["format"] = format
        created = self.post("/structr/rest/SchemaProperty", payload)
        return created["result"][0], True

    def ensure_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        *,
        source_multiplicity: str,
        target_multiplicity: str,
        source_json_name: str,
        target_json_name: str,
    ) -> tuple[str, bool]:
        """Create a SchemaRelationshipNode if one with this exact
        relationshipType/source/target doesn't already exist.

        Reminder (cheatsheet-verified): targetJsonName becomes the
        property on the SOURCE type; sourceJsonName becomes the
        property on the TARGET type. Named parameters here match
        Structr's own (inverted) field names on purpose, not the
        intuitive reading, so callers don't have to re-derive this.
        """
        existing = self.get(
            "/structr/rest/SchemaRelationshipNode",
            params={"relationshipType": relationship_type},
        )
        if existing and existing.get("result"):
            for rel in existing["result"]:
                src = rel.get("sourceId") or (rel.get("sourceNode") or {}).get("id")
                tgt = rel.get("targetId") or (rel.get("targetNode") or {}).get("id")
                if src == source_id and tgt == target_id:
                    differences = _drift(
                        {"sourceMultiplicity": source_multiplicity, "targetMultiplicity": target_multiplicity,
                         "sourceJsonName": source_json_name, "targetJsonName": target_json_name},
                        rel,
                    )
                    if differences:
                        raise SchemaDriftError("SchemaRelationshipNode", f"{relationship_type} {source_id}->{target_id}", differences)
                    return rel["id"], False

        payload = {
            "sourceId": source_id,
            "targetId": target_id,
            "relationshipType": relationship_type,
            "sourceMultiplicity": source_multiplicity,
            "targetMultiplicity": target_multiplicity,
            "sourceJsonName": source_json_name,
            "targetJsonName": target_json_name,
        }
        created = self.post("/structr/rest/SchemaRelationshipNode", payload)
        return created["result"][0], True

    def ensure_method(
        self,
        schema_node_id: str,
        name: str,
        source: str,
        *,
        return_raw_result: bool = True,
        is_static: bool = False,
    ) -> tuple[str, bool]:
        """Create or update a SchemaMethod by (schemaNode, name).

        Gotchas this bakes in (see structr-cheatsheet.md Sec 3a):
        - `source` is plain StructrScript, no ${...} wrapper.
        - Comparisons/predicates need function form (gt/equal), not
          infix operators -- a syntax error here is a SILENT no-op via
          REST (200, empty result), only visible in the container log.
          Callers should tail the log after calling this.
        - returnRawResult=True unwraps the response to the bare value
          instead of the usual {"result": [...]} envelope.
        """
        existing = self.get(
            "/structr/rest/SchemaMethod",
            params={"schemaNode": schema_node_id, "name": name},
        )
        payload = {
            "schemaNode": schema_node_id,
            "name": name,
            "source": source,
            "returnRawResult": return_raw_result,
            "isStatic": is_static,
        }
        if existing and existing.get("result"):
            method_id = existing["result"][0]["id"]
            self.patch(f"/structr/rest/SchemaMethod/{method_id}", payload)
            return method_id, False
        created = self.post("/structr/rest/SchemaMethod", payload)
        return created["result"][0], True

    def call_method(self, type_name: str, node_id: str, method_name: str, body: dict | None = None):
        return self.post(f"/structr/rest/{type_name}/{node_id}/{method_name}", body or {})

    # -- data CRUD -------------------------------------------------------

    def upsert(
        self,
        type_name: str,
        unique_prop: str,
        unique_value: Any,
        fields: dict[str, Any],
        *,
        visible_to_authenticated_users: bool = True,
        visible_to_public_users: bool = False,
    ) -> str:
        """Find-by-unique-property, then create or patch. Always sets
        visibility explicitly - Structr's default is owner-only and
        fails silently otherwise.

        0 matches: create. 1: patch it. More than 1: DuplicateMatchError.
        This used to patch whichever came back first, which after any earlier
        duplicate would quietly corrupt an arbitrary node.

        unique_value must be safe to find again by exact match
        (validate_exact_match_value): a comma or semicolon in it would make
        this method create a duplicate instead of finding the existing node.
        """
        validate_exact_match_value(f"upsert({type_name!r}, {unique_prop!r}, ...)", unique_value)
        existing = self.get(f"/structr/rest/{type_name}", params={unique_prop: unique_value})
        matches = (existing or {}).get("result") or []
        if len(matches) > 1:
            raise DuplicateMatchError(type_name, unique_prop, unique_value, [m["id"] for m in matches])
        payload = {k: v for k, v in fields.items() if v is not None}
        payload[unique_prop] = unique_value
        payload["visibleToAuthenticatedUsers"] = visible_to_authenticated_users
        payload["visibleToPublicUsers"] = visible_to_public_users

        if matches:
            node_id = matches[0]["id"]
            self.patch(f"/structr/rest/{type_name}/{node_id}", payload)
            return node_id

        created = self.post(f"/structr/rest/{type_name}", payload)
        return created["result"][0]

    def get_all(self, type_name: str, node_id: str | None = None, page_size: int = 500) -> dict:
        """GET with the /all view suffix - the default view omits custom
        properties and relationship collections.

        A whole collection is read page by page until every row is in. A bare
        collection GET returns only Structr's default page and says nothing
        about the rest, so on a type with more rows than that (a year of
        Measurements) it returned an incomplete list with no error. The result
        is the first page's response with `result` holding every row.
        """
        if node_id:
            return self.get(f"/structr/rest/{type_name}/{node_id}/all")
        path = f"/structr/rest/{type_name}/all"
        first = self.get(path, params={"_page": 1, "_pageSize": page_size})
        rows = list(first["result"])
        for page in range(2, int(first.get("page_count") or 1) + 1):
            rows.extend(self.get(path, params={"_page": page, "_pageSize": page_size})["result"])
        first["result"] = rows
        return first
