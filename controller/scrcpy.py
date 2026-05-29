"""
PJSK Auto Player — Scrcpy Controller
======================================

Implements BaseController via scrcpy video stream + minitouch touch backend.

Screenshot backend:
  - scrcpy PPM video stream (--output-format=ppm), ~30-60 FPS
  - Background reader thread continuously decodes PPM frames
  - get_frame() always returns the latest frame (frame-skip enabled)

Touch backend:
  - minitouch via local socket (tcp:1111), <5ms latency
  - Falls back to ADB input tap/swipe if minitouch unavailable.

All coordinates use relative scale 0~1; internally converted to absolute pixels
and scaled to minitouch coordinates.
"""

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Optional

import numpy as np

from controller.base import BaseController

logger = logging.getLogger("pjsk.controller.scrcpy")


class ScrcpyController(BaseController):
    """Scrcpy + Minitouch based device controller.

    Provides high-FPS screen capture via scrcpy PPM video stream
    and low-latency touch via minitouch socket protocol.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        scrcpy_cfg = config.get("scrcpy", {})
        adb_cfg = config.get("adb", {})

        # scrcpy settings
        self.executable = self._find_scrcpy(scrcpy_cfg.get("executable", "scrcpy"))
        self.serial = (adb_cfg.get("device_serial") or "").strip()
        self._max_fps = scrcpy_cfg.get("max_fps", 60)
        self._bit_rate = scrcpy_cfg.get("bit_rate", 8_000_000)
        self._scale = scrcpy_cfg.get("scale", 0.5)
        self._frame_skip = scrcpy_cfg.get("frame_skip", True)

        # scrcpy process & frame state
        self._process: Optional[subprocess.Popen] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None

        # PPM parser state
        self._buffer = b""
        self._state = "header"  # "header" | "data"
        self._ppm_width = 0
        self._ppm_height = 0
        self._ppm_data_size = 0

        # minitouch state
        self._mt_socket: Optional[socket.socket] = None
        self._mt_ready = False
        self._mt_max_contacts = 2
        self._mt_max_x = 1080
        self._mt_max_y = 2400
        self._mt_scale_x = 1.0
        self._mt_scale_y = 1.0
        self._mt_port = config.get("minitouch", {}).get("port", 1111)
        self._mt_binary_path = config.get("minitouch", {}).get("binary_path", "")

        self._connected = False

    # ── Scrcpy Binary Discovery ────────────────────────────────

    @staticmethod
    def _find_scrcpy(exe: str) -> str:
        """Locate the scrcpy executable on this system."""
        if os.path.isfile(exe):
            return exe
        which_cmd = "where" if sys.platform == "win32" else "which"
        try:
            subprocess.run([which_cmd, exe], capture_output=True, check=True)
            return exe
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("scrcpy executable '%s' not found in PATH", exe)
            return exe

    # ── Lifecycle ──────────────────────────────────────────────

    def connect(self) -> bool:
        """Start scrcpy PPM video stream and initialize minitouch.

        Returns True if both scrcpy stream and minitouch started successfully.
        Falls back gracefully if minitouch is unavailable.
        """
        if self._connected:
            return True

        # Start scrcpy video stream
        if not self._start_scrcpy():
            logger.error("Failed to start scrcpy video stream")
            return False

        # Try to initialize minitouch (non-fatal if it fails)
        try:
            self._init_minitouch()
        except Exception as e:
            logger.warning("minitouch init failed (falling back to ADB touch): %s", e)

        self._connected = True
        logger.info("ScrcpyController connected: %dx%d @ %d FPS",
                     self._screen_width, self._screen_height, self._max_fps)
        return True

    def disconnect(self) -> bool:
        """Stop scrcpy process and cleanup minitouch resources."""
        self._running = False
        self._connected = False

        # Close minitouch
        self._close_minitouch()

        # Stop scrcpy process
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

        self._latest_frame = None
        logger.info("ScrcpyController disconnected")
        return True

    # ── Screen Size ────────────────────────────────────────────

    def get_screen_size(self) -> tuple[int, int]:
        """Return the current screen resolution.

        Updated automatically from the first PPM frame header.
        """
        return self._screen_width, self._screen_height

    # ── Scrcpy Stream ──────────────────────────────────────────

    def _start_scrcpy(self) -> bool:
        """Launch scrcpy in PPM output mode."""
        cmd = [self.executable]

        if self.serial:
            cmd += ["-s", self.serial]

        # PPM mode: raw pixel data over stdout
        max_size = int(1080 * self._scale)
        cmd += [
            "--no-window",
            "--no-control",
            "--output-format=ppm",
            "--max-fps", str(self._max_fps),
            "--max-size", str(max_size),
            "--video-bit-rate", str(self._bit_rate),
        ]

        logger.info("Starting scrcpy PPM stream: max_fps=%d, scale=%.1f, max_size=%d",
                    self._max_fps, self._scale, max_size)

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except FileNotFoundError:
            logger.error("scrcpy not found — install via 'brew install scrcpy' (macOS) "
                         "or 'scoop install scrcpy' (Windows) or 'apt install scrcpy' (Linux)")
            return False
        except Exception as e:
            logger.error("Failed to start scrcpy: %s", e)
            return False

        self._running = True
        self._buffer = b""
        self._state = "header"
        self._reader_thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="scrcpy-ppm-reader",
        )
        self._reader_thread.start()

        # Wait for first frame
        for _ in range(200):  # up to 2 seconds
            time.sleep(0.01)
            with self._frame_lock:
                if self._latest_frame is not None:
                    h, w = self._latest_frame.shape[:2]
                    self._screen_width = w
                    self._screen_height = h
                    logger.info("scrcpy PPM stream started: %dx%d", w, h)
                    return True

        logger.warning("scrcpy PPM start timeout (no frame received in 2s)")
        self._running = False
        if self._process:
            self._process.terminate()
            self._process = None
        return False

    def _read_loop(self):
        """Background thread: continuously read and parse PPM frames from scrcpy stdout."""
        assert self._process is not None
        assert self._process.stdout is not None

        while self._running:
            try:
                chunk = self._process.stdout.read(65536)
            except Exception:
                break

            if not chunk:
                logger.info("scrcpy PPM stream ended")
                break

            self._buffer += chunk
            self._parse_buffer()

        logger.info("scrcpy PPM reader thread exited")

    def _parse_buffer(self):
        """Parse PPM frames from the accumulation buffer.

        PPM format: "P6\\n<width> <height>\\n255\\n" followed by W×H×3 RGB bytes.
        """
        while True:
            if self._state == "header":
                # Find "P6\n"
                first_nl = self._buffer.find(b"\n")
                if first_nl < 0:
                    break
                rest = self._buffer[first_nl + 1:]

                # Find second newline (dimension line)
                second_nl = rest.find(b"\n")
                if second_nl < 0:
                    break

                dims = rest[:second_nl].decode(errors="replace").strip()
                parts = dims.split()
                if len(parts) >= 2:
                    try:
                        self._ppm_width = int(parts[0])
                        self._ppm_height = int(parts[1])
                    except ValueError:
                        pass

                remaining = rest[second_nl + 1:]
                third_nl = remaining.find(b"\n")
                if third_nl < 0:
                    break

                data_start = first_nl + 1 + second_nl + 1 + third_nl + 1
                self._ppm_data_size = self._ppm_width * self._ppm_height * 3
                self._state = "data"
                self._buffer = self._buffer[data_start:]

            if self._state == "data":
                if len(self._buffer) < self._ppm_data_size:
                    break

                frame_data = self._buffer[:self._ppm_data_size]

                # PPM is RGB → convert to BGR for OpenCV
                rgb = np.frombuffer(frame_data, dtype=np.uint8).reshape(
                    self._ppm_height, self._ppm_width, 3,
                )
                bgr = rgb[:, :, ::-1]

                with self._frame_lock:
                    self._latest_frame = bgr

                # Remove consumed data, reset to header state
                self._buffer = self._buffer[self._ppm_data_size:]
                self._state = "header"
                continue

            break

    # ── Screencap ──────────────────────────────────────────────

    def screencap(self) -> Optional[np.ndarray]:
        """Get the latest frame from the scrcpy video stream.

        Returns the most recent frame (frame-skip: older frames are discarded).
        """
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    # ── Minitouch (Low-Latency Touch) ──────────────────────────

    def _init_minitouch(self) -> bool:
        """Initialize minitouch on the device and establish a socket connection.

        Steps:
          1. Push minitouch binary to device
          2. Start minitouch daemon via ADB shell
          3. Forward TCP port
          4. Connect local socket and parse protocol info
        """
        # Determine binary path
        mt_bin = self._mt_binary_path
        if not mt_bin:
            mt_bin = self._find_minitouch_binary()

        if not mt_bin or not os.path.exists(mt_bin):
            logger.warning("minitouch binary not found at '%s'", mt_bin)
            return False

        adb = self.config.get("adb", {}).get("executable", "adb")
        serial_args = ["-s", self.serial] if self.serial else []
        remote_path = "/data/local/tmp/minitouch"

        # Push binary
        push = subprocess.run(
            [adb, *serial_args, "push", mt_bin, remote_path],
            capture_output=True, text=True, timeout=10,
        )
        if push.returncode != 0:
            logger.warning("minitouch push failed: %s", push.stderr.strip())
            return False

        # Set permissions
        subprocess.run(
            [adb, *serial_args, "shell", "chmod", "755", remote_path],
            capture_output=True, timeout=5,
        )

        # Start minitouch daemon
        try:
            self._mt_proc = subprocess.Popen(
                [adb, *serial_args, "shell", remote_path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            logger.warning("minitouch start failed: %s", e)
            return False

        # Wait for minitouch to start listening
        for _ in range(40):  # up to ~1s
            check = subprocess.run(
                [adb, *serial_args, "shell", "ls", "/proc/net/tcp"],
                capture_output=True, text=True, timeout=3,
            )
            if "0457" in check.stdout:  # port 1111 = 0x0457
                break
            time.sleep(0.025)
        else:
            time.sleep(0.1)

        # ADB forward
        forward = subprocess.run(
            [adb, *serial_args, "forward", f"tcp:{self._mt_port}", f"tcp:{self._mt_port}"],
            capture_output=True, text=True, timeout=5,
        )
        if forward.returncode != 0:
            logger.warning("ADB forward failed: %s", forward.stderr.strip())
            self._cleanup_minitouch()
            return False

        # Connect socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect(("127.0.0.1", self._mt_port))

            # Read welcome: "v <version> <max_contacts> <max_x> <max_y>\n"
            welcome = b""
            while b"\n" not in welcome:
                try:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    welcome += chunk
                except socket.timeout:
                    break

            welcome_str = welcome.decode(errors="replace").strip()
            logger.info("minitouch connected: %s", welcome_str)

            parts = welcome_str.split()
            if len(parts) >= 4 and parts[0] == "v":
                self._mt_max_contacts = int(parts[1])
                self._mt_max_x = int(parts[2])
                self._mt_max_y = int(parts[3])
                self._mt_scale_x = self._mt_max_x / self._screen_width
                self._mt_scale_y = self._mt_max_y / self._screen_height

            self._mt_socket = sock
            self._mt_ready = True
            logger.info("minitouch ready: %d contacts, %dx%d",
                        self._mt_max_contacts, self._mt_max_x, self._mt_max_y)
            return True

        except (socket.error, OSError) as e:
            logger.warning("minitouch socket connect failed: %s", e)
            self._cleanup_minitouch()
            return False

    def _find_minitouch_binary(self) -> str:
        """Locate minitouch binary automatically based on device architecture."""
        adb = self.config.get("adb", {}).get("executable", "adb")
        serial_args = ["-s", self.serial] if self.serial else []

        arch = ""
        try:
            result = subprocess.run(
                [adb, *serial_args, "shell", "getprop", "ro.product.cpu.abi"],
                capture_output=True, text=True, timeout=5,
            )
            arch = result.stdout.strip()
        except Exception:
            pass

        mapping = {
            "arm64-v8a": "arm64",
            "armeabi-v7a": "arm",
            "x86_64": "x86_64",
            "x86": "x86",
        }
        arch_name = mapping.get(arch, arch)

        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "bin", "minitouch")
        candidates = [
            os.path.join(base_dir, f"minitouch_{arch_name}"),
            os.path.join(base_dir, "minitouch"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return ""

    def _close_minitouch(self):
        """Close minitouch socket and terminate the daemon process."""
        self._mt_ready = False
        if self._mt_socket:
            try:
                self._mt_socket.close()
            except Exception:
                pass
            self._mt_socket = None
        self._cleanup_minitouch()

    def _cleanup_minitouch(self):
        """Kill the minitouch subprocess and remove ADB forward."""
        if hasattr(self, "_mt_proc") and self._mt_proc:
            try:
                self._mt_proc.terminate()
            except Exception:
                pass
            self._mt_proc = None

    # ── Touch Operations (relative 0~1) ────────────────────────

    def click(self, x: float, y: float) -> bool:
        """Click at relative coordinates.

        Uses minitouch if available, falls back to ADB input tap.
        """
        if self._mt_ready:
            return self._mt_click(x, y)
        return self._adb_click(x, y)

    def swipe(self, x1: float, y1: float, x2: float, y2: float,
              duration_ms: int = 50) -> bool:
        """Swipe between relative coordinates.

        Uses minitouch if available, falls back to ADB input swipe.
        """
        if self._mt_ready:
            return self._mt_swipe(x1, y1, x2, y2, duration_ms)
        return self._adb_swipe(x1, y1, x2, y2, duration_ms)

    # ── Minitouch Touch Methods ────────────────────────────────

    def _mt_click(self, x_rel: float, y_rel: float) -> bool:
        """Click via minitouch socket protocol."""
        ax, ay = self._to_absolute(x_rel, y_rel)
        sx = int(ax * self._mt_scale_x)
        sy = int(ay * self._mt_scale_y)
        try:
            cmd = f"d 0 {sx} {sy} 50\nc\nu 0\nc\n"
            assert self._mt_socket is not None
            self._mt_socket.sendall(cmd.encode())
            return True
        except (socket.error, OSError) as e:
            logger.warning("minitouch click failed: %s", e)
            self._mt_ready = False
            return self._adb_click(x_rel, y_rel)

    def _mt_swipe(self, x1_rel: float, y1_rel: float,
                  x2_rel: float, y2_rel: float,
                  duration_ms: int) -> bool:
        """Swipe via minitouch socket protocol with linear interpolation."""
        ax1, ay1 = self._to_absolute(x1_rel, y1_rel)
        ax2, ay2 = self._to_absolute(x2_rel, y2_rel)
        sx1 = int(ax1 * self._mt_scale_x)
        sy1 = int(ay1 * self._mt_scale_y)
        sx2 = int(ax2 * self._mt_scale_x)
        sy2 = int(ay2 * self._mt_scale_y)

        try:
            cmd = f"d 0 {sx1} {sy1} 50\nc\n"

            steps = max(int(duration_ms / 5), 1)
            for i in range(1, steps + 1):
                t = i / steps
                mx = int(sx1 + (sx2 - sx1) * t)
                my = int(sy1 + (sy2 - sy1) * t)
                cmd += f"m 0 {mx} {my} 50\nc\n"

            cmd += "u 0\nc\n"

            assert self._mt_socket is not None
            self._mt_socket.sendall(cmd.encode())
            time.sleep(duration_ms / 1000.0)
            return True
        except (socket.error, OSError) as e:
            logger.warning("minitouch swipe failed: %s", e)
            self._mt_ready = False
            return self._adb_swipe(x1_rel, y1_rel, x2_rel, y2_rel, duration_ms)

    # ── ADB Fallback Touch Methods ─────────────────────────────

    def _adb_click(self, x_rel: float, y_rel: float) -> bool:
        """Fallback: click via ADB input tap."""
        adb = self.config.get("adb", {}).get("executable", "adb")
        serial_args = ["-s", self.serial] if self.serial else []
        ax, ay = self._to_absolute(x_rel, y_rel)
        try:
            subprocess.run(
                [adb, *serial_args, "shell", "input", "tap", str(ax), str(ay)],
                capture_output=True, timeout=5,
            )
            return True
        except Exception as e:
            logger.warning("ADB tap fallback failed: %s", e)
            return False

    def _adb_swipe(self, x1_rel: float, y1_rel: float,
                   x2_rel: float, y2_rel: float,
                   duration_ms: int) -> bool:
        """Fallback: swipe via ADB input swipe."""
        adb = self.config.get("adb", {}).get("executable", "adb")
        serial_args = ["-s", self.serial] if self.serial else []
        ax1, ay1 = self._to_absolute(x1_rel, y1_rel)
        ax2, ay2 = self._to_absolute(x2_rel, y2_rel)
        try:
            subprocess.run(
                [adb, *serial_args, "shell", "input", "swipe",
                 str(ax1), str(ay1), str(ax2), str(ay2), str(int(duration_ms))],
                capture_output=True, timeout=5,
            )
            return True
        except Exception as e:
            logger.warning("ADB swipe fallback failed: %s", e)
            return False
