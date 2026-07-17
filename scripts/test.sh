#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$root/.venv/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Blockstead requires a Python 3.12 virtual environment; run ./scripts/bootstrap-dev.sh"'
"$root/.venv/bin/ruff" check "$root/backend"
"$root/.venv/bin/mypy" --config-file "$root/backend/pyproject.toml" "$root/backend/src"
"$root/.venv/bin/pytest" "$root/backend"
npm --prefix "$root/frontend" run lint
npm --prefix "$root/frontend" test
npm --prefix "$root/frontend" run build
npm --prefix "$root/frontend" run e2e
