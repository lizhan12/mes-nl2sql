#!/bin/bash
# 生产模式启动脚本 (Linux 服务器)
# 用法:
#   bash scripts/start_prod.sh         前台启动（Ctrl+C 停止）
#   bash scripts/start_prod.sh start   后台启动
#   bash scripts/start_prod.sh stop    停止服务
#   bash scripts/start_prod.sh restart 重启服务
#   bash scripts/start_prod.sh status  查看状态

set -e

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PID_FILE="$ROOT_DIR/.server.pid"
LOG_FILE="$ROOT_DIR/logs/server.log"

# 从 .env 读取端口，默认 8000
PORT=$(grep -i -oP '^PORT\s*=\s*\K\d+' .env 2>/dev/null || echo "8000")

# ---- helpers ----
kill_port() {
    local pid
    pid=$(lsof -ti :"$PORT" 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "[端口] 端口 $PORT 被占用 (PID: $pid)，正在释放..."
        kill -9 $pid 2>/dev/null || true
        sleep 1
        echo "[端口] 已释放"
    fi
}

check_deps() {
    if [ ! -d ".venv" ]; then
        echo "[依赖] 创建虚拟环境..."
        uv sync
    else
        echo "[依赖] 同步依赖..."
        uv sync
    fi
}

check_frontend() {
    if [ ! -d "web/dist" ]; then
        echo "[前端] 构建产物不存在，正在构建..."
        cd web
        npm install --production
        npm run build
        cd ..
    else
        echo "[前端] 构建产物已存在，跳过构建"
    fi
}

# ---- commands ----
start_fg() {
    echo "========================================"
    echo "  MES NL2SQL - 前台启动"
    echo "========================================"
    kill_port
    check_deps
    check_frontend
    echo "[启动] 后端服务 (port $PORT)..."
    echo "  服务地址: http://0.0.0.0:$PORT"
    echo "  按 Ctrl+C 停止"
    echo "========================================"
    uv run uvicorn src.main:app --host 0.0.0.0 --port "$PORT" --workers 4
}

start_bg() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "[提示] 服务已在运行 (PID: $(cat "$PID_FILE"), port: $PORT)"
        return 1
    fi

    echo "========================================"
    echo "  MES NL2SQL - 后台启动"
    echo "========================================"
    kill_port
    check_deps
    check_frontend

    mkdir -p logs
    echo "[启动] 后端服务 (port $PORT)..."
    nohup uv run uvicorn src.main:app --host 0.0.0.0 --port "$PORT" --workers 4 \
        >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    sleep 2
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "  服务地址: http://0.0.0.0:$PORT"
        echo "  PID: $(cat "$PID_FILE")"
        echo "  日志: $LOG_FILE"
        echo "========================================"
    else
        echo "[错误] 启动失败，请查看日志: $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_svc() {
    if [ ! -f "$PID_FILE" ]; then
        echo "[提示] 服务未在运行（无 PID 文件）"
        return 0
    fi

    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "[停止] 正在停止服务 (PID: $PID)..."
        kill "$PID"
        sleep 2
        if kill -0 "$PID" 2>/dev/null; then
            echo "[停止] 强制终止..."
            kill -9 "$PID"
        fi
        echo "[停止] 服务已停止"
    else
        echo "[提示] PID $PID 已不存在，清理 PID 文件"
    fi
    rm -f "$PID_FILE"
}

status_svc() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "状态: 运行中"
        echo "PID: $(cat "$PID_FILE")"
        echo "端口: $PORT"
        echo "日志: $LOG_FILE"
    else
        echo "状态: 未运行"
        [ -f "$PID_FILE" ] && echo "(残留 PID 文件: $PID_FILE)"
    fi
}

# ---- main ----
case "${1:-}" in
    start)
        start_bg
        ;;
    stop)
        stop_svc
        ;;
    restart)
        stop_svc
        sleep 1
        start_bg
        ;;
    status)
        status_svc
        ;;
    *)
        start_fg
        ;;
esac
