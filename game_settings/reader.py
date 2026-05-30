"""
游戏设置读取器 —— OCR 导航 + 读取 + 校准的核心模块。

工作流程:
  1. 截屏 → 检测当前画面 (主菜单/设置/游戏中)
  2. 从主菜单导航到 設定 → ライブ設定
  3. OCR 读取 タイミング調整 和 ノーツ速度 的值
  4. 导航返回主菜单
  5. 调校 SettingsCalibrator 映射为软件参数
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import cv2

from game_settings.server_config import (
    GameServer,
    ServerConfig,
    detect_server,
    detect_server_by_ocr_labels,
    get_server_config,
    SERVER_CONFIGS,
)
from game_settings.calibrator import SettingsCalibrator, CalibrationResult

logger = logging.getLogger("pjsk.game_settings")


# ── 数据结构 ──

@dataclass
class GameSettings:
    """从游戏内读取到的原始设置值。"""
    timing_offset: int = 0         # タイミング調整 (-50 ~ +50)
    note_speed: float = 10.0       # ノーツ速度 (1.0 ~ 12.0)
    server: GameServer = GameServer.AUTO
    confidence: float = 0.0
    raw_ocr_text: str = ""
    errors: list[str] = field(default_factory=list)
    read_time: str = ""

    @property
    def is_valid(self) -> bool:
        return self.confidence >= 0.3 and not self.errors

    def __repr__(self) -> str:
        return (f"GameSettings(timing={self.timing_offset:+d}, "
                f"speed={self.note_speed:.1f}, "
                f"server={self.server.value}, conf={self.confidence:.2f})")


# ── 主读取器 ──

class GameSettingsReader:
    """
    游戏设置读取器。

    自动导航到 PJSK LIVE 设置页面，OCR 读取时延和速度参数。
    支持多服务器自动检测和手动指定。

    用法:
        # 需要传入 controller (具有 screencap/click/swipe 方法)
        reader = GameSettingsReader(controller, config)
        settings = reader.read_all()
        if settings.is_valid:
            calib = reader.calibrate(settings)
            reader.apply_to_config(calib)
    """

    # OCR 数值读取白名单
    OCR_DIGIT_WHITELIST = "-0123456789. "

    # 导航超时 (秒)
    NAV_TIMEOUT = 10.0
    # 导航步骤间等待 (秒)
    NAV_STEP_DELAY = 1.2
    # OCR 重试次数
    OCR_RETRIES = 3

    def __init__(self, controller, config: dict,
                 server: GameServer = GameServer.AUTO):
        """
        Args:
            controller: 设备控制器 (必须有 screencap/click/is_connected)
            config: 完整应用配置
            server: 目标服务器 (GameServer.AUTO = 自动检测)
        """
        self._ctrl = controller
        self._config = config
        self._screen_w = config.get("screen", {}).get("width", 1080)
        self._screen_h = config.get("screen", {}).get("height", 2400)

        # 服务器
        self._server = server
        self._server_cfg: Optional[ServerConfig] = None

        # OCR 引擎 (惰性初始化)
        self._ocr = None

        logger.info("GameSettingsReader init: server=%s", server.value)

    # ── OCR 引擎 ──

    def _init_ocr(self):
        """惰性初始化 OCR。"""
        if self._ocr is not None:
            return bool(self._ocr)

        server_cfg = self._resolve_server()
        try:
            from vision.ocr import OcrReader
            self._ocr = OcrReader(
                engine="auto",
                lang=server_cfg.ocr_lang,
                scale=2.0,
            )
            if self._ocr.is_ready():
                logger.info("OCR ready: %s", server_cfg.ocr_lang)
                return True
        except ImportError:
            pass

        # 降级到 lib/ocr_reader
        try:
            from ocr_reader import OcrReader as LegacyOcrReader
            self._ocr = LegacyOcrReader(self._config)
            logger.info("OCR ready (legacy)")
            return True
        except ImportError:
            pass

        logger.warning("No OCR engine available")
        self._ocr = None
        return False

    def _resolve_server(self) -> ServerConfig:
        """解析服务器配置。"""
        if self._server_cfg is not None:
            return self._server_cfg

        if self._server != GameServer.AUTO:
            self._server_cfg = get_server_config(self._server)
            return self._server_cfg

        # 自动检测: 尝试从 config 读取已缓存的服务器
        cached = self._config.get("game_settings", {}).get("detected_server", "")
        if cached:
            try:
                self._server = GameServer(cached)
                self._server_cfg = get_server_config(self._server)
                logger.info("Using cached server: %s", cached)
                return self._server_cfg
            except ValueError:
                pass

        # 尝试从包名检测
        try:
            pkg = self._detect_package_name()
            detected = detect_server(pkg)
            if detected:
                self._server = detected
                self._server_cfg = get_server_config(detected)
                logger.info("Server detected from package: %s → %s", pkg, detected.value)
                return self._server_cfg
        except Exception as e:
            logger.debug("Package detection failed: %s", e)

        # 默认日服
        self._server_cfg = get_server_config(GameServer.JP)
        logger.info("Server defaulting to JP")
        return self._server_cfg

    def _detect_package_name(self) -> Optional[str]:
        """检测设备上运行的 PJSK 包名。"""
        # 尝试通过 controller shell 获取前台应用
        try:
            if hasattr(self._ctrl, 'shell'):
                # adb shell dumpsys activity activities | grep topResumedActivity
                # 或 adb shell dumpsys window | grep mCurrentFocus
                result = ""
                # 尝试多种方法
                for cmd in [
                    "dumpsys activity activities 2>/dev/null | grep -E 'topResumedActivity|mResumedActivity' | head -1",
                    "dumpsys window windows 2>/dev/null | grep -i mCurrentFocus | head -1",
                ]:
                    try:
                        out = self._ctrl.shell(cmd)
                        if isinstance(out, str) and out.strip():
                            result = out.strip()
                            break
                        elif hasattr(out, 'stdout'):
                            result = out.stdout.strip()
                            if result:
                                break
                    except Exception:
                        continue

                if result:
                    # 从输出提取包名: ...com.sega.ColorfulStage/...
                    for part in result.split():
                        if '/' in part:
                            pkg = part.split('/')[0].strip()
                            if 'com.' in pkg:
                                return pkg
        except Exception as e:
            logger.debug("Package detection error: %s", e)

        # 尝试从 config 获取
        pkg = self._config.get("adb", {}).get("target_package", "")
        if pkg:
            return pkg

        return None

    # ── 截图辅助 ──

    def _capture(self) -> Optional[np.ndarray]:
        """安全截图。"""
        try:
            if hasattr(self._ctrl, 'screencap'):
                frame = self._ctrl.screencap()
                if frame is not None and frame.size > 0:
                    return frame
            # 降级尝试
            if hasattr(self._ctrl, 'capture'):
                return self._ctrl.capture()
        except Exception as e:
            logger.debug("Capture failed: %s", e)
        return None

    def _wait_stable(self, delay: float = None):
        """等待画面稳定。"""
        time.sleep(delay or self.NAV_STEP_DELAY)

    # ── 点击辅助 ──

    def _click_roi(self, roi: tuple, label: str = "") -> bool:
        """点击 ROI 中心。"""
        x = (roi[0] + roi[2]) / 2
        y = (roi[1] + roi[3]) / 2
        try:
            if hasattr(self._ctrl, 'click'):
                self._ctrl.click(x, y)
                logger.debug("Click %s at (%.3f, %.3f)", label, x, y)
                return True
        except Exception as e:
            logger.warning("Click failed: %s", e)
        return False

    # ── 导航 ──

    def navigate_to_live_settings(self) -> bool:
        """从当前画面导航到 LIVE 设置页面。

        导航路径:
          主菜单 → 右上角 Menu → 設定 → ライブ設定
          如果已在设置页面则跳过。

        Returns:
            True 如果成功到达 LIVE 设置页面
        """
        cfg = self._resolve_server()
        logger.info("Navigating to live settings (%s)...", cfg.display_name)

        # Step 1: 点击 Menu 按钮 (主菜单右上角)
        logger.debug("Step 1: Open menu")
        self._click_roi(cfg.menu_button_roi, "Menu button")
        self._wait_stable()

        # Step 2: 点击 設定 选项
        logger.debug("Step 2: Select settings")
        self._click_roi(cfg.settings_option_roi, "Settings option")
        self._wait_stable(1.5)

        # Step 3: 点击 ライブ設定 / LIVE 设置 选项
        logger.debug("Step 3: Select live settings")
        self._click_roi(cfg.live_settings_option_roi, "Live settings option")
        self._wait_stable(1.5)

        # Step 4: 验证 — OCR 确认已在 LIVE 设置页面
        frame = self._capture()
        if frame is not None:
            if self._verify_settings_page(frame):
                logger.info("✓ Navigated to live settings page")
                return True

        logger.warning("Navigation: arrived but couldn't verify settings page")
        # 即使无法验证, 也假设导航成功 (后续 OCR 会再次检测)
        return True

    def navigate_back_to_menu(self) -> bool:
        """从设置页面返回主菜单。"""
        cfg = self._resolve_server()

        # 点返回按钮 (2 次, 返回主菜单)
        for i in range(2):
            self._click_roi(cfg.back_button_roi, f"Back button ({i+1})")
            self._wait_stable(0.8)

        # 再点一次确保 (有些服需要额外关闭)
        self._click_roi(cfg.close_button_roi, "Close button")
        self._wait_stable(0.5)

        logger.info("✓ Navigated back to menu")
        return True

    def _verify_settings_page(self, frame: np.ndarray) -> bool:
        """OCR 验证当前画面是否为 LIVE 设置页面。"""
        if not self._init_ocr():
            return False

        cfg = self._resolve_server()

        # 读取标题区域
        title_roi = (0.05, 0.06, 0.60, 0.14)
        try:
            if hasattr(self._ocr, 'read'):
                from vision.ocr import OcrReader
                if isinstance(self._ocr, OcrReader):
                    result = self._ocr.read(frame, roi=title_roi)
                    text = result.text.lower()
                else:
                    # Legacy OcrReader
                    roi_img = self._extract_roi_img(frame, title_roi)
                    text = self._ocr._ocr_text(roi_img).lower() if roi_img is not None else ""
            else:
                return False

            # 检查是否包含设置页面关键词
            keywords = ["live", "ライブ", "설정", "设置", "設定", "setting"]
            return any(kw.lower() in text for kw in keywords)
        except Exception as e:
            logger.debug("Settings page verification failed: %s", e)
            return False

    # ── OCR 读取 ──

    def read_timing_offset(self, frame: np.ndarray = None) -> Optional[int]:
        """OCR 读取 タイミング調整 当前值。

        Returns:
            整数值 (-50 ~ +50), 或 None
        """
        if frame is None:
            frame = self._capture()
        if frame is None:
            return None

        cfg = self._resolve_server()

        for attempt in range(self.OCR_RETRIES):
            value = self._ocr_read_number(frame, cfg.timing_value_roi)
            if value is not None:
                # 范围校验
                t_min, t_max = cfg.timing_range
                if t_min <= value <= t_max:
                    logger.debug("Timing offset read: %+d (attempt %d)", value, attempt + 1)
                    return value
                logger.debug("Timing value %d out of range [%d, %d], retry", value, t_min, t_max)

            if attempt < self.OCR_RETRIES - 1:
                self._wait_stable(0.3)
                frame = self._capture()

        logger.warning("Failed to read timing offset after %d attempts", self.OCR_RETRIES)
        return None

    def read_note_speed(self, frame: np.ndarray = None) -> Optional[float]:
        """OCR 读取 ノーツ速度 当前值。

        Returns:
            浮点值 (1.0 ~ 12.0), 或 None
        """
        if frame is None:
            frame = self._capture()
        if frame is None:
            return None

        cfg = self._resolve_server()

        for attempt in range(self.OCR_RETRIES):
            value = self._ocr_read_number(frame, cfg.speed_value_roi, allow_float=True)
            if value is not None:
                s_min, s_max = cfg.speed_range
                if s_min <= value <= s_max:
                    logger.debug("Note speed read: %.1f (attempt %d)", value, attempt + 1)
                    return value
                logger.debug("Speed value %.1f out of range [%.1f, %.1f], retry",
                            value, s_min, s_max)

            if attempt < self.OCR_RETRIES - 1:
                self._wait_stable(0.3)
                frame = self._capture()

        logger.warning("Failed to read note speed after %d attempts", self.OCR_RETRIES)
        return None

    def _ocr_read_number(self, frame: np.ndarray,
                         roi: tuple, allow_float: bool = False) -> Optional[float]:
        """从指定 ROI 中 OCR 读取数字。

        Args:
            frame: 全屏截图
            roi: (x1, y1, x2, y2) 相对坐标
            allow_float: 是否允许小数

        Returns:
            数字值或 None
        """
        if not self._init_ocr():
            return None

        roi_img = self._extract_roi_img(frame, roi)
        if roi_img is None or roi_img.size == 0:
            return None

        try:
            from vision.ocr import OcrReader as VisionOcr
            if isinstance(self._ocr, VisionOcr):
                result = self._ocr.read(roi_img, roi=None,
                                        whitelist=self.OCR_DIGIT_WHITELIST)
                text = result.text.strip()
            else:
                # Legacy OcrReader
                text = self._ocr._ocr_text(roi_img).strip()
        except Exception as e:
            logger.debug("OCR read error: %s", e)
            return None

        if not text:
            return None

        return self._parse_number(text, allow_float)

    def _parse_number(self, text: str, allow_float: bool = False) -> Optional[float]:
        """从 OCR 文本中解析数字。

        处理 OCR 常见错误: 1→l, 0→O, .=, 等等。

        Args:
            text: OCR 原始文本
            allow_float: 是否接受小数

        Returns:
            解析后的数字或 None
        """
        # 常见 OCR 错误修正
        cleaned = text
        replacements = {
            'l': '1', 'I': '1', '|': '1',
            'O': '0', 'o': '0', 'Q': '0',
            'S': '5', 's': '5',
            'B': '8', 'b': '6',
            'Z': '2', 'z': '2',
            'T': '7',
            ',': '.', '。': '.', '、': '.',
        }
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)

        # 提取数字模式
        if allow_float:
            pattern = r'[-+]?\d+\.?\d*'
        else:
            pattern = r'[-+]?\d+'

        matches = re.findall(pattern, cleaned)
        if not matches:
            return None

        # 取最合理的值 (过滤太短/太长的)
        valid = []
        for m in matches:
            try:
                val = float(m)
                if allow_float:
                    if 0.5 <= val <= 15.0:
                        valid.append(val)
                else:
                    if -99 <= val <= 99:
                        valid.append(val)
            except ValueError:
                continue

        if not valid:
            return None

        # 取中位数 (更鲁棒)
        valid.sort()
        return valid[len(valid) // 2]

    def _extract_roi_img(self, frame: np.ndarray,
                         roi: tuple) -> Optional[np.ndarray]:
        """从全屏截图中提取 ROI。"""
        h, w = frame.shape[:2]
        x1 = max(0, int(roi[0] * w))
        y1 = max(0, int(roi[1] * h))
        x2 = min(w, int(roi[2] * w))
        y2 = min(h, int(roi[3] * h))

        if x2 <= x1 or y2 <= y1:
            return None

        roi_img = frame[y1:y2, x1:x2]

        # 预处理: 放大 + 灰度 + 二值化
        try:
            roi_img = cv2.resize(roi_img, None, fx=2.0, fy=2.0,
                                 interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255,
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return binary
        except Exception:
            return roi_img

    # ── 高层 API ──

    def read_all(self, navigate: bool = True) -> GameSettings:
        """完整流程: 导航 → OCR → 返回。

        Args:
            navigate: 是否自动导航到设置页面

        Returns:
            GameSettings 包含所有读取到的值
        """
        import datetime
        settings = GameSettings(read_time=datetime.datetime.now().isoformat())
        cfg = self._resolve_server()
        settings.server = self._server

        logger.info("=" * 50)
        logger.info("Reading game settings (%s)...", cfg.display_name)
        logger.info("=" * 50)

        # 保存当前画面 (用于恢复)
        original_frame = self._capture()

        try:
            # Step 1: 导航
            if navigate:
                if not self.navigate_to_live_settings():
                    settings.errors.append("Navigation failed")
                    return settings

            # Step 2: OCR 读取
            frame = self._capture()
            if frame is None:
                settings.errors.append("Screenshot failed")
                return settings

            # 尝试通过 OCR 确认/修正服务器
            if self._server == GameServer.AUTO and self._init_ocr():
                try:
                    title_roi = (0.05, 0.06, 0.60, 0.14)
                    title_img = self._extract_roi_img(frame, title_roi)
                    if title_img is not None:
                        from vision.ocr import OcrReader as VisionOcr
                        if isinstance(self._ocr, VisionOcr):
                            result = self._ocr.read(title_img, roi=None)
                            detected = detect_server_by_ocr_labels(result.text)
                            if detected and detected != GameServer.JP:
                                self._server = detected
                                self._server_cfg = get_server_config(detected)
                                cfg = self._server_cfg
                                settings.server = detected
                                logger.info("Server corrected via OCR: %s", detected.value)
                except Exception as e:
                    logger.debug("Server OCR correction failed: %s", e)

            # 读取 timing
            timing = self.read_timing_offset(frame)
            if timing is not None:
                settings.timing_offset = timing
            else:
                settings.errors.append("Failed to read timing offset")

            # 读取 speed
            speed = self.read_note_speed(frame)
            if speed is not None:
                settings.note_speed = speed
            else:
                settings.errors.append("Failed to read note speed")

            # 置信度
            ok_count = sum([
                timing is not None,
                speed is not None,
            ])
            settings.confidence = ok_count / 2.0

            # 保存原始 OCR 文本用于调试
            timing_roi_img = self._extract_roi_img(frame, cfg.timing_value_roi)
            if timing_roi_img is not None and self._init_ocr():
                try:
                    if hasattr(self._ocr, 'read'):
                        from vision.ocr import OcrReader as VisionOcr
                        if isinstance(self._ocr, VisionOcr):
                            r = self._ocr.read(timing_roi_img, roi=None)
                            settings.raw_ocr_text += f"[timing] {r.text}; "
                except Exception:
                    pass

        finally:
            # Step 3: 返回主菜单
            if navigate:
                self.navigate_back_to_menu()

        # 日志
        if settings.is_valid:
            logger.info("✓ Settings read: timing=%+d speed=%.1f (%.0f%%)",
                       settings.timing_offset, settings.note_speed,
                       settings.confidence * 100)
        else:
            logger.warning("✗ Settings read incomplete: %s", settings.errors)

        return settings

    def calibrate(self, settings: GameSettings) -> CalibrationResult:
        """基于读取的设置生成校准参数。"""
        calibrator = SettingsCalibrator.from_config(self._config)
        return calibrator.calibrate(
            timing_offset=settings.timing_offset,
            note_speed=settings.note_speed,
            server=settings.server.value if settings.server != GameServer.AUTO else "",
        )

    def apply_to_config(self, result: CalibrationResult) -> dict:
        """将校准结果应用到 config。

        Returns:
            更新后的 config 字典
        """
        calibrator = SettingsCalibrator.from_config(self._config)
        updates = calibrator.get_config_updates(result)

        # 深度合并
        merged = dict(self._config)
        for section, values in updates.items():
            if section in merged and isinstance(merged[section], dict):
                merged[section] = dict(merged[section])
                merged[section].update(values)
            else:
                merged[section] = dict(values) if isinstance(values, dict) else values

        logger.info("Config updated with calibration results")
        logger.info("  latency_compensation_ms: %.0f → %.0f",
                   self._config.get("timing", {}).get("latency_compensation_ms", 0),
                   result.adjusted_latency_comp_ms)
        logger.info("  advance_ms: %.0f → %.0f",
                   self._config.get("prediction", {}).get("manual_advance_ms", 0),
                   result.adjusted_advance_ms)
        logger.info("  velocity_correction: %.3f",
                   result.velocity_correction_factor)

        return merged

    def read_and_apply(self, navigate: bool = True) -> Optional[CalibrationResult]:
        """一步完成: 读取 + 校准 + 应用。

        这是最常用的入口。

        Args:
            navigate: 是否自动导航

        Returns:
            CalibrationResult 或 None (失败)
        """
        settings = self.read_all(navigate=navigate)
        if not settings.is_valid:
            logger.warning("Cannot calibrate: settings read incomplete")
            return None

        result = self.calibrate(settings)
        self._config = self.apply_to_config(result)
        return result
