"""
歌单播放器 (Combo) —— 自动切换多首歌曲, 支持选歌导航。

工作流程:
  1. 加载歌单 JSON
  2. 对每首歌:
     a. (可选) 导航到歌曲选择界面
     b. 选择歌曲和难度
     c. 等待执行开始
     d. 执行
     e. 处理结算
  3. 切到下一首, 重复

注意: 选歌导航需要模板图片或坐标配置,
      首次使用建议用 `loop-single` (单曲循环) 模式。
"""

import json
import logging
import os
import time
from typing import Optional

from auto_play import AutoPlayer, NoteTracker, Calibrator

logger = logging.getLogger("pjsk_combo")


class Combo:
    """歌单定义。"""

    def __init__(self, data: dict):
        self.name = data.get("name", "未命名歌单")
        self.description = data.get("description", "")
        self.difficulty = data.get("difficulty", "any")
        self.songs = data.get("songs", [])
        self.repeat = data.get("repeat", False)

    def __len__(self):
        return len(self.songs)

    def __repr__(self):
        return f"Compo({self.name}, {len(self.songs)} songs)"


class ComboPlayer:
    """
    歌单播放器: 按顺序播放歌单中的歌曲。

    模式:
      - single (默认): 只打当前歌曲 (连续执行用)
      - auto: 自动选歌 + 切换 (需要模板/坐标配置)
    """

    def __init__(self, config: dict, combo_name: str = "", song_count: int = 0):
        self.cfg = config
        self.combo: Optional[Combo] = None
        self.player = AutoPlayer(config)

        # 加载歌单
        if combo_name:
            self._load_combo(combo_name)
        else:
            # 默认用单曲循环
            self._load_combo("loop-single")

        # 连续执行参数
        bp = config.get("batch_play", {})
        self.target_count = song_count or bp.get("default_count", 0)
        self.result_wait = bp.get("result_wait_seconds", 4.0)
        self.result_tap_interval = bp.get("result_tap_interval", 2.5)
        self.max_result_taps = bp.get("max_result_taps", 15)
        self.next_song_timeout = bp.get("next_song_timeout", 30.0)
        self.song_timeout = bp.get("song_timeout", 360)
        self.max_failures = bp.get("max_failures_per_song", 20)

        # 导航配置 (坐标偏移量, 需要针对手机分辨率调整)
        s = config["screen"]
        self.screen_w = s.get("width", 1080)
        self.screen_h = s.get("height", 2400)

        self._running = False
        self._current_song_idx = 0
        self._batch_stats = {
            "songs_played": 0, "songs_failed": 0,
            "total_taps": 0, "total_flicks": 0, "total_holds": 0,
            "total_frames": 0, "start_time": 0.0, "total_game_time": 0.0,
        }

    def _load_combo(self, name: str):
        """加载歌单。"""
        # 尝试直接加载文件
        if os.path.isfile(name):
            path = name
        else:
            # 在 combos/ 目录查找
            combo_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "combos"
            )
            # 尝试 name.json, name.yaml
            for ext in [".json", ".yaml", ".yml"]:
                p = os.path.join(combo_dir, f"{name}{ext}")
                if os.path.exists(p):
                    path = p
                    break
            else:
                # 默认: 单曲循环
                path = os.path.join(combo_dir, "default.json")
                name = "loop-single"

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"歌单加载失败: {e}, 使用单曲循环")
            self.combo = Combo({
                "name": "单曲循环",
                "repeat": True,
                "songs": [{"id": "current", "name": "当前歌曲"}]
            })
            return

        if name in data:
            self.combo = Combo(data[name])
        else:
            # 用第一个歌单
            first_key = next((k for k in data if not k.startswith("_")
                            and k != "doc" and k != "version"), None)
            if first_key:
                self.combo = Combo(data[first_key])
            else:
                logger.warning("歌单文件为空, 使用单曲循环")
                self.combo = Combo({"name": "单曲循环", "repeat": True,
                                    "songs": [{"id": "current"}]})

        logger.info(f"歌单已加载: {self.combo.name} ({len(self.combo)} 首)")

    def list_combos(self) -> list[dict]:
        """列出所有可用歌单。"""
        combo_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "combos"
        )
        results = []
        if not os.path.exists(combo_dir):
            return results

        for fname in sorted(os.listdir(combo_dir)):
            if not fname.endswith((".json", ".yaml", ".yml")):
                continue
            path = os.path.join(combo_dir, fname)
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                for key, val in data.items():
                    if key.startswith("_") or key in ("doc", "version"):
                        continue
                    results.append({
                        "key": key,
                        "name": val.get("name", key),
                        "description": val.get("description", ""),
                        "songs": len(val.get("songs", [])),
                        "file": fname,
                    })
            except (json.JSONDecodeError, IOError):
                continue
        return results

    def start(self):
        """启动歌单播放。"""
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
        logger.info(f"🎵 歌单: {self.combo.name}")
        logger.info(f"曲目: {len(self.combo)} 首  |  目标: {count_label}")
        logger.info(f"请在手机上进入执行画面 (手动选好第一首歌)")
        logger.info("按 Ctrl+C 停止")
        logger.info("=" * 50)

        try:
            if self.combo.repeat:
                self._run_repeat_loop()
            else:
                self._run_combo_loop()
        except KeyboardInterrupt:
            logger.info("\n收到中断信号...")
        finally:
            self._print_stats()
            self._cleanup()

    def _run_repeat_loop(self):
        """单曲循环模式: 重复当前歌曲。"""
        while self._running:
            if self.target_count > 0 and \
               self._batch_stats["songs_played"] >= self.target_count:
                break

            song_num = self._batch_stats["songs_played"] + 1
            logger.info(f"\n{'─' * 40}")
            logger.info(f"🎵 第 {song_num} 首 — 等待执行开始...")

            if not self._wait_for_game():
                break

            logger.info(f"▶ 开始!")
            song_start = time.time()
            stats = self._play_one()
            game_time = time.time() - song_start

            if stats:
                self._batch_stats["songs_played"] += 1
                for k in ("taps", "flicks", "holds", "frames"):
                    self._batch_stats[f"total_{k}"] += stats.get(k, 0)
                self._batch_stats["total_game_time"] += game_time
                self._write_stats()
                logger.info(f"✅ 第 {song_num} 首 完成 ({game_time:.1f}s)")
            else:
                self._batch_stats["songs_failed"] += 1
                logger.warning(f"⚠️  第 {song_num} 首 异常")

            if self._running:
                logger.info("📊 处理结算...")
                self._handle_result()

            time.sleep(0.5)

    def _run_combo_loop(self):
        """多曲目模式: 切歌后继续。"""
        total_songs = len(self.combo)
        self._current_song_idx = 0

        while self._running:
            if self.target_count > 0 and \
               self._batch_stats["songs_played"] >= self.target_count:
                break

            song = self.combo.songs[self._current_song_idx]
            song_name = song.get("name", f"曲目{self._current_song_idx+1}")
            song_num = self._batch_stats["songs_played"] + 1

            logger.info(f"\n{'─' * 40}")
            logger.info(f"🎵 [{self._current_song_idx+1}/{total_songs}] {song_name}")

            # 选歌 (如果是第一首或需要切歌)
            if self._batch_stats["songs_played"] > 0 or song_num == 1:
                if not self._select_song(song):
                    logger.warning(f"选歌失败: {song_name}, 跳过")
                    self._current_song_idx = (self._current_song_idx + 1) % total_songs
                    continue

            if not self._wait_for_game():
                logger.info("等待超时, 停止")
                break

            stats = self._play_one()
            if stats:
                self._batch_stats["songs_played"] += 1
                for k in ("taps", "flicks", "holds", "frames"):
                    self._batch_stats[f"total_{k}"] += stats.get(k, 0)
                self._batch_stats["total_game_time"] += time.time()
                self._write_stats()
                logger.info(f"✅ {song_name} 完成")
            else:
                self._batch_stats["songs_failed"] += 1

            if self._running:
                self._handle_result()

            # 下一首
            self._current_song_idx = (self._current_song_idx + 1) % total_songs
            time.sleep(0.5)

    def _select_song(self, song: dict) -> bool:
        """
        选歌导航: 点击指定歌曲。

        使用配置坐标 + 模板匹配。

        TODO: 更智能的选歌 (OCR 搜索 + 滚动列表)。
        """
        difficulty = song.get("difficulty", self.combo.difficulty)
        if difficulty == "any":
            return True

        # 使用配置的选歌坐标
        nav = self.cfg.get("navigation", {})
        cx, cy = self.screen_w // 2, self.screen_h // 2

        if nav.get("enabled", False):
            # 有坐标配置: 点击歌曲位置
            song_x = nav.get("song_select_x", cx)
            song_y = nav.get("song_select_y", int(self.screen_h * 0.5))
            self.player.adb.tap(song_x, song_y)
            time.sleep(1.0)

            # 点击难度
            diff_map = {"easy": 0, "normal": 1, "hard": 2, "expert": 3, "master": 4}
            diff_idx = diff_map.get(difficulty, 3)
            diff_y = nav.get("difficulty_y_start", int(self.screen_h * 0.45))
            diff_spacing = nav.get("difficulty_spacing", 60)
            self.player.adb.tap(cx, diff_y + diff_idx * diff_spacing)
            time.sleep(0.5)

            # 点击开始
            start_x = nav.get("start_x", cx)
            start_y = nav.get("start_y", int(self.screen_h * 0.78))
            self.player.adb.tap(start_x, start_y)
            return True

        # 无坐标配置: 提示用户手动选歌
        logger.info(f"📢 请手动选择: {song.get('name', '下一首')}")
        logger.info(f"   难度: {difficulty}")
        input("   选好后按 Enter 继续...")
        return True

    def _wait_for_game(self) -> bool:
        """等待进入执行画面。"""
        start = time.time()
        while time.time() - start < self.next_song_timeout:
            if not self._running:
                return False
            frame = self.player.adb.screencap()
            if frame is None:
                time.sleep(0.3)
                continue
            from scene_classifier import SceneClassifier
            sc = SceneClassifier(self.cfg)
            if sc.is_game(frame):
                time.sleep(0.1)
                frame2 = self.player.adb.screencap()
                if frame2 and sc.is_game(frame2):
                    return True
            time.sleep(0.2)
        return False

    def _play_one(self) -> Optional[dict]:
        """打一首歌。"""
        self.player.tracker.reset()
        self.player._running = True
        self.player._paused = False
        self.player._stats["start_time"] = time.time()
        self.player._last_game_active = time.time()

        song_start = time.time()
        failures = 0

        while self.player._running:
            if time.time() - song_start > self.song_timeout:
                logger.warning(f"单曲超时 ({self.song_timeout}s)")
                break

            frame = self.player.adb.screencap()
            if frame is None:
                failures += 1
                if failures > self.max_failures:
                    break
                time.sleep(0.05)
                continue
            failures = 0

            state = self.player.analyzer.analyze(frame)
            self.player._stats["frames"] += 1

            if state.in_result:
                self.player._running = False
                break
            if not state.in_game:
                if self.player._last_game_active > 0:
                    idle = time.time() - self.player._last_game_active
                    if idle > self.player.game_over_timeout:
                        self.player._running = False
                        break
                time.sleep(0.05)
                continue

            self.player._last_game_active = time.time()

            if self.player.use_prediction:
                triggers = self.player.tracker.update(
                    state.predicted_notes, state.detected_notes, time.time())
                for t in triggers:
                    self.player.adb.tap(t["x"], t["y"])
                    self.player._stats["taps"] += 1

            self.player._process_notes(state)

        self.player._release_all()
        return {
            "taps": self.player._stats["taps"],
            "flicks": self.player._stats["flicks"],
            "holds": self.player._stats["holds"],
            "frames": self.player._stats["frames"],
        }

    def _handle_result(self):
        """处理结算画面。"""
        time.sleep(self.result_wait)
        cx, cy = self.screen_w // 2, self.screen_h // 2

        from scene_classifier import SceneClassifier
        sc = SceneClassifier(self.cfg)

        for i in range(self.max_result_taps):
            if not self._running:
                return
            self.player.adb.tap(cx, cy)
            time.sleep(self.result_tap_interval)
            frame = self.player.adb.screencap()
            if frame is None:
                continue
            st = sc.classify(frame)
            if st.name in ("GAME", "MENU"):
                return

    def _write_stats(self):
        """写入仪表盘状态。"""
        stats_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".batch_stats.json"
        )
        now = time.time()
        elapsed = now - self._batch_stats.get("start_time", now)
        played = self._batch_stats.get("songs_played", 0)
        stats = {
            "running": self._running,
            "songs_played": played,
            "songs_failed": self._batch_stats.get("songs_failed", 0),
            "target": self.target_count,
            "elapsed_seconds": round(elapsed),
            "avg_song_time": round(self._batch_stats["total_game_time"] / played, 1)
                if played > 0 else 0,
            "total_taps": self._batch_stats.get("total_taps", 0),
            "total_flicks": self._batch_stats.get("total_flicks", 0),
            "total_holds": self._batch_stats.get("total_holds", 0),
            "total_frames": self._batch_stats.get("total_frames", 0),
            "version": "3.6.0",
        }
        try:
            with open(stats_file, "w") as f:
                json.dump(stats, f)
        except OSError:
            pass

    def _print_stats(self):
        """打印统计。"""
        elapsed = time.time() - self._batch_stats["start_time"]
        played = self._batch_stats["songs_played"]
        logger.info("=" * 50)
        logger.info(f"🎵 歌单: {self.combo.name}")
        logger.info(f"  完成: {played} 首  |  失败: {self._batch_stats['songs_failed']}")
        logger.info(f"  时长: {elapsed:.0f}s ({elapsed/60:.1f}min)")
        if played > 0:
            logger.info(f"  点击: {self._batch_stats['total_taps']}")
        logger.info("=" * 50)

    def _cleanup(self):
        self._running = False
        self.player._running = False
        self.player._release_all()
        self.player.analyzer.close()
        self.player.adb.close_scrcpy()
