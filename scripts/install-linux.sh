#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/blockstead
CONFIG_DIR=/etc/blockstead
DATA_DIR=/var/lib/blockstead
SERVER_ROOT=/srv/minecraft
DATABASE=$DATA_DIR/blockstead.db
ROLLBACK_DIR=$DATA_DIR/update-backups/previous
SERVICE=blockstead.service
UNIT_PATH=/etc/systemd/system/$SERVICE
POWER_HELPER=/usr/lib/blockstead/blockstead-power
SUDOERS_PATH=/etc/sudoers.d/blockstead-power
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ${EUID} -ne 0 ]]; then echo "Run this installer with sudo." >&2; exit 1; fi
if [[ $(uname -s) != Linux ]]; then echo "Blockstead deployment requires Linux." >&2; exit 1; fi
for command in python3 npm node systemctl curl runuser; do
  command -v "$command" >/dev/null \
    || { echo "Missing required command: $command" >&2; exit 1; }
done
python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' \
  || { echo "Python 3.12.x is required." >&2; exit 1; }

assume_yes=false
case ${1:-} in
  "") ;;
  --yes) assume_yes=true ;;
  *) echo "Usage: sudo ./scripts/install-linux.sh [--yes]" >&2; exit 2 ;;
esac

new_version=$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$ROOT/backend/pyproject.toml")
old_version="not installed"
mode=install
had_app=false
if [[ -d $APP_DIR ]]; then
  had_app=true
  mode=update
  if [[ -f $APP_DIR/VERSION ]]; then
    old_version=$(<"$APP_DIR/VERSION")
  elif [[ -f $APP_DIR/backend/pyproject.toml ]]; then
    old_version=$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$APP_DIR/backend/pyproject.toml")
  else
    old_version="unknown"
  fi
fi

if [[ $assume_yes == false ]]; then
  if [[ $mode == update ]]; then
    action="update Blockstead from $old_version to $new_version"
  else
    action="install Blockstead $new_version"
  fi
  cat <<EOF
Blockstead will $action.

  Application:     $APP_DIR
  Configuration:   $CONFIG_DIR/blockstead.env
  Private data:    $DATA_DIR
  Managed servers: $SERVER_ROOT

Configuration, administrator data, backups, and Minecraft server folders are
preserved during updates. Stop any running Minecraft server from the dashboard
before continuing. An update also keeps one previous application/database
snapshot so a failed health check can be rolled back automatically.
EOF
  read -r -p "Continue? [y/N] " answer
  [[ $answer =~ ^[Yy]$ ]] || { echo "Installation cancelled."; exit 0; }
fi

if ! id -u blockstead >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin blockstead
fi
install -d -o blockstead -g blockstead -m 0750 "$DATA_DIR" "$SERVER_ROOT"
install -d -o root -g blockstead -m 0750 "$CONFIG_DIR"

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

echo "Building the dashboard before stopping the installed service…"
npm --prefix "$ROOT/frontend" ci
npm --prefix "$ROOT/frontend" run build

service_was_active=false
service_was_enabled=false
if systemctl is-active --quiet "$SERVICE"; then service_was_active=true; fi
if systemctl is-enabled --quiet "$SERVICE"; then service_was_enabled=true; fi

if [[ $service_was_active == true ]]; then
  main_pid=$(systemctl show "$SERVICE" --property MainPID --value)
  child_file=/proc/$main_pid/task/$main_pid/children
  if [[ -r $child_file ]]; then
    read -r child_pids <"$child_file" || true
    if [[ -n ${child_pids:-} ]]; then
      echo "A managed Minecraft process still appears to be running." >&2
      echo "Stop it from the Blockstead dashboard, then run this command again." >&2
      exit 1
    fi
  fi
  systemctl stop "$SERVICE"
fi

had_database=false
had_unit=false
had_helper=false
had_sudoers=false
rollback_ready=false
deployment_changed=false

rollback() {
  local status=${1:-1}
  trap - ERR INT TERM
  set +e
  echo "The new Blockstead release did not become ready; restoring the previous installation." >&2
  systemctl stop "$SERVICE"

  if [[ $deployment_changed == true && $rollback_ready == true ]]; then
    rm -rf "$APP_DIR"
    if [[ $had_app == true ]]; then cp -a "$ROLLBACK_DIR/application" "$APP_DIR"; fi

    rm -f "$DATABASE" "$DATABASE-wal" "$DATABASE-shm"
    if [[ $had_database == true ]]; then
      install -o blockstead -g blockstead -m 0600 "$ROLLBACK_DIR/blockstead.db" "$DATABASE"
    fi

    if [[ $had_unit == true ]]; then
      install -m 0644 "$ROLLBACK_DIR/blockstead.service" "$UNIT_PATH"
    else
      rm -f "$UNIT_PATH"
    fi
    if [[ $had_helper == true ]]; then
      install -m 0755 "$ROLLBACK_DIR/blockstead-power" "$POWER_HELPER"
    else
      rm -f "$POWER_HELPER"
    fi
    if [[ $had_sudoers == true ]]; then
      install -m 0440 "$ROLLBACK_DIR/blockstead-power.sudoers" "$SUDOERS_PATH"
    else
      rm -f "$SUDOERS_PATH"
    fi
    systemctl daemon-reload
  fi

  if [[ $service_was_enabled == true ]]; then
    systemctl enable "$SERVICE"
  else
    systemctl disable "$SERVICE"
  fi
  if [[ $service_was_active == true ]]; then systemctl start "$SERVICE"; fi
  exit "$status"
}

trap 'rollback $?' ERR
trap 'rollback 130' INT TERM

rm -rf "$ROLLBACK_DIR"
install -d -o root -g root -m 0700 "$ROLLBACK_DIR"
if [[ $had_app == true ]]; then cp -a "$APP_DIR" "$ROLLBACK_DIR/application"; fi
if [[ -f $DATABASE ]]; then
  had_database=true
  python3 -c 'import sqlite3, sys; source = sqlite3.connect(sys.argv[1]); target = sqlite3.connect(sys.argv[2]); source.backup(target); target.close(); source.close()' "$DATABASE" "$ROLLBACK_DIR/blockstead.db"
  chmod 0600 "$ROLLBACK_DIR/blockstead.db"
fi
if [[ -f $UNIT_PATH ]]; then had_unit=true; cp -a "$UNIT_PATH" "$ROLLBACK_DIR/blockstead.service"; fi
if [[ -f $POWER_HELPER ]]; then had_helper=true; cp -a "$POWER_HELPER" "$ROLLBACK_DIR/blockstead-power"; fi
if [[ -f $SUDOERS_PATH ]]; then had_sudoers=true; cp -a "$SUDOERS_PATH" "$ROLLBACK_DIR/blockstead-power.sudoers"; fi
rollback_ready=true

deployment_changed=true
rm -rf "$APP_DIR"
install -d -o root -g root -m 0755 "$APP_DIR" "$APP_DIR/frontend"
cp -a "$ROOT/backend" "$APP_DIR/backend"
cp -a "$ROOT/frontend/dist" "$APP_DIR/frontend/dist"
cp -a "$ROOT/packaging" "$APP_DIR/packaging"
printf '%s\n' "$new_version" >"$APP_DIR/VERSION"

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install "$APP_DIR/backend"

runuser -u blockstead -- "$APP_DIR/venv/bin/python" -m blockstead.database_migrations \
  --database "$DATABASE" \
  --config "$APP_DIR/backend/alembic.ini" \
  --migrations "$APP_DIR/backend/migrations"

install -d -o root -g root -m 0755 /usr/lib/blockstead
install -o root -g root -m 0755 "$ROOT/packaging/blockstead-power" "$POWER_HELPER"
install -o root -g root -m 0440 "$ROOT/packaging/sudoers/blockstead-power" "$SUDOERS_PATH"
install -m 0644 "$ROOT/packaging/systemd/$SERVICE" "$UNIT_PATH"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl start "$SERVICE"

health_bind=$(python3 -c 'import sys; values = dict(line.strip().split("=", 1) for line in open(sys.argv[1], encoding="utf-8") if line.strip() and not line.lstrip().startswith("#") and "=" in line); print(values.get("BLOCKSTEAD_BIND_HOST", "127.0.0.1"))' "$CONFIG_DIR/blockstead.env")
health_port=$(python3 -c 'import sys; values = dict(line.strip().split("=", 1) for line in open(sys.argv[1], encoding="utf-8") if line.strip() and not line.lstrip().startswith("#") and "=" in line); print(values.get("BLOCKSTEAD_PORT", "8765"))' "$CONFIG_DIR/blockstead.env")
if [[ $health_bind == "::" || $health_bind == "::1" ]]; then
  health_host="[::1]"
else
  health_host=127.0.0.1
fi
health_url="http://$health_host:$health_port"
ready=false
for _ in {1..20}; do
  if health=$(curl --fail --silent "$health_url/api/v1/health"); then
    if python3 -c 'import json, sys; body = json.loads(sys.argv[1]); raise SystemExit(0 if body.get("status") == "ok" and body.get("version") == sys.argv[2] else 1)' "$health" "$new_version"; then
      ready=true
      break
    fi
  fi
  sleep 1
done

if [[ $ready != true ]]; then
  echo "Blockstead did not become healthy. Review: sudo journalctl -u $SERVICE -n 100" >&2
  rollback 1
fi

trap - ERR INT TERM
if [[ $mode == update ]]; then
  result="Blockstead was updated from $old_version to $new_version"
else
  result="Blockstead $new_version was installed"
fi
cat <<EOF

$result and is ready at $health_url

First steps:
  1. Create your Blockstead administrator account if this is a new installation.
  2. Place a legitimately obtained server folder under $SERVER_ROOT.
  3. Confirm its eula.txt contains eula=true, then import that folder in the dashboard.
  4. Select the profile and choose Start server.

Use 'sudo journalctl -u $SERVICE -f' to view dashboard logs.
EOF
