#!/bin/bash
# 生产模式启动脚本 (Linux 服务器)
# 后端直接托管前端静态文件，只启动一个服务

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "========================================"
echo "  MES NL2SQL - 生产模式启动"
echo "========================================"

# 检查并安装后端依赖
if [ ! -d ".venv" ]; then
    echo "[1/3] 创建虚拟环境..."
    uv sync
else
    echo "[1/3] 同步依赖..."
    uv sync
fi

# 检查前端构建产物
if [ ! -d "web/dist" ]; then
    echo "[2/3] 前端构建产物不存在，正在构建..."
    cd web
    npm install --production
    npm run build
    cd ..
else
    echo "[2/3] 前端构建产物已存在，跳过构建"
fi

# 启动后端服务
echo "[3/3] 启动后端服务 (port 8000)..."
echo "========================================"
echo "  服务地址: http://0.0.0.0:8000"
echo "========================================"

uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4
