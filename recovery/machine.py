"""
RecoveryStateMachine — 崩溃恢复状态机。

恢复升级链 (5 级):
  L1: navigate_back    → 最大 3 次, 退避 1s→2s→4s
  L2: restart_app      → 最大 3 次, 退避 2s→4s→8s
  L3: force_restart    → 最大 2 次, 退避 3s→6s
  L4: adb_reconnect    → 最大 3 次, 退避 5s→10s→15s
  L5: notify + safe_stop

崩溃模式检测: 同类型 3 次/5分钟 → degraded_mode
"""

import logging
import time
from collections import deque
from typing import Callable, Optional

logger = logging.getLogger("pjsk.recovery.machine")


class RecoveryState:
    """恢复状态枚举 (字符串常量, 无 enum 依赖)。"""
    IDLE = "idle"
    DETECTED = "detected"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    ESCALATED = "escalated"


# ── 升级链配置 ──

RECOVERY_LEVELS = [
    {
        "name": "navigate_back",
        "max_attempts": 3,
        "backoff": [1.0, 2.0, 4.0],
        "description": "按返回键退出未知页面",
    },
    {
        "name": "restart_app",
        "max_attempts": 3,
        "backoff": [2.0, 4.0, 8.0],
        "description": "杀死游戏进程并重启",
    },
    {
        "name": "force_restart",
        "max_attempts": 2,
        "backoff": [3.0, 6.0],
        "description": "强制杀进程 + 重启",
    },
    {
        "name": "adb_reconnect",
        "max_attempts": 3,
        "backoff": [5.0, 10.0, 15.0],
        "description": "ADB 重连",
    },
    {
        "name": "safe_stop",
        "max_attempts": 1,
        "backoff": [0],
        "description": "通知用户并安全停止",
    },
]

# 崩溃模式检测: 同类型 5 分钟内出现 N 次
CRASH_PATTERN_WINDOW = 300  # 5 分钟 (秒)
CRASH_PATTERN_THRESHOLD = 3  # 3 次
DEGRADED_CLEAR_COUNT = 5    # 连续成功 5 次清除 degraded


class RecoveryStateMachine:
    """崩溃恢复状态机。"""

    _PACKAGE = "com.sega.pjsekai"

    def __init__(self, controller, config: dict,
                 on_escalated: Optional[Callable] = None):
        self.controller = controller
        self.config = config
        self._on_escalated = on_escalated

        self._state = RecoveryState.IDLE
        self._current_level = 0
        self._attempts = 0
        self._consecutive_successes = 0
        self._degraded_mode = False

        # 崩溃历史: deque of (timestamp, crash_type, scene_before)
        self._crash_history: deque = deque(maxlen=20)

        # 当前恢复的 crash_type (用于模式检测)
        self._current_crash_type = ""

        # 恢复开始时间 (超时保护)
        self._recovery_start = 0.0
        self._recovery_timeout = 60  # 60s 总超时

    # ── 属性 ──

    @property
    def state(self) -> str:
        return self._state

    @property
    def degraded_mode(self) -> bool:
        return self._degraded_mode

    @property
    def current_level(self) -> int:
        return self._current_level

    # ── 外部接口 ──

    def report_crash(self, crash_type: str, scene_before: str = ""):
        """报告一个崩溃事件, 启动恢复流程。"""
        now = time.time()

        # 记录崩溃
        self._crash_history.append((now, crash_type, scene_before))
        self._current_crash_type = crash_type

        # 崩溃模式检测
        self._check_crash_pattern()

        if self._state != RecoveryState.IDLE:
            logger.debug("[Recovery] 忽略: 已在恢复中 (%s)", self._state)
            return

        self._state = RecoveryState.DETECTED
        self._current_level = 0
        self._attempts = 0
        self._recovery_start = now
        logger.info("[Recovery] 🚨 崩溃检测: %s | scene=%s",
                     crash_type, scene_before)

        # 立即执行第一级恢复
        self._execute_current_level()

    def tick(self, frame, scene_name: str):
        """主循环每帧调用, 推进状态机。

        在 RECOVERING 状态下:
          - 每次 tick = 一次重试机会
          - 直到验证通过 → RECOVERED
          - 或重试耗尽 → 升级下一级
        """
        if self._state != RecoveryState.RECOVERING:
            return

        # 总超时保护
        if time.time() - self._recovery_start > self._recovery_timeout:
            logger.error("[Recovery] ⏰ 恢复超时 (%ds)", self._recovery_timeout)
            self._escalate()
            return

        # 验证当前帧是否已恢复
        if self._verify_recovery(frame, scene_name):
            self._state = RecoveryState.RECOVERED
            self._consecutive_successes += 1
            if self._degraded_mode and self._consecutive_successes >= DEGRADED_CLEAR_COUNT:
                self._degraded_mode = False
                logger.info("[Recovery] ✅ degraded 模式已清除 (连续 %d 次成功)",
                            DEGRADED_CLEAR_COUNT)
            logger.info("[Recovery] ✅ 恢复成功! (level=%d, attempt=%d)",
                        self._current_level, self._attempts)
            return

        # 重试当前级别
        self._attempts += 1
        level_cfg = RECOVERY_LEVELS[self._current_level]

        if self._attempts < level_cfg["max_attempts"]:
            backoff = level_cfg["backoff"][
                min(self._attempts, len(level_cfg["backoff"]) - 1)
            ]
            logger.info("[Recovery] 重试 %s (%d/%d, 退避 %.1fs)",
                        level_cfg["name"], self._attempts + 1,
                        level_cfg["max_attempts"], backoff)
            time.sleep(backoff)
            self._execute_current_level()
        else:
            # 升级
            self._escalate()

    def _execute_current_level(self):
        """执行当前级别的恢复操作。"""
        level_cfg = RECOVERY_LEVELS[self._current_level]
        name = level_cfg["name"]
        logger.info("[Recovery] 恢复级别 %d: %s — %s",
                    self._current_level + 1, name, level_cfg["description"])

        self._state = RecoveryState.RECOVERING

        try:
            if name == "navigate_back":
                self._do_navigate_back()
            elif name == "restart_app":
                self._do_restart_app()
            elif name == "force_restart":
                self._do_force_restart()
            elif name == "adb_reconnect":
                self._do_adb_reconnect()
            elif name == "safe_stop":
                self._do_safe_stop()
        except Exception as e:
            logger.error("[Recovery] 恢复操作执行异常: %s", e)
            # 异常也算一次失败, tick 会决定重试或升级

    def _escalate(self):
        """升级到下一级恢复。"""
        self._current_level += 1

        if self._current_level >= len(RECOVERY_LEVELS):
            # 所有级别耗尽
            self._state = RecoveryState.ESCALATED
            logger.error("[Recovery] 🔴 所有恢复级别耗尽, 进入 ESCALATED")
            if self._on_escalated:
                self._on_escalated()
            return

        # degraded 模式下: L2 失败直接跳到 L5
        if self._degraded_mode and self._current_level == 1:
            logger.warning("[Recovery] ⚠ degraded 模式: 跳过 L2-L4, 直接 safe_stop")
            self._current_level = len(RECOVERY_LEVELS) - 1  # safe_stop

        self._attempts = 0
        self._execute_current_level()

    # ── 具体恢复操作 ──

    def _do_navigate_back(self):
        if self.controller and hasattr(self.controller, "shell"):
            self.controller.shell("input keyevent 4")
            logger.info("[Recovery] ← 按下返回键")
        time.sleep(1.0)

    def _do_restart_app(self):
        if self.controller:
            self.controller.app_stop(self._PACKAGE)
            time.sleep(2.0)
            self.controller.app_start(self._PACKAGE)
            logger.info("[Recovery] 🔄 重启游戏 %s", self._PACKAGE)
        time.sleep(5.0)

    def _do_force_restart(self):
        if self.controller:
            self.controller.app_stop(self._PACKAGE)
            if hasattr(self.controller, "shell"):
                self.controller.shell(f"am force-stop {self._PACKAGE}")
            time.sleep(3.0)
            self.controller.app_start(self._PACKAGE)
            logger.info("[Recovery] 💥 强制重启 %s", self._PACKAGE)
        time.sleep(5.0)

    def _do_adb_reconnect(self):
        import subprocess
        adb = self.config.get("adb", {}).get("executable", "adb")
        serial = self.config.get("adb", {}).get("device_serial", "")
        try:
            subprocess.run([adb, "-s", serial, "disconnect"] if serial
                           else [adb, "disconnect"],
                           capture_output=True, timeout=5)
            time.sleep(2.0)
        except Exception:
            pass
        try:
            subprocess.run([adb, "-s", serial, "connect"] if serial
                           else [adb, "connect"],
                           capture_output=True, timeout=10)
            time.sleep(3.0)
        except Exception:
            pass
        logger.info("[Recovery] 🔌 ADB 重连尝试完成")

    def _do_safe_stop(self):
        logger.critical("[Recovery] 🛑 无法自动恢复, 请求用户介入")
        # 通知 PjskApp 停止
        self._state = RecoveryState.ESCALATED
        if self._on_escalated:
            self._on_escalated()

    # ── 辅助 ──

    def _verify_recovery(self, frame, scene_name: str) -> bool:
        """验证画面是否已恢复正常。"""
        if frame is None:
            return False
        # 场景不是 UNKNOWN / LOADING 就算恢复
        return scene_name not in ("unknown", "loading")

    def _check_crash_pattern(self):
        """检查最近 5 分钟是否有 3 次同类型崩溃。"""
        now = time.time()
        recent = [
            t for t, ct, _ in self._crash_history
            if now - t < CRASH_PATTERN_WINDOW and ct == self._current_crash_type
        ]
        if len(recent) >= CRASH_PATTERN_THRESHOLD:
            self._degraded_mode = True
            logger.warning("[Recovery] ⚠ degraded 模式激活: "
                           "'%s' 在 %ds 内出现 %d 次",
                           self._current_crash_type,
                           CRASH_PATTERN_WINDOW, len(recent))

    def reset(self):
        """重置状态机 (恢复成功后调用)。"""
        self._state = RecoveryState.IDLE
        self._current_level = 0
        self._attempts = 0
        self._current_crash_type = ""
