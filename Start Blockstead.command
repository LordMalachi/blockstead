#!/usr/bin/env bash
# Double-click this in Finder to build and start Blockstead with Docker
# Compose, then open the dashboard in your browser. See scripts/docker-up.sh
# for what it actually does — this file only exists so Finder has something
# to double-click.
set -uo pipefail
cd "$(dirname "$0")" || exit 1

./scripts/docker-up.sh
status=$?

echo
if (( status == 0 )); then
  echo "Done. You can close this window."
else
  echo "Something did not finish. The messages above explain why."
fi
read -r -p "Press Enter to close… "
exit "$status"
