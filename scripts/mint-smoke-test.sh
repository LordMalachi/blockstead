#!/usr/bin/env bash
set -euo pipefail
if [[ ! -f /etc/os-release ]]; then echo "Cannot identify this operating system." >&2; exit 1; fi
# shellcheck disable=SC1091  # runtime system file, not part of the repository
. /etc/os-release
echo "OS: ${PRETTY_NAME:-unknown}"
echo "Architecture: $(uname -m)"
if [[ "${ID:-}" != "linuxmint" ]]; then echo "This is not Linux Mint; release acceptance cannot be marked complete." >&2; exit 2; fi
echo "Continue with docs/linux-mint-release-checklist.md; this script does not certify the release."
