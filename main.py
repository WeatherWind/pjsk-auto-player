#!/usr/bin/env python3
"""
PJSK Auto Player - 主入口

基于 ADB + OpenCV 的 Project Sekai 自动打歌。
纯 Web 操控 · 原生窗口 · 无需命令行。

法律提示:
  使用本软件可能违反 Project Sekai (SEGA/Colorful Palette) 的服务条款。
  请仔细阅读 TERMS.md 和 README.md 中的免责声明后使用。
  开发者不对任何账号封禁或其他后果负责。

用法:
    python main.py                          # Web 控制台 (原生窗口/浏览器)
    python main.py --port 9090              # 指定端口
    python main.py start                    # CLI 模式: 自动打歌
    python main.py auto                     # CLI 模式: 冲榜
    python main.py calibrate                # 校准
    python main.py setup                    # 设置向导
    python main.py --version                # 版本号
"""

import argparse
import logging
import os
import sys
import time
import shutil

import yaml


# ──────────────────────────────────────────
# 配置管理 (含 Profile 支持)
# ──────────────────────────────────────────

DEFAULT_CONFIG_PATH = "config.yaml"
PROFILES_DIR = "profiles"


def load_config(path: str = "config.yaml", profile: str = "") -> dict:
    """加载 YAML 配置文件, 支持 profile。"""
    # 如果指定了 profile, 尝试从 profiles 目录加载
    if profile:
        profile_path = os.path.join(PROFILES_DIR, f"{profile}.yaml")
        if os.path.exists(profile_path):
            print(f"📁 使用配置档案: {profile} ({profile_path})")
            with open(profile_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            if config is None:
                print(f"❌ 配置文件为空: {profile_path}")
                sys.exit(1)
            return _post_process_config(config)

        # 尝试从 profile 名称直接找文件
        if os.path.exists(profile):
            print(f"📁 使用配置文件: {profile}")
            with open(profile, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            if config is None:
                print(f"❌ 配置文件为空: {profile}")
                sys.exit(1)
            return _post_process_config(config)

        print(f"⚠️  配置档案 '{profile}' 不存在, 回退到默认配置")

    if not os.path.exists(path):
        print(f"❌ 配置文件不存在: {path}")
        print(f"   请确保当前目录下有 {path} 文件")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if config is None:
        print(f"❌ 配置文件为空: {path}")
        sys.exit(1)

    return _post_process_config(config)


def _post_process_config(config: dict) -> dict:
    """对加载的配置进行后处理 (路径展开 + 必填校验)。"""
    # 校验必填字段
    required = {
        "screen": ["width", "height", "judgment_line_y"],
        "adb": ["executable"],
        "detection": ["method"],
    }
    for section, fields in required.items():
        if section not in config:
            print(f"⚠️  配置缺少 {section} 段, 使用默认值")
            config[section] = {}
        for field in fields:
            if field not in config.get(section, {}):
                print(f"⚠️  配置 {section}.{field} 未设置, 使用默认值")

    # 路径展开
    debug_dir = config.get("debug", {}).get("debug_dir", "debug_output")
    if debug_dir.startswith("~"):
        debug_dir = os.path.expanduser(debug_dir)
        config["debug"]["debug_dir"] = debug_dir
    return config


def save_config(config: dict, path: str = "config.yaml", profile: str = ""):
    """保存配置到文件。"""
    if profile:
        os.makedirs(PROFILES_DIR, exist_ok=True)
        save_path = os.path.join(PROFILES_DIR, f"{profile}.yaml")
    else:
        save_path = path

    with open(save_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False,
                  allow_unicode=True, sort_keys=False)
    print(f"💾 配置已保存: {save_path}")


def list_profiles():
    """列出所有可用的配置档案。"""
    os.makedirs(PROFILES_DIR, exist_ok=True)
    profiles = [f.replace(".yaml", "") for f in os.listdir(PROFILES_DIR)
                if f.endswith(".yaml")]
    if profiles:
        print("📁 可用的配置档案:")
        for p in sorted(profiles):
            profile_path = os.path.join(PROFILES_DIR, f"{p}.yaml")
            size = os.path.getsize(profile_path)
            mtime = os.path.getmtime(profile_path)
            time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
            print(f"   - {p}  ({size} bytes, last modified {time_str})")
    else:
        print("📁 暂无配置档案")


# ──────────────────────────────────────────
# 法律合规确认 (首次使用提示)
# ──────────────────────────────────────────


AGREED_FLAG = ".legal_agreed"


def _check_legal_acknowledgment() -> bool:
    """检查用户是否已确认法律条款。首次运行显示提示。"""
    flag_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), AGREED_FLAG)
    if os.path.exists(flag_path):
        return True

    print()
    print("  ╔══════════════════════════════════════════════════════╗")
    print("  ║  ⚠️  法律提示 / Legal Notice                        ║")
    print("  ║                                                     ║")
    print("  ║  PJSK Auto Player 是一个自动化工具。                ║")
    print("  ║  根据 Project Sekai 利用規約第9条:                  ║")
    print("  ║  「自動操作ツール（マクロ）の利用」被明确禁止。    ║")
    print("  ║                                                     ║")
    print("  ║  使用本软件可能导致账号封禁。                       ║")
    print("  ║  请仔细阅读 TERMS.md 了解完整条款。                 ║")
    print("  ║                                                     ║")
    print("  ║  开发者不对任何账号损失承担责任。                   ║")
    print("  ╚══════════════════════════════════════════════════════╝")
    print()
    print("  输入 Y 确认已了解风险并继续, 其他任意键退出")
    ans = input("  [y/N]: ").strip().lower()
    if ans != "y" and ans != "yes":
        print("  已退出。")
        return False

    # 创建确认标记 (仅一次)
    try:
        with open(flag_path, "w") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        print("  ✅ 已记录确认, 下次不再显示此提示")
    except Exception:
        pass
    return True


# ──────────────────────────────────────────
# 日志配置
# ──────────────────────────────────────────


def setup_logging(config: dict):
    """配置日志。"""
    level_name = config.get("debug", {}).get("log_level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    ))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


# ──────────────────────────────────────────
# 命令处理
# ──────────────────────────────────────────


def cmd_start(config: dict, mode: str = "FC"):
    """启动自动打歌。"""
    from auto_play import AutoPlayer

    # 法律确认
    if not _check_legal_acknowledgment():
        return

    player = AutoPlayer(config, mode=mode)

    print()
    print("  ╔══════════════════════════════════╗")
    print("  ║   PJSK Auto Player - 自动打歌    ║")
    print("  ╚══════════════════════════════════╝")
    print()
    print("  请确保:")
    print("    1. 手机已通过 USB 连接到电脑")
    print("    2. USB 调试已开启")
    print("    3. PJSK 已打开, 选好歌曲")
    print("    4. 准备好进入打歌画面")
    print()
    print("  热键 (运行时):")
    print("    P - 暂停/继续     Q - 退出      M - 切换模式")
    print("    + - 延迟+5       - - 延迟-5")
    print("    > - 阈值+5       < - 阈值-5")
    print("    [ - 抖动-3ms     ] - 抖动+3ms   \\ - 随机化开关")
    print()
    input("  按 Enter 开始自动打歌...")

    player.start()


def cmd_calibrate(config: dict, interactive: bool = False,
                  profile: str = ""):
    """运行校准。"""
    from auto_play import Calibrator

    cal = Calibrator(config)

    if interactive:
        cal.interactive_calibrate()
        # 交互式校准后保存配置
        if profile:
            save_config(config, profile=profile)
        else:
            save_config(config)
    else:
        results = cal.run_all()

    # 列出可用档案
    if profile:
        list_profiles()


def cmd_auto(config: dict, count: int = 0, infinite: bool = False,
             combo: str = "", team: str = "", mode: str = "FC"):
    """启动冲榜模式: 自动连续打歌。"""
    # 法律确认
    if not _check_legal_acknowledgment():
        return

    # 先应用编队 (如需)
    if team:
        from team_builder import TeamBuilder
        from adb_controller import ADBController
        adb = ADBController(config)
        if adb.wait_for_device(timeout=10):
            tb = TeamBuilder(config, team_name=team)
            if tb.team:
                logger.info(f"应用编队: {tb.team.name}")
                tb.navigate_to_team_screen(adb)
                tb.apply(adb)

    if combo:
        # 歌单模式
        from combo_player import ComboPlayer
        song_count = 0 if infinite else count
        player = ComboPlayer(config, combo_name=combo, song_count=song_count)

        print()
        print("  ╔══════════════════════════════════╗")
        print(f"  ║   PJSK — {player.combo.name:<17} ║")
        print("  ╚══════════════════════════════════╝")
        print()
        print(f"  歌单: {player.combo.description}")
        print(f"  曲目: {len(player.combo)} 首")
        print(f"  目标: {'无限' if infinite else f'{count} 首'}")

        if not combo:
            print()
            input("  按 Enter 开始...")
        player.start()
        return

    from auto_play import BatchPlayer

    if infinite:
        song_count = 0
    else:
        song_count = count

    player = BatchPlayer(config, song_count=song_count, mode=mode)

    print()
    print("  ╔══════════════════════════════════╗")
    print("  ║   PJSK Auto Player - 冲榜模式    ║")
    print("  ╚══════════════════════════════════╝")
    print()
    if song_count > 0:
        print(f"  目标: 连续打 {song_count} 首")
    else:
        print("  目标: 无限循环 (按 Ctrl+C 停止)")
    print()
    print("  请确保:")
    print("    1. 手机已通过 USB 连接到电脑")
    print("    2. USB 调试已开启")
    print("    3. PJSK 已打开, 选好歌曲")
    print("    4. 准备好进入打歌画面")
    print()
    input("  按 Enter 开始冲榜...")

    player.start()


def cmd_web(config: dict, port: int = 8080, bind: str = "0.0.0.0"):
    """启动 Web 仪表盘。"""
    from web_dashboard import run_server
    run_server(host=bind, port=port)


def cmd_minitouch_setup(config: dict):
    """下载并配置 minitouch 二进制。"""
    import subprocess
    from adb_controller import ADBController

    print("🔧 Minitouch 设置工具")
    print("=" * 40)

    adb = ADBController(config)

    # 检测设备架构
    arch = adb._get_device_arch()
    if not arch:
        print("❌ 无法检测设备架构, 请确保设备已连接")
        return
    print(f"📱 设备架构: {arch}")

    # 创建二进制目录
    bin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "minitouch")
    os.makedirs(bin_dir, exist_ok=True)

    # 下载 URL
    url = (f"https://github.com/DeviceFarmer/minitouch/releases/"
           f"latest/download/minitouch-{arch}")

    print(f"📥 下载: {url}")
    try:
        import urllib.request
        urllib.request.urlretrieve(url, os.path.join(bin_dir, f"minitouch_{arch}"))
        print("✅ 下载成功")
    except Exception as e:
        print(f"❌ 下载失败: {e}")
        print("   请手动下载: https://github.com/DeviceFarmer/minitouch/releases")
        return

    # 设置执行权限
    os.chmod(os.path.join(bin_dir, f"minitouch_{arch}"), 0o755)
    print("✅ minitouch 已就绪, 路径: bin/minitouch/minitouch_{arch}")
    print("   启动打歌时自动推送和使用")


def cmd_test(config: dict, loop: bool = False):
    """测试 ADB 连接和截图。"""
    from adb_controller import ADBController

    adb = ADBController(config)

    print("🔍 测试 ADB 连接...")
    devices = adb.devices()

    if not devices:
        print("❌ 未检测到设备!")
        print("   请检查:")
        print("     - USB 线是否连接")
        print("     - 手机上 USB 调试是否开启")
        print("     - adb devices 是否能识别设备")
        return

    print(f"✅ 检测到 {len(devices)} 台设备:")
    for d in devices:
        print(f"   - {d['serial']} ({d['status']})")

    if len(devices) > 1 and not config["adb"].get("device_serial"):
        print("⚠️  发现多台设备, 请在 config.yaml 中设置 device_serial")

    print("\n📸 测试截图...")
    frame = adb.screencap()
    if frame is None:
        print("❌ 截图失败!")
        return

    h, w = frame.shape[:2]
    print(f"✅ 截图成功: {w}x{h}")
    print(f"   数据大小: {frame.nbytes / 1024:.1f} KB")

    # 延迟测量
    print("\n⏱  测量延迟...")
    latency = adb.measure_latency(samples=3)
    if "screencap_avg_ms" in latency:
        print(f"   截图延迟: {latency['screencap_avg_ms']:.1f}ms")
    if "tap_avg_ms" in latency:
        print(f"   触摸延迟: {latency['tap_avg_ms']:.1f}ms")
    if "total_avg_ms" in latency:
        print(f"   总延迟:   {latency['total_avg_ms']:.1f}ms")

    if loop:
        print("\n🔄 持续测试模式 (按 Ctrl+C 停止)...")
        frame_count = 0
        try:
            while True:
                t0 = time.perf_counter()
                frame = adb.screencap()
                t1 = time.perf_counter()
                frame_count += 1
                ms = (t1 - t0) * 1000
                if frame is not None:
                    print(f"   [{frame_count}] 截图耗时: {ms:.1f}ms  "
                          f"尺寸: {frame.shape[1]}x{frame.shape[0]}")
                else:
                    print(f"   [{frame_count}] 截图失败!")
                time.sleep(0.5)
        except KeyboardInterrupt:
            print(f"\n   共测试 {frame_count} 帧")


# ──────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="PJSK Auto Player - Project Sekai 自动打歌",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py start                         # 启动自动打歌
  python main.py start --profile expert        # 使用 expert 档案
  python main.py calibrate                     # 自动校准参数
  python main.py calibrate -i                  # 交互式校准
  python main.py calibrate --profile phone2    # 校准时保存到指定档案
  python main.py test                          # 测试连接
  python main.py test --loop                   # 持续测试截图性能
  python main.py profiles                      # 列出配置档案
  python main.py auto                          # 冲榜模式 (5首)
  python main.py auto -n 20                   # 冲榜模式 (20首)
  python main.py auto --infinite               # 无限冲榜
        """
    )

    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="配置文件路径 (默认: config.yaml)"
    )
    parser.add_argument(
        "-V", "--version",
        action="store_true",
        help="显示版本号"
    )

    sub = parser.add_subparsers(dest="command", help="命令")

    # start
    start_parser = sub.add_parser("start", help="启动自动打歌")
    start_parser.add_argument(
        "--mode", default="FC",
        choices=["AP", "FC", "LIVE"],
        help="打歌模式: AP=AllPerfect, FC=FullCombo(默认), LIVE=通关"
    )
    start_parser.add_argument(
        "--profile", default="",
        help="使用指定配置档案 (profiles/<name>.yaml)"
    )

    # calibrate
    cal_parser = sub.add_parser("calibrate", help="校准参数")
    cal_parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="交互式校准模式 (显示实时预览)"
    )
    cal_parser.add_argument(
        "--profile", default="",
        help="校准结果保存到指定配置档案"
    )
    cal_parser.add_argument(
        "--speed", action="store_true",
        help="自动检测游戏速度并调整预测参数 (额外录制 8 秒)"
    )

    # test
    test_parser = sub.add_parser("test", help="测试 ADB 连接")
    test_parser.add_argument(
        "--loop",
        action="store_true",
        help="持续截图测试"
    )

    # profiles
    sub.add_parser("profiles", help="列出配置档案")

    # web dashboard
    web_parser = sub.add_parser("web", help="启动 Web 仪表盘 (手机端监控)")
    web_parser.add_argument(
        "--port", type=int, default=8080,
        help="端口 (默认: 8080)"
    )
    web_parser.add_argument(
        "--bind", default="0.0.0.0",
        help="绑定地址 (默认: 0.0.0.0)"
    )

    # minitouch-setup
    sub.add_parser("minitouch-setup", help="下载并配置 minitouch 二进制")

    # setup
    setup_parser = sub.add_parser("setup", help="设置向导: 一键检测设备 + 校准 + 配置")
    setup_parser.add_argument(
        "--auto", action="store_true",
        help="自动模式 (无需交互)"
    )

    # auto (冲榜模式)
    auto_parser = sub.add_parser("auto", help="冲榜模式: 自动连续打歌")
    auto_parser.add_argument(
        "--mode", default="FC",
        choices=["AP", "FC", "LIVE"],
        help="基础打歌模式 (冲榜时自动浮动: FC为主, AP/LIVE为辅)"
    )
    auto_parser.add_argument(
        "-n", "--count", type=int, default=5,
        help="打歌次数 (默认: 5)"
    )
    auto_parser.add_argument(
        "--infinite", action="store_true",
        help="无限循环 (直到手动停止)"
    )
    auto_parser.add_argument(
        "--combo", default="",
        help="歌单名称 (combos/ 目录下的歌单, 如 grind-single)"
    )
    auto_parser.add_argument(
        "--team", default="",
        help="编队模板名称 (teams/ 目录下的编队, 如 event-grind)"
    )
    auto_parser.add_argument(
        "--profile", default="",
        help="使用指定配置档案"
    )

    # combos
    sub.add_parser("combos", help="列出可用歌单")

    # teams
    sub.add_parser("teams", help="列出可用编队模板")

    args = parser.parse_args()

    if not args.command:
        if args.version:
            vp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
            if os.path.exists(vp):
                with open(vp) as f:
                    print(f"PJSK Auto Player v{f.read().strip()}")
            else:
                print("PJSK Auto Player (version unknown)")
            return
        from web_dashboard import run
        run()
        return

    # profiles 命令不需要加载配置
    if args.command == "profiles":
        list_profiles()
        return

    # web 和 minitouch-setup 不需要配置
    if args.command == "web":
        from web_dashboard import run_server
        run_server(host=args.bind, port=args.port)
        return

    if args.command == "minitouch-setup":
        from adb_controller import ADBController
        cmd_minitouch_setup({})
        return

    if args.command == "setup":
        from setup_wizard import SetupWizard
        wizard = SetupWizard(auto=args.auto)
        wizard.run()
        return

    # combos 不需要加载配置
    if args.command == "combos":
        from combo_player import ComboPlayer
        cp = ComboPlayer({})
        combos = cp.list_combos()
        print("📁 可用歌单:")
        print()
        for c in combos:
            print(f"  {c['key']:20s}  {c['name']} ({c['songs']} 首)")
            if c['description']:
                print(f"  {'':20s}  {c['description']}")
            print()
        return

    if args.command == "teams":
        from team_builder import TeamBuilder
        tb = TeamBuilder({})
        teams = tb.list_teams()
        print("📁 可用编队:")
        print()
        for t in teams:
            print(f"  {t['key']:20s}  {t['name']} ({t['method']})")
            if t['description']:
                print(f"  {'':20s}  {t['description']}")
            print()
        return

    # 加载配置 (支持 profile)
    config = load_config(args.config, getattr(args, 'profile', ''))

    # 设置日志
    setup_logging(config)

    # 执行命令
    if args.command == "start":
        cmd_start(config, mode=args.mode)
    elif args.command == "auto":
        cmd_auto(config, count=args.count, infinite=args.infinite,
                 combo=args.combo, team=args.team, mode=args.mode)
    elif args.command == "calibrate":
        cmd_calibrate(config, interactive=args.interactive,
                      profile=args.profile)
        if args.speed:
            from auto_play import Calibrator
            cal = Calibrator(config)
            cal.detect_game_speed()
    elif args.command == "test":
        cmd_test(config, loop=args.loop)


if __name__ == "__main__":
    main()
