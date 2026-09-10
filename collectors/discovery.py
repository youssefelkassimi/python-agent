import socket
import subprocess
import sys
import logging
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Hard safety cap: never let a misconfigured "subnets: null" auto-detect
# blow up into scanning something huge like a /8 by accident.
MAX_HOSTS_PER_SCAN = 4096
DEFAULT_MAX_WORKERS = 64


def _get_local_subnets():
    subnets = []
    for name, addrs in __import__("psutil").net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address and addr.netmask:
                try:
                    network = ipaddress.IPv4Network(f"{addr.address}/{addr.netmask}", strict=False)
                    if not network.is_loopback:
                        subnets.append(str(network))
                except ValueError:
                    continue
    return subnets


def _ping_host(ip_str, timeout=1):
    param = "-n" if sys.platform == "win32" else "-c"
    timeout_param = "-w" if sys.platform == "win32" else "-W"
    # Windows -w takes milliseconds, POSIX -W takes seconds.
    timeout_value = str(int(timeout * 1000)) if sys.platform == "win32" else str(timeout)
    try:
        result = subprocess.run(
            ["ping", param, "1", timeout_param, timeout_value, ip_str],
            capture_output=True, timeout=timeout + 2
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_port(ip_str, port, timeout=2):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip_str, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _scan_host(ip_str, ports, timeout):
    if not _ping_host(ip_str, timeout):
        return None
    open_ports = [port for port in ports if _check_port(ip_str, port, timeout=1)]
    return {"ip": ip_str, "status": "up", "open_ports": open_ports}


def discover_network(subnets=None, ports=None, timeout=1, max_workers=DEFAULT_MAX_WORKERS):
    """Ping-sweep + port-scan configured subnets.

    Runs host scans concurrently via a thread pool instead of sequentially,
    since a sequential scan of a /24 (254 hosts * ~1-3s each) can block the
    whole agent's collection loop for minutes.
    """
    if subnets is None:
        subnets = _get_local_subnets()
    if ports is None:
        ports = [22, 80, 443, 3306, 5432, 6379, 8080, 8443]

    all_hosts = []
    for subnet_str in subnets:
        try:
            network = ipaddress.IPv4Network(subnet_str, strict=False)
        except ValueError:
            logger.warning(f"Skipping invalid subnet in discovery config: {subnet_str}")
            continue
        all_hosts.extend(str(ip) for ip in network.hosts())

    truncated = False
    if len(all_hosts) > MAX_HOSTS_PER_SCAN:
        logger.warning(
            f"Discovery would scan {len(all_hosts)} hosts, capping at {MAX_HOSTS_PER_SCAN} "
            f"to avoid an unbounded scan"
        )
        all_hosts = all_hosts[:MAX_HOSTS_PER_SCAN]
        truncated = True

    discovered = []
    if all_hosts:
        with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(all_hosts)))) as pool:
            futures = {pool.submit(_scan_host, ip, ports, timeout): ip for ip in all_hosts}
            for future in as_completed(futures):
                try:
                    host_info = future.result()
                except Exception as e:
                    logger.debug(f"Host scan failed for {futures[future]}: {e}")
                    host_info = None
                if host_info:
                    discovered.append(host_info)

    return {
        "subnets_scanned": subnets,
        "hosts_found": len(discovered),
        "hosts": discovered,
        "truncated": truncated,
    }


def discover_services(ports=None):
    if ports is None:
        ports = {
            22: "ssh", 23: "telnet", 25: "smtp", 53: "dns",
            80: "http", 110: "pop3", 143: "imap", 443: "https",
            993: "imaps", 995: "pop3s", 3306: "mysql", 3389: "rdp",
            5432: "postgresql", 6379: "redis", 8080: "http-alt",
            8443: "https-alt", 27017: "mongodb",
        }

    local_ip = socket.gethostbyname(socket.gethostname())
    results = []
    with ThreadPoolExecutor(max_workers=min(16, len(ports))) as pool:
        futures = {
            pool.submit(_check_port, local_ip, port, 1): (port, name)
            for port, name in ports.items()
        }
        for future in as_completed(futures):
            port, service_name = futures[future]
            try:
                is_open = future.result()
            except Exception:
                is_open = False
            results.append({
                "port": port,
                "service": service_name,
                "status": "open" if is_open else "closed",
            })

    results.sort(key=lambda r: r["port"])
    return {
        "host": local_ip,
        "services": results,
    }
