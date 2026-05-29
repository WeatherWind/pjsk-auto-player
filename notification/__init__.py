"""
PJSK Auto Player — 通知系统

桌面通知 + Web/WebSocket 推送通知。
"""

from .desktop import DesktopNotifier
from .web import WebNotifier

__all__ = ["DesktopNotifier", "WebNotifier"]
