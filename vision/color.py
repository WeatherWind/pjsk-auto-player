"""颜色检测模块 —— RGB/HSV 范围检测。

提供:
  - ColorRange 定义 (RGB/HSV 上下限)
  - ColorDetector 检测像素是否在指定范围内
  - 颜色区域分析 (占比、连通域)
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("pjsk_vision.color")


@dataclass
class ColorRange:
    """颜色范围定义。

    支持 RGB 和 HSV 两种色彩空间。
    用法:
        # RGB 白色范围
        white_rgb = ColorRange(
            lower=(200, 200, 200), upper=(255, 255, 255),
            space="rgb"
        )
        # HSV 蓝色范围
        blue_hsv = ColorRange(
            lower=(90, 50, 50), upper=(130, 255, 255),
            space="hsv"
        )
    """
    lower: tuple[int, int, int]   # 下界 (B,G,R) 或 (H,S,V)
    upper: tuple[int, int, int]   # 上界 (B,G,R) 或 (H,S,V)
    space: str = "rgb"            # "rgb" 或 "hsv"
    name: str = ""                # 颜色名称 (可选)

    def __post_init__(self) -> None:
        self.space = self.space.lower()
        if self.space not in ("rgb", "hsv", "bgr"):
            raise ValueError(f"不支持的色彩空间: {self.space}。可选: rgb, hsv, bgr")

    def to_hsv(self) -> "ColorRange":
        """将 RGB 范围转为 HSV 范围 (近似)。

        注意: 精确转换需要在像素级别进行。
        这里给出近似值, HSV 检测建议直接使用 HSV 定义。
        """
        if self.space == "hsv":
            return self
        # OpenCV 使用 BGR, 需要反转
        lower_bgr = (self.lower[2], self.lower[1], self.lower[0])
        upper_bgr = (self.upper[2], self.upper[1], self.upper[0])
        return ColorRange(lower=lower_bgr, upper=upper_bgr, space="hsv", name=self.name)

    def to_bgr(self) -> tuple[np.ndarray, np.ndarray]:
        """返回适合 cv2.inRange 的 BGR numpy 数组对。"""
        if self.space == "hsv":
            return np.array(self.lower, dtype=np.uint8), np.array(self.upper, dtype=np.uint8)
        # RGB -> BGR 反转
        lower_bgr = (self.lower[2], self.lower[1], self.lower[0])
        upper_bgr = (self.upper[2], self.upper[1], self.upper[0])
        return np.array(lower_bgr, dtype=np.uint8), np.array(upper_bgr, dtype=np.uint8)

    # 预定义常用颜色
    @classmethod
    def white(cls) -> "ColorRange":
        return cls(lower=(200, 200, 200), upper=(255, 255, 255), space="rgb", name="white")

    @classmethod
    def black(cls) -> "ColorRange":
        return cls(lower=(0, 0, 0), upper=(50, 50, 50), space="rgb", name="black")

    @classmethod
    def red(cls) -> "ColorRange":
        return cls(lower=(0, 0, 150), upper=(80, 80, 255), space="rgb", name="red")

    @classmethod
    def green(cls) -> "ColorRange":
        return cls(lower=(0, 150, 0), upper=(80, 255, 80), space="rgb", name="green")

    @classmethod
    def blue(cls) -> "ColorRange":
        return cls(lower=(150, 0, 0), upper=(255, 80, 80), space="rgb", name="blue")

    @classmethod
    def hsv_white(cls) -> "ColorRange":
        """HSV 白色: V>200, S<30"""
        return cls(lower=(0, 0, 200), upper=(180, 30, 255), space="hsv", name="hsv_white")

    @classmethod
    def hsv_blue(cls) -> "ColorRange":
        """HSV 蓝色: H 90~130"""
        return cls(lower=(90, 50, 50), upper=(130, 255, 255), space="hsv", name="hsv_blue")

    @classmethod
    def hsv_yellow(cls) -> "ColorRange":
        """HSV 黄色: H 20~40"""
        return cls(lower=(20, 100, 100), upper=(40, 255, 255), space="hsv", name="hsv_yellow")


@dataclass
class ColorDetectionResult:
    """颜色检测结果。"""
    present: bool                     # 是否存在目标颜色
    ratio: float                      # 目标颜色像素占比 (0~1)
    count: int                        # 目标颜色像素数
    centers: list[tuple[int, int]] = field(default_factory=list)  # 连通区域中心
    contours: list = field(default_factory=list)                  # 轮廓列表
    mask: Optional[np.ndarray] = None                             # 二值掩码


class ColorDetector:
    """颜色检测器。

    在帧中检测指定颜色范围, 支持:
      - RGB / HSV 色彩空间
      - 连通域分析 (找色块区域)
      - 面积/比例过滤
      - 多颜色范围并行检测

    用法:
        detector = ColorDetector()
        # 单次检测
        result = detector.detect(frame, ColorRange.white())
        if result.present:
            print(f"白色占比: {result.ratio:.2%}")

        # 多颜色检测
        results = detector.detect_all(frame, [
            ColorRange.hsv_blue(),
            ColorRange.hsv_yellow(),
        ])
    """

    def __init__(self) -> None:
        # 形态学核
        self._kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        # 最小/最大色块面积
        self.min_area: int = 10
        self.max_area: int = 100000
        # 是否执行形态学清理
        self.use_morphology: bool = True

    def detect(
        self, frame: np.ndarray, color_range: ColorRange,
    ) -> ColorDetectionResult:
        """检测帧中指定颜色范围。

        Args:
            frame: BGR numpy array
            color_range: 颜色范围定义

        Returns:
            ColorDetectionResult
        """
        if frame is None or frame.size == 0:
            return ColorDetectionResult(present=False, ratio=0.0, count=0)

        # 获取掩码
        mask = self._create_mask(frame, color_range)
        if mask is None:
            return ColorDetectionResult(present=False, ratio=0.0, count=0)

        total_pixels = frame.shape[0] * frame.shape[1]
        color_count = int(np.sum(mask > 0))
        ratio = color_count / total_pixels if total_pixels > 0 else 0.0

        # 连通域分析
        contours, centers = self._analyze_contours(mask)

        return ColorDetectionResult(
            present=color_count > 0,
            ratio=float(ratio),
            count=color_count,
            centers=centers,
            contours=contours,
            mask=mask,
        )

    def detect_all(
        self, frame: np.ndarray,
        color_ranges: list[ColorRange],
    ) -> dict[str, ColorDetectionResult]:
        """并行检测多个颜色范围。

        Args:
            frame: BGR numpy array
            color_ranges: 颜色范围列表

        Returns:
            {颜色名称: ColorDetectionResult}
        """
        results: dict[str, ColorDetectionResult] = {}
        for cr in color_ranges:
            name = cr.name or str(cr)
            results[name] = self.detect(frame, cr)
        return results

    def detect_area_ratio(
        self, frame: np.ndarray, color_range: ColorRange,
        roi: Optional[tuple[int, int, int, int]] = None,
    ) -> float:
        """检测指定区域内目标颜色的占比。

        Args:
            frame: BGR numpy array
            color_range: 颜色范围
            roi: (x, y, w, h) 或 None=全图

        Returns:
            占比 (0~1)
        """
        if roi is not None and frame is not None:
            x, y, w, h = roi
            frame = frame[y:y + h, x:x + w]

        result = self.detect(frame, color_range)
        return result.ratio

    def detect_at_point(
        self, frame: np.ndarray, point: tuple[int, int],
        color_range: ColorRange,
    ) -> bool:
        """检测指定像素点的颜色是否在范围内。

        Args:
            frame: BGR numpy array
            point: (x, y)
            color_range: 颜色范围

        Returns:
            是否匹配
        """
        if frame is None or frame.size == 0:
            return False

        x, y = point
        if y >= frame.shape[0] or x >= frame.shape[1] or y < 0 or x < 0:
            return False

        pixel = frame[y, x, :3]  # BGR

        lower, upper = color_range.to_bgr()

        if color_range.space == "hsv":
            pixel_hsv = cv2.cvtColor(pixel.reshape(1, 1, 3), cv2.COLOR_BGR2HSV)[0, 0]
            return bool(np.all(lower <= pixel_hsv) and np.all(pixel_hsv <= upper))
        else:
            return bool(np.all(lower <= pixel) and np.all(pixel <= upper))

    # ── 内部方法 ──────────────────────────────────────

    def _create_mask(self, frame: np.ndarray, color_range: ColorRange) -> Optional[np.ndarray]:
        """创建颜色掩码。"""
        lower, upper = color_range.to_bgr()

        if color_range.space == "hsv":
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, lower, upper)
        else:
            mask = cv2.inRange(frame, lower, upper)

        if self.use_morphology:
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self._kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self._kernel)

        return mask

    def _analyze_contours(
        self, mask: np.ndarray,
    ) -> tuple[list, list[tuple[int, int]]]:
        """分析连通域, 返回 (contours, centers)。"""
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        centers: list[tuple[int, int]] = []
        filtered: list = []

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if self.min_area <= area <= self.max_area:
                filtered.append(cnt)
                M = cv2.moments(cnt)
                if M["m00"] > 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    centers.append((cx, cy))

        return filtered, centers
