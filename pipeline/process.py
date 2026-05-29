"""process.py — ProcessTask 执行引擎。

ProcessTask 是 Pipeline V2 的核心执行单元:

  1. 从 TaskDataLoader 获取任务定义 (JSON 中的任务节点)
  2. 在画面上执行识别 (algorithm)
  3. 执行动作 (action)
  4. 根据匹配结果和重试计数决定跳转 (next / failed_next / exceeded_next)
  5. 按 Node 生命周期执行 (freeze → delay → action → freeze → delay)

场景检测结果 (scene_name) 传给 ProcessTask, 由其决定执行哪个任务。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np

from .base import AbstractTask, TaskResult, TaskStatus

logger = logging.getLogger("pjsk_pipeline_v2")


# ──────────────────────────────────────────
# 执行结果
# ──────────────────────────────────────────


@dataclass
class ProcessTaskResult(TaskResult):
    """ProcessTask 的扩展结果。"""
    next_task: str = ""
    matched: bool = False
    retries: int = 0
    recognition_details: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────
# 识别器 — 封装具体识别算法
# ──────────────────────────────────────────


class Recognizer:
    """封装画面识别算法。

    支持: DirectHit (模板匹配), OcrDetect, BrightnessDetect, ColorDetect
    """

    def __init__(self, template_dir: str = "templates"):
        self.template_dir = template_dir
        self._template_cache: dict[str, np.ndarray] = {}

    def recognize(
        self,
        task_def: dict,
        frame: np.ndarray | None,
    ) -> dict[str, Any]:
        """对画面执行识别。

        Args:
            task_def: 任务定义字典 (从 JSON 加载)
            frame: OpenCV BGR 图像

        Returns:
            {"matched": bool, "x": int, "y": int, "confidence": float, ...}
        """
        result: dict[str, Any] = {
            "matched": False,
            "x": 0,
            "y": 0,
            "confidence": 0.0,
        }

        if frame is None:
            # 无画面时, 仅 Wait / DoNothing 动作视为匹配
            action = task_def.get("action", "DoNothing")
            if action in ("Wait", "DoNothing"):
                result["matched"] = True
                result["confidence"] = 1.0
            return result

        algorithm = task_def.get("algorithm", "DirectHit")
        roi = task_def.get("roi", [])

        # 提取 ROI
        roi_frame, rx, ry = self._extract_roi(frame, roi)
        if roi_frame is None or roi_frame.size == 0:
            return result

        # 根据算法分派
        if algorithm == "DirectHit":
            return self._direct_hit(task_def, roi_frame, rx, ry)
        elif algorithm == "OcrDetect":
            return self._ocr_detect(task_def, roi_frame, rx, ry)
        elif algorithm == "BrightnessDetect":
            return self._brightness_detect(task_def, roi_frame, rx, ry)
        elif algorithm == "ColorDetect":
            return self._color_detect(task_def, roi_frame, rx, ry)
        else:
            logger.warning(f"[Recognizer] 不支持的算法: {algorithm}")
            return result

    @staticmethod
    def _extract_roi(
        frame: np.ndarray, roi: list[int]
    ) -> tuple[np.ndarray | None, int, int]:
        """从画面中提取 ROI。

        Returns:
            (roi_frame, offset_x, offset_y)
            roi 为空时返回完整画面。
        """
        h, w = frame.shape[:2]
        if roi and len(roi) == 4:
            rx, ry, rw, rh = roi
            rx = max(0, rx)
            ry = max(0, ry)
            rw = min(rw, w - rx)
            rh = min(rh, h - ry)
            if rw <= 0 or rh <= 0:
                return None, 0, 0
            return frame[ry:ry+rh, rx:rx+rw], rx, ry
        return frame, 0, 0

    def _direct_hit(
        self, task_def: dict, roi: np.ndarray, rx: int, ry: int
    ) -> dict[str, Any]:
        """模板匹配 (DirectHit)。"""
        template_name = task_def.get("template", "")
        threshold = task_def.get("threshold", 0.8)

        if not template_name:
            # 无模板时默认匹配
            return {"matched": True, "x": rx + roi.shape[1] // 2,
                    "y": ry + roi.shape[0] // 2, "confidence": 1.0}

        template = self._load_template(template_name)
        if template is None:
            return {"matched": False, "x": 0, "y": 0, "confidence": 0.0}

        if roi.shape[0] < template.shape[0] or roi.shape[1] < template.shape[1]:
            return {"matched": False, "x": 0, "y": 0, "confidence": 0.0}

        try:
            import cv2
            gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            gray_tpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY) \
                if len(template.shape) == 3 else template

            match_result = cv2.matchTemplate(gray_roi, gray_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(match_result)

            if float(max_val) >= threshold:
                cx = rx + max_loc[0] + gray_tpl.shape[1] // 2
                cy = ry + max_loc[1] + gray_tpl.shape[0] // 2
                return {"matched": True, "x": cx, "y": cy,
                        "confidence": float(max_val)}
        except ImportError:
            logger.error("[Recognizer] OpenCV (cv2) 未安装, 无法执行模板匹配")
        except Exception as e:
            logger.error(f"[Recognizer] 模板匹配异常: {e}")

        return {"matched": False, "x": 0, "y": 0, "confidence": 0.0}

    def _ocr_detect(
        self, task_def: dict, roi: np.ndarray, rx: int, ry: int
    ) -> dict[str, Any]:
        """OCR 文字识别 (OcrDetect)。"""
        texts = task_def.get("text", [])
        if not texts:
            cx = rx + roi.shape[1] // 2
            cy = ry + roi.shape[0] // 2
            return {"matched": True, "x": cx, "y": cy, "confidence": 1.0}

        # 预留 OCR 集成点
        ocr_engine = task_def.get("_ocr_engine")
        if ocr_engine is None:
            logger.warning("[Recognizer] OCR 引擎未配置")
            return {"matched": False, "x": 0, "y": 0, "confidence": 0.0}

        try:
            recognized = ocr_engine.recognize(roi)
            for expected in texts:
                if expected.lower() in recognized.lower():
                    cx = rx + roi.shape[1] // 2
                    cy = ry + roi.shape[0] // 2
                    return {"matched": True, "x": cx, "y": cy,
                            "confidence": 0.9, "text": recognized}
        except Exception as e:
            logger.error(f"[Recognizer] OCR 异常: {e}")

        return {"matched": False, "x": 0, "y": 0, "confidence": 0.0}

    @staticmethod
    def _brightness_detect(
        task_def: dict, roi: np.ndarray, rx: int, ry: int
    ) -> dict[str, Any]:
        """亮度检测 (BrightnessDetect)。

        计算 ROI 中亮像素的比例, 超过阈值即匹配。
        """
        import cv2
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        threshold = task_def.get("threshold", 200)

        bright_pixels = float(np.sum(gray > threshold))
        total = float(roi.shape[0] * roi.shape[1])
        ratio = bright_pixels / total if total > 0 else 0

        cx = rx + roi.shape[1] // 2
        cy = ry + roi.shape[0] // 2

        return {"matched": ratio > 0.02, "x": cx, "y": cy, "confidence": ratio}

    @staticmethod
    def _color_detect(
        task_def: dict, roi: np.ndarray, rx: int, ry: int
    ) -> dict[str, Any]:
        """颜色检测 (ColorDetect)。"""
        import cv2
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        lower = task_def.get("color_lower", [0, 0, 200])
        upper = task_def.get("color_upper", [180, 50, 255])
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        ratio = float(np.mean(mask > 0))

        cx = rx + roi.shape[1] // 2
        cy = ry + roi.shape[0] // 2

        return {"matched": ratio > 0.1, "x": cx, "y": cy, "confidence": ratio}

    def _load_template(self, name: str) -> np.ndarray | None:
        """加载模板图片 (带缓存)。"""
        if name in self._template_cache:
            return self._template_cache[name]

        import os
        import cv2

        if os.path.isfile(name):
            path = name
        else:
            path = os.path.join(self.template_dir, name)

        if not os.path.exists(path):
            logger.warning(f"[Recognizer] 模板图片不存在: {path}")
            return None

        img = cv2.imread(path)
        if img is not None:
            self._template_cache[name] = img
        return img


# ──────────────────────────────────────────
# ProcessTask — 核心执行引擎
# ──────────────────────────────────────────


class ProcessTask(AbstractTask):
    """ProcessTask — 任务执行引擎。

    职责:
      1. 从 TaskDataLoader 获取完整任务定义
      2. 对画面执行识别 (algorithm)
      3. 执行动作 (action)
      4. 按 next / failed_next / exceeded_next 跳转
      5. 管理重试计数

    接收:
      - task_def: dict — 当前任务定义
      - controller: BaseController 实例 (截图 + 执行操作)
      - frame: np.ndarray — 当前帧 (可选, 由外部传入或内部截图)
      - task_loader: TaskDataLoader — 用于获取其他任务定义 (跳转)
    """

    def __init__(
        self,
        name: str = "",
        task_def: dict | None = None,
        controller=None,
        task_loader=None,
        recognizer: Recognizer | None = None,
    ):
        super().__init__(name)
        self.task_def: dict = task_def or {}
        self.controller = controller
        self.task_loader = task_loader
        self.recognizer = recognizer or Recognizer()

        # 运行时状态
        self._retries: int = 0
        self._max_retries: int = self.task_def.get("maxRetries", 10)
        self._pre_delay: int = self.task_def.get("preDelay", 0)
        self._post_delay: int = self.task_def.get("postDelay", 0)
        self._next: list[str] = self.task_def.get("next", ["#next"])
        self._failed_next: list[str] = self.task_def.get("failed_next", [])
        self._exceeded_next: list[str] = self.task_def.get("exceeded_next", ["Stop"])
        self._sub: list[str] = self.task_def.get("sub", [])

    def _run(self, context: dict) -> TaskResult:
        """执行 ProcessTask 核心逻辑。

        context 预期包含:
          - "frame": np.ndarray (当前画面)
          - "scene": str (场景名, 可选)
          - 其他自定义参数
        """
        frame: np.ndarray | None = context.get("frame")
        start_time = time.perf_counter()

        # 如果 controller 可用且没有传入 frame, 自动截图
        if frame is None and self.controller is not None:
            try:
                frame = self.controller.screencap()
            except Exception as e:
                logger.warning(f"[{self.name}] 截图失败: {e}")

        # 执行子任务 (在主任务之前运行)
        if self._sub and frame is not None:
            self._run_subtasks(frame, context)

        # 阶段 1: 前置延迟
        if self._pre_delay > 0:
            time.sleep(self._pre_delay / 1000.0)

        # 阶段 2: 执行子任务 (延迟后再次检测, 用于弹窗)
        if self._sub and self.controller is not None:
            try:
                frame = self.controller.screencap()
            except Exception:
                pass

        # 阶段 3: 识别
        recog_result = self.recognizer.recognize(self.task_def, frame)
        matched = recog_result.get("matched", False)
        recog_x = recog_result.get("x", 0)
        recog_y = recog_result.get("y", 0)
        confidence = recog_result.get("confidence", 0.0)

        # 阶段 4: 执行动作
        action_performed = False
        if matched:
            action_performed = self._execute_action(self.task_def, recog_x, recog_y, context)
        else:
            self._retries += 1

        # 阶段 5: 后置延迟
        if self._post_delay > 0:
            time.sleep(self._post_delay / 1000.0)

        # 阶段 6: 跳转决策
        next_task = self._decide_next(matched)
        duration = (time.perf_counter() - start_time) * 1000

        return ProcessTaskResult(
            task_name=self.name,
            success=matched and action_performed,
            status=TaskStatus.SUCCESS if matched else TaskStatus.FAILED,
            matched=matched,
            x=recog_x,
            y=recog_y,
            confidence=confidence,
            retries=self._retries,
            next_task=next_task,
            recognition_details=recog_result,
            duration_ms=duration,
        )

    def _run_subtasks(self, frame: np.ndarray, context: dict) -> None:
        """执行子任务 (弹窗检测/关闭等)。

        子任务定义也是 JSON 中的任务节点, 由 task_loader 获取。
        """
        if self.task_loader is None:
            return

        for sub_name in self._sub:
            sub_def = self.task_loader.get_task(sub_name) if hasattr(
                self.task_loader, "get_task"
            ) else self.task_loader.get(sub_name)

            if sub_def is None:
                continue

            # 识别子任务目标
            sub_result = self.recognizer.recognize(sub_def, frame)
            if sub_result.get("matched"):
                logger.info(f"[{self.name}] 子任务触发: {sub_name}")
                self._execute_action(sub_def, sub_result["x"], sub_result["y"], context)

                # 重新截图
                if self.controller is not None:
                    try:
                        frame = self.controller.screencap()
                    except Exception:
                        break

    def _execute_action(
        self, task_def: dict, x: int, y: int, context: dict
    ) -> bool:
        """执行任务定义中的动作。"""
        action = task_def.get("action", "DoNothing")

        if self.controller is None:
            logger.debug(f"[{self.name}] 无控制器, 跳过动作: {action}")
            return True

        try:
            if action == "ClickSelf":
                self.controller.tap(x, y)
                logger.debug(f"[{self.name}] ClickSelf @({x},{y})")

            elif action == "ClickXY":
                target_x = task_def.get("specific_x", x)
                target_y = task_def.get("specific_y", y)
                self.controller.tap(target_x, target_y)
                logger.debug(f"[{self.name}] ClickXY @({target_x},{target_y})")

            elif action == "Swipe":
                x2 = task_def.get("swipe_x2", x)
                y2 = task_def.get("swipe_y2", y + 200)  # 默认向下滑动
                duration = task_def.get("swipe_duration", 300)
                self.controller.swipe(x, y, x2, y2, duration)
                logger.debug(f"[{self.name}] Swipe ({x},{y})->({x2},{y2})")

            elif action == "Tap":
                self.controller.tap(x, y)
                logger.debug(f"[{self.name}] Tap @({x},{y})")

            elif action == "Wait":
                wait_ms = task_def.get("postDelay", 1000)
                time.sleep(wait_ms / 1000.0)
                logger.debug(f"[{self.name}] Wait {wait_ms}ms")

            elif action == "DoNothing":
                pass

            else:
                logger.warning(f"[{self.name}] 未知动作: {action}")
                return False

            return True

        except Exception as e:
            logger.error(f"[{self.name}] 动作执行失败 {action}: {e}")
            return False

    def _decide_next(self, matched: bool) -> str:
        """根据匹配结果和重试次数决定下一步。

        决策逻辑 (参考 MAA):
          1. 匹配成功 → next 列表第一个
          2. 匹配失败且未超重试 → failed_next 列表
          3. 超过重试上限 → exceeded_next 列表
          4. #next → 顺序下一个 (当前任务名的下一个任务)
          5. #self → 重试自己
          6. Stop → 停止
        """
        if matched:
            candidates = self._next
        elif self._retries >= self._max_retries:
            candidates = self._exceeded_next
            logger.warning(
                f"[{self.name}] 超过重试上限 ({self._max_retries}), "
                f"走 exceeded_next: {self._exceeded_next}"
            )
        else:
            candidates = self._failed_next or []

        if not candidates:
            return "#next"

        next_name = candidates[0]

        if next_name == "#next":
            return self._resolve_next_sequential()
        elif next_name == "#self":
            return self.name
        elif next_name == "Stop":
            return "Stop"
        elif next_name == "#back":
            # 返回上一个任务 — 由上层调用者处理
            return "#back"
        else:
            return next_name

    def _resolve_next_sequential(self) -> str:
        """解析顺序下一个任务。

        简单实现: 如果 task_loader 有 task_order, 使用 order 列表;
        否则返回 Stop。
        """
        if self.task_loader is not None and hasattr(self.task_loader, "task_order"):
            order = self.task_loader.task_order
            if isinstance(order, list):
                try:
                    idx = order.index(self.name)
                    if idx + 1 < len(order):
                        return order[idx + 1]
                except ValueError:
                    pass
        return "Stop"

    def reset_retries(self) -> None:
        """重置重试计数。"""
        self._retries = 0

    @property
    def retries(self) -> int:
        return self._retries

    @property
    def max_retries(self) -> int:
        return self._max_retries
