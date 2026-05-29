"""
PJSK Auto Player — ALAS 启发式 Button 声明式 UI 系统

每个 UI 元素 = Button(area, color, button, template)
支持颜色检测、模板匹配、二值化匹配三种方式。

坐标使用相对比例 0~1，运行时自动乘以分辨率。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("pjsk.button")

# ── 工具函数 ──


def crop_relative(image: np.ndarray, area: tuple[float, float, float, float]) -> np.ndarray:
    """按相对比例裁剪图像。"""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = area
    abs_area = (
        int(x1 * w),
        int(y1 * h),
        int(x2 * w),
        int(y2 * h),
    )
    return image[abs_area[1]:abs_area[3], abs_area[0]:abs_area[2]]


def color_distance(c1: tuple, c2: tuple) -> float:
    """计算两个 RGB 颜色的欧氏距离。"""
    return np.sqrt(sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3])))


def get_average_color(image: np.ndarray) -> tuple[int, int, int]:
    """获取图像平均颜色。"""
    return tuple(map(int, cv2.mean(image)[:3]))


def absolute_area(area: tuple, screen_w: int, screen_h: int) -> tuple:
    """相对坐标转绝对像素坐标。"""
    return (
        int(area[0] * screen_w),
        int(area[1] * screen_h),
        int(area[2] * screen_w),
        int(area[3] * screen_h),
    )


def absolute_point(point: tuple[float, float], screen_w: int, screen_h: int) -> tuple[int, int]:
    """相对坐标点转绝对像素点。"""
    return (int(point[0] * screen_w), int(point[1] * screen_h))


# ── Button 类 ──


@dataclass
class PjskButton:
    """声明式 UI 元素定义。
    
    area: 元素出现区域 (x1, y1, x2, y2) 相对比例 0~1
    color: 期望颜色 (r, g, b)
    button: 点击区域，默认同 area
    template: 模板图片路径（可选）
    name: 按钮名称（默认从变量名推断）
    threshold: 颜色检测阈值（默认 30）
    similarity: 模板匹配阈值（默认 0.85）
    """
    area: tuple[float, float, float, float]
    color: tuple[int, int, int]
    button: Optional[tuple] = None
    template: str = ""
    name: str = ""
    threshold: int = 30
    similarity: float = 0.85

    _template_cache: Optional[np.ndarray] = field(default=None, repr=False, compare=False)
    _screen_w: int = field(default=1080, repr=False, compare=False)
    _screen_h: int = field(default=2400, repr=False, compare=False)

    def __post_init__(self):
        if not self.button:
            self.button = self.area
        if not self.name:
            self.name = "Unknown"

    def set_screen_size(self, w: int, h: int):
        """设置屏幕分辨率。"""
        self._screen_w = w
        self._screen_h = h

    # ── 绝对坐标（按当前分辨率计算） ──

    @property
    def abs_area(self) -> tuple[int, int, int, int]:
        return absolute_area(self.area, self._screen_w, self._screen_h)

    @property
    def abs_button(self) -> tuple[int, int, int, int]:
        return absolute_area(self.button, self._screen_w, self._screen_h)

    @property
    def click_point(self) -> tuple[int, int]:
        """点击区域中心点。"""
        x1, y1, x2, y2 = self.abs_button
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    # ── 检测方法 ──

    def appear_on(self, image: np.ndarray) -> bool:
        """颜色检测：检测按钮是否出现（最快的检测方法）。"""
        roi = crop_relative(image, self.area)
        if roi.size == 0:
            return False
        avg = get_average_color(roi)
        dist = color_distance(avg, self.color)
        return dist < self.threshold

    def match_template(self, image: np.ndarray) -> bool:
        """模板匹配检测。"""
        if not self.template or not os.path.exists(self.template):
            logger.debug("Template not found: %s", self.template)
            return False
        self._ensure_template()
        if self._template_cache is None:
            return False
        roi = crop_relative(image, self.area)
        if roi.size == 0:
            return False
        try:
            res = cv2.matchTemplate(
                roi, self._template_cache, cv2.TM_CCOEFF_NORMED
            )
            _, sim, _, point = cv2.minMaxLoc(res)
            # 更新 button 偏移
            ox, oy = absolute_area(self.area, self._screen_w, self._screen_h)[:2]
            abs_button = (
                ox + point[0], oy + point[1],
                ox + point[0] + self._template_cache.shape[1],
                oy + point[1] + self._template_cache.shape[0],
            )
            self.button = (
                abs_button[0] / self._screen_w,
                abs_button[1] / self._screen_h,
                abs_button[2] / self._screen_w,
                abs_button[3] / self._screen_h,
            )
            return sim > self.similarity
        except Exception as e:
            logger.debug("Template match failed: %s", e)
            return False

    def match_binary(self, image: np.ndarray) -> bool:
        """二值化模板匹配（抗光照变化）。"""
        if not self.template or not os.path.exists(self.template):
            return False
        self._ensure_template()
        if self._template_cache is None:
            return False
        roi = crop_relative(image, self.area)
        if roi.size == 0:
            return False
        try:
            # 二值化 ROI
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            # 二值化模板
            tpl = self._template_cache
            tpl_gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
            _, tpl_binary = cv2.threshold(tpl_gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            res = cv2.matchTemplate(binary, tpl_binary, cv2.TM_CCOEFF_NORMED)
            _, sim, _, _ = cv2.minMaxLoc(res)
            return sim > self.similarity
        except Exception as e:
            logger.debug("Binary match failed: %s", e)
            return False

    def detect(self, image: np.ndarray, method: str = "auto") -> bool:
        """自动选择最快的检测方法。
        
        method: auto | color | template | binary
        """
        if method == "color" or (method == "auto" and not self.template):
            return self.appear_on(image)
        elif method == "template":
            return self.match_template(image)
        elif method == "binary":
            return self.match_binary(image)
        else:
            # auto: 先颜色检测（快），不行再模板匹配（准确）
            if self.appear_on(image):
                return True
            if self.template:
                return self.match_template(image)
            return False

    def _ensure_template(self):
        """延迟加载模板缓存。"""
        if self._template_cache is not None:
            return
        if not self.template or not os.path.exists(self.template):
            return
        try:
            img = cv2.imread(self.template, cv2.IMREAD_COLOR)
            if img is not None:
                self._template_cache = img
        except Exception as e:
            logger.error("Failed to load template %s: %s", self.template, e)

    def release(self):
        """释放模板缓存。"""
        self._template_cache = None

    def __str__(self):
        return f"PjskButton({self.name}, area={self.area})"

    __repr__ = __str__


# ── 内置 Project Sekai UI 元素定义 ──

# 这些按钮坐标基于 1080x2400 屏幕
# 实际使用前需 set_screen_size()

PJSK_BUTTONS = {
    # 菜单画面
    "start_live": PjskButton(
        name="start_live",
        area=(0.40, 0.85, 0.60, 0.93),
        color=(255, 184, 66),
        button=(0.40, 0.85, 0.60, 0.93),
    ),
    "multi_live": PjskButton(
        name="multi_live",
        area=(0.05, 0.85, 0.22, 0.93),
        color=(239, 210, 165),
    ),
    
    # 执行画面
    "judgment_line": PjskButton(
        name="judgment_line",
        area=(0.05, 0.76, 0.95, 0.80),
        color=(100, 180, 255),
    ),
    
    # 结算画面
    "result_dismiss": PjskButton(
        name="result_dismiss",
        area=(0.75, 0.03, 0.95, 0.10),
        color=(180, 180, 180),
        button=(0.85, 0.90, 0.95, 0.97),
    ),
    "result_continue": PjskButton(
        name="result_continue",
        area=(0.10, 0.85, 0.30, 0.93),
        color=(239, 210, 165),
    ),
    "result_retry": PjskButton(
        name="result_retry",
        area=(0.35, 0.85, 0.55, 0.93),
        color=(255, 184, 66),
    ),
    
    # 通用
    "loading_indicator": PjskButton(
        name="loading_indicator",
        area=(0.45, 0.48, 0.55, 0.52),
        color=(100, 100, 100),
        threshold=40,
    ),
    "tap_to_start": PjskButton(
        name="tap_to_start",
        area=(0.30, 0.85, 0.70, 0.95),
        color=(255, 255, 255),
    ),
    "close_button": PjskButton(
        name="close_button",
        area=(0.92, 0.02, 0.98, 0.06),
        color=(200, 200, 200),
    ),
    "ok_button": PjskButton(
        name="ok_button",
        area=(0.40, 0.72, 0.60, 0.80),
        color=(100, 200, 255),
    ),
    "cancel_button": PjskButton(
        name="cancel_button",
        area=(0.20, 0.72, 0.38, 0.80),
        color=(200, 200, 200),
    ),
}


def get_button(name: str) -> Optional[PjskButton]:
    """获取预定义的 UI 按钮。"""
    return PJSK_BUTTONS.get(name)


def apply_screen_size(w: int, h: int):
    """为所有预定义按钮设置屏幕分辨率。"""
    for btn in PJSK_BUTTONS.values():
        btn.set_screen_size(w, h)
