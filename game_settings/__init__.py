"""
Game Settings Reader — 游戏内设置自动读取 + 多服适配。

自动导航到 PJSK 游戏设置页面 (ライブ設定),
OCR 读取时延(タイミング調整)和音符速度(ノーツ速度),
自动映射到软件参数并校准预测引擎。

支持服务器: JP / TW / CN / KR / EN (含自动检测)。

用法:
    from game_settings import GameSettingsReader, detect_server

    # 自动检测
    reader = GameSettingsReader(controller, config)
    settings = reader.read_all()
    print(f"Timing: {settings.timing_offset}, Speed: {settings.note_speed}")

    # 指定服务器
    reader = GameSettingsReader(controller, config, server=GameServer.JP)
    reader.apply_to_config()
"""
from game_settings.server_config import (
    GameServer,
    ServerConfig,
    SERVER_CONFIGS,
    detect_server,
    detect_server_by_ocr_labels,
    get_server_config,
    get_all_servers,
)
from game_settings.reader import GameSettingsReader, GameSettings
from game_settings.calibrator import SettingsCalibrator, CalibrationResult

__all__ = [
    "GameServer",
    "ServerConfig",
    "SERVER_CONFIGS",
    "GameSettingsReader",
    "GameSettings",
    "SettingsCalibrator",
    "CalibrationResult",
    "detect_server",
    "detect_server_by_ocr_labels",
    "get_server_config",
    "get_all_servers",
]
