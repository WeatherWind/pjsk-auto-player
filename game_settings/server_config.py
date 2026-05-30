"""
游戏服务器/语言配置 — 多服适配核心。

定义各服的 UI 特征、OCR 策略、导航路径。
支持 JP / TW / CN / KR / EN 五个服务器。

PJSK 各服主要差异:
  - 包名不同 (com.sega.ColorfulStage / com.sega.pjsekai.tw 等)
  - UI 文字不同 (タイミング調整 / Timing Adjustment / 判定调整 等)
  - UI 布局基本一致 (同一游戏引擎, 坐标可复用)
  - 字体可能不同 (各服使用各自语言字体)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class GameServer(str, Enum):
    """PJSK 服务器。"""
    JP = "jp"       # 日服
    TW = "tw"       # 台服
    CN = "cn"       # 国服/简中
    KR = "kr"       # 韩服
    EN = "en"       # 国际服
    AUTO = "auto"   # 自动检测


@dataclass
class ServerConfig:
    """单个服务器的完整 UI/OCR 配置。所有 ROIs 使用相对坐标比例 0.0~1.0。"""

    server: GameServer
    display_name: str
    package_patterns: list[str] = field(default_factory=list)
    ocr_lang: list[str] = field(default_factory=list)
    ocr_lang_tesseract: str = ""
    settings_title_label: str = ""
    timing_label: str = ""
    note_speed_label: str = ""
    menu_button_roi: tuple = (0, 0, 0, 0)
    settings_option_roi: tuple = (0, 0, 0, 0)
    live_settings_option_roi: tuple = (0, 0, 0, 0)
    timing_value_roi: tuple = (0, 0, 0, 0)
    speed_value_roi: tuple = (0, 0, 0, 0)
    back_button_roi: tuple = (0, 0, 0, 0)
    close_button_roi: tuple = (0, 0, 0, 0)
    timing_range: tuple = (-50, 50)
    speed_range: tuple = (1.0, 12.0)
    ui_color_theme: tuple = (0, 0, 0)
    description: str = ""


# ── 各服完整配置 ──
# PJSK 设置页面布局在所有服基本一致 (同一引擎)。
# ROI 坐标基于 1080x2400 基准, 运行时乘以实际分辨率。

SERVER_CONFIGS: dict[GameServer, ServerConfig] = {
    GameServer.JP: ServerConfig(
        server=GameServer.JP,
        display_name="日服 (JP)",
        package_patterns=[
            "com.sega.ColorfulStage",
            "com.sega.pjsekai",
            "jp.co.sega.pjsekai",
        ],
        ocr_lang=["ja", "en"],
        ocr_lang_tesseract="jpn+eng",
        settings_title_label="ライブ設定",
        timing_label="タイミング調整",
        note_speed_label="ノーツ速度",
        menu_button_roi=(0.84, 0.04, 0.98, 0.12),
        settings_option_roi=(0.08, 0.36, 0.92, 0.50),
        live_settings_option_roi=(0.08, 0.22, 0.92, 0.36),
        timing_value_roi=(0.28, 0.22, 0.72, 0.36),
        speed_value_roi=(0.28, 0.40, 0.72, 0.54),
        back_button_roi=(0.02, 0.03, 0.12, 0.10),
        close_button_roi=(0.84, 0.03, 0.98, 0.10),
        timing_range=(-50, 50),
        speed_range=(1.0, 12.0),
        ui_color_theme=(0, 170, 255),
        description="日服: タイミング調整 + ノーツ速度",
    ),
    GameServer.TW: ServerConfig(
        server=GameServer.TW,
        display_name="台服 (TW)",
        package_patterns=[
            "com.sega.pjsekai.tw",
            "com.sega.ColorfulStage.tw",
        ],
        ocr_lang=["ch_tra", "en"],
        ocr_lang_tesseract="chi_tra+eng",
        settings_title_label="LIVE設定",
        timing_label="時機調整",
        note_speed_label="音符速度",
        menu_button_roi=(0.84, 0.04, 0.98, 0.12),
        settings_option_roi=(0.08, 0.36, 0.92, 0.50),
        live_settings_option_roi=(0.08, 0.22, 0.92, 0.36),
        timing_value_roi=(0.28, 0.22, 0.72, 0.36),
        speed_value_roi=(0.28, 0.40, 0.72, 0.54),
        back_button_roi=(0.02, 0.03, 0.12, 0.10),
        close_button_roi=(0.84, 0.03, 0.98, 0.10),
        timing_range=(-50, 50),
        speed_range=(1.0, 12.0),
        ui_color_theme=(0, 170, 255),
        description="台服: 時機調整 + 音符速度",
    ),
    GameServer.CN: ServerConfig(
        server=GameServer.CN,
        display_name="国服 (CN)",
        package_patterns=[
            "com.tencent.pjsk",
            "com.sega.pjsekai.cn",
            "com.tencent.pjsekai",
        ],
        ocr_lang=["ch_sim", "en"],
        ocr_lang_tesseract="chi_sim+eng",
        settings_title_label="LIVE设置",
        timing_label="判定调整",
        note_speed_label="音符速度",
        menu_button_roi=(0.84, 0.04, 0.98, 0.12),
        settings_option_roi=(0.08, 0.36, 0.92, 0.50),
        live_settings_option_roi=(0.08, 0.22, 0.92, 0.36),
        timing_value_roi=(0.28, 0.22, 0.72, 0.36),
        speed_value_roi=(0.28, 0.40, 0.72, 0.54),
        back_button_roi=(0.02, 0.03, 0.12, 0.10),
        close_button_roi=(0.84, 0.03, 0.98, 0.10),
        timing_range=(-50, 50),
        speed_range=(1.0, 12.0),
        ui_color_theme=(0, 170, 255),
        description="国服: 判定调整 + 音符速度",
    ),
    GameServer.KR: ServerConfig(
        server=GameServer.KR,
        display_name="韩服 (KR)",
        package_patterns=[
            "com.sega.pjsekai.kr",
            "com.sega.ColorfulStage.kr",
        ],
        ocr_lang=["ko", "en"],
        ocr_lang_tesseract="kor+eng",
        settings_title_label="라이브 설정",
        timing_label="타이밍 조정",
        note_speed_label="노트 속도",
        menu_button_roi=(0.84, 0.04, 0.98, 0.12),
        settings_option_roi=(0.08, 0.36, 0.92, 0.50),
        live_settings_option_roi=(0.08, 0.22, 0.92, 0.36),
        timing_value_roi=(0.28, 0.22, 0.72, 0.36),
        speed_value_roi=(0.28, 0.40, 0.72, 0.54),
        back_button_roi=(0.02, 0.03, 0.12, 0.10),
        close_button_roi=(0.84, 0.03, 0.98, 0.10),
        timing_range=(-50, 50),
        speed_range=(1.0, 12.0),
        ui_color_theme=(0, 170, 255),
        description="韩服: 타이밍 조정 + 노트 속도",
    ),
    GameServer.EN: ServerConfig(
        server=GameServer.EN,
        display_name="国际服 (EN)",
        package_patterns=[
            "com.sega.ColorfulStage.en",
            "com.sega.pjsekai.en",
        ],
        ocr_lang=["en"],
        ocr_lang_tesseract="eng",
        settings_title_label="Live Settings",
        timing_label="Timing Adjustment",
        note_speed_label="Note Speed",
        menu_button_roi=(0.84, 0.04, 0.98, 0.12),
        settings_option_roi=(0.08, 0.36, 0.92, 0.50),
        live_settings_option_roi=(0.08, 0.22, 0.92, 0.36),
        timing_value_roi=(0.28, 0.22, 0.72, 0.36),
        speed_value_roi=(0.28, 0.40, 0.72, 0.54),
        back_button_roi=(0.02, 0.03, 0.12, 0.10),
        close_button_roi=(0.84, 0.03, 0.98, 0.10),
        timing_range=(-50, 50),
        speed_range=(1.0, 12.0),
        ui_color_theme=(0, 170, 255),
        description="国际服: Timing Adjustment + Note Speed",
    ),
}


def detect_server(package_name: str) -> Optional[GameServer]:
    """根据包名自动检测服务器。

    使用优先级列表从最具体到最通用匹配，避免误判。
    JP 的 "com.sega.ColorfulStage" 模式太通用，放在最后检查。
    """
    if not package_name:
        return None
    pkg_lower = package_name.lower()

    # 按优先级从最具体到最通用排列
    priority_check: list[tuple[GameServer, list[str]]] = [
        (GameServer.TW, [".tw", "taiwan"]),
        (GameServer.KR, [".kr", "korea"]),
        (GameServer.EN, [".en", "global", "english"]),
        (GameServer.CN, ["tencent", ".cn", "china", "bilibili"]),
        (GameServer.JP, ["com.sega"]),  # 最后 fallback
    ]

    for server, patterns in priority_check:
        for pat in patterns:
            if pat.lower() in pkg_lower:
                return server

    if "pjsekai" in pkg_lower or "colorfulstage" in pkg_lower:
        return GameServer.JP

    return None


def detect_server_by_ocr_labels(ocr_text: str) -> Optional[GameServer]:
    """根据 OCR 识别的设置页面文字检测服务器。"""
    server_scores: dict[GameServer, int] = {}
    text_lower = ocr_text.lower()
    for server, cfg in SERVER_CONFIGS.items():
        if server == GameServer.AUTO:
            continue
        score = 0
        if cfg.settings_title_label.lower() in text_lower:
            score += 3
        if cfg.timing_label.lower() in text_lower:
            score += 2
        if cfg.note_speed_label.lower() in text_lower:
            score += 2
        if score > 0:
            server_scores[server] = score
    if server_scores:
        return max(server_scores, key=server_scores.get)
    return None


def get_server_config(server: GameServer) -> ServerConfig:
    """获取指定服务器的完整配置。"""
    if server == GameServer.AUTO:
        return SERVER_CONFIGS[GameServer.JP]
    return SERVER_CONFIGS.get(server, SERVER_CONFIGS[GameServer.JP])


def get_all_servers() -> list[GameServer]:
    """获取所有可用服务器列表 (不含 AUTO)。"""
    return [s for s in SERVER_CONFIGS if s != GameServer.AUTO]
