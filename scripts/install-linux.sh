#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/blockstead
CONFIG_DIR=/etc/blockstead
DATA_DIR=/var/lib/blockstead
LOG_DIR=/var/log/blockstead
UPDATE_STATE_DIR=/var/lib/blockstead-update
UPDATE_STATUS=$UPDATE_STATE_DIR/status.json
UPDATE_LOG_DIR=/var/log/blockstead-update
UPDATE_LOG=$UPDATE_LOG_DIR/update.log
UPDATE_LOCK=/run/blockstead-update.lock
SERVER_ROOT=/srv/minecraft
DATABASE=$DATA_DIR/blockstead.db
ROLLBACK_DIR=$UPDATE_STATE_DIR/previous
SERVICE=blockstead.service
UNIT_PATH=/etc/systemd/system/$SERVICE
POWER_HELPER=/usr/lib/blockstead/blockstead-power
SUDOERS_PATH=/etc/sudoers.d/blockstead-power
UPDATE_HELPER=/usr/lib/blockstead/blockstead-update
UPDATE_PATH_UNIT=/etc/systemd/system/blockstead-update.path
UPDATE_SERVICE_UNIT=/etc/systemd/system/blockstead-update.service
CLI_PATH=/usr/local/bin/blockstead
DESKTOP_PATH=/usr/share/applications/blockstead.desktop
ICON_PATH=/usr/share/icons/hicolor/scalable/apps/blockstead.svg
SOURCE_RECORD=$CONFIG_DIR/install-source
REPO=LordMalachi/blockstead
BRANCH=main
MANIFEST_URL=https://github.com/LordMalachi/blockstead/releases/download/update-channel/latest.json
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPDATE_ATTEMPT=${BLOCKSTEAD_UPDATE_ATTEMPT:-}

if [[ ${EUID} -ne 0 ]]; then echo "Run this installer with sudo." >&2; exit 1; fi
if [[ $(uname -s) != Linux ]]; then echo "Blockstead deployment requires Linux." >&2; exit 1; fi

assume_yes=false
case ${1:-} in
  "") ;;
  --yes) assume_yes=true ;;
  *) echo "Usage: sudo ./scripts/install-linux.sh [--yes]" >&2; exit 2 ;;
esac

ensure_update_dirs() {
  local path
  for path in "$UPDATE_STATE_DIR" "$UPDATE_LOG_DIR"; do
    if [[ -L $path || ( -e $path && ! -d $path ) ]]; then
      echo "Refusing unsafe updater directory: $path" >&2
      exit 1
    fi
    install -d -o root -g root -m 0755 "$path"
  done
  if [[ -L $UPDATE_LOG || ( -e $UPDATE_LOG && ! -f $UPDATE_LOG ) ]]; then
    echo "Refusing unsafe updater log: $UPDATE_LOG" >&2
    exit 1
  fi
  if [[ -e $UPDATE_LOG ]] && ! python3 - "$UPDATE_LOG" <<'PY'
import os
import stat
import sys
info = os.lstat(sys.argv[1])
raise SystemExit(0 if stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1 else 1)
PY
  then
    echo "Refusing an updater log that is not a singly-linked root-owned file: $UPDATE_LOG" >&2
    exit 1
  fi
  touch "$UPDATE_LOG"
  chown root:root "$UPDATE_LOG"
  chmod 0644 "$UPDATE_LOG"
}

record_update_status() {
  local state=$1 commit=$2 detail=$3 retryable=${4:-} retry_after=${5:-} rolled_back=${6:-}
  python3 - "$UPDATE_STATUS" "$state" "$commit" "$UPDATE_ATTEMPT" "$detail" "$(date -Is)" \
    "$retryable" "$retry_after" "$rolled_back" <<'PY'
import json
import os
import sys
import tempfile

path, state, commit, attempt, detail, at, retryable, retry_after, rolled_back = sys.argv[1:]
payload = {"state": state, "commit": commit, "detail": detail, "at": at}
if attempt:
    payload["attempt"] = attempt
if retryable:
    payload["retryable"] = retryable == "true"
if retry_after:
    payload["retry_after"] = retry_after
if rolled_back:
    payload["rolled_back"] = rolled_back == "true"
directory = os.path.dirname(path)
fd, temporary = tempfile.mkstemp(prefix=".status.", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        os.fchmod(handle.fileno(), 0o644)
    os.replace(temporary, path)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

acquire_update_lock() {
  local inherited_target
  if [[ ${BLOCKSTEAD_UPDATE_LOCKED:-} == 1 && -e /proc/$$/fd/9 ]]; then
    inherited_target=$(readlink -f /proc/$$/fd/9 2>/dev/null || true)
    if [[ $inherited_target == "$UPDATE_LOCK" ]]; then
      return
    fi
  fi
  unset BLOCKSTEAD_UPDATE_LOCKED
  exec 9>"$UPDATE_LOCK"
  if ! flock --nonblock 9; then
    echo "Another Blockstead install, update, or uninstall is already running." >&2
    exit 1
  fi
  export BLOCKSTEAD_UPDATE_LOCKED=1
}

read_approved_manifest() {
  local destination=$1
  python3 - "$destination" "$REPO" "$BRANCH" <<'PY'
import datetime as dt
import json
import re
import sys

path, expected_repository, expected_branch = sys.argv[1:]
try:
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    expected_keys = {
        "schema", "repository", "branch", "commit", "committed_at", "summary", "published_at"
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise ValueError("unexpected manifest fields")
    commit = manifest["commit"]
    committed_at = manifest["committed_at"]
    summary = manifest["summary"]
    published_at = manifest["published_at"]
    if type(manifest.get("schema")) is not int or manifest["schema"] != 1:
        raise ValueError("unsupported schema")
    if manifest.get("repository") != expected_repository:
        raise ValueError("wrong repository")
    if manifest.get("branch") != expected_branch:
        raise ValueError("wrong branch")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid commit")
    if not isinstance(summary, str) or not summary.strip() or summary != summary.strip():
        raise ValueError("invalid summary")
    if "\n" in summary or "\r" in summary or len(summary) > 500:
        raise ValueError("invalid summary")
    for field, value in (("committed_at", committed_at), ("published_at", published_at)):
        if not isinstance(value, str) or not value:
            raise ValueError(f"invalid {field}")
        moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError(f"{field} has no timezone")
except (KeyError, OSError, ValueError, json.JSONDecodeError, TypeError) as error:
    print(f"The Blockstead update manifest is invalid: {error}", file=sys.stderr)
    raise SystemExit(1)
print(commit)
print(committed_at)
print(published_at)
PY
}

installed_commit() {
  python3 - /opt/blockstead/BUILD <<'PY' 2>/dev/null || true
import json
import re
import sys
try:
    value = json.load(open(sys.argv[1], encoding="utf-8")).get("commit")
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value):
        print(value)
except (OSError, ValueError, TypeError):
    pass
PY
}

installation_is_complete() {
  local commit=$1
  [[ $(installed_commit) == "$commit" \
    && -x $APP_DIR/scripts/update-linux.sh \
    && -x $APP_DIR/scripts/uninstall-linux.sh \
    && -x $UPDATE_HELPER \
    && -f $UPDATE_PATH_UNIT \
    && -f $UPDATE_SERVICE_UNIT \
    && -x $CLI_PATH ]]
}

compare_relation() {
  local installed=$1 approved=$2 response
  response=$(curl --fail --silent --show-error --location --max-time 30 \
    "https://api.github.com/repos/$REPO/compare/$installed...$approved") || return 1
  python3 -c 'import json, sys
try:
    value = json.loads(sys.stdin.read()).get("status")
except (AttributeError, ValueError, TypeError):
    raise SystemExit(1)
if value not in {"ahead", "behind", "diverged", "identical"}:
    raise SystemExit(1)
print(value)' <<<"$response"
}

validate_database_for_backup() {
  python3 - "$DATABASE" blockstead <<'PY'
import os
import pwd
import stat
import sys

path, expected_user = sys.argv[1:]
try:
    info = os.lstat(path)
except FileNotFoundError:
    raise SystemExit(0)
expected_uid = pwd.getpwnam(expected_user).pw_uid
if not stat.S_ISREG(info.st_mode):
    print("Refusing to back up a database that is not a regular file.", file=sys.stderr)
    raise SystemExit(1)
if info.st_uid != expected_uid:
    print("Refusing to back up a database not owned by the Blockstead service account.", file=sys.stderr)
    raise SystemExit(1)
if info.st_nlink != 1:
    print("Refusing to back up a multiply-linked Blockstead database.", file=sys.stderr)
    raise SystemExit(1)
PY
}

backup_database_securely() {
  python3 - "$DATABASE" "$ROLLBACK_DIR/blockstead.db" blockstead <<'PY'
import os
import pwd
import shutil
import sqlite3
import stat
import sys

source_path, backup_path, expected_user = sys.argv[1:]
expected_uid = pwd.getpwnam(expected_user).pw_uid
snapshot_path = backup_path + ".source"


def copy_regular(source: str, destination: str, *, required: bool) -> bool:
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        if required:
            raise
        return False
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or info.st_nlink != 1:
            raise OSError(f"unsafe database component: {source}")
        with os.fdopen(descriptor, "rb", closefd=False) as source_handle:
            with open(destination, "xb") as destination_handle:
                shutil.copyfileobj(source_handle, destination_handle)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
    finally:
        os.close(descriptor)
    return True


try:
    copy_regular(source_path, snapshot_path, required=True)
    copy_regular(source_path + "-wal", snapshot_path + "-wal", required=False)
    source = sqlite3.connect(snapshot_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
finally:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(snapshot_path + suffix)
        except FileNotFoundError:
            pass
PY
}

quarantine_data_entry() {
  local name=$1
  python3 - "$DATA_DIR" "$name" <<'PY'
import os
import secrets
import sys

directory, name = sys.argv[1:]
try:
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
except FileNotFoundError:
    raise SystemExit(0)
try:
    destination = f".consumed-{name}.{secrets.token_hex(8)}"
    try:
        os.rename(name, destination, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    except FileNotFoundError:
        pass
finally:
    os.close(directory_fd)
PY
}

database_quick_check() {
  python3 - "$DATABASE" blockstead <<'PY'
import os
import pwd
import sqlite3
import stat
import sys

path, expected_user = sys.argv[1:]
descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
try:
    info = os.fstat(descriptor)
    expected_uid = pwd.getpwnam(expected_user).pw_uid
    if not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or info.st_nlink != 1:
        raise SystemExit(1)
    connection = sqlite3.connect(
        f"file:/proc/self/fd/{descriptor}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        rows = connection.execute("PRAGMA quick_check").fetchall()
    finally:
        connection.close()
finally:
    os.close(descriptor)
raise SystemExit(0 if rows == [("ok",)] else 1)
PY
}

restored_file_matches() {
  local existed=$1 backup=$2 target=$3
  if [[ $existed == true ]]; then
    [[ -f $target ]] && cmp -s "$backup" "$target"
  else
    [[ ! -e $target && ! -L $target ]]
  fi
}

bootstrap_approved_release() {
  local workdir manifest commit committed_at published_at current extracted retry_after relation status=1
  local install_args=()
  local -a approved
  workdir=$(mktemp -d /tmp/blockstead-bootstrap.XXXXXX)
  manifest=$workdir/latest.json

  if ! curl --fail --silent --show-error --location --max-time 30 \
    --output "$manifest" "$MANIFEST_URL"; then
    retry_after=$(date --iso-8601=seconds --date='+1 hour')
    record_update_status failed "" \
      "Blockstead could not download the approved update manifest. Try again later." \
      true "$retry_after"
    rm -rf "$workdir"
    return 1
  fi
  mapfile -t approved < <(read_approved_manifest "$manifest")
  if (( ${#approved[@]} != 3 )); then
    retry_after=$(date --iso-8601=seconds --date='+1 hour')
    record_update_status failed "" \
      "Blockstead could not validate the approved update manifest. Try again later." \
      true "$retry_after"
    rm -rf "$workdir"
    return 1
  fi
  commit=${approved[0]}
  committed_at=${approved[1]}
  published_at=${approved[2]}
  current=$(installed_commit)
  if [[ -n $current && $current == "$commit" ]] && installation_is_complete "$commit"; then
    record_update_status succeeded "$commit" \
      "Blockstead is already current at ${commit:0:7}." false
    echo "You already have the newest approved Blockstead (${commit:0:7}). Nothing to do."
    rm -rf "$workdir"
    return 0
  fi
  if [[ -n $current && $current != "$commit" ]]; then
    if ! relation=$(compare_relation "$current" "$commit"); then
      retry_after=$(date --iso-8601=seconds --date='+1 hour')
      record_update_status failed "$commit" \
        "Blockstead could not verify that the approved channel would not downgrade this installation. Try again later." \
        true "$retry_after"
      rm -rf "$workdir"
      return 1
    fi
    if [[ $relation != ahead ]]; then
      record_update_status failed "$commit" \
        "The approved channel is not a direct newer descendant of the installed build, so Blockstead refused to replace it." \
        false "" false
      rm -rf "$workdir"
      return 1
    fi
  fi

  echo "Downloading approved Blockstead ${commit:0:7}…"
  record_update_status downloading "$commit" "Downloading Blockstead ${commit:0:7}."
  if ! curl --fail --silent --show-error --location --max-time 300 \
    --output "$workdir/source.tar.gz" "https://codeload.github.com/$REPO/tar.gz/$commit"; then
    retry_after=$(date --iso-8601=seconds --date='+1 hour')
    record_update_status failed "$commit" \
      "Blockstead could not download the approved update. Try again later." \
      true "$retry_after"
    rm -rf "$workdir"
    return 1
  fi
  mkdir "$workdir/source"
  if ! tar --no-same-owner -xzf "$workdir/source.tar.gz" -C "$workdir/source"; then
    retry_after=$(date --iso-8601=seconds --date='+1 hour')
    record_update_status failed "$commit" \
      "The approved Blockstead update could not be unpacked. Try again later." \
      true "$retry_after" false
    rm -rf "$workdir"
    return 1
  fi
  extracted=$(find "$workdir/source" -mindepth 1 -maxdepth 1 -type d -print -quit)
  if [[ -z $extracted || ! -f $extracted/scripts/install-linux.sh ]]; then
    record_update_status failed "$commit" \
      "The approved Blockstead update did not contain an installer." false "" false
    rm -rf "$workdir"
    return 1
  fi
  chmod +x "$extracted/scripts/install-linux.sh"

  echo "Installing approved Blockstead ${commit:0:7}…"
  if [[ $assume_yes == true ]]; then install_args=(--yes); fi
  if BLOCKSTEAD_INSTALL_APPROVED=1 \
    BLOCKSTEAD_INSTALL_COMMIT=$commit \
    BLOCKSTEAD_INSTALL_COMMIT_AT=$committed_at \
    BLOCKSTEAD_INSTALL_PUBLISHED_AT=$published_at \
    BLOCKSTEAD_UPDATE_ATTEMPT=$UPDATE_ATTEMPT \
    BLOCKSTEAD_INSTALL_SOURCE=${BLOCKSTEAD_INSTALL_SOURCE:-channel} \
    "$extracted/scripts/install-linux.sh" "${install_args[@]}"; then
    status=0
  fi
  if [[ $status -eq 0 ]] && ! installation_is_complete "$commit"; then
    record_update_status failed "$commit" \
      "The approved installer exited without leaving a complete installation; no success was recorded." \
      false "" false
    status=1
  fi
  rm -rf "$workdir"
  return "$status"
}

# systemd and runuser cannot be meaningfully installed here; everything else
# missing is offered as a normal apt installation below.
command -v systemctl >/dev/null \
  || { echo "This system does not use systemd, which Blockstead requires." >&2; exit 1; }
command -v runuser >/dev/null \
  || { echo "Missing required command: runuser (part of util-linux)." >&2; exit 1; }
command -v flock >/dev/null \
  || { echo "Missing required command: flock (part of util-linux)." >&2; exit 1; }

acquire_update_lock

required_packages=()
recommended_packages=()
command -v python3 >/dev/null || required_packages+=(python3 python3-venv)
if command -v python3 >/dev/null && ! python3 -c 'import venv, ensurepip' >/dev/null 2>&1; then
  required_packages+=(python3-venv)
fi
command -v node >/dev/null || required_packages+=(nodejs)
command -v npm >/dev/null || required_packages+=(npm)
command -v curl >/dev/null || required_packages+=(curl)
command -v java >/dev/null || recommended_packages+=(openjdk-21-jre-headless)

if (( ${#required_packages[@]} > 0 || ${#recommended_packages[@]} > 0 )); then
  echo "Blockstead needs some system packages that are not installed yet."
  if (( ${#required_packages[@]} > 0 )); then
    echo "  Required:    ${required_packages[*]}"
  fi
  if (( ${#recommended_packages[@]} > 0 )); then
    echo "  Recommended: ${recommended_packages[*]} (Minecraft itself needs Java 21)"
  fi
  if ! command -v apt-get >/dev/null; then
    echo "Install them with your package manager, then run this installer again." >&2
    exit 1
  fi
  install_packages=true
  if [[ $assume_yes == false ]]; then
    read -r -p "Install them now with apt? [Y/n] " answer
    if [[ $answer =~ ^[Nn] ]]; then install_packages=false; fi
  fi
  if [[ $install_packages == true ]]; then
    apt-get update
    apt-get install -y "${required_packages[@]}" "${recommended_packages[@]}"
  elif (( ${#required_packages[@]} > 0 )); then
    echo "Blockstead cannot continue without: ${required_packages[*]}" >&2
    echo "Install them with: sudo apt install ${required_packages[*]}" >&2
    exit 1
  else
    echo "Continuing without Java. Install it before starting a Minecraft server:"
    echo "  sudo apt install openjdk-21-jre-headless"
  fi
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)' \
  || { echo "Blockstead needs Python 3.12, which is standard on Linux Mint 22." >&2
       echo "This system reports: $(python3 --version 2>&1)" >&2; exit 1; }
node_major=$(node --version | sed 's/^v//' | cut -d. -f1)
if (( node_major < 18 )); then
  echo "Blockstead needs Node.js 18 or newer to build its dashboard." >&2
  echo "This system reports Node.js $(node --version)." >&2
  echo "On Linux Mint 22, 'sudo apt install nodejs npm' provides a new enough version." >&2
  exit 1
fi

ensure_update_dirs
# Retire the service-owned result file used by older releases. It is never
# trusted or followed; the new status file lives in a root-owned directory.
rm -f "$DATA_DIR/update-result.json"

# A downloaded ZIP or git checkout is only a bootstrap. The actual installed
# payload always comes from the exact commit promoted after main's tests pass.
if [[ ${BLOCKSTEAD_INSTALL_APPROVED:-} != 1 ]]; then
  bootstrap_approved_release
  exit $?
fi

new_commit=${BLOCKSTEAD_INSTALL_COMMIT:-}
new_commit_at=${BLOCKSTEAD_INSTALL_COMMIT_AT:-}
new_published_at=${BLOCKSTEAD_INSTALL_PUBLISHED_AT:-}
install_source=${BLOCKSTEAD_INSTALL_SOURCE:-channel}
if [[ ! $new_commit =~ ^[0-9a-f]{40}$ || -z $new_commit_at || -z $new_published_at ]]; then
  echo "The approved Blockstead payload is missing valid build identity." >&2
  exit 1
fi
if [[ -n $UPDATE_ATTEMPT && ! $UPDATE_ATTEMPT =~ ^[0-9a-f]{32}$ ]]; then
  echo "The approved Blockstead payload has an invalid update attempt identity." >&2
  exit 1
fi
if [[ $install_source == automatic && ! $UPDATE_ATTEMPT =~ ^[0-9a-f]{32}$ ]]; then
  echo "An automatic Blockstead install requires its original update attempt identity." >&2
  exit 1
fi
python3 - "$new_commit_at" "$new_published_at" <<'PY'
import datetime as dt
import sys
for value in sys.argv[1:]:
    moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise SystemExit("Approved build timestamps must include a timezone.")
PY

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

  Application:      $APP_DIR
  Configuration:    $CONFIG_DIR/blockstead.env
  Private data:     $DATA_DIR
  Application logs: $LOG_DIR
  Managed servers:  $SERVER_ROOT
  Terminal helper:  $CLI_PATH
  Menu entry:       "Blockstead" in the applications menu

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
install -d -o blockstead -g blockstead -m 0750 "$DATA_DIR" "$LOG_DIR" "$SERVER_ROOT"
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

predeployment_interrupted() {
  trap - INT TERM
  local retry_after
  retry_after=$(date --iso-8601=seconds --date='+1 hour')
  record_update_status failed "$new_commit" \
    "The update was interrupted before installed files changed. It can be retried later." \
    true "$retry_after" false || true
  exit 130
}

trap predeployment_interrupted INT TERM
record_update_status installing "$new_commit" "Installing Blockstead ${new_commit:0:7}."
echo "Building the dashboard before stopping the installed service…"
if ! npm --prefix "$ROOT/frontend" ci \
  || ! npm --prefix "$ROOT/frontend" run build; then
  record_update_status failed "$new_commit" \
    "The Blockstead dashboard could not be built, so nothing was changed." \
    false "" false
  exit 1
fi

service_was_active=false
service_was_enabled=false
update_path_was_active=false
update_path_was_enabled=false
update_service_was_active=false
update_service_was_enabled=false
if systemctl is-active --quiet "$SERVICE"; then service_was_active=true; fi
if systemctl is-enabled --quiet "$SERVICE"; then service_was_enabled=true; fi
if systemctl is-active --quiet blockstead-update.path; then update_path_was_active=true; fi
if systemctl is-enabled --quiet blockstead-update.path; then update_path_was_enabled=true; fi
if systemctl is-active --quiet blockstead-update.service; then update_service_was_active=true; fi
if systemctl is-enabled --quiet blockstead-update.service; then update_service_was_enabled=true; fi

if [[ $service_was_active == true ]]; then
  main_pid=$(systemctl show "$SERVICE" --property MainPID --value)
  child_file=/proc/$main_pid/task/$main_pid/children
  if [[ -r $child_file ]]; then
    read -r child_pids <"$child_file" || true
    if [[ -n ${child_pids:-} ]]; then
      echo "A managed Minecraft process still appears to be running." >&2
      echo "Stop it from the Blockstead dashboard, then run this command again." >&2
      record_update_status failed "$new_commit" \
        "A managed Minecraft server is still running; stop it before updating." \
        false "" false
      exit 1
    fi
  fi
  if ! systemctl stop "$SERVICE"; then
    if systemctl start "$SERVICE"; then
      record_update_status failed "$new_commit" \
        "Blockstead could not stop the dashboard service safely, so no installed files were changed and the dashboard was started again." \
        false "" false
    else
      record_update_status failed "$new_commit" \
        "Blockstead could not stop the dashboard service safely. No installed files changed, but the dashboard could not be restarted; run sudo blockstead start." \
        false "" false
    fi
    exit 1
  fi
fi

# The service owns its data directory, so validate the database only after its
# whole systemd cgroup has stopped. Root must never follow a database symlink
# prepared by compromised service code.
if ! validate_database_for_backup; then
  if [[ $service_was_active == true ]]; then systemctl start "$SERVICE" || true; fi
  record_update_status failed "$new_commit" \
    "The existing database did not pass the safe-backup checks, so no installed files were changed." \
    false "" false
  exit 1
fi

had_database=false
had_unit=false
had_helper=false
had_sudoers=false
had_update_helper=false
had_update_path_unit=false
had_update_service_unit=false
had_cli=false
had_desktop=false
had_icon=false
had_source_record=false
rollback_ready=false
deployment_changed=false
old_commit=$(installed_commit)
rollback_ok=true

rollback_step() {
  if ! "$@"; then
    rollback_ok=false
    echo "Rollback step failed: $*" >&2
  fi
}

rollback_service_healthy() {
  local bind port host url health
  bind=$(python3 -c 'import sys; values = dict(line.strip().split("=", 1) for line in open(sys.argv[1], encoding="utf-8") if line.strip() and not line.lstrip().startswith("#") and "=" in line); print(values.get("BLOCKSTEAD_BIND_HOST", "127.0.0.1"))' "$CONFIG_DIR/blockstead.env") || return 1
  port=$(python3 -c 'import sys; values = dict(line.strip().split("=", 1) for line in open(sys.argv[1], encoding="utf-8") if line.strip() and not line.lstrip().startswith("#") and "=" in line); print(values.get("BLOCKSTEAD_PORT", "8765"))' "$CONFIG_DIR/blockstead.env") || return 1
  if [[ $bind == "::" || $bind == "::1" ]]; then host="[::1]"; else host=127.0.0.1; fi
  url="http://$host:$port/api/v1/health"
  for _ in {1..60}; do
    if health=$(curl --fail --silent --max-time 5 "$url"); then
      if python3 -c 'import json, sys
body = json.loads(sys.argv[1])
expected = sys.argv[2]
raise SystemExit(0 if body.get("status") == "ok" and (expected in {"", "unknown"} or body.get("version") == expected) else 1)' "$health" "$old_version"; then
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}

rollback() {
  local status=${1:-1} rollback_performed=false restored_commit
  # This function exits deliberately. Clear every transaction trap first so
  # its own cleanup commands cannot recurse into a second rollback.
  trap - EXIT ERR INT TERM
  set +e
  echo "The new Blockstead release did not become ready; restoring the previous installation." >&2
  rollback_ok=true
  if ! systemctl stop "$SERVICE" 2>/dev/null && [[ $service_was_active == true ]]; then
    rollback_ok=false
    echo "Rollback could not stop the Blockstead service." >&2
  fi
  # Snapshot failures happen before any installed file changes. In that case
  # the existing watcher is still valid and must not be disabled merely because
  # rollback is restarting the dashboard. Once deployment begins, stop it while
  # updater files are restored and then reinstate its captured state below.
  if [[ $deployment_changed == true ]]; then
    systemctl disable --now blockstead-update.path 2>/dev/null || true
  fi

  if [[ $deployment_changed == true && $rollback_ready == true ]]; then
    rollback_performed=true
    rollback_step rm -rf "$APP_DIR"
    if [[ $had_app == true ]]; then rollback_step cp -a "$ROLLBACK_DIR/application" "$APP_DIR"; fi

    rollback_step rm -f "$DATABASE" "$DATABASE-wal" "$DATABASE-shm"
    if [[ $had_database == true ]]; then
      rollback_step install -o blockstead -g blockstead -m 0600 "$ROLLBACK_DIR/blockstead.db" "$DATABASE"
    fi

    if [[ $had_unit == true ]]; then
      rollback_step install -m 0644 "$ROLLBACK_DIR/blockstead.service" "$UNIT_PATH"
    else
      rollback_step rm -f "$UNIT_PATH"
    fi
    if [[ $had_helper == true ]]; then
      rollback_step install -m 0755 "$ROLLBACK_DIR/blockstead-power" "$POWER_HELPER"
    else
      rollback_step rm -f "$POWER_HELPER"
    fi
    if [[ $had_sudoers == true ]]; then
      rollback_step install -m 0440 "$ROLLBACK_DIR/blockstead-power.sudoers" "$SUDOERS_PATH"
    else
      rollback_step rm -f "$SUDOERS_PATH"
    fi
    # A release that shipped a broken updater must not leave that updater in
    # place, or the machine could never be repaired automatically again.
    if [[ $had_update_helper == true ]]; then
      rollback_step install -m 0755 "$ROLLBACK_DIR/blockstead-update" "$UPDATE_HELPER"
    else
      rollback_step rm -f "$UPDATE_HELPER"
    fi
    if [[ $had_update_path_unit == true ]]; then
      rollback_step install -m 0644 "$ROLLBACK_DIR/blockstead-update.path" "$UPDATE_PATH_UNIT"
    else
      rollback_step rm -f "$UPDATE_PATH_UNIT"
    fi
    if [[ $had_update_service_unit == true ]]; then
      rollback_step install -m 0644 "$ROLLBACK_DIR/blockstead-update.service" "$UPDATE_SERVICE_UNIT"
    else
      rollback_step rm -f "$UPDATE_SERVICE_UNIT"
    fi
    if [[ $had_cli == true ]]; then
      rollback_step install -m 0755 "$ROLLBACK_DIR/blockstead-cli" "$CLI_PATH"
    else
      rollback_step rm -f "$CLI_PATH"
    fi
    if [[ $had_desktop == true ]]; then
      rollback_step install -m 0644 "$ROLLBACK_DIR/blockstead.desktop" "$DESKTOP_PATH"
    else
      rollback_step rm -f "$DESKTOP_PATH"
    fi
    if [[ $had_icon == true ]]; then
      rollback_step install -m 0644 "$ROLLBACK_DIR/blockstead.svg" "$ICON_PATH"
    else
      rollback_step rm -f "$ICON_PATH"
    fi
    if [[ $had_source_record == true ]]; then
      rollback_step install -o root -g blockstead -m 0640 "$ROLLBACK_DIR/install-source" "$SOURCE_RECORD"
    else
      rollback_step rm -f "$SOURCE_RECORD"
    fi
    if [[ $had_helper == false && $had_update_helper == false ]]; then
      rmdir /usr/lib/blockstead 2>/dev/null || true
    fi
    # Whatever asked for this update failed with it; leaving the request would
    # start the same losing update again as soon as the watcher returns.
    rollback_step quarantine_data_entry update-request.json
    rollback_step systemctl daemon-reload

    if [[ $update_path_was_enabled == true ]]; then
      rollback_step systemctl enable blockstead-update.path
    else
      systemctl disable blockstead-update.path 2>/dev/null || true
    fi
    if [[ $update_path_was_active == true ]]; then
      rollback_step systemctl start blockstead-update.path
    else
      systemctl stop blockstead-update.path 2>/dev/null || true
    fi
    if [[ $update_service_was_enabled == true ]]; then
      rollback_step systemctl enable blockstead-update.service
    else
      systemctl disable blockstead-update.service 2>/dev/null || true
    fi
    # When this installer was launched by the oneshot update service, that
    # service is still this process and will become inactive naturally. A
    # first-install failure, by contrast, must not leave a new service active.
    if [[ $update_service_was_active == false ]]; then
      systemctl stop blockstead-update.service 2>/dev/null || true
    fi
  fi

  # Verify the restored database while the service is still stopped. The
  # database directory is service-owned, so checking after startup would let
  # restored code replace the path before root validates it.
  local database_restore_safe=true
  if [[ $rollback_performed == true ]]; then
    if [[ $had_database == true ]]; then
      if [[ ! -f $DATABASE ]] || ! database_quick_check; then
        database_restore_safe=false
        rollback_ok=false
        echo "The restored Blockstead database did not pass SQLite quick_check." >&2
      fi
    elif [[ -e $DATABASE || -L $DATABASE ]]; then
      database_restore_safe=false
      rollback_ok=false
    fi
  fi

  if [[ $service_was_enabled == true ]]; then
    rollback_step systemctl enable "$SERVICE"
  else
    systemctl disable "$SERVICE" 2>/dev/null || true
  fi
  if [[ $service_was_active == true ]]; then
    if [[ $database_restore_safe != true ]]; then
      rollback_ok=false
      echo "The restored Blockstead service was left stopped because its database could not be verified." >&2
    else
      rollback_step systemctl start "$SERVICE"
      if ! rollback_service_healthy; then
        rollback_ok=false
        echo "The restored Blockstead service did not become healthy." >&2
      fi
    fi
  fi

  if [[ $rollback_performed == true && $had_app == true ]]; then
    restored_commit=$(installed_commit)
    if [[ -n $old_commit && $restored_commit != "$old_commit" ]]; then
      rollback_ok=false
      echo "The restored application does not match the previous build." >&2
    elif [[ ! -d $APP_DIR ]]; then
      rollback_ok=false
    fi
  elif [[ $rollback_performed == true && $had_app == false && -e $APP_DIR ]]; then
    rollback_ok=false
  fi

  if [[ $rollback_performed == true ]]; then
    restored_file_matches "$had_unit" "$ROLLBACK_DIR/blockstead.service" "$UNIT_PATH" \
      || rollback_ok=false
    restored_file_matches "$had_helper" "$ROLLBACK_DIR/blockstead-power" "$POWER_HELPER" \
      || rollback_ok=false
    restored_file_matches "$had_sudoers" "$ROLLBACK_DIR/blockstead-power.sudoers" "$SUDOERS_PATH" \
      || rollback_ok=false
    restored_file_matches "$had_update_helper" "$ROLLBACK_DIR/blockstead-update" "$UPDATE_HELPER" \
      || rollback_ok=false
    restored_file_matches "$had_update_path_unit" "$ROLLBACK_DIR/blockstead-update.path" "$UPDATE_PATH_UNIT" \
      || rollback_ok=false
    restored_file_matches "$had_update_service_unit" "$ROLLBACK_DIR/blockstead-update.service" "$UPDATE_SERVICE_UNIT" \
      || rollback_ok=false
    restored_file_matches "$had_cli" "$ROLLBACK_DIR/blockstead-cli" "$CLI_PATH" \
      || rollback_ok=false
    restored_file_matches "$had_desktop" "$ROLLBACK_DIR/blockstead.desktop" "$DESKTOP_PATH" \
      || rollback_ok=false
    restored_file_matches "$had_icon" "$ROLLBACK_DIR/blockstead.svg" "$ICON_PATH" \
      || rollback_ok=false
    restored_file_matches "$had_source_record" "$ROLLBACK_DIR/install-source" "$SOURCE_RECORD" \
      || rollback_ok=false
  fi

  if [[ $rollback_performed == true && $rollback_ok == true ]]; then
    record_update_status failed "$new_commit" \
      "The update failed, and the previous Blockstead installation was restored and verified." \
      false "" true || true
  elif [[ $rollback_performed == false && $rollback_ok == true ]]; then
    record_update_status failed "$new_commit" \
      "The update stopped before application files changed; the existing installation remains in place." \
      false "" false || true
  else
    record_update_status failed "$new_commit" \
      "The update failed and rollback could not be verified. Review the update log before retrying." \
      false "" false || true
  fi
  exit "$status"
}

# EXIT is the transaction guard. Unlike an ERR trap, it also runs when `set -e`
# exits because a command failed inside a shell function (for example, secure
# SQLite snapshot creation). It remains armed until every installed artifact
# and the final success status have been written.
trap 'rollback $?' EXIT
trap 'rollback 130' INT TERM

rm -rf "$ROLLBACK_DIR"
install -d -o root -g root -m 0700 "$ROLLBACK_DIR"
if [[ $had_app == true ]]; then cp -a "$APP_DIR" "$ROLLBACK_DIR/application"; fi
if [[ -f $DATABASE ]]; then
  had_database=true
  backup_database_securely
  chmod 0600 "$ROLLBACK_DIR/blockstead.db"
fi
if [[ -f $UNIT_PATH ]]; then had_unit=true; cp -a "$UNIT_PATH" "$ROLLBACK_DIR/blockstead.service"; fi
if [[ -f $POWER_HELPER ]]; then had_helper=true; cp -a "$POWER_HELPER" "$ROLLBACK_DIR/blockstead-power"; fi
if [[ -f $UPDATE_HELPER ]]; then had_update_helper=true; cp -a "$UPDATE_HELPER" "$ROLLBACK_DIR/blockstead-update"; fi
if [[ -f $UPDATE_PATH_UNIT ]]; then had_update_path_unit=true; cp -a "$UPDATE_PATH_UNIT" "$ROLLBACK_DIR/blockstead-update.path"; fi
if [[ -f $UPDATE_SERVICE_UNIT ]]; then had_update_service_unit=true; cp -a "$UPDATE_SERVICE_UNIT" "$ROLLBACK_DIR/blockstead-update.service"; fi
if [[ -f $SUDOERS_PATH ]]; then had_sudoers=true; cp -a "$SUDOERS_PATH" "$ROLLBACK_DIR/blockstead-power.sudoers"; fi
if [[ -f $CLI_PATH ]]; then had_cli=true; cp -a "$CLI_PATH" "$ROLLBACK_DIR/blockstead-cli"; fi
if [[ -f $DESKTOP_PATH ]]; then had_desktop=true; cp -a "$DESKTOP_PATH" "$ROLLBACK_DIR/blockstead.desktop"; fi
if [[ -f $ICON_PATH ]]; then had_icon=true; cp -a "$ICON_PATH" "$ROLLBACK_DIR/blockstead.svg"; fi
if [[ -f $SOURCE_RECORD ]]; then had_source_record=true; cp -a "$SOURCE_RECORD" "$ROLLBACK_DIR/install-source"; fi
rollback_ready=true

deployment_changed=true
rm -rf "$APP_DIR"
install -d -o root -g root -m 0755 "$APP_DIR" "$APP_DIR/frontend"
cp -a "$ROOT/backend" "$APP_DIR/backend"
cp -a "$ROOT/frontend/dist" "$APP_DIR/frontend/dist"
cp -a "$ROOT/packaging" "$APP_DIR/packaging"
cp -a "$ROOT/scripts" "$APP_DIR/scripts"
printf '%s\n' "$new_version" >"$APP_DIR/VERSION"
# What the dashboard reads to know whether a newer commit exists upstream.
python3 -c 'import json, sys
json.dump({"version": sys.argv[1], "commit": sys.argv[2] or None,
           "committed_at": sys.argv[3] or None, "published_at": sys.argv[4] or None,
           "source": sys.argv[5]}, open(sys.argv[6], "w"), indent=2)' \
  "$new_version" "$new_commit" "$new_commit_at" "$new_published_at" \
  "$install_source" "$APP_DIR/BUILD"
chmod 0644 "$APP_DIR/BUILD"

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

# Blockstead updates itself through a root-owned path unit rather than sudo:
# the dashboard's own unit sets NoNewPrivileges and cannot write /opt, and an
# update has to outlive the dashboard restart it causes. The dashboard only
# writes a request file into its data directory; systemd notices it and runs
# the helper. Root owns the helper, so the service account cannot edit what
# will later run as root.
install -o root -g root -m 0755 "$ROOT/packaging/blockstead-update" "$UPDATE_HELPER"
install -m 0644 "$ROOT/packaging/systemd/blockstead-update.path" "$UPDATE_PATH_UNIT"
install -m 0644 "$ROOT/packaging/systemd/blockstead-update.service" "$UPDATE_SERVICE_UNIT"
# A request left over from the update that is installing right now would
# otherwise start the whole thing again the moment the watcher comes back.
quarantine_data_entry update-request.json

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl enable --now blockstead-update.path
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
# Generous on purpose. An automatic update runs unattended right after a pip
# install and a database migration, and a slow home machine that needed a few
# more seconds would otherwise be rolled back off a perfectly good release.
for _ in {1..60}; do
  if health=$(curl --fail --silent --max-time 5 "$health_url/api/v1/health"); then
    if python3 -c 'import json, sys
body = json.loads(sys.argv[1])
healthy = body.get("status") == "ok" and body.get("version") == sys.argv[2]
if sys.argv[3]:
    healthy = healthy and body.get("commit") == sys.argv[3]
raise SystemExit(0 if healthy else 1)' "$health" "$new_version" "$new_commit"; then
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

# The API answers /api/v1/health even when the dashboard is not being served, which
# looks like a successful install until the owner opens a browser and gets a 404.
dashboard_type=$(curl --fail --silent --output /dev/null --write-out '%{content_type}' "$health_url/" || true)
if [[ $dashboard_type != text/html* ]]; then
  echo "Blockstead is healthy but served no dashboard at $health_url" >&2
  echo "Review: sudo journalctl -u $SERVICE -n 100" >&2
  rollback 1
fi

# These are part of the transaction too. Their previous copies were snapshotted
# above, so a disk or permission failure here restores a genuinely complete
# previous installation rather than leaving a BUILD stamp that cannot repair
# itself on the next run.
install -o root -g root -m 0755 "$ROOT/packaging/bin/blockstead" "$CLI_PATH"
install -d -o root -g root -m 0755 "$(dirname "$ICON_PATH")"
install -o root -g root -m 0644 "$ROOT/packaging/icons/blockstead.svg" "$ICON_PATH"
install -o root -g root -m 0644 "$ROOT/packaging/desktop/blockstead.desktop" "$DESKTOP_PATH"

# Install a desktop launcher for the person who started either the sudo or the
# graphical PolicyKit installer. Environment input is accepted only when it
# resolves to a real, non-root local account.
DESKTOP_USER=${BLOCKSTEAD_INSTALL_USER:-${SUDO_USER:-}}
if [[ -z $DESKTOP_USER && ${PKEXEC_UID:-} =~ ^[0-9]+$ ]]; then
  DESKTOP_USER=$(getent passwd "$PKEXEC_UID" | cut -d: -f1 || true)
fi
if [[ -n $DESKTOP_USER ]] && id "$DESKTOP_USER" >/dev/null 2>&1 \
    && [[ $(id -u "$DESKTOP_USER") -ne 0 ]]; then
  DESKTOP_GROUP=$(id -gn "$DESKTOP_USER")
  DESKTOP_HOME=$(getent passwd "$DESKTOP_USER" | cut -d: -f6)
  USER_DESKTOP=""
  if command -v xdg-user-dir >/dev/null; then
    USER_DESKTOP=$(runuser -u "$DESKTOP_USER" -- env HOME="$DESKTOP_HOME" \
      xdg-user-dir DESKTOP 2>/dev/null || true)
  fi
  if [[ -z $USER_DESKTOP && -d $DESKTOP_HOME/Desktop ]]; then
    USER_DESKTOP=$DESKTOP_HOME/Desktop
  fi
  if [[ -n "$USER_DESKTOP" && -d "$USER_DESKTOP" ]]; then
    DESKTOP_ICON="$USER_DESKTOP/blockstead.desktop"
    echo "Installing launcher shortcut to $DESKTOP_ICON..."
    if ! install -o "$DESKTOP_USER" -g "$DESKTOP_GROUP" -m 0755 \
      "$ROOT/packaging/desktop/blockstead.desktop" "$DESKTOP_ICON"; then
      echo "Blockstead was installed, but the optional desktop shortcut could not be written." >&2
    fi
    if command -v gio >/dev/null; then
      runuser -u "$DESKTOP_USER" -- env HOME="$DESKTOP_HOME" \
        gio set "$DESKTOP_ICON" metadata::trusted true || true
    fi
  fi
fi
if command -v update-desktop-database >/dev/null; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null; then
  gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi
printf '%s\n' "managed:$MANIFEST_URL" >"$SOURCE_RECORD"
chown root:blockstead "$SOURCE_RECORD"
chmod 0640 "$SOURCE_RECORD"

record_update_status succeeded "$new_commit" \
  "Blockstead was updated successfully to ${new_commit:0:7}." false
trap - EXIT ERR INT TERM

if [[ $mode == update ]]; then
  result="Blockstead was updated from $old_version to $new_version"
else
  result="Blockstead $new_version was installed"
fi
cat <<EOF

$result and is ready at $health_url

First steps:
  1. Open Blockstead and create your administrator account.
  2. Create a Vanilla, Fabric, Forge, Quilt, NeoForge, or Paper server in the dashboard,
     or import an existing server folder straight from this computer.
  3. Review and accept the Minecraft EULA, then choose Start server.

"Blockstead" in the applications menu opens the dashboard. From any terminal:

  blockstead status         Is everything running, and where do I open it?
  blockstead doctor         Check for common problems and suggest fixes
  blockstead logs           Show recent dashboard messages
  sudo blockstead update    Download and install the newest Blockstead
  sudo blockstead uninstall Remove Blockstead (keeps worlds and settings)
EOF
