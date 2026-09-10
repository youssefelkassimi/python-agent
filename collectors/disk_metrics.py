import psutil


def get_disk_usage_metrics():
    partitions = psutil.disk_partitions(all=False)
    result = []
    for p in partitions:
        try:
            usage = psutil.disk_usage(p.mountpoint)
            result.append({
                "device": p.device,
                "mountpoint": p.mountpoint,
                "fstype": p.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent": usage.percent,
            })
        except PermissionError:
            continue
    return result


def get_disk_io_metrics(prev_counters=None, interval=1.0):
    io = psutil.disk_io_counters(perdisk=True)
    metrics = {}
    for disk_name, counters in io.items():
        entry = {
            "read_bytes": counters.read_count,
            "write_bytes": counters.write_count,
            "read_count": counters.read_count,
            "write_count": counters.write_count,
            "read_time_ms": counters.read_time,
            "write_time_ms": counters.write_time,
        }
        if prev_counters and disk_name in prev_counters:
            prev = prev_counters[disk_name]
            entry["read_bytes_per_sec"] = (counters.read_bytes - prev.read_bytes) / interval
            entry["write_bytes_per_sec"] = (counters.write_bytes - prev.write_bytes) / interval
        metrics[disk_name] = entry
    return metrics, io
