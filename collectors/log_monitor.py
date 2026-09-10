import os
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)


class LogMonitor:
    def __init__(self, log_configs=None):
        if log_configs is None:
            log_configs = []
        self.watchers = {}
        for cfg in log_configs:
            path = cfg.get("path", "")
            patterns = cfg.get("patterns", [])
            max_lines = cfg.get("max_lines", 100)
            if path and os.path.exists(path):
                self.watchers[path] = {
                    "patterns": patterns,
                    "max_lines": max_lines,
                    "last_pos": os.path.getsize(path),
                    "recent_lines": deque(maxlen=max_lines),
                }

    def check_logs(self):
        results = []
        for path, watcher in self.watchers.items():
            try:
                current_size = os.path.getsize(path)
                if current_size < watcher["last_pos"]:
                    watcher["last_pos"] = 0

                if current_size == watcher["last_pos"]:
                    results.append({
                        "path": path,
                        "status": "no_change",
                        "new_lines": 0,
                        "matched_lines": [],
                    })
                    continue

                new_lines = []
                with open(path, "r", errors="replace") as f:
                    f.seek(watcher["last_pos"])
                    for line in f:
                        new_lines.append(line.rstrip())
                    watcher["last_pos"] = f.tell()

                matched = []
                for line in new_lines:
                    watcher["recent_lines"].append(line)
                    for pattern in watcher["patterns"]:
                        if pattern.lower() in line.lower():
                            matched.append({"line": line, "matched_pattern": pattern})
                            break

                results.append({
                    "path": path,
                    "status": "ok",
                    "new_lines": len(new_lines),
                    "matched_lines": matched[:50],
                    "total_matched": len(matched),
                })
            except Exception as e:
                results.append({
                    "path": path,
                    "status": "error",
                    "error": str(e),
                })

        return results
