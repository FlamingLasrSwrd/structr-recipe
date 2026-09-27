"""Where the scripts find Structr, in one place.

Every script used to repeat the same three constants and the same client
construction (45 copies), so changing how a connection is made meant editing
all of them. The URL comes from STRUCTR_URL (default: the local compose stack)
and the password from STRUCTR_SUPERUSER_PASSWORD, which has no default on
purpose: a script run without it should stop, not try a guess.

It is also the one guard between the demo scripts and the owner's data. An
instance holding the owner's real data carries a marker (a Concept named
OWNER_MARKER, written by tools/make_owner_instance.py). The numbered scripts are
demos and tests: 15a deletes every recipe, cook and meal plan, and
tools/rebuild.sh runs them all against whatever STRUCTR_URL names. So connect()
refuses a marked instance unless the caller says it is a tool meant for owner
data (owner_data_ok=True).
"""

from __future__ import annotations

import os

from structr_client import StructrClient
from structr_client.client import StructrError

DEFAULT_URL = "http://localhost:8083"
SUPERUSER = "superadmin"
OWNER_MARKER = "INSTANCE -- owner data"


class OwnerInstanceError(RuntimeError):
    """A demo or test script pointed at the instance holding the owner's data."""


def is_owner_instance(client) -> bool:
    """Whether this instance carries the owner-data marker. An instance built
    only up to before the Concept type exists (scripts 00 and 01) has none."""
    try:
        return bool(client.get("/structr/rest/Concept", params={"name": OWNER_MARKER})["result"])
    except StructrError as exc:
        if exc.status == 404:
            return False
        raise


def connect(*, owner_data_ok: bool = False) -> StructrClient:
    """A client for the configured instance. Unless owner_data_ok, it waits for
    the instance and refuses one that holds the owner's data; otherwise it does
    not wait, and the caller calls wait_until_ready() when it needs to."""
    url = os.environ.get("STRUCTR_URL", DEFAULT_URL)
    client = StructrClient(url, SUPERUSER, os.environ["STRUCTR_SUPERUSER_PASSWORD"])
    if not owner_data_ok:
        client.wait_until_ready()
        if is_owner_instance(client):
            raise OwnerInstanceError(
                f"{url} holds the owner's data, and this is a demo or test: it could delete or overwrite that "
                f"data. Point STRUCTR_URL at a development or throwaway instance.")
    return client
