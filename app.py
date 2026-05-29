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

logger = logging.getLogger("pjsk.app")


class PjskApp:
    """应用主类 —— 协调所有模块。"""

    def __init__(self, profile: str = ""):
        self.profile = profile
        self._config_loader = get_config_loader()
        self.config = self._config_loader.load(profile)

        # 控制器
        self.controller = None
        self._cv: Optional[cv2.VideoCapture] = None  # noqa: F821

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
        from controller.combined import CombinedController
        try:
            self.controller = CombinedController(self.config)
            self.controller.connect()
            logger.info("Controller connected")
        except Exception as e:
            logger.error("Controller init failed: %s", e)
            raise

    def run(self, mode: str = "live", infinite: bool = False):
        """启动打歌主循环。"""
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
        """暂停打歌。"""
        self.paused = True
        logger.info("Paused")

    def resume(self):
        """恢复打歌。"""
        self.paused = False
        logger.info("Resumed")

    def calibrate(self):
        """一键校准。"""
        from lib.auto_play import calibrate
        calibrate(self.config)

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
        """主循环。"""
        from pipeline.process import ProcessTask
        from pipeline.task_data import TaskDataLoader

        task_loader = TaskDataLoader("resource/tasks")
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
                    self.stats["fps"] = frame_count / (now - last_fps_time)
                    frame_count = 0
                    last_fps_time = now

                # 截图
                frame = self._get_frame()
                if frame is None:
                    time.sleep(0.05)
                    continue

                # 场景检测
                task_name = self._detect_scene(frame)

                # 执行 Pipeline 任务
                if task_name:
                    self.current_task = task_name
                    task_def = task_loader.get_task(task_name)
                    if task_def:
                        task = ProcessTask(task_def, self.controller, frame)
                        result = task.run()
                        if result.action_taken:
                            self.stats["clicks"] += 1

                # 非无限模式只跑一圈
                if not infinite:
                    break

            except PjskError as e:
                self._handle_error(e)
            except Exception as e:
                logger.error("Unexpected error: %s", e, exc_info=True)
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
        """场景检测 → 返回对应的 Pipeline 任务名。"""
        try:
            from scene.classifier import SceneClassifier
            classifier = SceneClassifier(self.config)
            scene = classifier.classify(frame)
            return scene.task_name
        except Exception as e:
            logger.debug("Scene detection failed: %s", e)
            return ""

    def _handle_error(self, error: PjskError):
        """处理分级异常。"""
        self.stats["errors"] += 1
        error.log()
        strategy = get_recovery_strategy(error.code)
        logger.warning("Recovery strategy: %s", strategy["action"])
        # TODO: 执行恢复策略 (restart_app / force_restart / navigate_back 等)

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
