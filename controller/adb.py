"""
PJSK Auto Player — ADB Controller
===================================

Implements BaseController via Android Debug Bridge (ADB).

Screenshot backends:
  - exec-out (default): adb exec-out screencap -p, ~5-15 FPS
  - file (compat): adb shell screencap + adb pull, ~3-8 FPS

Touch backend:
  - adb shell input tap/swipe, ~50ms latency
  - Falls back gracefully when minitouch is not available.

All coordinates use relative scale 0~1; internally converted to absolute pixels.
"""

import logging
import os
import subprocess
import sys
import time
from typing import Optional

import numpy as np

from controller.base import BaseController

logger = logging.getLogger("pjsk.controller.adb")


class ADBController(BaseController):
    """ADB-based device controller.

    Communicates with an Android device through the Android Debug Bridge.
    Supports exec-out and file-based screencap backends.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        adb_cfg = config.get("adb", {})
        self.executable = self._find_adb(adb_cfg.get("executable", "adb"))
        self.serial = (adb_cfg.get("device_serial") or "").strip()
        self._screencap_method = adb_cfg.get("screencap_method", "exec-out")
        self._temp_dir = adb_cfg.get("temp_dir", "/sdcard/")
        self._connected = False

    # ── ADB Binary Discovery ───────────────────────────────────

    @staticmethod
    def _find_adb(exe: str) -> str:
        """Locate the ADB executable on this system."""
        if os.path.isfile(exe):
            return exe
        which_cmd = "where" if sys.platform == "win32" else "which"
        try:
            subprocess.run([which_cmd, exe], capture_output=True, check=True)
            return exe
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("ADB executable '%s' not found in PATH", exe)
            return exe

    # ── ADB Command Builder ────────────────────────────────────

    def _adb_cmd(self, *args: str) -> list[str]:
        """Build an ADB command list with device serial if set."""
        cmd = [self.executable]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        return cmd

    # ── Lifecycle ──────────────────────────────────────────────

    def connect(self) -> bool:
        """Connect to the device via ADB.

        Returns True if the device is already connected or was connected.
        """
        if self._connected:
            return True
        # Check if device is reachable
        try:
            result = subprocess.run(
                self._adb_cmd("get-state"),
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and "device" in result.stdout.strip().lower():
                self._connected = True
                logger.info("ADB connected to serial=%s", self.serial or "(auto)")
                return True
        except Exception as e:
            logger.warning("ADB connect failed: %s", e)
        return False

    def disconnect(self) -> bool:
        """Disconnect from the device."""
        self._connected = False
        logger.info("ADB disconnected")
        return True

    # ── Screen Size ────────────────────────────────────────────

    def get_screen_size(self) -> tuple[int, int]:
        """Query device screen size via 'adb shell wm size'.

        Falls back to config values on failure.
        """
        try:
            result = subprocess.run(
                self._adb_cmd("shell", "wm", "size"),
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if "Physical size:" in line or "Override size:" in line:
                    size_str = line.split()[-1].strip()
                    if "x" in size_str:
                        w_str, h_str = size_str.split("x")
                        w, h = int(w_str), int(h_str)
                        self._screen_width = w
                        self._screen_height = h
                        return w, h
        except Exception as e:
            logger.warning("Failed to get screen size via ADB: %s", e)
        return self._screen_width, self._screen_height

    # ── Screencap ──────────────────────────────────────────────

    def screencap(self) -> Optional[np.ndarray]:
        """Capture device screen using the configured screencap method.

        Method is selected by config['adb']['screencap_method']:
          - "exec-out": adb exec-out screencap -p (default, 5-15 FPS)
          - "file":     adb shell screencap + adb pull (compat, 3-8 FPS)
        """
        import cv2  # Delayed import to avoid forcing cv2 at import time

        method = self._screencap_method
        if method == "exec-out":
            return self._screencap_execout(cv2)
        elif method == "file":
            return self._screencap_file(cv2)
        else:
            logger.warning("Unknown screencap method '%s', falling back to exec-out", method)
            return self._screencap_execout(cv2)

    def _screencap_execout(self, cv2) -> Optional[np.ndarray]:
        """Screencap via 'adb exec-out screencap -p' (fastest ADB method)."""
        try:
            result = subprocess.run(
                self._adb_cmd("exec-out", "screencap", "-p"),
                capture_output=True, timeout=15,
            )
            if result.returncode != 0 or len(result.stdout) < 100:
                logger.warning("exec-out screencap failed (%d bytes)", len(result.stdout))
                return None

            img_arr = np.frombuffer(result.stdout, dtype=np.uint8)
            frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
            if frame is None:
                logger.warning("exec-out screencap decode failed")
                return None
            return frame

        except subprocess.TimeoutExpired:
            logger.warning("exec-out screencap timed out")
            return None
        except Exception as e:
            logger.warning("exec-out screencap error: %s", e)
            return None

    def _screencap_file(self, cv2) -> Optional[np.ndarray]:
        """Screencap via file (adb shell screencap + adb pull, more compatible)."""
        try:
            ts = int(time.time() * 1000)
            remote = f"{self._temp_dir}ss_{ts}.png"
            local = f"__temp_ss_{ts}.png"

            subprocess.run(
                self._adb_cmd("shell", "screencap", "-p", remote),
                capture_output=True, timeout=15,
            )
            subprocess.run(
                self._adb_cmd("pull", remote, local),
                capture_output=True, timeout=15,
            )
            subprocess.run(
                self._adb_cmd("shell", "rm", remote),
                capture_output=True, timeout=10,
            )

            frame = cv2.imread(local)
            if local and os.path.exists(local):
                os.remove(local)
            return frame

        except Exception as e:
            logger.warning("file screencap error: %s", e)
            return None

    # ── Touch Operations (relative 0~1 → absolute pixels) ─────

    def click(self, x: float, y: float) -> bool:
        """Click at relative coordinates via 'adb shell input tap'.

        Args:
            x: Relative X coordinate (0~1)
            y: Relative Y coordinate (0~1)
        """
        ax, ay = self._to_absolute(x, y)
        try:
            subprocess.run(
                self._adb_cmd("shell", "input", "tap", str(ax), str(ay)),
                capture_output=True, timeout=5,
            )
            return True
        except Exception as e:
            logger.warning("ADB tap(%d, %d) failed: %s", ax, ay, e)
            return False

    def swipe(self, x1: float, y1: float, x2: float, y2: float,
              duration_ms: int = 50) -> bool:
        """Swipe at relative coordinates via 'adb shell input swipe'.

        Args:
            x1, y1: Starting relative coordinates (0~1)
            x2, y2: Ending relative coordinates (0~1)
            duration_ms: Swipe duration in milliseconds.
        """
        ax1, ay1 = self._to_absolute(x1, y1)
        ax2, ay2 = self._to_absolute(x2, y2)
        try:
            subprocess.run(
                self._adb_cmd(
                    "shell", "input", "swipe",
                    str(ax1), str(ay1), str(ax2), str(ay2),
                    str(int(duration_ms)),
                ),
                capture_output=True, timeout=5,
            )
            return True
        except Exception as e:
            logger.warning("ADB swipe(%d,%d→%d,%d) failed: %s",
                           ax1, ay1, ax2, ay2, e)
            return False
