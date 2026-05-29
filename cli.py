"""
PJSK Auto Player — CLI 入口

使用示例:
    pjsk start              # 开始执行 (默认模式)
    pjsk auto               # 连续执行
    pjsk calibrate          # 一键校准
    pjsk daemon             # 后台守护进程
    pjsk web                # 启动 Web 控制面板
    pjsk setup              # 设置向导
    pjsk config list        # 列出配置档案
    pjsk config set play.mode ap  # 运行时修改配置
    pjsk status             # 查看运行状态
    pjsk stop               # 停止运行
"""

import argparse
import logging
import os
import sys
import time

# 确保项目根目录在 path 中
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_start(args):
    """启动自动执行。"""
    from app import PjskApp
    app = PjskApp(profile=args.profile)
    app.initialize()
    mode = args.mode or app.config.get("play", {}).get("mode", "live")
    print(f"🎵 开始执行 | 模式: {mode}")
    app.run(mode=mode)


def cmd_auto(args):
    """连续执行。"""
    from app import PjskApp
    app = PjskApp(profile=args.profile)
    app.initialize()
    print("♾️  连续执行 — 自动自动连续")
    app.run(mode="auto", infinite=True)


def cmd_calibrate(args):
    """一键校准。"""
    from app import PjskApp
    app = PjskApp(profile=args.profile)
    app.initialize()
    print("📏 开始校准...")
    app.calibrate()
    print("✅ 校准完成！配置已自动更新。")


def cmd_setup(args):
    """设置向导。"""
    from wizard.setup import SetupWizard
    wizard = SetupWizard(profile=args.profile)
    wizard.run()


def cmd_web(args):
    """启动 Web 控制面板。"""
    from web.app import WebApp
    port = args.port or 8080
    app = WebApp(profile=args.profile, port=port)
    print(f"🌐 Web 控制面板: http://localhost:{port}")
    app.run()


def cmd_daemon(args):
    """后台守护进程模式。"""
    from app import PjskApp
    app = PjskApp(profile=args.profile)
    app.initialize()
    print(f"🔄 守护进程启动 (PID: {os.getpid()})")
    print("   后台运行中... 使用 'pjsk status' 查看状态")
    app.run_daemon()


def cmd_status(args):
    """查看运行状态。"""
    try:
        import json
        import socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock_path = os.path.expanduser("~/.pjskd.sock")
        s.settimeout(3)
        s.connect(sock_path)
        s.sendall(b'{"cmd": "status"}')
        data = s.recv(4096)
        status = json.loads(data.decode())
        print(f"📊 运行状态:")
        print(f"   运行中: {'✅' if status.get('running') else '❌'}")
        print(f"   模式: {status.get('mode', '-')}")
        print(f"   当前任务: {status.get('current_task', '-')}")
        print(f"   歌曲: {status.get('song', '-')}")
        print(f"   帧率: {status.get('fps', 0):.1f} FPS")
        print(f"   点击数: {status.get('clicks', 0)}")
        print(f"   运行时间: {status.get('uptime', '0s')}")
        s.close()
    except Exception as e:
        print(f"❌ 守护进程未运行: {e}")
        print("   启动: pjsk daemon")


def cmd_stop(args):
    """停止运行。"""
    try:
        import json
        import socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock_path = os.path.expanduser("~/.pjskd.sock")
        s.settimeout(3)
        s.connect(sock_path)
        s.sendall(b'{"cmd": "stop"}')
        data = s.recv(4096)
        print("🛑 已发送停止指令")
        s.close()
    except Exception as e:
        print(f"❌ 守护进程未运行: {e}")


def cmd_config(args):
    """配置管理。"""
    from config import get_config_loader
    loader = get_config_loader()
    cfg = loader.load(profile=args.profile)

    if args.config_action == "list":
        profiles = loader.list_profiles()
        print("📁 配置档案:")
        for p in profiles:
            print(f"   - {p}")
        print(f"\n当前配置: {args.profile or 'default'}")

    elif args.config_action == "show":
        import yaml
        print(yaml.dump(cfg, default_flow_style=False, allow_unicode=True))

    elif args.config_action == "set":
        key = args.config_key
        val = args.config_value
        loader.set_local_override(key, val)
        print(f"✅ 已设置: {key} = {val}")

    elif args.config_action == "save":
        loader.save_profile(args.config_name or args.profile or "default", cfg)
        print(f"✅ 配置已保存: {args.config_name or args.profile or 'default'}")

    else:
        print("用法: pjsk config [list|show|set|save] [args]")


def main():
    parser = argparse.ArgumentParser(
        description="PJSK Auto Player — 一站式 Project Sekai 游戏助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  pjsk start             启动自动执行
  pjsk auto              连续执行
  pjsk daemon            后台守护进程
  pjsk web               启动 Web 控制面板
  pjsk setup             设置向导
  pjsk calibrate         一键校准
  pjsk status            查看状态
  pjsk stop              停止运行
  pjsk config list       列出配置档案
  pjsk config set play.mode ap  运行时修改模式
        """,
    )

    parser.add_argument("--profile", "-p", default="", help="配置档案名")
    parser.add_argument("--version", "-v", action="store_true", help="显示版本")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # start
    p_start = subparsers.add_parser("start", help="开始执行")
    p_start.add_argument("--mode", "-m", choices=["ap", "fc", "live", "auto"], help="执行模式")
    p_start.set_defaults(func=cmd_start)

    # auto (连续执行)
    subparsers.add_parser("auto", help="连续执行").set_defaults(func=cmd_auto)

    # calibrate
    subparsers.add_parser("calibrate", help="一键校准").set_defaults(func=cmd_calibrate)

    # setup
    subparsers.add_parser("setup", help="设置向导").set_defaults(func=cmd_setup)

    # web
    p_web = subparsers.add_parser("web", help="Web 控制面板")
    p_web.add_argument("--port", type=int, default=8080, help="端口 (默认 8080)")
    p_web.set_defaults(func=cmd_web)

    # daemon
    subparsers.add_parser("daemon", help="后台守护进程").set_defaults(func=cmd_daemon)

    # status
    subparsers.add_parser("status", help="查看运行状态").set_defaults(func=cmd_status)

    # stop
    subparsers.add_parser("stop", help="停止运行").set_defaults(func=cmd_stop)

    # config
    p_config = subparsers.add_parser("config", help="配置管理")
    p_config.add_argument("config_action", nargs="?", choices=["list", "show", "set", "save"], default="list")
    p_config.add_argument("config_key", nargs="?", help="配置键 (如 play.mode)")
    p_config.add_argument("config_value", nargs="?", help="配置值")
    p_config.add_argument("--name", dest="config_name", help="配置档案名")
    p_config.set_defaults(func=cmd_config)

    args = parser.parse_args()

    if args.version:
        try:
            with open(os.path.join(ROOT_DIR, "VERSION")) as f:
                print(f"PJSK Auto Player v{f.read().strip()}")
        except Exception:
            print("PJSK Auto Player")
        return

    if not args.command:
        parser.print_help()
        return

    setup_logging()
    args.func(args)


if __name__ == "__main__":
    main()
