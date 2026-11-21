"""Vercel entry point for the demo page.

Vercel runs this file as a serverless function and looks for a class named
`handler` that subclasses BaseHTTPRequestHandler. Every request is routed here by
vercel.json, and the page is produced by the same `serve.app.dispatch()` that
`python -m serve.app` uses, so the two cannot drift apart.

Standard library only (plus PyYAML for core/config.yaml). The default config is
BM25 with no embedding and no rerank, so there is no API key and no outbound call.
"""
import pathlib
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core import retrieve  # noqa: E402
from serve.app import dispatch  # noqa: E402

# Build the index once per cold start rather than on the first request.
retrieve.warmup()


class handler(BaseHTTPRequestHandler):
    def _respond(self, status, headers, payload):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path.split("?", 1)[0].endswith("favicon.ico"):
            self.send_error(404)
            return
        self._respond(*dispatch("GET", self.path, cookie=self.headers.get("Cookie") or ""))

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self._respond(*dispatch("POST", self.path, body, self.headers.get("Cookie") or ""))

    def log_message(self, fmt, *args):  # no query text in logs
        pass
