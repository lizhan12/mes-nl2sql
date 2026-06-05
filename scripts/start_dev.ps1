# 开发模式启动脚本 (Windows PowerShell)
# 同时启动后端 (8000) 和前端 (4173)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MES NL2SQL - 开发模式启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$root = Split-Path -Parent $PSScriptRoot

# 从 .env 读取端口，默认 8000
$port = (Select-String -Path "$root\.env" -Pattern '^port\s*=\s*(\d+)' | Select-Object -First 1).Matches.Groups[1].Value
if (-not $port) { $port = "8000" }

# 启动后端
Write-Host "`n[1/2] 启动后端服务 (port $port)..." -ForegroundColor Green
$backend = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; uv run uvicorn src.main:app --reload --host 0.0.0.0 --port $port" -PassThru

# 等待后端就绪
Write-Host "  等待后端启动..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# 启动前端
Write-Host "`n[2/2] 启动前端服务 (port 4173)..." -ForegroundColor Green
$frontend = Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\web'; npm run dev" -PassThru

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  后端:  http://localhost:8000" -ForegroundColor White
Write-Host "  前端:  http://localhost:4173" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "`n按任意键停止所有服务..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

Write-Host "`n正在停止服务..." -ForegroundColor Yellow
if (-not $backend.HasExited) { Stop-Process $backend.Id -Force }
if (-not $frontend.HasExited) { Stop-Process $frontend.Id -Force }
Write-Host "已停止。"
