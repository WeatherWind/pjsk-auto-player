"""
PJSK Auto Player — 工具库 (v5.0.0+)

提供通用工具:
  - lib.decorators: cached_property, classproperty, once_per_frame
  - lib.resource: Resource 资源管理器, LazyResource 延迟加载
  - lib.anti_detection: HumanTouch 触摸模拟, 贝塞尔曲线, 反检测
"""

from lib.decorators import cached_property, classproperty, once_per_frame
from lib.resource import Resource, LazyResource
from lib.anti_detection import HumanTouch, HumanTouchConfig, bezier_curve, get_human_touch

__all__ = [
    "cached_property",
    "classproperty",
    "once_per_frame",
    "Resource",
    "LazyResource",
    "HumanTouch",
    "HumanTouchConfig",
    "bezier_curve",
    "get_human_touch",
]
