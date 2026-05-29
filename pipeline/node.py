"""node.py — Node 生命周期管理。

Node 代表一个带有 freeze 检测的完整执行周期:

  pre_wait_freezes → pre_delay → action → post_wait_freezes → post_delay

freeze 检测用于等待画面稳定 (例如弹窗动画播放完毕),
确保在合适的时机执行操作。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np

logger = logging.getLogger("pjsk_pipeline_v2")


FREEZE_CHECK_INTERVAL = 0.05  # freeze 检测间隔 (秒)
DEFAULT_FREEZE_FRAMES = 3      # 默认需要连续多少帧稳定才视为 freeze
DEFAULT_FREEZE_THRESHOLD = 0.95  # 默认 freeze 相似度阈值


@dataclass
class NodeResult:
    """Node 执行结果。"""
    success: bool = False
    action_performed: bool = False
    x: int = 0
    y: int = 0
    confidence: float = 0.0
    pre_delay_ms: float = 0.0
    post_delay_ms: float = 0.0
    freeze_before: bool = False
    freeze_after: bool = False
    duration_ms: float = 0.0
    error: str = ""


class Node:
    """Node — 一个完整的识别-执行生命周期。

    生命周期: pre_wait_freezes → pre_delay → action → post_wait_freezes → post_delay

    action 由构造时传入的 callable 定义。
    """

    def __init__(
        self,
        name: str = "",
        action_fn: Callable | None = None,
        config: dict | None = None,
        controller=None,
    ):
        self.name = name or self.__class__.__name__
        self.action_fn = action_fn
        self.config: dict = config or {}
        self.controller = controller  # 截图/操作控制器

        # freeze 配置
        self.freeze_before_enabled: bool = self.config.get("freeze_before", True)
        self.freeze_after_enabled: bool = self.config.get("freeze_after", False)
        self.freeze_frames: int = self.config.get("freeze_frames", DEFAULT_FREEZE_FRAMES)
        self.freeze_threshold: float = self.config.get(
            "freeze_threshold", DEFAULT_FREEZE_THRESHOLD
        )
        self.freeze_timeout: float = self.config.get("freeze_timeout", 10.0)  # 秒

        # delay 配置 (毫秒)
        self.pre_delay: int = self.config.get("preDelay", 0)
        self.post_delay: int = self.config.get("postDelay", 0)

        # 识别结果回填 (由 ProcessTask 在调用 node 前设置)
        self.recognition_result: dict[str, Any] = field(default_factory=dict)  # type: ignore[assignment]

    # ── 核心执行 ──

    def execute(self, context: dict | None = None) -> NodeResult:
        """执行 Node 的完整生命周期。"""
        context = context or {}
        start_time = time.perf_counter()
        result = NodeResult()

        try:
            # 阶段 1: 前置 freeze 等待
            freeze_before_ok = True
            if self.freeze_before_enabled and self.controller is not None:
                freeze_before_ok = self._wait_freeze(
                    timeout=self.freeze_timeout,
                    threshold=self.freeze_threshold,
                    required_frames=self.freeze_frames,
                )
                result.freeze_before = freeze_before_ok
                if not freeze_before_ok:
                    logger.warning(
                        f"[{self.name}] 前置 freeze 等待超时 ({self.freeze_timeout}s)"
                    )

            # 阶段 2: 前置延迟
            pre_delay_start = time.perf_counter()
            if self.pre_delay > 0:
                time.sleep(self.pre_delay / 1000.0)
            result.pre_delay_ms = (time.perf_counter() - pre_delay_start) * 1000

            # 阶段 3: 执行动作
            if self.action_fn is not None:
                action_start = time.perf_counter()
                try:
                    action_result = self.action_fn(context)
                    if isinstance(action_result, dict):
                        result.x = action_result.get("x", 0)
                        result.y = action_result.get("y", 0)
                        result.confidence = action_result.get("confidence", 0.0)
                        result.success = action_result.get("success", True)
                    else:
                        result.success = bool(action_result)
                    result.action_performed = True
                except Exception as e:
                    logger.error(f"[{self.name}] 动作执行异常: {e}")
                    result.success = False
                    result.error = str(e)
                action_duration = (time.perf_counter() - action_start) * 1000
                context["action_duration_ms"] = action_duration
            else:
                # 没有动作函数, 视为纯检测节点
                logger.debug(f"[{self.name}] 无动作函数 (检测节点)")
                result.success = True

            # 阶段 4: 后置 freeze 等待
            freeze_after_ok = True
            if self.freeze_after_enabled and self.controller is not None:
                freeze_after_ok = self._wait_freeze(
                    timeout=self.freeze_timeout,
                    threshold=self.freeze_threshold,
                    required_frames=self.freeze_frames,
                )
                result.freeze_after = freeze_after_ok
                if not freeze_after_ok:
                    logger.warning(
                        f"[{self.name}] 后置 freeze 等待超时 ({self.freeze_timeout}s)"
                    )

            # 阶段 5: 后置延迟
            post_delay_start = time.perf_counter()
            if self.post_delay > 0:
                time.sleep(self.post_delay / 1000.0)
            result.post_delay_ms = (time.perf_counter() - post_delay_start) * 1000

        except Exception as e:
            logger.exception(f"[{self.name}] Node 执行异常: {e}")
            result.success = False
            result.error = str(e)

        result.duration_ms = (time.perf_counter() - start_time) * 1000
        return result

    # ── Freeze 检测 ──

    def _wait_freeze(
        self,
        timeout: float = 10.0,
        threshold: float = 0.95,
        required_frames: int = 3,
    ) -> bool:
        """等待画面稳定 (freeze)。

        持续截图比较, 当连续 required_frames 帧的相似度 ≥ threshold 时返回 True。
        超时返回 False。

        如果 controller 没有 screencap 方法, 默认返回 True。
        """
        if not hasattr(self.controller, "screencap") or not callable(
            getattr(self.controller, "screencap", None)
        ):
            return True

        prev_frame: np.ndarray | None = None
        stable_count = 0
        deadline = time.perf_counter() + timeout

        while time.perf_counter() < deadline:
            frame = self.controller.screencap()
            if frame is None:
                time.sleep(FREEZE_CHECK_INTERVAL)
                continue

            if prev_frame is not None:
                similarity = self._compute_similarity(prev_frame, frame)
                if similarity >= threshold:
                    stable_count += 1
                    if stable_count >= required_frames:
                        return True
                else:
                    stable_count = 0

            prev_frame = frame
            time.sleep(FREEZE_CHECK_INTERVAL)

        return False

    @staticmethod
    def _compute_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """计算两帧画面的结构相似度 (0~1)。

        使用平均 SSIM 的近似: 比较灰度直方图和相关度。
        如果形状不同, 返回 0.0。
        """
        if a.shape != b.shape:
            return 0.0

        try:
            # 转灰度
            if len(a.shape) == 3:
                a_gray = np.mean(a, axis=2).astype(np.float32)
                b_gray = np.mean(b, axis=2).astype(np.float32)
            else:
                a_gray = a.astype(np.float32)
                b_gray = b.astype(np.float32)

            # MSE → 归一化相似度
            mse = np.mean((a_gray - b_gray) ** 2)
            if mse < 1.0:
                return 1.0
            similarity = 1.0 / (1.0 + mse / 10000.0)
            return float(similarity)

        except Exception:
            return 0.0


# ──────────────────────────────────────────
# NodeLifecycle — Node 生命周期构建器
# ──────────────────────────────────────────


class NodeLifecycle:
    """便捷构建器, 用于快速创建带 freeze 检测的 Node。

    用法:
        lifecycle = (NodeLifecycle(controller=adb)
            .with_pre_delay(200)
            .with_action(my_action)
            .with_post_delay(500)
            .with_freeze_before(frames=5, threshold=0.98, timeout=8.0)
        )
        result = lifecycle.run(context)
    """

    def __init__(self, controller=None, name: str = ""):
        self._name = name
        self._controller = controller
        self._action_fn: Callable | None = None
        self._config: dict = {}

    def with_name(self, name: str) -> "NodeLifecycle":
        self._name = name
        return self

    def with_pre_delay(self, ms: int) -> "NodeLifecycle":
        self._config["preDelay"] = ms
        return self

    def with_post_delay(self, ms: int) -> "NodeLifecycle":
        self._config["postDelay"] = ms
        return self

    def with_action(self, action_fn: Callable) -> "NodeLifecycle":
        self._action_fn = action_fn
        return self

    def with_freeze_before(
        self,
        enabled: bool = True,
        frames: int = DEFAULT_FREEZE_FRAMES,
        threshold: float = DEFAULT_FREEZE_THRESHOLD,
        timeout: float = 10.0,
    ) -> "NodeLifecycle":
        self._config["freeze_before"] = enabled
        if frames != DEFAULT_FREEZE_FRAMES:
            self._config["freeze_frames"] = frames
        if threshold != DEFAULT_FREEZE_THRESHOLD:
            self._config["freeze_threshold"] = threshold
        if timeout != 10.0:
            self._config["freeze_timeout"] = timeout
        return self

    def with_freeze_after(
        self,
        enabled: bool = True,
        frames: int = DEFAULT_FREEZE_FRAMES,
        threshold: float = DEFAULT_FREEZE_THRESHOLD,
        timeout: float = 10.0,
    ) -> "NodeLifecycle":
        self._config["freeze_after"] = enabled
        if frames != DEFAULT_FREEZE_FRAMES:
            self._config["freeze_frames"] = frames
        if threshold != DEFAULT_FREEZE_THRESHOLD:
            self._config["freeze_threshold"] = threshold
        if timeout != 10.0:
            self._config["freeze_timeout"] = timeout
        return self

    def build(self) -> Node:
        """构建 Node 实例。"""
        return Node(
            name=self._name,
            action_fn=self._action_fn,
            config=self._config,
            controller=self._controller,
        )

    def run(self, context: dict | None = None) -> NodeResult:
        """构建并立即执行。"""
        node = self.build()
        return node.execute(context)
