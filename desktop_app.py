#!/usr/bin/env python3
"""
PJSK Auto Player — 桌面应用 (Desktop App)

开箱即用的桌面体验：
  - 双击启动 → 自动打开浏览器控制面板
  - 首次运行自动进入设置向导
  - 系统托盘图标（可选）
  - 一键打歌/冲榜/暂停/停止

零命令行依赖 — 适合不熟悉终端的用户。

用法:
    python desktop_app.py              # 桌面模式 (默认)
    python desktop_app.py --tray       # 系统托盘模式
    python desktop_app.py --wizard     # 强制设置向导
    python desktop_app.py --start      # 直接开始打歌
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logger = logging.getLogger("pjsk.desktop")


# ═══════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════

APP_NAME = "PJSK Auto Player"
APP_ICON = "🎵"
DEFAULT_PORT = 8080
DASHBOARD_URL = f"http://localhost:{DEFAULT_PORT}"


# ═══════════════════════════════════════════════════════════════
# 首次运行检测
# ═══════════════════════════════════════════════════════════════


def is_first_run() -> bool:
    """检测是否首次运行（无配置文件、无校准数据）。"""
    # 检查是否存在配置文件
    config_paths = [
        ROOT_DIR / "config.yaml",
        ROOT_DIR / "config" / "local.yaml",
    ]
    has_config = any(p.exists() for p in config_paths)

    # 检查是否同意过法律条款
    legal_agreed = Path.home() / ".pjsk_legal_agreed"
    has_agreed = legal_agreed.exists()

    # 检查是否有 profile
    profiles_dir = ROOT_DIR / "config" / "profiles"
    has_profile = profiles_dir.exists() and any(profiles_dir.iterdir())

    return not (has_config or has_agreed or has_profile)


def show_first_run_wizard():
    """显示首次运行向导。"""
    print("\n" + "=" * 60)
    print("  🎵 欢迎使用 PJSK Auto Player！")
    print("  检测到这是首次运行，正在启动设置向导...")
    print("=" * 60 + "\n")

    try:
        from wizard.setup import SetupWizard
        wizard = SetupWizard()
        wizard.run()
    except ImportError:
        print("⚠️  设置向导模块不可用，请手动配置 config.yaml")
        print(f"   配置文件位置: {ROOT_DIR / 'config.yaml'}")
        input("\n按 Enter 继续...")


# ═══════════════════════════════════════════════════════════════
# Web 服务器启动器
# ═══════════════════════════════════════════════════════════════


def start_web_server(port: int = DEFAULT_PORT) -> threading.Thread:
    """在后台线程启动 Web 服务器。

    Returns:
        服务器线程对象
    """
    def _run_server():
        try:
            from web.app import WebApp
            app = WebApp(host="0.0.0.0", port=port)
            app.run()
        except Exception as e:
            logger.error("Web server failed: %s", e)

    thread = threading.Thread(target=_run_server, daemon=True, name="web-server")
    thread.start()

    # 等待服务器就绪
    for _ in range(50):  # 最多等 5 秒
        try:
            s = socket.create_connection(("localhost", port), timeout=0.1)
            s.close()
            return thread
        except (socket.error, OSError):
            time.sleep(0.1)

    logger.warning("Web server may not be ready yet")
    return thread


# ═══════════════════════════════════════════════════════════════
# 浏览器启动
# ═══════════════════════════════════════════════════════════════


def open_dashboard(port: int = DEFAULT_PORT):
    """在默认浏览器中打开控制面板。"""
    url = f"http://localhost:{port}"
    print(f"\n  🌐 正在打开控制面板: {url}")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"  ⚠️  无法自动打开浏览器: {e}")
        print(f"  请手动打开: {url}")


# ═══════════════════════════════════════════════════════════════
# 系统托盘 (可选, 需要 pystray)
# ═══════════════════════════════════════════════════════════════


_tray_icon = None


def setup_system_tray(port: int = DEFAULT_PORT):
    """设置系统托盘图标（需要 pystray 库）。

    提供菜单操作：开始打歌、暂停、停止、打开面板、退出。
    """
    global _tray_icon

    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        logger.info("pystray 未安装，跳过系统托盘 (pip install pystray Pillow)")
        return None

    # 创建简单图标
    def _create_icon():
        img = Image.new("RGB", (64, 64), color=(30, 30, 40))
        draw = ImageDraw.Draw(img)
        # 画一个音符符号 🎵
        draw.ellipse([16, 8, 48, 40], fill=(100, 180, 255))
        draw.rectangle([44, 24, 52, 56], fill=(100, 180, 255))
        draw.ellipse([36, 8, 56, 32], fill=(255, 180, 60))
        return img

    def _on_start(icon, item):
        print("\n  🎵 开始打歌...")
        try:
            _send_command("start", {"mode": "FC"})
        except Exception as e:
            print(f"  ❌ {e}")

    def _on_stop(icon, item):
        print("\n  🛑 停止打歌")
        try:
            _send_command("stop")
        except Exception as e:
            print(f"  ❌ {e}")

    def _on_open(icon, item):
        open_dashboard(port)

    def _on_quit(icon, item):
        print("\n  👋 退出 PJSK Auto Player")
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("🎵 开始打歌", _on_start, default=True),
        pystray.MenuItem("🛑 停止", _on_stop),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("🌐 打开控制面板", _on_open),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ 退出", _on_quit),
    )

    _tray_icon = pystray.Icon(
        "pjsk-auto-player",
        _create_icon(),
        APP_NAME,
        menu,
    )

    return _tray_icon


def _send_command(action: str, extra: dict | None = None):
    """向 daemon 或 web 服务器发送命令。"""
    import urllib.request

    cmd = {"action": action}
    if extra:
        cmd.update(extra)

    data = json.dumps(cmd).encode()
    req = urllib.request.Request(
        f"http://localhost:{DEFAULT_PORT}/command",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.debug("Command failed: %s", e)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════


def print_banner():
    """打印启动横幅。"""
    try:
        vp = ROOT_DIR / "VERSION"
        version = vp.read_text().strip()
    except Exception:
        version = "4.x"

    print(f"""
  ╔══════════════════════════════════════════════╗
  ║                                              ║
  ║       🎵  PJSK Auto Player  v{version:<10}    ║
  ║          Project Sekai 自动打歌助手            ║
  ║                                              ║
  ║   控制面板: {DASHBOARD_URL:<29}  ║
  ║   手机访问: http://<电脑IP>:{DEFAULT_PORT:<22} ║
  ║                                              ║
  ╚══════════════════════════════════════════════╝
""")


def print_quick_guide():
    """打印快速操作指南。"""
    print("""  ┌─ 快速操作 ─────────────────────────────────┐
  │                                              │
  │   🌐 控制面板已在浏览器中打开                  │
  │      如果没有自动打开，请手动访问上方地址       │
  │                                              │
  │   ⌨️  终端快捷键:                              │
  │      [S] 开始打歌    [P] 暂停                 │
  │      [Q] 退出        [W] 设置向导              │
  │      [O] 重新打开浏览器                        │
  │                                              │
  │   📱 确保:                                    │
  │      1. 手机已通过 USB 连接                   │
  │      2. USB 调试已开启                        │
  │      3. 游戏在主界面或选歌界面                  │
  │                                              │
  └──────────────────────────────────────────────┘
""")


def run_desktop(
    port: int = DEFAULT_PORT,
    use_tray: bool = False,
    auto_start: bool = False,
    force_wizard: bool = False,
    skip_browser: bool = False,
):
    """桌面模式主入口。

    Args:
        port: Web 服务器端口
        use_tray: 是否使用系统托盘
        auto_start: 是否自动开始打歌
        force_wizard: 是否强制显示设置向导
        skip_browser: 是否跳过打开浏览器
    """
    print_banner()

    # 首次运行检测
    if force_wizard or is_first_run():
        show_first_run_wizard()

    # 启动 Web 服务器
    print("  ⏳ 正在启动服务...")
    server_thread = start_web_server(port)
    print(f"  ✅ 服务已启动: http://localhost:{port}")

    # 启动 PjskApp
    app_instance = None
    try:
        from app import PjskApp
        app_instance = PjskApp()
        app_instance.initialize()
        print("  ✅ 设备控制器已就绪")

        # 初始化 Web 全局引用
        try:
            from web.app import init
            init(app_instance=app_instance, config=app_instance.config)
        except Exception:
            pass

    except Exception as e:
        print(f"  ⚠️  设备初始化失败: {e}")
        print("     Web 控制面板仍然可用，但需要先连接设备")

    print_quick_guide()

    # 打开浏览器
    if not skip_browser:
        time.sleep(0.5)  # 等待服务器完全就绪
        open_dashboard(port)

    # 自动开始打歌
    if auto_start and app_instance:
        print("\n  🎵 自动开始打歌...")
        try:
            app_thread = threading.Thread(
                target=app_instance.run, kwargs={"mode": "live"}, daemon=True
            )
            app_thread.start()
        except Exception as e:
            print(f"  ❌ 自动打歌失败: {e}")

    # 系统托盘
    tray_thread = None
    if use_tray:
        tray_icon = setup_system_tray(port)
        if tray_icon:
            def _run_tray():
                tray_icon.run()
            tray_thread = threading.Thread(target=_run_tray, daemon=True)
            tray_thread.start()
            print("  📌 系统托盘已启用")

    # 注册退出处理
    def _cleanup():
        print("\n  🧹 正在清理...")
        if app_instance:
            app_instance.stop()

    atexit.register(_cleanup)
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    # 交互式终端控制
    print("\n  💡 提示: 在下方输入快捷键，或直接使用浏览器控制面板\n")

    try:
        while True:
            try:
                cmd = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if cmd in ("q", "quit", "exit"):
                break
            elif cmd in ("s", "start"):
                print("  🎵 开始打歌...")
                _send_command("start")
            elif cmd in ("p", "pause"):
                if app_instance:
                    if app_instance.paused:
                        app_instance.resume()
                        print("  ▶️  已恢复")
                    else:
                        app_instance.pause()
                        print("  ⏸️  已暂停")
            elif cmd in ("w", "wizard", "setup"):
                show_first_run_wizard()
            elif cmd in ("o", "open"):
                open_dashboard(port)
            elif cmd in ("h", "help", "?"):
                print_quick_guide()
            elif cmd == "":
                continue
            else:
                print(f"  未知命令: {cmd} (输入 h 查看帮助)")

    finally:
        print("\n  👋 PJSK Auto Player 已退出")
        if app_instance:
            app_instance.stop()


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} — 桌面应用",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
示例:
  python desktop_app.py                桌面模式 (推荐)
  python desktop_app.py --tray         系统托盘模式
  python desktop_app.py --wizard       强制设置向导
  python desktop_app.py --start        直接开始打歌
  python desktop_app.py --no-browser   不打开浏览器
        """,
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Web 服务器端口")
    parser.add_argument("--tray", action="store_true", help="启用系统托盘")
    parser.add_argument("--wizard", action="store_true", help="强制显示设置向导")
    parser.add_argument("--start", action="store_true", help="自动开始打歌")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    run_desktop(
        port=args.port,
        use_tray=args.tray,
        auto_start=args.start,
        force_wizard=args.wizard,
        skip_browser=args.no_browser,
    )


if __name__ == "__main__":
    main()
