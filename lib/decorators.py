"""
PJSK Auto Player — ALAS-style cached_property decorator.

比 functools.cached_property 更强的特性:
  - 支持通过 __dict__.pop() 手动失效缓存
  - 配合 resource_release() 统一释放所有缓存资源
  - 线程安全（加锁保护首次计算）

用法:
    from lib.decorators import cached_property

    class MyTask:
        @cached_property
        def expensive_data(self):
            return load_large_file()

        def release(self):
            # 手动失效缓存
            self.__dict__.pop('expensive_data', None)
"""

from __future__ import annotations

import functools
import threading
from typing import Any, Callable


class cached_property:
    """缓存属性的描述器（非数据描述器）。

    首次访问时计算值，存入实例 __dict__ 中；
    后续访问直接返回 __dict__ 中的缓存值。

    支持:
        obj.__dict__.pop('attr_name')      # 手动失效
        del obj.attr_name                   # 删除属性触发重新计算
    """

    def __init__(self, func: Callable) -> None:
        self.func = func
        self.attrname: str | None = None
        self.__doc__ = func.__doc__
        self._lock = threading.Lock()

    def __set_name__(self, owner: type, name: str) -> None:
        if self.attrname is None:
            self.attrname = name

    def __get__(self, instance, owner=None) -> Any:
        if instance is None:
            return self
        if self.attrname is None:
            raise TypeError(
                "Cannot use cached_property without calling __set_name__."
            )
        # Fast path: already cached
        try:
            return instance.__dict__[self.attrname]
        except KeyError:
            pass
        # Slow path: compute with lock
        with self._lock:
            # Double-check after acquiring lock
            try:
                return instance.__dict__[self.attrname]
            except KeyError:
                value = self.func(instance)
                instance.__dict__[self.attrname] = value
                return value

    def __delete__(self, instance) -> None:
        if self.attrname:
            instance.__dict__.pop(self.attrname, None)

    def __repr__(self) -> str:
        return f"<cached_property {self.func.__qualname__}>"


# ── 简易变体 ──


class classproperty:
    """类级别的只读属性（非数据描述器）。

    用法:
        class Config:
            @classproperty
            def version(cls):
                return read_version_file()
    """

    def __init__(self, func: Callable) -> None:
        self.func = func
        self.__doc__ = func.__doc__

    def __get__(self, instance, owner=None) -> Any:
        return self.func(owner)


def once_per_frame(method: Callable) -> Callable:
    """装饰器：每帧只执行一次（相同参数在单帧内缓存）。

    帧由调用上下文中的 frame_hash 或 timestamp 确定。
    需要被装饰的实例有 _last_call_frame 和 _last_call_result 属性。

    用法:
        class Detector:
            _last_call_frame = 0
            _last_call_result = None

            @once_per_frame
            def detect(self, frame):
                ...
    """
    @functools.wraps(method)
    def wrapper(self, frame, *args, **kwargs):
        import time
        frame_id = id(frame) if hasattr(frame, '__array_interface__') else time.perf_counter()
        if getattr(self, '_last_call_frame', 0) == frame_id:
            return self._last_call_result
        result = method(self, frame, *args, **kwargs)
        self._last_call_frame = frame_id
        self._last_call_result = result
        return result
    return wrapper
