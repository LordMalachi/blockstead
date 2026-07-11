#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v python3 >/dev/null || { echo "Python is required." >&2; exit 1; }
command -v node >/dev/null || { echo "Node.js is required." >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Blockstead requires Python 3.12.x"'
python3 -m venv "$root/.venv"
"$root/.venv/bin/python" -m pip install --upgrade pip
"$root/.venv/bin/python" -m pip install -e "$root/backend[dev]"
npm --prefix "$root/frontend" ci
mkdir -p "$root/data"
cp -n "$root/.env.example" "$root/.env" || true
echo "Ready. Run ./scripts/dev.sh and open http://127.0.0.1:5173"
