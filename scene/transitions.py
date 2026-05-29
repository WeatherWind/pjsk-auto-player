"""状态机转换规则 —— 定义游戏场景间的合法转换及权重。"""

import logging
from typing import Optional

from .states import GameScene, SceneTask

logger = logging.getLogger("pjsk_scene.transitions")


class SceneTransitions:
    """场景状态机转换规则。

    定义场景间的合法转换路径及其默认权重。
    支持回调注册（场景变化时通知）。
    """

    # 合法转换矩阵: {from_scene -> {to_scene: weight}}
    # weight 越高表示该转换越"自然"/期望
    ALLOWED_TRANSITIONS: dict[GameScene, dict[GameScene, float]] = {
        GameScene.LOADING: {
            GameScene.GAME: 0.8,
            GameScene.MENU: 0.8,
            GameScene.LOADING: 0.5,
            GameScene.UNKNOWN: 0.3,
        },
        GameScene.MENU: {
            GameScene.GAME: 1.0,       # 选歌 → 进游戏
            GameScene.MENU: 0.9,       # 停留在菜单
            GameScene.LOADING: 0.7,    # 菜单 → 加载
            GameScene.UNKNOWN: 0.2,
        },
        GameScene.GAME: {
            GameScene.RESULT: 1.0,     # 执行结束 → 结算
            GameScene.GAME: 0.9,       # 继续执行
            GameScene.UNKNOWN: 0.2,
        },
        GameScene.RESULT: {
            GameScene.MENU: 1.0,       # 结算 → 返回菜单
            GameScene.RESULT: 0.8,     # 停留在结算
            GameScene.LOADING: 0.5,
            GameScene.UNKNOWN: 0.2,
        },
        GameScene.UNKNOWN: {
            GameScene.LOADING: 0.5,
            GameScene.MENU: 0.4,
            GameScene.UNKNOWN: 0.3,
        },
    }

    def __init__(self) -> None:
        self._current: GameScene = GameScene.UNKNOWN
        self._previous: Optional[GameScene] = None
        self._callbacks: list = []

    @property
    def current(self) -> GameScene:
        """当前场景。"""
        return self._current

    @property
    def previous(self) -> Optional[GameScene]:
        """上一场景。"""
        return self._previous

    @property
    def just_changed(self) -> bool:
        """最近一次 transition() 是否发生了场景变化。"""
        return self._previous != self._current

    def register_callback(self, callback) -> None:
        """注册场景变化回调。

        Args:
            callback: callable(old: GameScene, new: GameScene, task: SceneTask)
        """
        self._callbacks.append(callback)

    def transition(
        self, detected: GameScene, confidence: float = 1.0,
        hysteresis_count: int = 2,
    ) -> "SceneTransitions":
        """尝试转换到检测到的场景。

        Args:
            detected: 检测到的场景
            confidence: 检测置信度 (0~1)
            hysteresis_count: 滞回计数 — 连续多少次检测到同一场景才切换
                              防止单帧误检导致抖动

        Returns:
            self (链式调用)
        """
        # --- 置信度门限 ---
        if confidence < 0.3:
            return self

        # --- 检查是否合法转换 ---
        allowed = self.ALLOWED_TRANSITIONS.get(self._current, {})
        weight = allowed.get(detected, 0.0)

        if weight <= 0 and detected != self._current:
            logger.debug(
                f"非法转换: {self._current.value} -> {detected.value}, 忽略"
            )
            return self

        # --- 滞回计数器 ---
        if not hasattr(self, "_hysteresis"):
            self._hysteresis: dict[GameScene, int] = {}

        if detected == self._current:
            self._hysteresis[detected] = 0
            return self

        self._hysteresis[detected] = self._hysteresis.get(detected, 0) + 1
        if self._hysteresis[detected] < hysteresis_count:
            return self

        # --- 执行转换 ---
        self._hysteresis[detected] = 0
        old = self._current
        self._previous = old
        self._current = detected

        task = self._scene_to_task(detected)

        logger.info(
            f"场景切换: {old.value} -> {detected.value} "
            f"(conf={confidence:.2f}, weight={weight:.1f}, "
            f"task={task.value})"
        )

        for cb in self._callbacks:
            try:
                cb(old, detected, task)
            except Exception as e:
                logger.exception(f"回调异常: {e}")

        return self

    def reset(self, scene: GameScene = GameScene.UNKNOWN) -> None:
        """重置状态机到指定场景。"""
        self._previous = self._current
        self._current = scene
        if hasattr(self, "_hysteresis"):
            self._hysteresis.clear()

    def get_current_task(self) -> SceneTask:
        """获取当前场景对应的默认任务。"""
        return self._scene_to_task(self._current)

    @staticmethod
    def _scene_to_task(scene: GameScene) -> SceneTask:
        """场景 -> 默认任务映射。"""
        mapping: dict[GameScene, SceneTask] = {
            GameScene.GAME: SceneTask.PLAY_AUTO,
            GameScene.RESULT: SceneTask.READ_SCORE,
            GameScene.MENU: SceneTask.SELECT_SONG,
            GameScene.LOADING: SceneTask.WAIT,
            GameScene.UNKNOWN: SceneTask.DIAGNOSE,
        }
        return mapping.get(scene, SceneTask.DIAGNOSE)
