#!/usr/bin/env python3
"""
PJSK Auto Player — 一站式 Project Sekai 游戏助手 (v4.9.0+)

基于 ADB/OpenCV/scrcpy 的自动打歌工具。
吸收 MAA (MaaAssistantArknights) + ALAS (AzurLaneAutoScript) + MaaFramework 精华。

法律提示:
  使用本软件可能违反 Project Sekai (SEGA/Colorful Palette) 的服务条款。
  请仔细阅读 TERMS.md 和 README.md 中的免责声明后使用。
  开发者不对任何账号封禁或其他后果负责。

用法:
    python main.py                          # Web 控制台 (默认 8080)
    python main.py start                    # 开始打歌
    python main.py auto                     # 冲榜模式
    python main.py daemon                   # 后台守护进程
    python main.py calibrate                # 校准
    python main.py setup                    # 设置向导
    python main.py config                   # 配置管理
    python main.py --version                # 版本号
"""

import os
import sys

# 确保项目根目录在 path 中
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def main():
    """入口函数，委派给 cli.py。"""
    from cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
