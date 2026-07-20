#!/usr/bin/env bash
# Update Blockstead in place: fetch the newest code, then re-run the
# installer, which preserves settings, accounts, backups, and Minecraft
# folders and rolls back automatically if the new version is not healthy.
#
# This works whether Blockstead came from `git clone` or from a downloaded ZIP.
# A git checkout pulls; anything else downloads the current branch tip into a
# temporary folder and installs from there, leaving the folder it was run from
# untouched. Blockstead normally keeps itself current on its own, so this is
# for updating on the spot rather than waiting for the next check.
#
# The whole script runs inside main() so that `git pull` rewriting this file
# cannot confuse the shell that is executing it; main() ends with exec/exit.
set -euo pipefail

REPO=LordMalachi/blockstead
BRANCH=main

main() {
  local root owner repo_version installed_version before after
  local yes_args=()

  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

  if [[ $(uname -s) != Linux ]]; then
    echo "Blockstead deployment requires Linux." >&2
    exit 1
  fi
  if [[ ${EUID} -ne 0 ]]; then
    echo "Run this updater with sudo: sudo ./scripts/update-linux.sh" >&2
    exit 1
  fi
  case ${1:-} in
    "") ;;
    --yes) yes_args=(--yes) ;;
    *)
      echo "Usage: sudo ./scripts/update-linux.sh [--yes]" >&2
      exit 2
      ;;
  esac

  # A folder that is not a git checkout — the usual case for someone who
  # downloaded the ZIP — is updated by downloading rather than by pulling.
  if [[ ! -d $root/.git ]] || ! command -v git >/dev/null; then
    update_from_download ${yes_args[0]+"${yes_args[@]}"}
    return
  fi

  # The clone usually belongs to the desktop user; run git as that user so
  # root does not trip git's ownership safety check or leave root-owned files.
  owner=$(stat -c %U "$root")
  run_git() {
    if [[ $owner != root ]]; then
      runuser -u "$owner" -- git -C "$root" "$@"
    else
      git -C "$root" "$@"
    fi
  }

  if [[ -n $(run_git status --porcelain) ]]; then
    cat >&2 <<EOF
This Blockstead folder has local file changes, so the updater will not pull
over them. Either discard the changes, or download a fresh copy of Blockstead
and run sudo ./scripts/install-linux.sh from there.
EOF
    exit 1
  fi

  echo "Checking for a newer Blockstead…"
  before=$(run_git rev-parse HEAD)
  run_git pull --ff-only
  after=$(run_git rev-parse HEAD)

  repo_version=$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$root/backend/pyproject.toml")
  installed_version="not installed"
  if [[ -f /opt/blockstead/VERSION ]]; then
    installed_version=$(</opt/blockstead/VERSION)
  fi

  if [[ $before == "$after" && $repo_version == "$installed_version" ]]; then
    echo "You already have the newest Blockstead ($installed_version). Nothing to do."
    exit 0
  fi

  echo "Installing the update…"
  exec "$root/scripts/install-linux.sh" ${yes_args[0]+"${yes_args[@]}"}
}

# Download the branch tip and install from it. Nothing is written into the
# folder this was run from, so a downloaded ZIP stays exactly as it was and the
# owner never has to fetch a new one by hand again.
update_from_download() {
  local commit committed_at installed_commit workdir extracted head

  for needed in curl tar python3; do
    command -v "$needed" >/dev/null || {
      echo "$needed is required to download updates. Install it with: sudo apt install $needed" >&2
      exit 1
    }
  done

  echo "Checking for a newer Blockstead…"
  head=$(curl --fail --silent --show-error --max-time 30 \
    "https://api.github.com/repos/$REPO/commits/$BRANCH") || {
    echo "Blockstead could not reach GitHub to check for updates." >&2
    exit 1
  }
  commit=$(python3 -c 'import json, sys; print(json.loads(sys.stdin.read())["sha"])' <<<"$head")
  committed_at=$(python3 -c 'import json, sys; print(json.loads(sys.stdin.read())["commit"]["committer"]["date"])' <<<"$head")

  if [[ ! $commit =~ ^[0-9a-f]{40}$ ]]; then
    echo "GitHub did not return a usable commit for $BRANCH." >&2
    exit 1
  fi

  installed_commit=""
  if [[ -f /opt/blockstead/BUILD ]]; then
    installed_commit=$(python3 -c 'import json, sys
try:
    print(json.load(open(sys.argv[1]))["commit"] or "")
except Exception:
    pass' /opt/blockstead/BUILD 2>/dev/null || true)
  fi
  if [[ -n $installed_commit && $installed_commit == "$commit" ]]; then
    echo "You already have the newest Blockstead (${commit:0:7}). Nothing to do."
    exit 0
  fi

  workdir=$(mktemp -d /tmp/blockstead-update.XXXXXX)
  # shellcheck disable=SC2064  # workdir is fixed now; expand it now too.
  trap "rm -rf '$workdir'" EXIT

  echo "Downloading Blockstead ${commit:0:7}…"
  curl --fail --silent --show-error --location --max-time 300 \
    --output "$workdir/source.tar.gz" "https://codeload.github.com/$REPO/tar.gz/$commit"
  mkdir -p "$workdir/source"
  tar -xzf "$workdir/source.tar.gz" -C "$workdir/source"
  extracted=$(find "$workdir/source" -mindepth 1 -maxdepth 1 -type d | head -n 1)
  if [[ -z $extracted || ! -f $extracted/scripts/install-linux.sh ]]; then
    echo "The downloaded update did not contain an installer." >&2
    exit 1
  fi
  chmod +x "$extracted/scripts/install-linux.sh"

  echo "Installing the update…"
  export BLOCKSTEAD_INSTALL_COMMIT=$commit
  export BLOCKSTEAD_INSTALL_COMMIT_AT=$committed_at
  "$extracted/scripts/install-linux.sh" "$@"
}

main "$@"
