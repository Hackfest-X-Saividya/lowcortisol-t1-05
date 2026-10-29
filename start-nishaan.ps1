# Starts the whole Nishaan app, each part in its own window:
#   2D backend (FastAPI)      http://localhost:8000
#   3D face service (Flask)   http://127.0.0.1:5001
#   web app (Vite)            http://localhost:5173   <- open this one
# The keys come from the .env in this folder (never committed); they are passed to every
# part through the environment, so neither project needs its own .env.
#
# Run:  powershell -ExecutionPolicy Bypass -File start-nishaan.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
  foreach ($line in Get-Content $envFile) {
    if ($line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') { continue }
    $name = $Matches[1]
    $value = $Matches[2].Trim()
    if ($value -match '^"(.*)"$' -or $value -match "^'(.*)'$") { $value = $Matches[1] }
    else { $value = ($value -replace '\s+#.*$', '').Trim() }
    # a variable already set in this shell wins, like python-dotenv
    if ($value -and -not [Environment]::GetEnvironmentVariable($name)) { Set-Item -Path "Env:$name" -Value $value }
  }
} else {
  Write-Warning "No .env found in $root - AI features need GROQ_API_KEY and the other keys."
}

function Start-NishaanPart([string]$title, [string]$dir, [string]$command, [int]$port) {
  if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Write-Warning "$title not started: port $port is already in use (close the other copy first)."
    return
  }
  $script = "`$host.UI.RawUI.WindowTitle = '$title'; $command"
  Start-Process powershell -WorkingDirectory $dir -ArgumentList @("-NoExit", "-Command", $script)
  Write-Host "Started $title on port $port"
}

Start-NishaanPart "Nishaan 2D backend" (Join-Path $root "2D\backend") ".\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000" 8000
Start-NishaanPart "Nishaan 3D face service" (Join-Path $root "3D MODEL") "python backend\server.py" 5001
Start-NishaanPart "Nishaan web app" (Join-Path $root "2D\frontend") "npm run dev" 5173

Write-Host ""
Write-Host "Open http://localhost:5173  (witness window: Evidence index -> 3D model)"
