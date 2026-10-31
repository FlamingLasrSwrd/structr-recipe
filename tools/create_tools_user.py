"""Make the Structr account the tools and scripts log in as, or bring it back into line.

    python3 tools/create_tools_user.py                                   # the development stack
    STRUCTR_URL=http://localhost:8085 python3 tools/create_tools_user.py # the owner's instance, once

Everything in `scripts/` and `tools/` logs in as this account (mealplanner/connection.TOOLS_USER),
an admin `User`, not as the superuser. On Structr 7.1, three wrong superuser passwords within 15
minutes block the superuser everywhere for that time, the admin interface included, and with its
second factor turned on every header request would need a fresh code (docs/structr-reference.md
§2.3). So the superuser is kept for the admin interface and for this tool alone.

The account is an admin, so Structr's access control lets it do all the superuser did for the
tools: change the schema, read and write every node. It is made with skipSecurityRelationships, so
what it creates has no owner and no grants, exactly as when the superuser made it: otherwise every
node would gain an OWNS and a SECURITY relationship, and a household member's grants
(docs/methods.md) would sit beside an owner nobody meant. It is invisible to other users, like any
account (tools/create_login.py).

Run it again at any time: it creates the account if it is missing, and otherwise sets its flags and
its password from .env again, and clears its failed logins, which is how a tools account locked by
a wrong password is opened again. tools/rebuild.sh runs it before the first script. The password is
STRUCTR_TOOLS_PASSWORD (cloud/bootstrap.sh --env-only adds one to .env); this tool also needs
STRUCTR_SUPERUSER_PASSWORD, and is safe on any instance, the owner's included: it changes one
account and no data.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import DEFAULT_URL, SUPERUSER, TOOLS_USER, connect
from structr_client import StructrClient

ACCOUNT = {"isAdmin": True, "skipSecurityRelationships": True,
           "visibleToAuthenticatedUsers": False, "visibleToPublicUsers": False}


def ensure_tools_user(superuser, password: str) -> str:
    """Create the tools account, or set its flags and password again. Returns what was done."""
    users = superuser.get("/structr/rest/User", params={"name": TOOLS_USER})["result"]
    if len(users) > 1:
        raise RuntimeError(f"{len(users)} accounts are named {TOOLS_USER!r}; remove the extra ones by hand")
    if not users:
        superuser.post("/structr/rest/User", {"name": TOOLS_USER, "password": password, **ACCOUNT})
        return "created"
    superuser.patch(f"/structr/rest/User/{users[0]['id']}", {"password": password, "passwordAttempts": 0, **ACCOUNT})
    return "brought into line"


def main() -> int:
    url = os.environ.get("STRUCTR_URL", DEFAULT_URL)
    password = os.environ.get("STRUCTR_TOOLS_PASSWORD", "")
    if len(password) < 8:
        print("problem: STRUCTR_TOOLS_PASSWORD is missing or shorter than 8 characters "
              "(cloud/bootstrap.sh --env-only adds one to .env)")
        return 1
    superuser = StructrClient(url, SUPERUSER, os.environ["STRUCTR_SUPERUSER_PASSWORD"])
    superuser.wait_until_ready()
    done = ensure_tools_user(superuser, password)
    connect(owner_data_ok=True).wait_until_ready()      # the account logs in with what .env says
    print(f"{TOOLS_USER} at {url}: {done}; the tools log in as it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
