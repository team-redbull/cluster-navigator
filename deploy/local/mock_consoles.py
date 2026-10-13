"""Stands in for every cluster's OpenShift console, for the local stack only.

The seed points each fake cluster's console URL here, at /<cluster name>, so
the server's console checks have something to reach. Clusters marked
`console_down` in the fixtures answer 503, as the router does when the
console pods are gone.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import fixtures

DOWN = {
    name
    for group in (fixtures.MCES, fixtures.HOSTED, fixtures.UPI)
    for name, *_, extras in group
    if extras.get("console_down")
}


class Handler(BaseHTTPRequestHandler):
    def _answer(self) -> None:
        name = self.path.strip("/")
        self.send_response(503 if name in DOWN else 200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_HEAD = _answer  # noqa: N815 - names fixed by BaseHTTPRequestHandler

    def log_message(self, *args) -> None:
        return


if __name__ == "__main__":
    print(f"mock consoles listening on :8000, down: {', '.join(sorted(DOWN)) or 'none'}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
