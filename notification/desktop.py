#!/usr/bin/env python3
"""
PJSK Auto Player — 桌面通知

支持平台:
  - macOS: osascript (系统原生通知)
  - Windows: win10toast (可选) / print 回退
  - Linux: notify-send (可选) / print 回退
"""

import logging
import platform
import shutil
import subprocess
import sys
from typing import Optional

logger = logging.getLogger("pjsk.notification.desktop")


class DesktopNotifier:
    """
    桌面通知发送器。

    自动检测操作系统并选择最佳通知方式。

    用法:
        notifier = DesktopNotifier()
        notifier.notify(
            title="PJSK Auto Player",
            message="打歌完成！",
            icon="path/to/icon.png",
        )
    """

    def __init__(self, icon: Optional[str] = None):
        self._icon = icon
        self._system = platform.system()
        self._available = self._check_available()

    # ── 可用性检测 ──────────────────────────────────────────

    def _check_available(self) -> bool:
        """检测当前平台的通知机制是否可用。"""
        if self._system == "Darwin":
            # macOS: osascript 总是可用
            return True
        elif self._system == "Windows":
            return self._check_windows()
        elif self._system == "Linux":
            return self._check_linux()
        return False

    def _check_windows(self) -> bool:
        """检查 Windows toast 通知是否可用。"""
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            # 快速测试
            return True
        except ImportError:
            logger.info("win10toast 未安装，回退到 print 模式")
            return False
        except Exception as e:
            logger.debug(f"Windows 通知检测失败: {e}")
            return False

    def _check_linux(self) -> bool:
        """检查 Linux notify-send 是否可用。"""
        return shutil.which("notify-send") is not None

    @property
    def available(self) -> bool:
        """通知系统是否可用。"""
        return self._available

    # ── 发送通知 ───────────────────────────────────────────

    def notify(
        self,
        title: str,
        message: str,
        icon: Optional[str] = None,
        sound: bool = False,
        timeout: int = 5,
    ) -> bool:
        """
        发送桌面通知。

        参数:
            title: 通知标题
            message: 通知正文
            icon: 图标路径 (可选，覆盖构造函数中的 icon)
            sound: 是否播放提示音
            timeout: 通知显示时长 (秒，仅部分平台支持)

        返回:
            bool: 通知是否成功发送
        """
        icon_path = icon or self._icon

        if self._system == "Darwin":
            return self._notify_macos(title, message, icon_path, sound)
        elif self._system == "Windows":
            return self._notify_windows(title, message, icon_path, timeout)
        elif self._system == "Linux":
            return self._notify_linux(title, message, icon_path, timeout)
        else:
            # 回退
            self._notify_fallback(title, message)
            return False

    # ── macOS (osascript) ────────────────────────────────────

    def _notify_macos(
        self,
        title: str,
        message: str,
        icon: Optional[str] = None,
        sound: bool = False,
    ) -> bool:
        """
        通过 osascript 发送 macOS 原生通知。

        icon 在 osascript 中无法直接指定，但可以配合
        terminal-notifier 使用 (如果已安装)。
        """
        # 如果安装了 terminal-notifier，优先使用
        terminal_notifier = shutil.which("terminal-notifier")
        if terminal_notifier:
            try:
                cmd = [
                    terminal_notifier,
                    "-title", title,
                    "-message", message,
                    "-timeout", "5",
                ]
                if icon:
                    cmd += ["-contentImage", icon]
                if sound:
                    cmd += ["-sound", "default"]
                subprocess.run(cmd, capture_output=True, timeout=5)
                logger.debug(f"macOS 通知 (terminal-notifier): {title}")
                return True
            except Exception as e:
                logger.debug(f"terminal-notifier 失败，回退 osascript: {e}")

        # 回退 osascript
        try:
            osa_script = (
                f'display notification "{message}" '
                f'with title "{title}"'
            )
            if sound:
                osa_script += ' sound name "default"'
            subprocess.run(
                ["osascript", "-e", osa_script],
                capture_output=True,
                timeout=5,
            )
            logger.debug(f"macOS 通知 (osascript): {title}")
            return True
        except Exception as e:
            logger.warning(f"macOS 通知失败: {e}")
            self._notify_fallback(title, message)
            return False

    # ── Windows (win10toast) ────────────────────────────────

    def _notify_windows(
        self,
        title: str,
        message: str,
        icon: Optional[str] = None,
        timeout: int = 5,
    ) -> bool:
        """使用 win10toast 发送 Windows toast 通知。"""
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast(
                title,
                message,
                icon_path=icon or "",
                duration=timeout,
                threaded=True,
            )
            logger.debug(f"Windows 通知: {title}")
            return True
        except ImportError:
            self._notify_fallback(title, message)
            return False
        except Exception as e:
            logger.warning(f"Windows 通知失败: {e}")
            self._notify_fallback(title, message)
            return False

    # ── Linux (notify-send) ─────────────────────────────────

    def _notify_linux(
        self,
        title: str,
        message: str,
        icon: Optional[str] = None,
        timeout: int = 5,
    ) -> bool:
        """使用 notify-send 发送 Linux 桌面通知。"""
        try:
            cmd = [
                "notify-send",
                title,
                message,
                "-t", str(timeout * 1000),
            ]
            if icon:
                cmd += ["-i", icon]
            subprocess.run(cmd, capture_output=True, timeout=5)
            logger.debug(f"Linux 通知: {title}")
            return True
        except Exception as e:
            logger.warning(f"Linux 通知失败: {e}")
            self._notify_fallback(title, message)
            return False

    # ── 回退 (print) ────────────────────────────────────────

    def _notify_fallback(self, title: str, message: str):
        """通用回退：打印到终端。"""
        print(f"\n🔔 [{title}] {message}\n", file=sys.stderr)
        logger.info(f"通知回退: [{title}] {message}")


# ══════════════════════════════════════════════════════════════
#  快捷函数
# ══════════════════════════════════════════════════════════════

def notify(
    title: str,
    message: str,
    icon: Optional[str] = None,
    sound: bool = False,
) -> bool:
    """
    一键发送桌面通知 (使用全局 DesktopNotifier 实例)。

    用法:
        from notification.desktop import notify
        notify("PJSK", "打歌完成！")
    """
    notifier = DesktopNotifier()
    return notifier.notify(title, message, icon=icon, sound=sound)


# ── 自测 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    n = DesktopNotifier()
    print(f"系统: {platform.system()}")
    print(f"通知可用: {n.available}")

    success = n.notify(
        title="PJSK Auto Player 测试",
        message="这是桌面通知测试消息",
        sound=True,
    )
    print(f"发送结果: {'成功' if success else '失败'}")
