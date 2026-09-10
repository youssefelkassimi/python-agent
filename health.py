import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)


class _StatusStore:
    """Thread-safe holder for the latest agent status snapshot."""

    def __init__(self):
        self._lock = threading.Lock()
        self._status = {
            "started_at": time.time(),
            "last_cycle_at": None,
            "last_cycle_ok": None,
            "cycle_count": 0,
            "cycle_errors": 0,
            "retry_queue_size": 0,
            "plugins": {},
        }

    def update(self, **fields):
        with self._lock:
            self._status.update(fields)

    def snapshot(self):
        with self._lock:
            return dict(self._status)


status_store = _StatusStore()


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Silence default per-request stderr logging; we log via `logging`.
        logger.debug("health endpoint: " + fmt, *args)

    def do_GET(self):
        if self.path not in ("/health", "/healthz", "/status"):
            self.send_response(404)
            self.end_headers()
            return

        snap = status_store.snapshot()
        now = time.time()
        last_cycle_at = snap.get("last_cycle_at")
        stale = last_cycle_at is None or (now - last_cycle_at) > 300

        body = {
            "status": "unhealthy" if stale else "ok",
            "uptime_seconds": round(now - snap["started_at"], 1),
            "last_cycle_seconds_ago": round(now - last_cycle_at, 1) if last_cycle_at else None,
            "cycle_count": snap["cycle_count"],
            "cycle_errors": snap["cycle_errors"],
            "retry_queue_size": snap["retry_queue_size"],
            "plugins": snap["plugins"],
        }

        payload = json.dumps(body).encode("utf-8")
        self.send_response(200 if not stale else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def start_health_server(host="127.0.0.1", port=9273):
    """Starts the health endpoint in a daemon thread and returns the server.

    Call server.shutdown() during agent shutdown to stop it cleanly.
    """
    server = ThreadingHTTPServer((host, port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="health-server")
    thread.start()
    logger.info(f"Health endpoint listening on http://{host}:{port}/health")
    return server
