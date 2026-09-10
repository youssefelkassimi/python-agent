import os
import time
import threading
import psutil

_process = psutil.Process(os.getpid())
_start_time = time.time()


def get_agent_self_metrics(cycle_count=None, cycle_errors=None, last_cycle_duration_ms=None):
    """Reports the agent's own resource usage.

    Handy for catching an agent that's leaking memory, a plugin that's
    spinning up threads without cleaning them up, or a collector that's
    slowly getting slower over time.
    """
    with _process.oneshot():
        mem = _process.memory_info()
        cpu_percent = _process.cpu_percent(interval=None)
        num_threads = _process.num_threads()
        try:
            num_fds = _process.num_fds()
        except AttributeError:
            # num_fds() isn't available on Windows
            num_fds = None

    return {
        "pid": _process.pid,
        "uptime_seconds": round(time.time() - _start_time, 1),
        "cpu_percent": cpu_percent,
        "rss_bytes": mem.rss,
        "vms_bytes": mem.vms,
        "num_threads": num_threads,
        "num_fds": num_fds,
        "active_threads": threading.active_count(),
        "cycle_count": cycle_count,
        "cycle_errors": cycle_errors,
        "last_cycle_duration_ms": last_cycle_duration_ms,
    }
