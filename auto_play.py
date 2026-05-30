"""
自动执行引擎 —— 核心循环: 截图 → 分析 → 触摸 (含预测引擎)。

核心改进:
  1. 预测引擎: 提前检测判定线上方的 note, 计算滚动速度,
     在 note 到达判定线时准时触发, 补偿 ADB 延迟
  2. 实时统计: FPS / notes 数 / 延迟信息
  3. 热键控制: P=暂停 Q=退出 +/-=补偿 </>=阈值
  4. 校准自动写入 config.yaml
"""

import logging
import time
import sys
import os
import json
import random
from typing import Optional

import numpy as np
import cv2

from adb_controller import ADBController
from screen_analyzer import ScreenAnalyzer, NoteEvent, GameState

# Pipeline 引擎 (可选, v3.0.0+)
try:
    from pipeline import PipelineEngine, PipelineState, TaskDef
    _HAS_PIPELINE = True
except ImportError:
    _HAS_PIPELINE = False

logger = logging.getLogger("pjsk_auto_play")


# 执行模式预设: 每个模式对应一组随机化参数
# 通过调整时机抖动、位置抖动和漏键率来模拟不同水平的人类玩家
PERFORMANCE_MODES = {
    "AP": {
        "label": " AP (All Perfect)",
        "description": "极致精确，所有 note PERFECT",
        "timing_jitter_ms": 3,
        "position_jitter_px": 2,
        "miss_chance": 0.0,
        "hold_duration_jitter_ms": 10,
    },
    "FC": {
        "label": " FC (Full Combo)",
        "description": "不漏键，但可能有 GREAT/GOOD",
        "timing_jitter_ms": 15,
        "position_jitter_px": 5,
        "miss_chance": 0.0,
        "hold_duration_jitter_ms": 30,
    },
    "LIVE": {
        "label": " LIVE CLEAR",
        "description": "保底通关，允许漏键和 BAD",
        "timing_jitter_ms": 35,
        "position_jitter_px": 10,
        "miss_chance": 0.003,
        "hold_duration_jitter_ms": 50,
    },
}

MODE_NAMES = list(PERFORMANCE_MODES.keys())


class NoteTracker:
    """Note 轨迹追踪器 —— 预测引擎的核心。
      1. 从 ScreenAnalyzer 获取判定线上方的 note 检测结果
      2. 对每个轨道追踪 note 的 Y 位置变化
      3. 计算滚动速度 (px/s)
      4. 预测 note 到达判定线的时间
      5. 在最佳时间触发触摸
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.judgment_y = config["screen"]["judgment_line_y"] * config["screen"]["height"]
        self.judgment_y = int(self.judgment_y)

        prediction_cfg = config.get("prediction", {})
        self.enabled = prediction_cfg.get("enabled", True)
        self.min_track_frames = prediction_cfg.get("min_track_frames", 2)
        self.velocity_window = prediction_cfg.get("velocity_smooth_window", 3)
        self.manual_advance = prediction_cfg.get("manual_advance_ms", 0)

        # 点击随机化参数 (从 AutoPlayer/config 传入)
        rand_cfg = config.get("randomization", {})
        self.timing_jitter_ms = rand_cfg.get("timing_jitter_ms", 15)
        self.rand_enabled = rand_cfg.get("enabled", True)

        # 测量到的 ADB 延迟 (ms)
        self._measured_latency_ms = 0

        # ═══ v4.8.0: 自适应延迟 PID 控制器 ═══
        pid_cfg = config.get("timing", {}).get("adaptive_latency", {})
        self._pid_enabled = pid_cfg.get("enabled", True)
        self._pid_kp = pid_cfg.get("kp", 0.3)    # 比例增益
        self._pid_ki = pid_cfg.get("ki", 0.05)   # 积分增益
        self._pid_kd = pid_cfg.get("kd", 0.1)    # 微分增益
        self._pid_target = pid_cfg.get("target_advance_ms", 15)  # 目标提前量 (ms)
        self._pid_error_sum = 0.0
        self._pid_last_error = 0.0
        self._pid_samples: list[float] = []       # 本次歌曲的提前量样本
        self._pid_min_samples = pid_cfg.get("min_samples", 50)  # 最少样本数

        # 追踪状态: lane -> { positions: [(y, t), ...], velocity: float, fired: bool }
        self._tracks: dict[int, dict] = {}
        # 缓存 lane X 坐标 (避免每次 _lane_to_x 重算)
        self._lane_x_cache: list[int] = []

        # v5.3.0: 速度校准因子 (来自游戏内设置 note_speed 读取)
        self._velocity_correction_factor: float = 1.0
        # v5.3.0: 手动提前量覆盖 (来自游戏内设置 calibration)
        self._calibrated_advance_ms: Optional[float] = None

    def set_latency(self, latency_ms: float):
        """设置测量到的 ADB 延迟 (ms)。"""
        self._measured_latency_ms = latency_ms
        logger.info(f"预测引擎: ADB 延迟 = {latency_ms:.0f}ms")

    def set_velocity_factor(self, factor: float):
        """v5.3.0: 设置速度校准因子 (来自游戏内 note_speed)。

        factor = game_note_speed / default_note_speed (10.0)
        预测引擎在计算 velocity 时会乘以这个因子。
        """
        self._velocity_correction_factor = max(0.5, min(2.0, factor))
        logger.info(f"预测引擎: 速度校准因子 = {self._velocity_correction_factor:.3f}")

    def set_manual_advance(self, advance_ms: float):
        """v5.3.0: 设置校准后的手动提前量 (来自游戏内 timing_offset 校准)。"""
        self._calibrated_advance_ms = advance_ms
        logger.info(f"预测引擎: 校准提前量 = {advance_ms:.0f}ms")

    def update(self, predicted_notes: list[NoteEvent],
               detected_notes: list[NoteEvent],
               now: float) -> list[dict]:
        """
        更新追踪状态, 返回需要触发的 note 列表。

        Returns:
            [{"lane": int, "note_type": str, "x": int, "y": int,
              "flick_direction": str}, ...]
        """
        if not self.enabled:
            return []

        triggers = []

        # 更新已有轨迹
        predicted_lanes = {n.lane for n in predicted_notes}

        # 对每个被预测到的轨道, 更新位置
        for note in predicted_notes:
            if note.lane not in self._tracks:
                self._tracks[note.lane] = {
                    "positions": [],
                    "velocity": 0.0,
                    "fired": False,
                    "note_type": "tap",
                }
            track = self._tracks[note.lane]
            track["positions"].append((note.y, now))

            # 保持窗口大小
            max_positions = self.velocity_window + 2
            if len(track["positions"]) > max_positions:
                track["positions"] = track["positions"][-max_positions:]

            # 计算速度
            if len(track["positions"]) >= 2:
                ys = [p[0] for p in track["positions"]]
                ts = [p[1] for p in track["positions"]]
                # 线性回归: 速度 = dy / dt (像素/秒)
                # dy 应为负 (note 从上往下)
                dy = ys[-1] - ys[0]
                dt = ts[-1] - ts[0]
                if dt > 0:
                    velocity = dy / dt  # 像素/秒, 应为负值
                    # 平滑
                    alpha = 0.7
                    track["velocity"] = track["velocity"] * (1 - alpha) + velocity * alpha

        # 检测是否需要触发
        base_advance_ms = self._measured_latency_ms
        if self.manual_advance > 0:
            base_advance_ms = self.manual_advance
        # v5.3.0: 使用校准后的 advance (来自游戏设置读取)
        if self._calibrated_advance_ms is not None:
            base_advance_ms = self._calibrated_advance_ms

        for lane, track in self._tracks.items():
            if track["fired"]:
                continue  # 已经触发过了

            if not track["positions"]:
                continue

            # 需要足够多的追踪帧才能建立稳定的速度
            if len(track["positions"]) < self.min_track_frames:
                continue

            # 如果速度太小 (接近 0), 说明 note 可能停在屏幕上了
            # v5.3.0: 应用速度校准因子
            effective_velocity = abs(track["velocity"]) * self._velocity_correction_factor
            if effective_velocity < 50:
                continue

            # ═══ 每 lane 独立时机随机化 (之前是全局一次, 现在 per-lane) ═══
            advance_ms = base_advance_ms
            if self.rand_enabled and self.timing_jitter_ms > 0:
                jittered = advance_ms + random.uniform(
                    -self.timing_jitter_ms, self.timing_jitter_ms
                )
                advance_ms = max(5, jittered)

            # 当前 Y 位置
            current_y = track["positions"][-1][0]
            distance_to_judgment = current_y - self.judgment_y  # 应为正 (note 在判定线上方)

            # 如果 note 已经在判定线位置或以下, 立即触发
            if distance_to_judgment <= 0:
                track["fired"] = True
                triggers.append({
                    "lane": lane,
                    "note_type": track.get("note_type", "tap"),
                    "x": self._lane_to_x(lane),
                    "y": self.judgment_y,
                    "flick_direction": "",
                })
                continue

            # 计算剩余时间 (秒) 和触发提前量
            # v5.3.0: 使用校准后的有效速度
            velocity = abs(track["velocity"]) * self._velocity_correction_factor
            if velocity < 50:  # 太慢, 可能不准
                continue

            time_to_arrival = distance_to_judgment / velocity  # 秒
            advance_seconds = advance_ms / 1000.0

            # 如果到达时间小于提前量, 触发!
            if time_to_arrival <= advance_seconds:
                track["fired"] = True
                triggers.append({
                    "lane": lane,
                    "note_type": track.get("note_type", "tap"),
                    "x": self._lane_to_x(lane),
                    "y": self.judgment_y,
                    "flick_direction": "",
                })
                # ═══ v4.8.0: PID 采样 — 记录实际提前量 ═══
                if self._pid_enabled:
                    actual_advance = distance_to_judgment / velocity * 1000  # ms
                    self._pid_samples.append(actual_advance)

        # 清理: 如果 note 已到达判定线 (被 detected_notes 捕获), 或轨迹过期
        detected_lanes = {n.lane for n in detected_notes}
        expired_lanes = []
        for lane, track in self._tracks.items():
            if track["fired"] or lane in detected_lanes:
                expired_lanes.append(lane)
            elif track["positions"]:
                last_t = track["positions"][-1][1]
                if now - last_t > 1.0:  # 1 秒没更新
                    expired_lanes.append(lane)

        for lane in expired_lanes:
            del self._tracks[lane]

        return triggers

    def _lane_to_x(self, lane: int) -> int:
        """将轨道编号映射到 X 坐标 (像素)，带缓存。"""
        if not self._lane_x_cache:
            s = self.cfg.get("screen", {})
            w = s.get("width", 1080)
            l = [int(x * w) for x in s.get("left_lanes", [0.15, 0.25, 0.35])]
            r = [int(x * w) for x in s.get("right_lanes", [0.65, 0.75, 0.85])]
            self._lane_x_cache = l + r
        if 0 <= lane < len(self._lane_x_cache):
            return self._lane_x_cache[lane]
        return int(self.cfg.get("screen", {}).get("width", 1080) // 2)

    def reset(self):
        """重置所有轨迹 (新歌开始时调用)。
        
        v4.6.0: 谱面缓存 — 保留已学习的滚动速度, 仅清除位置和触发状态。
        这样下一首歌开始时 NoteTracker 已有速度估计, 跳过 2-3 帧校准期。
        """
        if self.cfg.get("prediction", {}).get("velocity_cache", True):
            # 缓存模式: 保留 velocity, 重置其他状态
            for lane in self._tracks:
                self._tracks[lane]["positions"] = []
                self._tracks[lane]["fired"] = False
        else:
            self._tracks.clear()

    def get_stats(self) -> dict:
        """获取追踪统计。"""
        stats = {
            "tracked_notes": len(self._tracks),
            "measured_latency_ms": self._measured_latency_ms,
        }
        if self._pid_enabled and self._pid_samples:
            avg_advance = sum(self._pid_samples) / len(self._pid_samples)
            stats["pid_avg_advance_ms"] = round(avg_advance, 1)
            stats["pid_samples"] = len(self._pid_samples)
        return stats

    def compute_pid_adjustment(self) -> float:
        """
        基于本次歌曲的 PID 样本计算延迟补偿调整值 (ms)。
        正值 = 增加补偿 (提前更多), 负值 = 减少补偿。

        在每首歌结束后调用, 异步应用于 _measured_latency_ms。
        """
        if not self._pid_enabled or len(self._pid_samples) < self._pid_min_samples:
            self._pid_samples.clear()
            return 0.0

        # 平均实际提前量
        samples = self._pid_samples[:]
        self._pid_samples.clear()

        # 过滤离群值: 剔除 >3σ 的样本
        if len(samples) >= self._pid_min_samples:
            mean = sum(samples) / len(samples)
            variance = sum((s - mean) ** 2 for s in samples) / len(samples)
            std = variance ** 0.5
            if std > 0:
                samples = [s for s in samples if abs(s - mean) <= 3 * std]

        if len(samples) < self._pid_min_samples // 2:
            return 0.0

        avg_advance = sum(samples) / len(samples)

        # PID 误差: 实际提前量 - 目标提前量
        error = avg_advance - self._pid_target  # 正 = 提前太多
        self._pid_error_sum += error
        # 防积分饱和
        self._pid_error_sum = max(-100, min(100, self._pid_error_sum))
        derivative = error - self._pid_last_error
        self._pid_last_error = error

        adjustment = (self._pid_kp * error
                      + self._pid_ki * self._pid_error_sum
                      + self._pid_kd * derivative)
        # 单次调整上限
        adjustment = max(-20, min(20, adjustment))
        return round(adjustment, 1)


class AutoPlayer:
    """
    自动执行器。

    工作流程:
        1. 截取手机屏幕
        2. 分析画面, 检测判定线上的 notes + 判定线上方的 note (预测)
        3. 预测引擎: 追踪 note 滚动速度, 提前触发
        4. 对判定线上的 note 发送触摸指令 (备用)
        5. 循环 1-5, 直到歌曲结束
    """

    def __init__(self, config: dict, mode: str = "FC"):
        self.cfg = config
        self.adb = ADBController(config)
        self.analyzer = ScreenAnalyzer(config)
        self.tracker = NoteTracker(config)

        self._running = False
        self._paused = False

        # 时序参数
        self.latency_comp = config.get("timing", {}).get("latency_compensation_ms", 0)
        self.min_interval = config.get("timing", {}).get("min_frame_interval_ms", 10) / 1000.0
        self.game_over_timeout = config.get("timing", {}).get("game_over_timeout", 5.0)

        # v5.2: 画面捕获优化器 — 只截 ROI (判定线附近), 减少处理面积
        self._capture_opt = None
        try:
            from capture_optimizer import CaptureOptimizer
            self._capture_opt = CaptureOptimizer(config)
        except ImportError:
            pass

        # v5.2: 异步截屏 (producer-consumer, 提升帧率)
        self._async_capture = config.get("adb", {}).get("async_capture", True)

        # 触摸参数
        self.tap_duration = config.get("touch", {}).get("tap_duration_ms", 30)
        self.flick_distance = config.get("touch", {}).get("flick_distance", 150)
        self.flick_duration = config.get("touch", {}).get("flick_duration_ms", 50)

        # 显示参数
        self.show_stats = config.get("display", {}).get("show_stats", True)
        self.stats_interval = config.get("display", {}).get("stats_interval_frames", 15)

        # 预测参数
        self.use_prediction = config.get("prediction", {}).get("enabled", True)

        # ═══ 缓存: 避免每帧重建 ═══
        self._lane_positions: Optional[list] = None

        # ════════════════════════════════════════════
        # 操作随机化参数
        # ════════════════════════════════════════════
        rand_cfg = config.get("randomization", {})
        self.rand_enabled = rand_cfg.get("enabled", True)
        self.timing_jitter_ms = rand_cfg.get("timing_jitter_ms", 15)
        self.position_jitter_px = rand_cfg.get("position_jitter_px", 5)
        self.miss_chance = rand_cfg.get("miss_chance", 0.001)
        self.hold_duration_jitter_ms = rand_cfg.get("hold_duration_jitter_ms", 30)

        # ═══ 执行模式 ═══
        self._mode = mode.upper() if mode.upper() in MODE_NAMES else "FC"
        self._mode_index = MODE_NAMES.index(self._mode)
        self.set_mode(self._mode)

        # 状态
        self._last_game_active = 0.0
        self._held_lanes = set()
        # v5.2: tap/flick 跨帧去重 cooldown (防止同 note 重复触发)
        self._lane_tap_cooldown: dict[int, int] = {}
        self._lane_flick_cooldown: dict[int, int] = {}
        self._tap_cooldown_frames = config.get("timing", {}).get("tap_cooldown_frames", 3)
        self._flick_cooldown_frames = config.get("timing", {}).get("flick_cooldown_frames", 5)
        self._stats = {
            "frames": 0,
            "taps": 0,
            "flicks": 0,
            "holds": 0,
            "predicted_triggers": 0,
            "misses": 0,
            "start_time": 0.0,
            "last_stats_time": 0.0,
            "fps": 0.0,
        }

    # ──────────────────────────────────────────
    # 主控制
    # ──────────────────────────────────────────

    def start(self) -> None:
        """启动自动执行循环。"""
        if not self._ensure_ready():
            return

        # 测量延迟 (用于预测引擎)
        if self.use_prediction:
            logger.info("测量 ADB 延迟用于预测引擎...")
            latency = self.adb.measure_latency(samples=3)
            total_latency = latency.get("total_avg_ms", self.latency_comp)
            if total_latency > 0:
                self.tracker.set_latency(total_latency)
            else:
                logger.warning("延迟测量失败, 使用配置值")
                self.tracker.set_latency(self.latency_comp or 150)

        # ═══ v5.3.0: 自动读取游戏内设置并校准 ═══
        self._read_game_settings()

        self._running = True
        self._paused = False
        self._stats["start_time"] = time.time()
        self._stats["last_stats_time"] = time.time()

        prediction_status = "已启用" if self.use_prediction else "已禁用"
        rand_status = "已启用" if self.rand_enabled else "已禁用"
        mode_label = self.mode_label
        logger.info("=" * 60)
        logger.info("自动执行已启动!")
        logger.info(f"模式: {mode_label}  |  "
                     f"延迟补偿: {self.latency_comp}ms  |  "
                     f"预测引擎: {prediction_status}")
        logger.info(f"随机化: {rand_status}  "
                     f"时机±{self.timing_jitter_ms}ms  "
                     f"坐标±{self.position_jitter_px}px")
        logger.info(f"判定线 Y: {self.analyzer.judgment_y}")
        logger.info("热键: P=暂停  Q=退出  M=切换模式  "
                     "+/-=补偿  </>=阈值  []=随机化")
        logger.info("=" * 60)

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("收到中断信号, 停止...")
        finally:
            self.stop()

    def stop(self) -> None:
        """停止自动执行, 释放所有触摸。"""
        self._running = False
        self._paused = False
        self._release_all()

        # ═══ v4.8.0: 歌曲结束时运行 PID 调整 ═══
        if self.use_prediction:
            adjustment = self.tracker.compute_pid_adjustment()
            if abs(adjustment) >= 1.0:
                self.latency_comp = max(0, self.latency_comp + adjustment)
                self.tracker.set_latency(self.latency_comp)
                stats = self.tracker.get_stats()
                logger.info(f"PID 自适应: 调整 {adjustment:+.1f}ms "
                            f"→ 补偿 {self.latency_comp:.0f}ms "
                            f"(samples={stats.get('pid_samples', '?')}, "
                            f"avg_adv={stats.get('pid_avg_advance_ms', '?')}ms)")

        self.analyzer.close()
        self.adb.stop_async_capture()
        self.adb.close_scrcpy()
        self.adb._cleanup_minitouch()

        elapsed = time.time() - self._stats["start_time"]
        fps_avg = self._stats["frames"] / elapsed if elapsed > 0 else 0

        logger.info("─" * 40)
        logger.info("自动执行已停止")
        logger.info(f"运行时间: {elapsed:.1f}s")
        logger.info(f"处理帧数: {self._stats['frames']}  ({fps_avg:.1f} FPS)")
        logger.info(f"点击: {self._stats['taps']}  "
                     f"Flick: {self._stats['flicks']}  "
                     f"长按: {self._stats['holds']}")
        if self.use_prediction:
            logger.info(f"预测触发: {self._stats['predicted_triggers']}")
        logger.info("─" * 40)

    def _reset_stats(self) -> None:
        """重置统计计数器 (每首新歌调用)。"""
        self._stats = {
            "frames": 0,
            "taps": 0,
            "flicks": 0,
            "holds": 0,
            "predicted_triggers": 0,
            "misses": 0,
            "start_time": 0.0,
            "last_stats_time": 0.0,
            "fps": 0.0,
        }

    def pause(self) -> None:
        """暂停/恢复。"""
        self._paused = not self._paused
        if self._paused:
            self._release_all()
            logger.info("\n⏸ 已暂停")
        else:
            self.tracker.reset()
            logger.info("\n▶ 已恢复")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    # ──────────────────────────────────────────
    # 准备
    # ──────────────────────────────────────────

    def _ensure_ready(self) -> bool:
        """确保 ADB 连接和配置就绪。"""
        logger.info("检查 ADB 连接...")

        if not self.adb.wait_for_device(timeout=10):
            logger.error("无法连接设备, 请检查 USB / ADB 连接")
            return False

        try:
            actual_w, actual_h = self.adb.get_screen_size()
            cfg_w, cfg_h = self.cfg["screen"]["width"], self.cfg["screen"]["height"]
            if actual_w != cfg_w or actual_h != cfg_h:
                logger.info(
                    f"实际分辨率 {actual_w}x{actual_h} "
                    f"与配置 {cfg_w}x{cfg_h} 不一致, 自动适配"
                )
                self.cfg["screen"]["width"] = actual_w
                self.cfg["screen"]["height"] = actual_h
                self.analyzer = ScreenAnalyzer(self.cfg)
                self.tracker = NoteTracker(self.cfg)
                self._lane_positions = None
        except Exception as e:
            logger.warning(f"获取屏幕分辨率失败: {e}")

        logger.info("测试截图...")
        test_frame = self.adb.screencap()
        if test_frame is None:
            logger.error("截图失败, 请检查设备和 ADB")
            return False
        logger.info(f"截图成功: {test_frame.shape[1]}x{test_frame.shape[0]}")

        # 初始化 minitouch 后端
        mt_cfg = self.cfg.get("minitouch", {})
        if mt_cfg.get("auto_init", True):
            logger.info("初始化 minitouch 后端...")
            if self.adb.init_minitouch():
                logger.info("minitouch 已就绪 (触摸延迟 <5ms)")
            else:
                logger.info("minitouch 不可用, 使用 ADB input (延迟 ~50ms)")

        # v5.2: 启动异步截屏 (producer-consumer, 提升 30-50% 帧率)
        if self._async_capture:
            self.adb.start_async_capture(target_fps=30)

        return True

    def _read_game_settings(self) -> None:
        """v5.3.0: 自动读取游戏内设置 (タイミング調整 + ノーツ速度) 并校准软件参数。"""
        gs_cfg = self.cfg.get("game_settings", {})
        if not gs_cfg.get("auto_read", True):
            logger.info("游戏设置自动读取: 已禁用 (game_settings.auto_read=false)")
            return

        frequency = gs_cfg.get("frequency", "once")
        last_time = gs_cfg.get("last_calibration_time", "")
        if frequency == "once" and last_time:
            logger.info(f"游戏设置自动读取: 已有缓存 ({last_time}), 跳过")
            return

        try:
            from game_settings import GameSettingsReader, GameServer

            server_str = gs_cfg.get("server", "auto")
            try:
                server = GameServer(server_str)
            except ValueError:
                server = GameServer.AUTO

            logger.info("⏳ 正在读取游戏内设置 (タイミング調整 + ノーツ速度)...")

            # 创建读取器 (传入 self.adb 作为 controller)
            reader = GameSettingsReader(self.adb, self.cfg, server=server)

            # 执行读取
            result = reader.read_and_apply(navigate=True)

            if result is not None:
                # 更新本地引用的配置
                self.latency_comp = result.adjusted_latency_comp_ms
                if self.use_prediction:
                    self.tracker.set_latency(self.latency_comp)
                    # 应用速度校准因子
                    if hasattr(self.tracker, 'set_velocity_factor'):
                        self.tracker.set_velocity_factor(result.velocity_correction_factor)

                logger.info(
                    "✓ 游戏设置已应用: timing=%+d speed=%.1f → "
                    "lat_comp=%.0fms advance=%.0fms vel_factor=%.3f",
                    result.game_timing_offset, result.game_note_speed,
                    result.adjusted_latency_comp_ms, result.adjusted_advance_ms,
                    result.velocity_correction_factor,
                )

                # 更新 tracker 的 manual_advance
                if hasattr(self.tracker, 'set_manual_advance'):
                    self.tracker.set_manual_advance(result.adjusted_advance_ms)

                # 持久化到 config.yaml
                try:
                    self._save_calibration_result(result)
                except Exception as e:
                    logger.debug("Failed to persist calibration: %s", e)
            else:
                logger.warning(
                    "游戏设置读取失败 (可能不在主菜单画面)。"
                    "将使用 config.yaml 中的现有参数。"
                )

        except ImportError as e:
            logger.debug("Game settings module not available: %s", e)
        except Exception as e:
            logger.warning("游戏设置读取异常 (不影响执行): %s", e)

    def _save_calibration_result(self, result) -> None:
        """将校准结果持久化到 config.yaml。"""
        import yaml
        import os

        config_paths = [
            "config.yaml",
            os.path.join(os.path.dirname(__file__), "config.yaml"),
        ]

        for path in config_paths:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}

                    if "game_settings" not in data:
                        data["game_settings"] = {}
                    gs = data["game_settings"]
                    gs["last_read_timing_offset"] = result.game_timing_offset
                    gs["last_read_note_speed"] = result.game_note_speed
                    gs["last_calibration_time"] = result.calibration_time
                    gs["detected_server"] = result.server

                    with open(path, "w", encoding="utf-8") as f:
                        yaml.dump(data, f, default_flow_style=False,
                                  allow_unicode=True, sort_keys=False)
                    logger.debug("Calibration result saved to %s", path)
                    return
                except Exception as e:
                    logger.debug("Failed to save to %s: %s", path, e)

    def _try_reconnect(self) -> bool:
        """尝试重连 ADB 设备。"""
        try:
            # 等待设备重新连接
            logger.info("等待设备重连...")
            for _ in range(10):
                if self.adb.is_connected():
                    logger.info("设备已重连")
                    # 重新初始化 minitouch
                    mt_cfg = self.cfg.get("minitouch", {})
                    if mt_cfg.get("auto_init", True):
                        self.adb.init_minitouch()
                    return True
                time.sleep(0.5)
            return False
        except Exception as e:
            logger.debug(f"重连异常: {e}")
            return False

    # ──────────────────────────────────────────
    # 主循环
    # ──────────────────────────────────────────

    def _main_loop(self) -> None:
        """
        核心循环: 截图 → 分析 → 预测 → 触摸。

        v5.2 优化:
          - 异步截屏 (producer-consumer): 主线程直接取缓存帧, 隐藏 ADB 延迟
          - 批量触摸: 帧结束时一次性发送所有触碰 (减少 subprocess 开销)
          - screencap 自动选择最快后端: scrcpy > raw > PNG
        """
        kb_enabled = True
        loop_count = 0  # 用于热键节流

        # ── v5.2: 主循环异常保护 + 异常退避 ──
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10

        while self._running:
            loop_start = time.perf_counter()
            loop_count += 1

            if self._paused:
                if kb_enabled and loop_count % 5 == 0 and self._check_keyboard():
                    pass
                time.sleep(0.1)
                continue

            try:
                # 1. 截图 (screencap 自动使用异步帧, 零额外延迟)
                frame = self.adb.screencap()
                if frame is None:
                    misses = self._stats["misses"] = self._stats.get("misses", 0) + 1
                    if misses >= 3:
                        logger.info(f"截图失败 ({self._stats['misses']}次), 尝试重连...")
                        if self._try_reconnect():
                            logger.info("重连成功")
                            self._stats["misses"] = 0
                        else:
                            logger.warning("重连失败, 继续尝试...")
                    if misses > 15:
                        logger.error("连续 15 次截图失败, 停止")
                        break
                    time.sleep(0.3)
                    continue

                self._stats["misses"] = 0
                consecutive_errors = 0

                # 2. 分析 (判定线 + 预测区域)
                state = self.analyzer.analyze(frame)
                self._stats["frames"] += 1
                # v5.4: 热路径 — 直接 += 避免 dict.get
                try:
                    self._stats["_frames_since_print"] += 1
                except KeyError:
                    self._stats["_frames_since_print"] = 1

                # 3. 如果不在游戏中, 等待 (自适应 sleep)
                if not state.in_game:
                    if self._last_game_active > 0:
                        idle = time.time() - self._last_game_active
                        if idle > self.game_over_timeout:
                            logger.info("游戏结束超时, 停止")
                            break
                    self.tracker.reset()
                    self.adb.flush_touch_batch()
                    wait_ms = min(50 + int(idle * 1000) if self._last_game_active > 0 else 50, 500)
                    time.sleep(wait_ms / 1000.0)
                    continue

                self._last_game_active = time.time()

                # 4. 预测 + 判定线处理 (共享逻辑)
                self._process_frame(state)

                # 6. 键盘热键检查 (节流: 每 5 帧检查一次)
                if kb_enabled and loop_count % 5 == 0:
                    self._check_keyboard()

                # 7. 显示实时统计
                if self.show_stats and self._stats["frames"] % self.stats_interval == 0:
                    self._print_stats()

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"主循环异常 (连续 {consecutive_errors} 次): {e}", exc_info=True)
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical("连续异常过多, 紧急停止")
                    break
                backoff = min(0.05 * (2 ** min(consecutive_errors, 5)), 2.0)
                time.sleep(backoff)

            # 8. 帧率控制 (自适应: 不强制 sleep 如果已经跑慢了)
            elapsed = time.perf_counter() - loop_start
            if elapsed < self.min_interval:
                sleep_time = self.min_interval - elapsed
                time.sleep(sleep_time)

    def _check_keyboard(self) -> bool:
        """
        检查键盘热键输入 (非阻塞)。
        跨平台支持: Unix (termios) / Windows (msvcrt).

        热键:
          p/P - 暂停/继续   q/Q - 退出
          +/- - 延迟补偿     </> - 亮度阈值
        """
        ch = self._get_key_nonblocking()
        if ch is None:
            return False

        c = ch.lower()
        if c == "p":
            self.pause()
            return True
        elif c == "q":
            logger.info("用户按 Q 退出")
            self._running = False
            return True
        elif c == "+" or c == "=":
            self.latency_comp += 5
            logger.info(f"延迟补偿: {self.latency_comp}ms")
            return True
        elif c == "-" or c == "_":
            self.latency_comp = max(0, self.latency_comp - 5)
            logger.info(f"延迟补偿: {self.latency_comp}ms")
            return True
        elif c == ">" or c == ".":
            self.analyzer.bright_thresh = min(255, self.analyzer.bright_thresh + 5)
            logger.info(f"亮度阈值: {self.analyzer.bright_thresh}")
            return True
        elif c == "<" or c == ",":
            self.analyzer.bright_thresh = max(0, self.analyzer.bright_thresh - 5)
            logger.info(f"亮度阈值: {self.analyzer.bright_thresh}")
            return True
        elif c == "[":
            # 降低时机抖动幅度
            self.timing_jitter_ms = max(0, self.timing_jitter_ms - 3)
            self.tracker.timing_jitter_ms = self.timing_jitter_ms
            logger.info(f"时机抖动: {self.timing_jitter_ms}ms"
                        f"{' (已禁用)' if self.timing_jitter_ms == 0 else ''}")
            return True
        elif c == "]":
            # 增加时机抖动幅度
            self.timing_jitter_ms = min(100, self.timing_jitter_ms + 3)
            self.tracker.timing_jitter_ms = self.timing_jitter_ms
            logger.info(f"时机抖动: {self.timing_jitter_ms}ms")
            # 启用随机化 (如果之前禁用了)
            if not self.rand_enabled:
                self.rand_enabled = True
                logger.info("点击随机化已自动启用")
            self.tracker.rand_enabled = self.rand_enabled
            return True
        elif c == "\\":
            # 切换随机化启用/禁用
            self.rand_enabled = not self.rand_enabled
            self.tracker.rand_enabled = self.rand_enabled
            status = "已启用" if self.rand_enabled else "已禁用"
            logger.info(f"点击随机化: {status}")
            return True
        elif c == "m":
            # 循环切换执行模式
            self.cycle_mode()
            return True

        return False

    # v5.4: 缓存 termios 属性避免每帧 tcgetattr
    _cached_termios_attrs = None

    @staticmethod
    def _get_key_nonblocking() -> Optional[str]:
        """
        跨平台非阻塞键盘读取。
          - Windows: msvcrt.kbhit()
          - Unix:    termios + select
        """
        import sys
        if sys.platform == "win32":
            try:
                import msvcrt
                if msvcrt.kbhit():
                    return msvcrt.getch().decode("utf-8", errors="ignore")
            except ImportError:
                pass
            return None

        # Unix/macOS
        try:
            import select
            import termios
            import tty
            fd = sys.stdin.fileno()
            if not select.select([sys.stdin], [], [], 0)[0]:
                return None
            if AutoPlayer._cached_termios_attrs is None:
                AutoPlayer._cached_termios_attrs = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                return sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, AutoPlayer._cached_termios_attrs)
        except (ImportError, AttributeError, Exception):
            return None

    # v5.2: 缓存 _supports_ansi 结果 (终端不支持中途改变)
    _cached_ansi_support: Optional[bool] = None

    @classmethod
    def _supports_ansi(cls) -> bool:
        """检测终端是否支持 ANSI 转义序列。结果缓存于类变量。"""
        if cls._cached_ansi_support is not None:
            return cls._cached_ansi_support
        import os
        if sys.platform == "win32":
            cls._cached_ansi_support = (
                os.environ.get("TERM") is not None or os.environ.get("WT_SESSION") is not None
            )
        else:
            cls._cached_ansi_support = sys.stdout.isatty()
        return cls._cached_ansi_support

    def _print_stats(self):
        """在终端打印实时统计信息。"""
        now = time.time()
        dt = now - self._stats["last_stats_time"]

        if dt > 0:
            actual_frames = self._stats.get("_frames_since_print", self.stats_interval)
            fps = actual_frames / dt
            self._stats["fps"] = fps
            self._stats["_frames_since_print"] = 0

        self._stats["last_stats_time"] = now

        use_ansi = self._supports_ansi()

        fps = self._stats['fps']
        frames = self._stats['frames']
        taps = self._stats['taps']
        flicks = self._stats['flicks']
        holds = self._stats['holds']
        comp = self.latency_comp
        thresh = self.analyzer.bright_thresh

        # v5.4: 单 f-string + 条件嵌入
        pred_part = f" | 预触发: {self._stats['predicted_triggers']}" if self.use_prediction else ""
        if use_ansi:
            line = (
                f"\033[36m[STATS]\033[0m "
                f"FPS: \033[33m{fps:.1f}\033[0m | "
                f"帧: {frames} | 点: {taps} 划: {flicks} 按: {holds}"
                f"{pred_part}"
                f" | 补偿: \033[32m{comp}ms\033[0m | "
                f"检测: \033[35m{thresh}\033[0m"
            )
        else:
            line = (
                f"[STATS] "
                f"FPS: {fps:.1f} | "
                f"帧: {frames} | 点: {taps} 划: {flicks} 按: {holds}"
                f"{pred_part}"
                f" | 补偿: {comp}ms | 检测: {thresh}"
            )

        sys.stdout.write("\r\033[K" + line)
        sys.stdout.flush()

    # ──────────────────────────────────────────
    # Note 处理
    # ──────────────────────────────────────────

    def _process_frame(self, state: GameState) -> None:
        """处理单帧: 预测引擎触发 + 判定线 note 处理。共享于 main_loop 和 batch。

        v5.2 优化: 使用批量触摸队列, 在帧结束时一次性发送所有触碰命令,
        避免每次 tap 都启动一个 adb 进程 (节省 ~50ms per tap)。
        """
        now = time.time()

        # 预测引擎: 触发提前发现的 note
        if self.use_prediction:
            triggers = self.tracker.update(
                state.predicted_notes,
                state.detected_notes,
                now,
            )
            for trigger in triggers:
                note_type = trigger["note_type"]

                if self._should_skip():
                    logger.debug(f"[PRED] SKIP lane={trigger['lane']} (随机漏键)")
                    continue
                jx, jy = self._apply_position_jitter(trigger["x"], trigger["y"])

                if note_type == "tap":
                    self.adb.queue_tap(jx, jy)
                    self._stats["predicted_triggers"] += 1
                    self._stats["taps"] += 1
                    logger.debug(f"[PRED] TAP lane={trigger['lane']} @({trigger['x']},{trigger['y']})")
                elif note_type == "flick":
                    self.adb.queue_swipe(jx, jy, jx, jy - self.flick_distance, self.flick_duration)
                    self._stats["predicted_triggers"] += 1
                    self._stats["flicks"] += 1

        # 判定线 notes (备用)
        if self._lane_positions is None:
            self._lane_positions = self.analyzer.get_lane_positions()
        self._process_notes(state)

        # ── v5.2: 帧结束时一次性发送所有批量触摸命令 ──
        self.adb.flush_touch_batch()

    def _process_notes(self, state: GameState) -> None:
        """处理检测到的判定线 notes (使用缓存的轨道位置)。

        v5.2: 增加 tap/flick 跨帧去重, 避免同一 note 被重复点击。
        """
        # 快速路径: 无 note 时只检查 hold 释放
        if not state.detected_notes:
            if self._held_lanes:
                for lane in list(self._held_lanes):
                    self._release_lane(lane, self._lane_positions)
            return

        current_active = set()
        lane_positions = self._lane_positions or self.analyzer.get_lane_positions()

        for note in state.detected_notes:
            lane_x, lane_y = lane_positions[note.lane]
            current_active.add(note.lane)

            if note.note_type == "tap":
                # 去重: 同一 lane 在前一帧已触发过 tap 则跳过
                if not self._lane_tap_cooldown.get(note.lane, 0):
                    self._do_tap(note, lane_x, lane_y)
                    self._lane_tap_cooldown[note.lane] = self._tap_cooldown_frames
            elif note.note_type == "flick":
                if not self._lane_flick_cooldown.get(note.lane, 0):
                    self._do_flick(note, lane_x, lane_y)
                    self._lane_flick_cooldown[note.lane] = self._flick_cooldown_frames
            elif note.note_type == "hold":
                self._do_hold(note, lane_x, lane_y)

        # 帧级 cooldown 衰减
        # v5.4: dict comprehension
        self._lane_tap_cooldown = {
            k: v - 1 for k, v in self._lane_tap_cooldown.items() if v > 1
        }
        self._lane_flick_cooldown = {
            k: v - 1 for k, v in self._lane_flick_cooldown.items() if v > 1
        }

        for lane in list(self._held_lanes):
            if lane not in current_active:
                self._release_lane(lane, lane_positions)

    def _do_tap(self, note: NoteEvent, x: int, y: int) -> None:
        """处理 tap note，应用随机化 (位置抖动 + 漏键)。v5.2: 使用批量队列。"""
        if self._should_skip():
            logger.debug(f"SKIP tap lane={note.lane} @({x},{y}) (随机漏键)")
            return
        jx, jy = self._apply_position_jitter(x, y)
        self.adb.queue_tap(jx, jy)
        self._stats["taps"] += 1
        if jx != x or jy != y:
            logger.debug(f"TAP  lane={note.lane} @({x},{y}) → ({jx},{jy})  conf={note.confidence:.2f}")
        else:
            logger.debug(f"TAP  lane={note.lane} @({x},{y})  conf={note.confidence:.2f}")

    def _do_flick(self, note: NoteEvent, x: int, y: int) -> None:
        """处理 flick note，应用位置随机化。v5.2: 使用批量队列。"""
        if self._should_skip():
            logger.debug(f"SKIP flick lane={note.lane} @({x},{y}) (随机漏键)")
            return
        jx, jy = self._apply_position_jitter(x, y)
        direction = note.flick_direction or "up"
        dist = self.flick_distance
        dur = self.flick_duration
        if direction == "up":
            self.adb.queue_swipe(jx, jy, jx, jy - dist, dur)
        elif direction == "down":
            self.adb.queue_swipe(jx, jy, jx, jy + dist, dur)
        elif direction == "left":
            self.adb.queue_swipe(jx, jy, jx - dist, jy, dur)
        elif direction == "right":
            self.adb.queue_swipe(jx, jy, jx + dist, jy, dur)
        else:
            self.adb.queue_swipe(jx, jy, jx, jy - dist, dur)

        self._stats["flicks"] += 1
        logger.debug(f"FLICK lane={note.lane} dir={direction} @({x},{y})")

    def _do_hold(self, note: NoteEvent, x: int, y: int) -> None:
        """处理 hold note，应用位置随机化 + 长按时长抖动。v5.2: 使用批量队列。"""
        if self._should_skip():
            logger.debug(f"SKIP hold lane={note.lane} @({x},{y}) (随机漏键)")
            return
        jx, jy = self._apply_position_jitter(x, y)
        if note.lane not in self._held_lanes:
            # hold 开始: 用 press (长按), 通过 queue_swipe 原地模拟
            jittered_dur = self._apply_hold_jitter(100)
            self.adb.queue_swipe(jx, jy, jx, jy, jittered_dur)
            self._held_lanes.add(note.lane)
            self._stats["holds"] += 1
            logger.debug(f"HOLD START lane={note.lane} @({x},{y})→({jx},{jy}) dur={jittered_dur}ms")
        else:
            # hold 续期
            jittered_dur = self._apply_hold_jitter(50)
            self.adb.queue_swipe(jx, jy, jx, jy, jittered_dur)

    def _release_lane(self, lane: int, positions: list) -> None:
        self._held_lanes.discard(lane)
        logger.debug(f"HOLD END  lane={lane}")

    def _release_all(self) -> None:
        self._held_lanes.clear()

    # ──────────────────────────────────────────
    # 点击随机化 (反封号) —— 模拟人类操作
    # ──────────────────────────────────────────

    def _apply_position_jitter(self, x: int, y: int) -> tuple[int, int]:
        """对点击坐标施加随机偏移，模拟手指落点不精确。"""
        if not self.rand_enabled or self.position_jitter_px <= 0:
            return x, y
        jx = random.randint(-self.position_jitter_px, self.position_jitter_px)
        jy = random.randint(-self.position_jitter_px, self.position_jitter_px)
        return max(0, x + jx), max(0, y + jy)

    def _apply_hold_jitter(self, base_ms: int) -> int:
        """对长按时长施加随机偏移。"""
        if not self.rand_enabled or self.hold_duration_jitter_ms <= 0:
            return base_ms
        offset = random.randint(-self.hold_duration_jitter_ms,
                                self.hold_duration_jitter_ms)
        return max(10, base_ms + offset)

    def _should_skip(self) -> bool:
        """随机决定是否跳过本次点击 (模拟漏键)。"""
        if not self.rand_enabled or self.miss_chance <= 0:
            return False
        return random.random() < self.miss_chance

    # ──────────────────────────────────────────
    # 执行模式切换 (AP / FC / LIVE)
    # ──────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        """切换到指定执行模式, 自动应用对应随机化参数。
           同时同步到预测引擎 NoteTracker。"""
        mode = mode.upper()
        if mode not in PERFORMANCE_MODES:
            logger.warning(f"未知执行模式: {mode}, 使用 FC")
            mode = "FC"

        preset = PERFORMANCE_MODES[mode]
        self._mode = mode
        self._mode_index = MODE_NAMES.index(mode)
        self.timing_jitter_ms = preset["timing_jitter_ms"]
        self.position_jitter_px = preset["position_jitter_px"]
        self.miss_chance = preset["miss_chance"]
        self.hold_duration_jitter_ms = preset["hold_duration_jitter_ms"]

        # 同步到 NoteTracker (预测引擎也使用这些随机化参数)
        self.tracker.timing_jitter_ms = preset["timing_jitter_ms"]
        self.tracker.rand_enabled = self.rand_enabled

        logger.info(f"🎮 切换到 {preset['label']}  ─ "
                     f"时机±{preset['timing_jitter_ms']}ms  "
                     f"坐标±{preset['position_jitter_px']}px  "
                     f"漏键{preset['miss_chance']*100:.1f}%")

    def cycle_mode(self) -> None:
        """循环切换到下一个模式。"""
        next_idx = (self._mode_index + 1) % len(MODE_NAMES)
        self.set_mode(MODE_NAMES[next_idx])

    @property
    def mode_name(self) -> str:
        return self._mode

    @property
    def mode_label(self) -> str:
        return PERFORMANCE_MODES[self._mode]["label"]


# ──────────────────────────────────────────
# 校准工具
# ──────────────────────────────────────────

class Calibrator:
    """
    校准工具: 自动测量延迟、判定线位置、轨道位置、游戏速度。
    改进: 自动写入 config.yaml + 自动检测游戏设置。
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.adb = ADBController(config)
        self.analyzer = ScreenAnalyzer(config)

    def detect_game_speed(self, duration_s: float = 8.0) -> dict:
        """
        自动检测游戏 note 滚动速度, 返回推荐的预测参数。

        原理: 录制几秒游戏画面, 用 NoteTracker 追踪 note,
              计算平均滚动速度, 反推最优的预测提前量和检测区域。

        Returns:
            {
                "avg_velocity": float,    # 平均滚动速度 (px/s)
                "recommended_lookahead_ms": int,  # 推荐提前检测窗口
                "recommended_detect_ratio": float, # 推荐检测区域比例
                "recommended_latency_comp_ms": int,
                "detected": bool,
                "message": str,
            }
        """
        logger.info("=" * 50)
        logger.info("🎯 自动检测游戏速度")
        logger.info(f"请在手机上进入 PJSK 执行界面, 程序将录制 {duration_s:.0f} 秒")
        logger.info("=" * 50)

        if not self.adb.wait_for_device(timeout=10):
            return {"detected": False, "message": "设备未连接"}

        # 手动创建 NoteTracker
        tracker = NoteTracker(self.cfg)

        # 测量延迟
        latency = self.adb.measure_latency(samples=3)
        total_latency = latency.get("total_avg_ms", 100)
        tracker.set_latency(total_latency)

        velocities = []
        frame_count = 0
        start_t = time.time()

        logger.info("录制中...")
        while time.time() - start_t < duration_s:
            frame = self.adb.screencap()
            if frame is None:
                time.sleep(0.05)
                continue

            state = self.analyzer.analyze(frame)
            frame_count += 1

            if not state.in_game:
                time.sleep(0.1)
                continue

            now = time.time()
            triggers = tracker.update(state.predicted_notes, state.detected_notes, now)

            # 记录有速度的轨道
            for lane, track in tracker._tracks.items():
                v = abs(track.get("velocity", 0))
                if v > 100:  # 有效速度下限
                    velocities.append(v)

            # 限制精度 (30fps 足够)
            time.sleep(0.03)

        logger.info(f"录制完成: {frame_count} 帧, {len(velocities)} 个速度样本")

        if len(velocities) < 10:
            logger.warning("速度样本不足, 请确保在执行画面中运行")
            return {"detected": False, "message": "速度样本不足, 请打开执行界面后重试"}

        avg_v = sum(velocities) / len(velocities)
        velocities.sort()
        median_v = velocities[len(velocities) // 2]

        # 基于速度计算推荐参数
        screen_h = self.cfg["screen"]["height"]
        # 判定线上方区域比例: 速度越快, 需要更大的检测区域
        # 基础: 0.25; 每 500px/s 加 0.05
        detect_ratio = max(0.2, min(0.6, 0.20 + (median_v / 500) * 0.05))
        # 提前检测窗口: 计算让 note 从 detect_top 滚到判定线的时间
        detect_distance_px = detect_ratio * screen_h
        scroll_time_ms = (detect_distance_px / median_v) * 1000
        lookahead_ms = int(scroll_time_ms * 0.6)  # 60% 位置开始规律追踪

        msg = (f"平均速度: {avg_v:.0f} px/s, 中位: {median_v:.0f} px/s\n"
               f"推荐检测区域: {detect_ratio:.3f} "
               f"(能提前 {scroll_time_ms:.0f}ms 发现 note)\n"
               f"推荐预测窗口 lookahead: {lookahead_ms}ms\n"
               f"推荐延迟补偿: {int(total_latency)}ms")
        logger.info(msg)

        result = {
            "detected": True,
            "avg_velocity": round(avg_v, 1),
            "median_velocity": round(median_v, 1),
            "recommended_detect_ratio": round(detect_ratio, 4),
            "recommended_lookahead_ms": lookahead_ms,
            "recommended_latency_comp_ms": int(total_latency),
            "sample_count": len(velocities),
            "message": msg,
        }

        # 自动写入 config
        self._auto_save_speed(result)
        return result

    def _auto_save_speed(self, result: dict) -> bool:
        """自动将速度检测结果写入 config.yaml。"""
        import yaml
        config_path = "config.yaml"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            modified = False

            if result["recommended_detect_ratio"]:
                config.setdefault("screen", {})
                config["screen"]["note_detect_region_ratio"] = result["recommended_detect_ratio"]
                modified = True

            if result["recommended_lookahead_ms"]:
                config.setdefault("prediction", {})
                config["prediction"]["lookahead_ms"] = result["recommended_lookahead_ms"]
                modified = True

            if result["recommended_latency_comp_ms"]:
                config.setdefault("timing", {})
                config["timing"]["latency_compensation_ms"] = result["recommended_latency_comp_ms"]
                modified = True

            if modified:
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(config, f, default_flow_style=False,
                              allow_unicode=True, sort_keys=False)
                logger.info("  ✅ config.yaml 已自动更新 (游戏速度参数)")
                return True
        except Exception as e:
            logger.warning(f"自动写入游戏速度配置失败: {e}")
        return False

    def run_all(self) -> dict:
        """运行全部校准, 返回校准结果。"""
        logger.info("=" * 50)
        logger.info("PJSK Auto Player - 校准工具")
        logger.info("=" * 50)

        if not self.adb.wait_for_device(timeout=10):
            logger.error("设备未连接")
            return {}

        results = {}

        # 1. 延迟测量
        logger.info("\n[1/3] 测量 ADB 延迟...")
        results["latency"] = self.adb.measure_latency(samples=5)
        if "total_avg_ms" in results["latency"]:
            logger.info(f"  截图平均: {results['latency']['screencap_avg_ms']:.1f}ms")
            logger.info(f"  触摸平均: {results['latency']['tap_avg_ms']:.1f}ms")
            logger.info(f"  总延迟:   {results['latency']['total_avg_ms']:.1f}ms")
            recommended = results["latency"]["total_avg_ms"]
            results["recommended_compensation_ms"] = round(recommended)
            logger.info(f"  推荐延迟补偿: {round(recommended)}ms")

        # 2. 截图
        logger.info("\n[2/3] 获取屏幕截图用于视觉校准...")
        frame = self.adb.screencap()
        if frame is None:
            logger.error("截图失败")
            return results

        h, w = frame.shape[:2]
        self.cfg["screen"]["width"] = w
        self.cfg["screen"]["height"] = h
        self.analyzer = ScreenAnalyzer(self.cfg)

        # 3. 判定线校准
        logger.info("\n[3/3] 校准判定线和轨道位置...")
        judgment_y = self.analyzer.calibrate_judgment_line(frame)
        results["judgment_line_y"] = judgment_y
        results["judgment_line_y_ratio"] = round(judgment_y / h, 4)
        logger.info(f"  判定线 Y={judgment_y} (比例={results['judgment_line_y_ratio']})")

        lanes = self.analyzer.calibrate_lanes(frame)
        if lanes:
            lane_ratios = [round(x / w, 4) for x in lanes]
            mid = w // 2
            left = [r for r, x in zip(lane_ratios, lanes) if x < mid]
            right = [r for r, x in zip(lane_ratios, lanes) if x >= mid]
            results["left_lanes"] = left
            results["right_lanes"] = right
            logger.info(f"  左轨道: {left}")
            logger.info(f"  右轨道: {right}")

        # 保存校准截图
        debug_path = "calibration_result.jpg"
        debug_frame = frame.copy()
        cv2.line(debug_frame, (0, judgment_y), (w, judgment_y), (0, 255, 0), 3)
        for lx, _ in self.analyzer.get_lane_positions():
            cv2.circle(debug_frame, (lx, judgment_y), 15, (0, 0, 255), 3)
        cv2.imwrite(debug_path, debug_frame)
        logger.info(f"\n校准结果截图已保存: {debug_path}")

        # ── 自动写入 config.yaml ──
        auto_save = self._auto_save_config(results)
        if auto_save:
            logger.info("\n✅ 校准完成! 配置已自动更新到 config.yaml")
        else:
            logger.info("\n⚠️  无法自动写入 config.yaml")
            logger.info("请将以下内容手动添加到 config.yaml:")
            self._print_config_snippet(results)

        logger.info("=" * 50)
        return results

    def _auto_save_config(self, results: dict) -> bool:
        """自动将校准结果写入 config.yaml。"""
        import yaml

        config_path = "config.yaml"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            modified = False

            if "judgment_line_y_ratio" in results:
                config["screen"]["judgment_line_y"] = results["judgment_line_y_ratio"]
                modified = True

            if "left_lanes" in results and results["left_lanes"]:
                config["screen"]["left_lanes"] = results["left_lanes"]
                modified = True

            if "right_lanes" in results and results["right_lanes"]:
                config["screen"]["right_lanes"] = results["right_lanes"]
                modified = True

            if "recommended_compensation_ms" in results:
                if "timing" not in config:
                    config["timing"] = {}
                config["timing"]["latency_compensation_ms"] = results["recommended_compensation_ms"]
                modified = True

            if modified:
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(config, f, default_flow_style=False,
                              allow_unicode=True, sort_keys=False)
                logger.info("  ✅ config.yaml 已自动更新")
                return True

        except Exception as e:
            logger.warning(f"自动写入配置失败: {e}")

        return False

    def _print_config_snippet(self, results: dict):
        """打印配置文本块 (供手动复制)。"""
        print("\n📝 请将以下内容更新到 config.yaml:\n")
        print("screen:")
        print(f"  width: {self.cfg['screen']['width']}")
        print(f"  height: {self.cfg['screen']['height']}")
        if "judgment_line_y_ratio" in results:
            print(f"  judgment_line_y: {results['judgment_line_y_ratio']}")
        if "left_lanes" in results and results["left_lanes"]:
            print(f"  left_lanes: {results['left_lanes']}")
        if "right_lanes" in results and results["right_lanes"]:
            print(f"  right_lanes: {results['right_lanes']}")
        if "recommended_compensation_ms" in results:
            comp = results["recommended_compensation_ms"]
            print("\ntiming:")
            print(f"  latency_compensation_ms: {comp}")
        print()

    def interactive_calibrate(self):
        """交互式校准: 实时预览 + 按键调参。"""
        import os

        if not self.adb.wait_for_device(timeout=10):
            return

        print("交互式校准已启动。")
        print("请在手机上打开 PJSK 执行界面。")
        print("按键: q=退出  r=重新校准  +/- 调整判定线  </> 调整阈值")

        cv2.namedWindow("PJSK Calibrator", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("PJSK Calibrator", 540, 960)

        threshold = self.cfg["detection"]["brightness"]["threshold"]
        judgment_y = self.analyzer.judgment_y
        running = True

        while running:
            frame = self.adb.screencap()
            if frame is None:
                time.sleep(0.1)
                continue

            h, w = frame.shape[:2]
            if w != self.cfg["screen"]["width"] or h != self.cfg["screen"]["height"]:
                self.cfg["screen"]["width"] = w
                self.cfg["screen"]["height"] = h
                self.analyzer = ScreenAnalyzer(self.cfg)
                judgment_y = self.analyzer.judgment_y

            state = self.analyzer.analyze(frame)

            debug = frame.copy()
            cv2.line(debug, (0, judgment_y), (w, judgment_y), (0, 255, 0), 2)
            # 检测区域上边界
            cv2.line(debug, (0, self.analyzer.note_detect_top),
                     (w, self.analyzer.note_detect_top), (255, 255, 0), 1)

            for idx, (lx, ly) in enumerate(self.analyzer.get_lane_positions()):
                active = any(n.lane == idx for n in state.detected_notes)
                color = (0, 0, 255) if active else (128, 128, 128)
                cv2.circle(debug, (lx, ly), self.analyzer.detect_radius, color, 2)
                if active:
                    cv2.circle(debug, (lx, ly), 8, (0, 0, 255), -1)

            # 画预测 note
            for note in state.predicted_notes:
                cv2.circle(debug, (note.x, note.y), 6, (255, 0, 255), -1)

            info = [
                f"Threshold: {threshold}",
                f"Judgment Y: {judgment_y} ({judgment_y/h:.3f})",
                f"Notes: {len(state.detected_notes)}  Pred: {len(state.predicted_notes)}",
                f"In Game: {state.in_game}",
                f"'q'=quit  'r'=recalib  '+/-'=adj Y  '</>'=adj thr",
            ]
            for i, text in enumerate(info):
                cv2.putText(debug, text, (10, 30 + i * 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            cv2.imshow("PJSK Calibrator", debug)
            key = cv2.waitKey(30) & 0xFF

            if key == ord("q"):
                running = False
            elif key == ord("r"):
                new_y = self.analyzer.calibrate_judgment_line(frame)
                if new_y:
                    judgment_y = new_y
                    self.analyzer.judgment_y = new_y
            elif key == ord("+") or key == ord("="):
                judgment_y = min(h - 10, judgment_y + 5)
                self.analyzer.judgment_y = judgment_y
            elif key == ord("-") or key == ord("_"):
                judgment_y = max(10, judgment_y - 5)
                self.analyzer.judgment_y = judgment_y
            elif key == ord(".") or key == ord(">"):
                threshold = min(255, threshold + 5)
                self.analyzer.bright_thresh = threshold
                self.cfg["detection"]["brightness"]["threshold"] = threshold
            elif key == ord(",") or key == ord("<"):
                threshold = max(0, threshold - 5)
                self.analyzer.bright_thresh = threshold
                self.cfg["detection"]["brightness"]["threshold"] = threshold

        cv2.destroyAllWindows()


# ──────────────────────────────────────────
# 连续执行 (Continuous Execution) —— 自动连续执行
# ──────────────────────────────────────────

class BatchPlayer:
    """
    连续执行: 自动连续执行, 处理结算画面、等待、重试。

    工作流程:
      1. 启动 AutoPlayer, 等待用户进入执行
      2. 等待歌曲结束 (game_over_timeout)
      3. 检测结算画面, 逐次点击返回选歌
      4. 等待回到执行画面
      5. 重复 2-4, 直到达到指定次数
    """

    def __init__(self, config: dict, song_count: int = 0, mode: str = "FC"):
        self.cfg = config
        self.player = AutoPlayer(config, mode=mode)

        # Pipeline 引擎 (v3.0.0+)
        self.pipeline: Optional[PipelineEngine] = None
        self._use_pipeline = False

        bp = config.get("batch_play", {})
        self.target_count = song_count or bp.get("default_count", 0)
        self.result_wait = bp.get("result_wait_seconds", 4.0)
        self.result_tap_interval = bp.get("result_tap_interval", 2.5)
        self.max_result_taps = bp.get("max_result_taps", 15)
        self.next_song_timeout = bp.get("next_song_timeout", 30.0)
        self.song_timeout = bp.get("song_timeout", 360)
        self.max_failures = bp.get("max_failures_per_song", 20)

        # 连续执行浮动权重: 每首歌随机选择执行模式
        mode_weights = bp.get("mode_weights", {"AP": 25, "FC": 70, "LIVE": 5})
        self._mode_pool = []
        for m, w in mode_weights.items():
            m = m.upper()
            if m in MODE_NAMES and w > 0:
                self._mode_pool.extend([m] * w)
        if not self._mode_pool:
            self._mode_pool = ["FC"]  # fallback

        # 尝试初始化 Pipeline 引擎
        if _HAS_PIPELINE and bp.get("use_pipeline", True):
            try:
                self.pipeline = PipelineEngine(
                    config,
                    adb_controller=self.player.adb,
                    screen_analyzer=self.player.analyzer,
                )

                # 加载任务定义
                pipeline_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "tasks"
                )
                if os.path.exists(pipeline_dir):
                    self.pipeline.load_tasks(pipeline_dir)
                    self._use_pipeline = True
                    logger.info(f"Pipeline 引擎已初始化 ({len(self.pipeline._tasks)} 个任务)")
                else:
                    logger.info("tasks/ 目录不存在, 回退到传统模式")
            except Exception as e:
                logger.warning(f"Pipeline 引擎初始化失败: {e}, 回退到传统模式")

        self._running = False
        self._batch_stats = {
            "songs_played": 0,
            "songs_failed": 0,
            "total_taps": 0,
            "total_flicks": 0,
            "total_holds": 0,
            "total_frames": 0,
            "start_time": 0.0,
            "total_game_time": 0.0,
        }

    def start(self) -> None:
        """启动连续执行。"""
        # 先用 AutoPlayer 的 prepare 逻辑
        if not self.player._ensure_ready():
            return

        # 测量延迟
        if self.player.use_prediction:
            logger.info("测量 ADB 延迟...")
            latency = self.player.adb.measure_latency(samples=3)
            total = latency.get("total_avg_ms", 0)
            if total > 0:
                self.player.tracker.set_latency(total)

        self._running = True
        self._batch_stats["start_time"] = time.time()

        # 初始化 Web 仪表盘状态文件
        self._write_stats()

        count_label = f"{self.target_count} 首" if self.target_count > 0 else "无限"
        # 显示模式浮动范围
        unique_modes = sorted(set(self._mode_pool))
        mode_range = "→".join(PERFORMANCE_MODES[m]["label"] for m in unique_modes)
        logger.info("=" * 60)
        logger.info("🔥 PJSK 连续执行 已启动!")
        logger.info(f"目标次数: {count_label}")
        logger.info(f"模式浮动: {mode_range}")
        logger.info(f"延迟补偿: {self.player.latency_comp}ms")
        logger.info("请在手机上进入执行画面, 程序将自动循环")
        logger.info("按 Ctrl+C 停止")
        logger.info("=" * 60)

        try:
            if self._use_pipeline and self.pipeline:
                logger.info("使用 Pipeline 引擎执行连续执行...")
                self._run_with_pipeline()
            else:
                self._auto_play_loop()
        except KeyboardInterrupt:
            logger.info("\n收到中断信号...")
        finally:
            self._print_final_stats()
            self._cleanup()

    def _run_with_pipeline(self):
        """使用 Pipeline 引擎执行连续执行。"""
        if not self.pipeline:
            self._auto_play_loop()
            return

        song_count = 0
        target = self.target_count

        def on_task(task, result, state):
            nonlocal song_count
            if task.name == "PlaySong" and result.matched:
                # 执行执行
                self._play_one_song()
                song_count += 1
                logger.info(f"✅ 第 {song_count} 首 完成  "
                           f"({song_count}/{target if target>0 else '∞'})")

                # 检查是否达到目标
                if target > 0 and song_count >= target:
                    logger.info(f"✅ 已完成 {target} 首, 连续执行结束!")
                    self.pipeline.stop()

        # 注册回调来拦截 PlaySong 任务
        self.pipeline.run("BatchStart", callback=on_task)

    def _auto_play_loop(self):
        """连续执行主循环: 执行 → 结算 → 下一首。"""
        while self._running:
            # 检查是否达到目标次数
            if self.target_count > 0 and \
               self._batch_stats["songs_played"] >= self.target_count:
                logger.info(f"✅ 已完成 {self.target_count} 首, 连续执行结束!")
                break

            # ── 1. 等待进入执行画面 ──
            song_num = self._batch_stats["songs_played"] + 1
            logger.info(f"\n{'─' * 40}")
            logger.info(f"🎵 第 {song_num} 首 — 等待执行开始...")

            if not self._wait_for_game_start():
                logger.info("等待执行开始超时, 停止")
                break

            # ── 2. 执行 ──
            logger.info(f"▶ 第 {song_num} 首 开始!")
            song_start = time.time()
            song_stats = self._play_one_song()
            game_time = time.time() - song_start

            # ── 3. 统计 ──
            if song_stats:
                self._batch_stats["songs_played"] += 1
                self._batch_stats["total_taps"] += song_stats.get("taps", 0)
                self._batch_stats["total_flicks"] += song_stats.get("flicks", 0)
                self._batch_stats["total_holds"] += song_stats.get("holds", 0)
                self._batch_stats["total_frames"] += song_stats.get("frames", 0)
                self._batch_stats["total_game_time"] += game_time
                self._write_stats()  # ← 更新 Web 仪表盘
                logger.info(f"✅ 第 {song_num} 首 完成! "
                           f"用时: {game_time:.1f}s  "
                           f"点: {song_stats.get('taps', 0)}  "
                           f"划: {song_stats.get('flicks', 0)}")

                # 每 5 首歌重新测量 ADB 延迟, 自适应优化
                if self._batch_stats["songs_played"] % 5 == 0:
                    try:
                        latency = self.player.adb.measure_latency(samples=2)
                        total = latency.get("total_avg_ms", 0)
                        if total > 0:
                            self.player.tracker.set_latency(total)
                            self.player.latency_comp = int(total)
                            logger.info(f"⚡ ADB 延迟自适应: {total:.0f}ms (已更新)")
                    except Exception:
                        pass
            else:
                self._batch_stats["songs_failed"] += 1
                logger.warning(f"⚠️  第 {song_num} 首 异常结束")

            # ── 4. 处理结算画面 ──
            if self._running:
                logger.info("📊 检测到结算画面, 正在跳过...")
                self._handle_result_screen()

            # 短期暂停防止过热
            time.sleep(0.5)

    def _wait_for_game_start(self, need_game: bool = True) -> bool:
        """
        等待进入执行画面。

        Returns:
            True 如果检测到执行开始, False 如果超时
        """
        timeout = self.next_song_timeout
        start_time = time.time()

        while time.time() - start_time < timeout:
            if not self._running:
                return False

            frame = self.player.adb.screencap()
            if frame is None:
                time.sleep(0.3)
                continue

            screen_type = self.player.analyzer.classify_screen(frame)

            if need_game and screen_type == "game":
                # 确认确实是执行中: 连续检测到 2 次
                time.sleep(0.1)
                frame2 = self.player.adb.screencap()
                if frame2 and self.player.analyzer.classify_screen(frame2) == "game":
                    return True

            if not need_game and screen_type != "game":
                return True

            time.sleep(0.2)

        return False

    def _pick_and_apply_mode(self) -> None:
        """从权重池中随机选择一个执行模式, 应用到 player。
           如果历史记录中有失败记录, 动态降级模式以提高稳定性。"""
        pool = list(self._mode_pool)

        # 动态调整: 读取最近记录, 降低容易出问题的模式的权重
        try:
            hist_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), ".song_history.json"
            )
            if os.path.exists(hist_file):
                with open(hist_file) as f:
                    history = json.load(f)
                # 只看最近 10 首
                recent = history[-10:] if len(history) > 10 else history
                # 统计每个模式的失败率 (帧数过少的歌曲视为异常)
                mode_failures = {}
                mode_total = {}
                for s in recent:
                    m = s.get("mode", "FC")
                    mode_total[m] = mode_total.get(m, 0) + 1
                    frames = s.get("frames", 0)
                    duration = s.get("duration", 0)
                    # 少于 200 帧或小于 10 秒 => 异常歌曲
                    if frames < 200 or duration < 10:
                        mode_failures[m] = mode_failures.get(m, 0) + 1

                for m, failures in mode_failures.items():
                    total = mode_total.get(m, 1)
                    fail_rate = failures / total
                    if fail_rate > 0.3:
                        # 失败率超过 30%, 降低该模式的权重 (移除一半的该模式实例)
                        remove_count = pool.count(m) // 2
                        for _ in range(remove_count):
                            if m in pool:
                                pool.remove(m)
                        logger.debug(f"策略: {m} 失败率 {fail_rate:.0%}, 权重已降低")
                # 确保池子不为空
                if not pool:
                    pool = ["FC"]
        except Exception:
            pass

        chosen = random.choice(pool)
        self.player.set_mode(chosen)

    def _play_one_song(self) -> Optional[dict]:
        """
        打一首歌, 返回该次执行的统计。

        内部使用 AutoPlayer 的循环逻辑, 但增加了:
          - 单曲超时保护
          - 结算画面检测后自动退出循环
          - 随机模式浮动 (FC/AP/LIVE)
        """
        # 每首歌随机选择执行模式 (浮动 AP/FC/LIVE)
        self._pick_and_apply_mode()

        # 重置追踪器和统计 (每首歌独立)
        self.player.tracker.reset()
        self.player._reset_stats()

        self.player._running = True
        self.player._paused = False
        self.player._stats["start_time"] = time.time()
        self.player._stats["last_stats_time"] = time.time()
        self.player._last_game_active = time.time()

        song_start = time.time()
        failures = 0

        loop_count = 0
        while self.player._running:
            loop_count += 1
            # 单曲超时
            if time.time() - song_start > self.song_timeout:
                logger.warning(f"⏰ 单曲超时 ({self.song_timeout}s), 跳过")
                break

            loop_start = time.perf_counter()

            if self.player._paused:
                time.sleep(0.1)
                continue

            # 热键检查 (每 10 帧)
            if loop_count % 10 == 0:
                self.player._check_keyboard()

            # 截图 (v5.2: screencap() 自动使用异步帧, 零延迟)
            frame = self.player.adb.screencap()
            if frame is None:
                failures += 1
                if failures > self.max_failures:
                    logger.error(f"连续 {failures} 次截图失败, 放弃当前歌曲")
                    break
                time.sleep(0.05)
                continue

            failures = 0

            # 分析
            state = self.player.analyzer.analyze(frame)
            self.player._stats["frames"] += 1

            # 画面分类
            if state.in_result:
                # 歌曲结束, 结算画面出现
                logger.info("检测到结算画面, 结束执行")
                self.player._running = False
                break

            if not state.in_game and not state.in_menu:
                # 既不是执行也不是菜单 — 可能是加载或过渡
                if self.player._last_game_active > 0:
                    idle = time.time() - self.player._last_game_active
                    if idle > self.player.game_over_timeout:
                        logger.info("游戏结束超时, 结束执行")
                        self.player._running = False
                        break
                self.player.tracker.reset()
                time.sleep(0.05)
                continue

            if not state.in_game:
                # 菜单/选歌画面
                self.player.tracker.reset()
                time.sleep(0.05)
                continue

            # 执行中
            self.player._last_game_active = time.time()

            # 预测 + 判定线 (共享逻辑)
            self.player._process_frame(state)

            # 实时统计
            if self.player.show_stats and \
               self.player._stats["frames"] % self.player.stats_interval == 0:
                self.player._print_stats()

            # 帧率控制
            elapsed = time.perf_counter() - loop_start
            sleep_time = self.player.min_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        # 收集统计
        self.player._release_all()
        song_stats = {
            "taps": self.player._stats["taps"],
            "flicks": self.player._stats["flicks"],
            "holds": self.player._stats["holds"],
            "frames": self.player._stats["frames"],
            "predicted": self.player._stats.get("predicted_triggers", 0),
            "mode": self.player.mode_name,
            "timestamp": time.time(),
            "duration": time.time() - song_start,
        }
        # 写入历史记录
        self._append_song_history(song_stats)
        return song_stats

    def _handle_result_screen(self):
        """
        处理结算画面: 等待 → 逐次点击 → 返回选歌。
        应用随机化: 点击间隔抖动 + 位置小偏移。

        PJSK 典型结算流程:
          1. 分数展示 (自动滚动)  ~3s
          2. 点击 → 详细结果
          3. 点击 → 可能显示称号/等级提升
          4. 点击 → 返回歌曲选择/房间
        """
        # 等待结算动画播放 (带随机化)
        wait_interval = self.result_wait
        if self.player.rand_enabled:
            jitter = random.uniform(-1.0, 1.0)  # ±1s 随机等待
            wait_interval = max(1.5, wait_interval + jitter)
        time.sleep(wait_interval)

        # 找到屏幕中央
        w = self.cfg.get("screen", {}).get("width", 1080)
        h = self.cfg.get("screen", {}).get("height", 2400)
        cx, cy = w // 2, h // 2

        result_tap_jitter = self.cfg.get("randomization", {}).get(
            "result_tap_jitter", 0.8
        )

        for i in range(self.max_result_taps):
            if not self._running:
                return

            # 点击屏幕中央 (带位置微偏，模拟手指每次落点不同)
            tap_x, tap_y = self.player._apply_position_jitter(cx, cy)
            self.player.adb.tap(tap_x, tap_y)

            # 随机化点击间隔: 模拟人类观看结算画面的速度变化
            base_interval = self.result_tap_interval
            if self.player.rand_enabled and result_tap_jitter > 0:
                offset = random.uniform(-result_tap_jitter, result_tap_jitter)
                actual_interval = max(0.8, base_interval + offset)
            else:
                actual_interval = base_interval
            time.sleep(actual_interval)

            # 检查画面状态
            frame = self.player.adb.screencap()
            if frame is None:
                continue

            st = self.player.analyzer.classify_screen(frame)

            if st == "game":
                logger.info("✅ 已返回执行画面")
                return
            if st == "menu":
                logger.info("✅ 已返回选歌/菜单")
                return

        logger.warning(f"⚠️  结算画面点击 {self.max_result_taps} 次仍未回到选歌, "
                       "尝试继续...")

    def _print_final_stats(self):
        """打印连续执行最终统计。"""
        elapsed = time.time() - self._batch_stats["start_time"]
        played = self._batch_stats["songs_played"]

        logger.info("=" * 50)
        logger.info("🔥 连续执行统计")
        logger.info("=" * 50)
        logger.info(f"  完成歌曲: {played} 首")
        logger.info(f"  失败歌曲: {self._batch_stats['songs_failed']} 首")
        logger.info(f"  总运行时间: {elapsed:.0f}s ({elapsed/60:.1f}min)")
        if played > 0:
            avg_time = self._batch_stats["total_game_time"] / played
            logger.info(f"  平均每首: {avg_time:.1f}s")
            logger.info(f"  总点击: {self._batch_stats['total_taps']} 次")
            logger.info(f"  总 Flick: {self._batch_stats['total_flicks']} 次")
            logger.info(f"  总长按: {self._batch_stats['total_holds']} 次")
            logger.info(f"  处理帧数: {self._batch_stats['total_frames']}")
            logger.info(f"  平均 FPS: "
                        f"{self._batch_stats['total_frames']/self._batch_stats['total_game_time']:.1f}"
                        if self._batch_stats['total_game_time'] > 0 else "")
        logger.info("─" * 40)

    def _append_song_history(self, song: dict):
        """将一首歌的记录追加到历史文件。"""
        hist_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".song_history.json"
        )
        try:
            history = []
            if os.path.exists(hist_file):
                with open(hist_file, "r") as f:
                    history = json.load(f)
            history.append(song)
            # 只保留最近 200 条
            if len(history) > 200:
                history = history[-200:]
            with open(hist_file, "w") as f:
                json.dump(history, f, indent=2)
        except Exception:
            pass

    def _write_stats(self):
        """写入连续执行状态供 Web 仪表盘读取。"""
        stats_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".batch_stats.json"
        )
        now = time.time()
        elapsed = now - self._batch_stats.get("start_time", now)
        played = self._batch_stats.get("songs_played", 0)

        # 实时 FPS 计算: 当前歌曲的实际帧率
        fps = self.player._stats.get("fps", 0)
        if fps <= 0 and self.player._stats.get("frames", 0) > 0:
            elapsed_now = now - self.player._stats.get("start_time", now)
            fps = self.player._stats["frames"] / elapsed_now if elapsed_now > 0 else 0

        stats = {
            "running": self._running,
            "songs_played": played,
            "songs_failed": self._batch_stats.get("songs_failed", 0),
            "target": self.target_count,
            "elapsed_seconds": round(elapsed),
            "avg_song_time": round(self._batch_stats["total_game_time"] / played, 1)
                if played > 0 else 0,
            "fps": round(fps, 1),
            "latency_comp_ms": self.player.latency_comp,
            "total_taps": self._batch_stats.get("total_taps", 0),
            "total_flicks": self._batch_stats.get("total_flicks", 0),
            "total_holds": self._batch_stats.get("total_holds", 0),
            "total_frames": self._batch_stats.get("total_frames", 0),
            "log": self._get_recent_log(),
            "version": "4.3.0",
        }
        try:
            with open(stats_file, "w") as f:
                json.dump(stats, f)
        except OSError:
            pass

    def _get_recent_log(self) -> str:
        """获取最近的日志文本 (最后 5 行)。"""
        try:
            for handler in logging.getLogger().handlers:
                if hasattr(handler, 'stream') and hasattr(handler.stream, 'getvalue'):
                    lines = handler.stream.getvalue().strip().split("\n")
                    return "\n".join(lines[-10:])
        except Exception:
            pass
        return ""

    def _cleanup(self):
        """清理资源。"""
        self._running = False
        self.player._running = False
        self.player._release_all()
        self.player.analyzer.close()
        self.player.adb.stop_async_capture()
        self.player.adb.close_scrcpy()

