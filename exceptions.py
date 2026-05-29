"""
PJSK Auto Player — 分级异常体系

受 ALAS (AzurLaneAutoScript) 异常系统启发。
每种异常类型对应一种恢复策略。

┌──────────────────────────────────────────────────────┐
│ PjskError (基类)                                      │
│ ├── GameStuckError        → 重启游戏                  │
│ ├── GameBugError          → 杀进程 + 重启             │
│ ├── GamePageUnknownError  → 尝试返回 + 重试           │
│ ├── ConnectionLostError   → 等待重连                  │
│ ├── TooManyClickError     → 防死循环 -> 停止任务      │
│ ├── TaskTimeoutError      → 跳过当前任务              │
│ ├── RecognitionError      → 重试识别                  │
│ └── ConfigError           → 报错停止                  │
└──────────────────────────────────────────────────────┘
"""

import logging
import traceback
from typing import Optional

logger = logging.getLogger("pjsk.exception")


class PjskError(Exception):
    """所有 PJSK 异常的基类。"""

    code: str = "UNKNOWN"
    message: str = "未知错误"
    recoverable: bool = False
    should_notify: bool = True
    should_save_screenshot: bool = True

    def __init__(
        self,
        message: Optional[str] = None,
        context: Optional[dict] = None,
    ):
        self.message = message or self.message
        self.context = context or {}
        super().__init__(self.message)

    def log(self):
        logger.error(
            "[%s] %s | context=%s",
            self.code,
            self.message,
            self.context,
        )
        if self.should_save_screenshot:
            logger.debug("Screenshot should be saved for this error")


class GameStuckError(PjskError):
    """游戏卡住不动（画面长时间无变化）。"""

    code = "GAME_STUCK"
    message = "游戏画面长时间无变化, 尝试重启"
    recoverable = True


class GameBugError(PjskError):
    """游戏异常（崩溃、闪退、黑屏）。"""

    code = "GAME_BUG"
    message = "游戏出现异常, 需要杀进程重启"
    recoverable = True
    should_notify = True


class GamePageUnknownError(PjskError):
    """当前画面无法识别（未知页面）。"""

    code = "PAGE_UNKNOWN"
    message = "无法识别当前画面, 尝试返回导航"
    recoverable = True
    should_notify = False


class ConnectionLostError(PjskError):
    """设备连接断开（USB 松动、ADB 掉线）。"""

    code = "CONNECTION_LOST"
    message = "设备连接断开, 等待重连"
    recoverable = True


class TooManyClickError(PjskError):
    """防死循环保护——连续点击同一位置过多。"""

    code = "TOO_MANY_CLICKS"
    message = "连续点击同一位置超过限制, 疑似死循环"
    recoverable = True
    should_notify = True


class TaskTimeoutError(PjskError):
    """任务执行超时。"""

    code = "TASK_TIMEOUT"
    message = "任务执行超时"
    recoverable = True
    should_notify = False


class RecognitionError(PjskError):
    """图像/文字识别失败。"""

    code = "RECOGNITION_FAILED"
    message = "识别失败"
    recoverable = True
    should_notify = False
    should_save_screenshot = False


class ConfigError(PjskError):
    """配置错误——不可恢复。"""

    code = "CONFIG_ERROR"
    message = "配置错误"
    recoverable = False


class DeviceNotConnectedError(PjskError):
    """设备未连接。"""

    code = "DEVICE_NOT_CONNECTED"
    message = "设备未连接"
    recoverable = False


class RequestHumanTakeover(PjskError):
    """需要用户介入（无法自动处理的情况）。"""

    code = "HUMAN_TAKEOVER"
    message = "需要用户介入处理"
    recoverable = False
    should_notify = True
    should_save_screenshot = True


class SongSelectError(PjskError):
    """选歌失败（歌曲不存在、被锁定等）。"""

    code = "SONG_SELECT_ERROR"
    message = "选歌失败"
    recoverable = True
    should_notify = True


class ResourceExhaustedError(PjskError):
    """资源耗尽（体力/次数用完）。"""

    code = "RESOURCE_EXHAUSTED"
    message = "资源耗尽"
    recoverable = False
    should_notify = True


# ── 错误恢复策略注册表 ──

RecoveryStrategy = dict[str, dict]  # {error_code: {action, retry_delay, max_retries}}

DEFAULT_RECOVERY_STRATEGIES: RecoveryStrategy = {
    "GAME_STUCK": {
        "action": "restart_app",
        "retry_delay": 3.0,
        "max_retries": 3,
        "description": "杀死游戏进程并重启",
    },
    "GAME_BUG": {
        "action": "force_restart",
        "retry_delay": 5.0,
        "max_retries": 3,
        "description": "强制杀死进程 + 清除缓存后重启",
    },
    "PAGE_UNKNOWN": {
        "action": "navigate_back",
        "retry_delay": 1.0,
        "max_retries": 5,
        "description": "尝试按返回键退出未知页面",
    },
    "CONNECTION_LOST": {
        "action": "wait_reconnect",
        "retry_delay": 2.0,
        "max_retries": 30,
        "description": "等待设备重新连接",
    },
    "TOO_MANY_CLICKS": {
        "action": "stop_task",
        "retry_delay": 0.5,
        "max_retries": 1,
        "description": "停止当前任务并报告",
    },
    "TASK_TIMEOUT": {
        "action": "skip_task",
        "retry_delay": 0.5,
        "max_retries": 3,
        "description": "跳过超时任务继续执行",
    },
    "RECOGNITION_FAILED": {
        "action": "retry",
        "retry_delay": 1.0,
        "max_retries": 10,
        "description": "增加阈值后重试识别",
    },
    "HUMAN_TAKEOVER": {
        "action": "notify_user",
        "retry_delay": 0,
        "max_retries": 0,
        "description": "发送通知等待用户介入",
    },
    "SONG_SELECT_ERROR": {
        "action": "skip_task",
        "retry_delay": 2.0,
        "max_retries": 3,
        "description": "跳过当前歌曲，尝试下一首",
    },
    "RESOURCE_EXHAUSTED": {
        "action": "stop",
        "retry_delay": 0,
        "max_retries": 0,
        "description": "停止任务并通知用户",
    },
    "CONFIG_ERROR": {
        "action": "stop",
        "retry_delay": 0,
        "max_retries": 0,
        "description": "配置错误，停止并提示修复",
    },
    "DEVICE_NOT_CONNECTED": {
        "action": "stop",
        "retry_delay": 0,
        "max_retries": 0,
        "description": "设备未连接，停止任务",
    },
}


def get_recovery_strategy(error_code: str) -> dict:
    """获取指定错误代码的恢复策略。"""
    return DEFAULT_RECOVERY_STRATEGIES.get(
        error_code,
        {"action": "stop", "retry_delay": 1.0, "max_retries": 1, "description": "停止任务"},
    )


def classify_error(exc: Exception) -> PjskError:
    """将任意异常转换为 PjskError 层次结构。"""
    if isinstance(exc, PjskError):
        return exc
    if isinstance(exc, TimeoutError):
        return TaskTimeoutError(str(exc))
    if isinstance(exc, ConnectionError):
        return ConnectionLostError(str(exc))
    # 通用兜底
    return GamePageUnknownError(f"{type(exc).__name__}: {exc}")
