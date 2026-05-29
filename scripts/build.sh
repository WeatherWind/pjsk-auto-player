#!/bin/bash
# PJSK Auto Player 本地打包脚本
# 用法: ./scripts/build.sh [平台]
#   平台: macos (默认), windows (需交叉编译), linux (需交叉编译)
#
# 依赖: pip install pyinstaller opencv-python-headless numpy pyyaml

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PLATFORM="${1:-$(uname -s | tr '[:upper:]' '[:lower:]')}"

echo "🔧 PJSK Auto Player 打包工具 (v4.9.0+)"
echo "========================================"
echo "平台: $PLATFORM"
echo "目录: $PROJECT_DIR"
echo ""

# 检查 PyInstaller
if ! command -v pyinstaller &>/dev/null; then
    echo "📦 安装 PyInstaller..."
    pip install pyinstaller
fi

# 检查依赖
for pkg in opencv-python-headless numpy pyyaml; do
    if ! python -c "import ${pkg%%-*}" 2>/dev/null; then
        echo "📦 安装 $pkg..."
        pip install "$pkg"
    fi
done

# 清理旧构建
echo "🧹 清理旧构建..."
rm -rf build dist *.spec __pycache__

# 版本号
VERSION=$(cat VERSION 2>/dev/null || echo "4.9.0")
echo "📌 版本: $VERSION"

# 预下载 minitouch
echo "📥 下载 minitouch 二进制..."
bash scripts/download_minitouch.sh 2>/dev/null || true

# 通用 PyInstaller 参数
COMMON_ARGS=(
    --onefile
    --add-data "tasks:tasks"
    --add-data "templates:templates"
    --add-data "bin:bin"
    --add-data "config:config"
    --add-data "resource:resource"
    --add-data "README.md:."
    --add-data "TERMS.md:."
    --add-data "CHANGELOG.md:."
    --add-data "VERSION:."
)

# 隐藏导入（v4.9.0 新模块）
HIDDEN_IMPORTS=(
    cv2 numpy yaml
    app cli exceptions config
    controller controller.base controller.adb controller.scrcpy controller.combined
    pipeline pipeline.base pipeline.process pipeline.node pipeline.plugins pipeline.task_data pipeline.scheduler
    scene scene.classifier scene.states scene.transitions
    vision vision.matcher vision.ocr vision.color vision.scene
    web web.app web.websocket
    wizard.setup
    notification.desktop notification.web
    # 旧模块兼容
    pipeline adb_controller screen_analyzer auto_play ocr_reader web_dashboard
    scene_classifier capture_optimizer setup_wizard scrcpy_controller
)

EXTRA_ARGS=""
OUTPUT_NAME="pjsk-auto-player"
EXCLUDES="--exclude-module tkinter --exclude-module matplotlib --exclude-module scipy --exclude-module PIL --exclude-module easyocr --exclude-module pytesseract --exclude-module tensorflow --exclude-module torch --exclude-module pandas"

case "$PLATFORM" in
    darwin|macos)
        echo "🍎 构建 macOS 单文件..."
        OUTPUT_NAME="pjsk-auto-player-macos"
        EXTRA_ARGS="--target-arch universal2 --add-data 'templates:templates' --add-data 'bin:bin'"
        ;;
    windows|win|win32)
        echo "🪟 构建 Windows 单文件..."
        OUTPUT_NAME="pjsk-auto-player.exe"
        # Windows 用 ; 分隔路径
        EXTRA_ARGS="--add-data 'tasks;tasks' --add-data 'templates;templates' --add-data 'bin;bin' --add-data 'config;config' --add-data 'resource;resource' --add-data 'README.md;.' --add-data 'TERMS.md;.' --add-data 'CHANGELOG.md;.' --add-data 'VERSION;.'"
        ;;
    linux)
        echo "🐧 构建 Linux 单文件..."
        OUTPUT_NAME="pjsk-auto-player-linux"
        EXTRA_ARGS=""
        ;;
    *)
        echo "⚠️  未知平台: $PLATFORM, 使用默认配置"
        EXTRA_ARGS=""
        ;;
esac

echo ""
echo "⚡ 开始编译..."
echo "   输出: dist/$OUTPUT_NAME"
echo ""

# 构建 import 参数
IMPORT_ARGS=()
for mod in "${HIDDEN_IMPORTS[@]}"; do
    IMPORT_ARGS+=("--hidden-import" "$mod")
done

pyinstaller \
    "${COMMON_ARGS[@]}" \
    "${IMPORT_ARGS[@]}" \
    $EXCLUDES \
    --name "$OUTPUT_NAME" \
    --console \
    main.py

echo ""
echo "✅ 打包完成!"
echo "   输出文件: dist/$OUTPUT_NAME"
echo "   大小: $(du -h dist/$OUTPUT_NAME 2>/dev/null | cut -f1 || echo 'N/A')"

# macOS 创建 .dmg
if [ "$PLATFORM" = "darwin" ] || [ "$PLATFORM" = "macos" ]; then
    echo ""
    echo "📀 创建 .dmg 磁盘映像..."
    DMG_NAME="pjsk-auto-player-macos-universal.dmg"
    mkdir -p dmg-root
    cp "dist/$OUTPUT_NAME" dmg-root/pjsk-auto-player
    cp README.md TERMS.md CHANGELOG.md VERSION dmg-root/
    chmod +x dmg-root/pjsk-auto-player
    hdiutil create \
        -volname "PJSK Auto Player v${VERSION}" \
        -srcfolder dmg-root \
        -ov \
        -format UDZO \
        "$DMG_NAME"
    mv "$DMG_NAME" "dist/$DMG_NAME"
    rm -rf dmg-root
    echo "   .dmg: dist/$DMG_NAME"
fi

echo ""
echo "🎉 完成!"
