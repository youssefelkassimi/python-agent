import os
import shutil
import subprocess
import logging
import time
import threading

logger = logging.getLogger(__name__)


class RemoteCommandHandler:
    """Executes allow-listed commands requested by the backend.

    Security notes:
    - Commands are matched by basename against `allowed_commands`, so
      passing an absolute/relative path (e.g. "/usr/bin/ping" or
      "../../bin/ping") can't be used to sneak past the allow list -
      the basename is what's checked either way.
    - subprocess is always invoked with a list (never shell=True), so
      shell metacharacters in `command` or `args` are never interpreted
      by a shell.
    - The resolved executable must exist on PATH (via shutil.which);
      if `command` isn't an allow-listed name, or resolution fails,
      execution is refused.
    - A simple token-bucket rate limit avoids a compromised/misbehaving
      backend from hammering the host with command executions.
    """

    def __init__(self, allowed_commands=None, max_output_bytes=1048576,
                 max_commands_per_minute=30):
        if allowed_commands is None:
            allowed_commands = []
        self.allowed_commands = {cmd.lower() for cmd in allowed_commands}
        self.max_output_bytes = max_output_bytes
        self.command_log = []
        self._lock = threading.Lock()
        self._max_per_minute = max_commands_per_minute
        self._recent_timestamps = []

    def _rate_limited(self):
        now = time.time()
        with self._lock:
            self._recent_timestamps = [t for t in self._recent_timestamps if now - t < 60]
            if len(self._recent_timestamps) >= self._max_per_minute:
                return True
            self._recent_timestamps.append(now)
            return False

    def _is_allowed(self, command):
        basename = os.path.basename(command).lower()
        # Strip a .exe suffix so the same allow list works cross-platform.
        if basename.endswith(".exe"):
            basename = basename[:-4]
        if not self.allowed_commands:
            return False, basename
        return basename in self.allowed_commands, basename

    def execute(self, command_id, command, args=None, timeout=30):
        result = {
            "command_id": command_id,
            "command": command,
            "args": args,
            "status": "error",
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "executed_at": time.time(),
        }

        if self._rate_limited():
            result["status"] = "rejected"
            result["stderr"] = "Rate limit exceeded for remote command execution"
            logger.warning(f"Rate-limited remote command request: {command}")
            self._log(result)
            return result

        allowed, basename = self._is_allowed(command)
        if not allowed:
            result["stderr"] = f"Command '{basename}' is not in the allowed list"
            logger.warning(f"Blocked remote command: {command}")
            self._log(result)
            return result

        resolved = shutil.which(basename)
        if not resolved:
            result["status"] = "error"
            result["stderr"] = f"Command not found on PATH: {basename}"
            self._log(result)
            return result

        try:
            full_cmd = [resolved]
            if args:
                if isinstance(args, list):
                    full_cmd.extend(str(a) for a in args)
                else:
                    full_cmd.append(str(args))

            proc = subprocess.run(
                full_cmd,
                capture_output=True,
                timeout=timeout,
                text=True,
                shell=False,
            )

            result["stdout"] = proc.stdout[:self.max_output_bytes]
            result["stderr"] = proc.stderr[:self.max_output_bytes]
            result["exit_code"] = proc.returncode
            result["status"] = "success" if proc.returncode == 0 else "error"

        except subprocess.TimeoutExpired:
            result["status"] = "timeout"
            result["stderr"] = f"Command timed out after {timeout}s"
        except FileNotFoundError:
            result["status"] = "error"
            result["stderr"] = f"Command not found: {basename}"
        except Exception as e:
            result["status"] = "error"
            result["stderr"] = str(e)

        self._log(result)
        return result

    def _log(self, result):
        self.command_log.append(result)
        if len(self.command_log) > 100:
            self.command_log = self.command_log[-100:]

    def get_recent_commands(self, limit=20):
        return self.command_log[-limit:]
