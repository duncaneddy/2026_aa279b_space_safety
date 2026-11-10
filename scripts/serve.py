# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Serve the deck locally with caching disabled, so edits to slides, code and data show on reload.

Run: uv run scripts/serve.py [port]   then open http://localhost:8279
"""

import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DECK = Path(__file__).resolve().parents[1] / "deck"


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8279
    server = ThreadingHTTPServer(("", port), partial(NoCacheHandler, directory=str(DECK)))
    print(f"Serving {DECK} at http://localhost:{port}")
    server.serve_forever()
