"""Vercel entry point for the demo page.

Vercel runs this file as a serverless function and looks for a class named
`handler` that subclasses BaseHTTPRequestHandler. Every request is routed here by
vercel.json, and the page is rendered by the same `serve.app.page()` that
`python -m serve.app` uses, so the two cannot drift apart.

Standard library only (plus PyYAML for core/config.yaml). The default config is
BM25 with no embedding and no rerank, so there is no API key and no outbound call.
"""
import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core import retrieve  # noqa: E402
from serve.app import page  # noqa: E402

# Build the index once per cold start rather than on the first request.
retrieve.warmup()


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        # The demo has one page; only the query string selects what it shows.
        if parsed.path.endswith("favicon.ico"):
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)

        def one(name):
            return params.get(name, [""])[0]

        data = page(one("q")[:300], one("doc") or None, bool(one("list"))).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # no query text in logs
        pass
