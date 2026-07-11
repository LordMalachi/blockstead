#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
npm --prefix "$root/frontend" ci
npm --prefix "$root/frontend" run build
"$root/.venv/bin/python" -m build "$root/backend"
