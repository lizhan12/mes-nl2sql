#!/bin/bash
# ── MES NL2SQL Service 启动脚本（Linux 后台运行） ──
# 用法：
#   ./restart.sh       启动（默认后台运行）
#   ./restart.sh stop  停止
#   ./restart.sh logs  查看最新日志
#   ./restart.sh status 查看运行状态
set -euo pipefail

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
# 从 .env 读取端口，未配置时默认 8000
PORT=$(grep -oP '^PORT=\K\d+' "$PROJ_DIR/.env" 2>/dev/null || echo "8000")
LOG_DIR="$PROJ_DIR/logs"
PID_FILE="$LOG_DIR/service.pid"
LOG_FILE="$LOG_DIR/service.log"

ACTION="${1:-start}"

# ── 工具函数 ──
_cyan()  { echo -e "\033[36m$*\033[0m"; }
_green() { echo -e "\033[32m$*\033[0m"; }
_red()   { echo -e "\033[31m$*\033[0m"; }
_yellow(){ echo -e "\033[33m$*\033[0m"; }

# ── status ──
_show_status() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            _green "[RUNNING] PID=$pid  Port=$PORT"
            return 0
        else
            _yellow "[STALE] PID 文件存在但进程不存在，清理..."
            rm -f "$PID_FILE"
            return 1
        fi
    fi
    _red "[STOPPED] 服务未运行"
    return 1
}

# ── stop ──
_stop() {
    echo "========================================"
    echo -e "  \033[36mMES NL2SQL Service - Stop\033[0m"
    echo "========================================"

    # 1. 按 PID 文件杀
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Killing PID $pid ..."
            kill "$pid" 2>/dev/null || true
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
            _green "  Stopped PID $pid"
        fi
        rm -f "$PID_FILE"
    fi

    # 2. 按端口清理（兜底，避免孤儿进程）
    if command -v lsof &>/dev/null; then
        local pids
        pids=$(lsof -ti :$PORT 2>/dev/null || true)
        if [ -n "$pids" ]; then
            for p in $pids; do
                echo "  Killing orphan PID $p (port $PORT) ..."
                kill "$p" 2>/dev/null || true
                sleep 0.5
                kill -9 "$p" 2>/dev/null || true
            done
            _green "  Port $PORT released"
        fi
    fi

    echo ""
}

# ── logs ──
_logs() {
    if [ ! -f "$LOG_FILE" ]; then
        echo "日志文件不存在: $LOG_FILE"
        exit 1
    fi
    tail -f "$LOG_FILE"
}

# ── main ──
case "$ACTION" in
    stop)
        _stop
        ;;
    status)
        _show_status
        ;;
    logs)
        _logs
        ;;
    start)
        # 先停旧的
        _stop

        # 确保环境
        mkdir -p "$LOG_DIR"

        echo "========================================"
        echo -e "  \033[36mMES NL2SQL Service - Start\033[0m"
        echo "========================================"
        echo "  Project : $PROJ_DIR"
        echo "  Port    : $PORT"
        echo "  Log     : $LOG_FILE"
        echo "  PID     : $PID_FILE"
        echo ""

        cd "$PROJ_DIR"

        echo "[1] Starting service in background..."
        nohup uv run python src/main.py \
            >> "$LOG_FILE" 2>&1 &
        svc_pid=$!
        echo "$svc_pid" > "$PID_FILE"
        _green "  PID=$svc_pid"

        # 等待端口监听
        echo "[2] Waiting for port $PORT ..."
        for i in $(seq 1 30); do
            if ss -tlnp 2>/dev/null | grep -q ":$PORT " || netstat -tlnp 2>/dev/null | grep -q ":$PORT "; then
                _green "  Port $PORT is listening"
                break
            fi
            sleep 1
        done

        echo ""
        echo "========================================"
        _green "  Service started successfully!"
        echo "========================================"
        echo "  查看日志 : ./restart.sh logs"
        echo "  查看状态 : ./restart.sh status"
        echo "  停止服务 : ./restart.sh stop"
        echo ""
        ;;
    *)
        echo "用法: $0 {start|stop|status|logs}"
        exit 1
        ;;
esac
