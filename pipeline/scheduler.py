"""scheduler.py — 任务调度器。

按时间 / 状态 / 优先级调度任务的执行。

调度策略:
  - 时间调度: 定时执行 (cron-like), 间隔执行, 指定时间窗口
  - 状态调度: 根据前一任务的结果 / 场景状态选择下一任务
  - 优先级调度: 高优先级任务优先执行

用法:
    scheduler = TaskScheduler()
    scheduler.add_entry(TaskEntry("DailyCheck", cron="0 6 * * *", priority=10))
    scheduler.add_entry(TaskEntry("GameLoop", interval=5.0, priority=5))
    scheduler.run_loop(context_provider=lambda: {"frame": frame})
"""

from __future__ import annotations

import enum
import heapq
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .base import AbstractTask, TaskResult, TaskStatus

logger = logging.getLogger("pjsk_pipeline_v2")


# ──────────────────────────────────────────
# 调度优先级
# ──────────────────────────────────────────


class SchedulePriority(enum.IntEnum):
    """调度优先级 (数值越大优先级越高)。"""
    LOWEST = 0
    LOW = 25
    NORMAL = 50
    HIGH = 75
    HIGHEST = 100
    CRITICAL = 999


# ──────────────────────────────────────────
# 调度条目
# ──────────────────────────────────────────


@dataclass(order=True)
class ScheduleEntry:
    """调度条目。

    支持多种调度模式:
      - interval: 固定间隔执行 (秒)
      - cron: cron 表达式 (预留)
      - once: 单次执行
      - manual: 仅手动触发

    优先级队列排序依据:
      (next_run_time, -priority)
    """
    task: AbstractTask = field(compare=False)
    priority: int = field(default=SchedulePriority.NORMAL, compare=True)

    # 调度模式
    mode: str = field(default="interval", compare=False)  # "interval" | "cron" | "once" | "manual"
    interval: float = field(default=5.0, compare=False)  # 秒

    # cron 表达式 (预留)
    cron_expr: str = field(default="", compare=False)

    # 运行时状态
    last_run: float = field(default=0.0, compare=False)
    next_run: float = field(default=0.0, compare=False)
    enabled: bool = field(default=True, compare=False)
    run_count: int = field(default=0, compare=False)

    # 条件
    condition: Callable[[dict], bool] | None = field(default=None, compare=False)

    # 标签 (用于分组/过滤)
    tags: list[str] = field(default_factory=list, compare=False)

    def __post_init__(self):
        # 优先级取反, 因为 heapq 是最小堆
        # 但我们用 next_run 排序, priority 仅在同 next_run 时使用
        pass

    def should_run(self, context: dict) -> bool:
        """检查是否应该执行。

        Args:
            context: 当前上下文 (包含 frame, scene 等)

        Returns:
            是否应该执行
        """
        if not self.enabled:
            return False

        # 条件检查
        if self.condition is not None:
            try:
                if not self.condition(context):
                    return False
            except Exception as e:
                logger.warning(f"[Scheduler] 条件检查异常 ({self.task.name}): {e}")
                return False

        # 时间检查
        now = time.time()
        if self.mode == "interval":
            return (now - self.last_run) >= self.interval
        elif self.mode == "once":
            return self.run_count == 0
        elif self.mode == "manual":
            return False  # 仅手动触发
        elif self.mode == "cron":
            # 预留 cron 支持
            return now >= self.next_run

        return False

    def mark_run(self) -> None:
        """标记已执行, 更新下次执行时间。"""
        now = time.time()
        self.last_run = now
        self.run_count += 1

        if self.mode == "interval":
            self.next_run = now + self.interval
        elif self.mode == "once":
            self.next_run = float("inf")
        elif self.mode == "cron":
            # 预留: 计算下次 cron 触发时间
            self.next_run = now + 60  # 兜底: 1分钟后
        else:
            self.next_run = float("inf")


# ──────────────────────────────────────────
# 调度器
# ──────────────────────────────────────────


class TaskScheduler:
    """任务调度器。

    管理多个 ScheduleEntry, 在运行循环中决定下一个要执行的任务。
    """

    def __init__(self):
        self._entries: list[ScheduleEntry] = []
        self._entry_map: dict[str, ScheduleEntry] = {}  # task_name → entry
        self._running: bool = False
        self._paused: bool = False
        self._loop_delay: float = 0.05  # 主循环延迟 (秒)
        self._context_provider: Callable[[], dict] | None = None
        self._result_callback: Callable[[ScheduleEntry, TaskResult], None] | None = None

        # 状态追踪
        self._last_result: TaskResult | None = None
        self._last_entry: ScheduleEntry | None = None
        self._history: list[tuple[str, float, str]] = []  # (name, time, status)

    # ── 条目管理 ──

    def add_entry(self, entry: ScheduleEntry) -> None:
        """添加调度条目。"""
        self._entries.append(entry)
        self._entry_map[entry.task.name] = entry
        logger.info(
            f"[Scheduler] 添加任务: {entry.task.name} "
            f"(mode={entry.mode}, priority={entry.priority})"
        )

    def remove_entry(self, task_name: str) -> bool:
        """移除调度条目。"""
        entry = self._entry_map.pop(task_name, None)
        if entry:
            self._entries.remove(entry)
            logger.info(f"[Scheduler] 移除任务: {task_name}")
            return True
        return False

    def get_entry(self, task_name: str) -> ScheduleEntry | None:
        """获取调度条目。"""
        return self._entry_map.get(task_name)

    def has_entry(self, task_name: str) -> bool:
        """检查调度条目是否存在。"""
        return task_name in self._entry_map

    def enable_entry(self, task_name: str) -> bool:
        """启用调度条目。"""
        entry = self.get_entry(task_name)
        if entry:
            entry.enabled = True
            return True
        return False

    def disable_entry(self, task_name: str) -> bool:
        """禁用调度条目。"""
        entry = self.get_entry(task_name)
        if entry:
            entry.enabled = False
            return True
        return False

    def clear(self) -> None:
        """清空所有调度条目。"""
        self._entries.clear()
        self._entry_map.clear()

    @property
    def entries(self) -> list[ScheduleEntry]:
        return list(self._entries)

    # ── 上下文 / 回调 ──

    def set_context_provider(self, provider: Callable[[], dict]) -> None:
        """设置上下文提供者。

        每次运行循环都会调用 provider() 获取当前上下文
        (包含 frame, scene 等)。
        """
        self._context_provider = provider

    def set_result_callback(self, callback: Callable[[ScheduleEntry, TaskResult], None]) -> None:
        """设置结果回调。

        每次任务执行完成后调用。
        """
        self._result_callback = callback

    # ── 调度核心 ──

    def get_next_task(self, context: dict) -> ScheduleEntry | None:
        """获取下一个应该执行的任务。

        按优先级排序: 优先级越高越优先; 同优先级下按上次执行时间。
        """
        candidates: list[tuple[int, int, float, ScheduleEntry]] = []

        for i, entry in enumerate(self._entries):
            if entry.should_run(context):
                # 优先级取反 (大值优先), 时间顺序 (早的优先)
                neg_priority = -entry.priority
                candidates.append((neg_priority, i, entry.last_run, entry))

        if not candidates:
            return None

        # 排序: 优先看优先级, 再看 last_run (越久未执行越优先)
        candidates.sort(key=lambda x: (x[0], x[2], x[1]))
        return candidates[0][3]

    def execute_one(self, context: dict, entry: ScheduleEntry) -> TaskResult | None:
        """执行一个调度条目。

        Args:
            context: 执行上下文
            entry: 调度条目

        Returns:
            任务执行结果
        """
        try:
            result = entry.task.run(context)
            entry.mark_run()

            # 记录历史
            self._last_result = result
            self._last_entry = entry
            self._history.append(
                (entry.task.name, time.time(), result.status.name)
            )
            # 只保留最近 1000 条
            if len(self._history) > 1000:
                self._history = self._history[-1000:]

            # 回调
            if self._result_callback:
                try:
                    self._result_callback(entry, result)
                except Exception as e:
                    logger.error(f"[Scheduler] 结果回调异常: {e}")

            return result

        except Exception as e:
            logger.exception(f"[Scheduler] 执行任务异常 {entry.task.name}: {e}")
            entry.mark_run()
            return TaskResult(
                task_name=entry.task.name,
                success=False,
                status=TaskStatus.ERROR,
                error=str(e),
            )

    # ── 运行循环 ──

    def run_once(self, context: dict | None = None) -> TaskResult | None:
        """执行一次调度 (运行下一个符合条件的任务)。

        Returns:
            执行结果, 如果没有符合条件的任务则返回 None
        """
        ctx = context or (self._context_provider() if self._context_provider else {})

        entry = self.get_next_task(ctx)
        if entry is None:
            return None

        return self.execute_one(ctx, entry)

    def run_loop(
        self,
        max_iterations: int = 0,  # 0 = 无限
        timeout: float = 0,       # 0 = 无限
    ) -> None:
        """运行调度主循环。

        Args:
            max_iterations: 最大执行次数 (0 = 无限)
            timeout: 超时时间 (秒, 0 = 无限)
        """
        self._running = True
        self._paused = False
        start_time = time.time()
        iterations = 0

        logger.info("[Scheduler] 调度循环启动")

        try:
            while self._running:
                # 暂停检查
                if self._paused:
                    time.sleep(0.1)
                    continue

                # 超时检查
                if timeout > 0 and (time.time() - start_time) >= timeout:
                    logger.info("[Scheduler] 调度循环超时, 停止")
                    break

                # 迭代次数检查
                if max_iterations > 0 and iterations >= max_iterations:
                    logger.info(f"[Scheduler] 达到最大迭代次数 ({max_iterations}), 停止")
                    break

                # 执行一次调度
                result = self.run_once()

                if result is not None:
                    iterations += 1
                else:
                    # 没有可执行的任务, 短暂休眠
                    time.sleep(self._loop_delay)

        except KeyboardInterrupt:
            logger.info("[Scheduler] 调度循环被中断")
        except Exception as e:
            logger.exception(f"[Scheduler] 调度循环异常: {e}")
        finally:
            self._running = False
            logger.info("[Scheduler] 调度循环结束")

    def stop(self) -> None:
        """停止调度循环。"""
        self._running = False

    def pause(self) -> None:
        """暂停调度。"""
        self._paused = True
        logger.info("[Scheduler] 暂停")

    def resume(self) -> None:
        """恢复调度。"""
        self._paused = False
        logger.info("[Scheduler] 恢复")

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    # ── 状态查询 ──

    def get_history(
        self, limit: int = 10
    ) -> list[tuple[str, float, str]]:
        """获取执行历史。

        Args:
            limit: 返回最近 N 条

        Returns:
            [(task_name, timestamp, status), ...]
        """
        return self._history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """获取调度统计信息。"""
        stats = {
            "total_entries": len(self._entries),
            "enabled_entries": sum(1 for e in self._entries if e.enabled),
            "total_executions": len(self._history),
            "running": self._running,
            "paused": self._paused,
        }

        # 各任务执行次数
        task_counts: dict[str, int] = {}
        for name, _, _ in self._history:
            task_counts[name] = task_counts.get(name, 0) + 1
        stats["task_execution_counts"] = task_counts

        return stats

    def summary(self) -> str:
        """生成调度摘要。"""
        lines = ["=== Scheduler Summary ==="]

        stats = self.get_stats()
        lines.append(f"Entries: {stats['total_entries']} ({stats['enabled_entries']} enabled)")
        lines.append(f"Executions: {stats['total_executions']}")
        lines.append(f"Status: {'Running' if stats['running'] else 'Stopped'} "
                      f"{'(Paused)' if stats['paused'] else ''}")

        lines.append("")
        lines.append("Entries:")
        for entry in self._entries:
            status = "ENABLED" if entry.enabled else "DISABLED"
            last = f"last={time.strftime('%H:%M:%S', time.localtime(entry.last_run))}" \
                if entry.last_run > 0 else "never"
            lines.append(
                f"  [{status}] {entry.task.name}: "
                f"mode={entry.mode}, priority={entry.priority}, "
                f"runs={entry.run_count}, {last}"
            )

        return "\n".join(lines)
