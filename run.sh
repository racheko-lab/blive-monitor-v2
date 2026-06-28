#!/usr/bin/env bash
# ============================================================
#  B站直播监控 - 一键运行脚本
# ============================================================
#  使用方法:
#    1. 设置 SendKey:  export BLIVE_SENDKEY="SCTxxxxxxxxxxxxxx"
#    2. 设置房间:      export BLIVE_ROOMS="1874913653:峰哥亡命天涯"
#    3. 运行:          ./run.sh
#
#  或者一行搞定:
#    BLIVE_SENDKEY="SCTxxx" BLIVE_ROOMS="1874913653:峰哥亡命天涯" ./run.sh
# ============================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/bilibili_live_monitor.py"

echo "========================================"
echo "  B站直播监控 v1.0"
echo "========================================"

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] 未找到 python3，请先安装 Python 3"
    exit 1
fi

# 默认行为
CMD="${1:-once}"

case "$CMD" in
    once|1)
        python3 "$PY_SCRIPT" once
        ;;
    loop|watch|2)
        echo "持续监控模式 (Ctrl+C 停止)..."
        python3 "$PY_SCRIPT" loop
        ;;
    config|c)
        python3 "$PY_SCRIPT" config
        ;;
    test|t)
        python3 "$PY_SCRIPT" test
        ;;
    add|a)
        python3 "$PY_SCRIPT" add
        ;;
    setup|s)
        python3 "$PY_SCRIPT" setup
        ;;
    dry|d|--dry-run|-n)
        shift || true
        python3 "$PY_SCRIPT" "${1:-once}" --dry-run
        ;;
    reset)
        python3 "$PY_SCRIPT" reset
        ;;
    help|h|-h|--help)
        python3 "$PY_SCRIPT" help
        ;;
    *)
        echo "用法: ./run.sh [once|loop|config|test|add|setup|dry|reset|help]"
        ;;
esac
