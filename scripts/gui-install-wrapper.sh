#!/usr/bin/env bash
set -euo pipefail

# Get the root directory of Blockstead
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check if zenity is available
if command -v zenity >/dev/null; then
  if ! zenity --question --title="Blockstead Installer" \
    --text="Would you like to install Blockstead Minecraft Dashboard on this computer?\n\nThis will install Blockstead as a system service, create a menu shortcut, and place a launcher on your Desktop." \
    --ok-label="Install" --cancel-label="Cancel" --width=400; then
    exit 0
  fi
fi

# We need to run scripts/install-linux.sh in a terminal so the user can enter their sudo password and see the progress.
# Let's find a terminal emulator.
TERMINAL=""
if command -v x-terminal-emulator >/dev/null; then
  TERMINAL="x-terminal-emulator"
elif command -v gnome-terminal >/dev/null; then
  TERMINAL="gnome-terminal"
elif command -v mate-terminal >/dev/null; then
  TERMINAL="mate-terminal"
elif command -v xfce4-terminal >/dev/null; then
  TERMINAL="xfce4-terminal"
elif command -v konsole >/dev/null; then
  TERMINAL="konsole"
elif command -v lxterminal >/dev/null; then
  TERMINAL="lxterminal"
elif command -v xterm >/dev/null; then
  TERMINAL="xterm"
fi

if [[ -z "$TERMINAL" ]]; then
  if command -v zenity >/dev/null; then
    zenity --error --title="Blockstead Installer" --text="Could not find a terminal emulator. Please run the installer from a terminal:\nsudo ./scripts/install-linux.sh"
  else
    echo "Could not find a terminal emulator. Run: sudo ./scripts/install-linux.sh" >&2
  fi
  exit 1
fi

# Run the installer inside the terminal
if [[ "$TERMINAL" == "gnome-terminal" ]]; then
  gnome-terminal -- bash -c "cd '$ROOT_DIR' && sudo ./scripts/install-linux.sh; echo; read -p 'Press Enter to exit...' -r"
elif [[ "$TERMINAL" == "konsole" ]]; then
  konsole -e bash -c "cd '$ROOT_DIR' && sudo ./scripts/install-linux.sh; echo; read -p 'Press Enter to exit...' -r"
else
  $TERMINAL -e bash -c "cd '$ROOT_DIR' && sudo ./scripts/install-linux.sh; echo; read -p 'Press Enter to exit...' -r"
fi
