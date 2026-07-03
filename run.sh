#!/usr/bin/env bash
# ============================================================
#  B站/抖音直播监控 - 一键运行脚本
# ============================================================
#  使用方法:
#    1. 配置 rooms.json 文件（推荐）
#    2. 设置环境变量（可选，用于微信推送）:
#       export BLIVE_CONFIG='{"sendkey": "SCTxxxxxxxxxxxxxx"}'
#    3. 运行: ./run.sh
#
#  或者一行搞定:
#    BLIVE_CONFIG='{"sendkey": "SCTxxx"}' ./run.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/check_status.py"
POST_SCRIPT="$SCRIPT_DIR/check_new_posts.py"

echo "========================================"
echo "  B站/抖音直播监控 v1.0"
echo "========================================"

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] 未找到 python3，请先安装 Python 3"
    exit 1
fi

# 检查主脚本是否存在
if [ ! -f "$PY_SCRIPT" ]; then
    echo "[ERROR] 未找到 $PY_SCRIPT"
    exit 1
fi

# 默认行为
CMD="${1:-once}"

case "$CMD" in
    once|check|1)
        echo "开始检测直播状态..."
        python3 "$PY_SCRIPT"
        echo "检测完成"
        ;;
    posts|2)
        echo "开始检测新作品..."
        ENABLE_POST_CHECK=true python3 "$POST_SCRIPT"
        echo "检测完成"
        ;;
    all|3)
        echo "开始检测直播状态..."
        python3 "$PY_SCRIPT"
        echo "开始检测新作品..."
        ENABLE_POST_CHECK=true python3 "$POST_SCRIPT"
        echo "全部检测完成"
        ;;
    loop|watch|4)
        echo "持续监控模式 (Ctrl+C 停止)..."
        echo "每 60 秒检测一次"
        while true; do
            echo "--- $(date '+%Y-%m-%d %H:%M:%S') ---"
            python3 "$PY_SCRIPT"
            sleep 60
        done
        ;;
    help|h|-h|--help)
        echo "用法: ./run.sh [命令]"
        echo ""
        echo "命令:"
        echo "  once / check   检测一次直播状态（默认）"
        echo "  posts          检测抖音新作品"
        echo "  all            检测直播状态 + 新作品"
        echo "  loop / watch   持续监控（每60秒）"
        echo "  help           显示帮助信息"
        echo ""
        echo "环境变量:"
        echo "  BLIVE_CONFIG   JSON格式配置，如: '{\"sendkey\": \"SCTxxx\"}'"
        echo "  ENABLE_POST_CHECK=true  启用作品检测"
        ;;
    *)
        echo "未知命令: $CMD"
        echo "使用 ./run.sh help 查看帮助"
        exit 1
        ;;
esac
