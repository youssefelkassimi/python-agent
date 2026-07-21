import requests
import logging

class MetricSender:
    def __init__(self, backend_url, agent_id, api_key=None):
        self.endpoint = f"{backend_url}/api/metrics"
        self.agent_id = agent_id
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def send(self, payload: dict):
        payload["agentId"] = self.agent_id
        try:
            resp = requests.post(self.endpoint, json=payload, headers=self.headers, timeout=5)
            resp.raise_for_status()
            logging.info(f"Metrics sent: {resp.status_code}")
        except requests.RequestException as e:
            logging.error(f"Failed to send metrics: {e}")
