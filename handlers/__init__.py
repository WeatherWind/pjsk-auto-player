"""
PJSK Auto Player — Handler 交互处理器系统

受 ALAS module/handler/ 启发。
每个 Handler 封装一个游戏交互领域：
  - goto: 启动游戏 → 登录 → 主页导航
  - select_song: 选歌 → 选难度 → 确认
  - handle_result: 结算画面 → 跳过 → 统计
  - event_detect: 活动检测 → 自动选曲 → 策略推荐
  - reconnect: 断线检测 → 重连

所有 Handler 继承 BaseHandler，共享 controller + config。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("pjsk.handler")


class BaseHandler:
    """Handler 基类。"""

    def __init__(self, controller=None, config: Optional[dict] = None):
        self.controller = controller
        self.config = config or {}

    def set_controller(self, controller):
        self.controller = controller

    def set_config(self, config: dict):
        self.config = config

    def log(self, msg: str, level: str = "info"):
        getattr(logger, level, logger.info)("[%s] %s", self.__class__.__name__, msg)
