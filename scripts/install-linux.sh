#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/blockstead
CONFIG_DIR=/etc/blockstead
DATA_DIR=/var/lib/blockstead
SERVER_ROOT=/srv/minecraft
SERVICE=blockstead.service
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ${EUID} -ne 0 ]]; then echo "Run this installer with sudo." >&2; exit 1; fi
if [[ $(uname -s) != Linux ]]; then echo "Blockstead deployment requires Linux." >&2; exit 1; fi
for command in python3 npm node systemctl curl; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
  || { echo "Python 3.12 or newer is required." >&2; exit 1; }

if [[ ${1:-} != --yes ]]; then
  cat <<EOF
Blockstead will install a local dashboard service.

  Application:     $APP_DIR
  Configuration:   $CONFIG_DIR/blockstead.env
  Private data:    $DATA_DIR
  Managed servers: $SERVER_ROOT

It will create an unprivileged 'blockstead' service account, build the web
dashboard, install Python dependencies, and enable the local-only systemd
service. It will not download Minecraft or accept its EULA for you.
EOF
  read -r -p "Continue? [y/N] " answer
  [[ $answer =~ ^[Yy]$ ]] || { echo "Installation cancelled."; exit 0; }
fi

if ! id -u blockstead >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin blockstead
fi
install -d -o blockstead -g blockstead -m 0750 "$DATA_DIR" "$SERVER_ROOT"
install -d -o root -g blockstead -m 0750 "$CONFIG_DIR"

echo "Building the dashboard…"
npm --prefix "$ROOT/frontend" ci
npm --prefix "$ROOT/frontend" run build

was_active=false
if systemctl is-active --quiet "$SERVICE"; then
  was_active=true
  systemctl stop "$SERVICE"
fi

install -d -o root -g root -m 0755 "$APP_DIR"
rm -rf "$APP_DIR/backend" "$APP_DIR/frontend"
cp -a "$ROOT/backend" "$APP_DIR/backend"
install -d -o root -g root -m 0755 "$APP_DIR/frontend"
cp -a "$ROOT/frontend/dist" "$APP_DIR/frontend/dist"

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install "$APP_DIR/backend"

if [[ ! -f $CONFIG_DIR/blockstead.env ]]; then
  cat >"$CONFIG_DIR/blockstead.env" <<EOF
BLOCKSTEAD_BIND_HOST=127.0.0.1
BLOCKSTEAD_PORT=8765
BLOCKSTEAD_DATA_DIR=$DATA_DIR
BLOCKSTEAD_SERVER_ROOT=$SERVER_ROOT
BLOCKSTEAD_SECURE_COOKIES=false
BLOCKSTEAD_ALLOWED_ORIGINS=http://127.0.0.1:8765,http://localhost:8765
EOF
  chown root:blockstead "$CONFIG_DIR/blockstead.env"
  chmod 0640 "$CONFIG_DIR/blockstead.env"
fi

install -m 0644 "$ROOT/packaging/systemd/$SERVICE" "/etc/systemd/system/$SERVICE"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl start "$SERVICE"

for _ in {1..20}; do
  if curl --fail --silent http://127.0.0.1:8765/api/v1/health >/dev/null; then
    cat <<EOF

Blockstead is ready at http://127.0.0.1:8765

First steps:
  1. Create your Blockstead administrator account.
  2. Place a legitimately obtained vanilla server folder under $SERVER_ROOT.
  3. Confirm its eula.txt contains eula=true, then import that folder in the dashboard.
  4. Select the profile and choose Start server.

Use 'sudo journalctl -u $SERVICE -f' to view dashboard logs.
EOF
    exit 0
  fi
  sleep 1
done

echo "Blockstead did not become healthy. Review: sudo journalctl -u $SERVICE -n 100" >&2
systemctl stop "$SERVICE" || true
if [[ $was_active == false ]]; then systemctl disable "$SERVICE" || true; fi
exit 1
