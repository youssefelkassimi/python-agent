import psutil


def get_memory_metrics():
    virt = psutil.virtual_memory()
    swap = psutil.swap_memory()

    return {
        "total_bytes": virt.total,
        "available_bytes": virt.available,
        "used_bytes": virt.used,
        "percent": virt.percent,
        "buffers": getattr(virt, "buffers", 0),
        "cached": getattr(virt, "cached", 0),
        "active": getattr(virt, "active", 0),
        "inactive": getattr(virt, "inactive", 0),
        "wired": getattr(virt, "wired", 0),
        "shared": getattr(virt, "shared", 0),
        "swap_total": swap.total,
        "swap_used": swap.used,
        "swap_free": swap.free,
        "swap_percent": swap.percent,
    }
