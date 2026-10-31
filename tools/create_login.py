"""Create a Structr user to sign in to the pages with (docs/pages.md).

    python3 tools/create_login.py             # asks for a name and a password
    python3 tools/create_login.py --name eli  # asks for the password only

The superuser cannot sign in to pages, so reading them in a browser needs a user of its own. The
owner decided (2026-10-23) that the pages need no more security than that for now: the instance is
local and behind a firewall. A name of one of the household's people (a `Person`, which is also a
Structr account, data-model.md K1) gives that person a password, so they sign in as themselves:
the owner's choice for Elijah, the same day. Any other name is a Structr `User` of its own. The
password is typed without being shown and is stored nowhere but in Structr, as Structr stores
passwords. For the same name again, it sets a new password. Needs STRUCTR_TOOLS_PASSWORD and
STRUCTR_URL.
"""

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect

UNSEEN = {"visibleToAuthenticatedUsers": False, "visibleToPublicUsers": False}   # an account, not data to list


def main(argv=None, ask=input, ask_secret=getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", help="the name to sign in with")
    args = parser.parse_args(argv)
    name = (args.name or ask("Name to sign in with: ")).strip()
    if not name:
        print("problem: a name is needed")
        return 1
    password = ask_secret("Password: ")
    if len(password) < 8:
        print("problem: a password of at least 8 characters, please")
        return 1
    if ask_secret("The same password again: ") != password:
        print("problem: the two passwords differ; nothing was changed")
        return 1
    client = connect(owner_data_ok=True)     # an account on the owner's instance is theirs to make
    client.wait_until_ready()
    persons = client.get("/structr/rest/Person", params={"name": name})["result"]
    if len(persons) > 1:
        print(f"problem: {len(persons)} people are named {name!r}; nothing was changed")
        return 1
    if persons:
        client.patch(f"/structr/rest/Person/{persons[0]['id']}", {"password": password})
        print(f"{name}: a person of the household, who can now sign in at {client.base_url}/structr/html/login")
        return 0
    users = client.get("/structr/rest/User", params={"name": name})["result"]
    if users:
        client.patch(f"/structr/rest/User/{users[0]['id']}", {"password": password})
        print(f"{name}: a new password is set")
    else:
        client.post("/structr/rest/User", {"name": name, "password": password, "isAdmin": False, **UNSEEN})
        print(f"{name}: created; sign in at {client.base_url}/structr/html/login")
    return 0


if __name__ == "__main__":
    sys.exit(main())
