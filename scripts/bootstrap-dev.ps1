$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
py -3.12 -m venv "$root\.venv"
& "$root\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$root\.venv\Scripts\python.exe" -m pip install -e "$root\backend[dev]"
npm --prefix "$root\frontend" ci
if (!(Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env" }
Write-Host "Ready. Run .\scripts\dev.ps1 and open http://127.0.0.1:5173"
