"""
PJSK Auto Player — 结算画面 Handler

负责:
  1. 检测结算画面
  2. 读取分数/判定
  3. 跳过结算动画
  4. 选择继续/重试/返回
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from handlers import BaseHandler
from pipeline.timer import Timer
from vision.button import get_button, apply_screen_size

logger = logging.getLogger("pjsk.handler.result")


class ResultHandler(BaseHandler):
    """结算画面处理器。"""

    def __init__(self, controller=None, config: Optional[dict] = None):
        super().__init__(controller, config)
        self.last_score = 0
        self.last_combo = 0

    def detect_result_screen(self, frame) -> bool:
        """检测是否在结算画面。"""
        h, w = frame.shape[:2]
        apply_screen_size(w, h)
        btn = get_button("result_dismiss")
        return btn is not None and btn.detect(frame)

    def wait_for_result(self, timeout: float = 30.0) -> bool:
        """等待结算画面出现。"""
        timer = Timer(limit=timeout, count=60)
        timer.start()
        while not timer.reached():
            frame = self._screencap()
            if frame is None:
                time.sleep(0.5)
                continue
            if self.detect_result_screen(frame):
                self.log("✅ 检测到结算画面")
                return True
            time.sleep(0.3)
        self.log("❌ 结算画面超时", "error")
        return False

    def read_score(self, frame) -> Optional[int]:
        """从结算画面读取分数。"""
        try:
            from vision.ocr import OcrReader
            ocr = OcrReader()
            # 分数通常在画面中央区域
            h, w = frame.shape[:2]
            score_roi = frame[int(h*0.3):int(h*0.5), int(w*0.2):int(w*0.8)]
            score = ocr.read_numbers(score_roi)
            if score:
                self.last_score = score
                self.log(f"📊 分数: {score}")
            return score
        except Exception as e:
            logger.debug("Score read failed: %s", e)
            return None

    def dismiss(self, mode: str = "continue") -> bool:
        """跳过结算画面。
        
        Args:
            mode: continue=继续, retry=重试, back=返回选歌
        """
        self.log(f"⏭️  跳过结算 (mode={mode})")
        timer = Timer(limit=20, count=40)
        timer.start()
        while not timer.reached():
            frame = self._screencap()
            if frame is None:
                time.sleep(0.3)
                continue
            h, w = frame.shape[:2]
            apply_screen_size(w, h)
            
            # 先点跳过键（右上角）
            dismiss = get_button("result_dismiss")
            if dismiss and dismiss.detect(frame):
                x, y = dismiss.click_point
                self._click(x, y, jitter=True)
                time.sleep(0.5)
                continue
            
            # 再选模式
            btn_name = {
                "continue": "result_continue",
                "retry": "result_retry",
                "back": "close_button",
            }.get(mode, "result_continue")
            
            btn = get_button(btn_name)
            if btn and btn.detect(frame):
                x, y = btn.click_point
                self._click(x, y, jitter=True)
                return True
            
            # 如果检测不到任何按钮，点击画面中央跳过动画
            self._click(w // 2, int(h * 0.8), jitter=True)
            time.sleep(0.5)
        
        self.log("❌ 结算跳过超时", "error")
        return False

    def _screencap(self):
        if self.controller and hasattr(self.controller, "screencap"):
            try:
                return self.controller.screencap()
            except Exception:
                return None
        return None

    def _click(self, x, y, jitter=False):
        if self.controller and hasattr(self.controller, "click"):
            import random
            if jitter:
                x += random.randint(-5, 5)
                y += random.randint(-5, 5)
            try:
                self.controller.click(x, y)
            except Exception as e:
                logger.debug("Click failed: %s", e)
