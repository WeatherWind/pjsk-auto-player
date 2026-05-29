"""
PJSK Auto Player — 工具库 (v4.10.0+)

提供通用工具:
  - lib.decorators: cached_property, classproperty, once_per_frame
  - lib.resource: Resource 资源管理器, LazyResource 延迟加载
"""

from lib.decorators import cached_property, classproperty, once_per_frame
from lib.resource import Resource, LazyResource

__all__ = [
    "cached_property",
    "classproperty",
    "once_per_frame",
    "Resource",
    "LazyResource",
]
