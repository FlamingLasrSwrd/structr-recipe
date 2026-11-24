"""Install the meal planner's pages into Structr (pages/; docs/pages.md).

    python3 tools/install_pages.py            # install, or replace, every page
    python3 tools/install_pages.py --login    # also signing in: its page, its grant, and the page that sends the signed-out there
    python3 tools/install_pages.py --remove   # remove every page this installs, and the grant

The pages, at /structr/html/<name>: week, shopping, alternatives/<week>, recipes, recipe/<id>, nutrition and pantry. Each
is one server-side script (the engine code in pages/lib/, in name order, then pages/common.js, then
pages/<name>.js) that reads the graph as the signed-in
user and prints the page. They hold no data; the pantry and week pages' forms book pantry changes
(docs/pantry.md), so they are meant for the owner's instance as well as any other. Every element is
visible to signed-in users only. Two pages are for anyone, and neither holds data or books: the
sign-in page, and the one Structr shows as its 404 page, which sends a signed-out visitor to sign in
(pages/signed-out.js).

It also puts every pages/files/*.js in Structr's folder /mealplanner/, served at /mealplanner/<name> to
signed-in users only: the pantry page's camera and the barcode reader it loads (docs/pantry.md,
"Scanning with a phone's camera"), its look-up of an unknown barcode on Open Food Facts ("Looking up an
unknown barcode"), and its food picker ("Choosing the food"). Like the pages, each run replaces each file whole.

Before the pages, it makes the one node their bookings lock so that they run one at a time
(ensure_booking_lock; pages/lib/40_bookings.js). Pages are code: each run replaces each page whole. Its elements are deleted first, since deleting a
Page leaves them behind (verified on Structr 6.0.0), and every element states its `tag`, without which
Structr 6 renders nothing. Needs STRUCTR_TOOLS_PASSWORD and STRUCTR_URL.

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
    "alternatives": ("Alternatives", "alternatives.js"),
}
FILES_DIR = os.path.join(PAGES_DIR, "files")
FOLDER = "mealplanner"           # where the files are served from: /mealplanner/<name>
LOCK_PAGE = "booking-lock"     # made, read once and removed: the bookings' lock (ensure_booking_lock)
LOCK_SCRIPT = """${{
$.cypher("MATCH (l:MealPlannerBookingLock) WITH l ORDER BY elementId(l) SKIP 1 DELETE l");
$.print("booking locks: " + $.cypher("MERGE (l:MealPlannerBookingLock {name: 'bookings'}) RETURN count(l) AS n")[0].n);
}}"""
LOGIN = "login"
SIGNED_OUT = "signed-out"      # shown for a 404, and still a 404 (showOnErrorCodes); public, so no engine and no booking
LOGIN_GRANT = {"signature": "_login", "flags": 64}     # an anonymous POST to /structr/rest/login (cheatsheet)
PRIVATE = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": False}
PUBLIC = {"visibleToAuthenticatedUsers": True, "visibleToPublicUsers": True}


def read(name: str) -> str:
    with open(os.path.join(PAGES_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def engine() -> str:
    """The engine code the pages and the Structr methods share: every pages/lib/*.js, in name order."""
    lib = os.path.join(PAGES_DIR, "lib")
    return "\n".join(read(os.path.join("lib", f)) for f in sorted(os.listdir(lib)) if f.endswith(".js"))


def script(page_file: str) -> str:
    """The page's Content: one ${{ ... }} block, the shared helpers first."""
    return "${{\n" + engine() + "\n" + read("common.js") + "\n" + read(page_file) + "\n}}"


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


def build_page(client, name: str, title: str, body: str, *, body_type: str = "text/html", public: bool = False,
               **page_fields) -> str:
    """A Page: html > head > (title, style), body > content. Returns the Page's id."""
    seen = PUBLIC if public else PRIVATE

    def add(type_name: str, parent: str, page: str, **fields) -> str:
        return client.post(f"/structr/rest/{type_name}", {"pageId": page, "parent": parent, **seen, **fields})["result"][0]

    page = client.post("/structr/rest/Page", {"name": name, "contentType": "text/html", **seen, **page_fields})["result"][0]
    html = add("Html", page, page, tag="html")
    head = add("Head", html, page, tag="head")
    add("Meta", head, page, tag="meta", _html_charset="utf-8")
    add("Meta", head, page, tag="meta", _html_name="viewport", _html_content="width=device-width, initial-scale=1")
    add("Content", add("Title", head, page, tag="title"), page, content=f"{title} · Meal planner", contentType="text/plain")
    add("Content", add("Style", head, page, tag="style"), page, content=read("style.css"), contentType="text/css")
    add("Content", add("Body", html, page, tag="body"), page, content=body, contentType=body_type)
    return page


def ensure_booking_lock(client) -> None:
    """The one node every page booking writes to first, so that bookings run one at a time (pages/lib/40_bookings.js).
    Made here, where nothing runs beside it; made by the first booking, two at once each made their own.
    Cypher runs only inside Structr here, so a page made for the purpose makes it and is removed. A second
    lock node, left by an earlier way of making it, is deleted."""
    remove_page(client, LOCK_PAGE)
    build_page(client, LOCK_PAGE, "Booking lock", LOCK_SCRIPT)
    try:
        r = client.request("GET", f"/structr/html/{LOCK_PAGE}")
        r.raise_for_status()
        if "booking locks: 1" not in r.text:
            raise RuntimeError(f"the bookings' lock was not made: {r.text[:300]}")
    finally:
        remove_page(client, LOCK_PAGE)


def served_files() -> list[str]:
    """The files the pages load, by name: every pages/files/*.js (its licence beside it is not served)."""
    return sorted(f for f in os.listdir(FILES_DIR) if f.endswith(".js"))


def remove_files(client) -> int:
    """Delete every file in the /mealplanner/ folder, and the folder. Returns how many nodes went."""
    gone = 0
    for folder in client.get("/structr/rest/Folder", params={"name": FOLDER})["result"]:
        if folder.get("path") not in (None, f"/{FOLDER}"):
            continue
        for row in client.get("/structr/rest/File", params={"parentId": folder["id"]})["result"]:
            client.delete(f"/structr/rest/File/{row['id']}")
            gone += 1
        client.delete(f"/structr/rest/Folder/{folder['id']}")
        gone += 1
    return gone


def install_files(client) -> list[str]:
    """Each served file put in /mealplanner/ again, whole, visible to signed-in users only (an upload is
    owner-only until its visibility is set: docs/structr-cheatsheet.md §5). Returns their paths."""
    remove_files(client)
    folder = client.post("/structr/rest/Folder", {"name": FOLDER, **PRIVATE})["result"][0]
    paths = []
    for name in served_files():
        with open(os.path.join(FILES_DIR, name), "rb") as fh:
            body = fh.read()
        r = client.request("POST", "/structr/upload", files={"file": (name, body, "text/javascript")},
                           data={"parent": folder}, headers={"Content-Type": None})
        if r.status_code >= 400:
            raise RuntimeError(f"uploading {name}: {r.status_code} {r.text[:300]}")
        client.patch(f"/structr/rest/File/{r.text.strip()}", {"contentType": "text/javascript", **PRIVATE})
        paths.append(f"/{FOLDER}/{name}")
    return paths


def login_grants(client) -> list[dict]:
    return client.get("/structr/rest/ResourceAccess", params={"signature": LOGIN_GRANT["signature"]})["result"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--login", action="store_true", help="also the sign-in page, the redirect to it when signed out, and the anonymous login grant")
    parser.add_argument("--remove", action="store_true", help="remove the pages and the grant")
    args = parser.parse_args(argv)
    client = connect(owner_data_ok=True)     # pages hold no data; their bookings are the owner's to make
    client.wait_until_ready()
    if args.remove:
        for name in [*PAGES, LOGIN, SIGNED_OUT]:
            print(f"{name}: removed {remove_page(client, name)} node(s)")
        print(f"/{FOLDER}/: removed {remove_files(client)} node(s)")
        for grant in login_grants(client):
            client.delete(f"/structr/rest/ResourceAccess/{grant['id']}")
            print("removed the anonymous login grant")
        return 0
    ensure_booking_lock(client)
    print("bookings: one lock node")
    for path in install_files(client):
        print(f"{path}: installed")
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
        remove_page(client, SIGNED_OUT)     # after the page it sends people to
        build_page(client, SIGNED_OUT, "Not available", "${{\n" + read("signed-out.js") + "\n}}", public=True,
                   showOnErrorCodes="404", dontCache=True)
        print(f"{SIGNED_OUT}: installed; a signed-out visitor to a page is sent to sign in")
    return 0


if __name__ == "__main__":
    sys.exit(main())
