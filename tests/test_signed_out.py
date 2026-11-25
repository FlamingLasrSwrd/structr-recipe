"""A signed-out visitor is sent to sign in and back (pages/signed-out.js, pages/login.html), and the page
that does it gives them nothing else. The scripts run in node or gjs, where either is installed, against
a stand-in browser; the installation is checked without one."""

import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

from tests.test_pages_tools import PageGraph, load, run

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENGINE = shutil.which("node") or shutil.which("gjs")
WEEK = "/structr/html/week"
LOGIN = "/structr/html/login"


def javascript(code: str):
    """What `code` leaves in `result`. The program goes in a file, not on the command line: a page with its
    library is more than the 128 KB one argument may hold."""
    program = code + '\n(typeof print === "function" ? print : console.log)(JSON.stringify(result));'
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder) / "program.js"
        path.write_text(program)
        done = subprocess.run([ENGINE, str(path)], capture_output=True, text=True, timeout=30)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout.strip().splitlines()[-1])


def error_page(me) -> str:
    script = (ROOT / "pages" / "signed-out.js").read_text()
    return javascript(f"var result = ''; var $ = {{me: {json.dumps(me)}, print: function (h) {{ result += h; }}}};\n{script}")


def sent_to(path: str, search: str = ""):
    (script,) = re.findall(r"<script>(.*?)</script>", error_page(None), re.S)
    return javascript(f"var result = null; var location = {{pathname: {json.dumps(path)}, search: {json.dumps(search)}, "
                      f"replace: function (to) {{ result = to; }}}};\n{script}")


def sign_in(search: str = "", secure: bool = True, ok: bool = True) -> dict:
    (script,) = re.findall(r"<script>(.*?)</script>", (ROOT / "pages" / "login.html").read_text(), re.S)
    return javascript(f"""
var seen = {{}}, submit = null;
var location = {{search: {json.dumps(search)}, hostname: "192.0.2.8"}};
var window = {{isSecureContext: {json.dumps(secure)}, location: null}};
var document = {{getElementById: function (id) {{
  if (!seen[id]) {{ seen[id] = {{hidden: true, textContent: "", addEventListener: function (e, f) {{ submit = f; }}}}; }}
  return seen[id];
}}}};
var fetch = function () {{ return {{then: function (f) {{ f({{ok: {json.dumps(ok)}}}); }}}}; }};
{script}
submit({{preventDefault: function () {{}}, target: {{name: {{value: "Jamie"}}, password: {{value: "not-a-password"}}}}}});
var result = {{to: window.location, insecure: seen.insecure && !seen.insecure.hidden ? seen.insecure.textContent : null,
              unsaved: !!(seen.unsaved && !seen.unsaved.hidden), message: seen.message ? seen.message.textContent : ""}};""")


class Installed(unittest.TestCase):
    tool = load()

    def installed(self, *argv):
        graph = PageGraph()
        self.assertEqual(run(self.tool, list(argv), graph), 0)
        return graph

    def test_login_installs_one_public_404_page_however_often_it_runs(self):
        graph = self.installed("--login")
        run(self.tool, ["--login"], graph)
        (page,) = [p for p in graph.of("Page") if p.get("showOnErrorCodes")]
        self.assertEqual((page["name"], page["showOnErrorCodes"], page["dontCache"]), ("signed-out", "404", True))
        self.assertTrue(page["visibleToPublicUsers"] and page["visibleToAuthenticatedUsers"])
        elements = [n for n in graph.of("DOMNode") if n["pageId"] == page["id"]]
        self.assertEqual(len(elements), 10)
        self.assertTrue(all(n["visibleToPublicUsers"] and n["visibleToAuthenticatedUsers"] for n in elements))

    def test_the_planners_pages_stay_private(self):
        graph = self.installed("--login")
        public = {p["name"] for p in graph.of("Page") if p["visibleToPublicUsers"]}
        self.assertEqual(public, {"login", "signed-out"})
        private = {p["id"] for p in graph.of("Page") if p["name"] not in public}
        self.assertEqual(len(private), 6)
        self.assertFalse(any(n["visibleToPublicUsers"] for n in graph.of("DOMNode") if n["pageId"] in private))

    def test_the_public_page_can_neither_read_nor_book(self):
        graph = self.installed("--login")
        (page,) = [p for p in graph.of("Page") if p["name"] == "signed-out"]
        (body,) = [n["content"] for n in graph.of("Content") if n["pageId"] == page["id"] and n["contentType"] == "text/html"]
        self.assertEqual(body, "${{\n" + (ROOT / "pages" / "signed-out.js").read_text() + "\n}}")
        self.assertEqual(set(re.findall(r"\$\.(\w+)", body)), {"me", "print"})

    def test_without_login_there_is_none(self):
        self.assertFalse([p for p in self.installed().of("Page") if p.get("showOnErrorCodes")])

    def test_remove_takes_it_away(self):
        graph = self.installed("--login")
        run(self.tool, ["--remove"], graph)
        self.assertEqual(graph.nodes, {})


@unittest.skipUnless(ENGINE, "needs node or gjs")
class SignedOut(unittest.TestCase):
    def test_a_page_sends_to_sign_in_naming_itself(self):
        self.assertEqual(sent_to("/structr/html/pantry"), LOGIN + "?next=%2Fstructr%2Fhtml%2Fpantry")
        self.assertEqual(sent_to(WEEK + "/0a1b2c"), LOGIN + "?next=%2Fstructr%2Fhtml%2Fweek%2F0a1b2c")

    def test_a_booking_is_dropped_and_said_never_carried(self):
        self.assertEqual(sent_to("/structr/html/pantry", "?do=discard&portion=abc&token=1234"),
                         LOGIN + "?next=%2Fstructr%2Fhtml%2Fpantry&unsaved=1")
        self.assertEqual(sent_to("/structr/html/pantry", "?portion=abc&do=use"),
                         LOGIN + "?next=%2Fstructr%2Fhtml%2Fpantry&unsaved=1")

    def test_another_query_is_dropped_without_a_word(self):
        self.assertEqual(sent_to("/structr/html/recipes", "?meal=Breakfast&undo=1"),
                         LOGIN + "?next=%2Fstructr%2Fhtml%2Frecipes")

    def test_a_missing_sign_in_page_does_not_loop(self):
        self.assertIsNone(sent_to(LOGIN, "?next=%2Fstructr%2Fhtml%2Fweek"))

    def test_someone_signed_in_is_not_sent_anywhere(self):
        page = error_page({"name": "Jamie"})
        self.assertIn("Page not found", page)
        self.assertNotIn("<script", page)
        self.assertNotIn(LOGIN, page)


@unittest.skipUnless(ENGINE, "needs node or gjs")
class SignIn(unittest.TestCase):
    def test_it_goes_back_to_each_of_the_planners_pages(self):
        for name in load().PAGES:
            with self.subTest(name):
                self.assertEqual(sign_in(f"?next=%2Fstructr%2Fhtml%2F{name}")["to"], f"/structr/html/{name}")
        self.assertEqual(sign_in("?next=%2Fstructr%2Fhtml%2Fweek%2FWeek%2520of%25202026-10-26")["to"],
                         WEEK + "/Week%20of%202026-10-26")
        self.assertEqual(sign_in("?next=%2Fstructr%2Fhtml%2Frecipe%2F0a1b-2c3d")["to"], "/structr/html/recipe/0a1b-2c3d")

    def test_it_goes_on_to_the_week_by_itself(self):
        self.assertEqual(sign_in()["to"], WEEK)

    def test_it_goes_nowhere_else_whatever_a_link_says(self):
        for given in ("https://bank.example/", "//bank.example/", "/\\bank.example", "javascript:alert(1)",
                      "/structr/", "/structr/rest/User", "/structr/html/login", "/structr/html/signed-out",
                      "%2Fstructr%2Fhtml%2Fpantry%3Fdo%3Ddiscard%26token%3D1234", "/structr/html/pantry?do=discard",
                      "%2Fstructr%2Fhtml%2Fweek%2F0a1b%3Fdo%3Dcook%26token%3D1234",
                      "/structr/html/pantry#x", "/structr/html/week/../../rest/User", "/structr/html/week/..",
                      "/structr/html/pantryx", "x/structr/html/pantry", "%E0%A4%A"):
            with self.subTest(given):
                self.assertEqual(sign_in("?next=" + given)["to"], WEEK)

    def test_a_wrong_password_stays_and_says_so(self):
        seen = sign_in("?next=%2Fstructr%2Fhtml%2Fpantry", ok=False)
        self.assertIsNone(seen["to"])
        self.assertIn("did not sign in", seen["message"])

    def test_a_dropped_change_is_said(self):
        self.assertTrue(sign_in("?next=%2Fstructr%2Fhtml%2Fpantry&unsaved=1")["unsaved"])
        self.assertFalse(sign_in("?next=%2Fstructr%2Fhtml%2Fpantry")["unsaved"])

    def test_an_address_where_signing_in_cannot_last_says_so(self):
        self.assertIn("https://192.0.2.8:8443" + LOGIN, sign_in(secure=False)["insecure"])
        self.assertIsNone(sign_in(secure=True)["insecure"])


if __name__ == "__main__":
    unittest.main()
