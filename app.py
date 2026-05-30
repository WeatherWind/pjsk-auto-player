"""
PJSK Auto Player — 应用主类 (Application Manager)

协调所有模块: 配置 → 控制器 → 识别 → Pipeline → Web GUI
支持 CLI/Web/Daemon 三种运行模式。
"""

import logging
import os
import threading
import time
from typing import Optional

from config import get_config_loader
from exceptions import (
    PjskError,
    classify_error,
    get_recovery_strategy,
)

# 模块级导入 (v5.4: 从函数体内移出, 避免每帧重复 import)
from pipeline.process import ProcessTask
from pipeline.task_data import TaskDataLoader
from scene.classifier import SceneClassifier
from capture_optimizer import CaptureOptimizer

logger = logging.getLogger("pjsk.app")


class PjskApp:
    """应用主类 —— 协调所有模块。"""

    def __init__(self, profile: str = ""):
        self.profile = profile
        self._config_loader = get_config_loader()
        self.config = self._config_loader.load(profile)

        # 控制器
        self.controller = None

        # 运行状态
        self.running = False
        self.paused = False
        self.mode = "live"
        self.current_task = ""
        self.stats = {
            "clicks": 0,
            "fps": 0.0,
            "songs_played": 0,
            "start_time": 0,
            "errors": 0,
            "perfects": 0,
            "greats": 0,
            "misses": 0,
        }

        # 线程
        self._main_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # 后端
        self._backend_initialized = False

        # v5.2: 缓存场景分类器实例 (避免每帧重复创建)
        self._scene_classifier: Optional[SceneClassifier] = None

        # v5.4: 画面捕获优化器 — 场景感知 ROI 截取 + 帧差检测
        self._capture_optimizer: Optional[CaptureOptimizer] = None
        try:
            self._capture_optimizer = CaptureOptimizer(self.config)
        except Exception:
            pass

        # v5.4: 任务缓存 (避免每帧重新创建 ProcessTask)
        self._task_cache: dict[str, ProcessTask] = {}
        self._task_loader: Optional[TaskDataLoader] = None

    def initialize(self):
        """初始化所有后端。"""
        if self._backend_initialized:
            return
        logger.info("Initializing PJSK Auto Player...")
        self._init_controller()
        self._backend_initialized = True
        logger.info("Initialization complete")

    def _init_controller(self):
        """初始化设备控制器。"""
        from controller.combined import CombinedController  # 延迟导入避免循环依赖
        try:
            self.controller = CombinedController(self.config)
            self.controller.connect()
            logger.info("Controller connected")
        except Exception as e:
            logger.error("Controller init failed: %s", e)
            raise

    def run(self, mode: str = "live", infinite: bool = False):
        """启动执行主循环。"""
        self.mode = mode
        self.running = True
        self._stop_event.clear()
        self.stats["start_time"] = time.time()

        if self.config.get("web", {}).get("enabled", True):
            self._start_web_server()

        logger.info("Starting play loop (mode=%s, infinite=%s)", mode, infinite)
        self._main_loop(infinite)

    def run_daemon(self):
        """后台守护进程模式。"""
        import json
        import os
        import socket
        import threading

        self.initialize()
        self.running = True
        self._stop_event.clear()

        # 启动 Web 服务器
        if self.config.get("web", {}).get("enabled", True):
            self._start_web_server()

        # Unix domain socket 守护进程
        sock_path = os.path.expanduser("~/.pjskd.sock")
        try:
            os.unlink(sock_path)
        except OSError:
            pass

        def handle_client(conn):
            try:
                data = conn.recv(4096)
                req = json.loads(data.decode())
                cmd = req.get("cmd")
                if cmd == "status":
                    resp = {
                        "running": self.running,
                        "paused": self.paused,
                        "mode": self.mode,
                        "current_task": self.current_task,
                        "fps": self.stats["fps"],
                        "clicks": self.stats["clicks"],
                        "songs_played": self.stats["songs_played"],
                        "uptime": self._format_uptime(),
                    }
                    conn.sendall(json.dumps(resp).encode())
                elif cmd == "stop":
                    self.stop()
                    conn.sendall(b'{"ok": true}')
                elif cmd == "pause":
                    self.paused = True
                    conn.sendall(b'{"ok": true}')
                elif cmd == "resume":
                    self.paused = False
                    conn.sendall(b'{"ok": true}')
                else:
                    conn.sendall(b'{"error": "unknown cmd"}')
            except Exception as e:
                conn.sendall(json.dumps({"error": str(e)}).encode())
            finally:
                conn.close()

        daemon_thread = threading.Thread(target=self._main_loop, args=(True,), daemon=True)
        daemon_thread.start()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        server.listen(5)
        logger.info("Daemon listening on %s", sock_path)

        try:
            while self.running:
                conn, _ = server.accept()
                threading.Thread(target=handle_client, args=(conn,), daemon=True).start()
        finally:
            server.close()
            try:
                os.unlink(sock_path)
            except OSError:
                pass

    def stop(self):
        """停止所有运行。"""
        self.running = False
        self._stop_event.set()
        logger.info("Stopping...")

    def pause(self):
        """暂停执行。"""
        self.paused = True
        logger.info("Paused")

    def resume(self):
        """恢复执行。"""
        self.paused = False
        logger.info("Resumed")

    def calibrate(self):
        """一键校准。"""
        try:
            from auto_play import Calibrator
            cal = Calibrator(self.config)
            cal.run_all()
            logger.info("Calibration completed")
        except ImportError:
            logger.warning("Calibration module not available — falling back to setup wizard")
        except Exception as e:
            logger.error("Calibration failed: %s", e)

    def get_status(self) -> dict:
        """获取运行状态快照。"""
        with self._lock:
            return {
                "running": self.running,
                "paused": self.paused,
                "mode": self.mode,
                "current_task": self.current_task,
                "fps": self.stats["fps"],
                "clicks": self.stats["clicks"],
                "songs_played": self.stats["songs_played"],
                "errors": self.stats["errors"],
                "uptime": self._format_uptime(),
                "pid": os.getpid(),
            }

    # ── 私有方法 ──

    def _main_loop(self, infinite: bool = False):
        """主循环 - v5.4: 集成 CaptureOptimizer + 任务缓存复用。"""
        # 延迟初始化 TaskDataLoader (模块级导入, 实例化)
        if self._task_loader is None:
            self._task_loader = TaskDataLoader("resource/tasks")
        task_loader = self._task_loader
        frame_count = 0
        last_fps_time = time.time()

        while self.running and not self._stop_event.is_set():
            try:
                if self.paused:
                    time.sleep(0.1)
                    continue

                # FPS 统计
                frame_count += 1
                now = time.time()
                if now - last_fps_time >= 1.0:
                    with self._lock:
                        self.stats["fps"] = frame_count / (now - last_fps_time)
                    frame_count = 0
                    last_fps_time = now

                # v5.4: CaptureOptimizer 帧差检测 — 无变化跳过
                frame = self._get_frame()
                if frame is None:
                    time.sleep(0.05)
                    continue

                # 场景检测
                task_name = self._detect_scene(frame)

                # v5.4: CaptureOptimizer 帧差跳过
                if self._capture_optimizer and task_name and self._scene_classifier:
                    try:
                        last = self._scene_classifier._last_result
                        if last and not self._capture_optimizer.has_changed(frame,
                                                                           last.scene_name):
                            continue
                    except Exception:
                        pass

                # v5.4: 复用缓存的 ProcessTask 实例
                if task_name:
                    self.current_task = task_name
                    if task_name not in self._task_cache:
                        task_def = task_loader.get_task(task_name)
                        if task_def:
                            self._task_cache[task_name] = ProcessTask(
                                task_def, self.controller, frame
                            )
                    cached = self._task_cache.get(task_name)
                    if cached:
                        # v5.4: 传入 frame context, 避免 ProcessTask 重复截图
                        result = cached.run(context={"frame": frame})
                        if result.action_taken:
                            with self._lock:
                                self.stats["clicks"] += 1

                # 非无限模式只跑一圈
                if not infinite:
                    break

            except PjskError as e:
                self._handle_error(e)
            except Exception as e:
                logger.error("Unexpected error: %s", e, exc_info=True)
                with self._lock:
                    self.stats["errors"] += 1
                time.sleep(1.0)

    def _get_frame(self):
        """获取当前画面帧。"""
        if self.controller:
            try:
                return self.controller.screencap()
            except Exception as e:
                logger.debug("Screencap failed: %s", e)
        return None

    def _detect_scene(self, frame) -> str:
        """场景检测 → 返回对应的 Pipeline 任务名。

        v5.4: 使用模块级导入的 SceneClassifier (移除了函数体内 import)。
        """
        try:
            if self._scene_classifier is None:
                self._scene_classifier = SceneClassifier(self.config)
            scene = self._scene_classifier.classify(frame)
            return scene.task_name
        except Exception as e:
            logger.debug("Scene detection failed: %s", e)
            return ""

    def _handle_error(self, error: PjskError):
        """处理分级异常并执行自动恢复策略。"""
        with self._lock:
            self.stats["errors"] += 1
        error.log()
        strategy = get_recovery_strategy(error.code)
        action = strategy.get("action", "stop")
        retry_delay = strategy.get("retry_delay", 1.0)
        max_retries = strategy.get("max_retries", 3)

        logger.warning("Recovery: action=%s, delay=%.1fs, max_retries=%d",
                       action, retry_delay, max_retries)

        try:
            if action == "restart_app":
                self._recovery_restart_app(error)
            elif action == "force_restart":
                self._recovery_force_restart(error)
            elif action == "navigate_back":
                self._recovery_navigate_back()
            elif action == "wait_reconnect":
                self._recovery_wait_reconnect(retry_delay, max_retries)
            elif action == "skip_task":
                logger.info("Skipping current task due to %s", error.code)
            elif action == "retry":
                time.sleep(retry_delay)
            else:
                logger.error("Unhandled recovery action: %s", action)
        except Exception as e:
            logger.error("Recovery failed: %s", e)

    def _recovery_restart_app(self, error: PjskError):
        """杀死游戏进程并重启。"""
        logger.info("Recovery: restarting game app...")
        try:
            if self.controller:
                self.controller.app_stop("com.sega.pjsekai")
            time.sleep(2.0)
            if self.controller:
                self.controller.app_start("com.sega.pjsekai")
            time.sleep(5.0)
        except Exception as e:
            logger.error("Restart app failed: %s", e)

    def _recovery_force_restart(self, error: PjskError):
        """强制杀进程 + 重启。"""
        logger.info("Recovery: force restarting...")
        try:
            if self.controller:
                self.controller.app_stop("com.sega.pjsekai")
            # Also try shell-level force stop
            if self.controller and hasattr(self.controller, 'shell'):
                self.controller.shell("am force-stop com.sega.pjsekai")
            time.sleep(3.0)
            if self.controller:
                self.controller.app_start("com.sega.pjsekai")
            time.sleep(5.0)
        except Exception as e:
            logger.error("Force restart failed: %s", e)

    def _recovery_navigate_back(self):
        """尝试按返回键退出未知页面。"""
        logger.info("Recovery: pressing back key...")
        try:
            if self.controller and hasattr(self.controller, 'shell'):
                self.controller.shell("input keyevent 4")
            time.sleep(1.0)
        except Exception as e:
            logger.error("Navigate back failed: %s", e)

    def _recovery_wait_reconnect(self, retry_delay: float, max_retries: int):
        """等待设备重连。"""
        logger.info("Recovery: waiting for device reconnect...")
        for i in range(max_retries):
            if self.controller and self.controller.is_connected:
                logger.info("Device reconnected")
                return
            logger.debug("Reconnect attempt %d/%d", i + 1, max_retries)
            time.sleep(retry_delay)
        logger.error("Device reconnection failed after %d attempts", max_retries)

    def _start_web_server(self):
        """启动 Web 服务器（后台线程）。"""
        try:
            from web.app import WebApp
            port = self.config.get("web", {}).get("port", 8080)
            web_app = WebApp(profile=self.profile, port=port, app=self)
            t = threading.Thread(target=web_app.run, daemon=True, name="web-server")
            t.start()
            logger.info("Web server started on port %d", port)
        except Exception as e:
            logger.warning("Web server failed: %s", e)

    def _format_uptime(self) -> str:
        elapsed = time.time() - self.stats.get("start_time", time.time())
        h, r = divmod(int(elapsed), 3600)
        m, s = divmod(r, 60)
        if h > 0:
            return f"{h}h{m}m"
        return f"{m}m{s}s"
