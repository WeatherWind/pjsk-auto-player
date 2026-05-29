"""OCR 识别模块 —— 数字/文字识别。

参考 lib/ocr_reader.py 的设计思路，提供更通用的 OCR 接口。
支持 EasyOCR 和 pytesseract 作为后端引擎。
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("pjsk_vision.ocr")


@dataclass
class OcrResult:
    """OCR 识别结果。"""
    text: str
    confidence: float
    bbox: tuple[int, int, int, int] | None = None  # (x, y, w, h)
    engine: str = "unknown"


class OcrReader:
    """通用 OCR 识别器。

    参考 lib/ocr_reader.py 中 OcrReader 的设计:
      - 惰性初始化 OCR 引擎
      - 支持 EasyOCR / pytesseract 自动切换
      - ROI 预处理: 灰度化 + 二值化 + 缩放
      - 后处理: 正则提取数字/关键词

    用法:
        reader = OcrReader()
        result = reader.read(frame, roi=(0.3, 0.08, 0.7, 0.2))
        print(result.text)  # "1234567"

        # 数字专用
        numbers = reader.read_numbers(frame, roi=(0.3, 0.08, 0.7, 0.2))
        print(numbers)  # [1234567]
    """

    def __init__(
        self, engine: str = "auto",
        lang: list[str] | None = None,
        scale: float = 2.0,
    ) -> None:
        """
        Args:
            engine: OCR 引擎, "auto" | "easyocr" | "tesseract"
            lang: 语言列表 (EasyOCR: ["ch_sim", "en"]; tesseract: "chi_sim+eng")
            scale: ROI 缩放倍数 (放大有助于识别)
        """
        self._engine = engine
        self._lang = lang or ["ch_sim", "en"]
        self._scale = scale
        self._reader = None
        self._engine_name = "uninitialized"

        logger.info(f"OcrReader 创建, engine={engine}, lang={self._lang}")

    # ── 初始化 ──────────────────────────────────────────

    def _init_reader(self) -> bool:
        """惰性初始化 OCR 引擎。"""
        if self._reader is not None:
            return True

        if self._engine in ("easyocr", "auto"):
            try:
                import easyocr
                self._reader = easyocr.Reader(self._lang, gpu=False)
                self._engine_name = "easyocr"
                logger.info("OCR 引擎: EasyOCR")
                return True
            except ImportError:
                if self._engine == "easyocr":
                    logger.error("EasyOCR 未安装: pip install easyocr")
                    return False
                logger.info("EasyOCR 不可用, 尝试 pytesseract")

        if self._engine in ("tesseract", "auto"):
            try:
                import pytesseract
                # 验证可用性
                try:
                    pytesseract.get_tesseract_version()
                except Exception:
                    logger.debug("tesseract 未安装或不在 PATH")
                    if self._engine == "tesseract":
                        logger.error(
                            "Tesseract 未安装。请安装: "
                            "apt install tesseract-ocr (Linux) 或 "
                            "brew install tesseract (macOS)"
                        )
                        return False
                    return False

                self._reader = pytesseract
                self._engine_name = "tesseract"
                logger.info("OCR 引擎: pytesseract")
                return True
            except ImportError:
                if self._engine == "tesseract":
                    logger.error("pytesseract 未安装: pip install pytesseract")
                    return False
                logger.info("pytesseract 不可用")

        logger.warning(
            "无可用 OCR 引擎。安装: pip install easyocr "
            "或 pip install pytesseract (需系统安装 tesseract)"
        )
        return False

    # ── 核心 OCR ────────────────────────────────────────

    def read(
        self, frame: np.ndarray,
        roi: tuple[float, float, float, float] | None = None,
        preprocess: bool = True,
        whitelist: str | None = None,
    ) -> OcrResult:
        """对帧 (或 ROI) 执行 OCR。

        Args:
            frame: BGR numpy array
            roi: (x1_ratio, y1_ratio, x2_ratio, y2_ratio) 或 None=全图
            preprocess: 是否预处理 (灰度+二值化+缩放)
            whitelist: tesseract 白名单字符 (如 "0123456789")

        Returns:
            OcrResult 包含识别文本和置信度
        """
        if frame is None or frame.size == 0:
            return OcrResult("", 0.0)

        if not self._init_reader():
            return OcrResult("", 0.0)

        # 截取 ROI
        if roi is not None:
            image = self._extract_roi(frame, roi, preprocess)
        else:
            image = self._preprocess(frame) if preprocess else frame

        if image is None or image.size == 0:
            return OcrResult("", 0.0)

        # 执行 OCR
        try:
            if self._engine_name == "easyocr":
                return self._read_easyocr(image, whitelist)
            elif self._engine_name == "tesseract":
                return self._read_tesseract(image, whitelist)
            else:
                return OcrResult("", 0.0)
        except Exception as e:
            logger.debug(f"OCR 识别异常: {e}")
            return OcrResult("", 0.0)

    def read_numbers(
        self, frame: np.ndarray,
        roi: tuple[float, float, float, float] | None = None,
        min_digits: int = 1,
    ) -> list[int]:
        """读取 ROI 中的数字。

        Returns:
            所有找到的整数列表
        """
        result = self.read(frame, roi, whitelist="0123456789")
        if not result.text:
            return []
        numbers = re.findall(r"\d{" + str(min_digits) + ",}", result.text)
        return [int(n) for n in numbers]

    def read_score(
        self, frame: np.ndarray,
        score_roi: tuple[float, float, float, float] = (0.3, 0.08, 0.7, 0.2),
    ) -> Optional[int]:
        """读取分数 (6 位以上数字)。"""
        numbers = self.read_numbers(frame, score_roi, min_digits=6)
        return numbers[0] if numbers else None

    def read_judges(
        self, frame: np.ndarray,
        judge_roi: tuple[float, float, float, float] = (0.65, 0.25, 0.95, 0.7),
    ) -> dict[str, int]:
        """读取判定计数 (PERFECT/GREAT/GOOD/BAD/MISS/COMBO)。"""
        result = self.read(frame, judge_roi)
        if not result.text:
            return {}

        judges: dict[str, int] = {}
        for label in ["PERFECT", "GREAT", "GOOD", "BAD", "MISS", "COMBO"]:
            pattern = re.compile(rf"{label}\s*[:：]?\s*(\d+)", re.IGNORECASE)
            match = pattern.search(result.text)
            if match:
                judges[label.lower()] = int(match.group(1))

        return judges

    # ── 内部方法 ──────────────────────────────────────

    def _extract_roi(
        self, frame: np.ndarray,
        roi: tuple[float, float, float, float],
        preprocess: bool = True,
    ) -> Optional[np.ndarray]:
        """截取并预处理 ROI。"""
        h, w = frame.shape[:2]
        x1 = int(w * roi[0])
        y1 = int(h * roi[1])
        x2 = int(w * roi[2])
        y2 = int(h * roi[3])
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return None

        roi_img = frame[y1:y2, x1:x2]
        return self._preprocess(roi_img) if preprocess else roi_img

    def _preprocess(self, img: np.ndarray) -> np.ndarray:
        """预处理图像: 放大 + 灰度 + 二值化。"""
        # 放大
        if self._scale != 1.0:
            new_w = int(img.shape[1] * self._scale)
            new_h = int(img.shape[0] * self._scale)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

        # 灰度
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # 二值化 (OTSU)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    def _read_easyocr(
        self, image: np.ndarray, whitelist: str | None = None,
    ) -> OcrResult:
        """使用 EasyOCR 引擎识别。"""
        if whitelist is not None:
            # EasyOCR 不支持 whitelist, 忽略
            logger.debug("EasyOCR 不支持 whitelist 参数, 忽略")

        results = self._reader.readtext(
            image, detail=1, paragraph=True, width_ths=0.5,
        )
        if not results:
            return OcrResult("", 0.0)

        # 合并段落文本
        full_text = " ".join(r[1] for r in results)
        avg_conf = float(np.mean([r[2] for r in results])) if results else 0.0

        # 取第一个结果的 bbox
        bbox = results[0][0]
        x = int(min(p[0] for p in bbox))
        y = int(min(p[1] for p in bbox))
        x2 = int(max(p[0] for p in bbox))
        y2 = int(max(p[1] for p in bbox))

        return OcrResult(
            text=full_text,
            confidence=avg_conf,
            bbox=(x, y, x2 - x, y2 - y),
            engine="easyocr",
        )

    def _read_tesseract(
        self, image: np.ndarray, whitelist: str | None = None,
    ) -> OcrResult:
        """使用 Tesseract 引擎识别。"""
        import pytesseract

        config = "--oem 3 --psm 6"
        if whitelist:
            config += f" -c tessedit_char_whitelist={whitelist}"

        text = pytesseract.image_to_string(image, config=config)
        text = text.strip()

        if not text:
            return OcrResult("", 0.0)

        # Tesseract 不直接提供置信度, 用文本长度作为简单指标
        conf = min(1.0, len(text) / 50.0 + 0.5)

        return OcrResult(
            text=text,
            confidence=conf,
            engine="tesseract",
        )

    def is_ready(self) -> bool:
        """检查 OCR 引擎是否可用。"""
        return self._init_reader()
