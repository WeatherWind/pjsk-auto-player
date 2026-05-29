"""
PJSK Auto Player — Web GUI V2 服务器

HTTP + SSE 服务器，基于 http.server 标准库。
提供 REST API、SSE 实时推送、静态文件服务。

启动:
    python -m web.app [--port 8080] [--bind 0.0.0.0]

API 端点:
    GET  /                   — dashboard.html
    GET  /status             — 运行状态 (JSON)
    GET  /screenshot         — 当前帧 (base64 JPEG, JSON)
    GET  /log                — 日志缓冲区 (JSON)
    GET  /config             — 配置文件 (JSON)
    GET  /stats              — 性能统计 (JSON)
    GET  /events             — SSE 实时事件流
    POST /command            — 执行命令 (JSON body)

命令 (POST /command):
    {"action": "start", "mode": "FC", "count": 10}
    {"action": "stop"}
    {"action": "pause"}
    {"action": "resume"}
    {"action": "reconnect"}
    {"action": "calibrate"}
"""

import argparse
import base64
import json
import logging
import os
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

from .websocket import SSEHandler, push_log

logger = logging.getLogger("pjsk.web.app")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")

# ── 全局状态引用 (由后端在初始化时设置) ──
_app_instance = None  # PjskApp 实例引用
_cfg = {}             # 配置字典
_log_buf = []         # 日志缓冲区
_log_lock = threading.Lock()

# ── 后端控制器引用 (由 web_dashboard 兼容层设置) ──
_adb = None
_app_running = False
_app_paused = False


def init(app_instance=None, config=None, adb_ref=None,
         log_buffer=None, log_lock_ref=None,
         running_ref=None, paused_ref=None):
    """
    初始化全局引用，由后端在启动时调用。

    参数:
        app_instance: PjskApp 实例 (app.py 中的 App 类)
        config: 配置字典
        adb_ref: ADB 控制器引用
        log_buffer: 日志缓冲区列表
        log_lock_ref: 日志锁
        running_ref: 运行状态引用
        paused_ref: 暂停状态引用
    """
    global _app_instance, _cfg, _adb, _log_buf, _log_lock
    global _app_running, _app_paused

    if app_instance is not None:
        _app_instance = app_instance
    if config is not None:
        _cfg = config
    if adb_ref is not None:
        _adb = adb_ref
    if log_buffer is not None:
        _log_buf = log_buffer
    if log_lock_ref is not None:
        _log_lock = log_lock_ref
    if running_ref is not None:
        _app_running = running_ref
    if paused_ref is not None:
        _app_paused = paused_ref


# ═══════════════════════════════════════════════════
# HTTP 请求处理器
# ═══════════════════════════════════════════════════


class WebHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = self.path.split("?")[0]

        try:
            # ── 仪表盘 HTML ──
            if path == "/":
                self._serve_html()

            # ── SSE 实时事件流 ──
            elif path == "/events":
                SSEHandler.handle_sse(self)

            # ── REST API ──
            elif path == "/status":
                self._json(self._get_status())

            elif path == "/screenshot":
                self._json(self._get_screenshot())

            elif path == "/log":
                self._json(self._get_log())

            elif path == "/config":
                self._json(self._get_config())

            elif path == "/stats":
                self._json(self._get_stats())

            elif path == "/combos":
                self._json(self._get_combos())

            elif path == "/teams":
                self._json(self._get_teams())

            elif path == "/versions":
                self._json(self._get_versions())

            elif path == "/song-stats":
                self._json(self._get_song_stats())

            elif path == "/history":
                self._json(self._get_history())

            elif path == "/auto-speed":
                self._json(self._get_auto_speed())

            else:
                self.send_error(404, f"Not found: {path}")

        except Exception as e:
            logger.exception("GET %s failed", path)
            self._json({"error": str(e)})

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else "{}"

            if path == "/command":
                try:
                    cmd = json.loads(body)
                except json.JSONDecodeError:
                    self._json({"error": "invalid JSON"})
                    return
                result = self._handle_command(cmd)
                self._json(result)

            elif path == "/config":
                self._json(self._save_config(body))

            else:
                self.send_error(404, f"Not found: {path}")

        except Exception as e:
            logger.exception("POST %s failed", path)
            self._json({"error": str(e)})

    def do_OPTIONS(self):
        """CORS preflight"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── 辅助方法 ──

    def _serve_html(self):
        """返回 dashboard.html"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            with open(HTML_PATH, "rb") as f:
                self.wfile.write(f.read())
        except FileNotFoundError:
            self.wfile.write(b"<h1>dashboard.html not found</h1>")

    def _json(self, data: dict):
        """发送 JSON 响应。"""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, fmt, *args):
        """抑制 http.server 默认日志。"""
        pass

    # ── API 实现 ──

    def _get_status(self) -> dict:
        """获取运行状态。"""
        s = {
            "running": _app_running if isinstance(_app_running, bool) else False,
            "paused": _app_paused if isinstance(_app_paused, bool) else False,
            "adb": bool(_adb and getattr(_adb, 'is_connected', lambda: False)()),
            "scrcpy": bool(_adb and getattr(_adb, 'cfg', {}).get("screencap_method") == "scrcpy"),
            "minitouch": bool(_adb and hasattr(_adb, '_minitouch_socket') and getattr(_adb, '_minitouch_socket', None) is not None),
            "clients": SSEHandler.client_count,
            "version": self._get_version(),
        }
        if _adb:
            try:
                s["screen"] = f"{_adb.screen['width']}x{_adb.screen['height']}"
            except Exception:
                pass
        if _app_instance:
            s["current_task"] = getattr(_app_instance, "current_task", "")
            s["mode"] = getattr(_app_instance, "mode", "")
        return s

    def _get_screenshot(self) -> dict:
        """获取当前帧画面 (base64 JPEG)。"""
        if not _adb:
            return {"image": "", "w": 0, "h": 0}
        try:
            import cv2
            frame = _adb.screencap()
            if frame is None:
                return {"image": "", "w": 0, "h": 0}
            h, w = frame.shape[:2]
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            return {
                "image": base64.b64encode(buf).decode(),
                "w": w,
                "h": h,
            }
        except Exception:
            return {"image": "", "w": 0, "h": 0}

    def _get_log(self) -> dict:
        """获取日志缓冲区。"""
        with _log_lock:
            return {"log": "\n".join(_log_buf[-100:])}

    def _get_config(self) -> dict:
        """获取配置文件内容。"""
        cfg_path = os.path.join(ROOT_DIR, "config.yaml")
        try:
            with open(cfg_path, encoding="utf-8") as f:
                return {"content": f.read()}
        except Exception as e:
            return {"content": f"# Error: {e}"}

    def _save_config(self, content: str) -> dict:
        """保存配置文件。"""
        cfg_path = os.path.join(ROOT_DIR, "config.yaml")
        try:
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(content)
            push_log("💾 配置已保存", "info")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _get_stats(self) -> dict:
        """获取性能统计。"""
        stats_file = os.path.join(ROOT_DIR, ".batch_stats.json")
        d = {
            "running": _app_running if isinstance(_app_running, bool) else False,
            "paused": _app_paused if isinstance(_app_paused, bool) else False,
            "fps": 0,
            "songs_played": 0,
            "total_taps": 0,
            "total_flicks": 0,
            "total_holds": 0,
            "elapsed_seconds": 0,
            "version": self._get_version(),
        }
        try:
            if os.path.exists(stats_file):
                with open(stats_file) as f:
                    d.update(json.load(f))
        except Exception:
            pass
        return d

    def _get_combos(self) -> dict:
        """获取歌单列表。"""
        try:
            from combo_player import ComboPlayer
            return {"combos": ComboPlayer({}).list_combos()}
        except Exception as e:
            return {"combos": [], "error": str(e)}

    def _get_teams(self) -> dict:
        """获取编队列表。"""
        try:
            from team_builder import TeamBuilder
            return {"teams": TeamBuilder({}).list_teams()}
        except Exception as e:
            return {"teams": [], "error": str(e)}

    def _get_versions(self) -> dict:
        """获取版本历史。"""
        import subprocess
        try:
            r = subprocess.run(
                ["git", "tag", "--sort=-version:refname"],
                capture_output=True, text=True, timeout=5, cwd=ROOT_DIR,
            )
            tags = [t for t in r.stdout.strip().split("\n") if t][:10]
            versions = []
            for t in tags:
                date, msg = "", ""
                try:
                    r2 = subprocess.run(
                        ["git", "log", "-1", "--format=%ai|%s", t],
                        capture_output=True, text=True, timeout=3, cwd=ROOT_DIR,
                    )
                    parts = r2.stdout.strip().split("|", 1)
                    if len(parts) == 2:
                        date, msg = parts[0][:10], parts[1][:80]
                except Exception:
                    pass
                versions.append({"tag": t, "date": date, "message": msg})
            return {"versions": versions}
        except Exception:
            return {"versions": []}

    def _get_song_stats(self) -> dict:
        """获取歌曲统计。"""
        hist_file = os.path.join(ROOT_DIR, ".song_history.json")
        try:
            if os.path.exists(hist_file):
                with open(hist_file) as f:
                    history = json.load(f)
                if not history:
                    return {}
                total = len(history)
                recent = history[-30:] if len(history) > 30 else history
                avg_duration = sum(s.get("duration", 0) for s in recent) / len(recent)
                avg_taps = sum(s.get("taps", 0) for s in recent) / len(recent)
                mode_counts = {}
                for s in recent:
                    m = s.get("mode", "?")
                    mode_counts[m] = mode_counts.get(m, 0) + 1
                return {
                    "total_songs": total,
                    "recent_count": len(recent),
                    "avg_duration": round(avg_duration, 1),
                    "avg_taps": round(avg_taps, 1),
                    "mode_distribution": mode_counts,
                    "total_taps": sum(s.get("taps", 0) for s in history),
                    "total_flicks": sum(s.get("flicks", 0) for s in history),
                    "total_holds": sum(s.get("holds", 0) for s in history),
                    "total_duration": round(
                        sum(s.get("duration", 0) for s in history) / 60, 1),
                }
        except Exception:
            pass
        return {}

    def _get_history(self) -> dict:
        """获取歌曲历史。"""
        hist_file = os.path.join(ROOT_DIR, ".song_history.json")
        try:
            if os.path.exists(hist_file):
                with open(hist_file) as f:
                    history = json.load(f)
                return {"history": history[-50:], "total": len(history)}
        except Exception:
            pass
        return {"history": [], "total": 0}

    def _get_auto_speed(self) -> dict:
        """检测游戏速度。"""
        try:
            from auto_play import Calibrator
            cal = Calibrator(_cfg)
            return cal.detect_game_speed(duration_s=8.0)
        except Exception as e:
            return {"detected": False, "message": str(e)}

    def _get_version(self) -> str:
        """获取版本号。"""
        vp = os.path.join(ROOT_DIR, "VERSION")
        try:
            with open(vp) as f:
                return f.read().strip()
        except Exception:
            return "4.3.0"

    def _handle_command(self, cmd: dict) -> dict:
        """
        处理控制命令。

        cmd 格式:
          {"action": "start", "mode": "FC", "count": 10, "combo": "", "team": ""}
          {"action": "stop"}
          {"action": "pause"}
          {"action": "resume"}
          {"action": "reconnect"}
          {"action": "calibrate"}
          {"action": "team", "team": "my_team"}
          {"action": "clear-history"}
        """
        global _app_running
        action = cmd.get("action", "")

        if action == "start":
            mode = cmd.get("mode", "FC")
            count = int(cmd.get("count", 0))
            combo = cmd.get("combo", "")
            team = cmd.get("team", "")

            if _app_running:
                return {"ok": False, "error": "已在运行"}

            def _run_async():
                global _app_running, _app_paused
                try:
                    from auto_play import BatchPlayer
                    player = BatchPlayer(_cfg, song_count=count, mode=mode)
                    push_log(f"🚀 启动冲榜 (mode={mode}, count={count})", "info")
                    _app_running = True
                    _app_paused = False
                    player.start()
                except Exception as e:
                    push_log(f"❌ {e}", "error")
                finally:
                    _app_running = False
                    _app_paused = False
                    push_log("⏹ 已停止", "info")

            t = threading.Thread(target=_run_async, daemon=True)
            t.start()
            return {"ok": True}

        elif action == "stop":
            _app_running = False
            _app_paused = False
            push_log("⏹ 停止命令已发送", "warning")
            return {"ok": True}

        elif action == "pause":
            _app_paused = True
            push_log("⏸ 已暂停", "warning")
            return {"ok": True}

        elif action == "resume":
            _app_paused = False
            push_log("▶ 已恢复", "info")
            return {"ok": True}

        elif action == "reconnect":
            def _reconnect():
                try:
                    push_log("🔄 重新连接设备...", "info")
                    from adb_controller import ADBController
                    global _adb
                    _adb = ADBController(_cfg)
                    if _adb.wait_for_device(timeout=15):
                        push_log("✅ 设备已连接", "info")
                    else:
                        push_log("❌ 设备连接失败", "error")
                except Exception as e:
                    push_log(f"❌ 重连失败: {e}", "error")
            t = threading.Thread(target=_reconnect, daemon=True)
            t.start()
            return {"ok": True}

        elif action == "calibrate":
            def _calibrate():
                try:
                    push_log("📏 开始校准...", "info")
                    from auto_play import Calibrator
                    cal = Calibrator(_cfg)
                    cal.run_all()
                    push_log("✅ 校准完成", "info")
                except Exception as e:
                    push_log(f"❌ 校准失败: {e}", "error")
            t = threading.Thread(target=_calibrate, daemon=True)
            t.start()
            return {"ok": True}

        elif action == "team":
            team_name = cmd.get("team", "")
            if team_name:
                def _apply_team():
                    try:
                        from team_builder import TeamBuilder
                        from adb_controller import ADBController
                        tb = TeamBuilder(_cfg, team_name=team_name)
                        adb = ADBController(_cfg)
                        if tb.team and adb.wait_for_device(timeout=10):
                            tb.navigate_to_team_screen(adb)
                            tb.apply(adb)
                            push_log(f"✅ 编队已应用: {tb.team.name}", "info")
                        else:
                            push_log("❌ 编队失败", "error")
                    except Exception as e:
                        push_log(f"❌ 编队异常: {e}", "error")
                t = threading.Thread(target=_apply_team, daemon=True)
                t.start()
                return {"ok": True}
            return {"ok": False, "error": "未指定编队名称"}

        elif action == "clear-history":
            hist_file = os.path.join(ROOT_DIR, ".song_history.json")
            try:
                if os.path.exists(hist_file):
                    os.remove(hist_file)
                push_log("🗑️ 历史记录已清空", "info")
                return {"ok": True}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        return {"ok": False, "error": f"未知命令: {action}"}


# ═══════════════════════════════════════════════════
# WebApp 类
# ═══════════════════════════════════════════════════


class WebApp:
    """Web GUI V2 应用。"""

    def __init__(self, host="0.0.0.0", port=8080):
        self.host = host
        self.port = port
        self._server: Optional[HTTPServer] = None

    def run(self):
        """启动并运行 HTTP 服务器 (阻塞)。"""
        self._server = HTTPServer((self.host, self.port), WebHandler)
        logger.info("🌐 Web GUI V2 已启动: http://%s:%s", self.host, self.port)
        print(f"\n  🌐 PJSK Web GUI V2: http://localhost:{self.port}")
        print(f"  ─────────────────────────────────────")
        print(f"  Ctrl+C 停止服务\n")
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            print("\n⏹ 服务已停止")
            self._server.server_close()

    def start_background(self):
        """在后台线程启动服务器。"""
        t = threading.Thread(target=self.run, daemon=True, name="web-server-v2")
        t.start()
        return t

    def stop(self):
        """停止服务器。"""
        if self._server:
            self._server.shutdown()
            self._server.server_close()


# ═══════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="PJSK Web GUI V2")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    parser.add_argument("--bind", default="0.0.0.0", help="监听地址")
    args = parser.parse_args()

    app = WebApp(host=args.bind, port=args.port)
    app.run()


if __name__ == "__main__":
    main()
