#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/blockstead
CONFIG_DIR=/etc/blockstead
DATA_DIR=/var/lib/blockstead
LOG_DIR=/var/log/blockstead
SERVER_ROOT=/srv/minecraft
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

usage() {
  cat <<'EOF'
Usage: sudo ./scripts/uninstall-linux.sh [--yes] [--purge] [--remove-minecraft]

Without flags, only the application and its system service are removed;
settings, administrator accounts, backups, and Minecraft folders survive a
reinstall.

  --purge             Also delete settings, administrator accounts, backups,
                      application logs, and the blockstead service account.
  --remove-minecraft  Also delete /srv/minecraft, including every world.
  --yes               Do not ask for confirmation (for scripted use).
EOF
}

if [[ ${EUID} -ne 0 ]]; then echo "Run this uninstaller with sudo." >&2; exit 1; fi
if [[ $(uname -s) != Linux ]]; then echo "Blockstead deployment requires Linux." >&2; exit 1; fi

assume_yes=false
purge=false
remove_minecraft=false
for arg in "$@"; do
  case $arg in
    --yes) assume_yes=true ;;
    --purge) purge=true ;;
    --remove-minecraft) remove_minecraft=true ;;
    --help | -h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

# Never pull the service down while it is still supervising a Minecraft
# process; the owner should stop the server from the dashboard first.
if systemctl is-active --quiet "$SERVICE"; then
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
fi

if [[ $assume_yes == false ]]; then
  echo "This removes the Blockstead application, system service, terminal"
  echo "helper, and menu entry."
  echo
  if [[ $purge == true ]]; then
    echo "Because of --purge, the following will ALSO be deleted:"
    echo "  Settings:                 $CONFIG_DIR"
    echo "  Accounts, data, BACKUPS:  $DATA_DIR"
    echo "  Application logs:         $LOG_DIR"
    echo "  Service account:          blockstead"
  else
    echo "The following owner data will be preserved:"
    echo "  Configuration:   $CONFIG_DIR"
    echo "  Private data:    $DATA_DIR (includes world backups)"
    echo "  Application logs: $LOG_DIR"
  fi
  if [[ $remove_minecraft == true ]]; then
    echo "  Minecraft files: $SERVER_ROOT will be DELETED, including every world."
  else
    echo "  Minecraft files: $SERVER_ROOT is preserved."
  fi
  echo
  read -r -p "Continue? [y/N] " answer
  [[ $answer =~ ^[Yy]$ ]] || { echo "Uninstall cancelled."; exit 0; }
  if [[ $remove_minecraft == true ]]; then
    echo
    echo "Deleting $SERVER_ROOT cannot be undone. Worlds not backed up elsewhere"
    echo "will be gone forever."
    read -r -p 'Type "delete my worlds" to confirm: ' phrase
    [[ $phrase == "delete my worlds" ]] || { echo "Uninstall cancelled; nothing was removed."; exit 0; }
  fi
fi

systemctl disable --now "$SERVICE" 2>/dev/null || true
# The update watcher is a separate unit, so it has to be stopped separately or
# it would sit there waiting to reinstall what was just removed.
systemctl disable --now blockstead-update.path 2>/dev/null || true
rm -f "$UNIT_PATH" "$POWER_HELPER" "$SUDOERS_PATH" "$CLI_PATH" "$DESKTOP_PATH" "$ICON_PATH" \
  "$UPDATE_HELPER" "$UPDATE_PATH_UNIT" "$UPDATE_SERVICE_UNIT"
if [[ -n "${SUDO_USER:-}" ]]; then
  USER_DESKTOP=$(runuser -u "$SUDO_USER" -- xdg-user-dir DESKTOP 2>/dev/null || echo "")
  if [[ -n "$USER_DESKTOP" && -d "$USER_DESKTOP" ]]; then
    rm -f "$USER_DESKTOP/blockstead.desktop"
  fi
fi
rmdir /usr/lib/blockstead 2>/dev/null || true
rm -rf "$APP_DIR"
systemctl daemon-reload
if command -v update-desktop-database >/dev/null; then
  update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null; then
  gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi

if [[ $purge == true ]]; then
  rm -rf "$CONFIG_DIR" "$DATA_DIR" "$LOG_DIR"
  if id -u blockstead >/dev/null 2>&1; then
    userdel blockstead 2>/dev/null || true
  fi
fi
if [[ $remove_minecraft == true ]]; then
  rm -rf "$SERVER_ROOT"
fi

echo "Blockstead was uninstalled."
if [[ $purge == true && $remove_minecraft == true ]]; then
  echo "All Blockstead settings, data, backups, and Minecraft folders were removed."
elif [[ $purge == true ]]; then
  echo "Settings, data, and backups were removed. Your Minecraft folders remain"
  echo "in $SERVER_ROOT."
else
  cat <<EOF
Your configuration, application data, backups, and Minecraft server folders
were preserved. Reinstalling Blockstead will reuse:

  $CONFIG_DIR
  $DATA_DIR
  $SERVER_ROOT

To remove those too, rerun this uninstaller with --purge
(and --remove-minecraft to also delete worlds).
EOF
fi
