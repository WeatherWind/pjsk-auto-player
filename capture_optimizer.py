"""
画面捕获优化 —— 受 ALAS (Azur Lane Auto Sweep) 启发。

核心优化:
  1. 区域截取 (Region Capture) — 只截画面的一部分, 而非全屏
  2. 帧差检测 (Frame Diff) — 画面无变化时跳过分析
  3. 自适应帧率 — 根据画面内容动态调整截图频率

应用场景:
  - 执行中: 只需截取判定线附近区域 (~15% 画面)
  - 结算画面: 只需截取分数区域 (~20% 画面)
  - 加载/菜单: 慢速轮询 (2-5 FPS 即可)
"""

import hashlib
import logging
import time
from typing import Optional

import cv2
import numpy as np

from scene_classifier import SceneType

logger = logging.getLogger("pjsk_capture")


class CaptureOptimizer:
    """
    画面捕获优化器。

    根据场景类型动态调整捕获策略:
      - GAME:      高分帧率 + 区域截取
      - RESULT:    中等帧率 + 分数区域
      - MENU:      低帧率 + 全屏 (检测变化)
      - LOADING:   最低帧率
    """

    def __init__(self, config: dict):
        self.cfg = config
        s = config["screen"]
        self.screen_w = s["width"]
        self.screen_h = s["height"]
        self.judgment_y = int(s["judgment_line_y"] * self.screen_h)

        # 帧差检测
        self._prev_gray: Optional[np.ndarray] = None
        self._prev_scene = SceneType.UNKNOWN
        self._frame_count = 0

        # 各场景的推荐帧率
        self._scene_fps = {
            SceneType.GAME: 30,          # 执行: 30 FPS
            SceneType.RESULT: 5,         # 结算: 5 FPS
            SceneType.MENU: 3,           # 菜单: 3 FPS
            SceneType.LOADING: 1,        # 加载: 1 FPS
            SceneType.TRANSITION: 2,     # 过渡: 2 FPS
            SceneType.UNKNOWN: 5,        # 未知: 5 FPS
        }

        # 各场景的最小像素变化率 (低于此值跳过分析)
        self._scene_diff_threshold = {
            SceneType.GAME: 0.005,      # 0.5% — 执行时每帧都有 note 移动
            SceneType.RESULT: 0.02,     # 2% — 结算动画变化较快
            SceneType.MENU: 0.01,       # 1% — 菜单变化幅度中等
            SceneType.LOADING: 0.05,    # 5% — 加载时大幅变化才触发
            SceneType.TRANSITION: 0.03, # 3%
            SceneType.UNKNOWN: 0.01,
        }

    def get_roi_for_scene(self, scene: SceneType) -> tuple:
        """
        根据场景返回 ROI (x, y, w, h)。
        返回全屏时 = (0, 0, screen_w, screen_h)
        """
        if scene == SceneType.GAME:
            # 执行: 判定线附近 + 预测区域
            top = max(0, self.judgment_y - int(self.screen_h * 0.4))
            bottom = min(self.screen_h, self.judgment_y + 40)
            return (0, top, self.screen_w, bottom - top)

        elif scene == SceneType.RESULT:
            # 结算: 分数区域 (中央偏上)
            y1 = int(self.screen_h * 0.2)
            y2 = int(self.screen_h * 0.6)
            x1 = int(self.screen_w * 0.1)
            x2 = int(self.screen_w * 0.9)
            return (x1, y1, x2 - x1, y2 - y1)

        # 其他场景: 全屏
        return (0, 0, self.screen_w, self.screen_h)

    def get_target_fps(self, scene: SceneType) -> int:
        """根据场景类型获取目标帧率。"""
        return self._scene_fps.get(scene, 10)

    def has_changed(self, frame: np.ndarray, scene: SceneType) -> bool:
        """
        帧差检测: 画面是否有显著变化。

        Returns:
            True = 需要分析, False = 可跳过 (画面无变化)
        """
        if frame is None:
            return False

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # 缩放以加速
        small = cv2.resize(gray, (w // 8, h // 8))

        if self._prev_gray is None:
            self._prev_gray = small
            self._prev_scene = scene
            return True

        # 计算像素变化率
        diff = cv2.absdiff(small, self._prev_gray)
        change_ratio = np.mean(diff > 15)

        self._prev_gray = small
        self._prev_scene = scene

        threshold = self._scene_diff_threshold.get(scene, 0.01)
        changed = change_ratio > threshold

        if not changed:
            self._frame_count += 1

        self._frame_count = 0 if changed else self._frame_count

        return changed

    def get_skip_count(self) -> int:
        """获取连续跳过的帧数。"""
        return self._frame_count

    def reset(self):
        """重置帧差状态 (场景切换时调用)。"""
        self._prev_gray = None
        self._frame_count = 0
