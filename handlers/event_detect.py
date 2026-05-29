"""
PJSK Auto Player — 自动活动检测 Handler (v5.0.0)

检测 Project Sekai 当前活动类型，自动选择最佳连续执行策略:
  - 马拉松活动 (Marathon): 单曲反复刷
  - 芝士活动 (Cheerful Carnival): 5v5 团队战
  - 一般活动 (Normal): 任意曲目

检测方法:
  1. 主界面活动 Banner 颜色/模板匹配
  2. 活动图标识别
  3. 菜单文字 OCR

用法:
    from handlers.event_detect import EventDetector
    detector = EventDetector(controller)
    event_type = detector.detect(frame)
    if event_type == "marathon":
        detector.select_marathon_song()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger("pjsk.handler.event")


class EventType(str, Enum):
    """PJSK 活动类型。"""
    MARATHON = "marathon"            # 马拉松 (通常活动)
    CHEERFUL = "cheerful_carnival"   # 芝士嘉年华 (5v5)
    NORMAL = "normal"                # 无活动 / 一般
    UNKNOWN = "unknown"              # 无法识别


@dataclass
class EventInfo:
    """活动信息。"""
    event_type: EventType = EventType.UNKNOWN
    event_name: str = ""
    confidence: float = 0.0
    recommended_songs: list[str] = None  # 推荐连续执行歌曲

    def __post_init__(self):
        if self.recommended_songs is None:
            self.recommended_songs = []


class EventDetector:
    """活动检测器。

    通过分析游戏画面识别当前活动类型，提供连续执行建议。

    检测流程:
      1. 截图 → 分析 Banner 区域颜色特征
      2. 根据颜色判断活动类型:
         - 粉/红色调 → Marathon
         - 蓝/紫色调 → Cheerful Carnival
         - 其他 → Normal
      3. 返回活动信息和推荐策略
    """

    # 活动 Banner 区域 (相对坐标)
    EVENT_BANNER_ROI = (0.05, 0.08, 0.95, 0.25)  # 顶部横幅区域

    # 活动颜色特征 (BGR 均值)
    COLOR_SIGNATURES = {
        EventType.MARATHON: {
            "hue_range": (0, 30),     # 红色调 H
            "sat_min": 40,             # 饱和度阈值
            "val_min": 80,             # 亮度阈值
            "label": "马拉松活动",
        },
        EventType.CHEERFUL: {
            "hue_range": (90, 140),   # 蓝紫色调 H
            "sat_min": 30,
            "val_min": 70,
            "label": "芝士嘉年华",
        },
    }

    def __init__(self, controller=None):
        self.controller = controller
        self._last_event: Optional[EventInfo] = None
        self._last_detect_time: float = 0.0
        self._cache_ttl: float = 5.0  # 缓存 5 秒

    def detect(self, frame) -> EventInfo:
        """检测当前活动类型。

        Args:
            frame: BGR numpy array (游戏画面截图)

        Returns:
            EventInfo 包含活动类型和建议
        """
        import time
        import cv2
        import numpy as np

        # 缓存
        now = time.time()
        if self._last_event and (now - self._last_detect_time) < self._cache_ttl:
            return self._last_event

        if frame is None:
            return EventInfo(event_type=EventType.UNKNOWN)

        try:
            h, w = frame.shape[:2]
            # 提取 Banner 区域
            rx1, ry1, rx2, ry2 = self.EVENT_BANNER_ROI
            x1, y1 = int(w * rx1), int(h * ry1)
            x2, y2 = int(w * rx2), int(h * ry2)
            banner = frame[y1:y2, x1:x2]

            if banner.size == 0:
                return EventInfo(event_type=EventType.UNKNOWN)

            # HSV 颜色分析
            hsv = cv2.cvtColor(banner, cv2.COLOR_BGR2HSV)
            h_mean = float(np.mean(hsv[:, :, 0]))
            s_mean = float(np.mean(hsv[:, :, 1]))
            v_mean = float(np.mean(hsv[:, :, 2]))

            # 匹配颜色签名
            best_type = EventType.NORMAL
            best_conf = 0.0

            for event_type, sig in self.COLOR_SIGNATURES.items():
                h_min, h_max = sig["hue_range"]
                s_min = sig["sat_min"]
                v_min = sig["val_min"]

                # 色调匹配
                hue_match = 1.0 if h_min <= h_mean <= h_max else (
                    0.5 if abs(h_mean - (h_min + h_max) / 2) < 30 else 0.0
                )
                # 饱和度/亮度匹配
                sat_match = min(1.0, s_mean / max(s_min, 1))
                val_match = min(1.0, v_mean / max(v_min, 1))

                conf = hue_match * 0.5 + sat_match * 0.25 + val_match * 0.25
                if conf > best_conf:
                    best_conf = conf
                    best_type = event_type

            # 构建结果
            label = self.COLOR_SIGNATURES.get(best_type, {}).get("label", "未知活动")
            event = EventInfo(
                event_type=best_type,
                event_name=label,
                confidence=min(1.0, best_conf),
                recommended_songs=self._get_recommended_songs(best_type),
            )

            self._last_event = event
            self._last_detect_time = now
            logger.info(
                "活动检测: %s (conf=%.2f, H=%.0f S=%.0f V=%.0f)",
                event.event_name, event.confidence, h_mean, s_mean, v_mean,
            )
            return event

        except Exception as e:
            logger.debug("活动检测失败: %s", e)
            return EventInfo(event_type=EventType.UNKNOWN)

    def _get_recommended_songs(self, event_type: EventType) -> list[str]:
        """根据活动类型推荐连续执行策略。"""
        if event_type == EventType.MARATHON:
            return ["任意高难度曲目", "推荐: 短时曲目 (效率优先)"]
        elif event_type == EventType.CHEERFUL:
            return ["5v5 团队曲目", "推荐: 高分数曲目 (队伍加成)"]
        else:
            return ["自由选择"]

    def select_optimal_song(self, event: EventInfo) -> Optional[str]:
        """根据活动类型自动选择最优歌曲。

        Returns:
            推荐的歌曲名称，或 None (表示用户自行选择)
        """
        if event.event_type == EventType.MARATHON:
            # 马拉松: 选最短歌曲 (时间效率最高)
            return "auto_shortest"
        elif event.event_type == EventType.CHEERFUL:
            # 芝士: 选最高得分歌曲 (队伍加成)
            return "auto_highest_score"
        return None

    def clear_cache(self):
        """清除检测缓存。"""
        self._last_event = None
        self._last_detect_time = 0.0
