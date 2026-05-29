"""Pipeline V2 — PJSK 核心任务引擎。

基于 MAA (MaaAssistantArknights) 的 AbstractTask / PackageTask / ProcessTask 设计。

模块结构:
  base.py       — AbstractTask 基类, PackageTask, InterfaceTask
  node.py       — Node 生命周期 (freeze→delay→action→freeze→delay)
  process.py    — ProcessTask 执行引擎
  plugins.py    — AOP 插件系统
  task_data.py  — JSON 加载与 @继承解析
  scheduler.py  — 任务调度器 (按时间/状态/优先级)

用法:
  from pipeline.task_data import TaskDataLoader
  from pipeline.process import ProcessTask
  from pipeline.scheduler import TaskScheduler
"""

from .base import AbstractTask, PackageTask, InterfaceTask
from .node import Node, NodeResult, NodeLifecycle
from .process import ProcessTask, ProcessTaskResult
from .plugins import (
    AbstractTaskPlugin,
    LoggingPlugin,
    StatisticsPlugin,
    ErrorHandlerPlugin,
    PluginManager,
)
from .task_data import TaskDataLoader, TaskData
from .scheduler import TaskScheduler, ScheduleEntry, SchedulePriority

__all__ = [
    "AbstractTask",
    "PackageTask",
    "InterfaceTask",
    "Node",
    "NodeResult",
    "NodeLifecycle",
    "ProcessTask",
    "ProcessTaskResult",
    "AbstractTaskPlugin",
    "LoggingPlugin",
    "StatisticsPlugin",
    "ErrorHandlerPlugin",
    "PluginManager",
    "TaskDataLoader",
    "TaskData",
    "TaskScheduler",
    "ScheduleEntry",
    "SchedulePriority",
]
