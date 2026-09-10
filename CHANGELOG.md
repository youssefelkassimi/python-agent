# Changelog

All changes below were made to the existing agent; nothing here changes
the on-disk metric/alert JSON shapes your backend already expects, except
where noted.

## Bug fixes

- **Network discovery no longer blocks the agent.** It pinged/port-scanned
  hosts sequentially, which could stall the entire collection loop for
  minutes on a /24 (confirmed from `agent.log`: a discovery run that
  started at 19:28:28 hadn't finished a minute later). It now:
  - scans hosts concurrently with a thread pool (`collectors/discovery.py`)
  - runs on its own background thread/timer (`main.py`), so it never
    blocks metrics, heartbeats, or anything else
  - caps at 4096 hosts so a misconfigured `subnets: null` auto-detect
    can't turn into an unbounded scan

- **DNS/HTTP/ICMP checks now run concurrently instead of one at a time.**
  Previously N targets in `dns_checks`/`http_checks`/`icmp_checks` could
  take up to N × timeout seconds sequentially. Each check type is now
  parallelized internally, and the three check types also run
  concurrently with each other.

- **`PLUGIN_INTERVAL` is now actually respected.** Plugins declaring
  `PLUGIN_INTERVAL = 30` were re-run on every single collection cycle
  regardless. The loader now tracks per-plugin last-run time and returns
  the cached last result until the interval elapses.

- **`loader.py` no longer tries to load itself as a plugin.** It lives in
  the same directory as user plugins and was being scanned like one,
  producing a harmless but confusing "no collect() function" warning on
  every startup.

- **ICMP checks degrade gracefully instead of erroring every cycle.**
  `icmplib` needs raw or unprivileged-ICMP socket permissions that many
  containers/sandboxes don't grant. The collector now probes capability
  once at startup and falls back to the system `ping` binary (parsed for
  RTT/loss) instead of failing repeatedly.

- **Remote command allowlist could be bypassed with a full path.**
  `command.lower()` was checked directly against the allowlist, so
  `/bin/whatever` would never match a bare `whatever` entry - meaning an
  attacker (or bug) supplying a full path could dodge the intended
  allowlist matching. Commands are now matched by `os.path.basename()`
  either way, and resolved via `shutil.which()` before execution.

## New features

- **Trigger hysteresis and duration** (`triggers/engine.py`):
  - `for: <seconds>` - a condition must hold continuously before the
    alert fires, so a single noisy sample doesn't page anyone.
  - `recovery_threshold: <value>` - a separate, looser threshold used
    only for recovery, preventing "flapping" alerts when a metric
    hovers right at the edge of the fire threshold. The engine warns at
    startup if a configured `recovery_threshold` would make flapping
    *worse* instead of better.
  - Both fields are optional and fully backward compatible with
    existing trigger configs.

- **Remote command execution is now wired up and hardened**
  (`remote/commands.py`, `main.py`):
  - polls `sender.fetch_commands()` on a background thread when
    `remote_commands.enabled: true`, executes allow-listed commands,
    and reports results via the new `sender.send_command_result()`
  - per-minute rate limiting on command execution
  - still disabled by default; you must explicitly opt in

- **Agent self-monitoring** (`collectors/agent_self.py`): the agent now
  reports its own PID, uptime, CPU%, RSS/VMS memory, thread count, open
  FD count, and recent cycle count/errors/duration - useful for catching
  a leaking or slowing-down agent before it becomes a bigger problem.

- **GPU metrics** (`collectors/gpu_metrics.py`): per-GPU utilization,
  memory, temperature, and power draw via `nvidia-smi`. Safe no-op
  (`{"available": false}`) on any host without an NVIDIA GPU/driver.
  Disabled by default (`collectors.gpu: false`).

- **Docker container metrics** (`collectors/docker_metrics.py`): running
  container list plus per-container CPU/mem/net/block IO via the
  `docker` CLI. Safe no-op without Docker installed. Disabled by default
  (`collectors.docker: false`).

- **Health-check HTTP endpoint** (`health.py`): lightweight, stdlib-only
  `GET /health` returning JSON status, uptime, cycle count/errors, retry
  queue depth, and plugin stats. Returns 503 if the collection loop has
  stalled for 5+ minutes. Bound to `127.0.0.1` by default; disabled
  unless `health_endpoint.enabled: true`. Useful for systemd,
  orchestrators, or an external uptime check.

- **Graceful shutdown.** SIGINT/SIGTERM now trigger a clean shutdown:
  in-flight background threads stop, the retry queue gets one final
  flush attempt, and the health server is stopped, all before exit.
  Previously only `KeyboardInterrupt` (Ctrl+C) was handled, and there
  was no queue flush on exit.

- **Exponential backoff for a down backend** (`sender.py`): consecutive
  POST failures now increase the delay before the next retry-queue flush
  attempt (capped at 5 minutes), instead of retrying every
  `retry_flush` interval regardless of how long the backend has been down.

- **Config secrets via environment variables** (`main.py`): any string
  value in `config.yaml` matching `${VAR_NAME}` or `${VAR_NAME:-default}`
  is substituted from the environment at load time, so `api_key` (or
  anything else) no longer has to be committed in plaintext. Example:
  `api_key: "${AGENT_API_KEY:-}"`.

- **Structured JSON logging option**: `logging.json: true` in config
  switches log output to single-line JSON, for easier ingestion by log
  shippers.

- **Plugin hot-reload**: `PluginLoader.reload()` re-scans the plugins
  directory for new/changed/removed plugins without restarting the agent
  (not yet wired to a signal/timer in `main.py` - call it from a REPL,
  admin endpoint, or future SIGHUP handler as needed).

## Deployment additions

- `Dockerfile` - includes `iputils-ping` so the ICMP fallback works in
  containers without `--cap-add=NET_RAW`
- `deploy/python-agent.service` - systemd unit with reasonable
  sandboxing and a shutdown grace period long enough for the retry-queue
  flush
- `.gitignore`
- `tests/` - 30 pytest unit tests covering the trigger engine, retry
  queue, plugin loader, and remote command hardening (`pytest tests/`)
- `requirements-dev.txt`

## Config changes (`config.yaml`)

All new options have sensible, conservative defaults and are documented
inline:

- `health_endpoint` (new section, disabled by default)
- `collectors.agent_self` (new, enabled by default)
- `collectors.gpu` / `collectors.docker` (new, disabled by default)
- `remote_commands.poll_interval` / `max_commands_per_minute` (new)
- `logging.json` (new, disabled by default)
- `triggers[].for` / `triggers[].recovery_threshold` (new, optional -
  added to two example triggers to show usage)
- `api_key` now shows the `${AGENT_API_KEY:-}` env-var pattern

## What I deliberately did not change

- Metric/alert JSON payload shapes sent to the backend - existing
  dashboards/parsers should keep working unchanged.
- The plugin API (`collect()`, `PLUGIN_NAME`, etc.) - existing plugins
  work as-is, they just get interval scheduling for free now if they
  declare `PLUGIN_INTERVAL`.
- Discovery/service/log-monitor collector logic itself, beyond adding
  concurrency - the actual scanning/matching behavior is unchanged.
