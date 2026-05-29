#!/usr/bin/env bash
# PJSK Auto Player — 预下载 minitouch 二进制文件
# 
# minitouch (https://github.com/DeviceFarmer/minitouch) 是一个安卓
# 触摸守护进程，提供 <5ms 的触摸延迟。
#
# 本脚本从多个源尝试下载预编译二进制。
# 如果下载失败，也可以手动编译:
#   git clone https://github.com/DeviceFarmer/minitouch
#   cd minitouch && make
#   将编译好的文件重命名为 minitouch_<arch> 放入 bin/minitouch/
#
# 用法:
#   bash scripts/download_minitouch.sh                # 下载所有架构
#   bash scripts/download_minitouch.sh arm64 arm      # 仅指定架构
#
# 输出: bin/minitouch/minitouch_<arch>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$PROJECT_DIR/bin/minitouch"
mkdir -p "$OUTPUT_DIR"

# 支持的架构
ARCHES=("${@:-arm64 arm x86_64 x86}")

# 多个下载源（按优先级）
declare -A SOURCES
SOURCES["github_latest"]="https://github.com/DeviceFarmer/minitouch/releases/latest/download/minitouch-{arch}"
SOURCES["github_tag"]="https://github.com/DeviceFarmer/minitouch/releases/download/1.0.0/minitouch-{arch}"
# maatouch (MAA fork, more maintained)
SOURCES["maatouch"]="https://github.com/MaaAssistantArknights/maatouch/releases/latest/download/maatouch-{arch}"

echo "📥 PJSK Auto Player — Minitouch 预下载工具"
echo "============================================"
echo "输出目录: $OUTPUT_DIR"
echo "架构: ${ARCHES[*]}"
echo ""

for ARCH in "${ARCHES[@]}"; do
    OUTPUT_FILE="$OUTPUT_DIR/minitouch_${ARCH}"

    if [ -f "$OUTPUT_FILE" ] && [ -x "$OUTPUT_FILE" ]; then
        SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
        echo "  ✅ $ARCH 已存在 ($SIZE)"
        continue
    fi

    DOWNLOADED=false
    for SOURCE_NAME in "${!SOURCES[@]}"; do
        URL="${SOURCES[$SOURCE_NAME]}"
        URL="${URL//\{arch\}/$ARCH}"

        echo "  ⏳ 尝试 $SOURCE_NAME ($ARCH) ..."
        HTTP_CODE=$(curl -sL -w "%{http_code}" -o "$OUTPUT_FILE" "$URL" 2>/dev/null || echo "000")

        if [ "$HTTP_CODE" = "200" ]; then
            chmod +x "$OUTPUT_FILE"
            SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
            echo "  ✅ $ARCH 下载成功 (来源: $SOURCE_NAME, $SIZE)"
            DOWNLOADED=true
            break
        else
            rm -f "$OUTPUT_FILE"
        fi
    done

    if [ "$DOWNLOADED" = false ]; then
        echo "  ⚠️  $ARCH 所有源均下载失败"
        echo "     请手动编译: https://github.com/DeviceFarmer/minitouch"
        echo "     编译后放入: $OUTPUT_DIR/minitouch_${ARCH}"
    fi
done

echo ""
echo "📊 当前 minitouch 二进制:"
ls -lh "$OUTPUT_DIR" 2>/dev/null || echo "  (无)"
echo ""
echo "💡 提示: 成功下载的二进制会自动被 ADBController 使用"
echo "   也可以通过 python main.py minitouch-setup 触发下载"
