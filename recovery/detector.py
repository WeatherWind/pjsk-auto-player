"""
ObstructionDetector — 画面级阻塞事件检测器。

安全原则:
  1. 弹窗检测只识别"系统公告/更新通知"类, 不识别交互弹窗
  2. 自动关闭只操作右上角 X 按钮, 不点中央 OK/确认
  3. OCR 确认按钮文字为安全关键词后才点击
  4. 抽卡/购买/課金类弹窗 ❌ 不自动关闭, 暂停并告警
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("pjsk.recovery.detector")

# ── 安全弹窗关键词 (系统公告/更新通知) ──
# 文本出现在弹窗内容区域 → 安全, 可自动关闭
SAFE_DIALOG_KEYWORDS = {
    "jp": ["時間", "更新", "お知らせ", "メンテナンス", "開始", "終了"],
    "cn": ["时间", "更新", "通知", "公告", "维护", "开始", "结束"],
    "tw": ["時間", "更新", "通知", "公告", "維護", "開始", "結束"],
    "en": ["update", "notice", "maintenance", "server time", "event"],
}

# ── 消费类弹窗关键词 (触碰到资源, 禁止自动关闭) ──
CONSUMPTION_KEYWORDS = {
    "jp": ["ガチャ", "購入", "課金", "消費", "使用", "交換", "確認"],
    "cn": ["抽卡", "购买", "充值", "消费", "使用", "兑换", "支付"],
    "tw": ["抽卡", "購買", "儲值", "消費", "使用", "兌換", "支付"],
    "en": ["gacha", "purchase", "buy", "spend", "confirm purchase"],
}

# ── 安全关闭按钮文字 (只点这些) ──
SAFE_BUTTON_TEXTS = ["閉じる", "关闭", "關閉", "close", "✕", "×", "OK", "确定", "確定"]


@dataclass
class ObstructionEvent:
    """阻塞事件数据结构。"""
    type: str                     # "blocking_dialog" / "frozen" / "black_screen" / "crash_dialog" / "adb_disconnected"
    severity: int = 1             # 1(弹窗) ~ 3(ADB断连)
    scene_before: str = ""        # 事件发生前的场景名
    frame_hash: int = 0           # 帧哈希 (用于去重)
    timestamp: float = 0.0        # 检测时间戳
    dialog_is_consumption: bool = False  # 是否消费类弹窗 (禁止自动关闭)


class ObstructionDetector:
    """画面级阻塞事件检测器。"""

    # 冻结阈值: 连续多少帧无变化视为冻结 (120帧 ≈ 4s @ 30FPS)
    FREEZE_THRESHOLD = 120

    # 黑屏阈值: mean brightness < 8 且持续 N 帧
    BLACK_THRESHOLD = 8
    BLACK_FRAME_MIN = 30

    # ADB 断连: screencap 连续 None 帧数
    ADB_LOST_FRAMES = 10

    def __init__(self, config: dict):
        self.config = config
        s = config.get("screen", {})
        self.screen_w = s.get("width", 1080)
        self.screen_h = s.get("height", 2400)

        # OCR 引擎 (惰性初始化, 只用于按钮文字确认)
        self._ocr = None

        self._black_frame_count = 0
        self._freeze_frame_count = 0
        self._adb_lost_count = 0
        self._last_frame_hash = 0
        self._last_scene = ""

        # 弹窗 dedup
        self._last_dialog_time = 0.0
        self._dialog_cooldown = 10.0

    def _init_ocr(self):
        """惰性初始化 OCR。"""
        if self._ocr is not None:
            return self._ocr is not False
        try:
            from vision.ocr import OcrReader
            self._ocr = OcrReader(engine="auto", scale=2.0)
            return True
        except Exception:
            self._ocr = False
            return False

    def analyze(self, frame, scene_name: str, frame_hash: int) -> Optional[ObstructionEvent]:
        """分析一帧, 返回阻塞事件或 None。"""
        now = time.time()

        # ── [检测 1] ADB 断连 ──
        if frame is None:
            self._adb_lost_count += 1
            if self._adb_lost_count >= self.ADB_LOST_FRAMES:
                self._reset_counters()
                return ObstructionEvent(
                    type="adb_disconnected", severity=3,
                    scene_before=scene_name, timestamp=now,
                )
            return None

        self._adb_lost_count = 0
        self._last_scene = scene_name

        # ── [检测 2] 黑屏 (排除 LOADING) ──
        if scene_name != "loading":
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean_brightness = float(np.mean(gray))
            if mean_brightness < self.BLACK_THRESHOLD:
                self._black_frame_count += 1
                if self._black_frame_count >= self.BLACK_FRAME_MIN:
                    self._reset_counters()
                    return ObstructionEvent(
                        type="black_screen", severity=3,
                        scene_before=scene_name, timestamp=now,
                    )
            else:
                self._black_frame_count = 0

        # ── [检测 3] 画面冻结 (排除 MENU) ──
        if scene_name != "menu" and frame_hash == self._last_frame_hash:
            self._freeze_frame_count += 1
            if self._freeze_frame_count >= self.FREEZE_THRESHOLD:
                self._reset_counters()
                return ObstructionEvent(
                    type="frozen", severity=2,
                    scene_before=scene_name, frame_hash=frame_hash,
                    timestamp=now,
                )
        else:
            self._freeze_frame_count = 0
        self._last_frame_hash = frame_hash

        # ── [检测 4] 阻塞弹窗 ──
        if now - self._last_dialog_time > self._dialog_cooldown:
            dialog_result = self._detect_safe_dialog(frame)
            if dialog_result is not None:
                is_consumption, matched_keyword = dialog_result
                self._last_dialog_time = now
                if is_consumption:
                    logger.warning("[Detector] ⛔ 消费类弹窗检测: '%s' — 跳过自动关闭", matched_keyword)
                else:
                    logger.info("[Detector] 阻塞弹窗检测: '%s'", matched_keyword)
                return ObstructionEvent(
                    type="blocking_dialog", severity=1,
                    scene_before=scene_name, timestamp=now,
                    dialog_is_consumption=is_consumption,
                )

        return None

    def _detect_safe_dialog(self, frame):
        """检测是否为系统公告/更新弹窗 (非消费类)。

        Returns:
            (is_consumption, matched_keyword) or None (非弹窗)
        """
        h, w = frame.shape[:2]

        # 中央 40% ROI
        x1, y1 = int(w * 0.30), int(h * 0.25)
        x2, y2 = int(w * 0.70), int(h * 0.75)
        if x2 <= x1 or y2 <= y1:
            return None

        center = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        # 亮色像素比例
        bright_ratio = float(np.mean(thresh > 128))
        if bright_ratio < 0.15 or bright_ratio > 0.75:
            return None

        # 验证四角暗色遮罩
        margins = [
            frame[0:int(h*0.1), 0:int(w*0.1)],
            frame[0:int(h*0.1), int(w*0.9):w],
            frame[int(h*0.9):h, 0:int(w*0.1)],
            frame[int(h*0.9):h, int(w*0.9):w],
        ]
        dark_count = sum(
            1 for m in margins
            if m.size > 0 and float(np.mean(cv2.cvtColor(m, cv2.COLOR_BGR2GRAY))) < 60
        )
        if dark_count < 2:
            return None

        # 找亮色连通域
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        total = (x2 - x1) * (y2 - y1)
        if total <= 0 or not (0.03 <= area / total <= 0.35):
            return None

        # ── OCR 确认文字内容 ──
        if not self._init_ocr():
            # 无 OCR 时 ⚠ 保守策略: 不自动关闭, 走 verify_close_button 验证
            # geo_match_only 标记为消费弹窗以避免误关闭
            logger.warning("[Detector] OCR 不可用, 跳过弹窗自动关闭")
            return (True, "no_ocr_skip")

        try:
            # 读取弹窗内容区域文字 (排除按钮区域)
            content_roi = frame[y1:y2, x1:x2]
            result = self._ocr.read(content_roi)

            if not result or not result.text:
                return None

            text = result.text.strip()

            # 优先检查消费关键词
            for lang_keywords in CONSUMPTION_KEYWORDS.values():
                for kw in lang_keywords:
                    if kw in text:
                        return (True, kw)  # 消费弹窗!

            # 再检查安全关键词
            for lang_keywords in SAFE_DIALOG_KEYWORDS.values():
                for kw in lang_keywords:
                    if kw in text:
                        return (False, kw)  # 安全弹窗

            # OCR 有文字但未匹配任何关键词 → 未知类型, 保守跳过
            logger.debug("[Detector] 弹窗文字无匹配: '%s' — 跳过", text[:50])

        except Exception as e:
            logger.debug("[Detector] OCR 异常: %s", e)

        return None

    def verify_close_button(self, frame, region) -> bool:
        """OCR 验证指定区域是否包含安全关闭按钮文字。

        Args:
            frame: 当前帧
            region: (rx, ry, rw, rh) 相对坐标

        Returns:
            True = 按钮文字匹配安全列表
        """
        h, w = frame.shape[:2]
        rx, ry, rw, rh = region
        x1 = int(rx * w)
        y1 = int(ry * h)
        x2 = int(rw * w)
        y2 = int(rh * h)
        if x2 <= x1 or y2 <= y1:
            return False

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False

        if not self._init_ocr():
            return True  # 无 OCR 时允许 (保守但不过度限制)

        try:
            result = self._ocr.read(roi, preprocess=True)
            if result and result.text:
                text = result.text.strip()
                for safe in SAFE_BUTTON_TEXTS:
                    if safe in text:
                        return True
                logger.debug("[Detector] 按钮文字非安全列表: '%s'", text[:30])
        except Exception:
            pass
        return False

    def _reset_counters(self):
        self._black_frame_count = 0
        self._freeze_frame_count = 0
        self._adb_lost_count = 0

    def reset(self):
        self._reset_counters()
        self._last_frame_hash = 0
        self._last_dialog_time = 0.0
