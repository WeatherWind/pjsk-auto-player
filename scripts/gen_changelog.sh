#!/bin/bash
# 自动生成 CHANGELOG.md + 更新 README 版本历史
# 在 git tag 后运行: ./scripts/gen_changelog.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
cd "$REPO_DIR"

echo "📝 生成更新日志..."

# 获取所有 tag (按版本排序)
TAGS=$(git tag --sort=-version:refname 2>/dev/null)
if [ -z "$TAGS" ]; then
    echo "  ⚠️  没有 tag, 跳过"
    exit 0
fi

# 生成 CHANGELOG.md
cat > CHANGELOG.md << 'EOF'
# Changelog

所有 notable 变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/).

EOF

FIRST=true
while IFS= read -r TAG; do
    VERSION="${TAG#v}"
    DATE=$(git log -1 --format="%ai" "$TAG" 2>/dev/null | cut -d' ' -f1 || echo "未知")

    echo "## [$VERSION] - $DATE" >> CHANGELOG.md
    echo "" >> CHANGELOG.md

    # 获取此 tag 的 commit message
    MSG=$(git log -1 --format="%s" "$TAG" 2>/dev/null || echo "")
    echo "- $MSG" >> CHANGELOG.md
    echo "" >> CHANGELOG.md

    FIRST=false
done <<< "$TAGS"

echo "  ✅ CHANGELOG.md 已更新"

# 更新 README 版本亮点表
echo "  更新 README 版本亮点表..."

# 构建新表格行 (只保留最新的 8 个版本)
ROWS=""
COUNT=0
while IFS= read -r TAG; do
    VERSION="${TAG#v}"
    MSG=$(git log -1 --format="%s" "$TAG" 2>/dev/null | sed 's/^v[0-9.]*: //' || echo "")
    
    if [ $COUNT -eq 0 ]; then
        ROWS="$ROWS| **v$VERSION** 🆕 | $MSG |\n"
    else
        ROWS="$ROWS| **v$VERSION** | $MSG |\n"
    fi
    
    COUNT=$((COUNT + 1))
    if [ $COUNT -ge 8 ]; then
        break
    fi
done <<< "$TAGS"

# 更新 README (替换版本亮点表)
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS sed
    sed -i '' '/^| \*\*v.*\*\* 🆕 |.*|$/,/^$/c\
| 版本 | 特性 |\
|------|------|'"$(printf "$ROWS" | sed 's/$/\\/')"'
' README.md
else
    echo "  ⚠️  自动更新 README 仅支持 macOS (sed 差异)"
    echo "  请手动更新 README 版本表"
fi

echo "✅ 更新日志完成"
