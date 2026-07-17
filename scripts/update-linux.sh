#!/usr/bin/env bash
# Update Blockstead in place: fetch the newest code, then re-run the
# installer, which preserves settings, accounts, backups, and Minecraft
# folders and rolls back automatically if the new version is not healthy.
#
# The whole script runs inside main() so that `git pull` rewriting this file
# cannot confuse the shell that is executing it; main() ends with exec/exit.
set -euo pipefail

main() {
  local root owner yes_flag="" repo_version installed_version before after

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
    --yes) yes_flag=--yes ;;
    *)
      echo "Usage: sudo ./scripts/update-linux.sh [--yes]" >&2
      exit 2
      ;;
  esac

  if [[ ! -d $root/.git ]]; then
    cat >&2 <<EOF
This Blockstead folder is not a git checkout, so it cannot fetch updates
by itself. To update:

  1. Download the newest Blockstead release and extract it to a new folder.
  2. Open a terminal in that new folder.
  3. Run: sudo ./scripts/install-linux.sh

The installer recognizes the existing installation and keeps your settings,
administrator accounts, backups, and Minecraft folders.
EOF
    exit 2
  fi

  command -v git >/dev/null || {
    echo "git is required to fetch updates. Install it with: sudo apt install git" >&2
    exit 1
  }

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
  exec "$root/scripts/install-linux.sh" $yes_flag
}

main "$@"
