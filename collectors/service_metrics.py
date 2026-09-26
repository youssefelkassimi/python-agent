import psutil
import subprocess
import sys
import logging

logger = logging.getLogger(__name__)


def _check_windows_service(name):
    try:
        result = subprocess.run(
            ["sc.exe", "query", name],
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


# Map service platform -> local runtime platform
_PLATFORM_ALIASES = {
    "win32": "win32",
    "windows": "win32",
    "linux": "linux",
}


def _local_platform():
    if sys.platform == "win32":
        return "win32"
    return "linux"  # treat everything else as linux for systemctl


def get_service_metrics(services=None):
    if services is None:
        services = []

    local = _local_platform()
    results = []

    for svc in services:
        if isinstance(svc, str):
            # Backward compat: bare string, infer platform from local host
            name = svc
            platform = local
        else:
            name = svc.get("name")
            platform = _PLATFORM_ALIASES.get(
                (svc.get("platform") or "").lower(), local
            )

        if not name:
            continue

        # Skip services that don't belong to this platform
        if platform != local:
            # results.append({
            #     "name": name,
            #     "platform": platform,
            #     "status": "skipped",
            #     "reason": f"service is for {platform}, host is {local}",
            # })
            continue

        if local == "win32":
            status = _check_windows_service(name)
        else:
            status = _check_linux_service(name)

        results.append({
            "name": name,
            "platform": platform,
            "status": status,
        })

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
