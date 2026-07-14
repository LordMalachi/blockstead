#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/blockstead
CONFIG_DIR=/etc/blockstead
DATA_DIR=/var/lib/blockstead
SERVER_ROOT=/srv/minecraft
SERVICE=blockstead.service

if [[ ${EUID} -ne 0 ]]; then echo "Run this uninstaller with sudo." >&2; exit 1; fi
if [[ $(uname -s) != Linux ]]; then echo "Blockstead deployment requires Linux." >&2; exit 1; fi
if [[ ${1:-} != "" && ${1:-} != --yes ]]; then
  echo "Usage: sudo ./scripts/uninstall-linux.sh [--yes]" >&2
  exit 2
fi

if [[ ${1:-} != --yes ]]; then
  cat <<EOF
This removes the Blockstead application and system service.

The following owner data will be preserved:
  Configuration:   $CONFIG_DIR
  Private data:    $DATA_DIR
  Minecraft files: $SERVER_ROOT
EOF
  read -r -p "Continue? [y/N] " answer
  [[ $answer =~ ^[Yy]$ ]] || { echo "Uninstall cancelled."; exit 0; }
fi

systemctl disable --now "$SERVICE" 2>/dev/null || true
rm -f "/etc/systemd/system/$SERVICE"
rm -f /usr/lib/blockstead/blockstead-power
rm -f /etc/sudoers.d/blockstead-power
rm -rf "$APP_DIR"
systemctl daemon-reload

cat <<EOF
Blockstead was uninstalled. Your configuration, application data, backups, and
Minecraft server folders were preserved. Reinstalling Blockstead will reuse:

  $CONFIG_DIR
  $DATA_DIR
  $SERVER_ROOT
EOF
