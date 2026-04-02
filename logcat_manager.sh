#!/bin/bash
# logcat 后台进程管理：启动/停止持续日志收集
#
# 用法:
#   ./logcat_manager.sh <设备序列号> start   # 杀旧进程+删旧日志+启新后台logcat
#   ./logcat_manager.sh <设备序列号> stop    # 杀进程+删PID文件（保留日志）
#
# 文件:
#   $SKILL_TMP/logcat.txt  — 持续收集的设备日志
#   $SKILL_TMP/logcat.pid  — 后台 logcat 进程号

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TMP_DIR="${SKILL_TMP:-$SCRIPT_DIR/tmp}"
PID_FILE="$TMP_DIR/logcat.pid"
LOG_FILE="$TMP_DIR/logcat.txt"

DEVICE="${1:?用法: $0 <设备序列号> start|stop}"
ACTION="${2:?用法: $0 <设备序列号> start|stop}"

mkdir -p "$TMP_DIR"

# 杀掉已有的 logcat 后台进程
kill_existing() {
    if [ -f "$PID_FILE" ]; then
        local old_pid
        old_pid=$(cat "$PID_FILE" 2>/dev/null)
        if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
            kill "$old_pid" 2>/dev/null
            # 轮询等待进程退出（最多 2 秒），兼容跨 shell 孤儿进程
            local i=0
            while kill -0 "$old_pid" 2>/dev/null && [ $i -lt 20 ]; do
                sleep 0.1
                i=$((i + 1))
            done
        fi
        rm -f "$PID_FILE"
    fi
}

case "$ACTION" in
    start)
        # 杀旧进程
        kill_existing
        # 删旧日志
        rm -f "$LOG_FILE"
        # 写入会话分隔线（避免 logcat -c 与启动之间的日志丢失窗口）
        echo "=== logcat session start: $(date '+%Y-%m-%d %H:%M:%S') ===" > "$LOG_FILE"
        # 启动后台 logcat
        adb -s "$DEVICE" logcat >> "$LOG_FILE" 2>&1 &
        LOGCAT_PID=$!
        echo "$LOGCAT_PID" > "$PID_FILE"
        # 等待 300ms 确认进程没有立即退出
        sleep 0.3
        if ! kill -0 "$LOGCAT_PID" 2>/dev/null; then
            rm -f "$PID_FILE" "$LOG_FILE"
            echo "错误：logcat 启动失败，设备 $DEVICE 可能未连接" >&2
            exit 1
        fi
        echo "logcat 已启动 (PID=$LOGCAT_PID, 日志: $LOG_FILE)"
        ;;
    stop)
        kill_existing
        if [ -f "$LOG_FILE" ]; then
            echo "logcat 已停止 (日志保留: $LOG_FILE)"
        else
            echo "logcat 已停止"
        fi
        ;;
    *)
        echo "未知操作: $ACTION (支持 start|stop)" >&2
        exit 1
        ;;
esac
