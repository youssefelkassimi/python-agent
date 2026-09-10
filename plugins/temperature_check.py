PLUGIN_NAME = "temperature_check"
PLUGIN_DESCRIPTION = "Reports CPU temperature if available via psutil"
PLUGIN_INTERVAL = 30


def collect():
    import psutil

    temps = None
    try:
        temp_data = psutil.sensors_temperatures()
        if temp_data:
            temps = {}
            for name, entries in temp_data.items():
                temps[name] = [
                    {"label": e.label or name, "current": e.current, "high": e.high, "critical": e.critical}
                    for e in entries
                ]
    except (AttributeError, Exception):
        pass

    return {
        "available": temps is not None,
        "temperatures": temps,
    }
