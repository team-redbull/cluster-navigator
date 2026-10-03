"""A stand-in for Segments Manager, for the local stack only.

Serves the read endpoints with the same response shape as the real service.
The collector uses /api/segments/search.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import fixtures


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path in ("/api/segments", "/api/segments/search"):
            body = fixtures.segments()
            for key in ("site", "status", "type"):
                if key in query:
                    body = [segment for segment in body if segment.get(key) == query[key][0]]
            if url.path.endswith("/search"):
                # Like the real service: a case-insensitive match on part of the name, EPG or CIDR.
                needle = query.get("q", [""])[0].lower()
                body = [
                    segment for segment in body
                    if any(needle in str(segment.get(field) or "").lower() for field in ("cluster_name", "epg_name", "segment"))
                ]
        elif url.path == "/api/sites":
            body = {"sites": fixtures.SITES}
        elif url.path == "/api/health":
            body = {"status": "healthy"}
        else:
            self.send_error(404)
            return
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        return


if __name__ == "__main__":
    print("mock Segments Manager listening on :8000", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
