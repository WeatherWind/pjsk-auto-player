#!/usr/bin/env python3
"""
PJSK Auto Player - 主入口

基于 ADB + OpenCV 的 Project Sekai (プロジェクトセカイ) 自动打歌工具。

用法:
    python main.py start       # 启动自动打歌
    python main.py calibrate   # 运行校准 (延迟/判定线/轨道)
    python main.py calibrate --interactive  # 交互式校准(实时预览)
    python main.py test        # 测试截图和 ADB 连接
    python main.py test --loop # 持续截图测试 (按 Ctrl+C 停止)
"""

import argparse
import logging
import os
import sys
import time

import yaml


def load_config(path: str = "config.yaml") -> dict:
    """加载 YAML 配置文件。"""
    if not os.path.exists(path):
        print(f"❌ 配置文件不存在: {path}")
        print(f"   请确保当前目录下有 config.yaml 文件")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 处理 ~ 和相对路径
    debug_dir = config.get("debug", {}).get("debug_dir", "debug_output")
    if debug_dir.startswith("~"):
        debug_dir = os.path.expanduser(debug_dir)
        config["debug"]["debug_dir"] = debug_dir

    return config


def setup_logging(config: dict):
    """配置日志。"""
    level_name = config.get("debug", {}).get("log_level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = (
        "\033[36m%(asctime)s\033[0m "
        "\033[32m%(name)s\033[0m "
        "%(levelname)s "
        "%(message)s"
    )

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
    input("  按 Enter 开始自动打歌...")

    player.start()


def cmd_calibrate(config: dict, interactive: bool = False):
    """运行校准。"""
    from auto_play import Calibrator

    cal = Calibrator(config)

    if interactive:
        cal.interactive_calibrate()
    else:
        results = cal.run_all()

        if results:
            # 输出配置更新建议
            print("\n📝 将以下内容更新到 config.yaml:\n")
            print("screen:")
            print(f"  width: {config['screen']['width']}")
            print(f"  height: {config['screen']['height']}")
            if "judgment_line_y_ratio" in results:
                print(f"  judgment_line_y: {results['judgment_line_y_ratio']}")
            if "left_lanes" in results and results["left_lanes"]:
                print(f"  left_lanes: {results['left_lanes']}")
            if "right_lanes" in results and results["right_lanes"]:
                print(f"  right_lanes: {results['right_lanes']}")
            if "recommended_compensation_ms" in results:
                comp = results["recommended_compensation_ms"]
                print("\ntiming:")
                print(f"  latency_compensation_ms: {comp}")
            print()


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
                print(f"   [{frame_count}] 截图耗时: {ms:.1f}ms  "
                      f"尺寸: {frame.shape[1]}x{frame.shape[0]}" if frame is not None
                      else f"   [{frame_count}] 截图失败!")
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
  python main.py start              # 启动自动打歌
  python main.py calibrate          # 自动校准参数
  python main.py calibrate -i       # 交互式校准 (实时预览)
  python main.py test               # 测试连接
  python main.py test --loop        # 持续测试截图性能
        """
    )

    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="配置文件路径 (默认: config.yaml)"
    )

    sub = parser.add_subparsers(dest="command", help="命令")

    # start
    sub.add_parser("start", help="启动自动打歌")

    # calibrate
    cal_parser = sub.add_parser("calibrate", help="校准参数")
    cal_parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="交互式校准模式 (显示实时预览)"
    )

    # test
    test_parser = sub.add_parser("test", help="测试 ADB 连接")
    test_parser.add_argument(
        "--loop",
        action="store_true",
        help="持续截图测试"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 加载配置
    config = load_config(args.config)

    # 设置日志
    setup_logging(config)

    # 执行命令
    if args.command == "start":
        cmd_start(config)
    elif args.command == "calibrate":
        cmd_calibrate(config, interactive=args.interactive)
    elif args.command == "test":
        cmd_test(config, loop=args.loop)


if __name__ == "__main__":
    main()
