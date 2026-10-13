#!/bin/bash
set -euo pipefail

APP_DIR="/opt/python-agent"
VENV="$APP_DIR/venv"
REQ="$APP_DIR/requirements.txt"
STAMP="$VENV/.requirements.sha256"

export PIP_DISABLE_PIP_VERSION_CHECK=1

cd "$APP_DIR"

PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    echo "ERROR: Python not found. Run 'sudo $APP_DIR/setup.sh' first." >&2
    exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
    echo "Creating virtualenv with $("$PYTHON_BIN" --version)"
    "$PYTHON_BIN" -m venv "$VENV"
fi

if [[ -f "$REQ" ]]; then
    CURRENT_HASH="$(sha256sum "$REQ" | cut -d' ' -f1)"
    if [[ ! -f "$STAMP" || "$(cat "$STAMP")" != "$CURRENT_HASH" ]]; then
        echo "Installing requirements..."
        "$VENV/bin/pip" install --no-cache-dir -r "$REQ"
        echo "$CURRENT_HASH" > "$STAMP"
    fi
else
    echo "WARNING: $REQ not found, skipping dependency installation" >&2
fi

exec "$VENV/bin/python" "$APP_DIR/main.py"
