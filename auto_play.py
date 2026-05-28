"""
自动打歌引擎 —— 核心循环: 截图 → 分析 → 触摸 (含预测引擎)。

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


class NoteTracker:
    """
    Note 轨迹追踪器 —— 预测引擎的核心。

    工作方式:
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

        # 测量到的 ADB 延迟 (ms)
        self._measured_latency_ms = 0

        # 追踪状态: lane -> { positions: [(y, t), ...], velocity: float, fired: bool }
        self._tracks: dict[int, dict] = {}

    def set_latency(self, latency_ms: float):
        """设置测量到的 ADB 延迟 (ms)。"""
        self._measured_latency_ms = latency_ms
        logger.info(f"预测引擎: ADB 延迟 = {latency_ms:.0f}ms")

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
        advance_ms = self._measured_latency_ms
        if self.manual_advance > 0:
            advance_ms = self.manual_advance

        for lane, track in self._tracks.items():
            if track["fired"]:
                continue  # 已经触发过了

            if not track["positions"]:
                continue

            # 需要足够多的追踪帧才能建立稳定的速度
            if len(track["positions"]) < self.min_track_frames:
                continue

            # 如果速度太小 (接近 0), 说明 note 可能停在屏幕上了
            if abs(track["velocity"]) < 50:
                continue

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
            velocity = abs(track["velocity"])
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
        """将轨道编号映射到 X 坐标 (像素)。"""
        s = self.cfg.get("screen", {})
        w = s.get("width", 1080)
        l = [int(x * w) for x in s.get("left_lanes", [0.15, 0.25, 0.35])]
        r = [int(x * w) for x in s.get("right_lanes", [0.65, 0.75, 0.85])]
        all_l = l + r
        if 0 <= lane < len(all_l):
            return all_l[lane]
        return w // 2

    def reset(self):
        """重置所有轨迹 (新歌开始时调用)。"""
        self._tracks.clear()

    def get_stats(self) -> dict:
        """获取追踪统计。"""
        return {
            "tracked_notes": len(self._tracks),
            "measured_latency_ms": self._measured_latency_ms,
        }


class AutoPlayer:
    """
    自动打歌器。

    工作流程:
        1. 截取手机屏幕
        2. 分析画面, 检测判定线上的 notes + 判定线上方的 note (预测)
        3. 预测引擎: 追踪 note 滚动速度, 提前触发
        4. 对判定线上的 note 发送触摸指令 (备用)
        5. 循环 1-5, 直到歌曲结束
    """

    def __init__(self, config: dict):
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

        # 触摸参数
        self.tap_duration = config.get("touch", {}).get("tap_duration_ms", 30)
        self.flick_distance = config.get("touch", {}).get("flick_distance", 150)
        self.flick_duration = config.get("touch", {}).get("flick_duration_ms", 50)

        # 显示参数
        self.show_stats = config.get("display", {}).get("show_stats", True)
        self.stats_interval = config.get("display", {}).get("stats_interval_frames", 15)

        # 预测参数
        self.use_prediction = config.get("prediction", {}).get("enabled", True)

        # 状态
        self._last_game_active = 0.0
        self._held_lanes = set()
        self._touch_history = []
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
            "frame_count_stats": 0,
        }

    # ──────────────────────────────────────────
    # 主控制
    # ──────────────────────────────────────────

    def start(self) -> None:
        """启动自动打歌循环。"""
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

        self._running = True
        self._paused = False
        self._stats["start_time"] = time.time()
        self._stats["last_stats_time"] = time.time()

        prediction_status = "已启用" if self.use_prediction else "已禁用"
        logger.info("=" * 50)
        logger.info("自动打歌已启动!")
        logger.info(f"延迟补偿: {self.latency_comp}ms  预测引擎: {prediction_status}")
        logger.info(f"判定线 Y: {self.analyzer.judgment_y}")
        logger.info("热键: P=暂停  Q=退出  +/-=延迟补偿  </>=阈值")
        logger.info("=" * 50)

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("收到中断信号, 停止...")
        finally:
            self.stop()

    def stop(self) -> None:
        """停止自动打歌, 释放所有触摸。"""
        self._running = False
        self._paused = False
        self._release_all()
        self.analyzer.close()
        self.adb.close_scrcpy()
        self.adb._cleanup_minitouch()

        elapsed = time.time() - self._stats["start_time"]
        fps_avg = self._stats["frames"] / elapsed if elapsed > 0 else 0

        logger.info("─" * 40)
        logger.info("自动打歌已停止")
        logger.info(f"运行时间: {elapsed:.1f}s")
        logger.info(f"处理帧数: {self._stats['frames']}  ({fps_avg:.1f} FPS)")
        logger.info(f"点击: {self._stats['taps']}  "
                     f"Flick: {self._stats['flicks']}  "
                     f"长按: {self._stats['holds']}")
        if self.use_prediction:
            logger.info(f"预测触发: {self._stats['predicted_triggers']}")
        logger.info("─" * 40)

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

        return True

    # ──────────────────────────────────────────
    # 主循环
    # ──────────────────────────────────────────

    def _main_loop(self) -> None:
        """核心循环: 截图 → 分析 → 预测 → 触摸。"""
        import sys  # for non-blocking key input

        # 尝试启用非阻塞输入 (仅类 Unix 系统)
        kb_enabled = False
        try:
            import select
            kb_enabled = True
        except ImportError:
            pass

        while self._running:
            loop_start = time.perf_counter()

            if self._paused:
                # 即使在暂停状态也检查热键
                if kb_enabled and self._check_keyboard():
                    pass
                time.sleep(0.1)
                continue

            # 1. 截图
            frame = self.adb.screencap()
            if frame is None:
                self._stats["misses"] += 1
                if self._stats["misses"] > 10:
                    logger.error("连续 10 次截图失败, 停止")
                    break
                time.sleep(0.05)
                continue

            self._stats["misses"] = 0

            # 2. 分析 (判定线 + 预测区域)
            state = self.analyzer.analyze(frame)
            self._stats["frames"] += 1

            # 3. 如果不在游戏中, 等待
            if not state.in_game:
                if self._last_game_active > 0:
                    idle = time.time() - self._last_game_active
                    if idle > self.game_over_timeout:
                        logger.info("游戏结束超时, 停止")
                        break
                # 重置预测追踪
                self.tracker.reset()
                time.sleep(0.05)
                continue

            self._last_game_active = time.time()
            now = time.time()

            # 4. 预测引擎: 触发提前发现的 note
            if self.use_prediction:
                triggers = self.tracker.update(
                    state.predicted_notes,
                    state.detected_notes,
                    now,
                )
                for trigger in triggers:
                    lane_x = trigger["x"]
                    lane_y = trigger["y"]
                    note_type = trigger["note_type"]
                    if note_type == "tap":
                        self.adb.tap(lane_x, lane_y)
                        self._stats["predicted_triggers"] += 1
                        self._stats["taps"] += 1
                        logger.debug(f"[PRED] TAP lane={trigger['lane']} @({lane_x},{lane_y})")

            # 5. 处理判定线上的 notes (备用)
            self._process_notes(state)

            # 6. 键盘热键检查
            if kb_enabled:
                self._check_keyboard()

            # 7. 显示实时统计
            if self.show_stats and self._stats["frames"] % self.stats_interval == 0:
                self._print_stats()

            # 8. 帧率控制
            elapsed = time.perf_counter() - loop_start
            sleep_time = self.min_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _check_keyboard(self) -> bool:
        """
        检查键盘热键输入 (非阻塞)。

        热键:
          p/P - 暂停/继续
          q/Q - 退出
          +/- - 微调延迟补偿 (±5ms)
          </> - 微调亮度阈值 (±5)
        """
        try:
            import sys
            import select
            import termios
            import tty

            # 非阻塞读取 stdin
            fd = sys.stdin.fileno()
            if not select.select([sys.stdin], [], [], 0)[0]:
                return False

            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(sys.stdin.fileno())
                ch = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

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
            elif c == ">":
                self.analyzer.bright_thresh = min(255, self.analyzer.bright_thresh + 5)
                logger.info(f"亮度阈值: {self.analyzer.bright_thresh}")
                return True
            elif c == "<":
                self.analyzer.bright_thresh = max(0, self.analyzer.bright_thresh - 5)
                logger.info(f"亮度阈值: {self.analyzer.bright_thresh}")
                return True

        except (ImportError, AttributeError, Exception):
            # 非阻塞输入不可用 (Windows) - 静默忽略
            pass

        return False

    def _print_stats(self):
        """在终端打印实时统计信息。"""
        now = time.time()
        elapsed = now - self._stats["start_time"]
        dt = now - self._stats["last_stats_time"]

        if dt > 0:
            frames_in_interval = self.stats_interval
            fps = frames_in_interval / dt
            self._stats["fps"] = fps

        self._stats["last_stats_time"] = now

        tracker_stats = self.tracker.get_stats() if self.use_prediction else {}

        stats_line = (
            f"\033[36m[STATS]\033[0m "
            f"FPS: \033[33m{self._stats['fps']:.1f}\033[0m | "
            f"帧: {self._stats['frames']} | "
            f"点: {self._stats['taps']} "
            f"划: {self._stats['flicks']} "
            f"按: {self._stats['holds']}"
        )

        if self.use_prediction:
            stats_line += f" | 预触发: {self._stats['predicted_triggers']}"

        stats_line += (
            f" | 补偿: \033[32m{self.latency_comp}ms\033[0m | "
            f"检测: \033[35m{self.analyzer.bright_thresh}\033[0m"
        )

        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.write(stats_line)
        sys.stdout.flush()

    # ──────────────────────────────────────────
    # Note 处理
    # ──────────────────────────────────────────

    def _process_notes(self, state: GameState) -> None:
        """处理检测到的判定线 notes。"""
        current_active = set()
        lane_positions = self.analyzer.get_lane_positions()

        for note in state.detected_notes:
            lane_x, lane_y = lane_positions[note.lane]
            current_active.add(note.lane)

            if note.note_type == "tap":
                self._do_tap(note, lane_x, lane_y)
            elif note.note_type == "flick":
                self._do_flick(note, lane_x, lane_y)
            elif note.note_type == "hold":
                self._do_hold(note, lane_x, lane_y)

        for lane in list(self._held_lanes):
            if lane not in current_active:
                self._release_lane(lane, lane_positions)

    def _do_tap(self, note: NoteEvent, x: int, y: int) -> None:
        self.adb.tap(x, y)
        self._stats["taps"] += 1
        logger.debug(f"TAP  lane={note.lane} @({x},{y})  conf={note.confidence:.2f}")

    def _do_flick(self, note: NoteEvent, x: int, y: int) -> None:
        direction = note.flick_direction or "up"
        if direction == "up":
            self.adb.flick_up(x, y, self.flick_distance, self.flick_duration)
        elif direction == "down":
            self.adb.flick_down(x, y, self.flick_distance, self.flick_duration)
        elif direction == "left":
            self.adb.flick_left(x, y, self.flick_distance, self.flick_duration)
        elif direction == "right":
            self.adb.flick_right(x, y, self.flick_distance, self.flick_duration)
        else:
            self.adb.flick_up(x, y, self.flick_distance, self.flick_duration)

        self._stats["flicks"] += 1
        logger.debug(f"FLICK lane={note.lane} dir={direction} @({x},{y})")

    def _do_hold(self, note: NoteEvent, x: int, y: int) -> None:
        if note.lane not in self._held_lanes:
            self.adb.press(x, y, duration_ms=100)
            self._held_lanes.add(note.lane)
            self._stats["holds"] += 1
            logger.debug(f"HOLD START lane={note.lane} @({x},{y})")
        else:
            self.adb.press(x, y, duration_ms=50)

    def _release_lane(self, lane: int, positions: list) -> None:
        self._held_lanes.discard(lane)
        logger.debug(f"HOLD END  lane={lane}")

    def _release_all(self) -> None:
        self._held_lanes.clear()


# ──────────────────────────────────────────
# 校准工具
# ──────────────────────────────────────────

class Calibrator:
    """
    校准工具: 自动测量延迟、判定线位置、轨道位置。
    改进: 自动写入 config.yaml。
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.adb = ADBController(config)
        self.analyzer = ScreenAnalyzer(config)

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
        print("请在手机上打开 PJSK 打歌界面。")
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
# 冲榜模式 (Batch Play) —— 自动连续打歌
# ──────────────────────────────────────────

class BatchPlayer:
    """
    冲榜模式: 自动连续打歌, 处理结算画面、等待、重试。

    工作流程:
      1. 启动 AutoPlayer, 等待用户进入打歌
      2. 等待歌曲结束 (game_over_timeout)
      3. 检测结算画面, 逐次点击返回选歌
      4. 等待回到打歌画面
      5. 重复 2-4, 直到达到指定次数
    """

    def __init__(self, config: dict, song_count: int = 0):
        self.cfg = config
        self.player = AutoPlayer(config)

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
        """启动冲榜模式。"""
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

        count_label = f"{self.target_count} 首" if self.target_count > 0 else "无限"
        logger.info("=" * 50)
        logger.info("🔥 PJSK 冲榜模式 已启动!")
        logger.info(f"目标次数: {count_label}")
        logger.info(f"延迟补偿: {self.player.latency_comp}ms")
        logger.info("请在手机上进入打歌画面, 程序将自动循环")
        logger.info("按 Ctrl+C 停止")
        logger.info("=" * 50)

        try:
            if self._use_pipeline and self.pipeline:
                logger.info("使用 Pipeline 引擎执行冲榜...")
                self._run_with_pipeline()
            else:
                self._auto_play_loop()
        except KeyboardInterrupt:
            logger.info("\n收到中断信号...")
        finally:
            self._print_final_stats()
            self._cleanup()

    def _run_with_pipeline(self):
        """使用 Pipeline 引擎执行冲榜。"""
        if not self.pipeline:
            self._auto_play_loop()
            return

        song_count = 0
        target = self.target_count

        def on_task(task, result, state):
            nonlocal song_count
            if task.name == "PlaySong" and result.matched:
                # 执行打歌
                self._play_one_song()
                song_count += 1
                logger.info(f"✅ 第 {song_count} 首 完成  "
                           f"({song_count}/{target if target>0 else '∞'})")

                # 检查是否达到目标
                if target > 0 and song_count >= target:
                    logger.info(f"✅ 已完成 {target} 首, 冲榜结束!")
                    self.pipeline.stop()

        # 注册回调来拦截 PlaySong 任务
        self.pipeline.run("BatchStart", callback=on_task)

    def _auto_play_loop(self):
        """冲榜主循环: 打歌 → 结算 → 下一首。"""
        while self._running:
            # 检查是否达到目标次数
            if self.target_count > 0 and \
               self._batch_stats["songs_played"] >= self.target_count:
                logger.info(f"✅ 已完成 {self.target_count} 首, 冲榜结束!")
                break

            # ── 1. 等待进入打歌画面 ──
            song_num = self._batch_stats["songs_played"] + 1
            logger.info(f"\n{'─' * 40}")
            logger.info(f"🎵 第 {song_num} 首 — 等待打歌开始...")

            if not self._wait_for_game_start():
                logger.info("等待打歌开始超时, 停止")
                break

            # ── 2. 打歌 ──
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
                logger.info(f"✅ 第 {song_num} 首 完成! "
                           f"用时: {game_time:.1f}s  "
                           f"点: {song_stats.get('taps', 0)}  "
                           f"划: {song_stats.get('flicks', 0)}")
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
        等待进入打歌画面。

        Returns:
            True 如果检测到打歌开始, False 如果超时
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
                # 确认确实是打歌中: 连续检测到 2 次
                time.sleep(0.1)
                frame2 = self.player.adb.screencap()
                if frame2 and self.player.analyzer.classify_screen(frame2) == "game":
                    return True

            if not need_game and screen_type != "game":
                return True

            time.sleep(0.2)

        return False

    def _play_one_song(self) -> Optional[dict]:
        """
        打一首歌, 返回该次打歌的统计。

        内部使用 AutoPlayer 的循环逻辑, 但增加了:
          - 单曲超时保护
          - 结算画面检测后自动退出循环
        """
        # 重置追踪器
        self.player.tracker.reset()

        self.player._running = True
        self.player._paused = False
        self.player._stats["start_time"] = time.time()
        self.player._stats["last_stats_time"] = time.time()
        self.player._last_game_active = time.time()

        song_start = time.time()
        failures = 0

        while self.player._running:
            # 单曲超时
            if time.time() - song_start > self.song_timeout:
                logger.warning(f"⏰ 单曲超时 ({self.song_timeout}s), 跳过")
                break

            loop_start = time.perf_counter()

            if self.player._paused:
                time.sleep(0.1)
                continue

            # 截图
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
                logger.info("检测到结算画面, 结束打歌")
                self.player._running = False
                break

            if not state.in_game and not state.in_menu:
                # 既不是打歌也不是菜单 — 可能是加载或过渡
                if self.player._last_game_active > 0:
                    idle = time.time() - self.player._last_game_active
                    if idle > self.player.game_over_timeout:
                        logger.info("游戏结束超时, 结束打歌")
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

            # 打歌中
            self.player._last_game_active = time.time()
            now = time.time()

            # 预测引擎
            if self.player.use_prediction:
                triggers = self.player.tracker.update(
                    state.predicted_notes, state.detected_notes, now
                )
                for trigger in triggers:
                    self.player.adb.tap(trigger["x"], trigger["y"])
                    self.player._stats["predicted_triggers"] += 1
                    self.player._stats["taps"] += 1

            # 判定线 note 处理
            self.player._process_notes(state)

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
        return {
            "taps": self.player._stats["taps"],
            "flicks": self.player._stats["flicks"],
            "holds": self.player._stats["holds"],
            "frames": self.player._stats["frames"],
            "predicted": self.player._stats.get("predicted_triggers", 0),
        }

    def _handle_result_screen(self):
        """
        处理结算画面: 等待 → 逐次点击 → 返回选歌。

        PJSK 典型结算流程:
          1. 分数展示 (自动滚动)  ~3s
          2. 点击 → 详细结果
          3. 点击 → 可能显示称号/等级提升
          4. 点击 → 返回歌曲选择/房间
        """
        # 等待结算动画播放
        time.sleep(self.result_wait)

        # 找到屏幕中央
        w = self.cfg.get("screen", {}).get("width", 1080)
        h = self.cfg.get("screen", {}).get("height", 2400)
        cx, cy = w // 2, h // 2

        for i in range(self.max_result_taps):
            if not self._running:
                return

            # 点击屏幕中央
            self.player.adb.tap(cx, cy)
            time.sleep(self.result_tap_interval)

            # 检查画面状态
            frame = self.player.adb.screencap()
            if frame is None:
                continue

            st = self.player.analyzer.classify_screen(frame)

            if st == "game":
                logger.info("✅ 已返回打歌画面")
                return
            if st == "menu":
                logger.info("✅ 已返回选歌/菜单")
                return

        logger.warning(f"⚠️  结算画面点击 {self.max_result_taps} 次仍未回到选歌, "
                       "尝试继续...")

    def _print_final_stats(self):
        """打印冲榜最终统计。"""
        elapsed = time.time() - self._batch_stats["start_time"]
        played = self._batch_stats["songs_played"]

        logger.info("=" * 50)
        logger.info("🔥 冲榜统计")
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

    def _cleanup(self):
        """清理资源。"""
        self._running = False
        self.player._running = False
        self.player._release_all()
        self.player.analyzer.close()
        self.player.adb.close_scrcpy()

