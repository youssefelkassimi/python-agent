import psutil
import time


def get_cpu_metrics():
    per_core = psutil.cpu_percent(interval=0.5, percpu=True)
    freq = psutil.cpu_freq()
    times = psutil.cpu_times_percent(interval=0)
    ctx_switches = psutil.cpu_stats()

    return {
        "cpu_percent": psutil.cpu_percent(interval=0),
        "cpu_count": psutil.cpu_count(),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "per_core_percent": per_core,
        "frequency_current": freq.current if freq else None,
        "frequency_min": freq.min if freq else None,
        "frequency_max": freq.max if freq else None,
        "times_user": times.user,
        "times_system": times.system,
        "times_idle": times.idle,
        "times_iowait": getattr(times, "iowait", None),
        "times_steal": getattr(times, "steal", None),
        "times_irq": getattr(times, "irq", None),
        "ctx_switches": ctx_switches.ctx_switches,
        "interrupts": ctx_switches.interrupts,
        "soft_interrupts": ctx_switches.soft_interrupts,
        "load_avg": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None,
    }
