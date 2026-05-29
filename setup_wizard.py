#!/usr/bin/env python3
"""
PJSK Auto Player 设置向导 —— 一键检测设备、校准、生成配置。

用法:
    python main.py setup              # 启动交互式设置
    python main.py setup --auto       # 自动模式 (无需交互)
"""

import logging
import os
import shutil
import sys
import time
from typing import Optional

import cv2
import numpy as np
import yaml

logger = logging.getLogger("pjsk_setup")

# ANSI 终端颜色
C_RESET = "\033[0m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"
C_RED = "\033[31m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"


def print_banner():
    """打印启动横幅。"""
    print()
    print(f"  {C_CYAN}╔════════════════════════════════════════╗{C_RESET}")
    print(f"  {C_CYAN}║  {C_BOLD}PJSK Auto Player — 设置向导{C_RESET}{C_CYAN}        ║{C_RESET}")
    print(f"  {C_CYAN}╚════════════════════════════════════════╝{C_RESET}")
    print()


def step(msg: str, status: str = "..."):
    """打印步骤。"""
    status_color = {
        "✓": C_GREEN, "✗": C_RED, "→": C_YELLOW, "...": C_DIM
    }.get(status, C_DIM)
    print(f"  [{status_color}{status}{C_RESET}] {msg}")


def input_yesno(prompt: str, default: bool = True) -> bool:
    """简单的是/否输入。"""
    hint = "Y/n" if default else "y/N"
    while True:
        ans = input(f"  {C_CYAN}?{C_RESET} {prompt} [{hint}] ").strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def prompt(prompt: str, default: str = "", secret: bool = False) -> str:
    """带默认值的提示输入。"""
    default_hint = f" [{default}]" if default else ""
    val = input(f"  {C_CYAN}?{C_RESET} {prompt}{default_hint}: ").strip()
    if not val:
        return default
    return val


class SetupWizard:
    """
    交互式设置向导。

    自动完成:
      1. 检测 ADB 连接
      2. 检测设备
      3. 测量延迟
      4. 校准判定线和轨道
      5. 生成配置
      6. (可选) 安装 scrcpy 和 minitouch
    """

    def __init__(self, auto: bool = False):
        self.auto = auto
        self.config: dict = self._load_default_config()
        self.device_serial = ""
        self.screen_w = 1080
        self.screen_h = 2400
        self.adb = None

    def _load_default_config(self) -> dict:
        """加载默认配置。"""
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "config.yaml")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                return yaml.safe_load(f) or {}
        return {}

    def run(self):
        """运行设置向导。"""
        print_banner()
        print(f"  本向导将自动完成以下步骤:\n")
        print(f"    1. 检测 ADB")
        print(f"    2. 连接手机")
        print(f"    3. 测量延迟")
        print(f"    4. 校准画面")
        print(f"    5. 可选: scrcpy / minitouch")
        print(f"    6. 保存配置")
        print()

        if not self.auto:
            input(f"  {C_DIM}按 Enter 开始...{C_RESET}")
        print()

        # 步骤 1: ADB
        self._step_adb()

        # 步骤 2: 设备
        self._step_device()

        # 步骤 3: 延迟
        self._step_latency()

        # 步骤 4: 校准
        self._step_calibrate()

        # 步骤 5: 可选组件
        self._step_optional()

        # 步骤 6: 保存
        self._step_save()

    def _step_adb(self):
        """检测 ADB。"""
        step("检测 ADB 可执行文件...", "...")
        from adb_controller import ADBController

        # 尝试自动查找
        for exe in ["adb", "adb.exe"]:
            if shutil.which(exe):
                self.config["adb"] = self.config.get("adb", {})
                self.config["adb"]["executable"] = exe
                step("ADB 已找到", "✓")
                self.adb = ADBController(self.config)
                return

        step("ADB 未在 PATH 中找到", "✗")
        if self.auto:
            return

        path = prompt("请输入 ADB 路径", "adb")
        if not path:
            print(f"  {C_RED}  请先安装 ADB: https://developer.android.com/studio/releases/platform-tools{C_RESET}")
            sys.exit(1)
        self.config["adb"]["executable"] = path
        self.adb = ADBController(self.config)

    def _step_device(self):
        """检测并选择设备。"""
        if not self.adb:
            step("跳过 (ADB 未就绪)", "✗")
            return

        step("检测已连接的设备...", "...")
        devices = self.adb.devices()

        if not devices:
            step("未检测到设备", "✗")
            print(f"  {C_YELLOW}  请检查:{C_RESET}")
            print(f"    - USB 线是否连接")
            print(f"    - 手机上 USB 调试是否开启")
            print(f"    - 是否已授权电脑")
            if self.auto:
                return
            input(f"  {C_DIM}  连接后按 Enter 重试...{C_RESET}")
            devices = self.adb.devices()

        if len(devices) == 0:
            step("仍无设备, 跳过", "✗")
            return
        elif len(devices) == 1:
            self.device_serial = devices[0]["serial"]
            self.config["adb"]["device_serial"] = self.device_serial
            step(f"设备: {self.device_serial}", "✓")
        else:
            step(f"发现 {len(devices)} 台设备", "→")
            for i, d in enumerate(devices):
                print(f"    {i+1}. {d['serial']} ({d['status']})")
            if self.auto:
                self.device_serial = devices[0]["serial"]
            else:
                idx = int(prompt("选择设备编号", "1")) - 1
                self.device_serial = devices[idx]["serial"]
            self.config["adb"]["device_serial"] = self.device_serial

        # 检测屏幕尺寸
        try:
            w, h = self.adb.get_screen_size()
            self.screen_w, self.screen_h = w, h
            self.config["screen"]["width"] = w
            self.config["screen"]["height"] = h
            step(f"屏幕: {w}x{h}", "✓")
        except Exception as e:
            step(f"获取屏幕尺寸失败: {e}", "✗")

    def _step_latency(self):
        """测量 ADB 延迟。"""
        if not self.adb:
            step("跳过 (设备未连接)", "✗")
            return

        step("测量 ADB 延迟 (约 5 秒)...", "...")
        try:
            latency = self.adb.measure_latency(samples=5)
            total = latency.get("total_avg_ms", 0)
            screencap = latency.get("screencap_avg_ms", 0)
            tap = latency.get("tap_avg_ms", 0)

            if total > 0:
                self.config["timing"] = self.config.get("timing", {})
                self.config["timing"]["latency_compensation_ms"] = round(total)
                step(f"截图: {screencap:.0f}ms  触摸: {tap:.0f}ms  总延迟: {total:.0f}ms", "✓")
                step(f"延迟补偿已设为 {round(total)}ms", "✓")
            else:
                step("延迟测量返回空, 使用默认值 150ms", "→")
        except Exception as e:
            step(f"延迟测量失败: {e}", "✗")

    def _step_calibrate(self):
        """校准判定线和轨道。"""
        if not self.adb:
            step("跳过 (设备未连接)", "✗")
            return

        step("截取屏幕用于校准...", "...")
        frame = self.adb.screencap()
        if frame is None:
            step("截图失败, 跳过校准", "✗")
            return

        h, w = frame.shape[:2]
        self.config["screen"]["width"] = w
        self.config["screen"]["height"] = h

        from screen_analyzer import ScreenAnalyzer
        analyzer = ScreenAnalyzer(self.config)

        # 校准判定线
        step("自动校准判定线位置...", "...")
        judgment_y = analyzer.calibrate_judgment_line(frame)
        if judgment_y:
            ratio = round(judgment_y / h, 4)
            self.config["screen"]["judgment_line_y"] = ratio
            step(f"判定线 Y = {judgment_y} ({ratio})", "✓")

        # 校准轨道
        step("自动校准轨道位置...", "...")
        lanes = analyzer.calibrate_lanes(frame)
        if lanes:
            lane_ratios = [round(x / w, 4) for x in lanes]
            mid = w // 2
            left = [r for r, x in zip(lane_ratios, lanes) if x < mid]
            right = [r for r, x in zip(lane_ratios, lanes) if x >= mid]
            if left:
                self.config["screen"]["left_lanes"] = left
            if right:
                self.config["screen"]["right_lanes"] = right
            step(f"轨道: 左{left} 右{right}", "✓")

    def _step_optional(self):
        """可选组件安装。"""
        if self.auto:
            return

        print()
        step("可选组件", "→")

        # scrcpy
        if input_yesno("安装 scrcpy 以获取 30-60 FPS?", True):
            self._try_install_scrcpy()

        # minitouch
        if input_yesno("配置 minitouch 以降低触摸延迟 (<5ms)?", False):
            self._try_setup_minitouch()

    def _try_install_scrcpy(self):
        """尝试安装 scrcpy。"""
        if shutil.which("scrcpy"):
            step("scrcpy 已安装", "✓")
            self.config["adb"]["screencap_method"] = "scrcpy"
            return

        step("尝试安装 scrcpy...", "...")
        import platform
        sys_platform = platform.system()

        if sys_platform == "Darwin":
            os.system("brew install scrcpy 2>/dev/null || echo 'brew not found'")
        elif sys_platform == "Linux":
            os.system("apt install -y scrcpy 2>/dev/null || echo 'apt failed'")
        elif sys_platform == "Windows":
            os.system("winget install scrcpy 2>/dev/null || scoop install scrcpy 2>/dev/null || echo 'auto-install failed'")

        if shutil.which("scrcpy"):
            step("scrcpy 安装成功", "✓")
            self.config["adb"]["screencap_method"] = "scrcpy"
        else:
            step("请手动安装 scrcpy", "✗")

    def _try_setup_minitouch(self):
        """尝试设置 minitouch。"""
        step("检测设备架构...", "...")
        arch = self.adb._get_device_arch() if self.adb else ""
        if not arch:
            step("无法检测设备架构", "✗")
            return

        bin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "bin", "minitouch")
        os.makedirs(bin_dir, exist_ok=True)

        url = (f"https://github.com/DeviceFarmer/minitouch/releases/"
               f"latest/download/minitouch-{arch}")
        step(f"下载 minitouch ({arch})...", "...")
        try:
            import urllib.request
            urllib.request.urlretrieve(url,
                                       os.path.join(bin_dir, f"minitouch_{arch}"))
            os.chmod(os.path.join(bin_dir, f"minitouch_{arch}"), 0o755)
            step("minitouch 下载成功", "✓")
            self.config["minitouch"] = {"auto_init": True}
        except Exception as e:
            step(f"minitouch 下载失败: {e}", "✗")
            step("可稍后运行 python main.py minitouch-setup", "→")

    def _step_save(self):
        """保存配置。"""
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "config.yaml")

        step(f"保存配置到 {config_path}...", "...")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(self.config, f, default_flow_style=False,
                          allow_unicode=True, sort_keys=False)
            step("配置已保存", "✓")
        except Exception as e:
            step(f"保存配置失败: {e}", "✗")

        # 打印摘要
        print()
        print(f"  {C_GREEN}{'='*50}{C_RESET}")
        print(f"  {C_GREEN}✅ 设置完成!{C_RESET}")
        print(f"  {C_GREEN}{'='*50}{C_RESET}")
        print()
        print(f"    启动:  python main.py start")
        print(f"    连续执行:  python main.py auto")
        print(f"    校准:  python main.py calibrate")
        print(f"    仪表盘: python main.py web")
        print()

        # 提示
        print(f"  {C_DIM}💡 提示: 首次执行前请确保手机已进入选歌界面{C_RESET}")
        print()


def main():
    parser = argparse.ArgumentParser(description="PJSK Auto Player 设置向导")
    parser.add_argument("--auto", action="store_true",
                        help="自动模式 (无交互)")
    args = parser.parse_args()

    wizard = SetupWizard(auto=args.auto)
    wizard.run()


if __name__ == "__main__":
    import argparse
    main()
