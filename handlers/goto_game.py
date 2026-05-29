"""
PJSK Auto Player — 游戏启动/导航 Handler

负责:
  1. 启动 Project Sekai app
  2. 等待加载完成
  3. 导航到主页
  4. 处理弹窗/公告
  5. 进入执行入口
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from handlers import BaseHandler
from pipeline.timer import Timer
from vision.button import PjskButton

logger = logging.getLogger("pjsk.handler.goto")


class GotoHandler(BaseHandler):
    """游戏导航处理器。"""

    def __init__(self, controller=None, config: Optional[dict] = None):
        super().__init__(controller, config)
        self._package_name = "com.sega.pjsekai"
        self._max_wait = 60  # 最大等待游戏启动时间

    def start_game(self) -> bool:
        """启动 Project Sekai 游戏。"""
        self.log(f"🚀 启动游戏: {self._package_name}")
        if not self.controller:
            self.log("❌ 控制器未初始化", "error")
            return False
        self.controller.app_start(self._package_name)
        self.log("⏳ 等待游戏加载...")
        return self._wait_for_main_menu()

    def stop_game(self) -> bool:
        """停止游戏进程。"""
        self.log(f"🛑 停止游戏: {self._package_name}")
        if self.controller:
            self.controller.app_stop(self._package_name)
        return True

    def restart_game(self) -> bool:
        """重启游戏。"""
        self.log("🔄 重启游戏...")
        self.stop_game()
        time.sleep(2)
        return self.start_game()

    def _wait_for_main_menu(self) -> bool:
        """等待进入主页画面。"""
        timer = Timer(limit=self._max_wait, count=100)
        timer.start()
        while not timer.reached():
            frame = self._screencap()
            if frame is None:
                time.sleep(1)
                continue
            # 检测首页按钮（多种模式）
            button = self._find_any_button(frame, [
                "start_live", "multi_live", "tap_to_start",
            ])
            if button:
                self.log(f"✅ 已进入菜单 (检测到: {button.name})")
                return True
            time.sleep(0.5)
        self.log("❌ 游戏启动超时", "error")
        return False

    def navigate_to_live(self) -> bool:
        """导航到执行入口。"""
        self.log("🎵 导航到执行界面...")
        # 点击"开始演出"或"单人演出"
        timer = Timer(limit=15, count=30)
        timer.start()
        while not timer.reached():
            frame = self._screencap()
            if frame is None:
                time.sleep(0.5)
                continue
            button = self._find_any_button(frame, [
                "start_live", "multi_live",
            ])
            if button:
                self._click(button)
                self.log(f"✅ 点击: {button.name}")
                return True
            time.sleep(0.3)
        self.log("❌ 无法找到执行入口", "error")
        return False

    def handle_popups(self) -> int:
        """处理弹窗（公告、任务完成、活动等）。返回关闭的弹窗数。"""
        from vision.button import get_button
        closed = 0
        for _ in range(5):  # 最多处理 5 个弹窗
            frame = self._screencap()
            if frame is None:
                break
            # 尝试关闭按钮
            for btn_name in ["close_button", "ok_button", "cancel_button"]:
                btn = get_button(btn_name)
                if btn and btn.set_screen_size and btn.detect(frame):
                    self._click(btn)
                    closed += 1
                    time.sleep(0.5)
                    break
            else:
                break  # 没有可关闭的弹窗了
        if closed > 0:
            self.log(f"✅ 关闭了 {closed} 个弹窗")
        return closed

    def _screencap(self):
        """截图辅助。"""
        if self.controller and hasattr(self.controller, "screencap"):
            try:
                return self.controller.screencap()
            except Exception:
                return None
        return None

    def _click(self, button: PjskButton):
        """点击辅助。"""
        if self.controller and hasattr(self.controller, "click"):
            try:
                x, y = button.click_point
                self.controller.click(x, y)
            except Exception as e:
                self.log(f"点击失败: {e}", "error")

    def _find_any_button(self, frame, names: list[str]):
        """在画面中检测任意按钮。"""
        from vision.button import get_button, apply_screen_size
        h, w = frame.shape[:2]
        apply_screen_size(w, h)
        for name in names:
            btn = get_button(name)
            if btn and btn.detect(frame):
                return btn
        return None
