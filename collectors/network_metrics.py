import psutil


def get_network_metrics(prev_counters=None, interval=1.0):
    counters = psutil.net_io_counters()
    per_nic = psutil.net_io_counters(pernic=True)
    interfaces = psutil.net_if_addrs()
    connections = psutil.net_connections(kind="inet")

    nic_details = {}
    for name, nic_counters in per_nic.items():
        entry = {
            "bytes_sent": nic_counters.bytes_sent,
            "bytes_recv": nic_counters.bytes_recv,
            "packets_sent": nic_counters.packets_sent,
            "packets_recv": nic_counters.packets_recv,
            "errin": nic_counters.errin,
            "errout": nic_counters.errout,
            "dropin": nic_counters.dropin,
            "dropout": nic_counters.dropout,
        }
        if name in interfaces:
            entry["addresses"] = [
                {"family": str(a.family), "address": a.address, "netmask": a.netmask}
                for a in interfaces[name]
            ]
        nic_details[name] = entry

    metrics = {
        "total_bytes_sent": counters.bytes_sent,
        "total_bytes_recv": counters.bytes_recv,
        "total_packets_sent": counters.packets_sent,
        "total_packets_recv": counters.packets_recv,
        "total_errin": counters.errin,
        "total_errout": counters.errout,
        "total_dropin": counters.dropin,
        "total_dropout": counters.dropout,
        "active_connections": len(connections),
        "interfaces": nic_details,
    }

    if prev_counters:
        metrics["bandwidth_sent_bps"] = (counters.bytes_sent - prev_counters.bytes_sent) / interval
        metrics["bandwidth_recv_bps"] = (counters.bytes_recv - prev_counters.bytes_recv) / interval

    conn_states = {}
    for c in connections:
        state = c.status if c.status else "UNKNOWN"
        conn_states[state] = conn_states.get(state, 0) + 1
    metrics["connection_states"] = conn_states

    return metrics, counters
