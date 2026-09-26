import os
import sys
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

# Windows event log support is optional - pywin32 may not be installed,
# and it's obviously not importable on Linux/macOS at all.
IS_WINDOWS = sys.platform.startswith("win")
try:
    import win32evtlog
    import win32evtlogutil
    HAS_WIN32EVTLOG = True
except ImportError:
    HAS_WIN32EVTLOG = False
    if IS_WINDOWS:
        logger.warning(
            "pywin32 not installed - Windows Event Log monitoring disabled. "
            "Install it with: pip install pywin32"
        )


# Windows event levels -> severity names (mirrors Windows' own mapping)
_WIN_EVENT_LEVELS = {
    1: "critical",
    2: "error",
    3: "warning",
    4: "information",
    5: "verbose",
}

# Map config pattern keywords onto Windows event levels so users can
# keep using patterns like "error"/"critical" on Windows too.
_PATTERN_TO_LEVEL = {
    "critical": 1,
    "error": 2,
    "warning": 3,
    "warn": 3,
    "information": 4,
    "info": 4,
    "verbose": 5,
}


class LogMonitor:
    """Tails plain-text log files on Linux/macOS and reads Windows Event
    Logs on Windows. Configured via the `log_monitor` list in config.yaml.

    Each entry supports:
        path:      file path (Linux/macOS) OR event log name like
                   "Application", "System", "Security", OR the full
                   ".evtx" path (the event log name is derived from it).
        patterns:  list of substrings to match (case-insensitive).
        max_lines: size of the recent-lines ring buffer.
        type:      optional explicit "file" | "eventlog". Auto-detected
                   from the path if omitted.
    """

    def __init__(self, log_configs=None):
        if log_configs is None:
            log_configs = []
        self.watchers = {}

        for cfg in log_configs:
            path = (cfg.get("path") or "").strip()
            if not path:
                continue

            patterns = cfg.get("patterns", []) or []
            max_lines = cfg.get("max_lines", 100)
            entry_type = cfg.get("type") or self._detect_type(path)

            if entry_type == "eventlog":
                watcher = self._init_eventlog_watcher(path, patterns, max_lines)
            else:
                watcher = self._init_file_watcher(path, patterns, max_lines)

            if watcher is not None:
                self.watchers[path] = watcher

        if self.watchers:
            logger.info(
                "LogMonitor initialized with %d watcher(s): %s",
                len(self.watchers), list(self.watchers.keys()),
            )
        else:
            logger.warning("LogMonitor initialized with 0 active watchers")

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_type(path):
        if path.lower().endswith(".evtx"):
            return "eventlog"
        # Bare names like "Application" / "System" / "Security" with no
        # separators and no extension are treated as Windows event logs.
        if IS_WINDOWS and os.sep not in path and "/" not in path \
                and "." not in os.path.basename(path):
            return "eventlog"
        return "file"

    def _init_file_watcher(self, path, patterns, max_lines):
        if not os.path.exists(path):
            logger.warning("Log file does not exist, skipping: %s", path)
            return None
        if not os.access(path, os.R_OK):
            logger.warning("Log file not readable (permissions?), skipping: %s", path)
            return None
        try:
            st = os.stat(path)
        except OSError as e:
            logger.warning("Cannot stat log file %s: %s", path, e)
            return None

        return {
            "type": "file",
            "patterns": patterns,
            "max_lines": max_lines,
            # Start at 0 so we catch pre-existing matching lines on the
            # first run. Change to st.st_size if you only want new lines.
            "last_pos": 0,
            "inode": st.st_ino,
            "recent_lines": deque(maxlen=max_lines),
        }

    def _init_eventlog_watcher(self, path, patterns, max_lines):
        if not IS_WINDOWS:
            logger.warning(
                "Event log '%s' configured but this is not Windows, skipping", path
            )
            return None
        if not HAS_WIN32EVTLOG:
            logger.warning(
                "Event log '%s' configured but pywin32 is not installed, skipping", path
            )
            return None

        log_name = self._eventlog_name_from_path(path)
        try:
            handle = win32evtlog.OpenEventLog(None, log_name)
            oldest = win32evtlog.GetOldestEventLogRecord(handle)
            total = win32evtlog.GetNumberOfEventLogRecords(handle)
            # Record numbers are 1-based; "oldest + total - 1" is the most
            # recent record. We start just past it so only new events are
            # collected on the first run.
            last_record = oldest + total - 1 if total > 0 else 0
            win32evtlog.CloseEventLog(handle)
        except Exception as e:
            logger.warning("Cannot open Windows event log '%s': %s", log_name, e)
            return None

        return {
            "type": "eventlog",
            "log_name": log_name,
            "patterns": patterns,
            "max_lines": max_lines,
            "last_record": last_record,
            "recent_lines": deque(maxlen=max_lines),
        }

    @staticmethod
    def _eventlog_name_from_path(path):
        """Turn a full .evtx path into the log name win32evtlog expects.
        e.g. C:\\Windows\\System32\\winevt\\Logs\\Application.evtx -> 'Application'
        """
        base = os.path.basename(path)
        if base.lower().endswith(".evtx"):
            base = base[:-5]
        return base

    # ------------------------------------------------------------------
    # Main loop entry point
    # ------------------------------------------------------------------

    def check_logs(self):
        results = []
        for path, watcher in self.watchers.items():
            try:
                if watcher["type"] == "eventlog":
                    result = self._check_eventlog(path, watcher)
                else:
                    result = self._check_file(path, watcher)
                results.append(result)
            except Exception as e:
                logger.exception("Log check failed for %s", path)
                results.append({
                    "path": path,
                    "status": "error",
                    "error": str(e),
                })
        return results

    # ------------------------------------------------------------------
    # Text file tailing
    # ------------------------------------------------------------------

    def _check_file(self, path, watcher):
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return {
                "path": path, "status": "error",
                "error": "file disappeared",
            }

        # Detect rotation (new inode) vs truncation (same inode, smaller size)
        if st.st_ino != watcher.get("inode"):
            logger.info("Log rotated (inode changed): %s", path)
            watcher["inode"] = st.st_ino
            watcher["last_pos"] = 0
        elif st.st_size < watcher["last_pos"]:
            logger.info("Log truncated: %s", path)
            watcher["last_pos"] = 0

        if st.st_size == watcher["last_pos"]:
            return {
                "path": path,
                "status": "no_change",
                "new_lines": 0,
                "matched_lines": [],
                "total_matched": 0,
            }

        new_lines = []
        with open(path, "r", errors="replace") as f:
            f.seek(watcher["last_pos"])
            for line in f:
                new_lines.append(line.rstrip())
            watcher["last_pos"] = f.tell()

        matched = self._match_lines(watcher, new_lines)

        logger.debug(
            "Log check %s: %d new line(s), %d matched",
            path, len(new_lines), len(matched),
        )
        return {
            "path": path,
            "status": "ok",
            "new_lines": len(new_lines),
            "matched_lines": matched[:50],
            "total_matched": len(matched),
        }

    def _match_lines(self, watcher, lines):
        matched = []
        for line in lines:
            watcher["recent_lines"].append(line)
            for pattern in watcher["patterns"]:
                if pattern.lower() in line.lower():
                    matched.append({"line": line, "matched_pattern": pattern})
                    break
        return matched

    # ------------------------------------------------------------------
    # Windows Event Log reading
    # ------------------------------------------------------------------

    def _check_eventlog(self, path, watcher):
        log_name = watcher["log_name"]
        flags = (
            win32evtlog.EVENTLOG_FORWARDS_READ
            | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        )

        try:
            handle = win32evtlog.OpenEventLog(None, log_name)
        except Exception as e:
            return {
                "path": path, "status": "error",
                "error": f"cannot open event log '{log_name}': {e}",
            }

        new_lines = []
        last_seen = watcher["last_record"]
        try:
            while True:
                events = win32evtlog.ReadEventLog(handle, flags, 0)
                if not events:
                    break
                for event in events:
                    record_num = event.RecordNumber
                    if record_num <= last_seen:
                        continue
                    line = self._format_event(event)
                    new_lines.append(line)
                    last_seen = record_num
        finally:
            win32evtlog.CloseEventLog(handle)

        watcher["last_record"] = last_seen

        if not new_lines:
            return {
                "path": path,
                "status": "no_change",
                "new_lines": 0,
                "matched_lines": [],
                "total_matched": 0,
            }

        matched = self._match_event_lines(watcher, new_lines)

        logger.debug(
            "Event log check %s: %d new event(s), %d matched",
            log_name, len(new_lines), len(matched),
        )
        return {
            "path": path,
            "status": "ok",
            "new_lines": len(new_lines),
            "matched_lines": matched[:50],
            "total_matched": len(matched),
        }

    def _format_event(self, event):
        """Render one Windows event into a single log line."""
        level_num = event.EventType
        # win32evtlog maps EVENTLOG_ERROR_TYPE etc into EventType, but
        # those constants don't line up with the 1..5 scale. Normalize.
        try:
            level = {
                win32evtlog.EVENTLOG_ERROR_TYPE: "error",
                win32evtlog.EVENTLOG_WARNING_TYPE: "warning",
                win32evtlog.EVENTLOG_INFORMATION_TYPE: "information",
                win32evtlog.EVENTLOG_AUDIT_SUCCESS: "audit_success",
                win32evtlog.EVENTLOG_AUDIT_FAILURE: "audit_failure",
            }.get(level_num, f"type_{level_num}")
        except Exception:
            level = f"type_{level_num}"

        try:
            ts = event.TimeGenerated.Format()
        except Exception:
            ts = ""

        source = event.SourceName or ""
        event_id = event.EventID & 0xFFFF  # strip qualifier bits

        message = ""
        try:
            message = win32evtlogutil.SafeFormatMessage(event, watcher_log_name=None) \
                if False else win32evtlogutil.SafeFormatMessage(event, "")
        except Exception:
            # Fall back to the raw inserts if SafeFormatMessage fails
            message = " ".join(str(s) for s in (event.StringInserts or ()))

        message = " ".join(message.split())  # collapse newlines/whitespace

        return (
            f"{ts} [{level}] {source} (EventID={event_id}) {message}"
        ).strip()

    def _match_event_lines(self, watcher, lines):
        """Match event lines, honoring the extra convenience that a
        pattern named after an event level (error/critical/warning/etc.)
        matches any event of that level even if the word isn't in the
        rendered message."""
        matched = []
        for line in lines:
            watcher["recent_lines"].append(line)
            line_lower = line.lower()
            for pattern in watcher["patterns"]:
                p = pattern.lower()
                if p in line_lower:
                    matched.append({"line": line, "matched_pattern": pattern})
                    break
                # e.g. pattern "error" also matches "[error]" events
                if p in _PATTERN_TO_LEVEL:
                    level_name = _WIN_EVENT_LEVELS.get(_PATTERN_TO_LEVEL[p])
                    if level_name and f"[{level_name}]" in line_lower:
                        matched.append({"line": line, "matched_pattern": pattern})
                        break
        return matched
