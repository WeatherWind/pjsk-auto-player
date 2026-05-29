#!/bin/bash
# PJSK Auto Player — 一键启动脚本
# 自动检查依赖 → 安装 → 启动 Web 控制台

set -euo pipefail

cd "$(dirname "$0")"

echo ""
echo "  ╔════════════════════════════════════════╗"
echo "  ║     PJSK Auto Player — 一键启动        ║"
echo "  ╚════════════════════════════════════════╝"
echo ""

# 检查 Python
if ! command -v python3 &>/dev/null && ! command -v python &>/dev/null; then
    echo "❌ Python 未安装。请先安装 Python 3.8+"
    echo "   https://www.python.org/downloads/"
    exit 1
fi
PYTHON=$(command -v python3 || command -v python)
echo "✅ Python: $($PYTHON --version 2>&1)"

# 检查/安装依赖
if ! $PYTHON -c "import cv2, numpy, yaml" 2>/dev/null; then
    echo "📦 安装依赖..."
    $PYTHON -m pip install --upgrade pip -q
    $PYTHON -m pip install -r requirements.txt -q
    echo "✅ 依赖已安装"
else
    echo "✅ 依赖已就绪"
fi

# 检查 ADB
if ! command -v adb &>/dev/null; then
    echo "📦 ADB 未找到，尝试自动下载..."
    # 检测系统
    OS=$(uname -s)
    ARCH=$(uname -m)
    
    if [ "$OS" = "Darwin" ]; then
        URL="https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"
    elif [ "$OS" = "Linux" ]; then
        URL="https://dl.google.com/android/repository/platform-tools-latest-linux.zip"
    else
        echo "❌ 请手动安装 ADB: https://developer.android.com/studio/releases/platform-tools"
        exit 1
    fi
    
    echo "   下载 ADB platform-tools..."
    curl -sL "$URL" -o /tmp/platform-tools.zip 2>&1
    unzip -q -o /tmp/platform-tools.zip -d /tmp/ 2>/dev/null
    export PATH="/tmp/platform-tools:$PATH"
    echo "✅ ADB 已就绪: $(adb --version 2>&1 | head -1)"
else
    echo "✅ ADB: $(adb --version 2>&1 | head -1)"
fi

echo ""
echo "🚀 正在启动桌面应用..."
echo "   控制面板将在浏览器中自动打开"
echo "   如果没有自动打开，请访问 http://localhost:8080"
echo ""
echo "   手机访问: http://<电脑IP>:8080"
echo ""

$PYTHON main.py
