"""
Pipeline 任务流水线引擎 —— 受 MAA (MaaAssistantArknights) 启发。

核心概念:
  - Task: 一个可配置的检测-执行单元
  - Pipeline: 由多个 Task 组成的有向图
  - State: 当前画面状态 (用于 Task 的条件跳转)
  - Action: Task 执行的操作 (ClickSelf, Swipe, DoNothing 等)
  - SubTask: 并行检查的子任务 (弹窗检测等)

设计思路:
  1. 任务用 JSON 定义, 与代码解耦
  2. 每个任务定义: 检测区域、识别算法、执行动作、下一步跳转
  3. 引擎顺序执行任务, 根据识别结果和状态决定跳转
  4. 子任务在主任务间隙并行执行

参考: https://github.com/MaaAssistantArknights/MaaAssistantArknights
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

import cv2
import numpy as np

logger = logging.getLogger("pjsk_pipeline")

# ──────────────────────────────────────────
# 基础类型
# ──────────────────────────────────────────


class TaskAction(str, Enum):
    """任务执行的动作类型。"""
    DO_NOTHING = "DoNothing"       # 只检测, 不做操作
    CLICK_SELF = "ClickSelf"       # 在检测到的位置点击
    CLICK_XY = "ClickXY"           # 在指定坐标点击
    SWIPE = "Swipe"                # 滑动
    TAP = "Tap"                    # 对每条判定线点击 (打歌用)
    WAIT = "Wait"                  # 等待指定时间


class RecognitionAlgorithm(str, Enum):
    """识别算法。"""
    DIRECT_HIT = "DirectHit"       # 模板匹配 (默认)
    OCR = "OcrDetect"              # OCR 文字识别 (预留)
    BRIGHTNESS = "BrightnessDetect"  # 亮度检测 (兼容旧方法)
    COLOR = "ColorDetect"          # 颜色检测


@dataclass
class TaskResult:
    """单个任务的执行结果。"""
    task_name: str
    success: bool = False          # 是否成功匹配/执行
    matched: bool = False          # 是否匹配到目标
    x: int = 0
    y: int = 0
    confidence: float = 0.0
    duration_ms: float = 0.0
    error: str = ""


@dataclass
class PipelineState:
    """流水线运行时状态。"""
    current_task: str = ""         # 当前执行的任务名
    previous_task: str = ""        # 上一个执行的任务名
    task_history: list[str] = field(default_factory=list)  # 执行历史
    task_retries: dict[str, int] = field(default_factory=dict)  # 各任务重试计数
    paused: bool = False
    running: bool = True
    error: str = ""


# ──────────────────────────────────────────
# 任务定义
# ──────────────────────────────────────────


@dataclass
class TaskDef:
    """
    单个任务的配置定义。

    字段说明 (参考 MAA task schema):
      name          - 任务唯一名称
      action        - 匹配后执行的动作
      algorithm     - 识别算法 (DirectHit / OcrDetect / BrightnessDetect)
      roi           - 检测区域 [x, y, w, h], 完整画面 = []
      template      - 模板图片文件名 (在 templates/ 目录)
      text          - OCR 识别文本 (algorithm=OcrDetect 时)
      threshold     - 匹配阈值 (0~1, 默认 0.8)
      next          - 成功后的下一步任务列表 ['#next'=顺序下一个, '#self'=重试, 'TaskName'=跳转]
      failed_next   - 失败后的下一步任务列表
      exceeded_next - 超过重试次数后的任务列表
      sub           - 子任务列表 (并行检测)
      pre_delay     - 执行前等待 (ms)
      post_delay    - 执行后等待 (ms)
      max_retries   - 最大重试次数
      doc           - 说明文档
    """
    name: str
    action: str = TaskAction.DO_NOTHING
    algorithm: str = RecognitionAlgorithm.DIRECT_HIT
    roi: list[int] = field(default_factory=list)          # [x, y, w, h]
    template: str = ""
    text: list[str] = field(default_factory=list)          # OCR 文本
    threshold: float = 0.8
    next: list[str] = field(default_factory=lambda: ["#next"])
    failed_next: list[str] = field(default_factory=list)
    exceeded_next: list[str] = field(default_factory=lambda: ["Stop"])
    sub: list[str] = field(default_factory=list)
    pre_delay: int = 0
    post_delay: int = 0
    max_retries: int = 10
    doc: str = ""

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "TaskDef":
        """从字典创建 TaskDef。"""
        return cls(
            name=name,
            action=d.get("action", TaskAction.DO_NOTHING),
            algorithm=d.get("algorithm", RecognitionAlgorithm.DIRECT_HIT),
            roi=d.get("roi", []),
            template=d.get("template", ""),
            text=d.get("text", []),
            threshold=d.get("threshold", 0.8),
            next=d.get("next", ["#next"]),
            failed_next=d.get("failed_next", []),
            exceeded_next=d.get("exceeded_next", ["Stop"]),
            sub=d.get("sub", []),
            pre_delay=d.get("preDelay", 0),
            post_delay=d.get("postDelay", 0),
            max_retries=d.get("maxRetries", 10),
            doc=d.get("doc", ""),
        )


# ──────────────────────────────────────────
# 流水线引擎
# ──────────────────────────────────────────


class PipelineEngine:
    """
    流水线引擎: 加载 JSON 任务定义 → 按序执行 → 状态机跳转。

    使用方式:
        engine = PipelineEngine(config)
        engine.load_tasks("tasks/pipeline.json")
        engine.run("StartGame")   # 从 StartGame 任务开始执行
    """

    def __init__(self, config: dict, adb_controller=None, screen_analyzer=None):
        self.cfg = config
        self.adb = adb_controller
        self.analyzer = screen_analyzer

        self._tasks: dict[str, TaskDef] = {}
        self._state = PipelineState()
        self._task_order: list[str] = []  # 顺序执行的任务列表
        self._current_index = 0

        # 模板缓存
        self._template_cache: dict[str, np.ndarray] = {}
        self._template_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "templates"
        )
        os.makedirs(self._template_dir, exist_ok=True)

    @property
    def state(self) -> PipelineState:
        return self._state

    # ── 任务加载 ──

    def load_tasks(self, path: str) -> bool:
        """
        从 JSON 文件加载任务定义。
        支持单文件 (tasks.json) 或目录 (tasks/*.json)。
        """
        if os.path.isdir(path):
            # 加载目录下所有 JSON
            for fname in sorted(os.listdir(path)):
                if fname.endswith(".json"):
                    fpath = os.path.join(path, fname)
                    if not self._load_single(fpath):
                        logger.warning(f"加载任务文件失败: {fpath}")
            logger.info(f"已加载 {len(self._tasks)} 个任务 (来自目录 {path})")
            return len(self._tasks) > 0
        else:
            return self._load_single(path)

    def _load_single(self, path: str) -> bool:
        """加载单文件。"""
        if not os.path.exists(path):
            logger.warning(f"任务文件不存在: {path}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, task_dict in data.items():
                self._tasks[name] = TaskDef.from_dict(name, task_dict)
            return True
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"加载任务文件失败 {path}: {e}")
            return False

    def add_task(self, task: TaskDef):
        """动态添加任务。"""
        self._tasks[task.name] = task

    def get_task(self, name: str) -> Optional[TaskDef]:
        return self._tasks.get(name)

    # ── 执行 ──

    def run(self, start_task: str = "", callback: Callable = None) -> bool:
        """
        启动流水线。

        Args:
            start_task: 起始任务名 (空则从第一个任务开始)
            callback: 每步执行后的回调 (可选)

        Returns:
            是否成功完成
        """
        if not self._tasks:
            logger.error("没有加载任何任务")
            return False

        self._state = PipelineState()
        self._state.running = True

        # 找到起始任务
        if not start_task:
            # 用第一个任务名
            start_task = next(iter(self._tasks.keys()))

        self._state.current_task = start_task
        logger.info(f"流水线启动: 起始任务={start_task}")

        while self._state.running:
            task = self._tasks.get(self._state.current_task)
            if not task:
                logger.error(f"任务不存在: {self._state.current_task}")
                self._state.error = f"Task not found: {self._state.current_task}"
                break

            # 执行任务
            result = self._execute_task(task)

            # 回调
            if callback:
                callback(task, result, self._state)

            # 错误日志
            if result.error:
                logger.warning(f"[{task.name}] {result.error}")

            # 状态更新
            self._state.previous_task = task.name
            self._state.task_history.append(task.name)

            # 决定下一步
            next_task = self._decide_next(task, result)
            self._state.current_task = next_task

            if next_task == "Stop" or next_task == "":
                logger.info("流水线结束")
                break

            # 防止死循环
            if len(self._state.task_history) > 1000:
                logger.error("任务执行超过 1000 步, 终止")
                break

        return not self._state.error

    def stop(self):
        """停止流水线。"""
        self._state.running = False

    def pause(self):
        """暂停/继续。"""
        self._state.paused = not self._state.paused

    # ── 任务执行 ──

    def _execute_task(self, task: TaskDef) -> TaskResult:
        """执行单个任务。"""
        start_time = time.perf_counter()
        result = TaskResult(task_name=task.name)

        # 前置延迟
        if task.pre_delay > 0:
            time.sleep(task.pre_delay / 1000.0)

        # 截图 (如果 ADB 可用)
        frame = None
        if self.adb:
            frame = self.adb.screencap()

        # 识别
        matched, x, y, confidence = self._recognize(task, frame)

        result.matched = matched
        result.x = x
        result.y = y
        result.confidence = confidence

        # 执行动作
        if matched:
            self._execute_action(task, x, y)
            result.success = True
        else:
            # 更新重试计数
            self._state.task_retries[task.name] = \
                self._state.task_retries.get(task.name, 0) + 1

        # 后置延迟
        if task.post_delay > 0:
            time.sleep(task.post_delay / 1000.0)

        result.duration_ms = (time.perf_counter() - start_time) * 1000
        return result

    def _recognize(
        self, task: TaskDef, frame: Optional[np.ndarray]
    ) -> tuple[bool, int, int, float]:
        """
        对画面执行识别。

        Returns:
            (matched, x, y, confidence)
        """
        if frame is None:
            # 如果无法截图, 有些动作不需要画面
            if task.action in (TaskAction.WAIT, TaskAction.CLICK_XY):
                return True, 0, 0, 1.0
            return False, 0, 0, 0.0

        h, w = frame.shape[:2]

        # 提取 ROI
        if task.roi and len(task.roi) == 4:
            rx, ry, rw, rh = task.roi
            roi = frame[ry:ry+rh, rx:rx+rw]
            if roi.size == 0:
                return False, 0, 0, 0.0
        else:
            roi = frame
            rx, ry = 0, 0

        algo = task.algorithm

        if algo == RecognitionAlgorithm.DIRECT_HIT:
            return self._match_template(task, roi, rx, ry)
        elif algo == RecognitionAlgorithm.BRIGHTNESS:
            return self._detect_brightness(task, roi, rx, ry)
        elif algo == RecognitionAlgorithm.COLOR:
            return self._detect_color(task, roi, rx, ry)
        else:
            logger.warning(f"不支持的算法: {algo}")
            return False, 0, 0, 0.0

    def _match_template(
        self, task: TaskDef, roi: np.ndarray, rx: int, ry: int
    ) -> tuple[bool, int, int, float]:
        """模板匹配识别。"""
        if not task.template:
            # 没有模板时默认成功 (用于 Wait 等动作)
            return True, 0, 0, 1.0

        template = self._load_template(task.template)
        if template is None:
            return False, 0, 0, 0.0

        if roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
            return False, 0, 0, 0.0

        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray_tpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) \
            if len(template.shape) == 3 else template

        result = cv2.matchTemplate(gray_roi, gray_tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= task.threshold:
            cx = rx + max_loc[0] + gray_tpl.shape[1] // 2
            cy = ry + max_loc[1] + gray_tpl.shape[0] // 2
            return True, cx, cy, float(max_val)

        return False, 0, 0, 0.0

    def _detect_brightness(
        self, task: TaskDef, roi: np.ndarray, rx: int, ry: int
    ) -> tuple[bool, int, int, float]:
        """亮度检测 (兼容旧方法)。"""
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        threshold = self.cfg.get("detection", {}).get("brightness", {}).get("threshold", 200)
        bright_pixels = np.sum(gray > threshold)
        total_pixels = roi.shape[0] * roi.shape[1]
        ratio = bright_pixels / total_pixels if total_pixels > 0 else 0

        # 如果 task 指定了 roi, 点击 ROI 中心
        if task.roi:
            cx = rx + roi.shape[1] // 2
            cy = ry + roi.shape[0] // 2
        else:
            cx, cy = roi.shape[1] // 2, roi.shape[0] // 2

        return ratio > 0.02, cx, cy, ratio

    def _detect_color(
        self, task: TaskDef, roi: np.ndarray, rx: int, ry: int
    ) -> tuple[bool, int, int, float]:
        """颜色检测 (兼容旧方法)。"""
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lower = self.cfg.get("detection", {}).get("color", {}).get("white_range", [0, 0, 200, 180, 50, 255])
        mask = cv2.inRange(hsv, np.array(lower[:3]), np.array(lower[3:]))
        ratio = np.mean(mask > 0)

        if task.roi:
            cx = rx + roi.shape[1] // 2
            cy = ry + roi.shape[0] // 2
        else:
            cx, cy = roi.shape[1] // 2, roi.shape[0] // 2

        return ratio > 0.1, cx, cy, ratio

    def _load_template(self, name: str) -> Optional[np.ndarray]:
        """加载模板图片 (带缓存)。"""
        if name in self._template_cache:
            return self._template_cache[name]

        # 支持直接路径或 templates/ 目录
        if os.path.isfile(name):
            path = name
        else:
            path = os.path.join(self._template_dir, name)

        if not os.path.exists(path):
            logger.warning(f"模板图片不存在: {path}")
            return None

        img = cv2.imread(path)
        if img is not None:
            self._template_cache[name] = img
        return img

    def _execute_action(self, task: TaskDef, x: int, y: int):
        """执行任务动作。"""
        if not self.adb:
            return

        action = task.action

        if action == TaskAction.CLICK_SELF:
            self.adb.tap(x, y)
            logger.debug(f"[{task.name}] ClickSelf @({x},{y})")

        elif action == TaskAction.CLICK_XY:
            # 从 task 参数获取坐标
            params = getattr(task, '_click_xy', None)
            if params:
                self.adb.tap(params[0], params[1])

        elif action == TaskAction.SWIPE:
            logger.debug(f"[{task.name}] Swipe")

        elif action == TaskAction.WAIT:
            # 等待在 pre/post delay 中处理
            pass

        elif action == TaskAction.DO_NOTHING:
            pass

    # ── 跳转决策 ──

    def _decide_next(self, task: TaskDef, result: TaskResult) -> str:
        """
        根据执行结果决定下一步。

        决策逻辑 (参考 MAA):
          1. 如果匹配成功 → 走 next 列表
          2. 如果匹配失败 → 走 failed_next 列表
          3. 超过重试次数 → 走 exceeded_next
          4. #next 表示列表顺序下一个
          5. #self 表示重试自己
          6. Stop 表示停止
        """
        retries = self._state.task_retries.get(task.name, 0)

        if result.matched:
            candidates = task.next
        elif retries >= task.max_retries:
            candidates = task.exceeded_next
            logger.warning(f"[{task.name}] 超过重试上限 ({task.max_retries}), "
                           f"走 exceeded_next: {candidates}")
        else:
            candidates = task.failed_next or []

        if not candidates:
            return "#next"

        # 解析第一个候选
        next_name = candidates[0]

        if next_name == "#next":
            return self._get_next_sequential()
        elif next_name == "#self":
            return task.name
        elif next_name == "Stop":
            return "Stop"
        elif next_name == "#back":
            # 返回上一个任务
            return self._state.previous_task or task.name
        else:
            return next_name

    def _get_next_sequential(self) -> str:
        """
        获取顺序下一个任务名。
        从 _task_order 获取, 如果没有则用 tasks 的 keys 顺序。
        """
        if not self._task_order:
            self._task_order = list(self._tasks.keys())

        if self._current_index < len(self._task_order) - 1:
            self._current_index += 1
            return self._task_order[self._current_index]
        return "Stop"

    # ── 模板管理 ──

    def save_template(self, name: str, frame: np.ndarray, roi=None):
        """
        从画面截取 ROI 保存为模板图片。
        用于 "教" 程序识别新的按钮/画面。
        """
        if roi:
            x, y, w, h = roi
            template = frame[y:y+h, x:x+w]
        else:
            template = frame

        path = os.path.join(self._template_dir, name)
        cv2.imwrite(path, template)
        self._template_cache.pop(name, None)  # 清除缓存
        logger.info(f"模板已保存: {path} ({template.shape[1]}x{template.shape[0]})")
        return path

    def list_templates(self) -> list[str]:
        """列出所有模板。"""
        if not os.path.exists(self._template_dir):
            return []
        return sorted(os.listdir(self._template_dir))
