"""
PJSK Auto Player — 配置 Schema 校验 (JSON Schema-based).

基于 ALAS config/template.json 设计理念。
验证配置文件的完整性和类型正确性，前端可据此自动生成配置表单。

用法:
    from config.schema import validate_config, CONFIG_SCHEMA

    errors = validate_config(my_config)
    if errors:
        for e in errors:
            print(f"{e['path']}: {e['message']}")
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("pjsk.config.schema")


# ── Schema 类型定义 ──

CONFIG_SCHEMA: dict[str, dict] = {
    "adb": {
        "type": "object",
        "required": False,
        "description": "ADB 连接配置",
        "properties": {
            "executable": {"type": "str", "default": "adb", "description": "ADB 可执行文件路径"},
            "device_serial": {"type": "str", "default": "", "description": "设备序列号"},
            "screencap_method": {
                "type": "str",
                "default": "auto",
                "choices": ["auto", "exec-out", "file", "scrcpy"],
                "description": "截图方法",
            },
            "temp_dir": {"type": "str", "default": "/sdcard/", "description": "截图临时目录"},
            "auto_connect": {"type": "bool", "default": True, "description": "自动连接"},
            "reconnect_delay": {"type": "float", "default": 2.0, "description": "重连延迟 (秒)"},
            "max_reconnect_attempts": {"type": "int", "default": 30, "description": "最大重连次数"},
        },
    },
    "scrcpy": {
        "type": "object",
        "required": False,
        "description": "scrcpy 后端配置",
        "properties": {
            "executable": {"type": "str", "default": "scrcpy", "description": "scrcpy 路径"},
            "max_fps": {"type": "int", "default": 60, "min": 1, "max": 120},
            "bit_rate": {"type": "int", "default": 12000000},
            "scale": {"type": "float", "default": 0.5, "min": 0.1, "max": 1.0},
            "frame_skip": {"type": "bool", "default": True},
            "auto_install": {"type": "bool", "default": True},
        },
    },
    "screen": {
        "type": "object",
        "required": True,
        "description": "屏幕参数",
        "properties": {
            "width": {"type": "int", "default": 1080, "min": 1},
            "height": {"type": "int", "default": 2400, "min": 1},
            "judgment_line_y": {"type": "float", "default": 0.78, "min": 0.0, "max": 1.0},
            "detection_top_ratio": {"type": "float", "default": 0.35, "min": 0.0, "max": 1.0},
            "lane_count": {"type": "int", "default": 5, "min": 1, "max": 10},
        },
    },
    "play": {
        "type": "object",
        "required": False,
        "description": "执行参数",
        "properties": {
            "mode": {
                "type": "str",
                "default": "live",
                "choices": ["ap", "fc", "live", "auto"],
                "description": "执行模式",
            },
            "infinite": {"type": "bool", "default": False},
            "randomize_clicks": {"type": "bool", "default": True},
            "jitter_ms": {"type": "int", "default": 15, "min": 0, "max": 100},
            "position_jitter_px": {"type": "int", "default": 5, "min": 0, "max": 50},
            "miss_rate": {"type": "float", "default": 0.001, "min": 0.0, "max": 0.1},
        },
    },
    "pid": {
        "type": "object",
        "required": False,
        "description": "PID 自适应延迟",
        "properties": {
            "enabled": {"type": "bool", "default": True},
            "kp": {"type": "float", "default": 0.3, "min": 0.0},
            "ki": {"type": "float", "default": 0.05, "min": 0.0},
            "kd": {"type": "float", "default": 0.1, "min": 0.0},
            "auto_tune": {"type": "bool", "default": True},
        },
    },
    "pipeline": {
        "type": "object",
        "required": False,
        "description": "Pipeline 配置",
        "properties": {
            "task_timeout": {"type": "int", "default": 300, "min": 1},
            "default_retry_times": {"type": "int", "default": 5, "min": 0},
            "screenshot_interval": {"type": "float", "default": 0.1, "min": 0.01},
        },
    },
    "web": {
        "type": "object",
        "required": False,
        "properties": {
            "enabled": {"type": "bool", "default": True},
            "port": {"type": "int", "default": 8080, "min": 1, "max": 65535},
            "host": {"type": "str", "default": "0.0.0.0"},
            "dark_mode": {"type": "bool", "default": True},
            "auto_open_browser": {"type": "bool", "default": False},
        },
    },
    "game_settings": {
        "type": "object",
        "required": False,
        "description": "游戏内设置自动读取",
        "properties": {
            "auto_read": {"type": "bool", "default": True, "description": "启动时自动读取"},
            "frequency": {
                "type": "str", "default": "once",
                "choices": ["once", "every_song"],
                "description": "读取频率",
            },
            "server": {
                "type": "str", "default": "auto",
                "choices": ["auto", "jp", "tw", "cn", "kr", "en"],
                "description": "目标服务器",
            },
            "timing_unit_ms": {"type": "float", "default": 1.0, "description": "Timing 单位对应毫秒"},
            "default_note_speed": {"type": "float", "default": 10.0, "description": "基准音符速度"},
            "auto_calibrate": {"type": "bool", "default": True, "description": "自动校准"},
        },
    },
    "logging": {
        "type": "object",
        "required": False,
        "properties": {
            "level": {
                "type": "str",
                "default": "INFO",
                "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
            },
            "file": {"type": "str", "default": "logs/pjsk.log"},
            "max_bytes": {"type": "int", "default": 10485760},
            "backup_count": {"type": "int", "default": 5},
        },
    },
}


# ── 校验结果 ──


class SchemaError:
    """单个校验错误。"""

    def __init__(self, path: str, message: str, severity: str = "error"):
        self.path = path
        self.message = message
        self.severity = severity  # error | warning

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.path}: {self.message}"


# ── 校验器 ──


def validate_config(config: dict) -> list[SchemaError]:
    """根据 Schema 验证配置字典。

    Args:
        config: 配置字典 (通常是加载后的合并配置)

    Returns:
        错误列表，空列表表示通过校验
    """
    errors: list[SchemaError] = []

    # 检查顶层字段
    for section_name, section_schema in CONFIG_SCHEMA.items():
        section = config.get(section_name)
        if section is None:
            if section_schema.get("required", False):
                errors.append(SchemaError(
                    section_name, f"缺少必需配置节: {section_name}", "error"
                ))
            continue

        if not isinstance(section, dict):
            errors.append(SchemaError(
                section_name, f"应为 dict, 实际为 {type(section).__name__}", "error"
            ))
            continue

        # 校验子字段
        for prop_name, prop_schema in section_schema.get("properties", {}).items():
            value = section.get(prop_name)
            field_path = f"{section_name}.{prop_name}"

            # 检查类型
            expected_type = prop_schema.get("type")
            if value is not None and expected_type:
                type_ok = _check_type(value, expected_type)
                if not type_ok:
                    actual = type(value).__name__
                    errors.append(SchemaError(
                        field_path,
                        f"类型应为 {expected_type}, 实际为 {actual}",
                        "error",
                    ))

            # 检查取值范围 (str choices)
            choices = prop_schema.get("choices")
            if value is not None and choices is not None:
                if value not in choices:
                    errors.append(SchemaError(
                        field_path,
                        f"值 '{value}' 不在允许范围内: {choices}",
                        "error",
                    ))

            # 检查取值范围 (min/max)
            min_val = prop_schema.get("min")
            max_val = prop_schema.get("max")
            if value is not None and isinstance(value, (int, float)):
                if min_val is not None and value < min_val:
                    errors.append(SchemaError(
                        field_path,
                        f"值 {value} 小于最小值 {min_val}",
                        "error",
                    ))
                if max_val is not None and value > max_val:
                    errors.append(SchemaError(
                        field_path,
                        f"值 {value} 大于最大值 {max_val}",
                        "error",
                    ))

    # 检查未知节
    known_sections = set(CONFIG_SCHEMA.keys())
    for key in config:
        if key not in known_sections:
            errors.append(SchemaError(
                key, f"未知配置节 (typo?)", "warning"
            ))

    # 关键值检查
    _check_critical_values(config, errors)

    return errors


def _check_type(value: Any, expected: str) -> bool:
    """检查值的类型是否匹配 Schema 类型定义。"""
    type_map = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "list": list,
        "dict": dict,
        "object": dict,
    }
    expected_cls = type_map.get(expected)
    if expected_cls is None:
        return True
    # bool 是 int 的子类，需要特殊处理
    if expected_cls is bool:
        return isinstance(value, bool)
    return isinstance(value, expected_cls)


def _check_critical_values(config: dict, errors: list[SchemaError]) -> None:
    """检查关键配置值是否合理。"""
    screen = config.get("screen", {})
    w = screen.get("width", 0)
    h = screen.get("height", 0)
    if w > 0 and h > 0 and w > h:
        errors.append(SchemaError(
            "screen",
            f"宽度 ({w}) 大于高度 ({h}), 可能是横屏? PJSK 是竖屏游戏",
            "warning",
        ))

    play = config.get("play", {})
    miss_rate = play.get("miss_rate", 0)
    if miss_rate > 0.05:
        errors.append(SchemaError(
            "play.miss_rate",
            f"miss_rate={miss_rate} 较大, 会影响 AP 率",
            "warning",
        ))


def generate_config_template() -> dict:
    """根据 Schema 生成带默认值的配置模板。

    Returns:
        完整的默认配置字典 (可直接写为 YAML)
    """
    template: dict[str, Any] = {}

    for section_name, section_schema in CONFIG_SCHEMA.items():
        section: dict[str, Any] = {}
        for prop_name, prop_schema in section_schema.get("properties", {}).items():
            default = prop_schema.get("default")
            if default is not None:
                section[prop_name] = default
        if section:
            template[section_name] = section

    return template


def schema_for_frontend() -> list[dict]:
    """生成前端配置表单所需的 Schema 描述。

    Returns:
        按节组织的配置元数据列表，每个元素描述一组配置。
    """
    sections = []
    for section_name, section_schema in CONFIG_SCHEMA.items():
        props = []
        for prop_name, prop_schema in section_schema.get("properties", {}).items():
            props.append({
                "key": prop_name,
                "label": prop_schema.get("description", prop_name),
                "type": prop_schema.get("type", "str"),
                "default": prop_schema.get("default"),
                "choices": prop_schema.get("choices"),
                "min": prop_schema.get("min"),
                "max": prop_schema.get("max"),
            })
        sections.append({
            "section": section_name,
            "label": section_schema.get("description", section_name),
            "required": section_schema.get("required", False),
            "properties": props,
        })
    return sections
