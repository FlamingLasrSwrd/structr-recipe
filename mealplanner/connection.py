"""Where the scripts find Structr, in one place.

Every script used to repeat the same three constants and the same client
construction (45 copies), so changing how a connection is made meant editing
all of them. The URL comes from STRUCTR_URL (default: the local compose stack)
and the password from STRUCTR_SUPERUSER_PASSWORD, which has no default on
purpose: a script run without it should stop, not try a guess.
"""

from __future__ import annotations

import os

from structr_client import StructrClient

DEFAULT_URL = "http://localhost:8083"
SUPERUSER = "superadmin"


def connect() -> StructrClient:
    """A client for the configured instance. Does not wait for it to be ready;
    call wait_until_ready() when the script needs that."""
    return StructrClient(os.environ.get("STRUCTR_URL", DEFAULT_URL), SUPERUSER, os.environ["STRUCTR_SUPERUSER_PASSWORD"])
