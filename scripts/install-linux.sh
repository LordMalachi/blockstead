#!/usr/bin/env bash
set -euo pipefail
if [[ "${EUID}" -ne 0 ]]; then echo "Run this installer with sudo." >&2; exit 1; fi
if [[ "$(uname -s)" != "Linux" ]]; then echo "Linux is required." >&2; exit 1; fi
echo "Installation preview:"
echo "  application: /opt/blockstead"
echo "  configuration: /etc/blockstead"
echo "  private data: /var/lib/blockstead"
echo "  logs: /var/log/blockstead"
echo "  managed servers: /srv/minecraft"
echo "This milestone installer is a safety preview and does not modify the host."
echo "Production installation remains blocked until Linux Mint validation is completed."
exit 2
