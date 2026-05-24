import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict = {"status": "ok", "last_sync_at": None}

_PORT = 8080


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        with _lock:
            body = json.dumps(_state).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # suppress per-request access logs


def start() -> None:
    server = HTTPServer(("", _PORT), _Handler)
    thread = threading.Thread(target=server.serve_forever, name="health-server", daemon=True)
    thread.start()
    logger.info("Health check server listening on :%d/health", _PORT)


def set_last_sync(timestamp: str) -> None:
    with _lock:
        _state["last_sync_at"] = timestamp
