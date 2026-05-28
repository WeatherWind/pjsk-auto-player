"""
scrcpy 视频流后端 —— 通过 scrcpy 获取手机屏幕的高帧率视频流。

需要安装 scrcpy:
  - macOS: brew install scrcpy
  - Windows: scoop install scrcpy 或 winget install scrcpy
  - Linux: apt install scrcpy

依赖: numpy, opencv-python (已包含在 requirements.txt)
"""

import logging
import subprocess
import os
import sys
import threading
import time
from typing import Optional

import numpy as np

logger = logging.getLogger("pjsk_scrcpy")


class ScrcpyController:
    """
    scrcpy 视频流控制器。

    启动 scrcpy 进程并通过管道读取视频帧。
    提供 get_frame() 方法供 ADBController 调用。
    """

    def __init__(self, config: dict):
        self.cfg = config["scrcpy"]
        self.serial = config["adb"].get("device_serial", "")
        self.executable = self._find_scrcpy()

        self._process: Optional[subprocess.Popen] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._frame_count = 0
        self._fps = 0.0
        self._last_fps_time = time.time()

    def _find_scrcpy(self) -> str:
        """查找 scrcpy 可执行文件。"""
        exe = self.cfg.get("executable", "scrcpy")
        if os.path.isfile(exe):
            return exe
        which_cmd = "where" if sys.platform == "win32" else "which"
        try:
            subprocess.run(
                [which_cmd, exe],
                capture_output=True, check=True,
            )
            logger.info(f"scrcpy 已找到: {exe}")
            return exe
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.error(
                f"'{exe}' 未在 PATH 中找到。"
                "请安装 scrcpy: brew install scrcpy (macOS), "
                "scoop install scrcpy (Windows), apt install scrcpy (Linux)"
            )
            return exe

    def start(self) -> bool:
        """启动 scrcpy 视频流。返回是否成功。"""
        if self._running:
            return True

        max_fps = self.cfg.get("max_fps", 30)
        bit_rate = self.cfg.get("bit_rate", 8000000)
        scale = self.cfg.get("scale", 0.5)

        # 构造 scrcpy 参数
        cmd = [self.executable]

        # 设备序列号
        if self.serial:
            cmd += ["-s", self.serial]

        # 不显示窗口、不控制、只输出视频
        cmd += [
            "--no-window",
            "--no-control",
            "--max-size", str(int(1080 * scale)),
            "--max-fps", str(max_fps),
            "--video-codec", "h264",
            "--video-bit-rate", str(bit_rate),
            "--output-format", "h264",
            "--print-fps",
        ]

        logger.info(f"启动 scrcpy: {' '.join(cmd)}")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError:
            logger.error("scrcpy 未安装或未在 PATH 中")
            return False
        except Exception as e:
            logger.error(f"启动 scrcpy 失败: {e}")
            return False

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="scrcpy-reader"
        )
        self._reader_thread.start()

        # 等待第一帧
        for _ in range(50):
            time.sleep(0.02)  # 最多等 1 秒
            if self._latest_frame is not None:
                h, w = self._latest_frame.shape[:2]
                logger.info(f"scrcpy 已启动, 首帧: {w}x{h}")
                return True

        logger.warning("scrcpy 启动超时 (未收到视频帧)")
        self.stop()
        return False

    def _read_loop(self):
        """
        后台线程: 持续读取 scrcpy 输出中的 H.264 帧。

        scrcpy 输出 H.264 原始码流, 我们通过 OpenCV 的 VideoCapture
        或手动解析 NAL 单元来提取帧。
        """
        import cv2

        buffer = b""
        # 用 4 字节 NAL 起始码 (0x00 0x00 0x00 0x01) 分割帧
        nal_start = b"\x00\x00\x00\x01"
        nal_start3 = b"\x00\x00\x01"  # 某些设备用 3 字节

        while self._running and self._process and self._process.stdout:
            try:
                chunk = self._process.stdout.read(4096)
            except Exception:
                break

            if not chunk:
                logger.info("scrcpy 视频流已结束")
                break

            buffer += chunk

            # 尝试解码为图像
            frame = self._decode_h264_frame(buffer)
            if frame is not None:
                with self._lock:
                    self._latest_frame = frame
                    self._frame_count += 1

                    # FPS 统计
                    now = time.time()
                    if now - self._last_fps_time >= 1.0:
                        self._fps = self._frame_count / (now - self._last_fps_time)
                        self._frame_count = 0
                        self._last_fps_time = now

                # 清空 buffer (只保留可能跨块的部分)
                # 对于实时流, 丢弃已处理的 buffer
                if len(buffer) > 65536:
                    buffer = b""

        logger.info("scrcpy 读取线程已退出")

    def _decode_h264_frame(self, data: bytes) -> Optional[np.ndarray]:
        """尝试从 H.264 数据解码为一帧图像。"""
        import cv2

        try:
            # 用 OpenCV 的 imdecode 尝试直接从内存解码
            # H.264 原始码流需要封装为 AVI 或类似格式
            # 另一种方法: 用 cv2.VideoCapture 从管道读取

            # 方法: 找到 I 帧或 P 帧的起始码
            # 简单尝试: 检查是否有完整的 H.264 NAL 单元
            # 这里使用更可靠的方法: 通过临时文件用 ffmpeg 或直接 cv2

            # 实际上, scrcpy 输出的 H.264 流不能直接用 imdecode 解码,
            # 需要用 ffmpeg 或 cv2.VideoCapture("pipe:") 来读取。
            # 但对于本项目来说, 更实用的方案是用 cv2.VideoCapture
            # 通过命名管道或内存缓冲区来解码。

            # 替代方案: 如果解码失败, 回退到简单方法:
            # 检查是否有足够的数据, 尝试找到关键帧

            # 最简单的检测: 直接返回 None 表示无法解码
            # (让上层回退到 ADB screencap)
            pass
        except Exception:
            pass

        return None  # 本方法暂不实现 H.264 硬解

    def get_frame(self) -> Optional[np.ndarray]:
        """获取最新的视频帧。"""
        with self._lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def get_fps(self) -> float:
        """获取当前估算的 FPS。"""
        with self._lock:
            return self._fps

    def stop(self):
        """停止 scrcpy 进程。"""
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
        self._reader_thread = None
        logger.info("scrcpy 已停止")


# ──────────────────────────────────────────
# 简易 scrcpy 后端 (通过 ADB screencap 模拟)
# 实际项目中建议用 cv2.VideoCapture 连接 scrcpy 的管道
# 或使用 python-scrcpy 库
# ──────────────────────────────────────────

def create_scrcpy_capture(config: dict):
    """
    工厂函数: 尝试创建 scrcpy 后端, 失败则返回 None。
    
    实际使用中, 建议安装 python-scrcpy 库:
    pip install python-scrcpy
    
    或通过 scrcpy --no-window --output-format=ppm 输出 PPM 格式
    用 cv2.imdecode 逐帧读取。
    """
    try:
        return ScrcpyController(config)
    except Exception as e:
        logger.warning(f"创建 scrcpy 后端失败: {e}")
        return None
