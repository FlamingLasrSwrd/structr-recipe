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


class StructrClient:
    def __init__(self, base_url: str, username: str, password: str):
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
        return self._request("POST", path, json=json)

    def patch(self, path: str, json: dict):
        return self._request("PATCH", path, json=json)

    def delete(self, path: str):
        return self._request("DELETE", path)

    def wait_until_ready(self, timeout_s: float = 60.0, interval_s: float = 2.0) -> None:
        """Poll the schema endpoint until it responds, or raise on timeout."""
        deadline = time.monotonic() + timeout_s
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self.get("/structr/rest/SchemaNode")
                return
            except (requests.exceptions.ConnectionError, StructrError) as exc:
                last_err = exc
                time.sleep(interval_s)
        raise TimeoutError(f"Structr not ready after {timeout_s}s") from last_err

    # -- idempotent schema setup ---------------------------------------
    # Structr's schema endpoints are not idempotent by default: POSTing
    # the same SchemaNode/SchemaProperty/SchemaRelationshipNode twice
    # duplicates or errors. These wrappers check-then-create so a setup
    # script is safe to re-run after adding one new type.

    def ensure_type(
        self,
        name: str,
        is_abstract: bool = False,
        inherited_traits: list[str] | None = None,
    ) -> tuple[str, bool]:
        """Return (schema_node_id, created)."""
        existing = self.get("/structr/rest/SchemaNode", params={"name": name})
        if existing and existing.get("result"):
            node_id = existing["result"][0]["id"]
            # Do NOT reconcile inheritedTraits here. A SchemaNode's label
            # set in Neo4j is fixed at instance-creation time (cheatsheet
            # hard rule #2 in CLAUDE.md): silently PATCHing inheritedTraits
            # on a type that already has instances orphans every one of
            # them from polymorphic-target lookups, with no error at write
            # time. Schema drift for an existing type must fail loudly and
            # require a deliberate migration (direct Cypher `SET n:<Label>`
            # plus a conscious decision), never an automatic reconcile.
            if inherited_traits is not None:
                current = existing["result"][0].get("inheritedTraits") or []
                if set(current) != set(inherited_traits):
                    raise StructrError(
                        "ensure_type", f"SchemaNode/{node_id}", 0,
                        f"{name!r} already exists with inheritedTraits={current!r}, "
                        f"but the code now declares {inherited_traits!r}. Refusing to "
                        f"patch a live type's trait set automatically -- this can "
                        f"orphan existing instances. If this drift is intentional, "
                        f"resolve it deliberately (see CLAUDE.md hard rule #2).",
                    )
            return node_id, False

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
            return existing["result"][0]["id"], False

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

        A literal comma in unique_value silently breaks Structr's
        exact-match query (0 results even when a match exists) --
        confirmed empirically, see structr-cheatsheet.md Sec 4. That
        makes this method create a duplicate instead of finding the
        existing one, with no error. Guarded here since it bit real
        scripts twice before this check existed.
        """
        if isinstance(unique_value, str) and "," in unique_value:
            raise ValueError(
                f"upsert({type_name!r}, {unique_prop!r}, ...): unique_value contains a "
                f"comma, which breaks Structr's exact-match query and will silently "
                f"create a duplicate on re-run: {unique_value!r}. Rephrase without a comma."
            )
        existing = self.get(f"/structr/rest/{type_name}", params={unique_prop: unique_value})
        payload = {k: v for k, v in fields.items() if v is not None}
        payload[unique_prop] = unique_value
        payload["visibleToAuthenticatedUsers"] = visible_to_authenticated_users
        payload["visibleToPublicUsers"] = visible_to_public_users

        if existing and existing.get("result"):
            node_id = existing["result"][0]["id"]
            self.patch(f"/structr/rest/{type_name}/{node_id}", payload)
            return node_id

        created = self.post(f"/structr/rest/{type_name}", payload)
        return created["result"][0]

    def get_all(self, type_name: str, node_id: str | None = None) -> dict:
        """GET with the /all view suffix - the default view omits custom
        properties and relationship collections.
        """
        path = f"/structr/rest/{type_name}/{node_id}/all" if node_id else f"/structr/rest/{type_name}/all"
        return self.get(path)
