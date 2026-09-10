import shutil
import subprocess
import json
import logging

logger = logging.getLogger(__name__)

_DOCKER = shutil.which("docker")


def get_docker_metrics():
    """Reports running-container counts and per-container resource usage.

    Uses the `docker` CLI directly (no extra dependency on the docker SDK)
    so this collector stays optional and lightweight. Returns
    {"available": False} on hosts without Docker installed or reachable.
    """
    if not _DOCKER:
        return {"available": False, "containers": []}

    try:
        ps = subprocess.run(
            [_DOCKER, "ps", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=10,
        )
        if ps.returncode != 0:
            return {"available": False, "containers": [], "error": ps.stderr.strip()}

        container_ids = []
        basic_info = {}
        for line in ps.stdout.strip().splitlines():
            if not line:
                continue
            try:
                info = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = info.get("ID")
            if cid:
                container_ids.append(cid)
                basic_info[cid] = {
                    "id": cid,
                    "name": info.get("Names"),
                    "image": info.get("Image"),
                    "status": info.get("Status"),
                    "state": info.get("State"),
                }

        containers = list(basic_info.values())

        if container_ids:
            stats = subprocess.run(
                [_DOCKER, "stats", "--no-stream", "--format", "{{json .}}"] + container_ids,
                capture_output=True, text=True, timeout=15,
            )
            if stats.returncode == 0:
                for line in stats.stdout.strip().splitlines():
                    if not line:
                        continue
                    try:
                        s = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    cid = s.get("ID")
                    if cid in basic_info:
                        basic_info[cid].update({
                            "cpu_percent": _parse_percent(s.get("CPUPerc")),
                            "mem_percent": _parse_percent(s.get("MemPerc")),
                            "mem_usage": s.get("MemUsage"),
                            "net_io": s.get("NetIO"),
                            "block_io": s.get("BlockIO"),
                            "pids": s.get("PIDs"),
                        })
            containers = list(basic_info.values())

        return {
            "available": True,
            "container_count": len(containers),
            "containers": containers,
        }
    except Exception as e:
        logger.debug(f"Docker metrics collection failed: {e}")
        return {"available": False, "containers": [], "error": str(e)}


def _parse_percent(value):
    if not value:
        return None
    try:
        return float(str(value).strip().rstrip("%"))
    except ValueError:
        return None
