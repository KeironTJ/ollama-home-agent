#!/usr/bin/env bash
set -Eeuo pipefail

APP_USER="home-agent"
APP_GROUP="home-agent"
APP_DIR="/opt/home-agent"
CONFIG_DIR="/etc/home-agent"
DATA_DIR="/var/lib/home-agent"
SERVICE_FILE="/etc/systemd/system/home-agent.service"
START_SERVICE=false
SKIP_PACKAGES=false
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
Usage: sudo bash ./deploy/install-lxc.sh [options]

Install Home Agent inside an existing Debian/Ubuntu LXC.

Options:
  --source PATH       Repository source directory (default: script parent)
  --start             Start/restart Home Agent after installation
  --skip-packages     Do not run apt-get; required packages must already exist
  -h, --help          Show this help

The script never creates an LXC, stores credentials, or changes firewall rules.
EOF
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)
            [[ $# -ge 2 ]] || fail "--source requires a path"
            SOURCE_DIR="$(readlink -f "$2")"
            shift 2
            ;;
        --start)
            START_SERVICE=true
            shift
            ;;
        --skip-packages)
            SKIP_PACKAGES=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unknown option: $1"
            ;;
    esac
done

[[ ${EUID} -eq 0 ]] || fail "Run this script as root"
[[ -f "$SOURCE_DIR/pyproject.toml" ]] || fail "No pyproject.toml in $SOURCE_DIR"
[[ -f "$SOURCE_DIR/deploy/home-agent.service" ]] || fail "Deployment files are missing"
command -v systemctl >/dev/null || fail "systemd is required inside the LXC"

if [[ "$SKIP_PACKAGES" == false ]]; then
    command -v apt-get >/dev/null || fail "This installer supports Debian/Ubuntu apt-based containers"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-pip \
        python3-venv
fi

command -v python3 >/dev/null || fail "python3 is required"
python3 - <<'PY' || fail "Python 3.11 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

if ! id "$APP_USER" >/dev/null 2>&1; then
    useradd \
        --system \
        --user-group \
        --home-dir "$APP_DIR" \
        --shell /usr/sbin/nologin \
        "$APP_USER"
fi

install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$APP_DIR"
install -d -o root -g "$APP_GROUP" -m 0750 "$CONFIG_DIR"
install -d -o root -g "$APP_GROUP" -m 0750 "$CONFIG_DIR/certs"
install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$DATA_DIR"

if [[ "$SOURCE_DIR" != "$APP_DIR" ]]; then
    tar \
        --exclude=.git \
        --exclude=.venv \
        --exclude=.pytest_cache \
        --exclude=data \
        --exclude=.env \
        --exclude=home-agent.config.json \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        -C "$SOURCE_DIR" -cf - . \
        | tar -C "$APP_DIR" -xf -
    chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
fi

if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    python3 -m venv "$APP_DIR/.venv"
    chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/.venv"
fi

runuser -u "$APP_USER" -- \
    "$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
runuser -u "$APP_USER" -- \
    "$APP_DIR/.venv/bin/python" -m pip install --upgrade "$APP_DIR"

if [[ ! -e "$CONFIG_DIR/home-agent.env" ]]; then
    install \
        -o root \
        -g "$APP_GROUP" \
        -m 0640 \
        "$APP_DIR/deploy/home-agent.env.example" \
        "$CONFIG_DIR/home-agent.env"
    echo "Created $CONFIG_DIR/home-agent.env; add API secrets before production use."
else
    echo "Preserved existing $CONFIG_DIR/home-agent.env."
fi

install \
    -o root \
    -g root \
    -m 0644 \
    "$APP_DIR/deploy/home-agent.service" \
    "$SERVICE_FILE"

systemctl daemon-reload
systemctl enable home-agent.service

if systemctl is-active --quiet home-agent.service; then
    systemctl restart home-agent.service
elif [[ "$START_SERVICE" == true ]]; then
    systemctl start home-agent.service
fi

cat <<EOF

Home Agent is installed.

1. Add API secrets:
   sudoedit $CONFIG_DIR/home-agent.env

2. Copy public CA certificates into:
   $CONFIG_DIR/certs/
   Then reference those paths from the setup UI.

3. Start the service if --start was not supplied:
   systemctl start home-agent

4. Check it:
   systemctl --no-pager --full status home-agent
   curl http://127.0.0.1:8080/health

5. Configure through a tunnel from your workstation:
   ssh -L 8080:127.0.0.1:8080 <lxc-user>@<lxc-ip>
   Open http://127.0.0.1:8080/?setup=1

Restrict TCP 8080 to your trusted LAN. Do not expose Uvicorn directly to the internet.
EOF
