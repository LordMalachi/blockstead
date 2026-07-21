#!/usr/bin/env bash
# Exercise the real root updater without touching the CI host. Network access
# and the downloaded installer are replaced with deterministic fixtures; the
# authorization, request/status files, lock, and helper control flow are real.
set -euo pipefail

[[ -f /.dockerenv ]] || {
  echo "Run this test through tests/integration/run-native-update-tests.sh." >&2
  exit 2
}

APPROVED_COMMIT=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
OTHER_COMMIT=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
DEFAULT_ATTEMPT=cccccccccccccccccccccccccccccccc
SECOND_ATTEMPT=dddddddddddddddddddddddddddddddd
MANIFEST_URL=https://github.com/LordMalachi/blockstead/releases/download/update-channel/latest.json
REQUEST=/var/lib/blockstead/update-request.json
STATUS=/var/lib/blockstead-update/status.json
UPDATE_LOG=/var/log/blockstead-update/update.log
HELPER=/workspace/packaging/blockstead-update
FIXTURE_ROOT=/tmp/blockstead-native-update-contract

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file_contains() {
  local file=$1 expected=$2
  grep -F -- "$expected" "$file" >/dev/null \
    || fail "$file did not contain: $expected"
}

assert_exact_contents() {
  local file=$1 expected=$2 actual
  actual=$(<"$file")
  [[ $actual == "$expected" ]] \
    || fail "$file changed unexpectedly (wanted '$expected', got '$actual')"
}

assert_status() {
  local expected_state=$1 expected_commit=$2 expected_rollback=${3:-}
  local expected_attempt=${4:-$DEFAULT_ATTEMPT}
  python3 - "$STATUS" "$expected_state" "$expected_commit" "$expected_rollback" "$expected_attempt" <<'PY'
import json
import sys

path, expected_state, expected_commit, expected_rollback, expected_attempt = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    status = json.load(handle)
assert status["state"] == expected_state, status
assert status["commit"] == expected_commit, status
assert isinstance(status.get("detail"), str) and status["detail"], status
assert isinstance(status.get("at"), str) and status["at"], status
if expected_attempt == "none":
    assert "attempt" not in status, status
else:
    assert status.get("attempt") == expected_attempt, status
if expected_rollback:
    assert status.get("rolled_back") is (expected_rollback == "true"), status
PY
}

assert_failure_policy() {
  local expected_retryable=$1 expected_rollback=$2 expect_retry_after=$3
  python3 - "$STATUS" "$expected_retryable" "$expected_rollback" "$expect_retry_after" <<'PY'
import json
import sys

path, expected_retryable, expected_rollback, expect_retry_after = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    status = json.load(handle)
assert status["retryable"] is (expected_retryable == "true"), status
assert status.get("rolled_back", False) is (expected_rollback == "true"), status
if expect_retry_after == "true":
    assert isinstance(status.get("retry_after"), str) and status["retry_after"], status
else:
    assert not status.get("retry_after"), status
PY
}

write_request() {
  local commit=$1 attempt=${2:-$DEFAULT_ATTEMPT}
  mkdir -p "$(dirname "$REQUEST")"
  python3 - "$REQUEST" "$commit" "$attempt" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "commit": sys.argv[2],
        "attempt": sys.argv[3],
        "requested_at": "2026-07-20T12:00:00Z",
    }, handle)
PY
}

wait_for_state() {
  local wanted=$1
  local attempt
  for attempt in {1..200}; do
    if [[ -f $STATUS ]] && python3 - "$STATUS" "$wanted" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        raise SystemExit(0 if json.load(handle).get("state") == sys.argv[2] else 1)
except (OSError, ValueError):
    raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 0.05
  done
  fail "updater never reported state $wanted"
}

rm -rf "$FIXTURE_ROOT" /var/lib/blockstead /var/lib/blockstead-update /var/log/blockstead-update
mkdir -p "$FIXTURE_ROOT/archive/blockstead-$APPROVED_COMMIT/scripts"

cat >"$FIXTURE_ROOT/archive/blockstead-$APPROVED_COMMIT/scripts/install-linux.sh" <<'INSTALLER'
#!/usr/bin/env bash
set -euo pipefail
: "${FAKE_INSTALL_RECORD:?}"
: "${FAKE_ATTEMPT_RECORD:?}"
: "${BLOCKSTEAD_INSTALL_COMMIT:?}"
: "${BLOCKSTEAD_INSTALL_COMMIT_AT:?}"
: "${BLOCKSTEAD_INSTALL_PUBLISHED_AT:?}"
printf '%s\n' "$BLOCKSTEAD_INSTALL_COMMIT" >>"$FAKE_INSTALL_RECORD"
printf '%s\n' "${BLOCKSTEAD_UPDATE_ATTEMPT:-}" >>"$FAKE_ATTEMPT_RECORD"
stamp_build() {
  mkdir -p /opt/blockstead/scripts /usr/lib/blockstead /etc/systemd/system /usr/local/bin
  python3 - /opt/blockstead/BUILD "$BLOCKSTEAD_INSTALL_COMMIT" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({"commit": sys.argv[2], "version": "0.1.0"}, handle)
PY
  install -m 0755 /dev/null /opt/blockstead/scripts/update-linux.sh
  install -m 0755 /dev/null /opt/blockstead/scripts/uninstall-linux.sh
  install -m 0755 /dev/null /usr/lib/blockstead/blockstead-update
  install -m 0644 /dev/null /etc/systemd/system/blockstead-update.path
  install -m 0644 /dev/null /etc/systemd/system/blockstead-update.service
  install -m 0755 /dev/null /usr/local/bin/blockstead
}
case ${FAKE_INSTALL_MODE:-success} in
  success) stamp_build; exit 0 ;;
  wait)
    : "${FAKE_INSTALL_STARTED:?}"
    : "${FAKE_INSTALL_RELEASE:?}"
    : >"$FAKE_INSTALL_STARTED"
    while [[ ! -e $FAKE_INSTALL_RELEASE ]]; do sleep 0.05; done
    stamp_build
    ;;
  fail)
    : "${BLOCKSTEAD_UPDATE_ATTEMPT:?}"
    python3 - /var/lib/blockstead-update/status.json \
      "$BLOCKSTEAD_INSTALL_COMMIT" "$BLOCKSTEAD_UPDATE_ATTEMPT" <<'PY'
import datetime as dt
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "state": "failed",
        "commit": sys.argv[2],
        "attempt": sys.argv[3],
        "detail": "Fixture installer restored and verified the previous version.",
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "retryable": False,
        "rolled_back": True,
    }, handle)
PY
    exit 42
    ;;
  fail-unverified) exit 43 ;;
  *) echo "Unknown fake install mode: $FAKE_INSTALL_MODE" >&2; exit 2 ;;
esac
INSTALLER
chmod +x "$FIXTURE_ROOT/archive/blockstead-$APPROVED_COMMIT/scripts/install-linux.sh"
tar -czf "$FIXTURE_ROOT/source.tar.gz" \
  -C "$FIXTURE_ROOT/archive" "blockstead-$APPROVED_COMMIT"

# The helper puts /usr/local/bin first in PATH. This fake behaves like curl for
# the two immutable resources an updater is allowed to request and rejects any
# unexpected network destination.
cat >"$FIXTURE_ROOT/curl" <<'CURL'
#!/usr/bin/env bash
set -euo pipefail
: "${FAKE_CURL_LOG:?}"
: "${FAKE_ARCHIVE:?}"
: "${FAKE_MANIFEST_COMMIT:?}"

output=""
url=""
while (( $# )); do
  case $1 in
    --output|-o)
      output=$2
      shift 2
      ;;
    http://*|https://*)
      url=$1
      shift
      ;;
    *) shift ;;
  esac
done
printf '%s\n' "$url" >>"$FAKE_CURL_LOG"

case $url in
  https://github.com/LordMalachi/blockstead/releases/download/update-channel/latest.json)
    payload=$(python3 - "$FAKE_MANIFEST_COMMIT" <<'PY'
import json
import sys

print(json.dumps({
    "schema": 1,
    "repository": "LordMalachi/blockstead",
    "branch": "main",
    "commit": sys.argv[1],
    "committed_at": "2026-07-20T12:00:00Z",
    "summary": "Approved integration fixture",
    "published_at": "2026-07-20T12:10:00Z",
}))
PY
    )
    if [[ -n $output ]]; then printf '%s\n' "$payload" >"$output"; else printf '%s\n' "$payload"; fi
    ;;
  "https://codeload.github.com/LordMalachi/blockstead/tar.gz/$FAKE_MANIFEST_COMMIT")
    if [[ ${FAKE_DOWNLOAD_MODE:-success} == fail ]]; then
      echo "simulated archive download failure" >&2
      exit 22
    fi
    [[ -n $output ]] || { echo "archive request omitted --output" >&2; exit 1; }
    cp "$FAKE_ARCHIVE" "$output"
    ;;
  https://api.github.com/repos/LordMalachi/blockstead/compare/*...*)
    printf '{"status":"%s"}\n' "${FAKE_COMPARE_STATUS:-ahead}"
    ;;
  *)
    echo "unexpected network request: $url" >&2
    exit 22
    ;;
esac
CURL
install -m 0755 "$FIXTURE_ROOT/curl" /usr/local/bin/curl

# The bootstrap checks that native runtime commands exist before it resolves
# the channel. Their behavior is irrelevant because the approved fixture's
# installer is intentionally tiny.
cat >"$FIXTURE_ROOT/runtime-command" <<'COMMAND'
#!/usr/bin/env bash
if [[ ${0##*/} == node && ${1:-} == --version ]]; then
  echo v22.0.0
fi
exit 0
COMMAND
for command in java node npm systemctl; do
  install -m 0755 "$FIXTURE_ROOT/runtime-command" "/usr/local/bin/$command"
done

export FAKE_ARCHIVE=$FIXTURE_ROOT/source.tar.gz
export FAKE_CURL_LOG=$FIXTURE_ROOT/curl.log
export FAKE_INSTALL_RECORD=$FIXTURE_ROOT/installed-commits
export FAKE_ATTEMPT_RECORD=$FIXTURE_ROOT/installed-attempts
export FAKE_INSTALL_STARTED=$FIXTURE_ROOT/install-started
export FAKE_INSTALL_RELEASE=$FIXTURE_ROOT/release-installer
export FAKE_MANIFEST_COMMIT=$APPROVED_COMMIT
export FAKE_DOWNLOAD_MODE=success

echo "1. A stale ZIP bootstrap installs the exact approved commit"
mkdir -p "$FIXTURE_ROOT/stale-zip/scripts"
cp /workspace/scripts/install-linux.sh "$FIXTURE_ROOT/stale-zip/scripts/install-linux.sh"
cp /workspace/scripts/update-linux.sh "$FIXTURE_ROOT/stale-zip/scripts/update-linux.sh"
: >"$FAKE_CURL_LOG"
: >"$FAKE_INSTALL_RECORD"
: >"$FAKE_ATTEMPT_RECORD"
bash "$FIXTURE_ROOT/stale-zip/scripts/install-linux.sh" --yes
[[ $(wc -l <"$FAKE_INSTALL_RECORD") -eq 1 ]] || fail "stale ZIP did not run one installer"
assert_file_contains "$FAKE_INSTALL_RECORD" "$APPROVED_COMMIT"
[[ $(wc -l <"$FAKE_ATTEMPT_RECORD") -eq 1 ]] || fail "bootstrap attempt record was incomplete"
[[ -z $(<"$FAKE_ATTEMPT_RECORD") ]] || fail "manual bootstrap unexpectedly invented an automatic attempt"
assert_file_contains "$FAKE_CURL_LOG" "$MANIFEST_URL"
assert_file_contains "$FAKE_CURL_LOG" "https://codeload.github.com/LordMalachi/blockstead/tar.gz/$APPROVED_COMMIT"

echo "2. The root helper refuses an arbitrary well-formed commit"
: >"$FAKE_CURL_LOG"
: >"$FAKE_INSTALL_RECORD"
write_request "$OTHER_COMMIT"
if "$HELPER"; then
  fail "helper accepted a commit that was not in the update manifest"
fi
[[ ! -s $FAKE_INSTALL_RECORD ]] || fail "unauthorized commit reached the installer"
assert_status failed "$OTHER_COMMIT"
assert_failure_policy true false true
if grep -F "codeload.github.com" "$FAKE_CURL_LOG" >/dev/null; then
  fail "helper downloaded an unauthorized commit before rejecting it"
fi

echo "2a. A request symlink is removed without touching its target"
request_canary=$FIXTURE_ROOT/request-symlink-canary
printf '%s\n' 'request target must stay unchanged' >"$request_canary"
rm -f "$REQUEST"
ln -s "$request_canary" "$REQUEST"
if "$HELPER"; then
  fail "helper accepted a symlink as an update request"
fi
assert_exact_contents "$request_canary" 'request target must stay unchanged'
[[ ! -e $REQUEST && ! -L $REQUEST ]] || fail "unsafe request symlink was not consumed"

echo "2b. An existing status symlink is replaced, never followed"
status_canary=$FIXTURE_ROOT/status-symlink-canary
printf '%s\n' 'status target must stay unchanged' >"$status_canary"
rm -f "$STATUS"
ln -s "$status_canary" "$STATUS"
write_request "$OTHER_COMMIT"
if "$HELPER"; then
  fail "helper accepted an unauthorized commit during status symlink test"
fi
assert_exact_contents "$status_canary" 'status target must stay unchanged'
[[ -f $STATUS && ! -L $STATUS ]] || fail "status symlink was not atomically replaced"
assert_status failed "$OTHER_COMMIT"

echo "2c. A log symlink is rejected without touching its target"
log_canary=$FIXTURE_ROOT/log-symlink-canary
printf '%s\n' 'log target must stay unchanged' >"$log_canary"
rm -f "$UPDATE_LOG"
ln -s "$log_canary" "$UPDATE_LOG"
write_request "$OTHER_COMMIT"
if "$HELPER"; then
  fail "helper accepted an unsafe updater log"
fi
assert_exact_contents "$log_canary" 'log target must stay unchanged'
[[ -L $UPDATE_LOG ]] || fail "helper unexpectedly replaced the rejected log symlink"
rm -f "$REQUEST" "$UPDATE_LOG"
install -m 0644 /dev/null "$UPDATE_LOG"

echo "2c1. A multiply-linked updater log is rejected without changing its target"
hardlink_canary=$FIXTURE_ROOT/log-hardlink-canary
printf '%s\n' 'hardlink target must stay unchanged' >"$hardlink_canary"
chmod 0600 "$hardlink_canary"
rm -f "$UPDATE_LOG"
ln "$hardlink_canary" "$UPDATE_LOG"
write_request "$OTHER_COMMIT"
if "$HELPER"; then
  fail "helper accepted a multiply-linked updater log"
fi
assert_exact_contents "$hardlink_canary" 'hardlink target must stay unchanged'
[[ $(stat -c %a "$hardlink_canary") == 600 ]] || fail "updater chmod followed a log hardlink"
rm -f "$REQUEST" "$UPDATE_LOG"
install -m 0644 /dev/null "$UPDATE_LOG"

echo "2d. An unsafe request directory is quarantined without traversing it"
mkdir -p "$REQUEST/nested"
printf '%s\n' 'directory canary' >"$REQUEST/nested/canary"
if "$HELPER"; then
  fail "helper accepted a directory as an update request"
fi
[[ ! -e $REQUEST ]] || fail "unsafe request directory kept the PathExists trigger active"
quarantined_canary=$(find /var/lib/blockstead-update/quarantine -path '*/nested/canary' -print -quit)
[[ -n $quarantined_canary ]] || fail "unsafe request directory was not quarantined intact"
assert_exact_contents "$quarantined_canary" 'directory canary'

echo "3. Download failures carry a bounded retry policy"
rm -f "$STATUS"
rm -f /usr/local/bin/blockstead
export FAKE_DOWNLOAD_MODE=fail
write_request "$APPROVED_COMMIT"
if "$HELPER"; then
  fail "helper reported success after an archive download failure"
fi
assert_status failed "$APPROVED_COMMIT"
assert_failure_policy true false true
[[ ! -e $REQUEST ]] || fail "download failure left a request that would spin immediately"
export FAKE_DOWNLOAD_MODE=success

echo "4. Running status remains durable and the manual path shares the lock"
rm -f "$STATUS" "$FAKE_INSTALL_STARTED" "$FAKE_INSTALL_RELEASE"
: >"$FAKE_INSTALL_RECORD"
: >"$FAKE_ATTEMPT_RECORD"
export FAKE_INSTALL_MODE=wait
write_request "$APPROVED_COMMIT"
"$HELPER" >"$FIXTURE_ROOT/first-helper.log" 2>&1 &
first_pid=$!
wait_for_state installing
[[ -e $FAKE_INSTALL_STARTED ]] || fail "installer did not reach its controlled wait"
assert_status installing "$APPROVED_COMMIT"
assert_exact_contents "$FAKE_ATTEMPT_RECORD" "$DEFAULT_ATTEMPT"

bash "$FIXTURE_ROOT/stale-zip/scripts/update-linux.sh" --yes \
  >"$FIXTURE_ROOT/manual-overlap.log" 2>&1 || true
assert_file_contains "$FIXTURE_ROOT/manual-overlap.log" "already running"
[[ $(wc -l <"$FAKE_INSTALL_RECORD") -eq 1 ]] || fail "manual overlap ran a second installer"

: >"$FAKE_INSTALL_RELEASE"
wait "$first_pid"
assert_status succeeded "$APPROVED_COMMIT"
[[ -x /usr/local/bin/blockstead && -x /usr/lib/blockstead/blockstead-update \
  && -x /opt/blockstead/scripts/update-linux.sh \
  && -f /etc/systemd/system/blockstead-update.service ]] \
  || fail "helper recorded success without a complete installed footprint"

echo "4a. The automatic helper waits for the shared lock without dropping its request"
rm -f "$STATUS"
rm -f /usr/local/bin/blockstead
: >"$FAKE_INSTALL_RECORD"
: >"$FAKE_ATTEMPT_RECORD"
export FAKE_INSTALL_MODE=success
write_request "$APPROVED_COMMIT" "$SECOND_ATTEMPT"
exec 8>/run/blockstead-update.lock
flock 8
"$HELPER" 8>&- &
waiting_pid=$!
sleep 0.2
[[ -f $REQUEST ]] || fail "lock contention consumed the queued request before owning the lock"
flock --unlock 8
exec 8>&-
wait "$waiting_pid"
assert_status succeeded "$APPROVED_COMMIT" "" "$SECOND_ATTEMPT"
assert_exact_contents "$FAKE_ATTEMPT_RECORD" "$SECOND_ATTEMPT"

echo "5. Installer failure records suppression and rollback contracts"
rm -f "$STATUS"
rm -f /usr/local/bin/blockstead
: >"$FAKE_INSTALL_RECORD"
export FAKE_INSTALL_MODE=fail
write_request "$APPROVED_COMMIT"
if "$HELPER"; then
  fail "helper reported success after the installer failed"
fi
[[ $(wc -l <"$FAKE_INSTALL_RECORD") -eq 1 ]] || fail "failing installer did not run exactly once"
assert_status failed "$APPROVED_COMMIT" true
assert_failure_policy false true false
[[ ! -e $REQUEST ]] || fail "failed request was left behind to retrigger automatically"

echo "5a. The helper never invents a successful rollback for a silent installer failure"
rm -f "$STATUS"
export FAKE_INSTALL_MODE=fail-unverified
write_request "$APPROVED_COMMIT" "$SECOND_ATTEMPT"
if "$HELPER"; then
  fail "helper reported success after an unverified installer failure"
fi
assert_status failed "$APPROVED_COMMIT" false "$SECOND_ATTEMPT"
assert_failure_policy false false false

echo "6. A manual current check clears stale failure status without reinstalling"
mkdir -p /opt/blockstead
python3 - /opt/blockstead/BUILD "$APPROVED_COMMIT" <<'PY'
import json
import sys

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "version": "0.1.0",
        "commit": sys.argv[2],
        "committed_at": "2026-07-20T12:00:00Z",
        "source": "update",
    }, handle)
PY
mkdir -p /opt/blockstead/scripts /usr/lib/blockstead /etc/systemd/system /usr/local/bin
install -m 0755 /dev/null /opt/blockstead/scripts/update-linux.sh
install -m 0755 /dev/null /opt/blockstead/scripts/uninstall-linux.sh
install -m 0755 /dev/null /usr/lib/blockstead/blockstead-update
install -m 0644 /dev/null /etc/systemd/system/blockstead-update.path
install -m 0644 /dev/null /etc/systemd/system/blockstead-update.service
install -m 0755 /dev/null /usr/local/bin/blockstead
: >"$FAKE_INSTALL_RECORD"
export FAKE_INSTALL_MODE=success
bash "$FIXTURE_ROOT/stale-zip/scripts/update-linux.sh" --yes
[[ ! -s $FAKE_INSTALL_RECORD ]] || fail "current manual check unnecessarily reinstalled"
assert_status succeeded "$APPROVED_COMMIT" "" none
python3 - "$STATUS" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    status = json.load(handle)
assert status.get("retryable") in (None, False), status
assert "retry_after" not in status, status
assert "rolled_back" not in status, status
PY

echo "7. A manual update refuses a channel commit known to be behind"
python3 - /opt/blockstead/BUILD "$OTHER_COMMIT" <<'PY'
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({"version": "0.1.0", "commit": sys.argv[2]}, handle)
PY
: >"$FAKE_INSTALL_RECORD"
export FAKE_COMPARE_STATUS=behind
if bash "$FIXTURE_ROOT/stale-zip/scripts/update-linux.sh" --yes; then
  fail "manual updater accepted a known downgrade"
fi
[[ ! -s $FAKE_INSTALL_RECORD ]] || fail "known downgrade reached the installer"
assert_status failed "$APPROVED_COMMIT" false none
unset FAKE_COMPARE_STATUS

echo "8. Interrupted active attempts become explicit unverified failures"
python3 - "$STATUS" "$APPROVED_COMMIT" "$SECOND_ATTEMPT" <<'PY'
import datetime as dt
import json
import sys
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump({
        "state": "installing",
        "commit": sys.argv[2],
        "attempt": sys.argv[3],
        "detail": "Fixture update is active.",
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }, handle)
PY
"$HELPER" --finalize-interrupted
assert_status failed "$APPROVED_COMMIT" false "$SECOND_ATTEMPT"
assert_failure_policy false false false

echo "9. Non-purge uninstall quarantines an unsafe request directory before removal"
cat >/usr/local/bin/systemctl <<'SYSTEMCTL'
#!/usr/bin/env bash
case ${1:-} in
  is-active | is-enabled) exit 1 ;;
  show) printf '0\n'; exit 0 ;;
  *) exit 0 ;;
esac
SYSTEMCTL
chmod 0755 /usr/local/bin/systemctl
mkdir -p "$REQUEST/nested"
printf '%s\n' 'uninstall directory canary' >"$REQUEST/nested/canary"
bash /workspace/scripts/uninstall-linux.sh --yes
[[ ! -e $REQUEST ]] || fail "uninstall preserved the watched unsafe request name"
uninstall_canary=$(find /var/lib/blockstead -path '*/nested/canary' -print -quit)
[[ -n $uninstall_canary ]] || fail "uninstall did not quarantine the unsafe request directory intact"
assert_exact_contents "$uninstall_canary" 'uninstall directory canary'

echo "Native update integration contracts passed."
