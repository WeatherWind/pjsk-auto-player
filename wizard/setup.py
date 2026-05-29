#!/usr/bin/env python3
"""
PJSK Auto Player — 设置向导 V2

交互式 CLI 向导，引导用户完成首次配置：
  1. 选择语言
  2. 连接手机 (ADB 自动检测)
  3. 屏幕校准 (自动检测分辨率 + 判定线位置)
  4. 选择打歌模式 (AP/FC/LIVE/冲榜)
  5. 保存配置 → 完成

用法:
    pjsk setup              # 交互式设置
    pjsk setup --auto       # 静默校准 (无交互)
"""

import argparse
import logging
import os
import shutil
import sys
import time
from typing import Optional

logger = logging.getLogger("pjsk.wizard")

# ── ANSI 终端颜色 ────────────────────────────────────────────
C_RESET = "\033[0m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"
C_RED = "\033[31m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_MAGENTA = "\033[35m"


# ── 语言支持 ─────────────────────────────────────────────────
LANGUAGES = {
    "1": {"name": "中文", "code": "zh"},
    "2": {"name": "English", "code": "en"},
    "3": {"name": "日本語", "code": "ja"},
}

PLAY_MODES = {
    "1": {"key": "ap",  "label_zh": "AP (All Perfect)",       "label_en": "AP (All Perfect)"},
    "2": {"key": "fc",  "label_zh": "FC (Full Combo)",        "label_en": "FC (Full Combo)"},
    "3": {"key": "live", "label_zh": "LIVE (自由打歌)",         "label_en": "LIVE (Free Play)"},
    "4": {"key": "auto", "label_zh": "冲榜 (自动无限循环)",     "label_en": "Auto (Rank Push)"},
}


def _t(zh: str, en: str, ja: str, lang: str) -> str:
    """多语言文本选择。"""
    if lang == "en":
        return en
    elif lang == "ja":
        return ja
    return zh


# ── UI 辅助函数 ──────────────────────────────────────────────

def print_banner():
    """打印启动横幅。"""
    print()
    print(f"  {C_CYAN}╔══════════════════════════════════════════╗{C_RESET}")
    print(f"  {C_CYAN}║  {C_BOLD}PJSK Auto Player — 设置向导 V2{C_RESET}{C_CYAN}   ║{C_RESET}")
    print(f"  {C_CYAN}╚══════════════════════════════════════════╝{C_RESET}")
    print()


def step(msg: str, status: str = "..."):
    """打印带有状态标记的步骤行。"""
    status_color = {
        "✓": C_GREEN, "✗": C_RED, "→": C_YELLOW, "...": C_DIM, "ℹ": C_CYAN,
    }.get(status, C_DIM)
    print(f"  [{status_color}{status}{C_RESET}] {msg}")


def prompt(prompt_text: str, default: str = "", lang: str = "zh") -> str:
    """带默认值的提示输入。"""
    hint = f" [{default}]" if default else ""
    val = input(f"  {C_CYAN}?{C_RESET} {prompt_text}{hint}: ").strip()
    return val if val else default


def prompt_choice(
    prompt_text: str,
    options: dict,
    default: str = "1",
    lang: str = "zh",
) -> str:
    """菜单选择：展示选项列表并返回选中项的 key。"""
    print(f"  {C_CYAN}?{C_RESET} {prompt_text}")
    for key, opt in options.items():
        label = opt.get(f"label_{lang[:2]}", opt.get("name", opt.get("label_zh", key)))
        print(f"    {key}. {label}")
    while True:
        choice = input(f"    请选择 [{default}]: ").strip()
        if not choice:
            choice = default
        if choice in options:
            return options[choice].get("key", choice)
        print(f"  {C_RED}    无效选择，请重试{C_RESET}")


def confirm(prompt_text: str, default: bool = True, lang: str = "zh") -> bool:
    """是/否确认。"""
    hint = "Y/n" if default else "y/N"
    while True:
        ans = input(f"  {C_CYAN}?{C_RESET} {prompt_text} [{hint}] ").strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes", "是"):
            return True
        if ans in ("n", "no", "否"):
            return False


# ══════════════════════════════════════════════════════════════
#  SetUpWizard
# ══════════════════════════════════════════════════════════════

class SetupWizard:
    """
    PJSK Auto Player 交互式设置向导 V2。

    参数:
        profile: 配置档案名 (可选)
        auto: 静默模式，跳过交互输入

    用法:
        wizard = SetupWizard(profile="default")
        wizard.run()
    """

    def __init__(self, profile: str = "", auto: bool = False):
        self.profile = profile or "default"
        self.auto = auto
        self.lang = "zh"  # 默认语言
        self.config: dict = {}  # 运行时配置快照
        self.device_serial: str = ""
        self.screen_w: int = 1080
        self.screen_h: int = 2400
        self.judgment_line_y: float = 0.0
        self.play_mode: str = "live"
        self.adb = None  # 懒加载 ADBController

        # 尝试导入已有配置
        self._load_existing_config()

    # ── 配置加载 ─────────────────────────────────────────────

    def _load_existing_config(self):
        """加载现有配置作为默认值。"""
        try:
            from config import get_config_loader
            loader = get_config_loader()
            cfg = loader.load(profile=self.profile)
            self.config = cfg or {}
        except Exception:
            self.config = {}

        # 从现有配置提取默认值
        adb_cfg = self.config.get("adb", {})
        screen_cfg = self.config.get("screen", {})
        play_cfg = self.config.get("play", {})

        self.device_serial = adb_cfg.get("device_serial", "")
        self.screen_w = screen_cfg.get("width", 1080)
        self.screen_h = screen_cfg.get("height", 2400)
        self.judgment_line_y = screen_cfg.get("judgment_line_y", 0.0)
        self.play_mode = play_cfg.get("mode", "live")

    # ── 主入口 ───────────────────────────────────────────────

    def run(self):
        """启动交互式设置向导。"""
        print_banner()

        # 步骤 1: 选择语言
        self._step_language()

        if not self.auto:
            input(f"  {C_DIM}{_t('按 Enter 开始设置...', 'Press Enter to start setup...', 'Enter キーを押して設定を開始...', self.lang)}{C_RESET}")
            print()

        # 步骤 2: 连接手机
        self._step_adb_device()

        # 步骤 3: 屏幕校准
        self._step_calibrate()

        # 步骤 4: 选择打歌模式
        self._step_play_mode()

        # 步骤 5: 保存配置
        self._step_save()

        # 完成
        self._print_summary()

    # ── 步骤 1: 选择语言 ─────────────────────────────────────

    def _step_language(self):
        """选择界面语言 (中文 / English / 日本語)。"""
        if self.auto:
            self.lang = "zh"
            step(_t("语言: 中文", "Language: English", "言語: 日本語", self.lang), "✓")
            return

        step(_t("选择语言", "Select Language", "言語を選択", self.lang), "→")
        for key, lang_info in LANGUAGES.items():
            print(f"    {key}. {lang_info['name']}")

        choice = prompt(
            _t("请选择语言", "Select language", "言語を選択", self.lang),
            default="1",
            lang=self.lang,
        )
        if choice in LANGUAGES:
            self.lang = LANGUAGES[choice]["code"]
        step(
            _t("语言: 中文", "Language: English", "言語: 日本語", self.lang),
            "✓",
        )
        print()

    # ── 步骤 2: 连接手机 ─────────────────────────────────────

    def _step_adb_device(self):
        """ADB 自动检测 + 设备列表 + 连接确认。"""
        step(
            _t("检测 ADB 连接...", "Detecting ADB connection...", "ADB 接続を検出中...", self.lang),
            "...",
        )

        # ─ 查找 ADB 可执行文件 ─
        adb_exe = self._find_adb()
        if not adb_exe:
            step(
                _t("未找到 ADB", "ADB not found", "ADB が見つかりません", self.lang),
                "✗",
            )
            if not self.auto:
                print(f"  {C_YELLOW}  {_t('请安装 Android SDK Platform-Tools:', 'Please install Android SDK Platform-Tools:', 'Android SDK Platform-Tools をインストールしてください:', self.lang)}{C_RESET}")
                print(f"    https://developer.android.com/studio/releases/platform-tools")
                adb_path = prompt(
                    _t("手动输入 ADB 路径", "Enter ADB path manually", "ADB パスを手動入力", self.lang),
                    default="adb",
                    lang=self.lang,
                )
                if adb_path and adb_path != "adb":
                    adb_exe = adb_path
                else:
                    adb_exe = shutil.which("adb") or "adb"
            else:
                adb_exe = "adb"

        # ─ 初始化 ADB 控制器 ─
        self._init_adb(adb_exe)

        # ─ 列出设备 ─
        devices = self._list_devices()
        if not devices:
            step(
                _t("未检测到设备", "No devices detected", "デバイスが検出されませんでした", self.lang),
                "✗",
            )
            if self.auto:
                return

            print(f"  {C_YELLOW}  {_t('请检查:', 'Please check:', '確認してください:', self.lang)}{C_RESET}")
            print(f"    - {_t('USB 线是否连接', 'USB cable is connected', 'USB ケーブルが接続されている', self.lang)}")
            print(f"    - {_t('手机上 USB 调试是否开启', 'USB Debugging is enabled on the phone', 'スマホで USB デバッグが有効になっている', self.lang)}")
            print(f"    - {_t('是否已授权电脑', 'Computer is authorized', 'PC が認証されている', self.lang)}")
            input(f"  {C_DIM}{_t('连接后按 Enter 重试...', 'Press Enter after connecting...', '接続後 Enter キーを押してください...', self.lang)}{C_RESET}")
            devices = self._list_devices()

        # ─ 选择设备 ─
        if not devices:
            step(
                _t("跳过 (无设备)", "Skipped (no device)", "スキップ (デバイスなし)", self.lang),
                "✗",
            )
            return

        self._select_device(devices)

        # ─ 获取屏幕尺寸 ─
        self._fetch_screen_size()

    def _find_adb(self) -> Optional[str]:
        """在 PATH 和配置中查找 ADB 可执行文件。"""
        # 优先使用配置文件中的路径
        adb_cfg = self.config.get("adb", {})
        if "executable" in adb_cfg and os.path.exists(adb_cfg["executable"]):
            return adb_cfg["executable"]

        for exe in ["adb", "adb.exe"]:
            path = shutil.which(exe)
            if path:
                return path
        return None

    def _init_adb(self, adb_exe: str):
        """初始化 ADBController。"""
        try:
            from adb_controller import ADBController
            self.adb = ADBController({"adb": {"executable": adb_exe}})
            step(
                _t("ADB 已就绪", "ADB ready", "ADB 準備完了", self.lang),
                "✓",
            )
        except Exception as e:
            step(
                _t(f"ADB 初始化失败: {e}", f"ADB init failed: {e}", f"ADB 初期化失敗: {e}", self.lang),
                "✗",
            )
            self.adb = None

    def _list_devices(self) -> list:
        """列出连接的设备。"""
        if not self.adb:
            return []
        try:
            step(
                _t("扫描已连接的设备...", "Scanning connected devices...", "接続デバイスをスキャン中...", self.lang),
                "...",
            )
            devices = self.adb.devices()
            return devices
        except Exception as e:
            logger.warning(f"设备扫描失败: {e}")
            return []

    def _select_device(self, devices: list):
        """从设备列表中选择一台设备。"""
        if len(devices) == 1:
            self.device_serial = devices[0]["serial"]
            step(
                _t(f"设备: {self.device_serial}", f"Device: {self.device_serial}", f"デバイス: {self.device_serial}", self.lang),
                "✓",
            )
        else:
            step(
                _t(f"发现 {len(devices)} 台设备", f"Found {len(devices)} devices", f"{len(devices)} 台のデバイスを検出", self.lang),
                "→",
            )
            for i, d in enumerate(devices):
                print(f"    {i+1}. {d['serial']} ({d.get('status', 'device')})")

            if self.auto:
                self.device_serial = devices[0]["serial"]
            else:
                idx_str = prompt(
                    _t("选择设备编号", "Select device number", "デバイス番号を選択", self.lang),
                    default="1",
                    lang=self.lang,
                )
                try:
                    idx = int(idx_str) - 1
                    self.device_serial = devices[idx]["serial"]
                except (ValueError, IndexError):
                    self.device_serial = devices[0]["serial"]

            step(
                _t(f"已选择: {self.device_serial}", f"Selected: {self.device_serial}", f"選択: {self.device_serial}", self.lang),
                "✓",
            )

        # 将设备序列号写入临时配置
        if "adb" not in self.config:
            self.config["adb"] = {}
        self.config["adb"]["device_serial"] = self.device_serial

    def _fetch_screen_size(self):
        """从设备获取屏幕分辨率。"""
        if not self.adb or not self.device_serial:
            return
        try:
            w, h = self.adb.get_screen_size()
            self.screen_w, self.screen_h = w, h
            if "screen" not in self.config:
                self.config["screen"] = {}
            self.config["screen"]["width"] = w
            self.config["screen"]["height"] = h
            step(
                _t(f"屏幕: {w}x{h}", f"Screen: {w}x{h}", f"画面: {w}x{h}", self.lang),
                "✓",
            )
        except Exception as e:
            step(
                _t(f"获取屏幕尺寸失败: {e}", f"Failed to get screen size: {e}", f"画面サイズ取得失敗: {e}", self.lang),
                "✗",
            )

    # ── 步骤 3: 屏幕校准 ─────────────────────────────────────

    def _step_calibrate(self):
        """自动检测分辨率 + 判定线位置。"""
        if self.auto:
            self._auto_calibrate()
            return

        step(
            _t("屏幕校准", "Screen Calibration", "画面キャリブレーション", self.lang),
            "→",
        )
        print(f"  {C_DIM}  {_t('将自动检测: 分辨率 / 判定线位置 / 轨道区域', 'Will auto-detect: resolution / judgment line / lane area', '自動検出: 解像度 / 判定線 / レーン位置', self.lang)}{C_RESET}")

        if not confirm(
            _t("开始校准?", "Start calibration?", "キャリブレーションを開始しますか?", self.lang),
            default=True,
            lang=self.lang,
        ):
            step(
                _t("跳过校准", "Skipped calibration", "キャリブレーションをスキップ", self.lang),
                "→",
            )
            return

        print()
        self._auto_calibrate()

    def _auto_calibrate(self):
        """静默校准: 截屏 → 分析判定线 → 分析轨道。"""
        if not self.adb or not self.device_serial:
            step(
                _t("跳过 (设备未连接)", "Skipped (device not connected)", "スキップ (デバイス未接続)", self.lang),
                "✗",
            )
            return

        step(
            _t("截取屏幕...", "Capturing screen...", "画面をキャプチャ中...", self.lang),
            "...",
        )

        try:
            frame = self.adb.screencap()
        except Exception as e:
            step(
                _t(f"截图失败: {e}", f"Screenshot failed: {e}", f"スクリーンショット失敗: {e}", self.lang),
                "✗",
            )
            return

        if frame is None:
            step(
                _t("截图为空", "Screenshot is empty", "スクリーンショットが空です", self.lang),
                "✗",
            )
            return

        h, w = frame.shape[:2]
        self.screen_w, self.screen_h = w, h
        if "screen" not in self.config:
            self.config["screen"] = {}
        self.config["screen"]["width"] = w
        self.config["screen"]["height"] = h
        step(
            _t(f"分辨率: {w}x{h}", f"Resolution: {w}x{h}", f"解像度: {w}x{h}", self.lang),
            "✓",
        )

        # ─ 判定线校准 ─
        step(
            _t("检测判定线位置...", "Detecting judgment line...", "判定線位置を検出中...", self.lang),
            "...",
        )
        try:
            from screen_analyzer import ScreenAnalyzer
            analyzer = ScreenAnalyzer(self.config)
            judgment_y = analyzer.calibrate_judgment_line(frame)
            if judgment_y:
                ratio = round(judgment_y / h, 4)
                self.judgment_line_y = ratio
                self.config["screen"]["judgment_line_y"] = ratio
                step(
                    _t(f"判定线 Y = {judgment_y} ({ratio})", f"Judgment line Y = {judgment_y} ({ratio})", f"判定線 Y = {judgment_y} ({ratio})", self.lang),
                    "✓",
                )
            else:
                step(
                    _t("未检测到判定线，使用默认值", "No judgment line detected, using default", "判定線が検出されませんでした、デフォルト値を使用", self.lang),
                    "→",
                )
        except ImportError:
            step(
                _t("screen_analyzer 不可用，跳过判定线校准", "screen_analyzer not available, skipping judgment line", "screen_analyzer が利用できません、判定線キャリブレーションをスキップ", self.lang),
                "→",
            )
        except Exception as e:
            step(
                _t(f"判定线校准失败: {e}", f"Judgment line calibration failed: {e}", f"判定線キャリブレーション失敗: {e}", self.lang),
                "✗",
            )

        # ─ 轨道校准 ─
        step(
            _t("检测轨道位置...", "Detecting lanes...", "レーン位置を検出中...", self.lang),
            "...",
        )
        try:
            from screen_analyzer import ScreenAnalyzer
            analyzer = ScreenAnalyzer(self.config)
            lanes = analyzer.calibrate_lanes(frame)
            if lanes:
                lane_ratios = [round(x / w, 4) for x in lanes]
                mid = w // 2
                left = [r for r, x in zip(lane_ratios, lanes) if x < mid]
                right = [r for r, x in zip(lane_ratios, lanes) if x >= mid]
                if left:
                    self.config["screen"]["left_lanes"] = left
                if right:
                    self.config["screen"]["right_lanes"] = right
                step(
                    _t(f"轨道: 左 {left} | 右 {right}", f"Lanes: left {left} | right {right}", f"レーン: 左 {left} | 右 {right}", self.lang),
                    "✓",
                )
            else:
                step(
                    _t("未检测到轨道", "No lanes detected", "レーンが検出されませんでした", self.lang),
                    "→",
                )
        except ImportError:
            step(
                _t("screen_analyzer 不可用，跳过轨道校准", "screen_analyzer not available, skipping lane calibration", "screen_analyzer が利用できません、レーンキャリブレーションをスキップ", self.lang),
                "→",
            )
        except Exception as e:
            step(
                _t(f"轨道校准失败: {e}", f"Lane calibration failed: {e}", f"レーンキャリブレーション失敗: {e}", self.lang),
                "✗",
            )

        step(
            _t("校准完成", "Calibration complete", "キャリブレーション完了", self.lang),
            "✓",
        )
        print()

    # ── 步骤 4: 选择打歌模式 ─────────────────────────────────

    def _step_play_mode(self):
        """选择打歌模式: AP / FC / LIVE / 冲榜。"""
        if self.auto:
            self.play_mode = "live"
            step(
                _t("打歌模式: LIVE", "Play mode: LIVE", "プレイモード: LIVE", self.lang),
                "✓",
            )
            return

        step(
            _t("选择打歌模式", "Select Play Mode", "プレイモードを選択", self.lang),
            "→",
        )

        mode_key = prompt_choice(
            _t("请选择默认打歌模式", "Select default play mode", "デフォルトのプレイモードを選択", self.lang),
            options=PLAY_MODES,
            default="3",
            lang=self.lang,
        )
        self.play_mode = mode_key

        if "play" not in self.config:
            self.config["play"] = {}
        self.config["play"]["mode"] = mode_key

        mode_labels = {
            "ap": _t("AP (All Perfect)", "AP (All Perfect)", "AP (All Perfect)", self.lang),
            "fc": _t("FC (Full Combo)", "FC (Full Combo)", "FC (Full Combo)", self.lang),
            "live": _t("LIVE (自由打歌)", "LIVE (Free Play)", "LIVE (フリープレイ)", self.lang),
            "auto": _t("冲榜 (自动无限循环)", "Auto (Rank Push)", "自動 (ランクプッシュ)", self.lang),
        }
        step(
            _t(f"打歌模式: {mode_labels.get(mode_key, mode_key)}", f"Play mode: {mode_labels.get(mode_key, mode_key)}", f"プレイモード: {mode_labels.get(mode_key, mode_key)}", self.lang),
            "✓",
        )
        print()

    # ── 步骤 5: 保存配置 ─────────────────────────────────────

    def _step_save(self):
        """保存配置到文件。"""
        step(
            _t("保存配置...", "Saving config...", "設定を保存中...", self.lang),
            "...",
        )

        try:
            from config import get_config_loader
            loader = get_config_loader()

            # 确保关键字段存在
            if "adb" not in self.config:
                self.config["adb"] = {}
            if self.device_serial:
                self.config["adb"]["device_serial"] = self.device_serial

            if "screen" not in self.config:
                self.config["screen"] = {}
            self.config["screen"]["width"] = self.screen_w
            self.config["screen"]["height"] = self.screen_h
            if self.judgment_line_y:
                self.config["screen"]["judgment_line_y"] = self.judgment_line_y

            if "play" not in self.config:
                self.config["play"] = {}
            self.config["play"]["mode"] = self.play_mode

            loader.save_profile(self.profile, self.config)
            step(
                _t(f"配置已保存到档案: {self.profile}", f"Config saved to profile: {self.profile}", f"設定を保存: {self.profile}", self.lang),
                "✓",
            )
        except ImportError:
            # fallback: 直接写入 config.yaml
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config.yaml",
            )
            try:
                import yaml
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(self.config, f, default_flow_style=False,
                              allow_unicode=True, sort_keys=False)
                step(
                    _t(f"配置已保存到 {config_path}", f"Config saved to {config_path}", f"設定を保存: {config_path}", self.lang),
                    "✓",
                )
            except Exception as e:
                step(
                    _t(f"保存失败: {e}", f"Save failed: {e}", f"保存失敗: {e}", self.lang),
                    "✗",
                )
        except Exception as e:
            step(
                _t(f"保存失败: {e}", f"Save failed: {e}", f"保存失敗: {e}", self.lang),
                "✗",
            )

    # ── 结束 ─────────────────────────────────────────────────

    def _print_summary(self):
        """打印设置完成摘要。"""
        print()
        print(f"  {C_GREEN}{'='*52}{C_RESET}")
        print(f"  {C_GREEN}✅ {_t('设置完成!', 'Setup Complete!', '設定完了!', self.lang)}{C_RESET}")
        print(f"  {C_GREEN}{'='*52}{C_RESET}")
        print()

        mode_zh = {"ap": "AP", "fc": "FC", "live": "LIVE", "auto": "冲榜"}
        mode_en = {"ap": "AP", "fc": "FC", "live": "LIVE", "auto": "Auto"}

        print(f"    {_t('设备', 'Device', 'デバイス', self.lang)}:     {self.device_serial or '-'}")
        print(f"    {_t('屏幕', 'Screen', '画面', self.lang)}:       {self.screen_w}x{self.screen_h}")
        print(f"    {_t('模式', 'Mode', 'モード', self.lang)}:       {mode_zh.get(self.play_mode, self.play_mode)}")
        if self.judgment_line_y:
            print(f"    {_t('判定线', 'Judge Line', '判定線', self.lang)}:  {self.judgment_line_y:.4f}")
        print()

        print(f"    {C_CYAN}{_t('快速启动:', 'Quick Start:', 'クイックスタート:', self.lang)}{C_RESET}")
        print(f"      pjsk start              {_t('开始打歌', 'Start playing', 'プレイ開始', self.lang)}")
        print(f"      pjsk start --mode ap     {_t('AP 模式', 'AP mode', 'AP モード', self.lang)}")
        print(f"      pjsk auto               {_t('冲榜模式', 'Auto mode', '自動モード', self.lang)}")
        print(f"      pjsk web                {_t('Web 控制面板', 'Web dashboard', 'Web ダッシュボード', self.lang)}")
        print()

        print(f"  {C_DIM}{_t('💡 提示: 首次打歌前请确保手机已进入选歌界面', '💡 Tip: Ensure the phone is on the song selection screen before first play', '💡 ヒント: 最初のプレイ前にスマホが曲選択画面にあることを確認してください', self.lang)}{C_RESET}")
        print()


# ══════════════════════════════════════════════════════════════
#  CLI Entry Point
# ══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="PJSK Auto Player 设置向导 V2")
    parser.add_argument("--auto", action="store_true", help="静默模式 (无需交互)")
    parser.add_argument("--profile", "-p", default="", help="配置档案名")
    args = parser.parse_args()

    wizard = SetupWizard(profile=args.profile, auto=args.auto)
    wizard.run()


if __name__ == "__main__":
    main()
