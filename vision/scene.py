"""场景检测器 —— 多算法融合检测。

整合模板匹配、OCR、颜色检测、亮度分析等多种视觉算法，
对游戏画面进行多维度综合分析，输出联合检测结果。
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from scene.classifier import SceneClassifier, SceneResult
from scene.states import GameScene, SceneTask
from .matcher import TemplateMatcher, MatchResult
from .ocr import OcrReader, OcrResult
from .color import ColorDetector, ColorRange, ColorDetectionResult

logger = logging.getLogger("pjsk_vision.scene")


@dataclass
class DetectionResult:
    """多算法融合检测结果。"""
    scene: GameScene                    # 最终场景判断
    task: SceneTask                     # 对应任务
    confidence: float                   # 总体置信度

    # 各子系统结果
    scene_classifier: Optional[SceneResult] = None
    matches: list[MatchResult] = field(default_factory=list)
    ocr: Optional[OcrResult] = None
    colors: dict[str, ColorDetectionResult] = field(default_factory=dict)

    # 原始帧元数据
    frame_w: int = 0
    frame_h: int = 0
    timestamp: float = 0.0


class SceneDetector:
    """多算法融合场景检测器。

    整合场景分类器、模板匹配器、OCR 阅读器、颜色检测器，
    对画面进行全方位分析。

    用法:
        detector = SceneDetector()
        result = detector.detect(frame)
        if result.scene == GameScene.GAME:
            print(f"打歌中 (conf={result.confidence:.2f})")
            for match in result.matches:
                print(f"  匹配到: {match.name}")
    """

    def __init__(
        self,
        classifier: Optional[SceneClassifier] = None,
        matcher: Optional[TemplateMatcher] = None,
        ocr: Optional[OcrReader] = None,
        color: Optional[ColorDetector] = None,
    ) -> None:
        """
        Args:
            classifier: 场景分类器 (Scene 模块)
            matcher: 模板匹配器 (Vision 模块)
            ocr: OCR 阅读器 (Vision 模块)
            color: 颜色检测器 (Vision 模块)
        """
        self.classifier = classifier or SceneClassifier()
        self.matcher = matcher or TemplateMatcher()
        self.ocr = ocr or OcrReader()
        self.color = color or ColorDetector()

        # 注册默认颜色检测目标
        self._default_color_ranges: list[ColorRange] = [
            ColorRange.hsv_white(),
            ColorRange.hsv_blue(),
            ColorRange.hsv_yellow(),
        ]

        logger.info(
            "SceneDetector 已初始化: "
            f"classifier={type(self.classifier).__name__}, "
            f"matcher={type(self.matcher).__name__}, "
            f"ocr={type(self.ocr).__name__}, "
            f"color={type(self.color).__name__}"
        )

    # ── 核心检测 ──────────────────────────────────────

    def detect(
        self, frame: np.ndarray,
        enable_ocr: bool = False,
        enable_color: bool = True,
        enable_matcher: bool = True,
        template_names: Optional[list[str]] = None,
        color_ranges: Optional[list[ColorRange]] = None,
    ) -> DetectionResult:
        """多算法融合检测一帧画面。

        Args:
            frame: BGR numpy array
            enable_ocr: 是否启用 OCR (较慢)
            enable_color: 是否启用颜色检测
            enable_matcher: 是否启用模板匹配
            template_names: 模板名称过滤列表
            color_ranges: 颜色检测范围列表

        Returns:
            DetectionResult 包含所有子系统的检测结果
        """
        if frame is None or frame.size == 0:
            return DetectionResult(
                scene=GameScene.UNKNOWN,
                task=SceneTask.DIAGNOSE,
                confidence=0.0,
            )

        h, w = frame.shape[:2]
        import time
        now = time.time()

        # 1. 场景分类 (最快, 总是启用)
        scene_result = self.classifier.classify(frame)
        scene = GameScene(scene_result.scene_name)
        task = SceneTask(scene_result.task_name)

        # 2. 模板匹配 (可选)
        matches: list[MatchResult] = []
        if enable_matcher:
            try:
                matches = self.matcher.match(
                    frame, template_name=template_names[0] if template_names else None
                )
            except Exception as e:
                logger.debug(f"模板匹配异常: {e}")

            # 如果模板匹配到特定按钮, 考虑覆盖场景分类结果
            if matches and not template_names:
                # 高置信度模板匹配可以覆盖场景分类
                best_match = matches[0]
                match_scene = self._infer_scene_from_template(best_match.name)
                if match_scene and best_match.confidence > 0.9:
                    scene = match_scene
                    task = self._scene_to_task(scene)

        # 3. OCR (可选, 较慢)
        ocr_result: Optional[OcrResult] = None
        if enable_ocr:
            try:
                if scene == GameScene.RESULT:
                    score = self.ocr.read_score(frame)
                    if score is not None:
                        ocr_result = OcrResult(str(score), 1.0, engine="score")
                else:
                    ocr_result = self.ocr.read(frame)
            except Exception as e:
                logger.debug(f"OCR 异常: {e}")

        # 4. 颜色检测 (可选)
        color_results: dict[str, ColorDetectionResult] = {}
        if enable_color:
            try:
                ranges = color_ranges or self._default_color_ranges
                color_results = self.color.detect_all(frame, ranges)
            except Exception as e:
                logger.debug(f"颜色检测异常: {e}")

            # 颜色结果辅助场景确认
            if scene == GameScene.LOADING:
                # 加载画面: 白色和蓝色占比应极低
                white_ratio = color_results.get("hsv_white", ColorDetectionResult(False, 0, 0)).ratio
                if white_ratio > 0.1:
                    # 有白色元素, 可能不是加载
                    scene = GameScene.UNKNOWN

        return DetectionResult(
            scene=scene,
            task=task,
            confidence=scene_result.confidence,
            scene_classifier=scene_result,
            matches=matches,
            ocr=ocr_result,
            colors=color_results,
            frame_w=w,
            frame_h=h,
            timestamp=now,
        )

    # ── 便捷方法 ──────────────────────────────────────

    def is_game(self, frame: np.ndarray) -> bool:
        """快速判断是否在打歌中。"""
        return self.detect(frame, enable_ocr=False, enable_color=False).scene == GameScene.GAME

    def is_result(self, frame: np.ndarray) -> bool:
        """快速判断是否是结算画面。"""
        return self.detect(frame, enable_ocr=False, enable_color=False).scene == GameScene.RESULT

    def is_menu(self, frame: np.ndarray) -> bool:
        """快速判断是否是菜单/选歌画面。"""
        return self.detect(frame, enable_ocr=False, enable_color=False).scene == GameScene.MENU

    def detailed_analysis(
        self, frame: np.ndarray,
    ) -> DetectionResult:
        """完整分析 (启用所有子系统)。"""
        return self.detect(
            frame,
            enable_ocr=True,
            enable_color=True,
            enable_matcher=True,
        )

    def match_and_read(
        self, frame: np.ndarray,
        template_name: str,
        ocr_roi: Optional[tuple[float, float, float, float]] = None,
    ) -> tuple[Optional[MatchResult], Optional[OcrResult]]:
        """模板匹配后在匹配区域执行 OCR。

        Args:
            frame: BGR numpy array
            template_name: 模板名称
            ocr_roi: OCR ROI 比例

        Returns:
            (match_result, ocr_result)
        """
        match = self.matcher.match_first(frame, template_name=template_name)
        if match is None:
            return None, None

        if ocr_roi is not None:
            # 在匹配区域附近执行 OCR
            h, w = frame.shape[:2]
            x1 = int(w * ocr_roi[0])
            y1 = int(h * ocr_roi[1])
            x2 = int(w * ocr_roi[2])
            y2 = int(h * ocr_roi[3])
            roi_frame = frame[y1:y2, x1:x2]
            ocr_result = self.ocr.read(roi_frame)
            return match, ocr_result

        return match, None

    # ── 内部方法 ──────────────────────────────────────

    @staticmethod
    def _infer_scene_from_template(template_name: str) -> Optional[GameScene]:
        """根据模板名称推断场景。"""
        name_lower = template_name.lower()
        if any(kw in name_lower for kw in ("btn_start", "start", "play", "select")):
            return GameScene.MENU
        if any(kw in name_lower for kw in ("result", "score", "clear")):
            return GameScene.RESULT
        if any(kw in name_lower for kw in ("loading", "now_loading")):
            return GameScene.LOADING
        if any(kw in name_lower for kw in ("note", "fever", "skill")):
            return GameScene.GAME
        return None

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
