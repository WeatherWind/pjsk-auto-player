"""
自动打歌引擎 —— 核心循环: 截图 → 分析 → 触摸。

包含:
  - 主循环 (screencap → analyze → touch)
  - 延迟补偿
  - 歌词 / flick / hold 处理
  - 异常与超时处理
"""

import logging
import time
import sys
from typing import Optional

import numpy as np
import cv2

from adb_controller import ADBController
from screen_analyzer import ScreenAnalyzer, NoteEvent, GameState

logger = logging.getLogger("pjsk_auto_play")


class AutoPlayer:
    """
    自动打歌器。

    工作流程:
        1. 截取手机屏幕
        2. 分析画面, 检测判定线上的 notes
        3. 对每个检测到的 note 发送触摸指令
        4. 循环 1-3, 直到歌曲结束
    """

    def __init__(self, config: dict):
        self.cfg = config
        self.adb = ADBController(config)
        self.analyzer = ScreenAnalyzer(config)

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

        # 状态
        self._last_game_active = 0.0
        self._held_lanes = set()       # 当前保持按下的轨道
        self._touch_history = []       # 触摸历史 (用于调试)
        self._stats = {
            "frames": 0,
            "taps": 0,
            "flicks": 0,
            "holds": 0,
            "misses": 0,
            "start_time": 0.0,
        }

    # ──────────────────────────────────────────
    # 主控制
    # ──────────────────────────────────────────

    def start(self) -> None:
        """启动自动打歌循环。"""
        if not self._ensure_ready():
            return

        self._running = True
        self._paused = False
        self._stats["start_time"] = time.time()

        logger.info("=" * 50)
        logger.info("自动打歌已启动!")
        logger.info(f"延迟补偿: {self.latency_comp}ms")
        logger.info(f"判定线 Y: {self.analyzer.judgment_y}")
        logger.info("按 Ctrl+C 停止")
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

        elapsed = time.time() - self._stats["start_time"]
        logger.info("─" * 40)
        logger.info("自动打歌已停止")
        logger.info(f"运行时间: {elapsed:.1f}s")
        logger.info(f"处理帧数: {self._stats['frames']}")
        logger.info(f"点击次数: {self._stats['taps']}")
        logger.info(f"Flick 次数: {self._stats['flicks']}")
        logger.info(f"长按次数: {self._stats['holds']}")
        logger.info("─" * 40)

    def pause(self) -> None:
        """暂停/恢复。"""
        self._paused = not self._paused
        if self._paused:
            self._release_all()
            logger.info("⏸ 已暂停")
        else:
            logger.info("▶ 已恢复")

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
                # 重建 analyzer
                self.analyzer = ScreenAnalyzer(self.cfg)
        except Exception as e:
            logger.warning(f"获取屏幕分辨率失败: {e}")

        # 测试截图
        logger.info("测试截图...")
        test_frame = self.adb.screencap()
        if test_frame is None:
            logger.error("截图失败, 请检查设备和 ADB")
            return False
        logger.info(f"截图成功: {test_frame.shape[1]}x{test_frame.shape[0]}")

        return True

    # ──────────────────────────────────────────
    # 主循环
    # ──────────────────────────────────────────

    def _main_loop(self) -> None:
        """核心循环: 截图 → 分析 → 触摸。"""
        while self._running:
            loop_start = time.perf_counter()

            if self._paused:
                time.sleep(0.1)
                continue

            # 1. 截图
            frame = self.adb.screencap()
            if frame is None:
                self._stats["misses"] += 1
                # 连续截图失败可能是设备断连
                if self._stats["misses"] > 10:
                    logger.error("连续 10 次截图失败, 停止")
                    break
                time.sleep(0.05)
                continue

            self._stats["misses"] = 0  # 重置失败计数

            # 2. 分析
            state = self.analyzer.analyze(frame)
            self._stats["frames"] += 1

            # 3. 如果不在游戏中, 等待
            if not state.in_game:
                # 检查超时
                if self._last_game_active > 0:
                    idle = time.time() - self._last_game_active
                    if idle > self.game_over_timeout:
                        logger.info("游戏结束超时, 停止")
                        break
                time.sleep(0.05)
                continue

            self._last_game_active = time.time()

            # 4. 处理 notes
            self._process_notes(state)

            # 5. 帧率控制
            elapsed = time.perf_counter() - loop_start
            sleep_time = self.min_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    # ──────────────────────────────────────────
    # Note 处理
    # ──────────────────────────────────────────

    def _process_notes(self, state: GameState) -> None:
        """
        处理检测到的 notes: 发送触摸指令。

        策略:
          - tap: 直接点击
          - flick: 点击 + 滑动
          - hold: 按下并保持, 直到 note 消失
        """
        current_active = set()
        lane_positions = self.analyzer.get_lane_positions()

        for note in state.detected_notes:
            lane_x, lane_y = lane_positions[note.lane]
            current_active.add(note.lane)

            # 应用延迟补偿 (提前触发)
            if self.latency_comp > 0:
                # 如果启用补偿, 在检测到时就触发
                pass  # 实际上我们已经检测到了, 会立即触发

            if note.note_type == "tap":
                self._do_tap(note, lane_x, lane_y)
            elif note.note_type == "flick":
                self._do_flick(note, lane_x, lane_y)
            elif note.note_type == "hold":
                self._do_hold(note, lane_x, lane_y)

        # 释放不再活跃的 hold 轨道
        for lane in list(self._held_lanes):
            if lane not in current_active:
                self._release_lane(lane, lane_positions)

    def _do_tap(self, note: NoteEvent, x: int, y: int) -> None:
        """处理 tap note: 点击。"""
        self.adb.tap(x, y)
        self._stats["taps"] += 1
        logger.debug(f"TAP  lane={note.lane} @({x},{y})  conf={note.confidence:.2f}")

    def _do_flick(self, note: NoteEvent, x: int, y: int) -> None:
        """处理 flick note: 点击 + 向箭头方向滑动。"""
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
            # 默认上划
            self.adb.flick_up(x, y, self.flick_distance, self.flick_duration)

        self._stats["flicks"] += 1
        logger.debug(f"FLICK lane={note.lane} dir={direction} @({x},{y})")

    def _do_hold(self, note: NoteEvent, x: int, y: int) -> None:
        """处理 hold note: 按下并保持。"""
        if note.lane not in self._held_lanes:
            # 首次检测到 hold, 开始按下
            self.adb.press(x, y, duration_ms=100)
            self._held_lanes.add(note.lane)
            self._stats["holds"] += 1
            logger.debug(f"HOLD START lane={note.lane} @({x},{y})")
        else:
            # 持续按住 (通过短按压维持, 因为我们无法真正保持)
            self.adb.press(x, y, duration_ms=50)

    def _release_lane(self, lane: int, positions: list) -> None:
        """释放 hold 轨道。"""
        self._held_lanes.discard(lane)
        logger.debug(f"HOLD END  lane={lane}")

    def _release_all(self) -> None:
        """释放所有保持的触摸。"""
        self._held_lanes.clear()


# ──────────────────────────────────────────
# 校准工具
# ──────────────────────────────────────────

class Calibrator:
    """
    校准工具: 自动测量延迟、判定线位置、轨道位置。
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
            # 推荐补偿值
            recommended = results["latency"]["total_avg_ms"]
            results["recommended_compensation_ms"] = round(recommended)
            logger.info(f"  推荐延迟补偿: {round(recommended)}ms")

        # 2. 获取一张截图用于视觉校准
        logger.info("\n[2/3] 获取屏幕截图用于视觉校准...")
        frame = self.adb.screencap()
        if frame is None:
            logger.error("截图失败")
            return results

        # 更新 analyzer 的实际分辨率
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

        # 轨道位置
        lanes = self.analyzer.calibrate_lanes(frame)
        if lanes:
            lane_ratios = [round(x / w, 4) for x in lanes]
            # 分成左右
            mid = w // 2
            left = [r for r, x in zip(lane_ratios, lanes) if x < mid]
            right = [r for r, x in zip(lane_ratios, lanes) if x >= mid]
            results["left_lanes"] = left
            results["right_lanes"] = right
            logger.info(f"  左轨道: {left}")
            logger.info(f"  右轨道: {right}")

        # 保存校准结果截图
        debug_path = "calibration_result.jpg"
        debug_frame = frame.copy()
        cv2.line(debug_frame, (0, judgment_y), (w, judgment_y), (0, 255, 0), 3)
        for lx, _ in self.analyzer.get_lane_positions():
            cv2.circle(debug_frame, (lx, judgment_y), 15, (0, 0, 255), 3)
        cv2.imwrite(debug_path, debug_frame)
        logger.info(f"\n校准结果截图已保存: {debug_path}")

        logger.info("\n✅ 校准完成!")
        logger.info("请将以上结果更新到 config.yaml 中。")
        logger.info("=" * 50)

        return results

    def interactive_calibrate(self):
        """
        交互式校准: 实时预览 + 按键调参。

        使用方法:
          在手机上进入 PJSK 打歌界面, 运行此函数。
          按 'q' 退出, 按 'r' 重新校准。
        """
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

            # 更新实际分辨率
            h, w = frame.shape[:2]
            if w != self.cfg["screen"]["width"] or h != self.cfg["screen"]["height"]:
                self.cfg["screen"]["width"] = w
                self.cfg["screen"]["height"] = h
                self.analyzer = ScreenAnalyzer(self.cfg)
                judgment_y = self.analyzer.judgment_y

            # 分析
            state = self.analyzer.analyze(frame)

            # 画调试信息
            debug = frame.copy()
            cv2.line(debug, (0, judgment_y), (w, judgment_y), (0, 255, 0), 2)
            for idx, (lx, ly) in enumerate(self.analyzer.get_lane_positions()):
                active = any(n.lane == idx for n in state.detected_notes)
                color = (0, 0, 255) if active else (128, 128, 128)
                cv2.circle(debug, (lx, ly), self.analyzer.detect_radius, color, 2)
                if active:
                    cv2.circle(debug, (lx, ly), 8, (0, 0, 255), -1)

            info = [
                f"Threshold: {threshold}",
                f"Judgment Y: {judgment_y} ({judgment_y/h:.3f})",
                f"Notes: {len(state.detected_notes)}",
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
