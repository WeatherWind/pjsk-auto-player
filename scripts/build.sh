#!/bin/bash
# PJSK Auto Player 打包脚本
# 用法: ./scripts/build.sh [平台]
#   平台: macos (默认), windows (需交叉编译), linux (需交叉编译)
#
# 依赖: pip install pyinstaller

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PLATFORM="${1:-$(uname -s | tr '[:upper:]' '[:lower:]')}"

echo "🔧 PJSK Auto Player 打包工具"
echo "================================"
echo "平台: $PLATFORM"
echo "目录: $PROJECT_DIR"
echo ""

# 检查 PyInstaller
if ! command -v pyinstaller &>/dev/null; then
    echo "📦 安装 PyInstaller..."
    pip install pyinstaller
fi

# 清理旧构建
echo "🧹 清理旧构建..."
rm -rf build dist *.spec __pycache__

# 版本号
VERSION=$(cat VERSION 2>/dev/null || echo "3.2.0")
echo "📌 版本: $VERSION"

# 根据平台选择参数
EXTRA_ARGS=""
OUTPUT_NAME="pjsk-auto-player"

case "$PLATFORM" in
    darwin|macos)
        echo "🍎 构建 macOS 可执行..."
        EXTRA_ARGS="--target-arch universal2"
        OUTPUT_NAME="pjsk-auto-player-macos"
        ;;
    windows|win|win32)
        echo "🪟 构建 Windows 可执行..."
        EXTRA_ARGS="--add-data 'tasks;tasks' --add-data 'templates;templates'"
        OUTPUT_NAME="pjsk-auto-player.exe"
        ;;
    linux)
        echo "🐧 构建 Linux 可执行..."
        EXTRA_ARGS="--add-data 'tasks:tasks' --add-data 'templates:templates'"
        OUTPUT_NAME="pjsk-auto-player-linux"
        ;;
    *)
        echo "❌ 未知平台: $PLATFORM"
        echo "   支持: macos, windows, linux"
        exit 1
        ;;
esac

# 执行打包
echo ""
echo "📦 打包中..."
pyinstaller \
    --onefile \
    --name "$OUTPUT_NAME" \
    --add-data "tasks:tasks" \
    --add-data "templates:templates" \
    --hidden-import cv2 \
    --hidden-import numpy \
    --hidden-import yaml \
    --hidden-import pipeline \
    --hidden-import adb_controller \
    --hidden-import screen_analyzer \
    --hidden-import auto_play \
    --hidden-import ocr_reader \
    --hidden-import web_dashboard \
    --exclude-module tkinter \
    --exclude-module matplotlib \
    --exclude-module scipy \
    --exclude-module PIL \
    --exclude-module easyocr \
    --exclude-module pytesseract \
    --exclude-module pandas \
    --exclude-module torch \
    --console \
    main.py

echo ""
echo "✅ 打包完成!"
echo "   输出: dist/$OUTPUT_NAME"
echo "   大小: $(du -sh dist/$OUTPUT_NAME 2>/dev/null | cut -f1 || echo 'N/A')"

# 显示帮助
echo ""
echo "📋 用法:"
echo "   ./dist/$OUTPUT_NAME start           # 启动自动打歌"
echo "   ./dist/$OUTPUT_NAME auto -n 10     # 冲榜模式"
echo "   ./dist/$OUTPUT_NAME calibrate       # 校准"
echo "   ./dist/$OUTPUT_NAME test            # 测试连接"
echo "   ./dist/$OUTPUT_NAME web             # Web 仪表盘"
