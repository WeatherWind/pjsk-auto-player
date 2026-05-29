#!/usr/bin/env python3
"""
从 CHANGELOG.md 提取当前版本的 Release Notes。
用法: python3 scripts/gen_release_notes.py <version>
输出: 写入 /tmp/release_notes.md
"""
import sys
import os


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else ""
    if not version:
        # 从 VERSION 文件读取
        version_file = os.path.join(os.path.dirname(__file__), "..", "VERSION")
        with open(version_file) as f:
            version = f.read().strip()

    changelog = os.path.join(os.path.dirname(__file__), "..", "CHANGELOG.md")
    lines = open(changelog).readlines()

    output = [f"### ⚡ PJSK Auto Player v{version}", ""]

    # 提取当前版本条目
    found = False
    in_section = False
    header = f"## [{version}]"
    for line in lines:
        if line.startswith(header):
            in_section = True
            found = True
            continue
        if in_section and line.startswith("## ["):
            break
        if in_section:
            output.append(line.rstrip())

    if not found:
        # 无对应版本条目，用 git log 兜底
        output.append("")
        output.append("_No CHANGELOG entry found for this version._")
        output.append("")
        output.append("Recent commits:")
        os.system(
            "git log --oneline --no-decorate -10 origin/main 2>/dev/null"
            " | while read line; do echo \"- $line\"; done"
        )

    output.extend([
        "",
        "---",
        "",
        "📦 **下载**: 选择对应平台的单文件可执行文件即可直接运行",
        "📖 **文档**: 附带的 README.md / TERMS.md / CHANGELOG.md",
        "",
        "⚠️ **法律提示**: 使用本软件可能违反 Project Sekai 服务条款，请阅读 TERMS.md",
        "",
    ])

    notes_path = "/tmp/release_notes.md"
    with open(notes_path, "w") as f:
        f.write("\n".join(output) + "\n")

    print(f"Release notes written to {notes_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
