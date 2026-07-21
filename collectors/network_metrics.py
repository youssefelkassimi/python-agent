import psutil
import time

def get_network_metrics(prev_counters=None, interval=1.0):
    counters = psutil.net_io_counters()
    connections = len(psutil.net_io_connections(kind='inet'))

    metrics = {
        "bytes_sent": counters.bytes_sent,
        "bytes_recv": counters.bytes_recv,
        "packets_sent": counters.packets_sent,
        "packets_recv": counters.packets_recv,
        "active_connections": connections,
    }

    if prev_counters:
        metrics["bandwidth_sent_bps"] = (counters.bytes_sent - prev_counters.bytes_sent)/interval
        metrics["bandwidth_recv_bps"] = (counters.bytes_recv - prev_counters.bytes_recv) / interval
    return metrics, counters
