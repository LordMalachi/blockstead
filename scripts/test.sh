#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$root/.venv/bin/ruff" check "$root/backend"
"$root/.venv/bin/mypy" "$root/backend/src"
"$root/.venv/bin/pytest" "$root/backend"
npm --prefix "$root/frontend" run lint
npm --prefix "$root/frontend" test
npm --prefix "$root/frontend" run build
npm --prefix "$root/frontend" run e2e
