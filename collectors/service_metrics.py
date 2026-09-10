import psutil
import subprocess
import sys
import logging

logger = logging.getLogger(__name__)


def _check_windows_service(name):
    try:
        result = subprocess.run(
            ["sc", "query", name],
            capture_output=True, text=True, timeout=10
        )
        if "RUNNING" in result.stdout:
            return "running"
        elif "STOPPED" in result.stdout:
            return "stopped"
        return "unknown"
    except Exception:
        return "error"


def _check_linux_service(name):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return "error"


def get_service_metrics(services=None):
    if services is None:
        services = []

    results = []
    is_windows = sys.platform == "win32"

    for svc in services:
        if is_windows:
            status = _check_windows_service(svc)
        else:
            status = _check_linux_service(svc)
        results.append({"name": svc, "status": status})

    running_procs = {}
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info["name"]
            running_procs[name] = running_procs.get(name, 0) + 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return {
        "monitored_services": results,
        "running_processes": running_procs,
    }
