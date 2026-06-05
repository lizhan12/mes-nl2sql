# Dev mode startup script (Windows)
# Backend: port from .env (default 8000), Frontend: 4173

$root = Split-Path -Parent $PSScriptRoot

# Read port from .env, default 8000
$port = (Select-String -Path "$root\.env" -Pattern '^PORT\s*=\s*(\d+)' -CaseSensitive:$false | Select-Object -First 1).Matches.Groups[1].Value
if (-not $port) { $port = "8000" }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MES NL2SQL - Dev Mode" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Start backend
$backendCmd = "cd '$root'; uv run uvicorn src.main:app --reload --host 0.0.0.0 --port $port"
Write-Host "[1/2] Starting backend on port $port ..." -ForegroundColor Green
$backend = Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd -PassThru

Start-Sleep -Seconds 3

# Start frontend
Write-Host "[2/2] Starting frontend on port 4173 ..." -ForegroundColor Green
$frontend = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\web'; npm run dev" -PassThru

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Backend : http://localhost:$port" -ForegroundColor White
Write-Host "  Frontend: http://localhost:4173" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Press any key to stop all services..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

Write-Host "Stopping services..." -ForegroundColor Yellow
if (-not $backend.HasExited) { Stop-Process $backend.Id -Force }
if (-not $frontend.HasExited) { Stop-Process $frontend.Id -Force }
Write-Host "Stopped."
