// What Structr shows in place of a page that is not there for the visitor: the page is not installed,
// or they may not see it, as everyone signed out may not (tools/install_pages.py --login installs it as
// the 404 page; docs/pages.md "Signing in"). It is public, so it stands alone: it has none of pages/lib/
// or pages/common.js, reads no graph and books nothing. A signed-out visitor's browser goes on to the
// sign-in page, which brings them back. Only the path is carried: the query can hold a booking
// (?do=...), which must not be made by signing in. The sign-in page says when one was dropped.
if ($.me) {
  $.print('<h1>Page not found</h1><p><a href="/structr/html/week">To the week</a></p>');
} else {
  $.print('<h1>Signed out</h1><p><a href="/structr/html/login">Sign in</a></p>'
    + '<script>(function () {'
    + 'var here = location.pathname, signIn = "/structr/html/login";'
    + 'if (here === signIn) { return; }'    // no sign-in page to send them to: stay, do not loop
    + 'var unsaved = /[?&]do=/.test(location.search) ? "&unsaved=1" : "";'
    + 'location.replace(signIn + "?next=" + encodeURIComponent(here) + unsaved);'
    + '})();</script>');
}
