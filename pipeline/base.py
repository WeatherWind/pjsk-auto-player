"""base.py — AbstractTask / PackageTask / InterfaceTask 基类。

基于 MAA (MaaAssistantArknights) 的任务设计:
  - AbstractTask: 模板方法模式, run() → _run()
  - PackageTask: 子任务容器, 按序/条件执行子任务
  - InterfaceTask: 顶层接口任务, 整合场景检测与调度
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional

logger = logging.getLogger("pjsk_pipeline_v2")


# ──────────────────────────────────────────
# 基础类型 (与旧 pipeline.py 兼容但独立维护)
# ──────────────────────────────────────────


class TaskAction(str, Enum):
    """任务执行的动作类型。"""
    DO_NOTHING = "DoNothing"
    CLICK_SELF = "ClickSelf"
    CLICK_XY = "ClickXY"
    SWIPE = "Swipe"
    TAP = "Tap"
    WAIT = "Wait"


class RecognitionAlgorithm(str, Enum):
    """识别算法。"""
    DIRECT_HIT = "DirectHit"
    OCR = "OcrDetect"
    BRIGHTNESS = "BrightnessDetect"
    COLOR = "ColorDetect"


class TaskStatus(Enum):
    """任务执行状态。"""
    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    SKIPPED = auto()
    TIMEOUT = auto()
    ERROR = auto()


@dataclass
class TaskResult:
    """任务的执行结果。"""
    task_name: str = ""
    success: bool = False
    status: TaskStatus = TaskStatus.PENDING
    matched: bool = False
    x: int = 0
    y: int = 0
    confidence: float = 0.0
    duration_ms: float = 0.0
    error: str = ""
    retries: int = 0
    data: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────
# AbstractTask — 模板方法基类
# ──────────────────────────────────────────


class AbstractTask(ABC):
    """任务基类, 使用模板方法模式。

    run() 为外部入口, 内部调用 _run() 由子类实现。
    插件钩子 (pre_run / post_run) 由 PluginManager 自动织入。
    """

    def __init__(self, name: str = "", config: dict | None = None):
        self.name = name or self.__class__.__name__
        self.config: dict = config or {}
        self.status: TaskStatus = TaskStatus.PENDING
        self.result: TaskResult = TaskResult(task_name=self.name)
        self._start_time: float = 0.0
        self._plugins: list[AbstractTaskPlugin] = []  # noqa: F821 — forward ref in plugins.py

    # ── 模板方法 ──

    def run(self, context: dict | None = None) -> TaskResult:
        """外部调用入口。模板方法, 封装了 _run() 与插件钩子。"""
        self._start_time = time.perf_counter()
        self.status = TaskStatus.RUNNING
        context = context or {}

        try:
            # 插件前置钩子
            self._invoke_plugins("pre_run", context)

            # 子类实现的具体逻辑
            result = self._run(context)

            # 插件后置钩子
            self._invoke_plugins("post_run", context, result)

            self.result = result
            self.status = result.status if result.status != TaskStatus.PENDING else (
                TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
            )
            return result

        except Exception as e:
            logger.exception(f"[{self.name}] 执行异常: {e}")
            self.status = TaskStatus.ERROR
            self.result = TaskResult(
                task_name=self.name,
                success=False,
                status=TaskStatus.ERROR,
                error=str(e),
                duration_ms=(time.perf_counter() - self._start_time) * 1000,
            )
            return self.result

    @abstractmethod
    def _run(self, context: dict) -> TaskResult:
        """子类必须实现的具体执行逻辑。"""
        ...

    # ── 插件管理 ──

    def attach_plugin(self, plugin: AbstractTaskPlugin) -> None:  # noqa: F821
        """附加一个插件。"""
        self._plugins.append(plugin)

    def detach_plugin(self, plugin: AbstractTaskPlugin) -> None:  # noqa: F821
        """移除一个插件。"""
        if plugin in self._plugins:
            self._plugins.remove(plugin)

    def _invoke_plugins(self, hook: str, context: dict, result: TaskResult | None = None) -> None:
        """调用所有插件的指定钩子。"""
        for plugin in self._plugins:
            try:
                if hook == "pre_run":
                    plugin.on_pre_run(self, context)
                elif hook == "post_run":
                    plugin.on_post_run(self, context, result)  # type: ignore[arg-type]
            except Exception as e:
                logger.warning(f"[Plugin] {plugin.__class__.__name__}.{hook} 异常: {e}")


# ──────────────────────────────────────────
# PackageTask — 子任务容器
# ──────────────────────────────────────────


class PackageTask(AbstractTask):
    """子任务容器, 按序执行一组子任务。

    支持:
      - 顺序执行 (默认)
      - 条件执行 (根据场景检测结果)
      - 短路执行 (某个子任务失败后停止)
    """

    def __init__(
        self,
        name: str = "",
        config: dict | None = None,
        tasks: list[AbstractTask] | None = None,
        stop_on_failure: bool = True,
    ):
        super().__init__(name, config)
        self._tasks: list[AbstractTask] = tasks or []
        self.stop_on_failure = stop_on_failure

    def add_task(self, task: AbstractTask) -> None:
        """添加子任务。"""
        self._tasks.append(task)

    def get_task(self, name: str) -> Optional[AbstractTask]:
        """按名称查找子任务。"""
        for t in self._tasks:
            if t.name == name:
                return t
        return None

    def clear_tasks(self) -> None:
        """清空所有子任务。"""
        self._tasks.clear()

    @property
    def tasks(self) -> list[AbstractTask]:
        return list(self._tasks)

    # ── 子任务扩展点 ──

    def on_before_subtask(self, task: AbstractTask, context: dict) -> None:
        """每个子任务执行前的钩子。子类可重写。"""
        pass

    def on_after_subtask(self, task: AbstractTask, result: TaskResult, context: dict) -> None:
        """每个子任务执行后的钩子。子类可重写。"""
        pass

    def should_skip_subtask(self, task: AbstractTask, context: dict) -> bool:
        """子类可重写此方法实现条件跳过。"""
        return False

    def _run(self, context: dict) -> TaskResult:
        """按序执行所有子任务。"""
        results: list[TaskResult] = []

        for task in self._tasks:
            # 条件跳过
            if self.should_skip_subtask(task, context):
                task.status = TaskStatus.SKIPPED
                results.append(TaskResult(
                    task_name=task.name,
                    status=TaskStatus.SKIPPED,
                    success=False,
                ))
                continue

            # 前置钩子
            self.on_before_subtask(task, context)

            # 执行子任务
            result = task.run(context)
            results.append(result)

            # 后置钩子
            self.on_after_subtask(task, result, context)

            # 失败短路
            if self.stop_on_failure and not result.success:
                logger.info(f"[{self.name}] 子任务 {task.name} 失败, 停止执行后续任务")
                break

        # 汇总结果
        success_count = sum(1 for r in results if r.success)
        total = len(results)
        all_success = success_count == total and total > 0

        return TaskResult(
            task_name=self.name,
            success=all_success,
            status=TaskStatus.SUCCESS if all_success else TaskStatus.FAILED,
            data={"sub_results": results, "success_count": success_count, "total": total},
            duration_ms=(time.perf_counter() - self._start_time) * 1000,
        )


# ──────────────────────────────────────────
# InterfaceTask — 顶层入口任务
# ──────────────────────────────────────────


class InterfaceTask(AbstractTask):
    """顶层接口任务。

    整合:
      - 场景检测 (scene_classifier)
      - TaskDataLoader 中的任务定义
      - ProcessTask 执行引擎
      - 调度器

    是外部调用的主要入口。
    """

    def __init__(
        self,
        name: str = "InterfaceTask",
        config: dict | None = None,
        scene_classifier=None,
        task_loader=None,
        controller=None,
        scheduler=None,
    ):
        super().__init__(name, config)
        self.scene_classifier = scene_classifier
        self.task_loader = task_loader
        self.controller = controller
        self.scheduler = scheduler
        self._current_process: Optional[AbstractTask] = None

    def set_scene_classifier(self, classifier) -> None:
        """设置场景分类器。"""
        self.scene_classifier = classifier

    def set_task_loader(self, loader) -> None:
        """设置任务数据加载器。"""
        self.task_loader = loader

    def set_controller(self, controller) -> None:
        """设置设备控制器。"""
        self.controller = controller

    def set_scheduler(self, scheduler) -> None:
        """设置调度器。"""
        self.scheduler = scheduler

    def _run(self, context: dict) -> TaskResult:
        """执行顶层任务循环。

        流程:
          1. 场景检测 (如果可用)
          2. 根据场景选择 ProcessTask
          3. 执行 ProcessTask
          4. 由调度器决定下一步
        """
        scene_name = context.get("scene", "")

        # 场景检测
        if self.scene_classifier and not scene_name:
            frame = context.get("frame")
            if frame is not None:
                scene_name = self.scene_classifier.classify(frame)
                context["scene"] = scene_name
                logger.info(f"[{self.name}] 场景检测: {scene_name}")

        # 根据场景选择任务定义
        if self.task_loader and scene_name:
            task_def = self.task_loader.get_task(scene_name)
            if task_def:
                from .process import ProcessTask  # 延迟导入避免循环
                proc = ProcessTask(
                    name=scene_name,
                    task_def=task_def,
                    controller=self.controller,
                    task_loader=self.task_loader,
                )
                # 传递插件
                for plugin in self._plugins:
                    proc.attach_plugin(plugin)
                self._current_process = proc
                return proc.run(context)

        # 无场景匹配时的默认处理
        logger.warning(f"[{self.name}] 未检测到可处理的场景: {scene_name}")
        return TaskResult(
            task_name=self.name,
            success=False,
            status=TaskStatus.SKIPPED,
            error=f"未检测到可处理的场景: {scene_name}",
            duration_ms=(time.perf_counter() - self._start_time) * 1000,
        )

    @property
    def current_process(self) -> Optional[AbstractTask]:
        return self._current_process
