"""pytest 配置文件 — 共享 fixtures。"""

import os
import sys
from pathlib import Path

# 确保项目根目录在 path 中
ROOT = Path(os.path.dirname(os.path.abspath(__file__))).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


# ══════════════════════════════════════════════════════════════
# 通用 Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def root_dir():
    """项目根目录。"""
    return ROOT


@pytest.fixture
def sample_config():
    """示例配置字典。"""
    return {
        "adb": {
            "executable": "adb",
            "device_serial": "",
            "screencap_method": "auto",
        },
        "screen": {
            "width": 1080,
            "height": 2400,
            "judgment_line_y": 0.78,
        },
        "play": {
            "mode": "fc",
            "infinite": False,
        },
        "web": {
            "enabled": True,
            "port": 8080,
        },
    }


@pytest.fixture
def sample_task_def():
    """示例 Pipeline 任务定义。"""
    return {
        "ClickOK": {
            "action": "ClickSelf",
            "algorithm": "DirectHit",
            "template": "ok_button.png",
            "threshold": 0.85,
            "next": ["#next"],
            "maxRetries": 5,
            "preDelay": 200,
            "postDelay": 500,
        },
        "BaseClick": {
            "action": "ClickSelf",
            "algorithm": "DirectHit",
            "next": ["Stop"],
        },
        "MyClick@BaseClick": {
            "template": "my_button.png",
            "threshold": 0.9,
        },
    }
