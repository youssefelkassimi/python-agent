# Python Monitoring Agent

A lightweight, Zabbix-style monitoring agent: system metrics, service/DNS/
HTTP/ICMP checks, log tailing, LLD-style network/service discovery,
threshold-based alerting, a plugin system, and (opt-in) remote command
execution - all reporting to a backend over HTTP.

See `CHANGELOG.md` for a detailed list of what changed in this pass and
why.

## Quick start

```bash
pip install -r requirements.txt
cp config.yaml config.local.yaml   # edit backend_url, agent_id, etc.
python3 main.py
```

Set secrets via environment variables instead of editing config.yaml
directly:

```bash
export AGENT_API_KEY=your-key-here
python3 main.py
```

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Health check

Enable in `config.yaml`:

```yaml
health_endpoint:
  enabled: true
  host: "127.0.0.1"
  port: 9273
```

```bash
curl http://127.0.0.1:9273/health
```

## Docker

```bash
docker build -t python-agent .
docker run -d --name python-agent \
  -e AGENT_API_KEY=your-key-here \
  -v $(pwd)/config.yaml:/app/config.yaml \
  python-agent
```

ICMP checks work out of the box in the container via a `ping`-binary
fallback; for icmplib's faster raw-socket path instead, add
`--cap-add=NET_RAW`.

## systemd

```bash
sudo cp deploy/python-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now python-agent
```

Edit the `WorkingDirectory`/`ExecStart` paths and create
`/etc/python-agent/agent.env` for secrets (`AGENT_API_KEY=...`) first.

## Project layout

```
main.py                 entry point / collection loop
sender.py                HTTP client to the backend, retry-aware
retry_queue.py            durable queue for failed sends
health.py                 optional local /health HTTP endpoint
collectors/               one module per metric/check type
triggers/engine.py         threshold alerting (supports hysteresis + duration)
plugins/                   drop-in .py files with a collect() function
remote/commands.py         hardened remote command execution
tests/                     pytest unit tests
deploy/                    systemd unit
```

## Writing a plugin

Drop a `.py` file in `plugins/` with a `collect()` function:

```python
PLUGIN_NAME = "my_plugin"
PLUGIN_DESCRIPTION = "What this reports"
PLUGIN_INTERVAL = 60  # optional: run at most once every 60s, cached in between

def collect():
    return {"some_metric": 42}
```

## Configuration reference

See the comments in `config.yaml` - every section is documented inline,
including the new `for`/`recovery_threshold` trigger options,
`${ENV_VAR}` secret substitution, and the optional GPU/Docker/health-
endpoint/remote-command features.
