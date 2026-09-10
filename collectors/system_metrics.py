from collectors.cpu_metrics import get_cpu_metrics
from collectors.memory_metrics import get_memory_metrics
from collectors.disk_metrics import get_disk_usage_metrics
import psutil


def get_system_metrics():
    cpu = get_cpu_metrics()
    memory = get_memory_metrics()
    disk = get_disk_usage_metrics()

    return {
        "cpu_percent": cpu["cpu_percent"],
        "memory_percent": memory["percent"],
        "disk_usage_percent": disk[0]["percent"] if disk else 0,
        "load_avg": cpu.get("load_avg"),
        "cpu": cpu,
        "memory": memory,
        "disk": disk,
    }
