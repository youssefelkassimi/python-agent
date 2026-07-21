import time
import yaml
import logging
from collectors.system_metrics import get_system_metrics
from collectors.network_metrics import get_network_metrics
from sender import MetricSender

logging.basicConfig(level=logging.INFO)

def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)

def main():
    config = load_config("config.yaml")
    sender = MetricSender(config["backend_url"], config["agent_id"], config.get("api_key"))
    print('config: {config}')

    interval = config.get("interval_seconds", 5)

    prev_counters = None
    while True:
        system_metrics = get_system_metrics()
        network_metrics, prev_counters = get_network_metrics(prev_counters, interval)

        payload = {
            "timestamp": time.time(),
            "system": system_metrics,
            "network": network_metrics,
        }
        print(payload)
        sender.send(payload)
        time.sleep(interval)

if __name__ == "__main__":
    main()


