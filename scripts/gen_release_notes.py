#!/usr/bin/env python3
"""
从 CHANGELOG.md 或 git tag 生成 Release Notes。
用法:
    python3 scripts/gen_release_notes.py          # 自动检测版本
    python3 scripts/gen_release_notes.py v4.9.0   # 指定版本

输出: 写入 /tmp/release_notes.md
"""
import os
import subprocess
import sys


def get_latest_tag() -> str:
    """从 git 获取最新 tag。"""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, timeout=10, cwd=os.path.dirname(__file__)
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def get_tag_date(tag: str) -> str:
    """获取 tag 的创建日期。"""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ai", tag],
            capture_output=True, text=True, timeout=10, cwd=os.path.dirname(__file__)
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split()[0]
    except Exception:
        pass
    return ""


def get_commits_since_last_tag(tag: str) -> list[str]:
    """获取自上次 tag 以来的 commits。"""
    try:
        prev = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", f"{tag}^"],
            capture_output=True, text=True, timeout=10,
        )
        since = prev.stdout.strip() if prev.returncode == 0 else ""
        if since:
            log = subprocess.run(
                ["git", "log", "--oneline", "--no-decorate", f"{since}..{tag}"],
                capture_output=True, text=True, timeout=10,
            )
        else:
            log = subprocess.run(
                ["git", "log", "--oneline", "--no-decorate", "-20", tag],
                capture_output=True, text=True, timeout=10,
            )
        if log.returncode == 0 and log.stdout.strip():
            return log.stdout.strip().splitlines()
    except Exception:
        pass
    return []


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else ""

    # 从 VERSION 文件或 git tag 读取版本
    if not version:
        version_file = os.path.join(os.path.dirname(__file__), "..", "VERSION")
        try:
            with open(version_file) as f:
                version = f.read().strip()
        except Exception:
            pass

    if not version:
        tag = get_latest_tag()
        if tag:
            version = tag.lstrip("v")

    if not version:
        version = "dev"

    changelog = os.path.join(os.path.dirname(__file__), "..", "CHANGELOG.md")
    tag = f"v{version}"

    output = [f"## ⚡ PJSK Auto Player v{version}", ""]

    date = get_tag_date(tag)
    if date:
        output.append(f"📅 **发布日期**: {date}")
        output.append("")

    # 从 CHANGELOG 提取当前版本条目
    found = False
    if os.path.exists(changelog):
        with open(changelog, encoding="utf-8") as f:
            lines = f.readlines()

        header = f"## [{version}]"
        in_section = False
        for line in lines:
            if line.startswith(header):
                in_section = True
                found = True
                continue
            if in_section and (line.startswith("## [") or line.startswith("# ")):
                break
            if in_section:
                output.append(line.rstrip())

    if not found:
        # 无对应条目，从 git log 生成
        commits = get_commits_since_last_tag(tag)
        if commits:
            output.append("### 🚀 更新内容")
            output.append("")
            for c in commits:
                output.append(f"- {c}")
        else:
            output.append("_No changelog entry for this version._")

    # 下载链接和说明
    output.extend([
        "",
        "---",
        "",
        "### 📦 下载",
        "",
        "| 平台 | 文件 |",
        "|------|------|",
        "| 🪟 Windows | `pjsk-auto-player-windows-x86_64.exe` |",
        "| 🍎 macOS | `pjsk-auto-player-macos-universal` 或 `.dmg` |",
        "| 🐧 Linux | `pjsk-auto-player-linux-x86_64` |",
        "",
        "### 📖 文档",
        "",
        "同目录下包含:",
        "- `README.md` — 完整使用说明",
        "- `TERMS.md` — 法律条款",
        "- `CHANGELOG.md` — 完整变更历史",
        "",
        "### 🚀 使用",
        "",
        "```bash",
        "# macOS/Linux",
        "chmod +x pjsk-auto-player-macos-universal",
        "./pjsk-auto-player-macos-universal setup",
        "",
        "# Windows (双击或命令行)",
        "pjsk-auto-player-windows-x86_64.exe setup",
        "```",
        "",
        "```bash",
        "# Web 控制面板",
        "./pjsk-auto-player-macos-universal web",
        "# → 浏览器打开 http://localhost:8080",
        "```",
        "",
        "---",
        "",
        "⚠️ **法律提示**: 使用本软件可能违反 Project Sekai (SEGA/Colorful Palette) 的服务条款。",
        "请阅读 TERMS.md 后使用。开发者不对任何账号封禁或其他后果负责。",
        "",
    ])

    notes_path = "/tmp/release_notes.md"
    with open(notes_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output) + "\n")

    print(f"✅ Release notes written to {notes_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
