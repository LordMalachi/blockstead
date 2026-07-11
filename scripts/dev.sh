#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
trap 'kill 0' EXIT INT TERM
(cd "$root" && "$root/.venv/bin/uvicorn" blockstead.app:app --app-dir backend/src --host 127.0.0.1 --port 8765 --reload) &
npm --prefix "$root/frontend" run dev
