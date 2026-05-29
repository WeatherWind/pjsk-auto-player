#!/usr/bin/env python3
"""
PJSK Auto Player — 一站式 Project Sekai 游戏助手 (v4.11.0+)

基于 ADB/OpenCV/scrcpy 的自动执行工具。
吸收 MAA (MaaAssistantArknights) + ALAS (AzurLaneAutoScript) + MaaFramework 精华。

开箱即用：
    python main.py                          # 🖥️ 桌面模式 (自动打开浏览器控制面板)
    python main.py desktop                  # 同上

进阶用法:
    python main.py start                    # 开始执行
    python main.py auto                     # 连续执行
    python main.py daemon                   # 后台守护进程
    python main.py calibrate                # 校准
    python main.py setup                    # 设置向导
    python main.py config                   # 配置管理
    python main.py --version                # 版本号

法律提示:
  使用本软件可能违反 Project Sekai (SEGA/Colorful Palette) 的服务条款。
  请仔细阅读 TERMS.md 和 README.md 中的免责声明后使用。
"""

import os
import sys

# 确保项目根目录在 path 中
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def main():
    """入口函数。

    无参数时启动原生 GUI（像 MAA 一样）。
    desktop 参数启动 Web 桌面模式。
    其他参数委派给 cli.py。
    """
    # 无参数 → 原生 GUI (MAA 风格)
    if len(sys.argv) <= 1:
        from native_gui import PjskGui
        gui = PjskGui()
        gui.run()
        return

    # desktop → Web 桌面模式
    if sys.argv[1] == "desktop":
        from desktop_app import run_desktop
        run_desktop()
        return

    # gui → 原生 GUI
    if sys.argv[1] == "gui":
        from native_gui import PjskGui
        gui = PjskGui()
        gui.run()
        return

    from cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
