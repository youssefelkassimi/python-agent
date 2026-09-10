import time
import re
import os
import sys
import signal
import platform
import threading
import logging
import logging.handlers
from concurrent.futures import ThreadPoolExecutor

import yaml

from sender import MetricSender
from retry_queue import RetryQueue
from triggers.engine import TriggerEngine
from plugins.loader import PluginLoader
from remote.commands import RemoteCommandHandler
import health

from collectors.cpu_metrics import get_cpu_metrics
from collectors.memory_metrics import get_memory_metrics
from collectors.disk_metrics import get_disk_usage_metrics, get_disk_io_metrics
from collectors.network_metrics import get_network_metrics
from collectors.process_metrics import get_process_metrics
from collectors.service_metrics import get_service_metrics
from collectors.dns_check import get_dns_check
from collectors.http_check import get_http_check
from collectors.icmp_check import get_icmp_check
from collectors.inventory import get_inventory
from collectors.discovery import discover_network, discover_services
from collectors.log_monitor import LogMonitor
from collectors.agent_self import get_agent_self_metrics
from collectors.gpu_metrics import get_gpu_metrics
from collectors.docker_metrics import get_docker_metrics

_ENV_VAR_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(:-(.*))?\}$")

shutdown_event = threading.Event()


def _expand_env(node):
    """Recursively replaces "${VAR}" / "${VAR:-default}" strings in the
    loaded config with environment variable values, so secrets like
    api_key don't have to be committed to config.yaml in plaintext."""
    if isinstance(node, dict):
        return {k: _expand_env(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_env(v) for v in node]
    if isinstance(node, str):
        m = _ENV_VAR_PATTERN.match(node.strip())
        if m:
            var_name, _, default = m.groups()
            return os.environ.get(var_name, default)
    return node


def load_config(path="config.yaml"):
    with open(path) as f:
        raw = yaml.safe_load(f)
    return _expand_env(raw)


def setup_logging(config):
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)

    if log_cfg.get("json", False):
        fmt = logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": "%(message)s"}'
        )
    else:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root_logger.addHandler(console)

    log_file = log_cfg.get("file")
    if log_file:
        fh = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=log_cfg.get("max_bytes", 10 * 1024 * 1024),
            backupCount=log_cfg.get("backup_count", 5),
        )
        fh.setFormatter(fmt)
        root_logger.addHandler(fh)

    return logging.getLogger("agent")


def _install_signal_handlers(logger):
    def _handle(signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle)
    # SIGTERM isn't available on Windows in the same way, guard just in case.
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle)


def _run_io_checks(config, logger):
    """Runs DNS/HTTP/ICMP/service checks concurrently rather than one after
    another, since each check can involve several seconds of network
    timeout waiting."""
    checks = {}
    tasks = {}

    services = config.get("services", [])
    if services:
        tasks["services"] = lambda: get_service_metrics(services)

    dns_targets = config.get("dns_checks", [])
    if dns_targets:
        tasks["dns"] = lambda: get_dns_check(dns_targets)

    http_targets = config.get("http_checks", [])
    if http_targets:
        tasks["http"] = lambda: get_http_check(http_targets)

    icmp_targets = config.get("icmp_checks", [])
    if icmp_targets:
        tasks["icmp"] = lambda: get_icmp_check(icmp_targets)

    if not tasks:
        return checks

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {pool.submit(fn): name for name, fn in tasks.items()}
        for future in futures:
            name = futures[future]
            try:
                checks[name] = future.result()
            except Exception as e:
                logger.error(f"Check '{name}' failed: {e}")
                checks[name] = {"error": str(e)}

    return checks


def _discovery_loop(config, sender, logger):
    """Runs LLD-style discovery on its own timer in a background thread so
    a slow subnet scan never blocks metric collection or heartbeats."""
    disc_cfg = config.get("discovery", {})
    interval = config.get("intervals", {}).get("discovery", 600)

    while not shutdown_event.is_set():
        try:
            if disc_cfg.get("network", {}).get("enabled", False):
                logger.info("Running network discovery...")
                net_disc = discover_network(
                    subnets=disc_cfg["network"].get("subnets"),
                    ports=disc_cfg["network"].get("ports"),
                    timeout=disc_cfg["network"].get("timeout", 1),
                )
                sender.send_discovery(net_disc)
                logger.info(f"Discovery found {net_disc['hosts_found']} live hosts")
            if disc_cfg.get("services", {}).get("enabled", False):
                svc_disc = discover_services(ports=disc_cfg["services"].get("ports"))
                sender.send_discovery(svc_disc)
        except Exception as e:
            logger.error(f"Discovery cycle error: {e}", exc_info=True)

        shutdown_event.wait(interval)


def _remote_command_loop(config, sender, logger):
    """Polls the backend for pending commands and executes allow-listed
    ones, reporting results back. Disabled unless remote_commands.enabled
    is explicitly set."""
    rc_cfg = config.get("remote_commands", {})
    if not rc_cfg.get("enabled", False):
        return

    poll_interval = rc_cfg.get("poll_interval", 15)
    handler = RemoteCommandHandler(
        allowed_commands=rc_cfg.get("allowed_commands", []),
        max_output_bytes=rc_cfg.get("max_output_bytes", 1048576),
        max_commands_per_minute=rc_cfg.get("max_commands_per_minute", 30),
    )

    logger.info(
        f"Remote command execution enabled (allowed: {sorted(handler.allowed_commands)})"
    )

    while not shutdown_event.is_set():
        try:
            pending = sender.fetch_commands()
            if pending:
                commands = pending.get("commands", []) if isinstance(pending, dict) else []
                for cmd in commands:
                    result = handler.execute(
                        command_id=cmd.get("id"),
                        command=cmd.get("command", ""),
                        args=cmd.get("args"),
                        timeout=cmd.get("timeout", 30),
                    )
                    sender.send_command_result(result)
        except Exception as e:
            logger.error(f"Remote command poll error: {e}", exc_info=True)

        shutdown_event.wait(poll_interval)


def run_collection_loop(config, logger):
    intervals = config.get("intervals", {})
    collector_cfg = config.get("collectors", {})

    metric_interval = intervals.get("metrics", 30)
    heartbeat_interval = intervals.get("heartbeat", 10)
    inventory_interval = intervals.get("inventory", 300)
    retry_interval = intervals.get("retry_flush", 30)

    retry_queue = None
    if config.get("retry", {}).get("enabled", True):
        retry_queue = RetryQueue(
            max_size=config["retry"].get("max_size", 1000),
            persist_path=config["retry"].get("persist_path"),
        )

    ssl_cfg = config.get("ssl", {})
    sender = MetricSender(
        backend_url=config["backend_url"],
        agent_id=config["agent_id"],
        api_key=config.get("api_key"),
        retry_queue=retry_queue,
        ssl_verify=ssl_cfg.get("verify", True),
        ca_cert=ssl_cfg.get("ca_cert"),
    )

    if config.get("auto_register", {}).get("enabled", True):
        logger.info("Registering agent with backend...")
        sender.register_agent()

    trigger_engine = TriggerEngine(config.get("triggers", []))

    plugin_loader = None
    if config.get("plugins", {}).get("enabled", True):
        plugins_dir = config.get("plugins", {}).get("directory", "plugins")
        if os.path.isdir(plugins_dir):
            plugin_loader = PluginLoader(plugins_dir)
            loaded = plugin_loader.list_plugins()
            if loaded:
                logger.info(f"Loaded plugins: {list(loaded.keys())}")

    log_monitor = None
    log_cfg = config.get("log_monitor", [])
    if log_cfg:
        log_monitor = LogMonitor(log_cfg)

    health_cfg = config.get("health_endpoint", {})
    health_server = None
    if health_cfg.get("enabled", False):
        health_server = health.start_health_server(
            host=health_cfg.get("host", "127.0.0.1"),
            port=health_cfg.get("port", 9273),
        )

    # Background threads for work that shouldn't block the metrics cycle.
    background_threads = []
    disc_cfg = config.get("discovery", {})
    if disc_cfg.get("network", {}).get("enabled") or disc_cfg.get("services", {}).get("enabled"):
        t = threading.Thread(
            target=_discovery_loop, args=(config, sender, logger),
            name="discovery", daemon=True,
        )
        t.start()
        background_threads.append(t)

    if config.get("remote_commands", {}).get("enabled", False):
        t = threading.Thread(
            target=_remote_command_loop, args=(config, sender, logger),
            name="remote-commands", daemon=True,
        )
        t.start()
        background_threads.append(t)

    prev_net_counters = None
    prev_disk_io_counters = None

    last_heartbeat = 0
    last_inventory = 0
    last_retry_flush = 0
    last_log_check = 0
    next_retry_attempt_at = 0

    cycle_count = 0
    cycle_errors = 0
    last_cycle_duration_ms = None

    logger.info(f"Agent '{config['agent_id']}' started on {platform.node()}")
    logger.info(f"Collecting metrics every {metric_interval}s")

    while not shutdown_event.is_set():
        cycle_start = time.monotonic()
        now = time.time()
        cycle_count += 1

        try:
            metrics = {"system": {}, "checks": {}}

            if collector_cfg.get("cpu", True):
                metrics["system"]["cpu"] = get_cpu_metrics()

            if collector_cfg.get("memory", True):
                metrics["system"]["memory"] = get_memory_metrics()

            if collector_cfg.get("disk_usage", True):
                metrics["system"]["disk_usage"] = get_disk_usage_metrics()

            if collector_cfg.get("disk_io", True):
                disk_io, prev_disk_io_counters = get_disk_io_metrics(
                    prev_disk_io_counters, metric_interval
                )
                metrics["system"]["disk_io"] = disk_io

            if collector_cfg.get("network", True):
                net, prev_net_counters = get_network_metrics(
                    prev_net_counters, metric_interval
                )
                metrics["system"]["network"] = net

            if collector_cfg.get("processes", True):
                metrics["system"]["processes"] = get_process_metrics()

            if collector_cfg.get("load_avg", True):
                if platform.system() != "Windows":
                    metrics["system"]["load_avg"] = list(os.getloadavg())

            if collector_cfg.get("gpu", False):
                metrics["system"]["gpu"] = get_gpu_metrics()

            if collector_cfg.get("docker", False):
                metrics["system"]["docker"] = get_docker_metrics()

            if collector_cfg.get("agent_self", True):
                metrics["system"]["agent_self"] = get_agent_self_metrics(
                    cycle_count=cycle_count,
                    cycle_errors=cycle_errors,
                    last_cycle_duration_ms=last_cycle_duration_ms,
                )

            metrics["checks"] = _run_io_checks(config, logger)

            if plugin_loader:
                plugin_results = plugin_loader.run_all()
                if plugin_results:
                    metrics["plugins"] = plugin_results

            alerts = trigger_engine.evaluate(metrics)
            if alerts:
                logger.info(f"Trigger engine produced {len(alerts)} events")
                sender.send_alerts(alerts)

            metrics["alerts_summary"] = {
                "total_alerts": len([a for a in alerts if a.get("status") == "problem"]),
                "recoveries": len([a for a in alerts if a.get("status") == "recovery"]),
            }

            sender.send_metrics(metrics)
            logger.debug("Metrics collected and sent")

            if now - last_heartbeat >= heartbeat_interval:
                sender.send_heartbeat()
                last_heartbeat = now

            if now - last_inventory >= inventory_interval:
                logger.info("Collecting host inventory...")
                inv = get_inventory()
                sender.send_inventory(inv)
                last_inventory = now

            if log_monitor and now - last_log_check >= intervals.get("log_check", 10):
                log_results = log_monitor.check_logs()
                if log_results:
                    sender.send_log_events(log_results)
                last_log_check = now

            if retry_queue and now - last_retry_flush >= retry_interval and now >= next_retry_attempt_at:
                sender.flush_retry_queue()
                stats = retry_queue.get_stats()
                if stats["queue_size"] > 0:
                    logger.info(f"Retry queue: {stats['queue_size']} pending entries")
                last_retry_flush = now
                # Back off proportionally to consecutive backend failures so a
                # down backend doesn't get hammered every single interval.
                next_retry_attempt_at = now + sender.backoff_seconds

            if health_server:
                health.status_store.update(
                    last_cycle_at=now,
                    last_cycle_ok=True,
                    cycle_count=cycle_count,
                    cycle_errors=cycle_errors,
                    retry_queue_size=retry_queue.size() if retry_queue else 0,
                    plugins=plugin_loader.list_plugins() if plugin_loader else {},
                )

        except Exception as e:
            cycle_errors += 1
            logger.error(f"Collection cycle error: {e}", exc_info=True)
            if health_server:
                health.status_store.update(last_cycle_at=now, last_cycle_ok=False, cycle_errors=cycle_errors)

        last_cycle_duration_ms = round((time.monotonic() - cycle_start) * 1000, 2)

        shutdown_event.wait(metric_interval)

    # --- graceful shutdown ---
    logger.info("Flushing retry queue before exit...")
    if retry_queue:
        sender.flush_retry_queue()
    if health_server:
        health_server.shutdown()
    logger.info(f"Agent stopped after {cycle_count} cycles ({cycle_errors} errors)")


def main():
    config = load_config("config.yaml")
    logger = setup_logging(config)
    logger.info("Zabbix-style Python Agent starting...")
    _install_signal_handlers(logger)

    try:
        run_collection_loop(config, logger)
    except KeyboardInterrupt:
        logger.info("Agent shutting down (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
