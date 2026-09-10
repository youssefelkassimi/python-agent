import shutil
import subprocess
import logging

logger = logging.getLogger(__name__)

_NVIDIA_SMI = shutil.which("nvidia-smi")

_QUERY_FIELDS = [
    "index", "name", "utilization.gpu", "utilization.memory",
    "memory.used", "memory.total", "temperature.gpu", "power.draw",
]


def get_gpu_metrics():
    """Reports per-GPU utilization via nvidia-smi, if present.

    Returns {"available": False} on any machine without an NVIDIA GPU /
    driver rather than raising, so this collector is safe to enable
    everywhere and simply reports nothing on CPU-only hosts.
    """
    if not _NVIDIA_SMI:
        return {"available": False, "gpus": []}

    try:
        query = ",".join(_QUERY_FIELDS)
        proc = subprocess.run(
            [_NVIDIA_SMI, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return {"available": False, "gpus": [], "error": proc.stderr.strip()}

        gpus = []
        for line in proc.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != len(_QUERY_FIELDS):
                continue
            values = dict(zip(_QUERY_FIELDS, parts))
            gpus.append({
                "index": int(values["index"]),
                "name": values["name"],
                "utilization_gpu_percent": _to_float(values["utilization.gpu"]),
                "utilization_memory_percent": _to_float(values["utilization.memory"]),
                "memory_used_mb": _to_float(values["memory.used"]),
                "memory_total_mb": _to_float(values["memory.total"]),
                "temperature_c": _to_float(values["temperature.gpu"]),
                "power_draw_w": _to_float(values["power.draw"]),
            })

        return {"available": True, "gpus": gpus}
    except Exception as e:
        logger.debug(f"GPU metrics collection failed: {e}")
        return {"available": False, "gpus": [], "error": str(e)}


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
