"""
ADB 控制器 —— 通过 ADB / scrcpy 连接安卓手机, 完成截图、触摸操作。

支持多种后端:
  - ADB exec-out screencap (默认, 5-15 FPS)
  - ADB file screencap (兼容模式, 3-8 FPS)
  - scrcpy 视频流 (可选, 30-60 FPS, 需安装 scrcpy)

Windows / macOS / Linux 通用。
"""

import subprocess
import time
import logging
import os
import sys
import socket
import threading
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
        if os.path.isfile(exe):
            return exe
        if os.sep in exe or (sys.platform == "win32" and "\\" in exe):
            return exe
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
        for line in lines[1:]:
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
        try:
            result = subprocess.run(
                self._adb_cmd("shell", "wm", "size"),
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if "Physical size:" in line or "Override size:" in line:
                    if "x" in line:
                        size_str = line.split()[-1].strip()
                        w, h = size_str.split("x")
                        return int(w), int(h)
        except Exception as e:
            logger.warning(f"获取屏幕尺寸失败: {e}")
        return self.screen["width"], self.screen["height"]

    # ──────────────────────────────────────────
    # 屏幕截图 (后端分发)
    # ──────────────────────────────────────────

    def screencap(self) -> Optional[np.ndarray]:
        """
        截取手机屏幕, 返回 BGR numpy 数组 (OpenCV 格式)。

        自动选择已配置的截图方法。
        """
        import cv2  # 延迟导入

        method = self.cfg.get("screencap_method", "exec-out")

        if method == "scrcpy":
            return self._screencap_scrcpy()
        elif method == "exec-out":
            return self._screencap_execout()
        elif method == "file":
            return self._screencap_file()
        else:
            logger.error(f"不支持的 screencap 方法: {method}")
            return None

    def _screencap_execout(self) -> Optional[np.ndarray]:
        """使用 adb exec-out screencap 获取截图 (默认, 5-15 FPS)。"""
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
        """截图保存到设备文件再 pull (兼容模式, 3-8 FPS)。"""
        import cv2

        try:
            ts = int(time.time() * 1000)
            remote_path = f"{self.cfg.get('temp_dir', '/sdcard/')}ss_{ts}.png"

            subprocess.run(
                self._adb_cmd("shell", "screencap", "-p", remote_path),
                capture_output=True, timeout=15
            )

            local_temp = f"__temp_ss_{ts}.png"
            subprocess.run(
                self._adb_cmd("pull", remote_path, local_temp),
                capture_output=True, timeout=15
            )
            subprocess.run(
                self._adb_cmd("shell", "rm", remote_path),
                capture_output=True, timeout=10
            )

            frame = cv2.imread(local_temp)
            if os.path.exists(local_temp):
                os.remove(local_temp)
            return frame

        except Exception as e:
            logger.warning(f"screencap_file 异常: {e}")
            return None

    # ──────────────────────────────────────────
    # scrcpy 后端 (可选, 30-60 FPS)
    # ──────────────────────────────────────────

    def _screencap_scrcpy(self) -> Optional[np.ndarray]:
        """
        通过 scrcpy 视频流获取画面帧。

        scrcpy 提供 ~30 FPS 的视频流, 远快于 ADB screencap。
        需要安装 scrcpy (https://github.com/Genymobile/scrcpy)。
        """
        # 延迟导入 ScrcpyController
        try:
            from scrcpy_controller import ScrcpyController
        except ImportError:
            logger.error(
                "scrcpy_controller.py 未找到, 回退到 ADB screencap。"
                "请确保 scrcpy_controller.py 在项目目录中。"
            )
            return self._screencap_execout()

        if not hasattr(self, '_scrcpy_instance'):
            self._scrcpy_instance = ScrcpyController(self.cfg)
            if not self._scrcpy_instance.start():
                logger.error("scrcpy 启动失败, 回退到 ADB screencap")
                self._scrcpy_instance = None
                return self._screencap_execout()

        frame = self._scrcpy_instance.get_frame()
        return frame

    def close_scrcpy(self):
        """关闭 scrcpy 后端 (如果有启动)。"""
        if hasattr(self, '_scrcpy_instance') and self._scrcpy_instance:
            self._scrcpy_instance.stop()

    # ──────────────────────────────────────────
    # Minitouch 后端 (可选, <5ms 触摸延迟)
    # ──────────────────────────────────────────

    def init_minitouch(self) -> bool:
        """
        初始化 minitouch 后端。

        minitouch 是一个运行在安卓设备上的触摸守护进程,
        通过本地 socket 接收触摸命令, 延迟 <5ms (远快于 ADB input ~50ms)。

        使用方式:
          1. adb_controller.py 在启动时自动推送 minitouch 到设备
          2. 启动 minitouch 进程, 建立 socket 连接
          3. tap() / swipe() 等方法自动切换到 minitouch

        返回是否成功初始化。
        """
        self._minitouch_socket: Optional[socket.socket] = None
        self._minitouch_proc = None
        self._mt_max_contacts = 2
        self._mt_max_x = self.screen["width"]
        self._mt_max_y = self.screen["height"]

        # minitouch 二进制文件路径
        mt_bin = self.cfg.get("minitouch", {}).get("binary_path", "")
        if not mt_bin:
            # 自动查找内置二进制
            import glob
            builtin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "bin", "minitouch")
            # 尝试根据架构查找
            arch = self._get_device_arch()
            if arch:
                mt_bin = os.path.join(builtin, f"minitouch_{arch}")
            else:
                mt_bin = os.path.join(builtin, "minitouch")

        if not os.path.exists(mt_bin):
            logger.warning(f"minitouch 二进制不存在: {mt_bin}")
            logger.info("可从 https://github.com/DeviceFarmer/minitouch 下载")
            logger.info("或设置 adb.minitouch.binary_path")
            return False

        # 推送二进制到设备
        remote_path = "/data/local/tmp/minitouch"
        push_result = subprocess.run(
            self._adb_cmd("push", mt_bin, remote_path),
            capture_output=True, text=True, timeout=10
        )
        if push_result.returncode != 0:
            logger.warning(f"minitouch 推送失败: {push_result.stderr.strip()}")
            return False

        # 设置执行权限
        subprocess.run(
            self._adb_cmd("shell", "chmod", "755", remote_path),
            capture_output=True, timeout=5
        )

        # 启动 minitouch (后台进程)
        try:
            self._minitouch_proc = subprocess.Popen(
                self._adb_cmd("shell", remote_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            logger.warning(f"minitouch 启动失败: {e}")
            return False

        # 等待 minitouch 启动, 读取输出获取分辨率信息
        time.sleep(0.5)

        # 通过 ADB forward 建立本地 socket 连接
        # minitouch 默认监听 localhost:1111
        forward_result = subprocess.run(
            self._adb_cmd("forward", "tcp:1111", "tcp:1111"),
            capture_output=True, text=True, timeout=5
        )
        if forward_result.returncode != 0:
            logger.warning(f"ADB forward 失败: {forward_result.stderr.strip()}")
            self._cleanup_minitouch()
            return False

        # 连接 socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", 1111))

            # 读取 minitouch 协议版本信息
            # 格式: v <version> <max_contacts> <max_x> <max_y>
            welcome = b""
            while b"\n" not in welcome:
                try:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    welcome += chunk
                except socket.timeout:
                    break

            welcome_str = welcome.decode().strip()
            logger.info(f"minitouch 已连接: {welcome_str}")

            # 解析协议信息
            parts = welcome_str.split()
            if len(parts) >= 4 and parts[0] == "v":
                self._mt_max_contacts = int(parts[1])
                self._mt_max_x = int(parts[2])
                self._mt_max_y = int(parts[3])

            self._minitouch_socket = sock
            logger.info(f"minitouch 初始化成功 (延迟 <5ms, "
                        f"触点={self._mt_max_contacts}, "
                        f"分辨率={self._mt_max_x}x{self._mt_max_y})")
            return True

        except (socket.error, OSError) as e:
            logger.warning(f"minitouch socket 连接失败: {e}")
            self._cleanup_minitouch()
            return False

    def _get_device_arch(self) -> str:
        """获取设备 CPU 架构。"""
        try:
            result = subprocess.run(
                self._adb_cmd("shell", "getprop", "ro.product.cpu.abi"),
                capture_output=True, text=True, timeout=5
            )
            arch = result.stdout.strip()
            # 映射到 minitouch 二进制命名
            mapping = {
                "arm64-v8a": "arm64",
                "armeabi-v7a": "arm",
                "x86_64": "x86_64",
                "x86": "x86",
            }
            return mapping.get(arch, arch)
        except Exception:
            return ""

    def _mt_tap(self, x: int, y: int) -> bool:
        """通过 minitouch 发送点击事件。"""
        if not self._minitouch_socket:
            return self._mt_fallback_tap(x, y)
        try:
            # minitouch 协议: d contact x y pressure + c + u contact
            scaled_x = int(x * self._mt_max_x / self.screen["width"])
            scaled_y = int(y * self._mt_max_y / self.screen["height"])
            cmd = f"d 0 {scaled_x} {scaled_y} 50\nc\nu 0\nc\n"
            self._minitouch_socket.sendall(cmd.encode())
            return True
        except (socket.error, OSError) as e:
            logger.warning(f"minitouch tap 失败: {e}")
            return self._mt_fallback_tap(x, y)

    def _mt_swipe(self, x1: int, y1: int, x2: int, y2: int,
                  duration_ms: int = 50) -> bool:
        """通过 minitouch 发送滑动事件。"""
        if not self._minitouch_socket:
            return self._mt_fallback_swipe(x1, y1, x2, y2, duration_ms)
        try:
            sx1 = int(x1 * self._mt_max_x / self.screen["width"])
            sy1 = int(y1 * self._mt_max_y / self.screen["height"])
            sx2 = int(x2 * self._mt_max_x / self.screen["width"])
            sy2 = int(y2 * self._mt_max_y / self.screen["height"])

            # 下笔 + 移动 + 抬起
            cmd = f"d 0 {sx1} {sy1} 50\nc\n"

            # 插值移动
            steps = max(int(duration_ms / 5), 1)
            for i in range(1, steps + 1):
                t = i / steps
                mx = int(sx1 + (sx2 - sx1) * t)
                my = int(sy1 + (sy2 - sy1) * t)
                cmd += f"m 0 {mx} {my} 50\nc\n"

            cmd += "u 0\nc\n"

            self._minitouch_socket.sendall(cmd.encode())
            time.sleep(duration_ms / 1000.0)
            return True
        except (socket.error, OSError) as e:
            logger.warning(f"minitouch swipe 失败: {e}")
            return self._mt_fallback_swipe(x1, y1, x2, y2, duration_ms)

    def _mt_press(self, x: int, y: int, duration_ms: int = 100) -> bool:
        """通过 minitouch 长按。"""
        if not self._minitouch_socket:
            return self._mt_fallback_press(x, y, duration_ms)
        try:
            sx = int(x * self._mt_max_x / self.screen["width"])
            sy = int(y * self._mt_max_y / self.screen["height"])
            cmd = f"d 0 {sx} {sy} 50\nc\n"
            self._minitouch_socket.sendall(cmd.encode())
            time.sleep(duration_ms / 1000.0)
            cmd = f"u 0\nc\n"
            self._minitouch_socket.sendall(cmd.encode())
            return True
        except (socket.error, OSError) as e:
            logger.warning(f"minitouch press 失败: {e}")
            return self._mt_fallback_press(x, y, duration_ms)

    def _mt_fallback_tap(self, x, y):
        """minitouch 不可用时的回退: 使用 ADB input tap。"""
        return self._adb_tap(x, y)

    def _mt_fallback_swipe(self, x1, y1, x2, y2, duration_ms):
        return self._adb_swipe(x1, y1, x2, y2, duration_ms)

    def _mt_fallback_press(self, x, y, duration_ms):
        return self._adb_swipe(x, y, x, y, duration_ms)

    def _cleanup_minitouch(self):
        """清理 minitouch 进程和 socket。"""
        if self._minitouch_socket:
            try:
                self._minitouch_socket.close()
            except Exception:
                pass
            self._minitouch_socket = None
        if self._minitouch_proc:
            try:
                self._minitouch_proc.terminate()
            except Exception:
                pass
            self._minitouch_proc = None

    # ──────────────────────────────────────────
    # 触摸操作 (自动选择后端: minitouch > ADB)
    # ──────────────────────────────────────────

    def tap(self, x: int, y: int) -> bool:
        """在 (x, y) 位置点击。自动选择 minitouch 或 ADB。"""
        if hasattr(self, '_minitouch_socket') and self._minitouch_socket:
            return self._mt_tap(x, y)
        return self._adb_tap(x, y)

    def _adb_tap(self, x: int, y: int) -> bool:
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
        """从 (x1,y1) 滑动到 (x2,y2)。自动选择 minitouch 或 ADB。"""
        if hasattr(self, '_minitouch_socket') and self._minitouch_socket:
            return self._mt_swipe(x1, y1, x2, y2, duration_ms)
        return self._adb_swipe(x1, y1, x2, y2, duration_ms)

    def _adb_swipe(self, x1: int, y1: int, x2: int, y2: int,
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
        """长按 (x, y) 位置。自动选择 minitouch 或 ADB。"""
        if hasattr(self, '_minitouch_socket') and self._minitouch_socket:
            return self._mt_press(x, y, duration_ms)
        return self._adb_press(x, y, duration_ms)

    def _adb_press(self, x: int, y: int, duration_ms: int = 100) -> bool:
        """长按 (x, y) 位置, 持续 duration_ms 毫秒。"""
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
                "screencap_avg_ms": ...,
                "tap_avg_ms": ...,
                "total_avg_ms": ...,
            }
        """
        screencap_times = []
        tap_times = []

        for i in range(samples):
            t0 = time.perf_counter()
            frame = self.screencap()
            t1 = time.perf_counter()
            if frame is not None:
                screencap_times.append((t1 - t0) * 1000)

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
