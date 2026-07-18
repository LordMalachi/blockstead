#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALLER="$ROOT_DIR/scripts/install-linux.sh"
WINDOW_ICON="$ROOT_DIR/packaging/icons/blockstead.svg"
DESKTOP_USER=$(id -un)

show_terminal_installer() {
  local terminal="" root_quoted user_quoted command
  if command -v x-terminal-emulator >/dev/null; then
    terminal=x-terminal-emulator
  elif command -v gnome-terminal >/dev/null; then
    terminal=gnome-terminal
  elif command -v mate-terminal >/dev/null; then
    terminal=mate-terminal
  elif command -v xfce4-terminal >/dev/null; then
    terminal=xfce4-terminal
  elif command -v konsole >/dev/null; then
    terminal=konsole
  elif command -v xterm >/dev/null; then
    terminal=xterm
  fi

  if [[ -z $terminal ]]; then
    printf 'Could not find a graphical authorization helper or terminal.\n' >&2
    printf 'Run this instead: sudo bash %q\n' "$INSTALLER" >&2
    return 1
  fi

  printf -v root_quoted '%q' "$ROOT_DIR"
  printf -v user_quoted '%q' "$DESKTOP_USER"
  command="cd $root_quoted && sudo env BLOCKSTEAD_INSTALL_USER=$user_quoted bash ./scripts/install-linux.sh; status=\$?; echo; if (( status == 0 )); then echo 'Blockstead is ready. You may close this window.'; else echo 'Installation did not finish. The messages above explain why.'; fi; read -r -p 'Press Enter to close…'; exit \$status"

  case $terminal in
    gnome-terminal | mate-terminal)
      "$terminal" -- bash -c "$command"
      ;;
    konsole)
      "$terminal" -e bash -c "$command"
      ;;
    *)
      "$terminal" -e bash -c "$command"
      ;;
  esac
}

if ! command -v zenity >/dev/null || ! command -v pkexec >/dev/null; then
  show_terminal_installer
  exit $?
fi

mode=install
verb=Install
if [[ -d /opt/blockstead ]]; then
  mode=update
  verb=Update
fi

if ! zenity --question \
    --title="${verb} Blockstead" \
    --window-icon="$WINDOW_ICON" \
    --text="<big><b>${verb} Blockstead?</b></big>\n\nBlockstead will run as a background service, add its app icon, and keep Minecraft worlds in <tt>/srv/minecraft</tt>.\n\nYour administrator password is needed once to ${mode} system files. Existing worlds, settings, and backups are preserved." \
    --ok-label="$verb" \
    --cancel-label="Not now" \
    --width=470; then
  exit 0
fi

install_log=$(mktemp /tmp/blockstead-installer.XXXXXX.log)
chmod 0600 "$install_log"

set +e
pkexec bash "$INSTALLER" --yes >"$install_log" 2>&1 &
install_pid=$!
set -e

(
  while kill -0 "$install_pid" 2>/dev/null; do
    printf '# Building and installing Blockstead…\nThis can take a few minutes the first time.\n'
    sleep 1
  done
) | zenity --progress \
  --title="${verb}ing Blockstead" \
  --window-icon="$WINDOW_ICON" \
  --text="Preparing Blockstead…" \
  --pulsate \
  --auto-close \
  --no-cancel \
  --width=470 || true

set +e
wait "$install_pid"
status=$?
set -e

if (( status != 0 )); then
  recent=$(tail -n 18 "$install_log" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g')
  zenity --error \
    --title="Blockstead was not installed" \
    --window-icon="$WINDOW_ICON" \
    --text="<big><b>Installation did not finish.</b></big>\n\nThe most recent messages were:\n\n<tt>$recent</tt>\n\nThe complete log is saved at <tt>$install_log</tt>." \
    --width=650
  exit "$status"
fi

rm -f "$install_log"

if command -v notify-send >/dev/null; then
  notify-send --app-name=Blockstead --icon="$WINDOW_ICON" \
    "Blockstead is ready" "Opening your Minecraft server dashboard."
fi

if ! /usr/local/bin/blockstead launch; then
  zenity --warning \
    --title="Blockstead is installed" \
    --window-icon="$WINDOW_ICON" \
    --text="Blockstead was installed successfully, but the browser did not open.\n\nOpen <tt>http://127.0.0.1:8765</tt>, or click the Blockstead app icon." \
    --width=470
fi
