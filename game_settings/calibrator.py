"""
设置校准器 — 将游戏内参数映射为软件操作参数。

核心映射逻辑:
  1. 游戏 timing_offset → 软件 latency_compensation_ms / advance_ms
  2. 游戏 note_speed → 预测引擎 velocity 校准系数
  3. 自动更新 config 中的相关字段
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("pjsk.calibrator")


@dataclass
class CalibrationResult:
    """校准结果 —— 游戏参数 → 软件参数的完整映射。"""

    # 原始游戏值
    game_timing_offset: int = 0        # 游戏内タイミング調整 (-50 ~ +50)
    game_note_speed: float = 10.0      # 游戏内ノーツ速度 (1.0 ~ 12.0)

    # 映射后的软件参数
    adjusted_latency_comp_ms: float = 0.0     # 延迟补偿 (ms)
    adjusted_advance_ms: float = 0.0          # 预测提前量 (ms)
    velocity_correction_factor: float = 1.0   # 速度校准系数
    timing_offset_comp_ms: float = 0.0        # timing offset 对应的毫秒补偿
    note_speed_factor: float = 1.0            # 音符速度比例因子

    # 元数据
    server: str = ""
    calibration_time: str = ""
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"CalibrationResult(timing={self.game_timing_offset:+d}, "
            f"speed={self.game_note_speed:.1f}, "
            f"lat_comp={self.adjusted_latency_comp_ms:.0f}ms, "
            f"advance={self.adjusted_advance_ms:.0f}ms, "
            f"vel_factor={self.velocity_correction_factor:.3f})"
        )


class SettingsCalibrator:
    """
    设置校准器。

    将游戏内的 タイミング調整 和 ノーツ速度 映射为软件预测引擎参数。

    映射原理:
      - タイミング調整: 游戏将 note 视觉位置偏移 timing_offset 单位。
        每个单位约对应 1~2ms 的时间偏移 (取决于音符速度)。
        正值 = note 视觉上提前到达判定线 → 软件需要减少 advance_ms。
        负值 = note 视觉上延迟到达 → 软件需要增加 advance_ms。

      - ノーツ速度: 直接影响 note 滚动速度 (px/s)。
        软件以 10.0 速度为基准, 其他速度按比例缩放。
        例如 speed=11.0 → velocity_factor = 11.0/10.0 = 1.1

    公式:
        timing_comp_ms = -timing_offset * TIMING_UNIT_MS
        velocity_factor = note_speed / DEFAULT_NOTE_SPEED
        adjusted_advance_ms = base_advance_ms + timing_comp_ms
    """

    # 游戏 timing 调整 1 个单位 ≈ 多少毫秒的时间偏移
    # 实际值取决于音符速度, 这里用近似 (在 speed=10.0 时, 1 单位 ≈ 1.0ms)
    TIMING_UNIT_MS = 1.0

    # 默认音符速度 (大多数玩家的基准)
    DEFAULT_NOTE_SPEED = 10.0

    # 速度到时间偏移的转换系数 (速度越快, 时序偏差越大)
    # 快速度下 timing offset 的影响更大
    SPEED_TIMING_FACTOR = 0.1

    def __init__(self, base_latency_comp_ms: float = 0.0,
                 base_advance_ms: float = 0.0):
        """
        Args:
            base_latency_comp_ms: 基础 ADB 延迟补偿 (ms)
            base_advance_ms: 基础预测提前量 (ms)
        """
        self.base_latency_comp_ms = base_latency_comp_ms
        self.base_advance_ms = base_advance_ms

    def calibrate(self, timing_offset: int, note_speed: float,
                  server: str = "",
                  base_latency_comp_ms: Optional[float] = None,
                  base_advance_ms: Optional[float] = None) -> CalibrationResult:
        """执行完整校准。

        Args:
            timing_offset: 游戏内タイミング調整值 (-50 ~ +50)
            note_speed: 游戏内ノーツ速度 (1.0 ~ 12.0)
            server: 服务器标识
            base_latency_comp_ms: 覆盖基础延迟补偿
            base_advance_ms: 覆盖基础预测提前量

        Returns:
            CalibrationResult 包含所有映射后的参数
        """
        import datetime

        if base_latency_comp_ms is not None:
            self.base_latency_comp_ms = base_latency_comp_ms
        if base_advance_ms is not None:
            self.base_advance_ms = base_advance_ms

        result = CalibrationResult(
            game_timing_offset=timing_offset,
            game_note_speed=note_speed,
            server=server,
            calibration_time=datetime.datetime.now().isoformat(),
        )

        warnings = []

        # ── 1. 速度校准 ──
        if note_speed > 0:
            result.note_speed_factor = note_speed / self.DEFAULT_NOTE_SPEED
            # 速度因子用于缩放预测引擎的 velocity 计算
            # prediction velocity 应乘以 note_speed_factor
            result.velocity_correction_factor = result.note_speed_factor
        else:
            result.note_speed_factor = 1.0
            result.velocity_correction_factor = 1.0
            warnings.append("Invalid note speed, using default 1.0x")

        # ── 2. Timing 偏移映射 ──
        # 游戏 timing_offset 正值 = note 视觉上提前 (早く)
        # → 软件应减少提前量 (提前量过大会导致按太早)
        # → timing_comp = -offset * unit_ms
        base_timing_comp = -timing_offset * self.TIMING_UNIT_MS

        # 速度越快, timing 偏移的影响越大
        speed_modified_timing = base_timing_comp * (
            1.0 + abs(result.note_speed_factor - 1.0) * self.SPEED_TIMING_FACTOR * 10
        )
        result.timing_offset_comp_ms = speed_modified_timing

        # ── 3. 最终延迟补偿 ──
        result.adjusted_latency_comp_ms = max(
            0, self.base_latency_comp_ms + speed_modified_timing
        )
        result.adjusted_advance_ms = max(
            5, self.base_advance_ms + speed_modified_timing
        )

        # ── 4. 边界检查 ──
        if abs(timing_offset) > 20:
            warnings.append(
                f"Timing offset ({timing_offset:+d}) is large, "
                f"may need manual verification"
            )
        if note_speed < 5.0 or note_speed > 11.5:
            warnings.append(
                f"Note speed ({note_speed:.1f}) is unusual, "
                f"velocity calibration may be inaccurate"
            )

        result.warnings = warnings
        result.confidence = 1.0 - (len(warnings) * 0.15)

        logger.info(
            "Calibration: timing=%+d speed=%.1f → "
            "lat_comp=%.0fms advance=%.0fms vel_factor=%.3f",
            timing_offset, note_speed,
            result.adjusted_latency_comp_ms,
            result.adjusted_advance_ms,
            result.velocity_correction_factor,
        )

        if warnings:
            for w in warnings:
                logger.warning("  ⚠ %s", w)

        return result

    def get_config_updates(self, result: CalibrationResult) -> dict:
        """生成可直接合并到 config 的参数更新字典。

        Returns:
            可直接用于 config.update() 的字典
        """
        updates = {
            "timing": {
                "latency_compensation_ms": round(result.adjusted_latency_comp_ms, 0),
            },
            "prediction": {
                "manual_advance_ms": round(result.adjusted_advance_ms, 0),
                "velocity_correction_factor": round(result.velocity_correction_factor, 3),
            },
            "game_settings": {
                "last_read_timing_offset": result.game_timing_offset,
                "last_read_note_speed": result.game_note_speed,
                "last_calibration_time": result.calibration_time,
                "detected_server": result.server,
                "auto_calibrate": True,
            },
        }
        return updates

    @staticmethod
    def from_config(config: dict) -> "SettingsCalibrator":
        """从现有 config 构建校准器。"""
        timing_cfg = config.get("timing", {})
        pred_cfg = config.get("prediction", {})

        base_lat = timing_cfg.get("latency_compensation_ms", 0)
        base_adv = pred_cfg.get("manual_advance_ms", 0)

        return SettingsCalibrator(
            base_latency_comp_ms=base_lat,
            base_advance_ms=base_adv,
        )
