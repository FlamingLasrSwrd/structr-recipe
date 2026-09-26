"""Two minimal public-facing Structr pages: a home page and a recipe list.

Deliberately plain: one small inline <style> block (no framework, no client-side
JS), one dynamic list built with StructrScript's each()/find(). The point of
this script is to have *something* real to look at over HTTP while the actual
frontend is designed -- expect this to be replaced or heavily edited, not
extended in place.

Two Structr rendering gotchas found while building this, neither previously in
docs/structr-cheatsheet.md, both worth knowing before touching this script:

1. TAG-SPECIFIC DOM TYPES DO NOT RENDER ON THIS BUILD. POSTing to
   /structr/rest/Html, /structr/rest/Body, /structr/rest/H1, /structr/rest/A,
   etc. (the approach the cheatsheet's own Sec 6 example shows) creates
   perfectly good graph nodes -- correct parent/child links, readable back via
   GET -- but the HtmlServlet renders nothing for that node or anything under
   it: the response is the bare "<!DOCTYPE html>" line and nothing else, no
   error anywhere (verified after a clean container restart, so not a stale
   process). The generic /structr/rest/DOMElement with an explicit "tag"
   property renders correctly. Every element below is built that way.
2. THE GENERIC ROUTE DROPS TAG-SPECIFIC ATTRIBUTES SILENTLY, confirming the
   cheatsheet's existing warning about _html_href etc. on a generic DOMElement.
   Worked around here by writing the handful of real <a href=...> links as
   literal markup inside a Content node with contentType "text/html" (Content
   itself renders fine either way; without that contentType the markup comes
   back HTML-ESCAPED as literal text -- also confirmed empirically, also not
   previously documented).
Both are being written up as additions to structr-cheatsheet.md Sec 6.

Visibility: an element renders only if visibleToPublicUsers is set True on it
(cheatsheet Sec 6); the default is owner-only, and an invisible element is just
absent, no error. Every element this script creates sets both visibility flags
explicitly.

What a public visitor sees on the recipe list depends on the RECIPE DATA's own
visibility, which this script does not touch: every RecipeIdentity currently on
this instance is "TEST --" disposable fixture data, upserted with the project's
default (visibleToAuthenticatedUsers=True, visibleToPublicUsers=False, see
structr_client.StructrClient.upsert), so an anonymous visitor correctly sees
"0 recipe(s)" -- that is the data's own visibility working as designed, not a
bug in this page. An authenticated request sees the real count.

Idempotent: each Page/element is matched by (pageId, name) and patched in place
if found, so editing this script and re-running it updates the live pages
instead of duplicating them. NOTE: deleting a Page does NOT cascade-delete its
element tree in this version (verified: the elements survive with pageId wiped
to null) -- if you ever retire one of these pages by hand, delete its elements
first. Page/DOMElement/Content are Structr's own built-in types, not project
SchemaNodes, so this script's output does not appear in tools/snapshot_state.py
and does not touch SNAPSHOT IDENTICAL.

Rendered at:
  /structr/html/home
  /structr/html/recipes

Run with: python3 scripts/27_public_pages.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mealplanner.connection import connect

VISIBLE = {"visibleToPublicUsers": True, "visibleToAuthenticatedUsers": True}

NAV_LINKS = [("Home", "/structr/html/home"), ("Recipes", "/structr/html/recipes")]
NAV_HTML = " | ".join(f'<a href="{href}">{label}</a>' for label, href in NAV_LINKS)

STYLE_CSS = (
    "body{font-family:sans-serif;max-width:40em;margin:2em auto;padding:0 1em;"
    "line-height:1.5}nav a{margin-right:1em}"
)


def ensure_page(client, name):
    existing = client.get("/structr/rest/Page", params={"name": name})
    if existing and existing.get("result"):
        return existing["result"][0]["id"], False
    payload = {"name": name, **VISIBLE}
    created = client.post("/structr/rest/Page", payload)
    return created["result"][0], True


def ensure_element(client, tag, page_id, parent_id, name):
    """Check-then-create/patch a generic DOMElement (see module docstring for
    why generic, not the tag-specific REST type) matched by (pageId, name)."""
    existing = client.get("/structr/rest/DOMElement", params={"pageId": page_id, "name": name})
    payload = {"name": name, "pageId": page_id, "parent": parent_id, "tag": tag, **VISIBLE}
    if existing and existing.get("result"):
        node_id = existing["result"][0]["id"]
        client.patch(f"/structr/rest/DOMElement/{node_id}", payload)
        return node_id, False
    created = client.post("/structr/rest/DOMElement", payload)
    return created["result"][0], True


def ensure_content(client, page_id, parent_id, name, content, *, html=False, content_type=None):
    """html=True: content is trusted literal markup (e.g. an <a href=...> link)
    and needs contentType "text/html", or it renders back HTML-escaped."""
    if html:
        content_type = "text/html"
    existing = client.get("/structr/rest/Content", params={"pageId": page_id, "name": name})
    payload = {"name": name, "pageId": page_id, "parent": parent_id, "content": content, **VISIBLE}
    if content_type:
        payload["contentType"] = content_type
    if existing and existing.get("result"):
        node_id = existing["result"][0]["id"]
        client.patch(f"/structr/rest/Content/{node_id}", payload)
        return node_id, False
    created = client.post("/structr/rest/Content", payload)
    return created["result"][0], True


def build_skeleton(client, page_id, title_text):
    """Page -> html -> head (title, style) / body (nav). Returns body_id."""
    html_id, _ = ensure_element(client, "html", page_id, page_id, "html")
    head_id, _ = ensure_element(client, "head", page_id, html_id, "head")
    title_id, _ = ensure_element(client, "title", page_id, head_id, "title")
    ensure_content(client, page_id, title_id, "title-text", title_text)
    style_id, _ = ensure_element(client, "style", page_id, head_id, "style")
    ensure_content(client, page_id, style_id, "style-text", STYLE_CSS, content_type="text/css")

    body_id, _ = ensure_element(client, "body", page_id, html_id, "body")
    nav_id, _ = ensure_element(client, "nav", page_id, body_id, "nav")
    ensure_content(client, page_id, nav_id, "nav-links", NAV_HTML, html=True)
    return body_id


def build_home_page(client):
    page_id, created = ensure_page(client, "home")
    body_id = build_skeleton(client, page_id, "Structr Recipe")

    h1_id, _ = ensure_element(client, "h1", page_id, body_id, "h1")
    ensure_content(client, page_id, h1_id, "h1-text", "Structr Recipe")

    p1_id, _ = ensure_element(client, "p", page_id, body_id, "intro")
    ensure_content(
        client, page_id, p1_id, "intro-text",
        "A spike build of a BFO-grounded meal-planning data model on Structr and "
        "Neo4j. This is a development instance, rebuilt from scripts on demand -- "
        "not a curated recipe collection.",
    )

    p2_id, _ = ensure_element(client, "p", page_id, body_id, "stats")
    ensure_content(
        client, page_id, p2_id, "stats-text",
        '${size(find("RecipeIdentity", "isRetired", false))} recipe(s) visible to you right now.',
    )
    return page_id, created


def build_recipes_page(client):
    page_id, created = ensure_page(client, "recipes")
    body_id = build_skeleton(client, page_id, "Recipes -- Structr Recipe")

    h1_id, _ = ensure_element(client, "h1", page_id, body_id, "h1")
    ensure_content(client, page_id, h1_id, "h1-text", "Recipes")

    ul_id, _ = ensure_element(client, "ul", page_id, body_id, "recipe-list")
    ensure_content(
        client, page_id, ul_id, "recipe-list-items",
        '${each(find("RecipeIdentity", "isRetired", false), print("<li>", data.name, "</li>"))}',
        html=True,
    )
    return page_id, created


def main():
    client = connect()
    client.wait_until_ready()

    print("[1] home page (name/navigation/intro paragraph, one live stat)...")
    home_id, home_created = build_home_page(client)
    print(f"    id={home_id} created={home_created}")

    print("\n[2] recipes page (dynamic list of non-retired RecipeIdentity)...")
    recipes_id, recipes_created = build_recipes_page(client)
    print(f"    id={recipes_id} created={recipes_created}")

    print("\n[3] Verification: render both pages over plain HTTP, no auth...")
    import requests

    base = os.environ.get("STRUCTR_URL", "http://localhost:8083")
    for name, must_contain in (("home", "Structr Recipe"), ("recipes", "<h1>Recipes</h1>")):
        resp = requests.get(f"{base}/structr/html/{name}", timeout=10)
        ok = resp.status_code == 200 and must_contain in resp.text
        print(f"    /structr/html/{name}: HTTP {resp.status_code}, has {must_contain!r}: {ok}")
        assert ok, f"{name} did not render as expected -- see body:\n{resp.text[:500]}"

    print("\n[4] Verification: an authenticated view sees the real recipe count...")
    resp = requests.get(
        f"{base}/structr/html/recipes",
        headers={"X-User": "superadmin", "X-Password": os.environ["STRUCTR_SUPERUSER_PASSWORD"]},
        timeout=10,
    )
    li_count = resp.text.count("<li>")
    print(f"    authenticated /structr/html/recipes: {li_count} <li> item(s)")
    assert li_count >= 1, "expected at least one recipe when authenticated"


if __name__ == "__main__":
    main()
