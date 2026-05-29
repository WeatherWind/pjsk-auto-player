"""
PJSK Auto Player — Device Controller Layer
=============================================

Abstract device controller layer inspired by MAA Controller + ALAS design.

Provides:
  - BaseController: abstract interface (connect/disconnect/screencap/click/swipe)
  - ADBController: ADB-based implementation (adb shell input + exec-out screencap)
  - ScrcpyController: scrcpy video stream + minitouch implementation
  - CombinedController: smart routing, auto-selects optimal backend

All coordinates use relative scale 0~1, internally multiplied by screen resolution.
"""

from controller.base import BaseController
from controller.adb import ADBController
from controller.scrcpy import ScrcpyController
from controller.combined import CombinedController

__all__ = [
    "BaseController",
    "ADBController",
    "ScrcpyController",
    "CombinedController",
]
