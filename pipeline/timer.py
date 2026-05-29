"""
PJSK Auto Player — ALAS 启发式 Timer 双定时器

支持时间和访问次数双重条件。
任一个达到即触发，提供慢速设备上的鲁棒性。
"""

from __future__ import annotations

import logging
import time
from functools import wraps

logger = logging.getLogger("pjsk.timer")


def timer_decorator(function):
    """装饰器：计时函数执行时间（调试用）。"""
    @wraps(function)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = function(*args, **kwargs)
        cost = time.perf_counter() - start
        logger.debug("%s: %.4f s", function.__name__, cost)
        return result
    return wrapper


class Timer:
    """双定时器：time 和 access count 双重条件。
    
    Args:
        limit: 时间限制（秒）
        count: 访问次数限制（默认 0 = 仅时间限制）
    
    用法:
        interval = Timer(limit=2, count=3)
        while running:
            if interval.reached_and_reset():
                # 每 2 秒或每 3 次调用执行一次
                do_something()
    """

    def __init__(self, limit: float, count: int = 0):
        self.limit = limit
        self.count = count
        self._start: float = 0.0
        self._access: int = 0

    @classmethod
    def from_seconds(cls, limit: float, speed: float = 0.5) -> Timer:
        """根据截图速度估算访问次数。
        
        Args:
            limit: 时间限制（秒）
            speed: 单次截图预计耗时。如果 >0.5s 说明设备慢
        
        Returns:
            Timer: 自动计算 count 的定时器
        """
        count = int(limit / speed) if speed > 0 else 0
        return cls(limit=limit, count=count)

    def start(self) -> Timer:
        """启动定时器。
        
        如果从未启动，reached() 总是返回 True（第一次快速执行）。
        """
        if self._start <= 0:
            self._start = time.perf_counter()
            self._access = 0
        return self

    def started(self) -> bool:
        """是否已启动。"""
        return self._start > 0

    def current_time(self) -> float:
        """当前已过时间。"""
        if self._start > 0:
            return max(0.0, time.perf_counter() - self._start)
        return 0.0

    def current_count(self) -> int:
        """当前访问次数。"""
        return self._access

    def reached(self) -> bool:
        """是否到达限制（时间或次数任一满足）。"""
        self._access += 1  # 每次调用计数 +1
        if self._start > 0:
            time_ok = time.perf_counter() - self._start > self.limit
            count_ok = self._access > self.count
            return time_ok or count_ok
        else:
            # 未启动：第一次总是 True（快速首次执行）
            return True

    def reached_and_reset(self) -> bool:
        """到达限制后自动重置。"""
        if self.reached():
            self.reset()
            return True
        return False

    def reset(self) -> Timer:
        """重置定时器（保持启动状态）。"""
        self._start = time.perf_counter()
        self._access = 0
        return self

    def clear(self) -> Timer:
        """清除定时器（回到未启动状态）。"""
        self._start = 0.0
        self._access = self.count
        return self

    def wait(self):
        """阻塞直到时间到达。"""
        elapsed = time.perf_counter() - self._start
        remaining = self.limit - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def add_count(self, n: int = 1) -> Timer:
        self._access += n
        return self

    def __str__(self):
        return (f"Timer(limit={self.current_time():.3f}/{self.limit}, "
                f"count={self._access}/{self.count})")

    __repr__ = __str__


class FrameTimer:
    """帧率定时器 — 用于计算和控制 FPS。"""
    
    def __init__(self, target_fps: float = 60.0):
        self.target_fps = target_fps
        self._frame_count = 0
        self._last_time = time.perf_counter()
        self._current_fps = 0.0

    def tick(self) -> float:
        """记录一帧，返回当前 FPS。"""
        self._frame_count += 1
        now = time.perf_counter()
        elapsed = now - self._last_time
        if elapsed >= 1.0:
            self._current_fps = self._frame_count / elapsed
            self._frame_count = 0
            self._last_time = now
        return self._current_fps

    @property
    def fps(self) -> float:
        return self._current_fps

    def wait_if_needed(self):
        """如果帧率超标，等待到下一帧时间。"""
        if self.target_fps <= 0:
            return
        target_interval = 1.0 / self.target_fps
        elapsed = time.perf_counter() - self._last_time
        wait = target_interval - elapsed
        if wait > 0:
            time.sleep(wait)
