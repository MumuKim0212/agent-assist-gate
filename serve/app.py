"""The demo server. Two surfaces, kept apart the way the real tool keeps them.

    /                  the tool's main screen: search box -> ranked list -> document.
                       No gate: what an agent sees is the ranking itself.
    /search?q=         the ranked list (a result opens its document beside the list)
    /doc?id=           one full document
    /departments       the routing table, filterable
    /not_here  (POST)  the "여기 없음" press; records nothing in the demo
    /answer            the gate demo (serve/gate_demo.py): the same retrieval, gated

    python -m serve.app                 # http://127.0.0.1:8000
    python -m serve.app --port 8080

Standard library only, and no JavaScript. Everything the page does is a plain
navigation or a form POST. `dispatch()` is the one place routes live: the local
server below and the Vercel entry point (`api/index.py`) both call it, so they cannot
drift apart.

The only state is a cookie of document ids (the sidebar's "최근 확인 문서"). Queries are
never stored, and `log_message` never prints a query string.
"""
import argparse
import http.cookies
import http.server
import urllib.parse

from core import index, retrieve
from serve import departments, gate_demo, render

RECENT_COOKIE = "recent"
RECENT_MAX = 8
RECENT_COOKIE_MAX_CHARS = 3000      # browsers keep ~4 KB per cookie; stay well under
RECENT_MAX_AGE = 30 * 24 * 3600

_DOCS = {}


def documents():
    """id -> document, from the same loader the search uses."""
    if not _DOCS:
        _DOCS.update({doc["id"]: doc for doc in index.load_docs()})
    return _DOCS


def _one(params, name):
    return (params.get(name) or [""])[0]


# -- recent documents ---------------------------------------------------------------------

def recent_cookie_value(ids):
    """Document ids only -- never a query -- percent-encoded and joined with `|`,
    newest first, trimmed from the old end until it fits."""
    ids = list(ids)[:RECENT_MAX]
    while ids:
        value = "|".join(urllib.parse.quote(i, safe="") for i in ids)
        if len(value) <= RECENT_COOKIE_MAX_CHARS:
            return value
        ids.pop()
    return ""


def read_recent(cookie_header):
    """This browser's recent ids. Ids the corpus does not have, repeats and anything
    malformed are dropped, so a stale or tampered cookie cannot put text on the
    screen: titles always come from the corpus."""
    try:
        jar = http.cookies.SimpleCookie(cookie_header or "")
    except http.cookies.CookieError:
        return []
    morsel = jar.get(RECENT_COOKIE)
    if morsel is None:
        return []
    known, seen, out = documents(), set(), []
    for part in morsel.value.split("|"):
        doc_id = urllib.parse.unquote(part)
        if doc_id in known and doc_id not in seen:
            seen.add(doc_id)
            out.append(doc_id)
    return out[:RECENT_MAX]


def _show_recent(ids):
    known = documents()
    render.RECENT.set(tuple((i, render.title_of(known[i])) for i in ids))


def _remember(ids, doc_id):
    """Put `doc_id` first, show it in this page's own sidebar, and return the
    Set-Cookie header that keeps it."""
    ids = ([doc_id] + [i for i in ids if i != doc_id])[:RECENT_MAX]
    _show_recent(ids)
    cookie = (f"{RECENT_COOKIE}={recent_cookie_value(ids)}; Path=/; "
              f"Max-Age={RECENT_MAX_AGE}; SameSite=Lax; HttpOnly")
    return [("Set-Cookie", cookie)]


# -- responses ----------------------------------------------------------------------------

def _html(body, status=200, headers=()):
    return status, [("Content-Type", "text/html; charset=utf-8"), *headers], body.encode("utf-8")


def _redirect(location, status=302):
    return status, [("Location", location)], b""


def _not_found():
    return _html(render.page("찾을 수 없음", "<p>없는 주소입니다.</p>"), status=404)


# -- routes -------------------------------------------------------------------------------

def dispatch(method, target, body=b"", cookie=""):
    """-> (status, [(header, value), ...], payload bytes)"""
    parsed = urllib.parse.urlparse(target)
    route = parsed.path.rstrip("/") or "/"
    params = urllib.parse.parse_qs(parsed.query)
    recent = read_recent(cookie)
    _show_recent(recent)

    if method == "POST":
        if route != "/not_here":
            return _not_found()
        form = urllib.parse.parse_qs(body.decode("utf-8", "replace"))
        # 303, so that the browser's next Back does not re-post the press. Nothing is
        # recorded: the real tool logs it, the demo has no log.
        return _redirect("/search?" + urllib.parse.urlencode(
            {"q": _one(form, "q")[:300], "none": "1"}), status=303)

    if route == "/":
        return _html(render.search_page(
            [(label, q) for label, q, _, _ in gate_demo.EXAMPLES]))
    if route == "/search":
        return _search(params, recent)
    if route == "/doc":
        return _document(params, recent)
    if route == "/departments":
        routing = documents().get(departments.ROUTING_ID)
        return _html(render.departments_page(routing, _one(params, "q")[:100]))
    if route == "/answer":
        return _html(gate_demo.page(_one(params, "q")[:300], _one(params, "doc") or None,
                                    bool(_one(params, "list"))))
    return _not_found()


def _search(params, recent):
    query = _one(params, "q").strip()[:300]
    if not query:
        return _html(render.search_page())
    hits = retrieve.retrieve(query)
    # A result opens its document beside the list: the same page again with `doc`
    # set. An id the corpus does not have opens nothing.
    doc = documents().get(_one(params, "doc"))
    headers = _remember(recent, doc["id"]) if doc is not None else ()
    return _html(render.results_page(query, hits, pressed_none=bool(params.get("none")),
                                     doc=doc), headers=headers)


def _document(params, recent):
    doc = documents().get(_one(params, "id"))
    if doc is None:
        return _not_found()
    query = _one(params, "q")[:300]
    back = "/search?" + urllib.parse.urlencode({"q": query}) if query else "/"
    return _html(render.document_page(doc, back, query), headers=_remember(recent, doc["id"]))


# -- the local server ---------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "agent-assist-demo"

    def log_message(self, fmt, *args):
        """The default logs the whole request line, which would put every query into
        stderr. Every argument is truncated at its first "?", which leaves the method,
        the path, and the status code."""
        super().log_message(fmt, *(str(arg).split("?", 1)[0] for arg in args))

    def _respond(self, status, headers, payload):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._respond(*dispatch("GET", self.path, cookie=self.headers.get("Cookie") or ""))

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self._respond(*dispatch("POST", self.path, body, self.headers.get("Cookie") or ""))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    retrieve.warmup()
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"http://{args.host}:{args.port}/         main screen -- ranked list, no gate")
    print(f"http://{args.host}:{args.port}/answer   gate demo")
    print("(Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
