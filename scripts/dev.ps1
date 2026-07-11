$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backend = Start-Process -PassThru -NoNewWindow "$root\.venv\Scripts\uvicorn.exe" -ArgumentList "blockstead.app:app", "--app-dir", "backend/src", "--host", "127.0.0.1", "--port", "8765", "--reload"
try { npm --prefix "$root\frontend" run dev } finally { Stop-Process -Id $backend.Id -ErrorAction SilentlyContinue }
