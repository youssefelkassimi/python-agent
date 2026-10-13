#!/bin/bash
set -euo pipefail

APP_DIR="/opt/python-agent"
APP_USER="monitoring-agent"
APP_GROUP="monitoring-agent"
LOG_DIR="/var/log/python-agent"
CONF_DIR="/etc/python-agent"
SERVICE="python-agent"

WATCHED_LOGS=(/var/log/messages /var/log/secure /var/log/syslog /var/log/auth.log)

if [[ $EUID -ne 0 ]]; then
    echo "Run as root: sudo $0" >&2
    exit 1
fi



# ---------------------------------------------------------------- Group / user
if ! getent group "$APP_GROUP" >/dev/null; then
    echo "Creating group $APP_GROUP"
    groupadd --system "$APP_GROUP"
fi

if ! id -u "$APP_USER" >/dev/null 2>&1; then
    echo "Creating user $APP_USER"
    useradd --system --gid "$APP_GROUP" --no-create-home \
            --shell /usr/sbin/nologin "$APP_USER"
fi

# ---------------------------------------------------------------------- Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python3 not found, installing..."
    if command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-pip
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3 python3-pip
    elif command -v apt-get >/dev/null 2>&1; then
        apt-get update && apt-get install -y python3 python3-venv python3-pip
    else
        echo "No supported package manager found. Install Python 3 manually." >&2
        exit 1
    fi
fi

# ----------------------------------------------------------------- Directories
mkdir -p "$APP_DIR" "$CONF_DIR"

# Log directory: writable by the agent, readable by the group (not world)
mkdir -p "$LOG_DIR"
chown "$APP_USER:$APP_GROUP" "$LOG_DIR"
chmod 2750 "$LOG_DIR"
if command -v setfacl >/dev/null 2>&1; then
    setfacl -d -m g::rX "$LOG_DIR"
fi

chown root:"$APP_GROUP" "$CONF_DIR"
chmod 750 "$CONF_DIR"
[[ -f "$CONF_DIR/agent.env" ]] && chmod 640 "$CONF_DIR/agent.env" \
    && chown root:"$APP_GROUP" "$CONF_DIR/agent.env"

chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
chmod 755 "$APP_DIR"
[[ -f "$APP_DIR/start.sh" ]] && chmod +x "$APP_DIR/start.sh"

# SELinux labels (RHEL/Fedora): harmless if SELinux is absent
if command -v restorecon >/dev/null 2>&1; then
    restorecon -R "$APP_DIR" "$LOG_DIR" "$CONF_DIR" 2>/dev/null || true
fi

# ------------------------------------------- Access for the agent (reads logs)
if getent group systemd-journal >/dev/null; then
    usermod -aG systemd-journal "$APP_USER"
fi
# Debian/Ubuntu: /var/log/syslog, auth.log belong to group adm
if getent group adm >/dev/null && [[ -e /var/log/syslog || -e /var/log/auth.log ]]; then
    usermod -aG adm "$APP_USER"
fi
# RHEL/Fedora: /var/log/messages and /var/log/secure are root-only, use ACLs
if command -v setfacl >/dev/null 2>&1; then
    for f in "${WATCHED_LOGS[@]}"; do
        [[ -f "$f" ]] && setfacl -m "u:${APP_USER}:r" "$f" && echo "ACL read access granted on $f"
    done
else
    echo "NOTE: setfacl not found (install the 'acl' package) - cannot grant read access on system logs" >&2
fi


# ------------------------------------------------- systemd drop-in for logging
DROPIN_DIR="/etc/systemd/system/${SERVICE}.service.d"
mkdir -p "$DROPIN_DIR"
cat > "$DROPIN_DIR/logs.conf" <<EOF
[Service]
LogsDirectory=python-agent
LogsDirectoryMode=2750
UMask=0027
ReadWritePaths=$LOG_DIR
SupplementaryGroups=systemd-journal
Environment=AGENT_LOG_DIR=$LOG_DIR
EOF
systemctl daemon-reload

echo
echo "Setup complete: $(python3 --version)"
echo "  Agent log : $LOG_DIR/agent.log"
echo "  Follow    : tail -f $LOG_DIR/agent.log"
echo "  Journal   : journalctl -u $SERVICE -f"
