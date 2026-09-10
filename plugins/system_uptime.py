import time
import platform

PLUGIN_NAME = "system_uptime"
PLUGIN_DESCRIPTION = "Reports system uptime and boot time"
PLUGIN_INTERVAL = 30


def collect():
    import psutil
    boot_time = psutil.boot_time()
    uptime = time.time() - boot_time
    days = int(uptime // 86400)
    hours = int((uptime % 86400) // 3600)
    minutes = int((uptime % 3600) // 60)

    return {
        "boot_time": boot_time,
        "uptime_seconds": int(uptime),
        "uptime_human": f"{days}d {hours}h {minutes}m",
        "hostname": platform.node(),
        "platform": platform.system(),
    }
