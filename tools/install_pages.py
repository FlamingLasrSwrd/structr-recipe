"""Install the meal planner's pages into Structr (pages/; docs/pages.md).

    python3 tools/install_pages.py            # install, or replace, every page
    python3 tools/install_pages.py --login    # also the sign-in page and the grant that lets it sign in
    python3 tools/install_pages.py --remove   # remove every page this installs, and the grant

The pages, at /structr/html/<name>: week, shopping, recipes, recipe/<id>, nutrition and pantry. Each
is one server-side script (pages/common.js, then pages/<name>.js) that reads the graph as the signed-in
user and prints the page. They hold no data; the pantry and week pages' forms book pantry changes
(docs/pantry.md), so they are meant for the owner's instance as well as any other. Every element is
visible to signed-in users only, the sign-in page to anyone.

Pages are code: each run replaces each page whole. Its elements are deleted first, since deleting a
Page leaves them behind (verified on Structr 6.0.0), and every element states its `tag`, without which
Structr 6 renders nothing. Needs STRUCTR_SUPERUSER_PASSWORD and STRUCTR_URL.

The superuser cannot sign in to pages (Structr answers "login with superuser not supported"), so
reading them in a browser needs a Structr user with a password; this tool creates none.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES_DIR = os.path.join(ROOT, "pages")
PAGES = {                    # name: (title, script)
    "week": ("Week", "week.js"),
    "recipes": ("Recipes", "recipes.js"),
    "recipe": ("Recipe", "recipe.js"),
    "nutrition": ("Nutrition", "nutrition.js"),
    "pantry": ("Pantry", "pantry.js"),
    "shopping": ("Shopping list", "shopping.js"),
}
LOGIN = "login"
LOGIN_GRANT = {"signature": "_login", "flags": 64}     # an anonymous POST to /structr/rest/login (cheatsheet)
PRIVATE = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False}
PUBLIC = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": True}


def read(name: str) -> str:
    with open(os.path.join(PAGES_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def script(page_file: str) -> str:
    """The page's Content: one ${{ ... }} block, the shared helpers first."""
    return "${{\n" + read("common.js") + "\n" + read(page_file) + "\n}}"


def remove_page(client, name: str) -> int:
    """Delete every Page of this name and every element of it. Returns how many nodes went."""
    gone = 0
    for page in client.get("/structr/rest/Page", params={"name": name})["result"]:
        for node in client.get_all("DOMNode", where={"pageId": page["id"]})["result"]:
            client.delete(f"/structr/rest/DOMNode/{node['id']}")
            gone += 1
        client.delete(f"/structr/rest/Page/{page['id']}")
        gone += 1
    return gone


def build_page(client, name: str, title: str, body: str, *, body_type: str = "text/html", public: bool = False) -> str:
    """A Page: html > head > (title, style), body > content. Returns the Page's id."""
    seen = PUBLIC if public else PRIVATE

    def add(type_name: str, parent: str, page: str, **fields) -> str:
        return client.post(f"/structr/rest/{type_name}", {"pageId": page, "parent": parent, **seen, **fields})["result"][0]

    page = client.post("/structr/rest/Page", {"name": name, "contentType": "text/html", **seen})["result"][0]
    html = add("Html", page, page, tag="html")
    head = add("Head", html, page, tag="head")
    add("Meta", head, page, tag="meta", _html_charset="utf-8")
    add("Meta", head, page, tag="meta", _html_name="viewport", _html_content="width=device-width, initial-scale=1")
    add("Content", add("Title", head, page, tag="title"), page, content=f"{title} · Meal planner", contentType="text/plain")
    add("Content", add("Style", head, page, tag="style"), page, content=read("style.css"), contentType="text/css")
    add("Content", add("Body", html, page, tag="body"), page, content=body, contentType=body_type)
    return page


def login_grants(client) -> list[dict]:
    return client.get("/structr/rest/ResourceAccess", params={"signature": LOGIN_GRANT["signature"]})["result"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--login", action="store_true", help="also the sign-in page and the anonymous login grant")
    parser.add_argument("--remove", action="store_true", help="remove the pages and the grant")
    args = parser.parse_args(argv)
    client = connect(owner_data_ok=True)     # pages hold no data; their bookings are the owner's to make
    client.wait_until_ready()
    if args.remove:
        for name in [*PAGES, LOGIN]:
            print(f"{name}: removed {remove_page(client, name)} node(s)")
        for grant in login_grants(client):
            client.delete(f"/structr/rest/ResourceAccess/{grant['id']}")
            print("removed the anonymous login grant")
        return 0
    for name, (title, page_file) in PAGES.items():
        removed = remove_page(client, name)
        build_page(client, name, title, script(page_file))
        print(f"{name}: {'replaced' if removed else 'installed'} at /structr/html/{name}")
    if args.login:
        remove_page(client, LOGIN)
        build_page(client, LOGIN, "Sign in", read("login.html"), public=True)
        if not login_grants(client):
            client.post("/structr/rest/ResourceAccess", {**LOGIN_GRANT, **PUBLIC})
            print("granted anonymous sign-in at /structr/rest/login")
        print(f"{LOGIN}: installed at /structr/html/{LOGIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
