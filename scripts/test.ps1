$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& "$root\.venv\Scripts\ruff.exe" check "$root\backend"
& "$root\.venv\Scripts\mypy.exe" "$root\backend\src"
& "$root\.venv\Scripts\pytest.exe" "$root\backend"
npm --prefix "$root\frontend" run lint
npm --prefix "$root\frontend" test
npm --prefix "$root\frontend" run build
npm --prefix "$root\frontend" run e2e
