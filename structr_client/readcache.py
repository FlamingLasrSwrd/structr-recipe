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

Two more things for a computation that reads a lot: `prefetch` reads whole
listings up front, one paged request per 500 rows in place of one request per
node (a week's extraction read 18,763 NutrientProfiles one at a time, 420 s
of 1,119 in a profiled run); and `memo` keeps a value derived from the reads,
for one that is asked for again and again (the same extraction scanned a
food's hundred-odd profiles once per nutrient, 1.96 million cached reads,
each copied on the way out).
"""

from __future__ import annotations

import copy


class ReadCache:
    def __init__(self, client):
        self._client = client
        self._nodes: dict[tuple[str, str], dict] = {}
        self._listings: dict[str, list[dict]] = {}
        self._queries: dict[tuple, dict] = {}
        self._memo: dict = {}

    def get_all(self, type_name: str, node_id: str | None = None) -> dict:
        if node_id is not None:
            key = (type_name, node_id)
            if key not in self._nodes:
                self._nodes[key] = self._client.get_all(type_name, node_id)["result"]
            return {"result": copy.deepcopy(self._nodes[key])}
        self.prefetch(type_name)
        return {"result": copy.deepcopy(self._listings[type_name])}

    def prefetch(self, *type_names: str) -> None:
        """Read each type's whole listing now, so that later lookups by id need no request."""
        for type_name in type_names:
            if type_name not in self._listings:
                rows = self._client.get_all(type_name)["result"]
                self._listings[type_name] = rows
                for row in rows:
                    self._nodes[(type_name, row["id"])] = row

    def memo(self, key, compute):
        """compute(), once for this cache. The value is shared, not copied: callers must not change it."""
        if key not in self._memo:
            self._memo[key] = compute()
        return self._memo[key]

    def get(self, path: str, params: dict | None = None) -> dict:
        key = (path, tuple(sorted((params or {}).items())))
        if key not in self._queries:
            self._queries[key] = self._client.get(path, params=params)
        return copy.deepcopy(self._queries[key])


def memoized(client, key, compute):
    """compute() once per ReadCache when the client is one (ReadCache.memo); every time otherwise."""
    return client.memo(key, compute) if isinstance(client, ReadCache) else compute()
