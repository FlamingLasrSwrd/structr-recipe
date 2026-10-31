"""Remove Structr's initial `admin` account while it still has the password `admin`.

Structr 7.1 gives a fresh database a user `admin` with the password `admin` and full admin rights
(`initialuser.create`; seen on a development stack before any script ran, 2026-10-31,
docs/structr-cheatsheet.md section 2). Nothing in this project uses it, and anyone who reaches the
port can sign in with it. docker-compose.yml now stops new databases from getting one
(STRUCTR_initialuser_create=false); this removes it from a database that already has one.

Only that account: a `User` named `admin` that still signs in with `admin`/`admin`. If its password
was changed, someone made it theirs, and it stays (and the one failed sign-in this cost it is taken
back off its count). A household member (a `Person`) of that name is never touched. The owner chose
this (2026-10-31).

It changes one account and no schema or data, so like 30a to 47a it must also run against the
owner's instance (owner_data_ok=True). Idempotent: run again, it finds nothing.

Run with: python3 scripts/48a_remove_initial_admin.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect
from structr_client import StructrClient
from structr_client.client import StructrError

NAME = PASSWORD = "admin"


def signs_in(url: str, name: str, password: str) -> bool:
    """Whether `name`/`password` signs in: one header request, which Structr counts as a login."""
    try:
        StructrClient(url, name, password).get("/structr/rest/me")
        return True
    except StructrError as exc:
        if exc.status == 401:
            return False
        raise


def remove_initial_admin(client, url: str, signs_in=signs_in) -> str:
    """Delete the initial account if it is still as Structr made it. Returns what was done."""
    users = [u for u in client.get("/structr/rest/User", params={"name": NAME})["result"] if u.get("type") == "User"]
    if not users:
        return "none"
    if len(users) > 1:
        raise RuntimeError(f"{len(users)} accounts are named {NAME!r}; look at them by hand")
    if not signs_in(url, NAME, PASSWORD):
        client.patch(f"/structr/rest/User/{users[0]['id']}", {"passwordAttempts": 0})
        return "kept"
    client.delete(f"/structr/rest/User/{users[0]['id']}")
    return "removed"


def main(signs_in=signs_in):
    client = connect(owner_data_ok=True)     # one account, no data; the owner's instance needs it too
    client.wait_until_ready()
    print(f"[1] A user {NAME!r} that still signs in with the password {PASSWORD!r}...")
    done = remove_initial_admin(client, client.base_url, signs_in=signs_in)
    print({"none": "    none here",
           "kept": f"    {NAME!r} is there but its password was changed: kept",
           "removed": f"    removed"}[done])
    # Only after a removal: signing in again to a kept account would count one more failed login
    # against it, the one remove_initial_admin has just taken back off.
    if done == "removed" and signs_in(client.base_url, NAME, PASSWORD):
        print(f"FAILED: {NAME}/{PASSWORD} still signs in")
        sys.exit(1)
    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
