import time
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def _check_one(target):
    url = target.get("url", "")
    method = target.get("method", "GET")
    expected_status = target.get("expected_status", 200)
    timeout = target.get("timeout", 10)
    headers = target.get("headers", {})
    body = target.get("body", None)
    follow_redirects = target.get("follow_redirects", True)
    ssl_verify = target.get("ssl_verify", True)

    result = {
        "url": url,
        "method": method,
        "expected_status": expected_status,
        "status_code": None,
        "response_time_ms": 0,
        "response_size_bytes": 0,
        "status": "error",
    }

    if not HAS_REQUESTS:
        result["status"] = "error"
        result["error"] = "requests library not installed"
        return result

    start = time.time()
    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            data=body,
            timeout=timeout,
            allow_redirects=follow_redirects,
            verify=ssl_verify,
        )
        elapsed = (time.time() - start) * 1000
        result["status_code"] = resp.status_code
        result["response_time_ms"] = round(elapsed, 2)
        result["response_size_bytes"] = len(resp.content)

        if resp.status_code == expected_status:
            result["status"] = "ok"
        else:
            result["status"] = "unexpected_status"

    except requests.Timeout:
        result["status"] = "timeout"
        result["response_time_ms"] = round((time.time() - start) * 1000, 2)
    except requests.ConnectionError as e:
        result["status"] = "connection_error"
        result["error"] = str(e)
        result["response_time_ms"] = round((time.time() - start) * 1000, 2)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["response_time_ms"] = round((time.time() - start) * 1000, 2)

    return result


def get_http_check(targets=None):
    """Runs configured HTTP checks concurrently.

    Run sequentially, N targets can add up to N * timeout seconds to a
    single collection cycle if several endpoints are slow or timing out.
    Running them concurrently bounds the whole check to roughly the
    slowest single target's timeout instead.
    """
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
