"""场景分类器 —— 多算法并行检测 + 加权投票。

基于 ALAS (Azur Lane Auto Sweep) 启发:
  1. 多个轻量级检测器并行运行
  2. 每个检测器对每个场景投票
  3. 加权投票决定最终场景

检测器列表:
  - TemplateMatcher: 模板匹配 (需预注册模板)
  - BrightnessDetector: 整体亮度 + 区域亮度分析
  - ColorDetector: 区域颜色直方图分析
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from .states import GameScene, SceneTask

logger = logging.getLogger("pjsk_scene.classifier")


# ====================================================================
# 结果类型
# ====================================================================

@dataclass
class AlgorithmVote:
    """单个算法的投票结果。"""
    scene: GameScene
    confidence: float
    weight: float = 1.0

    @property
    def weighted_confidence(self) -> float:
        return self.confidence * self.weight


@dataclass
class SceneResult:
    """场景分类结果。"""
    scene_name: str                        # 场景名称 (GameScene.value)
    task_name: str                         # 默认任务名称 (SceneTask.value)
    confidence: float                      # 总体置信度 (0~1)
    votes: list[AlgorithmVote] = field(default_factory=list)  # 各算法投票
    raw: dict = field(default_factory=dict)                    # 原始检测数据

    @classmethod
    def unknown(cls) -> "SceneResult":
        return cls(
            scene_name=GameScene.UNKNOWN.value,
            task_name=SceneTask.DIAGNOSE.value,
            confidence=0.0,
        )


# ====================================================================
# 检测器基类
# ====================================================================

class BaseDetector:
    """检测器基类。"""
    name: str = "base"

    def detect(self, frame: np.ndarray) -> AlgorithmVote:
        raise NotImplementedError


# ====================================================================
# 亮度检测器
# ====================================================================

class BrightnessDetector(BaseDetector):
    """基于整体/区域亮度的场景检测。

    检测策略:
      - overall_mean < 10   → LOADING (全黑)
      - overall_mean > 140  → RESULT (高亮)
      - 判定线有亮色活动    → GAME
      - 顶部 UI 边缘丰富    → MENU
    """

    name = "brightness"

    def __init__(self, judgment_line_y: float = 0.82) -> None:
        self.judgment_line_y = judgment_line_y

    def detect(self, frame: np.ndarray) -> AlgorithmVote:
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        overall_mean = float(np.mean(gray))

        # 1. LOADING: 全黑或接近全黑
        if overall_mean < 10:
            return AlgorithmVote(
                scene=GameScene.LOADING,
                confidence=max(0.0, 1.0 - overall_mean / 10.0),
                weight=1.2,
            )

        # 2. TRANSITION-like 暗色 (50 < mean < 80)
        if overall_mean < 60 and overall_mean >= 10:
            return AlgorithmVote(
                scene=GameScene.LOADING,
                confidence=0.5,
                weight=0.8,
            )

        judgment_y = int(self.judgment_line_y * h)

        # 3. RESULT: 整体高亮且判定线平滑
        if overall_mean > 140:
            j_roi = gray[
                max(0, judgment_y - 30):min(h, judgment_y + 30),
                max(0, w // 4):min(w, w * 3 // 4)
            ]
            if j_roi.size > 0:
                j_std = float(np.std(j_roi))
                if j_std < 20:
                    conf = min(1.0, (overall_mean - 140) / 60.0 + 0.5)
                    return AlgorithmVote(
                        scene=GameScene.RESULT,
                        confidence=conf,
                        weight=1.0,
                    )

        # 4. GAME: 判定线区域有亮色活动
        j_roi = gray[
            max(0, judgment_y - 20):min(h, judgment_y + 20),
            max(0, w // 4):min(w, w * 3 // 4)
        ]
        if j_roi.size > 0:
            bright_ratio = float(np.mean(j_roi > 150))
            if bright_ratio > 0.03:
                conf = min(1.0, bright_ratio * 5.0)
                return AlgorithmVote(
                    scene=GameScene.GAME,
                    confidence=conf,
                    weight=1.2,
                )

        # 5. MENU: 顶部 UI 元素丰富 (高的标准差)
        top_roi = gray[0:int(h * 0.1), int(w * 0.1):int(w * 0.9)]
        if top_roi.size > 0:
            top_std = float(np.std(top_roi))
            if top_std > 30:
                conf = min(1.0, top_std / 60.0)
                return AlgorithmVote(
                    scene=GameScene.MENU,
                    confidence=conf,
                    weight=0.8,
                )

        # 6. 回退: 倾向于 UNKNOWN
        return AlgorithmVote(
            scene=GameScene.UNKNOWN,
            confidence=0.3,
            weight=0.5,
        )


# ====================================================================
# 颜色检测器 (简单区域颜色分析)
# ====================================================================

class ColorDetector(BaseDetector):
    """基于区域颜色分布的场景检测。

    使用 HSV 颜色直方图分析画面色温。
      - 结算画面: 白色/浅色占比高
      - 游戏画面: 彩色 note + 黑色背景
      - 菜单画面: 蓝色/紫色 UI 色调
      - 加载画面: 黑色/深灰色
    """

    name = "color"

    def detect(self, frame: np.ndarray) -> AlgorithmVote:
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # 中央 60% 区域
        cx1, cy1 = int(w * 0.2), int(h * 0.2)
        cx2, cy2 = int(w * 0.8), int(h * 0.8)
        center = hsv[cy1:cy2, cx1:cx2]

        if center.size == 0:
            return AlgorithmVote(GameScene.UNKNOWN, 0.0, 0.5)

        # 计算颜色占比
        total_pixels = center.shape[0] * center.shape[1] + 1e-6

        # 黑色: V < 30
        black_mask = center[:, :, 2] < 30
        black_ratio = float(np.sum(black_mask)) / total_pixels

        # 白色: V > 200, S < 30
        white_mask = (center[:, :, 2] > 200) & (center[:, :, 1] < 30)
        white_ratio = float(np.sum(white_mask)) / total_pixels

        # 亮色: S > 80, V > 100
        color_mask = (center[:, :, 1] > 80) & (center[:, :, 2] > 100)
        color_ratio = float(np.sum(color_mask)) / total_pixels

        # 蓝色调: H 90-130
        blue_mask = (center[:, :, 0] > 90) & (center[:, :, 0] < 130) & \
                    (center[:, :, 1] > 40) & (center[:, :, 2] > 80)
        blue_ratio = float(np.sum(blue_mask)) / total_pixels

        # --- 决策 ---
        # LOADING: 黑色占比 > 80%
        if black_ratio > 0.8:
            return AlgorithmVote(
                GameScene.LOADING,
                min(1.0, black_ratio),
                weight=0.8,
            )

        # RESULT: 白色占比 > 30%
        if white_ratio > 0.30:
            return AlgorithmVote(
                GameScene.RESULT,
                min(1.0, white_ratio * 2.0),
                weight=0.9,
            )

        # GAME: 亮色 note 占比适中有大量黑色背景
        if color_ratio > 0.02 and black_ratio > 0.4:
            return AlgorithmVote(
                GameScene.GAME,
                min(1.0, color_ratio * 5.0 + black_ratio * 0.5),
                weight=1.0,
            )

        # MENU: 蓝色 UI 或白色为主
        if blue_ratio > 0.05 or white_ratio > 0.10:
            return AlgorithmVote(
                GameScene.MENU,
                min(1.0, max(blue_ratio, white_ratio) * 3.0),
                weight=0.8,
            )

        # 回退: 黑色/灰色混杂 → UNKNOWN
        return AlgorithmVote(GameScene.UNKNOWN, 0.2, 0.5)


# ====================================================================
# 模板匹配检测器 (轻量)
# ====================================================================

class TemplateDetector(BaseDetector):
    """基于模板匹配的场景检测。

    需要预先注册模板图像。
    每个模板关联一个场景, 匹配成功则投票给该场景。
    """

    name = "template"

    def __init__(self) -> None:
        self._templates: dict[str, list[tuple[np.ndarray, GameScene, float, float]]] = {}
        # name -> [(template_img, scene, threshold, roi_ratio), ...]

    def register(
        self, name: str, template: np.ndarray, scene: GameScene,
        threshold: float = 0.8, roi_ratio: float = 1.0,
    ) -> None:
        """注册一个模板。

        Args:
            name: 模板名称
            template: 模板图像 (灰度或彩色)
            scene: 匹配上时投票给哪个场景
            threshold: 匹配阈值 (0~1)
            roi_ratio: 搜索区域占屏幕的比例 (1.0 = 全屏)
        """
        if len(template.shape) == 3:
            template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        self._templates.setdefault(name, []).append(
            (template, scene, threshold, roi_ratio)
        )

    def detect(self, frame: np.ndarray) -> AlgorithmVote:
        if not self._templates:
            return AlgorithmVote(GameScene.UNKNOWN, 0.0, 0.0)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]

        best_scene = GameScene.UNKNOWN
        best_conf = 0.0

        for name, templates in self._templates.items():
            for tmpl, scene, threshold, roi_ratio in templates:
                th, tw = tmpl.shape[:2]
                if th > h or tw > w:
                    continue

                # ROI 裁剪
                if roi_ratio < 1.0:
                    margin_w = int(w * (1 - roi_ratio) / 2)
                    margin_h = int(h * (1 - roi_ratio) / 2)
                    search_roi = gray[margin_h:h - margin_h, margin_w:w - margin_w]
                    if search_roi.size == 0:
                        continue
                else:
                    search_roi = gray

                result = cv2.matchTemplate(search_roi, tmpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)

                if max_val >= threshold and max_val > best_conf:
                    best_conf = float(max_val)
                    best_scene = scene

        if best_conf > 0:
            return AlgorithmVote(best_scene, best_conf, weight=1.5)

        return AlgorithmVote(GameScene.UNKNOWN, 0.0, 0.0)


# ====================================================================
# SceneClassifier (主入口)
# ====================================================================

class SceneClassifier:
    """多算法场景分类器。

    并行运行多个检测器, 收集投票, 加权投票决定最终场景。

    用法:
        classifier = SceneClassifier()
        result = classifier.classify(frame)
        print(result.scene_name, result.task_name, result.confidence)
    """

    def __init__(self) -> None:
        self._detectors: list[BaseDetector] = [
            BrightnessDetector(),
            ColorDetector(),
            TemplateDetector(),
        ]

        # 缓存
        self._last_frame_hash = 0
        self._last_result: Optional[SceneResult] = None
        self._last_time = 0.0
        self._cache_ttl = 0.05  # 50ms

        # 场景权重重映射 (用于最终投票)
        # 某些场景更难被误判, 赋予更高权重
        self._scene_weights: dict[GameScene, float] = {
            GameScene.LOADING: 1.0,
            GameScene.RESULT: 1.0,
            GameScene.MENU: 1.0,
            GameScene.GAME: 1.0,
            GameScene.UNKNOWN: 0.5,
        }

        logger.info(
            f"SceneClassifier 已初始化, "
            f"detectors={[d.name for d in self._detectors]}"
        )

    @property
    def template_detector(self) -> TemplateDetector:
        """获取模板检测器 (用于注册模板)。"""
        for d in self._detectors:
            if isinstance(d, TemplateDetector):
                return d
        raise RuntimeError("TemplateDetector not found")

    def register_template(
        self, name: str, template: np.ndarray, scene: GameScene,
        threshold: float = 0.8, roi_ratio: float = 1.0,
    ) -> None:
        """便捷方法: 注册模板到 TemplateDetector。"""
        self.template_detector.register(name, template, scene, threshold, roi_ratio)

    def classify(self, frame: np.ndarray) -> SceneResult:
        """对一帧画面执行多算法场景分类。

        Args:
            frame: BGR numpy array

        Returns:
            SceneResult 包含最终场景、任务和置信度
        """
        if frame is None:
            return SceneResult.unknown()

        # --- 缓存: 相同帧直接复用 ---
        now = time.time()
        if now - self._last_time < self._cache_ttl and self._last_result is not None:
            return self._last_result

        # 快速帧哈希
        small = cv2.resize(frame, (8, 8))
        frame_hash = hash(small.tobytes())
        if frame_hash == self._last_frame_hash and self._last_result is not None:
            return self._last_result
        self._last_frame_hash = frame_hash
        self._last_time = now

        # --- 收集所有检测器投票 ---
        votes: list[AlgorithmVote] = []
        for detector in self._detectors:
            try:
                vote = detector.detect(frame)
                votes.append(vote)
            except Exception as e:
                logger.warning(f"检测器 {detector.name} 异常: {e}")

        # --- 加权投票 ---
        score_map: dict[GameScene, float] = {s: 0.0 for s in GameScene}
        total_weight = 0.0

        for vote in votes:
            wc = vote.weighted_confidence
            score_map[vote.scene] += wc
            total_weight += vote.weight if vote.confidence > 0 else 0

        # 应用场景权重
        for scene in GameScene:
            score_map[scene] *= self._scene_weights.get(scene, 1.0)

        # 选择最高分的场景
        if total_weight > 0:
            best_scene = max(score_map, key=score_map.get)  # type: ignore
            best_score = score_map[best_scene]
            # 归一化置信度
            max_possible = sum(
                v.weight * self._scene_weights.get(v.scene, 1.0)
                for v in votes if v.confidence > 0
            )
            confidence = min(1.0, best_score / max_possible) if max_possible > 0 else 0.0
        else:
            best_scene = GameScene.UNKNOWN
            confidence = 0.0

        # --- 构建结果 ---
        result = SceneResult(
            scene_name=best_scene.value,
            task_name=self._scene_to_task(best_scene).value,
            confidence=confidence,
            votes=votes,
            raw={d.name: v for d, v in zip(self._detectors, votes)},
        )

        self._last_result = result
        logger.debug(
            f"分类: {result.scene_name} "
            f"(conf={result.confidence:.3f}, "
            f"votes={[(v.scene.value, f'{v.confidence:.2f}') for v in votes]})"
        )

        return result

    @staticmethod
    def _scene_to_task(scene: GameScene) -> SceneTask:
        mapping = {
            GameScene.GAME: SceneTask.PLAY_AUTO,
            GameScene.RESULT: SceneTask.READ_SCORE,
            GameScene.MENU: SceneTask.SELECT_SONG,
            GameScene.LOADING: SceneTask.WAIT,
            GameScene.UNKNOWN: SceneTask.DIAGNOSE,
        }
        return mapping.get(scene, SceneTask.DIAGNOSE)

    def is_game(self, frame: np.ndarray) -> bool:
        return self.classify(frame).scene_name == GameScene.GAME.value

    def is_result(self, frame: np.ndarray) -> bool:
        return self.classify(frame).scene_name == GameScene.RESULT.value

    def is_menu(self, frame: np.ndarray) -> bool:
        return self.classify(frame).scene_name == GameScene.MENU.value

    def is_loading(self, frame: np.ndarray) -> bool:
        return self.classify(frame).scene_name == GameScene.LOADING.value
