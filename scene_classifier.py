"""
场景分类器 —— 受 ALAS (Azur Lane Auto Sweep) 启发。

核心思想:
  1. 用极轻量的像素检测来快速分类画面 (比完整分析快 10-100x)
  2. 决策树: 从最"便宜"的检测开始, 逐层排除
  3. 缓存上一次分类结果, 画面不变时直接复用

检测策略 (按成本从低到高):
  a. 整体平均亮度 (1 次 mean)        → 结算/菜单/加载
  b. 区域颜色直方图 (3 次 mean)      → 执行/选歌
  c. 局部模板匹配 (30ms)             → 确认具体按钮
  d. OCR 阅读 (100ms+)               → 读取分数(reference only)
"""

import logging
import time
from enum import Enum
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("pjsk_scene")


class SceneType(str, Enum):
    """PJSK 游戏画面类型 (按响应速度排序)。"""
    UNKNOWN = "unknown"          # 无法识别
    LOADING = "loading"          # 加载中 (全黑/渐变)
    MENU = "menu"                # 主菜单/选歌
    RESULT = "result"            # 结算画面 (高亮)
    GAME = "game"               # 执行中
    TRANSITION = "transition"    # 过渡动画


class SceneClassifier:
    """
    快速场景分类器。

    用 O(1) 像素检测快速判断当前画面类型,
    只在需要时降级到模板匹配或 OCR。

    用法:
        classifier = SceneClassifier(config)
        scene = classifier.classify(frame)  # ~1ms
    """

    def __init__(self, config: dict):
        self.cfg = config
        s = config["screen"]
        self.screen_w = s["width"]
        self.screen_h = s["height"]
        self.judgment_y = int(s["judgment_line_y"] * self.screen_h)

        # 缓存上次结果
        self._last_scene = SceneType.UNKNOWN
        self._last_frame_hash = 0
        self._last_classify_time = 0
        self._cache_ttl = 0.05  # 50ms 内复用结果

    def classify(self, frame: np.ndarray) -> SceneType:
        """
        快速分类画面 (平均 <1ms)。

        决策树:
          1. 空帧/全黑 → LOADING
          2. 整体 >160 → RESULT
          3. 判定线活跃 → GAME
          4. 检测到 UI → MENU
          5. → UNKNOWN
        """
        if frame is None:
            return SceneType.UNKNOWN

        # ── 帧哈希缓存: 相同画面直接复用上次结果 ──
        now = time.time()
        if now - self._last_classify_time < self._cache_ttl:
            return self._last_scene

        # 快速帧哈希 (取 8x8 缩小图的均值哈希)
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (8, 8))
        frame_hash = hash(small.tobytes())
        if frame_hash == self._last_frame_hash:
            return self._last_scene
        self._last_frame_hash = frame_hash

        # 更新缓存时间戳 (写在最开始以便后续返回时缓存)
        self._last_classify_time = now

        # ── 步骤 1: 检测加载/黑屏 (最便宜) ──
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        overall_mean = np.mean(gray)

        if overall_mean < 10:
            return SceneType.LOADING

        # ── 步骤 2: 检测结算画面 (整体高亮) ──
        if overall_mean > 140:
            # 结算画面: 整体亮 + 判定线无活动
            j_roi = gray[
                max(0, self.judgment_y - 30):min(h, self.judgment_y + 30),
                max(0, w // 4):min(w, w * 3 // 4)
            ]
            if j_roi.size > 0:
                j_mean = np.mean(j_roi)
                # 结算画面: 整体亮但判定线区域相对不那么亮 (因为有特效)
                # 这里用判定线区域亮度的标准差来判断是否有 note 活动
                j_std = np.std(j_roi)
                if j_std < 20:  # 判定线区域平滑 → 没有 note 活动
                    result = SceneType.RESULT
                    self._last_scene = result
                    return result

        # ── 步骤 3: 检测执行画面 ──
        # 判定线区域有亮色 note 活动
        j_roi = gray[
            max(0, self.judgment_y - 20):min(h, self.judgment_y + 20),
            max(0, w // 4):min(w, w * 3 // 4)
        ]
        if j_roi.size > 0:
            bright_ratio = np.mean(j_roi > 150)
            if bright_ratio > 0.03:
                result = SceneType.GAME
                self._last_scene = result
                return result

        # ── 步骤 4: 检测菜单/UI ──
        # 检查屏幕顶部是否有 UI 元素
        top_roi = gray[0:int(h * 0.1), int(w * 0.1):int(w * 0.9)]
        if top_roi.size > 0:
            top_std = np.std(top_roi)
            if top_std > 30:  # 有 UI 文字/元素
                result = SceneType.MENU
                self._last_scene = result
                return result

        # ── 步骤 5: 过渡动画 ──
        if overall_mean < 60:
            result = SceneType.TRANSITION
            self._last_scene = result
            return result

        result = SceneType.UNKNOWN
        self._last_scene = result
        return result

    def is_game(self, frame: np.ndarray) -> bool:
        """快速判断是否在执行中。"""
        return self.classify(frame) == SceneType.GAME

    def is_result(self, frame: np.ndarray) -> bool:
        """快速判断是否是结算画面。"""
        return self.classify(frame) == SceneType.RESULT

    def wait_for(
        self, adb, target: SceneType, timeout: float = 10.0,
        interval: float = 0.1
    ) -> Optional[np.ndarray]:
        """
        等待指定场景出现 (阻塞)。

        Args:
            adb: ADBController 实例
            target: 目标场景
            timeout: 超时秒数
            interval: 轮询间隔

        Returns:
            场景出现时的帧, 超时返回 None
        """
        start = time.time()
        while time.time() - start < timeout:
            frame = adb.screencap()
            if frame is not None and self.classify(frame) == target:
                return frame
            time.sleep(interval)
        return None
