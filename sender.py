import requests
import logging
import time
import uuid
import platform

logger = logging.getLogger(__name__)

DEFAULT_MAX_BACKOFF_SECONDS = 300


class MetricSender:
    def __init__(self, backend_url, agent_id, api_key=None, retry_queue=None,
                 ssl_verify=True, ca_cert=None, timeout=10,
                 max_backoff_seconds=DEFAULT_MAX_BACKOFF_SECONDS):
        self.base_url = backend_url.rstrip("/")
        self.agent_id = agent_id
        self.retry_queue = retry_queue
        self.ssl_verify = ssl_verify
        self.ca_cert = ca_cert
        self.timeout = timeout
        self.headers = {
            "Content-Type": "application/json",
            "X-Agent-ID": agent_id,
        }
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        if ca_cert:
            self.verify = ca_cert
        else:
            self.verify = ssl_verify

        # Exponential backoff state: tracks consecutive failures so the
        # caller (main loop) can space out retries instead of hammering a
        # backend that's down every single interval.
        self._consecutive_failures = 0
        self._max_backoff_seconds = max_backoff_seconds

    @property
    def backoff_seconds(self):
        """Suggested delay before the next retry, based on recent failures."""
        if self._consecutive_failures == 0:
            return 0
        return min(2 ** self._consecutive_failures, self._max_backoff_seconds)

    @property
    def is_degraded(self):
        return self._consecutive_failures >= 3

    def send_metrics(self, payload):
        payload["agentId"] = self.agent_id
        payload["sent_at"] = time.time()
        return self._post("/api/metrics", payload)

    def send_heartbeat(self):
        data = {
            "agentId": self.agent_id,
            "timestamp": time.time(),
            "hostname": platform.node(),
            "status": "alive",
        }
        return self._post("/api/heartbeat", data)

    def send_inventory(self, inventory_data):
        payload = {
            "agentId": self.agent_id,
            "timestamp": time.time(),
            "inventory": inventory_data,
        }
        return self._post("/api/inventory", payload)

    def send_alerts(self, alerts):
        payload = {
            "agentId": self.agent_id,
            "timestamp": time.time(),
            "alerts": alerts,
        }
        return self._post("/api/alerts", payload)

    def send_discovery(self, discovery_data):
        payload = {
            "agentId": self.agent_id,
            "timestamp": time.time(),
            "discovery": discovery_data,
        }
        return self._post("/api/discovery", payload)

    def send_log_events(self, log_data):
        payload = {
            "agentId": self.agent_id,
            "timestamp": time.time(),
            "logs": log_data,
        }
        return self._post("/api/logs", payload)

    def fetch_commands(self):
        return self._get(f"/api/commands/{self.agent_id}")

    def send_command_result(self, result):
        payload = {
            "agentId": self.agent_id,
            "timestamp": time.time(),
            "result": result,
        }
        return self._post(f"/api/commands/{result.get('command_id')}/result", payload)

    def fetch_config(self):
        return self._get(f"/api/agent-config/{self.agent_id}")

    def register_agent(self):
        data = {
            "agentId": self.agent_id,
            "hostname": platform.node(),
            "os": platform.system(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "registered_at": time.time(),
        }
        return self._post("/api/agent-register", data)

    def _post(self, path, data):
        url = f"{self.base_url}{path}"
        try:
            resp = requests.post(
                url, json=data, headers=self.headers,
                timeout=self.timeout, verify=self.verify
            )
            resp.raise_for_status()
            logger.info(f"POST {path}: {resp.status_code}")
            self._consecutive_failures = 0
            return {"status": "ok", "code": resp.status_code, "data": resp.json() if resp.text else {}}
        except requests.RequestException as e:
            self._consecutive_failures += 1
            logger.error(
                f"POST {path} failed ({self._consecutive_failures} consecutive failures, "
                f"next retry backoff {self.backoff_seconds}s): {e}"
            )
            if self.retry_queue:
                self.retry_queue.enqueue(data)
            return {"status": "error", "error": str(e)}

    def _get(self, path):
        url = f"{self.base_url}{path}"
        try:
            resp = requests.get(url, headers=self.headers, timeout=self.timeout, verify=self.verify)
            resp.raise_for_status()
            self._consecutive_failures = 0
            return resp.json() if resp.text else {}
        except requests.RequestException as e:
            self._consecutive_failures += 1
            logger.error(f"GET {path} failed: {e}")
            return None

    def flush_retry_queue(self):
        if not self.retry_queue:
            return
        batch = self.retry_queue.dequeue(batch_size=50)
        if not batch:
            return
        logger.info(f"Flushing {len(batch)} entries from retry queue")
        failed = []
        for entry in batch:
            result = self._post("/api/metrics", entry["payload"])
            if result["status"] != "ok":
                failed.append(entry)
        if failed:
            self.retry_queue.requeue(failed)
