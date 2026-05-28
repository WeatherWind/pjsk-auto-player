#!/usr/bin/env python3
"""
PJSK Auto Player - 主入口

基于 ADB + OpenCV 的 Project Sekai (プロジェクトセカイ) 自动打歌工具。

用法:
    python main.py start                    # 启动自动打歌
    python main.py start --profile expert   # 使用 expert 配置档案
    python main.py calibrate                # 运行校准 (延迟/判定线/轨道)
    python main.py calibrate -i             # 交互式校准 (实时预览)
    python main.py calibrate --profile expert  # 校准并保存到 expert 档案
    python main.py test                     # 测试截图和 ADB 连接
    python main.py test --loop              # 持续截图测试
    python main.py auto                     # 冲榜模式: 连续打 5 首
    python main.py auto -n 20              # 连续打 20 首
    python main.py auto --infinite          # 无限循环
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
    """对加载的配置进行后处理 (路径展开等)。"""
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


def cmd_start(config: dict):
    """启动自动打歌。"""
    from auto_play import AutoPlayer

    player = AutoPlayer(config)

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
    print("    P - 暂停/继续     Q - 退出")
    print("    + - 延迟+5ms      - - 延迟-5ms")
    print("    > - 阈值+5        < - 阈值-5")
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


def cmd_auto(config: dict, count: int = 0, infinite: bool = False):
    """启动冲榜模式: 自动连续打歌。"""
    from auto_play import BatchPlayer

    if infinite:
        song_count = 0
    else:
        song_count = count

    player = BatchPlayer(config, song_count=song_count)

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

    sub = parser.add_subparsers(dest="command", help="命令")

    # start
    start_parser = sub.add_parser("start", help="启动自动打歌")
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

    # test
    test_parser = sub.add_parser("test", help="测试 ADB 连接")
    test_parser.add_argument(
        "--loop",
        action="store_true",
        help="持续截图测试"
    )

    # profiles
    sub.add_parser("profiles", help="列出配置档案")

    # auto (冲榜模式)
    auto_parser = sub.add_parser("auto", help="冲榜模式: 自动连续打歌")
    auto_parser.add_argument(
        "-n", "--count", type=int, default=5,
        help="打歌次数 (默认: 5)"
    )
    auto_parser.add_argument(
        "--infinite", action="store_true",
        help="无限循环 (直到手动停止)"
    )
    auto_parser.add_argument(
        "--profile", default="",
        help="使用指定配置档案"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # profiles 命令不需要加载配置
    if args.command == "profiles":
        list_profiles()
        return

    # 加载配置 (支持 profile)
    config = load_config(args.config, getattr(args, 'profile', ''))

    # 设置日志
    setup_logging(config)

    # 执行命令
    if args.command == "start":
        cmd_start(config)
    elif args.command == "auto":
        cmd_auto(config, count=args.count, infinite=args.infinite)
    elif args.command == "calibrate":
        cmd_calibrate(config, interactive=args.interactive,
                      profile=args.profile)
    elif args.command == "test":
        cmd_test(config, loop=args.loop)


if __name__ == "__main__":
    main()
