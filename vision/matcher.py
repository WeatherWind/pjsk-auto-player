"""OpenCV 模板匹配模块 —— 支持多模板、多 ROI。

提供:
  - 单模板全图搜索
  - 多模板并行匹配 (选择最佳)
  - ROI (感兴趣区域) 限定搜索
  - 多种匹配方法
  - 尺度不变的模板匹配 (多尺度)
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("pjsk_vision.matcher")


@dataclass
class MatchResult:
    """模板匹配结果。"""
    name: str                          # 模板名称
    x: int                             # 匹配位置左上角 X
    y: int                             # 匹配位置左上角 Y
    w: int                             # 模板宽度
    h: int                             # 模板高度
    confidence: float                  # 匹配置信度 (0~1)
    method: str = "TM_CCOEFF_NORMED"   # 使用的匹配方法
    scale: float = 1.0                 # 匹配时的缩放比例

    @property
    def center(self) -> tuple[int, int]:
        """匹配区域的中心坐标。"""
        return (self.x + self.w // 2, self.y + self.h // 2)

    @property
    def rect(self) -> tuple[int, int, int, int]:
        """匹配区域的矩形 (x, y, w, h)。"""
        return (self.x, self.y, self.w, self.h)


class TemplateMatcher:
    """OpenCV 模板匹配器。

    支持:
      - 多模板注册 (通过名称关联)
      - 多 ROI 限定搜索区域
      - 多尺度搜索 (scale-invariant)
      - 多种匹配方法选择

    用法:
        matcher = TemplateMatcher()
        matcher.register("btn_start", template_img)
        results = matcher.match(frame, roi=(0, 0, 200, 100))
        if results:
            print(results[0].confidence, results[0].center)
    """

    # 匹配方法映射
    METHODS: dict[str, int] = {
        "TM_CCOEFF": cv2.TM_CCOEFF,
        "TM_CCOEFF_NORMED": cv2.TM_CCOEFF_NORMED,
        "TM_CCORR": cv2.TM_CCORR,
        "TM_CCORR_NORMED": cv2.TM_CCORR_NORMED,
        "TM_SQDIFF": cv2.TM_SQDIFF,
        "TM_SQDIFF_NORMED": cv2.TM_SQDIFF_NORMED,
    }

    def __init__(self, method: str = "TM_CCOEFF_NORMED") -> None:
        """
        Args:
            method: 匹配方法, 见 METHODS
        """
        if method not in self.METHODS:
            raise ValueError(f"不支持的匹配方法: {method}. 可选: {list(self.METHODS.keys())}")
        self._method = method
        self._method_flag = self.METHODS[method]

        # templates: name -> [(template_gray, threshold, scales, ...)]
        self._templates: dict[str, list[tuple[np.ndarray, float, list[float]]]] = {}

        # ROI 预设: name -> (x, y, w, h) or None
        self._rois: dict[str, Optional[tuple[int, int, int, int]]] = {}

        # 是否自动选择最佳匹配 (多个模板匹配时)
        self.best_only: bool = True

        # 最小置信度
        self.min_confidence: float = 0.5

        logger.info(f"TemplateMatcher 已初始化, method={method}")

    # ── 注册 ──────────────────────────────────────────────

    def register(
        self, name: str, template: np.ndarray,
        threshold: float = 0.8, scales: Optional[list[float]] = None,
        roi: Optional[tuple[int, int, int, int]] = None,
    ) -> None:
        """注册一个模板。

        Args:
            name: 模板名称 (用于标识)
            template: 模板图像 (BGR 或灰度)
            threshold: 匹配阈值, 低于此值的结果被忽略
            scales: 多尺度搜索的缩放比例列表, 如 [0.8, 0.9, 1.0, 1.1, 1.2]
            roi: 搜索区域的 ROI (x, y, w, h), None=全图
        """
        if len(template.shape) == 3:
            template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        scales = scales or [1.0]
        self._templates.setdefault(name, []).append(
            (template, threshold, scales)
        )
        self._rois[name] = roi

        logger.debug(
            f"注册模板: {name} "
            f"(size={template.shape}, threshold={threshold}, "
            f"scales={scales}, roi={roi})"
        )

    def register_from_file(
        self, name: str, filepath: str,
        threshold: float = 0.8, scales: Optional[list[float]] = None,
        roi: Optional[tuple[int, int, int, int]] = None,
    ) -> bool:
        """从文件加载并注册模板。

        Args:
            name: 模板名称
            filepath: 模板图像路径
            threshold: 匹配阈值
            scales: 多尺度缩放列表
            roi: 搜索 ROI

        Returns:
            是否成功加载
        """
        try:
            template = cv2.imread(filepath, cv2.IMREAD_GRAYSCALE)
            if template is None:
                logger.error(f"无法加载模板图像: {filepath}")
                return False
            self.register(name, template, threshold, scales, roi)
            return True
        except Exception as e:
            logger.error(f"加载模板失败 {filepath}: {e}")
            return False

    # ── 匹配 ──────────────────────────────────────────────

    def match(
        self, frame: np.ndarray,
        roi: Optional[tuple[int, int, int, int]] = None,
        template_name: Optional[str] = None,
    ) -> list[MatchResult]:
        """执行模板匹配。

        Args:
            frame: 搜索帧 (BGR 或灰度)
            roi: 搜索区域 (x, y, w, h), None=全图
            template_name: 可选, 只匹配指定名称的模板

        Returns:
            按置信度降序排列的匹配结果列表
        """
        if frame is None or frame.size == 0:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame
        h, w = gray.shape[:2]

        # 处理 ROI
        if roi is not None:
            rx, ry, rw, rh = roi
            rx = max(0, rx)
            ry = max(0, ry)
            rw = min(rw, w - rx)
            rh = min(rh, h - ry)
            if rw <= 0 or rh <= 0:
                return []
            search_roi = gray[ry:ry + rh, rx:rx + rw]
        else:
            search_roi = gray
            rx, ry = 0, 0

        results: list[MatchResult] = []
        templates_to_match = (
            {template_name: self._templates[template_name]}
            if template_name and template_name in self._templates
            else self._templates
        )

        for name, template_list in templates_to_match.items():
            for tmpl, threshold, scales in template_list:
                for scale in scales:
                    try:
                        res = self._match_single(
                            search_roi, tmpl, threshold, scale,
                            name, rx, ry,
                        )
                        if res is not None:
                            results.append(res)
                    except Exception as e:
                        logger.debug(
                            f"匹配异常 (name={name}, scale={scale}): {e}"
                        )

        # 按置信度降序
        results.sort(key=lambda r: r.confidence, reverse=True)

        if self.best_only and results:
            results = [results[0]]

        return results

    def _match_single(
        self, search_roi: np.ndarray, template: np.ndarray,
        threshold: float, scale: float,
        name: str, offset_x: int, offset_y: int,
    ) -> Optional[MatchResult]:
        """单尺度模板匹配。"""
        if scale != 1.0:
            new_w = int(template.shape[1] * scale)
            new_h = int(template.shape[0] * scale)
            if new_w < 4 or new_h < 4:
                return None
            scaled_tmpl = cv2.resize(template, (new_w, new_h),
                                     interpolation=cv2.INTER_AREA)
        else:
            scaled_tmpl = template

        th, tw = scaled_tmpl.shape[:2]
        if th > search_roi.shape[0] or tw > search_roi.shape[1]:
            return None

        try:
            result_map = cv2.matchTemplate(
                search_roi, scaled_tmpl, self._method_flag
            )
        except cv2.error as e:
            logger.debug(f"cv2.matchTemplate 失败: {e}")
            return None

        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result_map)

        # TM_SQDIFF/TM_SQDIFF_NORMED: 越小越好
        if self._method_flag in (cv2.TM_SQDIFF, cv2.TM_SQDIFF_NORMED):
            confidence = 1.0 - min_val
            loc = min_loc
        else:
            confidence = max_val
            loc = max_loc

        if confidence < max(threshold, self.min_confidence):
            return None

        return MatchResult(
            name=name,
            x=loc[0] + offset_x,
            y=loc[1] + offset_y,
            w=tw,
            h=th,
            confidence=float(confidence),
            method=self._method,
            scale=scale,
        )

    def match_first(
        self, frame: np.ndarray,
        roi: Optional[tuple[int, int, int, int]] = None,
        template_name: Optional[str] = None,
    ) -> Optional[MatchResult]:
        """便捷方法: 返回第一个 (置信度最高的) 匹配结果。"""
        results = self.match(frame, roi, template_name)
        return results[0] if results else None

    def match_at_roi(
        self, frame: np.ndarray, name: str,
    ) -> Optional[MatchResult]:
        """使用注册时指定的 ROI 进行匹配。"""
        if name not in self._rois:
            return self.match_first(frame, template_name=name)
        return self.match_first(frame, roi=self._rois[name], template_name=name)

    # ── 工具 ──────────────────────────────────────────────

    def draw_matches(
        self, frame: np.ndarray, matches: list[MatchResult],
        color: tuple[int, int, int] = (0, 255, 0),
        thickness: int = 2,
    ) -> np.ndarray:
        """在帧上绘制匹配结果。"""
        out = frame.copy()
        for m in matches:
            cv2.rectangle(
                out, (m.x, m.y), (m.x + m.w, m.y + m.h),
                color, thickness,
            )
            label = f"{m.name}: {m.confidence:.2f}"
            cv2.putText(
                out, label, (m.x, max(0, m.y - 5)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
            )
        return out

    def count(self) -> int:
        """已注册的模板数量。"""
        return sum(len(v) for v in self._templates.values())

    def clear(self) -> None:
        """清除所有注册的模板。"""
        self._templates.clear()
        self._rois.clear()
