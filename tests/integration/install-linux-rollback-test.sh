#!/usr/bin/env bash
# Exercise the real install-linux.sh transaction in a disposable container.
# The updater/helper integration suite intentionally replaces the installer;
# this test covers the complementary boundary: a deployed release fails its
# health check and the installer must restore every snapshotted component.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
IMAGE=blockstead-install-linux-rollback-contract

if [[ ! -f /.dockerenv ]]; then
  command -v docker >/dev/null 2>&1 || {
    echo "Docker is required for the disposable installer rollback test." >&2
    exit 1
  }
  docker build \
    --file "$ROOT/tests/integration/native-update.Dockerfile" \
    --tag "$IMAGE" \
    "$ROOT"
  docker run --rm "$IMAGE" bash tests/integration/install-linux-rollback-test.sh
  exit $?
fi

[[ ${EUID} -eq 0 ]] || {
  echo "The container side of this test must run as root." >&2
  exit 2
}

OLD_COMMIT=1111111111111111111111111111111111111111
NEW_COMMIT=2222222222222222222222222222222222222222
UPDATE_ATTEMPT=33333333333333333333333333333333
OLD_VERSION=0.0.1
STUB_DIR=/tmp/blockstead-install-rollback-bin
SYSTEMCTL_STATE=/tmp/blockstead-systemctl-state
EXPECTED_APP=/tmp/blockstead-expected-app.json
EXPECTED_ARTIFACTS=/tmp/blockstead-expected-artifacts.json
HEALTH_COUNTS=/tmp/blockstead-health-counts
STATUS=/var/lib/blockstead-update/status.json
DATABASE=/var/lib/blockstead/blockstead.db

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Only disposable-container paths are touched below.
rm -rf \
  "$STUB_DIR" "$SYSTEMCTL_STATE" "$HEALTH_COUNTS" \
  /opt/blockstead /etc/blockstead /var/lib/blockstead \
  /var/lib/blockstead-update /var/log/blockstead \
  /var/log/blockstead-update /srv/minecraft /usr/lib/blockstead
rm -f \
  /etc/systemd/system/blockstead.service \
  /etc/systemd/system/blockstead-update.path \
  /etc/systemd/system/blockstead-update.service \
  /etc/sudoers.d/blockstead-power \
  /usr/local/bin/blockstead \
  /usr/share/applications/blockstead.desktop \
  /usr/share/icons/hicolor/scalable/apps/blockstead.svg

mkdir -p "$STUB_DIR" "$SYSTEMCTL_STATE/active" "$SYSTEMCTL_STATE/enabled" "$HEALTH_COUNTS"

# systemctl is modeled as two small sets. The dashboard, path watcher, and
# oneshot updater begin enabled and active so rollback has real state to
# restore, not just files to copy back.
cat >"$STUB_DIR/systemctl" <<'SYSTEMCTL'
#!/usr/bin/env bash
set -euo pipefail
: "${FAKE_SYSTEMCTL_STATE:?}"
command=${1:-}
shift || true

service_arg() {
  local value
  for value in "$@"; do
    [[ $value == --* ]] || { printf '%s\n' "$value"; return; }
  done
  return 1
}

case $command in
  is-active)
    service=$(service_arg "$@")
    [[ -e $FAKE_SYSTEMCTL_STATE/active/$service ]]
    ;;
  is-enabled)
    service=$(service_arg "$@")
    [[ -e $FAKE_SYSTEMCTL_STATE/enabled/$service ]]
    ;;
  show)
    # A nonexistent PID avoids treating unrelated container processes as a
    # managed Minecraft child during the installer's pre-update safety check.
    printf '%s\n' 99999999
    ;;
  start)
    service=$(service_arg "$@")
    : >"$FAKE_SYSTEMCTL_STATE/active/$service"
    ;;
  stop)
    service=$(service_arg "$@")
    rm -f "$FAKE_SYSTEMCTL_STATE/active/$service"
    ;;
  enable)
    service=$(service_arg "$@")
    : >"$FAKE_SYSTEMCTL_STATE/enabled/$service"
    for value in "$@"; do
      [[ $value == --now ]] && : >"$FAKE_SYSTEMCTL_STATE/active/$service"
    done
    :
    ;;
  disable)
    service=$(service_arg "$@")
    rm -f "$FAKE_SYSTEMCTL_STATE/enabled/$service"
    for value in "$@"; do
      [[ $value == --now ]] && rm -f "$FAKE_SYSTEMCTL_STATE/active/$service"
    done
    :
    ;;
  daemon-reload)
    ;;
  *)
    echo "Unexpected systemctl command: $command $*" >&2
    exit 2
    ;;
esac
SYSTEMCTL
chmod +x "$STUB_DIR/systemctl"

# The real Python interpreter is retained for manifest/status/SQLite logic.
# Only venv construction is replaced so the transaction remains offline and
# deterministic. Its migration entrypoint deliberately changes the database;
# successful rollback must undo that change.
cat >"$STUB_DIR/python3" <<'PYTHON_WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == -m && ${2:-} == venv ]]; then
  destination=${3:?}
  mkdir -p "$destination/bin"
  cat >"$destination/bin/pip" <<'PIP'
#!/usr/bin/env bash
exit 0
PIP
  cat >"$destination/bin/python" <<'VENV_PYTHON'
#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == -m && ${2:-} == blockstead.database_migrations ]]; then
  shift 2
  database=""
  while (( $# )); do
    case $1 in
      --database) database=$2; shift 2 ;;
      *) shift ;;
    esac
  done
  [[ -n $database ]]
  exec /usr/local/bin/python3 - "$database" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
try:
    connection.execute("UPDATE rollback_fixture SET value = 'new release touched the database'")
    connection.commit()
finally:
    connection.close()
PY
fi
exec /usr/local/bin/python3 "$@"
VENV_PYTHON
  chmod +x "$destination/bin/pip" "$destination/bin/python"
  exit 0
fi
exec /usr/local/bin/python3 "$@"
PYTHON_WRAPPER
chmod +x "$STUB_DIR/python3"

cat >"$STUB_DIR/node" <<'NODE'
#!/usr/bin/env bash
if [[ ${1:-} == --version ]]; then printf '%s\n' v20.0.0; fi
NODE
chmod +x "$STUB_DIR/node"

cat >"$STUB_DIR/npm" <<'NPM'
#!/usr/bin/env bash
set -euo pipefail
: "${FAKE_SOURCE_ROOT:?}"
for argument in "$@"; do
  if [[ $argument == build ]]; then
    mkdir -p "$FAKE_SOURCE_ROOT/frontend/dist"
    printf '%s\n' '<!doctype html><title>fixture</title>' \
      >"$FAKE_SOURCE_ROOT/frontend/dist/index.html"
  fi
done
exit 0
NPM
chmod +x "$STUB_DIR/npm"

# Presence is sufficient to prevent an apt transaction for the recommended
# Java runtime; Java is not part of this installer transaction test.
cat >"$STUB_DIR/java" <<'JAVA'
#!/usr/bin/env bash
exit 0
JAVA
chmod +x "$STUB_DIR/java"

# The newly deployed BUILD always fails health. Once rollback has restored the
# old BUILD, the same endpoint is healthy immediately. A scoped no-op sleep
# below turns the intentional 60-attempt production grace period into a
# sub-second deterministic loop without changing production code.
cat >"$STUB_DIR/curl" <<'CURL'
#!/usr/bin/env bash
set -euo pipefail
: "${FAKE_OLD_COMMIT:?}"
: "${FAKE_OLD_VERSION:?}"
: "${FAKE_HEALTH_COUNTS:?}"
url=""
for argument in "$@"; do
  [[ $argument == http://* || $argument == https://* ]] && url=$argument
done
[[ $url == http://127.0.0.1:8765/api/v1/health ]] || {
  echo "Unexpected curl URL: $url" >&2
  exit 2
}
commit=$(/usr/local/bin/python3 - /opt/blockstead/BUILD <<'PY' 2>/dev/null || true
import json
import sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8")).get("commit", ""))
except (OSError, ValueError, TypeError):
    pass
PY
)
if [[ $commit == "$FAKE_OLD_COMMIT" ]]; then
  printf '.' >>"$FAKE_HEALTH_COUNTS/old"
  printf '{"status":"ok","version":"%s","commit":"%s"}\n' \
    "$FAKE_OLD_VERSION" "$FAKE_OLD_COMMIT"
  exit 0
fi
printf '.' >>"$FAKE_HEALTH_COUNTS/new"
exit 22
CURL
chmod +x "$STUB_DIR/curl"

cat >"$STUB_DIR/sleep" <<'SLEEP'
#!/usr/bin/env bash
exit 0
SLEEP
chmod +x "$STUB_DIR/sleep"

if ! id -u blockstead >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/blockstead --create-home \
    --shell /usr/sbin/nologin blockstead
fi

mkdir -p \
  /opt/blockstead/scripts /etc/blockstead /var/lib/blockstead \
  /var/lib/blockstead-update /var/log/blockstead /var/log/blockstead-update \
  /srv/minecraft /usr/lib/blockstead /etc/systemd/system /etc/sudoers.d \
  /usr/local/bin /usr/share/applications \
  /usr/share/icons/hicolor/scalable/apps
chown blockstead:blockstead /var/lib/blockstead /var/log/blockstead /srv/minecraft
chown root:blockstead /etc/blockstead
chmod 0750 /var/lib/blockstead /var/log/blockstead /srv/minecraft /etc/blockstead

printf '%s\n' "$OLD_VERSION" >/opt/blockstead/VERSION
/usr/local/bin/python3 - /opt/blockstead/BUILD "$OLD_VERSION" "$OLD_COMMIT" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({"version": sys.argv[2], "commit": sys.argv[3]}, handle)
PY
printf '%s\n' 'old application payload' >/opt/blockstead/old-payload.txt
printf '%s\n' '#!/usr/bin/env bash' 'echo old updater' >/opt/blockstead/scripts/update-linux.sh
printf '%s\n' '#!/usr/bin/env bash' 'echo old uninstaller' >/opt/blockstead/scripts/uninstall-linux.sh
chmod 0755 /opt/blockstead/scripts/update-linux.sh /opt/blockstead/scripts/uninstall-linux.sh

/usr/local/bin/python3 - "$DATABASE" <<'PY'
import sqlite3
import sys
connection = sqlite3.connect(sys.argv[1])
try:
    connection.execute("CREATE TABLE rollback_fixture (value TEXT NOT NULL)")
    connection.execute("INSERT INTO rollback_fixture VALUES ('old database value')")
    connection.commit()
finally:
    connection.close()
PY
chown blockstead:blockstead "$DATABASE"
chmod 0600 "$DATABASE"

cat >/etc/blockstead/blockstead.env <<'ENV'
BLOCKSTEAD_BIND_HOST=127.0.0.1
BLOCKSTEAD_PORT=8765
BLOCKSTEAD_DATA_DIR=/var/lib/blockstead
BLOCKSTEAD_SERVER_ROOT=/srv/minecraft
ENV
chown root:blockstead /etc/blockstead/blockstead.env
chmod 0640 /etc/blockstead/blockstead.env

seed_artifact() {
  local path=$1 mode=$2 value=$3
  printf '%s\n' "$value" >"$path"
  chmod "$mode" "$path"
  chown root:root "$path"
}

seed_artifact /etc/systemd/system/blockstead.service 0644 'old dashboard unit'
seed_artifact /usr/lib/blockstead/blockstead-power 0755 'old power helper'
seed_artifact /etc/sudoers.d/blockstead-power 0440 'old power sudoers'
seed_artifact /usr/lib/blockstead/blockstead-update 0755 'old update helper'
seed_artifact /etc/systemd/system/blockstead-update.path 0644 'old update path unit'
seed_artifact /etc/systemd/system/blockstead-update.service 0644 'old update service unit'
seed_artifact /usr/local/bin/blockstead 0755 'old command line helper'
seed_artifact /usr/share/applications/blockstead.desktop 0644 'old desktop entry'
seed_artifact /usr/share/icons/hicolor/scalable/apps/blockstead.svg 0644 'old application icon'
seed_artifact /etc/blockstead/install-source 0640 'old install source'
chown root:blockstead /etc/blockstead/install-source

# Model the request that launched this automatic update. It must be consumed,
# not left behind to retrigger the same failed release after rollback.
/usr/local/bin/python3 - /var/lib/blockstead/update-request.json \
  "$NEW_COMMIT" "$UPDATE_ATTEMPT" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "commit": sys.argv[2],
        "attempt": sys.argv[3],
        "requested_at": "2026-07-20T12:00:00Z",
    }, handle)
PY
chown blockstead:blockstead /var/lib/blockstead/update-request.json

for service in blockstead.service blockstead-update.path blockstead-update.service; do
  : >"$SYSTEMCTL_STATE/active/$service"
  : >"$SYSTEMCTL_STATE/enabled/$service"
done

# Capture content, type, mode, and ownership. Timestamps are intentionally not
# compared because install(1) recreates global artifacts during restoration.
/usr/local/bin/python3 - "$EXPECTED_APP" "$EXPECTED_ARTIFACTS" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

expected_app, expected_artifacts = sys.argv[1:]

def describe(path: Path) -> dict[str, object]:
    info = path.lstat()
    value: dict[str, object] = {
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
    }
    if path.is_symlink():
        value.update(type="symlink", target=os.readlink(path))
    elif path.is_dir():
        value["type"] = "directory"
    elif path.is_file():
        value.update(type="file", sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    else:
        raise AssertionError(f"unexpected fixture type: {path}")
    return value

root = Path("/opt/blockstead")
app = {".": describe(root)}
for path in sorted(root.rglob("*")):
    app[str(path.relative_to(root))] = describe(path)
Path(expected_app).write_text(json.dumps(app, sort_keys=True), encoding="utf-8")

artifact_paths = [
    "/etc/systemd/system/blockstead.service",
    "/usr/lib/blockstead/blockstead-power",
    "/etc/sudoers.d/blockstead-power",
    "/usr/lib/blockstead/blockstead-update",
    "/etc/systemd/system/blockstead-update.path",
    "/etc/systemd/system/blockstead-update.service",
    "/usr/local/bin/blockstead",
    "/usr/share/applications/blockstead.desktop",
    "/usr/share/icons/hicolor/scalable/apps/blockstead.svg",
    "/etc/blockstead/install-source",
]
artifacts = {path: describe(Path(path)) for path in artifact_paths}
Path(expected_artifacts).write_text(json.dumps(artifacts, sort_keys=True), encoding="utf-8")
PY

export PATH="$STUB_DIR:$PATH"
export FAKE_SOURCE_ROOT="$ROOT"
export FAKE_SYSTEMCTL_STATE="$SYSTEMCTL_STATE"
export FAKE_OLD_COMMIT="$OLD_COMMIT"
export FAKE_OLD_VERSION="$OLD_VERSION"
export FAKE_HEALTH_COUNTS="$HEALTH_COUNTS"

run_approved_installer() {
  BLOCKSTEAD_INSTALL_APPROVED=1 \
  BLOCKSTEAD_INSTALL_COMMIT="$NEW_COMMIT" \
  BLOCKSTEAD_INSTALL_COMMIT_AT=2026-07-20T12:00:00Z \
  BLOCKSTEAD_INSTALL_PUBLISHED_AT=2026-07-20T12:05:00Z \
  BLOCKSTEAD_INSTALL_SOURCE=automatic \
  BLOCKSTEAD_UPDATE_ATTEMPT="$UPDATE_ATTEMPT" \
    bash "$ROOT/scripts/install-linux.sh" --yes
}

# First fail while making the root-owned snapshot, before deployment starts.
# The existing updater watcher must stay enabled and active; disabling it here
# would silently break every later automatic update even though no files changed.
wal_peer=/tmp/blockstead-unsafe-wal-peer
printf '%s\n' 'unsafe multiply-linked WAL fixture' >"$DATABASE-wal"
chown blockstead:blockstead "$DATABASE-wal"
ln "$DATABASE-wal" "$wal_peer"
set +e
run_approved_installer
snapshot_status=$?
set -e
[[ $snapshot_status -eq 1 ]] \
  || fail "snapshot safety failure returned $snapshot_status instead of 1"
systemctl is-enabled --quiet blockstead-update.path \
  || fail "snapshot failure disabled the existing update watcher"
systemctl is-active --quiet blockstead-update.path \
  || fail "snapshot failure stopped the existing update watcher"
systemctl is-active --quiet blockstead.service \
  || fail "snapshot failure did not restart the unchanged dashboard"
/usr/local/bin/python3 - "$STATUS" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    status = json.load(handle)
assert status["state"] == "failed", status
assert status.get("rolled_back") is False, status
assert "existing installation remains" in status["detail"], status
PY
rm -f "$DATABASE-wal" "$wal_peer"

set +e
run_approved_installer
installer_status=$?
set -e

[[ $installer_status -eq 1 ]] \
  || fail "installer returned $installer_status instead of the forced health failure"

/usr/local/bin/python3 - "$EXPECTED_APP" "$EXPECTED_ARTIFACTS" "$STATUS" \
  "$DATABASE" "$NEW_COMMIT" "$UPDATE_ATTEMPT" <<'PY'
import hashlib
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

expected_app_path, expected_artifacts_path, status_path, database, commit, attempt = sys.argv[1:]

def describe(path: Path) -> dict[str, object]:
    info = path.lstat()
    value: dict[str, object] = {
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
    }
    if path.is_symlink():
        value.update(type="symlink", target=os.readlink(path))
    elif path.is_dir():
        value["type"] = "directory"
    elif path.is_file():
        value.update(type="file", sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    else:
        raise AssertionError(f"unexpected restored type: {path}")
    return value

root = Path("/opt/blockstead")
actual_app = {".": describe(root)}
for path in sorted(root.rglob("*")):
    actual_app[str(path.relative_to(root))] = describe(path)
expected_app = json.loads(Path(expected_app_path).read_text(encoding="utf-8"))
assert actual_app == expected_app, (actual_app, expected_app)

# The installer publishes with a sibling directory exchange. Once rollback has
# put the old app back, that sibling now holds the failed release and must be
# removed rather than accumulating executable trees under /opt.
assert not list(Path("/opt").glob("blockstead.incoming.*"))

expected_artifacts = json.loads(Path(expected_artifacts_path).read_text(encoding="utf-8"))
actual_artifacts = {path: describe(Path(path)) for path in expected_artifacts}
assert actual_artifacts == expected_artifacts, (actual_artifacts, expected_artifacts)

connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
try:
    assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    assert connection.execute("SELECT value FROM rollback_fixture").fetchall() == [
        ("old database value",)
    ]
finally:
    connection.close()

status = json.loads(Path(status_path).read_text(encoding="utf-8"))
assert status["state"] == "failed", status
assert status["commit"] == commit, status
assert status["attempt"] == attempt, status
assert status["rolled_back"] is True, status
assert status["retryable"] is False, status
assert not status.get("retry_after"), status
assert isinstance(status.get("detail"), str) and "restored and verified" in status["detail"], status
PY

for service in blockstead.service blockstead-update.path blockstead-update.service; do
  systemctl is-enabled --quiet "$service" \
    || fail "$service was not restored to enabled"
  systemctl is-active --quiet "$service" \
    || fail "$service was not restored to active"
done

[[ ! -e /var/lib/blockstead/update-request.json \
   && ! -L /var/lib/blockstead/update-request.json ]] \
  || fail "the failed automatic request was left armed"
find /var/lib/blockstead -maxdepth 1 -type f \
  -name '.consumed-update-request.json.*' -print -quit | grep -q . \
  || fail "the failed automatic request was not quarantined"

new_checks=$(wc -c <"$HEALTH_COUNTS/new")
old_checks=$(wc -c <"$HEALTH_COUNTS/old")
[[ $new_checks -eq 60 ]] || fail "expected 60 accelerated new health checks, got $new_checks"
[[ $old_checks -ge 1 ]] || fail "restored service never passed its health check"

echo "PASS: real install-linux.sh restored app, SQLite data, artifacts, and service state"
