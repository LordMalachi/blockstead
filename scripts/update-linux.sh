#!/usr/bin/env bash
# Update Blockstead to the exact newest commit promoted from main after CI
# passes. A git checkout and a downloaded ZIP are both bootstrap material;
# neither is pulled or trusted as the payload that lands in /opt/blockstead.
set -euo pipefail

LOCK=/run/blockstead-update.lock
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $(uname -s) != Linux ]]; then
  echo "Blockstead deployment requires Linux." >&2
  exit 1
fi
if [[ ${EUID} -ne 0 ]]; then
  echo "Run this updater with sudo: sudo ./scripts/update-linux.sh" >&2
  exit 1
fi
case ${1:-} in
  "" | --yes) ;;
  *) echo "Usage: sudo ./scripts/update-linux.sh [--yes]" >&2; exit 2 ;;
esac
command -v flock >/dev/null \
  || { echo "Missing required command: flock (part of util-linux)." >&2; exit 1; }

# All destructive entry points participate in one lock. The installer receives
# the open descriptor and verifies it before skipping its own acquisition, so
# this nesting cannot deadlock and a forged environment variable is not enough.
exec 9>"$LOCK"
if ! flock --nonblock 9; then
  echo "Another Blockstead install, update, or uninstall is already running." >&2
  exit 1
fi
export BLOCKSTEAD_UPDATE_LOCKED=1
export BLOCKSTEAD_INSTALL_SOURCE=manual

if [[ ! -x $ROOT/scripts/install-linux.sh ]]; then
  echo "This Blockstead folder does not contain the Linux installer." >&2
  exit 1
fi

echo "Checking the newest approved Blockstead from main…"
exec "$ROOT/scripts/install-linux.sh" "$@"
