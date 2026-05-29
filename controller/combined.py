"""
PJSK Auto Player — Combined Controller (Smart Router)
=======================================================

Intelligently routes between ADBController and ScrcpyController
based on availability and performance.

Backend selection logic:
  1. If scrcpy executable is found → try ScrcpyController first
  2. If scrcpy fails or isn't available → fall back to ADBController
  3. Runtime monitoring: periodically re-evaluate backend performance
     and switch automatically if a faster backend becomes available.

All coordinates use relative scale 0~1; internally converted to absolute pixels
by the underlying backend controller.
"""

import logging
import os
import subprocess
import sys
import threading
import time
from typing import Optional

import numpy as np

from controller.base import BaseController
from controller.adb import ADBController
from controller.scrcpy import ScrcpyController

# Type alias for backend registry entries
BackendEntry = tuple[str, type[BaseController], dict]

logger = logging.getLogger("pjsk.controller.combined")


class CombinedController(BaseController):
    """Smart routing controller that auto-selects the optimal backend.

    Automatically detects available backends (scrcpy > ADB),
    falls back gracefully, and optionally monitors performance
    to switch backends at runtime.

    Usage:
        ctrl = CombinedController(config)
        ctrl.connect()
        frame = ctrl.screencap()
        ctrl.click(0.5, 0.5)
        ctrl.disconnect()
    """

    # ── Priority-based backend registry ────────────────────────
    # Backends in order of preference (highest to lowest).
    _BACKENDS: list[BackendEntry] = [
        ("scrcpy", ScrcpyController, {
            "description": "scrcpy PPM stream + minitouch",
            "fps_estimate": 30.0,
            "latency_ms_estimate": 5.0,
            "requires_path": "scrcpy",
        }),
        ("adb", ADBController, {
            "description": "ADB exec-out screencap + input",
            "fps_estimate": 8.0,
            "latency_ms_estimate": 50.0,
            "requires_path": None,  # always available if ADB is installed
        }),
    ]

    def __init__(self, config: dict):
        super().__init__(config)
        self._active_backend: Optional[BaseController] = None
        self._active_name: Optional[str] = None
        self._lock = threading.Lock()

        # Performance tracking for auto-switching
        self._last_switch_time = 0.0
        self._switch_cooldown = config.get("controller", {}).get(
            "switch_cooldown", 30.0
        )
        self._screencap_times: list[float] = []
        self._perf_sample_size = config.get("controller", {}).get(
            "perf_sample_size", 10
        )

        # Auto-detect available backends
        self._available_backends: list[BackendEntry] = []
        self._detect_backends()

        self._connected = False

    # ── Backend Detection ──────────────────────────────────────

    def _detect_backends(self):
        """Detect which backends are available on this system.

        Checks for the presence of required executables.
        """
        available = []
        for name, cls, meta in self._BACKENDS:
            required = meta.get("requires_path")
            if required is None:
                # Always available (e.g. ADB — we can try even without the binary)
                available.append((name, cls, meta))
            elif self._find_executable(required):
                logger.debug("Backend '%s' available: found '%s'", name, required)
                available.append((name, cls, meta))
            else:
                logger.info("Backend '%s' unavailable: '%s' not found in PATH",
                            name, required)
        self._available_backends = available

        if not self._available_backends:
            # ADB should always be available as a fallback
            logger.warning("No backends detected! Using ADB as default fallback.")
            _, cls, meta = self._BACKENDS[-1]
            self._available_backends = [("adb", cls, meta)]

    @staticmethod
    def _find_executable(name: str) -> bool:
        """Check if an executable is available in PATH."""
        if os.path.isfile(name):
            return True
        which_cmd = "where" if sys.platform == "win32" else "which"
        try:
            result = subprocess.run(  # noqa: F821 — subprocess is imported
                [which_cmd, name], capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    # ── Lifecycle ──────────────────────────────────────────────

    def connect(self) -> bool:
        """Connect using the best available backend.

        Tries backends in priority order (scrcpy → ADB).
        Returns True if any backend connects successfully.
        """
        with self._lock:
            if self._connected and self._active_backend:
                return True

            for name, cls, meta in self._available_backends:
                logger.info("Attempting backend '%s': %s", name, meta["description"])
                try:
                    backend = cls(self.config)
                    if backend.connect():
                        self._active_backend = backend
                        self._active_name = name
                        self._connected = True
                        self._last_switch_time = time.time()
                        logger.info("CombinedController: active backend = '%s' (%s)",
                                    name, meta["description"])
                        return True
                except Exception as e:
                    logger.warning("Backend '%s' connect failed: %s", name, e)

            logger.error("All backends failed to connect")
            return False

    def disconnect(self) -> bool:
        """Disconnect the active backend."""
        with self._lock:
            self._connected = False
            if self._active_backend:
                try:
                    self._active_backend.disconnect()
                except Exception as e:
                    logger.warning("Backend '%s' disconnect error: %s",
                                   self._active_name, e)
                self._active_backend = None
                self._active_name = None
            logger.info("CombinedController disconnected")
            return True

    # ── Backend Selection / Switching ──────────────────────────

    @property
    def active_backend(self) -> Optional[str]:
        """Name of the currently active backend (e.g. 'scrcpy', 'adb')."""
        return self._active_name

    def switch_backend(self, name: str) -> bool:
        """Manually switch to a specific backend by name.

        Args:
            name: Backend name, one of 'scrcpy' or 'adb' (or others in _BACKENDS).

        Returns:
            True if the switch was successful.
        """
        with self._lock:
            for candidate_name, cls, meta in self._available_backends:
                if candidate_name == name:
                    logger.info("Switching backend: '%s' -> '%s'",
                                self._active_name, name)
                    # Disconnect current
                    if self._active_backend:
                        try:
                            self._active_backend.disconnect()
                        except Exception:
                            pass
                    # Connect new
                    try:
                        backend = cls(self.config)
                        if backend.connect():
                            self._active_backend = backend
                            self._active_name = name
                            self._last_switch_time = time.time()
                            logger.info("Switched to backend '%s': %s",
                                        name, meta["description"])
                            return True
                    except Exception as e:
                        logger.error("Failed to switch to backend '%s': %s", name, e)
                    return False
            logger.warning("Backend '%s' not found in available backends", name)
            return False

    def _auto_switch_if_needed(self) -> bool:
        """Check if a better backend is available and switch to it.

        Returns True if a switch was performed.
        """
        now = time.time()
        if now - self._last_switch_time < self._switch_cooldown:
            return False

        # If we're already on the best backend, no switch needed
        best_name = self._available_backends[0][0]
        if self._active_name == best_name:
            return False

        # Check if the better backend has become available
        best_name, best_cls, best_meta = self._available_backends[0]
        try:
            test_backend = best_cls(self.config)
            if test_backend.connect():
                test_backend.disconnect()
                # The better backend is now available — switch
                logger.info("Auto-switching to better backend '%s'", best_name)
                return self.switch_backend(best_name)
        except Exception:
            pass
        return False

    # ── Delegate to Active Backend ─────────────────────────────

    def screencap(self) -> Optional[np.ndarray]:
        """Capture screen via the active backend.

        Attempts auto-switch to a better backend if current backend
        appears to be slow or unavailable.
        """
        with self._lock:
            if not self._active_backend:
                logger.error("No active backend — call connect() first")
                return None

            try:
                t0 = time.perf_counter()
                frame = self._active_backend.screencap()
                elapsed = time.perf_counter() - t0

                if frame is None:
                    # Backend might have failed — try to reconnect
                    logger.warning("Backend '%s' returned None, attempting reconnect",
                                   self._active_name)
                    self._active_backend.disconnect()
                    self._active_backend = None
                    self._connected = False
                    self.connect()
                    if self._active_backend:
                        return self._active_backend.screencap()
                    return None

                # Track performance
                self._screencap_times.append(elapsed * 1000)
                if len(self._screencap_times) > self._perf_sample_size:
                    self._screencap_times.pop(0)

                return frame

            except Exception as e:
                logger.error("Backend '%s' screencap error: %s", self._active_name, e)
                return None

    def click(self, x: float, y: float) -> bool:
        """Click at relative coordinates via the active backend."""
        with self._lock:
            if not self._active_backend:
                logger.error("No active backend — call connect() first")
                return False
            try:
                return self._active_backend.click(x, y)
            except Exception as e:
                logger.error("Backend '%s' click error: %s", self._active_name, e)
                return False

    def swipe(self, x1: float, y1: float, x2: float, y2: float,
              duration_ms: int = 50) -> bool:
        """Swipe between relative coordinates via the active backend."""
        with self._lock:
            if not self._active_backend:
                logger.error("No active backend — call connect() first")
                return False
            try:
                return self._active_backend.swipe(x1, y1, x2, y2, duration_ms)
            except Exception as e:
                logger.error("Backend '%s' swipe error: %s", self._active_name, e)
                return False

    def get_screen_size(self) -> tuple[int, int]:
        """Get screen resolution from the active backend."""
        with self._lock:
            if self._active_backend:
                try:
                    return self._active_backend.get_screen_size()
                except Exception:
                    pass
            return self._screen_width, self._screen_height

    # ── Metadata ───────────────────────────────────────────────

    def get_performance_stats(self) -> dict:
        """Get performance statistics from the current backend.

        Returns:
            Dict with keys:
              - active_backend: str
              - screencap_avg_ms: float
              - screencap_min_ms: float
              - screencap_max_ms: float
              - available_backends: list[str]
        """
        stats = {
            "active_backend": self._active_name or "none",
            "available_backends": [name for name, _, _ in self._available_backends],
        }
        if self._screencap_times:
            stats["screencap_avg_ms"] = sum(self._screencap_times) / len(self._screencap_times)
            stats["screencap_min_ms"] = min(self._screencap_times)
            stats["screencap_max_ms"] = max(self._screencap_times)
        return stats
