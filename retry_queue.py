import json
import os
import time
import logging
import threading

logger = logging.getLogger(__name__)


class RetryQueue:
    def __init__(self, max_size=1000, persist_path=None):
        self.max_size = max_size
        self.persist_path = persist_path
        self.queue = []
        self.lock = threading.Lock()

        if persist_path and os.path.exists(persist_path):
            self._load()

    def enqueue(self, payload):
        with self.lock:
            entry = {
                "payload": payload,
                "timestamp": time.time(),
                "retries": 0,
            }
            if len(self.queue) >= self.max_size:
                self.queue.pop(0)
            self.queue.append(entry)
            self._save()

    def dequeue(self, batch_size=10):
        with self.lock:
            batch = self.queue[:batch_size]
            self.queue = self.queue[batch_size:]
            self._save()
            return batch

    def requeue(self, entries):
        with self.lock:
            for entry in entries:
                entry["retries"] += 1
                if entry["retries"] < 5:
                    self.queue.insert(0, entry)
            self._save()

    def size(self):
        with self.lock:
            return len(self.queue)

    def clear(self):
        with self.lock:
            self.queue = []
            self._save()

    def get_stats(self):
        with self.lock:
            return {
                "queue_size": len(self.queue),
                "oldest_entry_age": (time.time() - self.queue[0]["timestamp"]) if self.queue else 0,
            }

    def _save(self):
        if not self.persist_path:
            return
        try:
            with open(self.persist_path, "w") as f:
                json.dump(self.queue, f)
        except Exception as e:
            logger.error(f"Failed to persist retry queue: {e}")

    def _load(self):
        try:
            with open(self.persist_path, "r") as f:
                self.queue = json.load(f)
                logger.info(f"Loaded {len(self.queue)} entries from retry queue")
        except Exception as e:
            logger.warning(f"Failed to load retry queue: {e}")
            self.queue = []
