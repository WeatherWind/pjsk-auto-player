"""
OCR 积分读取器 —— 从 PJSK 结算画面读取分数和判定结果。

使用 EasyOCR 或 pytesseract 识别屏幕上的数字文本。
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("pjsk_ocr")


class OcrReader:
    """
    OCR 积分读取器。

    从 PJSK 结算画面截图中读取:
      - 总分数 (Score)
      - PERFECT / GREAT / GOOD / BAD / MISS 计数
      - 最大连击 (Max Combo)
    """

    def __init__(self, config: dict):
        self.cfg = config
        self._reader = None
        self._engine = config.get("ocr", {}).get("engine", "auto")

    def _init_reader(self):
        """惰性初始化 OCR 引擎。"""
        if self._reader is not None:
            return True

        if self._engine == "easyocr" or self._engine == "auto":
            try:
                import easyocr
                self._reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
                logger.info("OCR: EasyOCR 已初始化")
                return True
            except ImportError:
                if self._engine == "easyocr":
                    logger.error("EasyOCR 未安装: pip install easyocr")
                    return False
                logger.info("EasyOCR 未安装, 尝试 pytesseract")

        if self._engine == "tesseract" or self._engine == "auto":
            try:
                import pytesseract
                # 检查 tesseract 是否可用
                try:
                    pytesseract.get_tesseract_version()
                    self._reader = pytesseract
                    logger.info("OCR: pytesseract 已初始化")
                    return True
                except Exception:
                    logger.debug("tesseract 未安装")
            except ImportError:
                logger.debug("pytesseract 未安装")

        logger.warning("OCR: 无可用引擎。安装: pip install easyocr 或 pip install pytesseract")
        return False

    def read_score(self, frame) -> Optional[dict]:
        """
        从结算画面截图读取分数信息。

        Args:
            frame: BGR numpy array (OpenCV 格式)

        Returns:
            {
                "score": 1234567,
                "perfect": 500,
                "great": 50,
                "good": 5,
                "bad": 1,
                "miss": 0,
                "max_combo": 600,
            }
            失败返回 None
        """
        if frame is None:
            return None
        if not self._init_reader():
            return None

        h, w = frame.shape[:2]
        result = {}

        # 分数区: 屏幕中央偏上区域
        score_roi = self._extract_roi(frame, 0.3, 0.08, 0.7, 0.2)
        if score_roi is not None:
            score_text = self._ocr_text(score_roi)
            score = self._parse_score(score_text)
            if score:
                result["score"] = score

        # 判定计数区: 屏幕右侧
        judge_roi = self._extract_roi(frame, 0.65, 0.25, 0.95, 0.7)
        if judge_roi is not None:
            judge_text = self._ocr_text(judge_roi)
            judges = self._parse_judges(judge_text)
            result.update(judges)

        return result if result else None

    def _extract_roi(self, frame, x1_ratio, y1_ratio, x2_ratio, y2_ratio):
        """截取 ROI 区域。"""
        h, w = frame.shape[:2]
        x1 = int(w * x1_ratio)
        y1 = int(h * y1_ratio)
        x2 = int(w * x2_ratio)
        y2 = int(h * y2_ratio)
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return None

        # 放大以便 OCR 识别
        import cv2
        scale = 2.0
        roi = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        # 转灰度 + 二值化
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    def _ocr_text(self, image) -> str:
        """对图片执行 OCR, 返回文本。"""
        if self._reader is None:
            return ""

        try:
            if hasattr(self._reader, "readtext"):
                # EasyOCR
                results = self._reader.readtext(image, detail=0,
                                                paragraph=True,
                                                width_ths=0.5)
                return " ".join(results)
            else:
                # pytesseract
                import pytesseract
                custom_config = "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789PERFECTGREATGOODBADMISSCOMBO"
                text = pytesseract.image_to_string(image, config=custom_config)
                return text.strip()
        except Exception as e:
            logger.debug(f"OCR 识别失败: {e}")
            return ""

    def _parse_score(self, text: str) -> Optional[int]:
        """从 OCR 文本解析分数数字。"""
        # 提取纯数字 (6位以上)
        numbers = re.findall(r"\d{6,}", text)
        if numbers:
            return int(numbers[0])
        return None

    def _parse_judges(self, text: str) -> dict:
        """从 OCR 文本解析判定计数。"""
        result = {}
        # 匹配 "PERFECT 123" 或 "PERFECT\n123"
        for label in ["PERFECT", "GREAT", "GOOD", "BAD", "MISS", "COMBO"]:
            pattern = re.compile(rf"{label}\s*[:：]?\s*(\d+)", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                key = label.lower()
                result[key] = int(match.group(1))
        return result
