"""
PJSK Auto Player — Base Controller (Abstract Interface)
=========================================================

Defines the abstract controller interface, inspired by MAA Controller + ALAS design.

All subclasses must implement:
  - connect() / disconnect()
  - screencap() -> np.ndarray | None
  - click(x, y) -> bool        (relative 0~1)
  - swipe(x1, y1, x2, y2, duration_ms) -> bool  (relative 0~1)
  - get_screen_size() -> (width, height)

Coordinate convention: all public coordinate parameters use relative scale 0~1.
Internally, implementations multiply by screen resolution before sending to device.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

logger = logging.getLogger("pjsk.controller")


class BaseController(ABC):
    """Abstract base class for all device controllers.

    Controls a mobile device (typically Android) through various backends.
    All coordinates passed to public methods use relative scale 0~1,
    where (0, 0) is the top-left corner and (1, 1) is the bottom-right corner.
    """

    def __init__(self, config: dict):
        """Initialize the controller with application config.

        Args:
            config: Full application config dict, structured as:
                {
                    "adb": { "executable": ..., "device_serial": ... },
                    "screen": { "width": ..., "height": ... },
                    "scrcpy": { "executable": ..., "max_fps": ... },
                    ...
                }
        """
        self.config = config
        self._screen_width: int = config.get("screen", {}).get("width", 1080)
        self._screen_height: int = config.get("screen", {}).get("height", 2400)
        self._connected: bool = False

    # ── Lifecycle ──────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to the device.

        Returns:
            True if connection was successful, False otherwise.
        """
        ...

    @abstractmethod
    def disconnect(self) -> bool:
        """Disconnect from the device and release resources.

        Returns:
            True if disconnection was successful, False otherwise.
        """
        ...

    @property
    def is_connected(self) -> bool:
        """Whether the controller is currently connected to a device."""
        return self._connected

    # ── Screencap ──────────────────────────────────────────────

    @abstractmethod
    def screencap(self) -> Optional[np.ndarray]:
        """Capture the current device screen.

        Returns:
            BGR numpy array (OpenCV format) if successful, None on failure.
            Shape: (height, width, 3), dtype: np.uint8
        """
        ...

    # ── Touch Operations (relative coordinates 0~1) ────────────

    def _to_absolute(self, x_rel: float, y_rel: float) -> tuple[int, int]:
        """Convert relative coordinates (0~1) to absolute pixel coordinates.

        Args:
            x_rel: Relative X coordinate (0 = left, 1 = right)
            y_rel: Relative Y coordinate (0 = top, 1 = bottom)

        Returns:
            Tuple of (absolute_x, absolute_y) pixel coordinates.
        """
        return int(x_rel * self._screen_width), int(y_rel * self._screen_height)

    @abstractmethod
    def click(self, x: float, y: float) -> bool:
        """Click/tap at the given relative coordinates.

        Args:
            x: Relative X coordinate (0~1)
            y: Relative Y coordinate (0~1)

        Returns:
            True if the click was sent successfully.
        """
        ...

    @abstractmethod
    def swipe(self, x1: float, y1: float, x2: float, y2: float,
              duration_ms: int = 50) -> bool:
        """Swipe/drag from one point to another.

        Args:
            x1: Starting relative X coordinate (0~1)
            y1: Starting relative Y coordinate (0~1)
            x2: Ending relative X coordinate (0~1)
            y2: Ending relative Y coordinate (0~1)
            duration_ms: Duration of the swipe in milliseconds.

        Returns:
            True if the swipe was sent successfully.
        """
        ...

    @abstractmethod
    def get_screen_size(self) -> tuple[int, int]:
        """Get the device screen resolution.

        Returns:
            Tuple of (width, height) in pixels.
        """
        ...

    # ── Convenience Methods ────────────────────────────────────

    def press(self, x: float, y: float, duration_ms: int = 100) -> bool:
        """Long-press at the given relative coordinates.

        Default implementation uses swipe(x, y, x, y, duration_ms).
        Subclasses may override for better performance.

        Args:
            x: Relative X coordinate (0~1)
            y: Relative Y coordinate (0~1)
            duration_ms: Hold duration in milliseconds.

        Returns:
            True if successful.
        """
        return self.swipe(x, y, x, y, duration_ms)

    def flick_up(self, x: float, y: float,
                 distance_rel: float = 0.07, duration_ms: int = 50) -> bool:
        """Flick upward (flick note).

        Args:
            x: Relative X coordinate (0~1)
            y: Relative Y coordinate (0~1)
            distance_rel: Flick distance in relative coordinates (default 0.07 ≈ 75px at 1080p)
            duration_ms: Duration in milliseconds.

        Returns:
            True if successful.
        """
        return self.swipe(x, y, x, y - distance_rel, duration_ms)

    def flick_down(self, x: float, y: float,
                   distance_rel: float = 0.07, duration_ms: int = 50) -> bool:
        """Flick downward."""
        return self.swipe(x, y, x, y + distance_rel, duration_ms)

    def flick_left(self, x: float, y: float,
                   distance_rel: float = 0.07, duration_ms: int = 50) -> bool:
        """Flick left."""
        return self.swipe(x, y, x - distance_rel, y, duration_ms)

    def flick_right(self, x: float, y: float,
                    distance_rel: float = 0.07, duration_ms: int = 50) -> bool:
        """Flick right."""
        return self.swipe(x, y, x + distance_rel, y, duration_ms)
