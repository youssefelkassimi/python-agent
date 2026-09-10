import psutil


def get_process_metrics():
    processes = []
    for proc in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_percent",
                                      "memory_info", "status", "create_time", "num_threads",
                                      "cmdline"]):
        try:
            info = proc.info
            processes.append({
                "pid": info["pid"],
                "name": info["name"],
                "username": info["username"],
                "cpu_percent": info["cpu_percent"],
                "memory_percent": round(info["memory_percent"], 2) if info["memory_percent"] else 0,
                "memory_rss": info["memory_info"].rss if info["memory_info"] else 0,
                "memory_vms": info["memory_info"].vms if info["memory_info"] else 0,
                "status": info["status"],
                "num_threads": info["num_threads"],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    by_status = {}
    for p in processes:
        s = p["status"]
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "total_count": len(processes),
        "by_status": by_status,
        "top_cpu": sorted(processes, key=lambda x: x["cpu_percent"] or 0, reverse=True)[:10],
        "top_memory": sorted(processes, key=lambda x: x["memory_percent"] or 0, reverse=True)[:10],
    }
