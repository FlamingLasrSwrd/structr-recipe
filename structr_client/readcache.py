"""A read-only, memoizing view over a client, for one computation.

The selector and the reservation code read the same few hundred nodes over and
over (a DomainType is fetched every time a type tree is walked; every candidate
recipe rescans all the stock). One selector run over four recipes made 260
requests, only 112 of them different. Wrapping the client in a ReadCache for
the length of a computation fetches each node, listing and query once.

It exposes only get_all() and get(), the two calls the reading code uses, and
deliberately none of post/patch/delete/upsert: writing through a cache would
leave it stale. Make a new ReadCache per computation rather than keeping one
around, since nothing invalidates it; a computation is a point-in-time view.
Results are copied on the way out so a caller cannot alter what later callers
see. A listing (`get_all(type)`) also answers later lookups by id, since Structr
returns the same row either way (checked across 187 live objects).
"""

from __future__ import annotations

import copy


class ReadCache:
    def __init__(self, client):
        self._client = client
        self._nodes: dict[tuple[str, str], dict] = {}
        self._listings: dict[str, list[dict]] = {}
        self._queries: dict[tuple, dict] = {}

    def get_all(self, type_name: str, node_id: str | None = None) -> dict:
        if node_id is not None:
            key = (type_name, node_id)
            if key not in self._nodes:
                self._nodes[key] = self._client.get_all(type_name, node_id)["result"]
            return {"result": copy.deepcopy(self._nodes[key])}
        if type_name not in self._listings:
            rows = self._client.get_all(type_name)["result"]
            self._listings[type_name] = rows
            for row in rows:
                self._nodes[(type_name, row["id"])] = row
        return {"result": copy.deepcopy(self._listings[type_name])}

    def get(self, path: str, params: dict | None = None) -> dict:
        key = (path, tuple(sorted((params or {}).items())))
        if key not in self._queries:
            self._queries[key] = self._client.get(path, params=params)
        return copy.deepcopy(self._queries[key])
