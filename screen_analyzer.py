"""
屏幕分析器 —— 通过 OpenCV 分析 PJSK 游戏画面, 检测:
- 判定线上的 note (tap / flick / hold)
- 游戏状态 (选歌 / 打歌中 / 结算)
- 实时校准辅助
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

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


@dataclass
class GameState:
    """游戏画面状态。"""
    in_game: bool = False      # 是否在打歌中
    detected_notes: list[NoteEvent] = field(default_factory=list)
    combo: int = 0             # 当前 combo (实验性)
    frame_count: int = 0       # 处理帧计数


class ScreenAnalyzer:
    """
    屏幕分析器: 读取手机截屏, 检测 PJSK 画面中的 note。
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
        self._prev_active = set()       # 上一帧活跃的轨道
        self._hold_count = {}           # 轨道持续计数
        self.frame_count = 0

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

        Args:
            frame: BGR numpy array

        Returns:
            GameState 对象, 包含检测到的 notes
        """
        self.frame_count += 1
        state = GameState(frame_count=self.frame_count)

        if frame is None:
            return state

        h, w = frame.shape[:2]
        if w != self.screen_w or h != self.screen_h:
            # 实际分辨率可能和配置不一致, 自适应
            self.screen_w = w
            self.screen_h = h
            self._recalc_coords()

        # 判断是否在游戏中
        if not self._is_game_screen(frame):
            state.in_game = False
            return state

        state.in_game = True
        now = time.time()

        # 对每个轨道检测 note
        for idx, lane_x in enumerate(self.all_lanes):
            active, note_type, confidence, details = self._detect_note_at(
                frame, lane_x, self.judgment_y
            )

            if active:
                event = NoteEvent(
                    lane=idx,
                    x=lane_x,
                    y=self.judgment_y,
                    note_type=note_type,
                    confidence=confidence,
                    timestamp=now,
                )

                # 检测 flick 方向 (如果是 flick)
                if note_type == "flick":
                    direction = self._detect_flick_direction(
                        frame, lane_x, self.judgment_y
                    )
                    event.flick_direction = direction

                state.detected_notes.append(event)

        # 更新 hold 状态
        self._update_hold_state(state)

        # 可选: 保存调试截图
        if self.save_debug:
            self._save_debug_frame(frame, state)

        # 可选: 显示预览窗口
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
        # 重算忽略区域
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
        """
        判断当前画面是否为 PJSK 打歌界面。

        策略: 检查判定线区域是否有足够的亮像素
        (打歌时判定线附近有 UI 元素/ note, 选歌界面没有)。
        """
        h, w = frame.shape[:2]
        # 判定线周围一个矩形区域
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

        # 打歌时判定线区域有一定比例的亮像素 (note / 特效 / UI)
        # 选歌画面判定线区域通常很暗
        return bright_ratio > 0.02

    # ──────────────────────────────────────────
    # Note 检测 (核心算法)
    # ──────────────────────────────────────────

    def _detect_note_at(
        self, frame: np.ndarray, lane_x: int, judgment_y: int
    ) -> tuple[bool, str, float, dict]:
        """
        在指定轨道位置检测是否有 note。

        Args:
            frame: BGR 帧
            lane_x: 轨道 X 坐标
            judgment_y: 判定线 Y 坐标

        Returns:
            (active, note_type, confidence, details)
        """
        h, w = frame.shape[:2]
        r = self.detect_radius

        # 截取 ROI
        x1 = max(0, lane_x - r)
        x2 = min(w, lane_x + r)
        y1 = max(0, judgment_y - r)
        y2 = min(h, judgment_y + r)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "tap", 0.0, {}

        # 检查 ROI 是否在忽略区域内
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

        # 形态学开运算去除噪点
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(
            cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if self.min_area <= area <= self.max_area:
                # 计算亮度占比 (确认是亮的)
                mask = np.zeros_like(gray)
                cv2.drawContours(mask, [cnt], -1, 255, -1)
                brightness = cv2.mean(gray, mask=mask)[0]
                confidence = min(1.0, brightness / 255.0)

                # 判断 note 类型: 通过轮廓的宽高比
                _, (w_note, h_note), _ = cv2.minAreaRect(cnt)
                aspect = max(w_note, h_note) / (min(w_note, h_note) + 1e-6)

                # 宽度明显大于高度 -> 可能是 hold trail
                # 接近 1:1 -> tap / flick
                # 有箭头突起 -> flick
                note_type = "tap"
                if aspect > 2.5:
                    note_type = "hold"

                return True, note_type, confidence, {
                    "area": area, "aspect": aspect
                }

        return False, "tap", 0.0, {}

    def _detect_by_color(
        self, roi: np.ndarray
    ) -> tuple[bool, str, float, dict]:
        """基于颜色的 note 检测。"""
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        # 白色中心 mask
        white_mask = cv2.inRange(hsv, self.white_lower, self.white_upper)
        # 彩色边缘 mask
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
                note_type = "hold" if aspect > 2.5 else "tap"

                # 计算颜色饱和度作为置信度
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

        在 note 周围搜索箭头状轮廓, 判断方向。
        返回 "up"/"down"/"left"/"right" 之一, 或空字符串。
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
        _, thresh = cv2.threshold(gray, self.bright_thresh - 30, 255, cv2.THRESH_BINARY)

        # 找箭头: 箭头通常有三角形突起
        # 简单方法: 找亮度梯度指向最强的方向
        dx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        dy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)

        magnitude = np.sqrt(dx**2 + dy**2)
        angle = np.arctan2(dy, dx)

        # 在亮区计算主方向
        bright_mask = gray > self.bright_thresh - 30
        if np.sum(bright_mask) < 10:
            return ""

        # 将角度转为方向
        hist_bins = 4
        directions = ["right", "down", "left", "up"]  # 0°, 90°, 180°, 270°
        hist = np.zeros(hist_bins)

        for y_i in range(gray.shape[0]):
            for x_i in range(gray.shape[1]):
                if bright_mask[y_i, x_i]:
                    a = angle[y_i, x_i]
                    m = magnitude[y_i, x_i]
                    # 将弧度映射到 4 个方向
                    idx = int(((a + np.pi) / (2 * np.pi)) * hist_bins) % hist_bins
                    hist[idx] += m

        if np.max(hist) > 0:
            main_dir = directions[int(np.argmax(hist))]
            return main_dir

        return ""

    # ──────────────────────────────────────────
    # Hold 状态管理
    # ──────────────────────────────────────────

    def _update_hold_state(self, state: GameState):
        """
        更新 hold 状态: 如果一个轨道连续多帧检测到 note,
        则标记为 hold。
        """
        current_active = {n.lane for n in state.detected_notes}

        # 更新持续计数
        for lane in current_active:
            self._hold_count[lane] = self._hold_count.get(lane, 0) + 1

        for lane in list(self._hold_count.keys()):
            if lane not in current_active:
                self._hold_count[lane] = 0

        # 标记 hold
        hold_thresh = self.cfg["touch"].get("hold_threshold_frames", 3)
        for lane, count in self._hold_count.items():
            if count >= hold_thresh and lane in current_active:
                # 将 event 标记为 hold
                for event in state.detected_notes:
                    if event.lane == lane:
                        event.note_type = "hold"

        self._prev_active = current_active

    # ──────────────────────────────────────────
    # 辅助功能
    # ──────────────────────────────────────────

    def get_lane_positions(self) -> list[tuple[int, int]]:
        """返回所有轨道的 (x, y) 像素坐标。"""
        return [(x, self.judgment_y) for x in self.all_lanes]

    def get_lane_count(self) -> int:
        """返回轨道总数。"""
        return len(self.all_lanes)

    # ──────────────────────────────────────────
    # 调试与可视化
    # ──────────────────────────────────────────

    def _save_debug_frame(self, frame: np.ndarray, state: GameState):
        """保存带标注的调试截图。"""
        import os
        os.makedirs(self.debug_dir, exist_ok=True)

        debug = frame.copy()
        # 画判定线
        cv2.line(debug,
                 (0, self.judgment_y),
                 (self.screen_w, self.judgment_y),
                 (0, 255, 0), 2)

        # 画轨道
        for idx, (lx, ly) in enumerate(self.get_lane_positions()):
            active = any(n.lane == idx for n in state.detected_notes)
            color = (0, 0, 255) if active else (128, 128, 128)
            cv2.circle(debug, (lx, ly), self.detect_radius, color, 2)
            if active:
                cv2.circle(debug, (lx, ly), 5, (0, 0, 255), -1)

        ts = int(time.time() * 1000)
        path = os.path.join(self.debug_dir, f"frame_{self.frame_count:06d}_{ts}.jpg")
        cv2.imwrite(path, debug)

    def _show_preview(self, frame: np.ndarray, state: GameState):
        """显示实时检测预览窗口。"""
        preview = frame.copy()
        cv2.line(preview,
                 (0, self.judgment_y),
                 (self.screen_w, self.judgment_y),
                 (0, 255, 0), 2)

        for idx, (lx, ly) in enumerate(self.get_lane_positions()):
            active = any(n.lane == idx for n in state.detected_notes)
            color = (0, 0, 255) if active else (128, 128, 128)
            cv2.circle(preview, (lx, ly), self.detect_radius, color, 2)

        info = f"Notes: {len(state.detected_notes)}  Frame: {self.frame_count}"
        cv2.putText(preview, info, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv2.imshow("PJSK Auto Player - Preview", preview)
        cv2.waitKey(1)

    # ──────────────────────────────────────────
    # 校准工具
    # ──────────────────────────────────────────

    def calibrate_judgment_line(self, frame: np.ndarray) -> int:
        """
        校准判定线 Y 位置。

        分析画面, 自动寻找判定线的像素特征 (水平亮线)。
        返回 Y 坐标 (像素), 失败时返回当前配置值。
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # 只分析中间 60% 宽度
        x_start = int(w * 0.2)
        x_end = int(w * 0.8)

        # 计算每一行的平均亮度
        y_scores = []
        for y in range(int(h * 0.5), int(h * 0.95)):
            row = gray[y, x_start:x_end]
            score = np.mean(row)
            y_scores.append((y, score))

        # 找亮度最高的行 (判定线周围通常有发光特效)
        if y_scores:
            y_scores.sort(key=lambda x: x[1], reverse=True)
            best_y = y_scores[0][0]
            logger.info(f"自动校准判定线 Y={best_y} (原配置={self.judgment_y})")
            return best_y

        return self.judgment_y

    def calibrate_lanes(self, frame: np.ndarray) -> list[int]:
        """
        校准轨道 X 位置。

        分析判定线区域的亮度峰值点, 自动找出轨道位置。
        返回 X 坐标列表。
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # 判定线周围几行
        y_start = max(0, self.judgment_y - 10)
        y_end = min(h, self.judgment_y + 10)
        strip = gray[y_start:y_end, :]

        # 垂直投影: 每列的平均亮度
        col_scores = np.mean(strip, axis=0)

        # 找局部峰值
        from scipy.signal import find_peaks

        try:
            peaks, properties = find_peaks(
                col_scores,
                distance=w // 10,    # 轨道间距至少屏幕宽度的 10%
                height=np.mean(col_scores) + np.std(col_scores) * 1.5
            )

            # 过滤: 只保留中间区域 (排除边缘 UI)
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
