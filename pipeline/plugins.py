"""plugins.py — AOP 插件系统。

AbstractTaskPlugin 为 AbstractTask 提供面向切面编程支持:

  - on_pre_run(task, context): 在 task.run() 执行前调用
  - on_post_run(task, context, result): 在 task.run() 执行后调用

内置插件:
  - LoggingPlugin: 日志记录
  - StatisticsPlugin: 执行统计 (成功率、耗时等)
  - ErrorHandlerPlugin: 错误处理器 (重试、告警)
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base import AbstractTask, TaskResult

logger = logging.getLogger("pjsk_pipeline_v2")


# ──────────────────────────────────────────
# 插件抽象基类
# ──────────────────────────────────────────


class AbstractTaskPlugin(ABC):
    """任务插件抽象基类。

    子类需要实现 on_pre_run 和/或 on_post_run。
    """

    @abstractmethod
    def on_pre_run(self, task: "AbstractTask", context: dict) -> None:
        """任务执行前的钩子。"""
        ...

    @abstractmethod
    def on_post_run(self, task: "AbstractTask", context: dict, result: "TaskResult | None") -> None:
        """任务执行后的钩子。"""
        ...


# ──────────────────────────────────────────
# 日志插件
# ──────────────────────────────────────────


class LoggingPlugin(AbstractTaskPlugin):
    """日志记录插件。

    记录每个任务的执行开始/结束、耗时、结果。
    """

    def __init__(self, level: int = logging.INFO):
        self._level = level
        self._logger = logging.getLogger("pjsk_pipeline_v2.plugin.logging")

    def on_pre_run(self, task: "AbstractTask", context: dict) -> None:
        self._logger.log(self._level, f"[Task] {task.name} 开始执行 (context keys: {list(context.keys())})")

    def on_post_run(
        self, task: "AbstractTask", context: dict, result: "TaskResult | None"
    ) -> None:
        if result is None:
            return
        status = result.status.name if result.status else "UNKNOWN"
        duration = f"{result.duration_ms:.1f}ms" if result.duration_ms else "?"
        self._logger.log(
            self._level,
            f"[Task] {task.name} 完成 -> {status} ({duration})"
            f"{' error: ' + result.error if result.error else ''}",
        )


# ──────────────────────────────────────────
# 统计插件
# ──────────────────────────────────────────


@dataclass
class TaskStats:
    """单个任务的统计信息。"""
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    last_run: float = 0.0


class StatisticsPlugin(AbstractTaskPlugin):
    """执行统计插件。

    收集每个任务的执行次数、成功率、平均耗时等。
    """

    def __init__(self):
        self._stats: dict[str, TaskStats] = defaultdict(TaskStats)

    def on_pre_run(self, task: "AbstractTask", context: dict) -> None:
        pass  # 统计在后置钩子中更新

    def on_post_run(
        self, task: "AbstractTask", context: dict, result: "TaskResult | None"
    ) -> None:
        if result is None:
            return

        stats = self._stats[task.name]
        stats.total += 1
        stats.last_run = time.time()
        stats.total_duration_ms += result.duration_ms

        if result.duration_ms > 0:
            stats.min_duration_ms = min(stats.min_duration_ms, result.duration_ms)
            stats.max_duration_ms = max(stats.max_duration_ms, result.duration_ms)

        if result.success:
            stats.success += 1
        elif result.status.name == "SKIPPED":
            stats.skipped += 1
        elif result.status.name == "ERROR":
            stats.errors += 1
        else:
            stats.failed += 1

    def get_stats(self, task_name: str | None = None) -> dict[str, TaskStats] | TaskStats | None:
        """获取统计信息。

        Args:
            task_name: 指定任务名称, 为 None 时返回全部
        """
        if task_name:
            return self._stats.get(task_name)
        return dict(self._stats)

    def summary(self) -> str:
        """生成统计摘要文本。"""
        lines = ["=== Task Statistics ==="]
        total_all = sum(s.total for s in self._stats.values())
        success_all = sum(s.success for s in self._stats.values())

        lines.append(f"Total tasks: {len(self._stats)}")
        lines.append(f"Total runs: {total_all}")
        lines.append(f"Total successes: {success_all}")

        if total_all > 0:
            success_rate = success_all / total_all * 100
            lines.append(f"Overall success rate: {success_rate:.1f}%")
            avg_duration = sum(s.total_duration_ms for s in self._stats.values()) / total_all
            lines.append(f"Average duration: {avg_duration:.1f}ms")

        lines.append("")
        for task_name, stats in sorted(self._stats.items()):
            rate = (stats.success / stats.total * 100) if stats.total > 0 else 0
            avg = (stats.total_duration_ms / stats.total) if stats.total > 0 else 0
            lines.append(
                f"  {task_name}: {stats.total} runs, "
                f"{rate:.0f}% success, "
                f"avg {avg:.1f}ms"
            )

        return "\n".join(lines)

    def reset(self) -> None:
        """重置所有统计。"""
        self._stats.clear()


# ──────────────────────────────────────────
# 错误处理器插件
# ──────────────────────────────────────────


class ErrorHandlerPlugin(AbstractTaskPlugin):
    """错误处理插件。

    捕获任务执行中的异常, 执行自定义错误处理逻辑:
      - 记录错误日志
      - 超过阈值时触发告警回调
      - 可选地重试
    """

    def __init__(
        self,
        max_consecutive_errors: int = 5,
        alert_callback: Any = None,
        auto_retry: bool = True,
    ):
        self.max_consecutive_errors = max_consecutive_errors
        self.alert_callback = alert_callback  # callable(task_name, error_msg)
        self.auto_retry = auto_retry

        self._consecutive_errors: dict[str, int] = defaultdict(int)
        self._logger = logging.getLogger("pjsk_pipeline_v2.plugin.error_handler")

    def on_pre_run(self, task: "AbstractTask", context: dict) -> None:
        pass

    def on_post_run(
        self, task: "AbstractTask", context: dict, result: "TaskResult | None"
    ) -> None:
        if result is None:
            return

        if result.status.name == "ERROR" or result.error:
            # 连续错误计数
            self._consecutive_errors[task.name] += 1
            consecutive = self._consecutive_errors[task.name]

            self._logger.warning(
                f"[ErrorHandler] {task.name} 执行错误 "
                f"(连续 {consecutive}/{self.max_consecutive_errors}): {result.error}"
            )

            # 超过阈值触发告警
            if consecutive >= self.max_consecutive_errors:
                self._logger.error(
                    f"[ErrorHandler] {task.name} 连续错误达到阈值 "
                    f"({self.max_consecutive_errors}), 触发告警"
                )
                if self.alert_callback:
                    try:
                        self.alert_callback(task.name, result.error)
                    except Exception as e:
                        self._logger.error(f"[ErrorHandler] 告警回调异常: {e}")
        else:
            # 成功执行, 重置连续错误计数
            self._consecutive_errors[task.name] = 0

    def get_consecutive_errors(self, task_name: str) -> int:
        """获取指定任务的连续错误次数。"""
        return self._consecutive_errors.get(task_name, 0)

    def reset_consecutive_errors(self, task_name: str | None = None) -> None:
        """重置连续错误计数。"""
        if task_name:
            self._consecutive_errors[task_name] = 0
        else:
            self._consecutive_errors.clear()


# ──────────────────────────────────────────
# 插件管理器
# ──────────────────────────────────────────


class PluginManager:
    """插件管理器, 负责管理多个插件并批量应用到任务。"""

    def __init__(self):
        self._plugins: list[AbstractTaskPlugin] = []

    def register(self, plugin: AbstractTaskPlugin) -> None:
        """注册一个插件。"""
        if plugin not in self._plugins:
            self._plugins.append(plugin)
            logger.info(f"[PluginManager] 注册插件: {plugin.__class__.__name__}")

    def unregister(self, plugin: AbstractTaskPlugin) -> None:
        """注销一个插件。"""
        if plugin in self._plugins:
            self._plugins.remove(plugin)
            logger.info(f"[PluginManager] 注销插件: {plugin.__class__.__name__}")

    def apply_to(self, task: "AbstractTask") -> None:
        """将所有已注册的插件附加到指定任务。"""
        for plugin in self._plugins:
            task.attach_plugin(plugin)

    def apply_to_all(self, tasks: list["AbstractTask"]) -> None:
        """将插件批量附加到多个任务。"""
        for task in tasks:
            self.apply_to(task)

    @property
    def plugins(self) -> list[AbstractTaskPlugin]:
        return list(self._plugins)

    def clear(self) -> None:
        """清空所有插件。"""
        self._plugins.clear()

    def setup_defaults(self, log_level: int = logging.INFO) -> None:
        """设置默认插件集: 日志 + 统计 + 错误处理。"""
        self.register(LoggingPlugin(level=log_level))
        self.register(StatisticsPlugin())
        self.register(ErrorHandlerPlugin())
