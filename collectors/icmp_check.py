import re
import shutil
import subprocess
import sys
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

try:
    from icmplib import multiping
    HAS_ICMPLIB = True
except ImportError:
    HAS_ICMPLIB = False

_PING_BIN = shutil.which("ping")

# Cached after the first probe so we don't re-attempt (and re-log) a broken
# icmplib backend on every single collection cycle. None = not probed yet.
_icmplib_usable = None


def _probe_icmplib():
    """Checks once whether icmplib can actually open ICMP sockets here.

    Some environments (containers without CAP_NET_RAW, sandboxes without
    ping_group_range configured) can't create ICMP sockets even in
    "unprivileged" mode. In that case icmplib raises on every call, so we
    check once up front and fall back to the `ping` binary instead of
    hammering a broken path every cycle.
    """
    global _icmplib_usable
    if _icmplib_usable is not None:
        return _icmplib_usable
    try:
        multiping(["127.0.0.1"], count=1, timeout=1, privileged=False)
        _icmplib_usable = True
    except Exception as e:
        logger.warning(
            f"icmplib is not usable in this environment ({e}); "
            f"falling back to the system 'ping' binary for ICMP checks"
        )
        _icmplib_usable = False
    return _icmplib_usable


def _ping_via_binary(host, count, timeout):
    """Fallback using the system ping command, parsed for rtt/loss stats."""
    result = {
        "host": host, "count": count, "status": "error",
        "min_rtt_ms": 0, "max_rtt_ms": 0, "avg_rtt_ms": 0,
        "packet_loss_percent": 100, "packets_sent": count, "packets_received": 0,
    }
    if not _PING_BIN:
        result["error"] = "no 'ping' binary found on PATH"
        return result

    count_flag = "-n" if sys.platform == "win32" else "-c"
    timeout_flag = "-w" if sys.platform == "win32" else "-W"
    timeout_value = str(int(timeout * 1000)) if sys.platform == "win32" else str(int(timeout))

    try:
        proc = subprocess.run(
            [_PING_BIN, count_flag, str(count), timeout_flag, timeout_value, host],
            capture_output=True, text=True, timeout=(timeout * count) + 5,
        )
        output = proc.stdout

        loss_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:packet\s*)?loss", output)
        if loss_match:
            loss = float(loss_match.group(1))
            result["packet_loss_percent"] = loss
            result["packets_received"] = round(count * (1 - loss / 100))
            result["status"] = "ok" if loss < 100 else "unreachable"

        # Matches both "min/avg/max/mdev = 1.2/2.3/3.4/0.5 ms" (Linux) and
        # "Minimum = 1ms, Maximum = 3ms, Average = 2ms" (Windows).
        rtt_match = re.search(r"=\s*([\d.]+)/([\d.]+)/([\d.]+)", output)
        if rtt_match:
            result["min_rtt_ms"] = float(rtt_match.group(1))
            result["avg_rtt_ms"] = float(rtt_match.group(2))
            result["max_rtt_ms"] = float(rtt_match.group(3))
        elif proc.returncode == 0:
            result["status"] = "ok"

        if not loss_match and proc.returncode != 0:
            result["status"] = "unreachable"

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["error"] = f"ping timed out after {timeout * count + 5}s"
    except Exception as e:
        result["error"] = str(e)

    return result


def get_icmp_check(targets=None):
    if targets is None:
        targets = []
    if not targets:
        return []

    results = []
    hosts = []
    for target in targets:
        host = target.get("host", "")
        count = target.get("count", 3)
        results.append({
            "host": host, "count": count, "status": "error",
            "min_rtt_ms": 0, "max_rtt_ms": 0, "avg_rtt_ms": 0,
            "packet_loss_percent": 100, "packets_sent": count, "packets_received": 0,
        })
        hosts.append(host)

    if HAS_ICMPLIB and _probe_icmplib():
        try:
            ping_results = multiping(
                hosts,
                count=max(t.get("count", 3) for t in targets),
                timeout=max(t.get("timeout", 5) for t in targets),
                privileged=False,
            )
            for r in results:
                host = r["host"]
                if host in ping_results:
                    pr = ping_results[host]
                    r["status"] = "ok" if pr.is_alive else "unreachable"
                    r["min_rtt_ms"] = round(pr.min_rtt, 2) if pr.min_rtt else 0
                    r["max_rtt_ms"] = round(pr.max_rtt, 2) if pr.max_rtt else 0
                    r["avg_rtt_ms"] = round(pr.avg_rtt, 2) if pr.avg_rtt else 0
                    r["packet_loss_percent"] = round(pr.packet_loss, 2)
                    r["packets_sent"] = pr.packets_sent
                    r["packets_received"] = pr.packets_received
            return results
        except Exception as e:
            logger.error(f"icmplib multiping failed despite passing the capability probe: {e}")
            for r in results:
                r["error"] = str(e)
            return results

    # Fall back to the system ping binary, run concurrently across hosts so
    # N targets don't serialize into N * timeout seconds of blocking.
    with ThreadPoolExecutor(max_workers=min(16, max(1, len(targets)))) as pool:
        futures = {
            pool.submit(
                _ping_via_binary, t.get("host", ""), t.get("count", 3), t.get("timeout", 5)
            ): i
            for i, t in enumerate(targets)
        }
        for future in futures:
            i = futures[future]
            try:
                results[i] = future.result()
            except Exception as e:
                results[i]["error"] = str(e)

    return results
