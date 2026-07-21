import psutil

def get_system_metrics():
    return{
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_usage_percent": psutil.disk_usage('c').percent,
        "load_avg": psutil.getloadavg() if hasattr(psutil, "getloadavg") else None,

    }
