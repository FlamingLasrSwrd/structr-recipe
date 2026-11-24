"""A page's booking is made only from one of the instance's own pages (pages/common.js fromOwnPage;
docs/pages.md, "Bookings from another site"): a link another site sends a signed-in browser to books
nothing. runBooking runs in node or gjs, where either is installed, with a stand-in for Structr's `$` and
for the booking itself, so what is checked is the gate alone."""

import json
import pathlib
import shutil
import unittest

from tests.test_signed_out import javascript

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENGINE = shutil.which("node") or shutil.which("gjs")
HOST = "192.168.1.8:8443"


def booking(headers: dict, *, header_function: bool = True) -> dict:
    """What runBooking does for a purchase sent with these request headers: whether the booking ran, and
    the problem the page records."""
    common = (ROOT / "pages" / "common.js").read_text()
    lookup = ("getRequestHeader: function (name) { var k = Object.keys(H).filter(function (h) { "
              "return h.toLowerCase() === name.toLowerCase(); })[0]; return k === undefined ? null : H[k]; },"
              if header_function else "")
    return javascript(f"""
var H = {json.dumps(headers)}, ran = false;
var $ = {{request: {{do: "buy", token: "abcd1234"}}, me: {{type: "Person", groups: [{{type: "Household", name: "TEST"}}]}},
         {lookup} find: function () {{ return []; }}}};
function bookOnce(actions, action, request, token, household) {{
  ran = true;
  return {{problem: null, booking: {{process: "TEST -- a purchase", created: ["TEST -- a purchase"], notes: []}}}};
}}
{common}
var said = runBooking({{buy: function () {{}}}});
var result = {{ran: ran, problem: BOOKED && BOOKED.problem, said: said}};""")


@unittest.skipUnless(ENGINE, "needs node or gjs")
class BookingsComeFromTheSitesOwnPages(unittest.TestCase):
    def test_a_form_on_the_page_books(self):
        got = booking({"Host": HOST, "Sec-Fetch-Site": "same-origin", "Referer": f"https://{HOST}/structr/html/pantry"})
        self.assertTrue(got["ran"])
        self.assertIsNone(got["problem"])

    def test_a_link_from_another_site_books_nothing(self):
        for site in ("cross-site", "same-site", "none"):     # another site; another port of this address; a bookmark
            with self.subTest(site=site):
                got = booking({"Host": HOST, "Sec-Fetch-Site": site, "Referer": f"https://{HOST}/structr/html/pantry"})
                self.assertFalse(got["ran"])
                self.assertEqual(got["problem"], "not from this site")
                self.assertIn("was not saved", got["said"])

    def test_without_sec_fetch_site_the_referer_must_be_this_host(self):
        self.assertTrue(booking({"Host": HOST, "Referer": f"https://{HOST}/structr/html/week"})["ran"])
        self.assertTrue(booking({"Host": HOST.upper(), "Referer": f"HTTPS://{HOST}/structr/html/week?x=1"})["ran"])
        for referer in (f"https://evil.example/{HOST}/", f"https://{HOST}.evil.example/", "https://192.168.1.8:8085/",
                        "javascript:alert(1)", ""):
            with self.subTest(referer=referer):
                self.assertFalse(booking({"Host": HOST, "Referer": referer})["ran"])

    def test_a_request_that_says_nothing_of_where_it_came_from_books_nothing(self):
        self.assertFalse(booking({"Host": HOST})["ran"])
        self.assertFalse(booking({})["ran"])

    def test_a_tools_request_signed_in_by_its_own_headers_books(self):
        self.assertTrue(booking({"Host": HOST, "X-User": "TEST -- member A1", "X-Password": "x"})["ran"])
        self.assertTrue(booking({"Host": HOST, "X-StructrSessionToken": "abc"})["ran"])

    def test_without_the_header_function_nothing_books(self):
        """Should Structr not offer getRequestHeader, every page booking is refused rather than let through."""
        got = booking({"Host": HOST, "Sec-Fetch-Site": "same-origin"}, header_function=False)
        self.assertFalse(got["ran"])


if __name__ == "__main__":
    unittest.main()
