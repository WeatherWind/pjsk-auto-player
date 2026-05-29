#!/bin/bash
# PJSK Auto Player — macOS 一键启动 (双击即可运行)
# 首次使用可能需要: chmod +x "PJSK Auto Player.command"

cd "$(dirname "$0")"

# 检查 Python3
if ! command -v python3 &>/dev/null; then
    echo "❌ 需要 Python 3.9+"
    echo "   下载: https://www.python.org/downloads/"
    read -p "按 Enter 退出..."
    exit 1
fi

# 自动安装依赖
python3 -c "import cv2, numpy, yaml" 2>/dev/null || {
    echo "📦 首次运行，正在安装依赖..."
    python3 -m pip install --upgrade pip -q
    python3 -m pip install -r requirements.txt -q
    echo "✅ 依赖安装完成"
}

echo ""
echo "🎵 正在启动 PJSK Auto Player..."
echo ""

# 启动桌面模式
python3 main.py
