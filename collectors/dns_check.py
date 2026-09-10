import time
import socket
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

try:
    import dns.resolver
    HAS_DNSPYTHON = True
except ImportError:
    HAS_DNSPYTHON = False


def _check_one(target):
    domain = target.get("domain", "")
    record_type = target.get("type", "A")
    expected = target.get("expected", None)
    timeout = target.get("timeout", 5)

    result = {
        "domain": domain,
        "record_type": record_type,
        "expected": expected,
        "resolved": None,
        "response_time_ms": 0,
        "status": "error",
    }

    start = time.time()

    if HAS_DNSPYTHON:
        try:
            resolver = dns.resolver.Resolver()
            resolver.timeout = timeout
            resolver.lifetime = timeout
            answers = resolver.resolve(domain, record_type)
            resolved = [str(r) for r in answers]
            elapsed = (time.time() - start) * 1000
            result["resolved"] = resolved
            result["response_time_ms"] = round(elapsed, 2)
            if expected and expected in resolved:
                result["status"] = "ok"
            elif expected and expected not in resolved:
                result["status"] = "mismatch"
            else:
                result["status"] = "ok"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            result["response_time_ms"] = round((time.time() - start) * 1000, 2)
    else:
        try:
            resolved = socket.getaddrinfo(domain, None)
            elapsed = (time.time() - start) * 1000
            addresses = list(set(r[4][0] for r in resolved))
            result["resolved"] = addresses
            result["response_time_ms"] = round(elapsed, 2)
            if expected and expected in addresses:
                result["status"] = "ok"
            elif expected:
                result["status"] = "mismatch"
            else:
                result["status"] = "ok"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            result["response_time_ms"] = round((time.time() - start) * 1000, 2)

    return result


def get_dns_check(targets=None):
    """Runs configured DNS checks concurrently rather than one at a time,
    so a handful of slow/unresponsive resolvers don't serialize into
    N * timeout seconds for a single collection cycle."""
    if targets is None:
        targets = []
    if not targets:
        return []

    results = [None] * len(targets)
    with ThreadPoolExecutor(max_workers=min(16, len(targets))) as pool:
        futures = {pool.submit(_check_one, t): i for i, t in enumerate(targets)}
        for future in futures:
            i = futures[future]
            results[i] = future.result()

    return results
