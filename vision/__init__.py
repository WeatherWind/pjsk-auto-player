"""Vision 模块 —— 图像识别引擎。

提供模板匹配、OCR 识别、颜色检测、场景检测等视觉功能。
"""

from .matcher import TemplateMatcher, MatchResult
from .ocr import OcrReader
from .color import ColorDetector, ColorRange
from .scene import SceneDetector, DetectionResult

__all__ = [
    "TemplateMatcher",
    "MatchResult",
    "OcrReader",
    "ColorDetector",
    "ColorRange",
    "SceneDetector",
    "DetectionResult",
]
