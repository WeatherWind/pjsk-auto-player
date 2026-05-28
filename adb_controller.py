"""
ADB 控制器 —— 通过 ADB 连接安卓手机, 完成截图、触摸操作。

Windows / macOS / Linux 通用。
"""

import subprocess
import time
import logging
import os
import sys
from typing import Optional

import numpy as np

logger = logging.getLogger("pjsk_adb")


class ADBController:
    """ADB 控制器, 封装设备连接、截图、触摸操作。"""

    def __init__(self, config: dict):
        self.cfg = config["adb"]
        self.screen = config["screen"]
        self.executable = self._find_adb()
        self.serial = self.cfg.get("device_serial", "").strip()

    # ──────────────────────────────────────────
    # 设备管理
    # ──────────────────────────────────────────

    def _find_adb(self) -> str:
        """查找 adb 可执行文件 (Windows 下为 adb.exe)。"""
        exe = self.cfg.get("executable", "adb")
        # 如果指定了完整路径, 直接使用
        if os.path.isfile(exe):
            return exe
        # 如果含路径分隔符但不是文件, 可能是命令
        if os.sep in exe or (sys.platform == "win32" and "\\" in exe):
            return exe
        # 从 PATH 查找
        which_cmd = "where" if sys.platform == "win32" else "which"
        try:
            subprocess.run(
                [which_cmd, exe],
                capture_output=True,
                check=True,
            )
            return exe
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning(
                f"'{exe}' 未在 PATH 中找到。"
                "请安装 ADB (https://developer.android.com/studio/command-line/adb)"
                "或设置 adb.executable 配置项。"
            )
            return exe

    def _adb_cmd(self, *args: str) -> list[str]:
        """构造 adb 命令列表。"""
        cmd = [self.executable]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return cmd

    def devices(self) -> list[dict]:
        """列出已连接的设备。"""
        result = subprocess.run(
            self._adb_cmd("devices"),
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().splitlines()
        devices = []
        for line in lines[1:]:  # 跳过 "List of devices attached"
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) == 2 and parts[1] == "device":
                devices.append({"serial": parts[0], "status": "device"})
        return devices

    def is_connected(self) -> bool:
        """检查设备是否连接。"""
        devs = self.devices()
        if self.serial:
            return any(d["serial"] == self.serial for d in devs)
        return len(devs) > 0

    def wait_for_device(self, timeout: int = 30) -> bool:
        """等待设备连接。"""
        logger.info(f"等待设备连接 (超时 {timeout}s)...")
        for _ in range(timeout):
            if self.is_connected():
                logger.info("设备已连接.")
                return True
            time.sleep(1)
        logger.error("设备连接超时.")
        return False

    def get_screen_size(self) -> tuple[int, int]:
        """通过 adb shell wm size 获取屏幕尺寸。"""
        result = subprocess.run(
            self._adb_cmd("shell", "wm", "size"),
            capture_output=True, text=True, timeout=10
        )
        # 输出如 "Physical size: 1080x2400"
        for line in result.stdout.splitlines():
            if "Physical size:" in line or "Override size:" in line:
                if "x" in line:
                    size_str = line.split()[-1].strip()
                    w, h = size_str.split("x")
                    return int(w), int(h)
        # 回退到配置值
        return self.screen["width"], self.screen["height"]

    # ──────────────────────────────────────────
    # 屏幕截图
    # ──────────────────────────────────────────

    def screencap(self) -> Optional[np.ndarray]:
        """
        截取手机屏幕, 返回 BGR numpy 数组 (OpenCV 格式)。

        Returns:
            BGR 格式的 ndarray, 失败返回 None.
        """
        import cv2  # 延迟导入, 避免依赖未安装

        method = self.cfg.get("screencap_method", "exec-out")

        if method == "exec-out":
            return self._screencap_execout()
        elif method == "file":
            return self._screencap_file()
        else:
            logger.error(f"不支持的 screencap 方法: {method}")
            return None

    def _screencap_execout(self) -> Optional[np.ndarray]:
        """使用 adb exec-out screencap 直接获取截图 (推荐)。"""
        import cv2

        try:
            result = subprocess.run(
                self._adb_cmd("exec-out", "screencap", "-p"),
                capture_output=True, timeout=15
            )
            if result.returncode != 0 or len(result.stdout) < 100:
                logger.warning(f"screencap 失败, stdout={len(result.stdout)} bytes")
                return None

            img_arr = np.frombuffer(result.stdout, dtype=np.uint8)
            frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.warning("screencap 解码失败")
                return None
            return frame

        except subprocess.TimeoutExpired:
            logger.warning("screencap 超时")
            return None
        except Exception as e:
            logger.warning(f"screencap 异常: {e}")
            return None

    def _screencap_file(self) -> Optional[np.ndarray]:
        """截图保存到设备文件再 pull (兼容性方法)。"""
        import cv2

        try:
            ts = int(time.time() * 1000)
            remote_path = f"{self.cfg.get('temp_dir', '/sdcard/')}ss_{ts}.png"

            # 截图保存到设备
            subprocess.run(
                self._adb_cmd("shell", "screencap", "-p", remote_path),
                capture_output=True, timeout=15
            )

            # pull 到临时文件
            local_temp = f"__temp_ss_{ts}.png"
            subprocess.run(
                self._adb_cmd("pull", remote_path, local_temp),
                capture_output=True, timeout=15
            )

            # 删除设备上的截图
            subprocess.run(
                self._adb_cmd("shell", "rm", remote_path),
                capture_output=True, timeout=10
            )

            # 读取
            frame = cv2.imread(local_temp)
            if os.path.exists(local_temp):
                os.remove(local_temp)
            return frame

        except Exception as e:
            logger.warning(f"screencap_file 异常: {e}")
            return None

    # ──────────────────────────────────────────
    # 触摸操作
    # ──────────────────────────────────────────

    def tap(self, x: int, y: int) -> bool:
        """在 (x, y) 位置点击。"""
        try:
            subprocess.run(
                self._adb_cmd("shell", "input", "tap", str(int(x)), str(int(y))),
                capture_output=True, timeout=5
            )
            return True
        except Exception as e:
            logger.warning(f"tap 失败 ({x}, {y}): {e}")
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 50) -> bool:
        """从 (x1,y1) 滑动到 (x2,y2), 持续 duration_ms 毫秒。"""
        try:
            subprocess.run(
                self._adb_cmd(
                    "shell", "input", "swipe",
                    str(int(x1)), str(int(y1)),
                    str(int(x2)), str(int(y2)),
                    str(int(duration_ms))
                ),
                capture_output=True, timeout=5
            )
            return True
        except Exception as e:
            logger.warning(f"swipe 失败: {e}")
            return False

    def press(self, x: int, y: int, duration_ms: int = 100) -> bool:
        """
        长按 (x, y) 位置, 持续 duration_ms 毫秒。
        内部使用 swipe 实现 (同位置按下+抬起)。
        """
        return self.swipe(x, y, x, y, duration_ms)

    def flick_up(self, x: int, y: int,
                 distance: int = 150, duration_ms: int = 50) -> bool:
        """上划 (flick note)。"""
        return self.swipe(x, y, x, y - distance, duration_ms)

    def flick_down(self, x: int, y: int,
                   distance: int = 150, duration_ms: int = 50) -> bool:
        """下划。"""
        return self.swipe(x, y, x, y + distance, duration_ms)

    def flick_left(self, x: int, y: int,
                   distance: int = 150, duration_ms: int = 50) -> bool:
        """左划。"""
        return self.swipe(x, y, x - distance, y, duration_ms)

    def flick_right(self, x: int, y: int,
                    distance: int = 150, duration_ms: int = 50) -> bool:
        """右划。"""
        return self.swipe(x, y, x + distance, y, duration_ms)

    # ──────────────────────────────────────────
    # 延迟测量
    # ──────────────────────────────────────────

    def measure_latency(self, samples: int = 5) -> dict:
        """
        测量 ADB 操作延迟。

        Returns:
            {
                "screencap_avg_ms": ...,  # 截图平均耗时
                "tap_avg_ms": ...,         # 点击平均耗时
                "total_avg_ms": ...,       # 总延迟
            }
        """
        screencap_times = []
        tap_times = []

        for i in range(samples):
            # 测量 screencap
            t0 = time.perf_counter()
            frame = self.screencap()
            t1 = time.perf_counter()
            if frame is not None:
                screencap_times.append((t1 - t0) * 1000)

            # 测量 tap (点击屏幕中央)
            cx, cy = self.screen["width"] // 2, self.screen["height"] // 2
            t2 = time.perf_counter()
            self.tap(cx, cy)
            t3 = time.perf_counter()
            tap_times.append((t3 - t2) * 1000)

            time.sleep(0.5)

        result = {}
        if screencap_times:
            result["screencap_avg_ms"] = sum(screencap_times) / len(screencap_times)
            result["screencap_min_ms"] = min(screencap_times)
            result["screencap_max_ms"] = max(screencap_times)
        if tap_times:
            result["tap_avg_ms"] = sum(tap_times) / len(tap_times)
            result["tap_min_ms"] = min(tap_times)
            result["tap_max_ms"] = max(tap_times)
        if screencap_times and tap_times:
            result["total_avg_ms"] = result["screencap_avg_ms"] + result["tap_avg_ms"]

        return result
