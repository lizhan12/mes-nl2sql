# MES NL2SQL Service Restart Script
# Usage: .\restart.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MES NL2SQL Service Restart" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "[1] Stopping old processes on port 8000..." -ForegroundColor Yellow

$connections = netstat -ano | Select-String ":8000.*LISTENING"
if ($connections) {
    foreach ($conn in $connections) {
        $parts = $conn -split '\s+'
        $pid = $parts[$parts.Length - 1]
        if ($pid -and $pid -ne "0") {
            Write-Host "    Found PID: $pid" -ForegroundColor Gray
            try {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                Write-Host "    Killed PID $pid" -ForegroundColor Green
            } catch {
                Write-Host "    PID $pid not found" -ForegroundColor DarkGray
            }
        }
    }
} else {
    Write-Host "    No process listening on port 8000" -ForegroundColor Green
}

Write-Host ""
Write-Host "[2] Waiting for port release..." -ForegroundColor Yellow
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "[3] Starting new service..." -ForegroundColor Yellow
Set-Location $PSScriptRoot
uv run python src/main.py