"""
屏幕分析器 —— 通过 OpenCV 分析 PJSK 游戏画面, 检测:
- 判定线上的 note (tap / flick / hold)
- 判定线上方区域 (用于预测引擎提前发现 note)
- 游戏状态 (选歌 / 执行中 / 结算)
- 实时校准辅助
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from scene_classifier import SceneClassifier, SceneType

logger = logging.getLogger("pjsk_analyzer")


@dataclass
class NoteEvent:
    """检测到的 Note 事件。"""
    lane: int          # 轨道编号 (0-5, 0=左1, 1=左2, 2=左3, 3=右1, 4=右2, 5=右3)
    x: int             # 像素坐标 X
    y: int             # 像素坐标 Y
    note_type: str = "tap"   # "tap", "flick", "hold"
    confidence: float = 0.0  # 置信度 (0~1)
    flick_direction: str = ""  # "up", "down", "left", "right" (flick 时)
    timestamp: float = 0.0   # 检测时间戳
    # 预测引擎用
    y_roi_top: int = 0       # ROI 顶部 Y (所处检测区域的上边界)
    velocity_px_per_s: float = 0.0  # 预测的滚动速度 (像素/秒)


@dataclass
class GameState:
    """游戏画面状态。"""
    in_game: bool = False      # 是否在执行中
    in_result: bool = False    # 是否在结算画面
    in_menu: bool = False      # 是否在菜单/选歌画面
    detected_notes: list[NoteEvent] = field(default_factory=list)
    # 判定线上方区域检测到的 note (用于预测)
    predicted_notes: list[NoteEvent] = field(default_factory=list)
    combo: int = 0             # 当前 combo (实验性)
    frame_count: int = 0       # 处理帧计数


class ScreenAnalyzer:
    """
    屏幕分析器: 读取手机截屏, 检测 PJSK 画面中的 note。

    改进点:
      1. 判定线上方区域检测 (提前发现 note)
      2. 基于模板匹配的 flick 方向检测
      3. 更鲁棒的 hold 轨迹识别
    """

    def __init__(self, config: dict):
        s = config["screen"]
        d = config["detection"]
        self.screen_w = s["width"]
        self.screen_h = s["height"]
        self.cfg = config

        # 将相对坐标转为像素坐标
        self.judgment_y = int(s["judgment_line_y"] * self.screen_h)
        self.left_lanes = [int(x * self.screen_w) for x in s["left_lanes"]]
        self.right_lanes = [int(x * self.screen_w) for x in s["right_lanes"]]
        self.all_lanes = self.left_lanes + self.right_lanes
        self.detect_radius = s.get("detect_radius", 30)

        # 判定线上方检测区域 (用于提前检测 note)
        detect_ratio = s.get("note_detect_region_ratio", 0.35)
        self.note_detect_top = int((s["judgment_line_y"] - detect_ratio) * self.screen_h)
        self.note_detect_top = max(0, self.note_detect_top)

        # 检测参数
        self.bright_thresh = d["brightness"]["threshold"]
        self.min_area = d["brightness"]["min_contour_area"]
        self.max_area = d["brightness"]["max_contour_area"]

        # 颜色范围
        self.white_lower = np.array(d["color"]["white_range"][:3])
        self.white_upper = np.array(d["color"]["white_range"][3:])
        self.color_lower = np.array(d["color"]["color_range"][:3])
        self.color_upper = np.array(d["color"]["color_range"][3:])

        # 忽略区域
        self.ignore_masks = []
        for region in d.get("ignore_regions", []):
            x1 = int(region[0] * self.screen_w)
            y1 = int(region[1] * self.screen_h)
            x2 = int(region[2] * self.screen_w)
            y2 = int(region[3] * self.screen_h)
            self.ignore_masks.append((x1, y1, x2, y2))

        # 历史状态 (用于滤波)
        self._prev_active = set()
        self._hold_count = {}
        self.frame_count = 0

        # 用于预测引擎: 历史 note 位置追踪
        self._note_tracks = {}  # lane -> [(y, timestamp), ...]

        # 快速场景分类器 (ALAS 启发)
        self._scene_classifier = SceneClassifier(config)
        self._last_scene = SceneType.UNKNOWN

        # 画面捕获优化器
        self._capture_opt = None
        try:
            from capture_optimizer import CaptureOptimizer
            self._capture_opt = CaptureOptimizer(config)
        except ImportError:
            pass

        # 调试输出
        self.debug_dir = config.get("debug", {}).get("debug_dir", "debug_output")
        self.save_debug = config.get("debug", {}).get("save_debug_frames", False)
        self.show_preview = config.get("debug", {}).get("show_preview", False)

    # ──────────────────────────────────────────
    # 核心检测
    # ──────────────────────────────────────────

    def analyze(self, frame: np.ndarray) -> GameState:
        """
        分析一帧画面, 返回 GameState。

        检测两处:
          1. 判定线区域 -> 实时触发 (tap/flick/hold)
          2. 判定线上方 -> 用于预测引擎提前发现 note
        """
        self.frame_count += 1
        state = GameState(frame_count=self.frame_count)

        if frame is None:
            return state

        h, w = frame.shape[:2]
        if w != self.screen_w or h != self.screen_h:
            self.screen_w = w
            self.screen_h = h
            self._recalc_coords()

        # 快速场景分类 (<1ms) — 作为预过滤器
        scene = self._scene_classifier.classify(frame)
        self._last_scene = scene

        if scene == SceneType.LOADING or scene == SceneType.TRANSITION:
            # 加载/过渡: 快速返回, 不做 note 检测
            return state

        if scene == SceneType.RESULT:
            state.in_result = True
            return state

        if scene == SceneType.MENU:
            state.in_menu = True
            return state

        if scene != SceneType.GAME:
            # UNKNOWN: 使用旧方法作为备选
            game = self._is_game_screen(frame)
            if not game:
                state.in_menu = True
                return state

        state.in_game = True
        now = time.time()

        # ── [1] 判定线区域检测 (实时触发) ──
        for idx, lane_x in enumerate(self.all_lanes):
            active, note_type, confidence, details = self._detect_note_at(
                frame, lane_x, self.judgment_y
            )
            if active:
                event = NoteEvent(
                    lane=idx, x=lane_x, y=self.judgment_y,
                    note_type=note_type, confidence=confidence,
                    timestamp=now,
                )
                if note_type == "flick":
                    event.flick_direction = self._detect_flick_direction(
                        frame, lane_x, self.judgment_y
                    )
                state.detected_notes.append(event)

        self._update_hold_state(state)

        # ── [2] 判定线上方区域检测 (用于预测) ──
        predicted = self._detect_notes_above_judgment(frame, now)
        state.predicted_notes = predicted

        # 可选: 保存调试截图
        if self.save_debug:
            self._save_debug_frame(frame, state)

        if self.show_preview:
            self._show_preview(frame, state)

        return state

    def _recalc_coords(self):
        """根据实际分辨率重算坐标。"""
        s = self.cfg["screen"]
        self.judgment_y = int(s["judgment_line_y"] * self.screen_h)
        self.left_lanes = [int(x * self.screen_w) for x in s["left_lanes"]]
        self.right_lanes = [int(x * self.screen_w) for x in s["right_lanes"]]
        self.all_lanes = self.left_lanes + self.right_lanes

        detect_ratio = s.get("note_detect_region_ratio", 0.35)
        self.note_detect_top = int((s["judgment_line_y"] - detect_ratio) * self.screen_h)
        self.note_detect_top = max(0, self.note_detect_top)

        d = self.cfg["detection"]
        self.ignore_masks = []
        for region in d.get("ignore_regions", []):
            x1 = int(region[0] * self.screen_w)
            y1 = int(region[1] * self.screen_h)
            x2 = int(region[2] * self.screen_w)
            y2 = int(region[3] * self.screen_h)
            self.ignore_masks.append((x1, y1, x2, y2))

    # ──────────────────────────────────────────
    # 游戏画面检测
    # ──────────────────────────────────────────

    def _is_game_screen(self, frame: np.ndarray) -> bool:
        """判断当前画面是否为 PJSK 执行界面。"""
        h, w = frame.shape[:2]
        y_center = self.judgment_y
        roi = frame[
            max(0, y_center - 40):min(h, y_center + 40),
            max(0, w // 4):min(w, w * 3 // 4)
        ]
        if roi.size == 0:
            return False

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        bright_pixels = np.sum(gray > self.bright_thresh - 30)
        total_pixels = roi.shape[0] * roi.shape[1]
        bright_ratio = bright_pixels / total_pixels if total_pixels > 0 else 0
        return bright_ratio > 0.02

    def _is_result_screen(self, frame: np.ndarray) -> bool:
        """
        判断是否为 PJSK 结算画面。

        结算画面特征:
          - 整体偏亮 (白色/浅色背景)
          - 判定线区域没有 note 活动
          - 画面中央有大量白色/浅色像素
        """
        h, w = frame.shape[:2]

        # 中央区域: 取屏幕中央 60%x60%
        cx1, cy1 = int(w * 0.2), int(h * 0.2)
        cx2, cy2 = int(w * 0.8), int(h * 0.8)
        center = frame[cy1:cy2, cx1:cx2]
        if center.size == 0:
            return False

        gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
        mean_brightness = np.mean(gray)

        # 检查判定线区域 (应当没有 note 活动)
        jy = self.judgment_y
        j_roi = frame[
            max(0, jy - 30):min(h, jy + 30),
            max(0, w // 4):min(w, w * 3 // 4)
        ]
        j_gray = cv2.cvtColor(j_roi, cv2.COLOR_BGR2GRAY) if j_roi.size > 0 else gray[:1,:1]
        j_bright_ratio = np.mean(j_gray > self.bright_thresh - 30) if j_gray.size > 0 else 0

        # 结算画面: 整体亮 (mean_brightness > 120) 且判定线区域无 note 活动
        return mean_brightness > 120 and j_bright_ratio < 0.01

    # ──────────────────────────────────────────
    # 判定线上方区域检测 (预测引擎用)
    # ──────────────────────────────────────────

    def _detect_notes_above_judgment(
        self, frame: np.ndarray, now: float
    ) -> list[NoteEvent]:
        """
        检测判定线上方区域出现的 note。

        在判定线和 note_detect_top 之间扫描每个轨道,
        返回 detected notes (包含它们的 y 位置)。
        """
        events = []

        for idx, lane_x in enumerate(self.all_lanes):
            # 沿轨道扫描: 从判定线往上找第一个亮块
            y_found = self._scan_track_above(frame, lane_x)
            if y_found is not None:
                event = NoteEvent(
                    lane=idx, x=lane_x, y=y_found,
                    note_type="tap", confidence=0.5,
                    timestamp=now,
                    y_roi_top=self.note_detect_top,
                )
                events.append(event)

        return events

    def _scan_track_above(self, frame: np.ndarray, lane_x: int) -> Optional[int]:
        """
        沿轨道竖直扫描, 找判定线上方第一个亮块。

        向量化实现: 用 numpy 行均值替换 Python 逐行循环, 快 5-10x。

        Returns:
            找到的 Y 坐标 (像素), 或 None
        """
        h, w = frame.shape[:2]
        half_r = self.detect_radius // 2
        x1 = max(0, lane_x - half_r)
        x2 = min(w, lane_x + half_r)

        scan_start = max(0, self.note_detect_top)
        scan_end = max(1, self.judgment_y)

        if scan_start >= scan_end:
            return None

        # 截取轨道的竖直条带 (从 note_detect_top 到 judgment_y)
        strip = frame[scan_start:scan_end, x1:x2]
        if strip.size == 0:
            return None

        # 灰度化 (仅该区域, 避免全图转换)
        gray_strip = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)

        # 行均值 — O(n) 向量化操作
        row_scores = np.mean(gray_strip, axis=1)  # shape: (height,)

        # 找到所有超过阈值的行
        bright_mask = row_scores > self.bright_thresh
        bright_indices = np.where(bright_mask)[0]

        if len(bright_indices) == 0:
            return None

        # 返回最靠近判定线的 (距 judgment_y 最近的) 亮行
        # bright_indices 是相对于 strip 顶部 (note_detect_top) 的偏移
        best_local_y = bright_indices[-1]  # 越大的索引越靠近底部的判定线
        return scan_start + best_local_y

    # ──────────────────────────────────────────
    # Note 检测 (核心算法)
    # ──────────────────────────────────────────

    def _detect_note_at(
        self, frame: np.ndarray, lane_x: int, judgment_y: int
    ) -> tuple[bool, str, float, dict]:
        """在指定轨道位置检测是否有 note。"""
        h, w = frame.shape[:2]
        r = self.detect_radius

        x1 = max(0, lane_x - r)
        x2 = min(w, lane_x + r)
        y1 = max(0, judgment_y - r)
        y2 = min(h, judgment_y + r)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "tap", 0.0, {}

        for ix1, iy1, ix2, iy2 in self.ignore_masks:
            if (x1 >= ix1 and x2 <= ix2 and y1 >= iy1 and y2 <= iy2):
                return False, "tap", 0.0, {}

        method = self.cfg["detection"].get("method", "brightness")
        if method == "brightness":
            return self._detect_by_brightness(roi)
        else:
            return self._detect_by_color(roi)

    def _detect_by_brightness(
        self, roi: np.ndarray
    ) -> tuple[bool, str, float, dict]:
        """基于亮度的 note 检测。"""
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, self.bright_thresh, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(
            cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if self.min_area <= area <= self.max_area:
                mask = np.zeros_like(gray)
                cv2.drawContours(mask, [cnt], -1, 255, -1)
                brightness = cv2.mean(gray, mask=mask)[0]
                confidence = min(1.0, brightness / 255.0)

                _, (w_note, h_note), _ = cv2.minAreaRect(cnt)
                aspect = max(w_note, h_note) / (min(w_note, h_note) + 1e-6)

                # 改进的 note 类型判断:
                # 宽高比 > 2.5 = hold trail
                # 检测是否有"箭头突起" -> flick
                note_type = self._classify_note_type(cnt, roi)

                return True, note_type, confidence, {
                    "area": area, "aspect": aspect
                }

        return False, "tap", 0.0, {}

    def _classify_note_type(
        self, contour, roi: np.ndarray
    ) -> str:
        """
        改进的 note 类型分类:
        - 宽高比 > 2.5 → hold
        - 轮廓凸包有尖角突出 → flick
        - 其他 → tap
        """
        _, (w_note, h_note), _ = cv2.minAreaRect(contour)
        aspect = max(w_note, h_note) / (min(w_note, h_note) + 1e-6)

        if aspect > 2.5:
            return "hold"

        # 检查凸包缺陷 (flick 箭头)
        hull = cv2.convexHull(contour, returnPoints=False)
        if hull.size > 3 and len(contour) > 3:
            try:
                defects = cv2.convexityDefects(contour, hull)
                if defects is not None:
                    # 如果有显著的凸包缺陷 (箭头突起)
                    for i in range(defects.shape[0]):
                        _, _, far_dist, _ = defects[i, 0]
                        depth = far_dist / 256.0  # 归一化
                        if depth > 2.0:  # 显著的突起 -> flick
                            return "flick"
            except cv2.error:
                pass

        return "tap"

    def _detect_by_color(
        self, roi: np.ndarray
    ) -> tuple[bool, str, float, dict]:
        """基于颜色的 note 检测。"""
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        white_mask = cv2.inRange(hsv, self.white_lower, self.white_upper)
        color_mask = cv2.inRange(hsv, self.color_lower, self.color_upper)
        combined = cv2.bitwise_or(white_mask, color_mask)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cleaned = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(
            cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if self.min_area <= area <= self.max_area:
                _, (w_note, h_note), _ = cv2.minAreaRect(cnt)
                aspect = max(w_note, h_note) / (min(w_note, h_note) + 1e-6)
                note_type = self._classify_note_type(cnt, roi)

                mask = np.zeros_like(hsv[:, :, 1])
                cv2.drawContours(mask, [cnt], -1, 255, -1)
                mean_sat = cv2.mean(hsv, mask=mask)[1]
                confidence = min(1.0, mean_sat / 255.0 + 0.3)

                return True, note_type, confidence, {
                    "area": area, "aspect": aspect, "mean_saturation": mean_sat
                }

        return False, "tap", 0.0, {}

    # ──────────────────────────────────────────
    # Flick 方向检测
    # ──────────────────────────────────────────

    def _detect_flick_direction(
        self, frame: np.ndarray, lane_x: int, judgment_y: int
    ) -> str:
        """
        检测 flick note 的箭头方向。

        方法: 在 note 周围找最亮的梯度方向。
        向量化实现: 用 numpy 直方图替换 Python 像素循环。
        """
        h, w = frame.shape[:2]
        r = self.detect_radius * 2
        x1 = max(0, lane_x - r)
        x2 = min(w, lane_x + r)
        y1 = max(0, judgment_y - r)
        y2 = min(h, judgment_y + r)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return ""

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, self.bright_thresh - 30,
                                  255, cv2.THRESH_BINARY)

        dx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        dy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)

        magnitude = np.sqrt(dx**2 + dy**2)
        angle = np.arctan2(dy, dx)

        bright_mask = gray > self.bright_thresh - 30
        if np.sum(bright_mask) < 10:
            return ""

        # ═══ 向量化: 用 numpy 替换像素循环 ═══
        # 只处理亮像素位置的梯度和角度
        bright_angle = angle[bright_mask]
        bright_mag = magnitude[bright_mask]

        # 4 方向直方图 (加权)
        directions = ["right", "down", "left", "up"]
        bin_idx = ((bright_angle + np.pi) / (2 * np.pi) * 4).astype(np.int32) % 4
        hist = np.zeros(4)
        np.add.at(hist, bin_idx, bright_mag)

        if np.max(hist) > 0:
            main_dir = directions[int(np.argmax(hist))]
            return main_dir

        return ""

    # ──────────────────────────────────────────
    # Hold 状态管理
    # ──────────────────────────────────────────

    def _update_hold_state(self, state: GameState):
        """更新 hold 状态。"""
        current_active = {n.lane for n in state.detected_notes}

        for lane in current_active:
            self._hold_count[lane] = self._hold_count.get(lane, 0) + 1

        for lane in list(self._hold_count.keys()):
            if lane not in current_active:
                self._hold_count[lane] = 0

        hold_thresh = self.cfg["touch"].get("hold_threshold_frames", 3)
        for lane, count in self._hold_count.items():
            if count >= hold_thresh and lane in current_active:
                for event in state.detected_notes:
                    if event.lane == lane:
                        event.note_type = "hold"

        self._prev_active = current_active

    # ──────────────────────────────────────────
    # 辅助功能
    # ──────────────────────────────────────────

    def get_lane_positions(self) -> list[tuple[int, int]]:
        return [(x, self.judgment_y) for x in self.all_lanes]

    def get_lane_count(self) -> int:
        return len(self.all_lanes)

    def get_detection_region(self) -> tuple[int, int, int, int]:
        """返回检测区域的 (top, bottom, left, right) 像素坐标。"""
        return (self.note_detect_top, self.judgment_y,
                0, self.screen_w)

    def classify_screen(self, frame: np.ndarray) -> str:
        """
        快速分类当前画面: 'game' / 'result' / 'menu' / 'unknown'
        用于连续执行自动导航。
        """
        if frame is None:
            return "unknown"
        if self._is_game_screen(frame):
            return "game"
        if self._is_result_screen(frame):
            return "result"
        return "menu"

    # ──────────────────────────────────────────
    # 调试与可视化
    # ──────────────────────────────────────────

    def _save_debug_frame(self, frame: np.ndarray, state: GameState):
        import os
        os.makedirs(self.debug_dir, exist_ok=True)

        debug = frame.copy()
        # 判定线
        cv2.line(debug, (0, self.judgment_y),
                 (self.screen_w, self.judgment_y), (0, 255, 0), 2)
        # 检测区域上边界
        cv2.line(debug, (0, self.note_detect_top),
                 (self.screen_w, self.note_detect_top), (255, 255, 0), 1)

        for idx, (lx, ly) in enumerate(self.get_lane_positions()):
            active = any(n.lane == idx for n in state.detected_notes)
            color = (0, 0, 255) if active else (128, 128, 128)
            cv2.circle(debug, (lx, ly), self.detect_radius, color, 2)
            if active:
                cv2.circle(debug, (lx, ly), 5, (0, 0, 255), -1)

        # 画预测 note 位置
        for note in state.predicted_notes:
            cv2.circle(debug, (note.x, note.y), 6, (255, 0, 255), -1)

        ts = int(time.time() * 1000)
        path = os.path.join(self.debug_dir, f"frame_{self.frame_count:06d}_{ts}.jpg")
        cv2.imwrite(path, debug)

    def _show_preview(self, frame: np.ndarray, state: GameState):
        preview = frame.copy()
        cv2.line(preview, (0, self.judgment_y),
                 (self.screen_w, self.judgment_y), (0, 255, 0), 2)
        cv2.line(preview, (0, self.note_detect_top),
                 (self.screen_w, self.note_detect_top), (255, 255, 0), 1)

        for idx, (lx, ly) in enumerate(self.get_lane_positions()):
            active = any(n.lane == idx for n in state.detected_notes)
            color = (0, 0, 255) if active else (128, 128, 128)
            cv2.circle(preview, (lx, ly), self.detect_radius, color, 2)

        for note in state.predicted_notes:
            cv2.circle(preview, (note.x, note.y), 6, (255, 0, 255), -1)

        info = f"Notes: {len(state.detected_notes)}  Pred: {len(state.predicted_notes)}  Frame: {self.frame_count}"
        cv2.putText(preview, info, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv2.imshow("PJSK Auto Player - Preview", preview)
        cv2.waitKey(1)

    # ──────────────────────────────────────────
    # 校准工具
    # ──────────────────────────────────────────

    def calibrate_judgment_line(self, frame: np.ndarray) -> int:
        """校准判定线 Y 位置。"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        x_start = int(w * 0.2)
        x_end = int(w * 0.8)

        # 在屏幕下方 50%-95% 区域找最亮的行
        y_scores = []
        for y in range(int(h * 0.5), int(h * 0.95)):
            row = gray[y, x_start:x_end]
            score = np.mean(row)
            y_scores.append((y, score))

        if y_scores:
            y_scores.sort(key=lambda x: x[1], reverse=True)
            best_y = y_scores[0][0]
            logger.info(f"自动校准判定线 Y={best_y} (原配置={self.judgment_y})")
            return best_y

        return self.judgment_y

    def calibrate_lanes(self, frame: np.ndarray) -> list[int]:
        """校准轨道 X 位置。"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        y_start = max(0, self.judgment_y - 10)
        y_end = min(h, self.judgment_y + 10)
        strip = gray[y_start:y_end, :]
        col_scores = np.mean(strip, axis=0)

        try:
            from scipy.signal import find_peaks
            peaks, properties = find_peaks(
                col_scores,
                distance=w // 10,
                height=np.mean(col_scores) + np.std(col_scores) * 1.5
            )

            margin = int(w * 0.05)
            peaks = [p for p in peaks if margin < p < w - margin]

            if len(peaks) >= 2:
                logger.info(f"自动校准轨道: {len(peaks)} 个轨道 @ {peaks}")
                return peaks.tolist()

        except ImportError:
            logger.warning("scipy 未安装, 跳过自动校准。"
                           "pip install scipy 可启用。")

        return self.all_lanes

    def close(self):
        if self.show_preview:
            cv2.destroyAllWindows()
