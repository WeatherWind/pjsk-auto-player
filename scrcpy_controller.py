"""
scrcpy 视频流后端 —— 通过 PPM 格式从 scrcpy 获取高帧率手机画面。

原理:
  scrcpy --output-format=ppm 将手机屏幕以 PPM (便携像素图) 格式
  持续输出到 stdout。每帧包含: header + RGB 像素数据。
  OpenCV 可以直接解码 PPM 格式。

  相比 ADB screencap (5-15 FPS), 通过 scrcpy 可获得 30-60 FPS,
  是执行自动化的关键性能提升。

需要安装 scrcpy:
  - macOS: brew install scrcpy
  - Windows: scoop install scrcpy
  - Linux: apt install scrcpy
"""

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Optional

import numpy as np

logger = logging.getLogger("pjsk_scrcpy")


class ScrcpyController:
    """
    scrcpy 视频流控制器 (PPM 模式)。

    启动 scrcpy 进程并通过 stdout 持续读取 PPM 格式的视频帧。
    提供 get_frame() 方法供 ADBController 调用。
    """

    def __init__(self, config: dict):
        self.cfg = config.get("scrcpy", {})
        self.serial = config.get("adb", {}).get("device_serial", "")
        self.executable = self._find_scrcpy()

        self._process: Optional[subprocess.Popen] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._frame_count = 0
        self._fps = 0.0
        self._last_fps_time = time.time()

        # PPM 解析状态
        self._buffer = b""
        self._header_done = False
        self._ppm_width = 0
        self._ppm_height = 0
        self._ppm_data_size = 0
        self._state = "header"  # header → data

        # 帧跳过 (只处理最新帧, 不积压)
        self._frame_skip_enabled = self.cfg.get("frame_skip", True)
        self._frame_skip_counter = 0

    def _find_scrcpy(self) -> str:
        """查找 scrcpy 可执行文件。"""
        exe = self.cfg.get("executable", "scrcpy")
        if os.path.isfile(exe):
            return exe
        which_cmd = "where" if sys.platform == "win32" else "which"
        try:
            subprocess.run([which_cmd, exe], capture_output=True, check=True)
            logger.info(f"scrcpy 已找到: {exe}")
            return exe
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error(
                f"'{exe}' 未在 PATH 中。请安装 scrcpy"
            )
            return exe

    def start(self) -> bool:
        """启动 scrcpy PPM 视频流。返回是否成功。"""
        if self._running:
            return True

        max_fps = self.cfg.get("max_fps", 60)
        bit_rate = self.cfg.get("bit_rate", 8000000)
        scale = self.cfg.get("scale", 0.5)

        # PPM 模式: 输出原始像素数据, 无需编解码
        cmd = [self.executable]

        if self.serial:
            cmd += ["-s", self.serial]

        # --no-window: 不显示窗口
        # --no-control: 不处理输入
        # --output-format=ppm: 输出 PPM 格式 (关键!)
        # --max-fps: 限制帧率
        cmd += [
            "--no-window",
            "--no-control",
            "--output-format=ppm",
            "--max-fps", str(max_fps),
            "--max-size", str(int(1080 * scale)),
            "--video-bit-rate", str(bit_rate),
        ]

        logger.info(f"启动 scrcpy PPM 流: max_fps={max_fps}, scale={scale}")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,  # 无缓冲
            )
        except FileNotFoundError:
            logger.error("scrcpy 未安装")
            return False
        except Exception as e:
            logger.error(f"启动 scrcpy 失败: {e}")
            return False

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="scrcpy-ppm-reader"
        )
        self._reader_thread.start()

        # 等待首帧
        for _ in range(100):
            time.sleep(0.01)
            with self._lock:
                if self._latest_frame is not None:
                    h, w = self._latest_frame.shape[:2]
                    logger.info(f"scrcpy PPM 已启动: {w}x{h} @ {max_fps}FPS")
                    return True

        logger.warning("scrcpy PPM 启动超时 (未收到帧)")
        self.stop()
        return False

    def _read_loop(self):
        """
        后台线程: 读取 scrcpy stdout 的 PPM 数据流。

        PPM 格式:
          Header: "P6\\n<width> <height>\\n255\\n"
          Data:   width × height × 3 bytes (RGB)
        """
        self._buffer = b""
        self._state = "header"

        while self._running and self._process and self._process.stdout:
            try:
                chunk = self._process.stdout.read(65536)
            except Exception:
                break

            if not chunk:
                logger.info("scrcpy PPM 流结束")
                break

            self._buffer += chunk
            self._parse_buffer()

        logger.info("scrcpy PPM 读取线程已退出")

    def _parse_buffer(self):
        """从缓冲区解析 PPM 帧。"""
        while True:
            if self._state == "header":
                # 找 header 结束标记 "\n" (P6 后的第二个换行)
                # Header 格式: "P6\nW H\n255\n"
                first_nl = self._buffer.find(b"\n")
                if first_nl < 0:
                    break
                # 跳过 "P6\n"
                rest = self._buffer[first_nl + 1:]
                second_nl = rest.find(b"\n")
                if second_nl < 0:
                    break

                # 解析 "W H"
                dims = rest[:second_nl].decode().strip()
                parts = dims.split()
                if len(parts) >= 2:
                    try:
                        self._ppm_width = int(parts[0])
                        self._ppm_height = int(parts[1])
                    except ValueError:
                        # 可能包含 "255" 行, 继续解析
                        pass

                # 跳过 "255\n" (或数值行)
                remaining = rest[second_nl + 1:]
                third_nl = remaining.find(b"\n")
                if third_nl < 0:
                    break

                # 现在 data 从第三个换行后开始
                data_start = first_nl + 1 + second_nl + 1 + third_nl + 1
                self._ppm_data_size = self._ppm_width * self._ppm_height * 3
                self._state = "data"
                # 截断到 data 开始位置
                self._buffer = self._buffer[data_start:]

            if self._state == "data":
                if len(self._buffer) < self._ppm_data_size:
                    break  # 数据还不够

                # 取出一帧
                frame_data = self._buffer[:self._ppm_data_size]

                # PPM 是 RGB, OpenCV 需要 BGR — 转换
                rgb = np.frombuffer(frame_data, dtype=np.uint8).reshape(
                    self._ppm_height, self._ppm_width, 3
                )
                bgr = rgb[:, :, ::-1]  # RGB → BGR

                with self._lock:
                    self._latest_frame = bgr
                    self._frame_count += 1

                    # FPS 统计
                    now = time.time()
                    if now - self._last_fps_time >= 1.0:
                        self._fps = self._frame_count / (now - self._last_fps_time)
                        self._frame_count = 0
                        self._last_fps_time = now

                # 移除已处理的数据, 保留可能的下一帧头部
                self._buffer = self._buffer[self._ppm_data_size:]
                self._state = "header"

                # 继续循环, 看看 buffer 里是否已经有下一帧
                continue

            break  # 不应到达这里

    def get_frame(self) -> Optional[np.ndarray]:
        """获取最新视频帧 (BGR 格式)。"""
        with self._lock:
            if self._latest_frame is None:
                return None
            # 跳过积压: 只返回最新帧, 丢弃旧帧以保持低延迟
            if self._frame_skip_enabled and hasattr(self, '_frame_skip_counter'):
                self._frame_skip_counter += 1
                if self._frame_skip_counter % 2 == 0:
                    return self._latest_frame.copy()
                return None
            return self._latest_frame.copy()

    def get_fps(self) -> float:
        """获取当前 FPS。"""
        with self._lock:
            return self._fps

    def stop(self):
        """关闭 scrcpy 进程。"""
        self._running = False
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        logger.info("scrcpy PPM 已停止")
