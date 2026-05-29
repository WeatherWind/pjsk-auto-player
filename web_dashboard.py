"""
PJSK Auto Player — 应用主程序

浏览器完全操控，无需命令行。
自动初始化 scrcpy + minitouch，后台线程管理打歌。

启动:
  python main.py
"""

import argparse
import base64
import json
import logging
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATS_FILE = os.path.join(ROOT_DIR, ".batch_stats.json")

# ── 全局状态 ──
_app_thread: Optional[threading.Thread] = None
_app_running = False
_app_paused = False
_adb = None
_log_buf: list[str] = []
_log_lock = threading.Lock()
_cfg = {}


def _get_version() -> str:
    """从 VERSION 文件读取版本号。"""
    vp = os.path.join(ROOT_DIR, "VERSION")
    try:
        with open(vp) as f:
            return f.read().strip()
    except Exception:
        return "4.3.0"


def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    with _log_lock:
        _log_buf.append(f"[{ts}] {msg}")
        if len(_log_buf) > 200:
            _log_buf.pop(0)


# ══════════════════════════════════════════
# 后端管理
# ══════════════════════════════════════════


def _init_backends():
    """初始化 ADB + scrcpy + minitouch (后台线程)。"""
    global _adb, _cfg
    try:
        from adb_controller import ADBController
        _adb = ADBController(_cfg)
        log("🔌 检测 ADB...")
        if not _adb.wait_for_device(timeout=15):
            log("❌ 手机未连接，请插入 USB 并开启调试")
            _start_reconnect_thread()
            return
        try:
            w, h = _adb.get_screen_size()
            _cfg["screen"]["width"] = w
            _cfg["screen"]["height"] = h
            log(f"📱 {w}x{h}")
        except Exception:
            pass
        # scrcpy
        try:
            _adb.cfg["screencap_method"] = "scrcpy"
            if _adb.screencap() is not None:
                log("📡 scrcpy 30-60 FPS ✓")
            else:
                _adb.cfg["screencap_method"] = "exec-out"
                log("📡 ADB screencap 5-15 FPS")
        except Exception:
            _adb.cfg["screencap_method"] = "exec-out"
            log("📡 ADB screencap")
        # minitouch
        if _adb.init_minitouch():
            log("🤏 minitouch <5ms ✓")
        else:
            log("🤏 ADB input ~50ms")
        # 速度检测
        _run_speedtest()
        log("✅ 后端就绪")
        # 桌面通知
        _notify("设备已连接", "可以开始冲榜了！")
    except Exception as e:
        log(f"❌ 初始化失败: {e}")
        _start_reconnect_thread()


def _start_reconnect_thread():
    """启动自动重连线程 (USB 拔线后自动恢复)。"""
    def watch():
        global _adb
        while True:
            time.sleep(3)
            try:
                if _adb and _adb.is_connected():
                    continue
                log("🔄 USB 断开, 等待重连...")
                for _ in range(60):
                    time.sleep(1)
                    if _adb and _adb.is_connected():
                        log("✅ USB 已重连")
                        _notify("设备已重连", "冲榜继续！")
                        break
                else:
                    log("⏰ 重连超时, 继续等待...")
            except Exception:
                pass
    t = threading.Thread(target=watch, daemon=True)
    t.start()


def _run_speedtest():
    """速度检测: 测量截图耗时和 FPS。"""
    global _adb
    if not _adb:
        return
    try:
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            f = _adb.screencap()
            if f is not None:
                times.append((time.perf_counter() - t0) * 1000)
        if times:
            avg = sum(times) / len(times)
            fps = 1000 / avg if avg > 0 else 0
            log(f"⏱ 截图耗时: {avg:.0f}ms ({fps:.0f} FPS)")
            # 如果太慢, 建议 scrcpy
            if avg > 80:
                log("💡 建议安装 scrcpy 获得更高帧率: brew install scrcpy")
    except Exception:
        pass


def _notify(title: str, message: str):
    """发送系统桌面通知。"""
    try:
        import subprocess
        # macOS
        cmd = ["osascript", "-e",
               f'display notification "{message}" with title "{title}"']
        subprocess.run(cmd, capture_output=True, timeout=3)
    except Exception:
        pass


def cmd_start(song_count=0, combo="", team="", mode="FC"):
    """后台启动冲榜。"""
    global _app_thread, _app_running, _app_paused
    if _app_running:
        log("⚠️ 已在运行")
        return
    def _run():
        global _app_running, _app_paused
        try:
            from auto_play import BatchPlayer
            p = BatchPlayer(_cfg, song_count=song_count, mode=mode)
            p.start()
        except Exception as e:
            log(f"❌ {e}")
        finally:
            _app_running = False
            _app_paused = False
            log("⏹ 停止")
    _app_running = True
    _app_paused = False
    _app_thread = threading.Thread(target=_run, daemon=True)
    _app_thread.start()
    log("▶ 开始冲榜")


def cmd_stop():
    global _app_running, _app_paused
    _app_running = False
    _app_paused = False


def cmd_pause():
    global _app_paused
    _app_paused = not _app_paused
    log("⏸ 暂停" if _app_paused else "▶ 继续")


def cmd_calibrate():
    threading.Thread(target=_do_calibrate, daemon=True).start()


def _apply_team(tb):
    """在后台线程中应用编队。"""
    try:
        from adb_controller import ADBController
        adb = ADBController(_cfg)
        if adb.wait_for_device(timeout=10):
            tb.navigate_to_team_screen(adb)
            tb.apply(adb)
            log(f"✅ 编队已应用: {tb.team.name}")
        else:
            log("❌ 编队失败: 设备未连接")
    except Exception as e:
        log(f"❌ 编队异常: {e}")


def _do_calibrate():
    try:
        from auto_play import Calibrator
        c = Calibrator(_cfg)
        c.run_all()
        log("✅ 校准完成")
    except Exception as e:
        log(f"❌ 校准: {e}")


# ══════════════════════════════════════════
# HTTP 处理器
# ══════════════════════════════════════════


class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = self.path.split("?")[0]
        q = {}
        if "?" in self.path:
            for p in self.path.split("?")[1].split("&"):
                if "=" in p:
                    k, v = p.split("=", 1)
                    q[k] = v
        try:
            if path in ("/", "/index.html"):
                return self._html(HTML)
            if path == "/api/stats":
                return self._json(_api_stats())
            if path == "/api/log":
                return self._json(_api_log())
            if path == "/api/screenshot":
                return self._json(_api_screenshot())
            if path == "/api/config":
                return self._json(_api_config())
            if path == "/api/combos":
                return self._json(_api_combos())
            if path == "/api/teams":
                return self._json(_api_teams())
            if path == "/api/status":
                return self._json(_api_status())
            if path == "/api/setup":
                threading.Thread(target=_init_backends, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/action":
                a = q.get("action", "")
                if a == "start":
                    cmd_start(int(q.get("count", 0)),
                              q.get("combo", ""),
                              q.get("team", ""),
                              q.get("mode", "FC"))
                elif a == "stop":
                    cmd_stop()
                elif a in ("pause", "resume"):
                    cmd_pause()
                elif a == "calibrate":
                    cmd_calibrate()
                elif a == "team":
                    team_name = q.get("team", "")
                    if team_name:
                        from team_builder import TeamBuilder
                        tb = TeamBuilder(_cfg, team_name=team_name)
                        if tb.team:
                            log(f"👥 应用编队: {tb.team.name}")
                            _apply_team(tb)
                elif a == "reconnect":
                    threading.Thread(target=_init_backends, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/versions":
                return self._json(_api_versions())
            if path == "/api/auto-speed":
                return self._json(_api_auto_speed())
            if path == "/api/history":
                return self._json(_api_history())
            if path == "/api/song-stats":
                return self._json(_api_song_stats())
            self.send_error(404)
        except Exception as e:
            self._json({"error": str(e)})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/config":
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n).decode()
            return self._json(_api_save_config(body))
        self._json({"error": "not found"})

    def _html(self, s):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(s.encode())

    def _json(self, d):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(d, ensure_ascii=False).encode())

    def log_message(self, *a):
        pass


# ══════════════════════════════════════════
# API 函数
# ══════════════════════════════════════════


def _api_stats():
    d = {"running": _app_running, "paused": _app_paused,
         "songs_played": 0, "target": 0, "elapsed_seconds": 0,
         "fps": 0, "total_taps": 0, "total_flicks": 0, "total_holds": 0,
         "version": _get_version(), "adb": _adb and _adb.is_connected() or False}
    try:
        if os.path.exists(STATS_FILE):
            with open(STATS_FILE) as f:
                d.update(json.load(f))
    except Exception:
        pass
    return d


def _api_log():
    with _log_lock:
        return {"log": "\n".join(_log_buf[-60:])}


def _api_screenshot():
    if not _adb:
        return {"image": ""}
    try:
        import cv2
        f = _adb.screencap()
        if f is None:
            return {"image": ""}
        _, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 65])
        return {"image": base64.b64encode(buf).decode(),
                "w": f.shape[1], "h": f.shape[0]}
    except Exception:
        return {"image": ""}


def _api_config():
    p = os.path.join(ROOT_DIR, "config.yaml")
    try:
        with open(p, encoding="utf-8") as f:
            return {"content": f.read()}
    except Exception as e:
        return {"content": f"# {e}"}


def _api_save_config(c):
    p = os.path.join(ROOT_DIR, "config.yaml")
    try:
        with open(p, "w", encoding="utf-8") as f:
            f.write(c)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _api_combos():
    try:
        from combo_player import ComboPlayer
        return {"combos": ComboPlayer({}).list_combos()}
    except Exception as e:
        return {"combos": [], "error": str(e)}


def _api_teams():
    try:
        from team_builder import TeamBuilder
        return {"teams": TeamBuilder({}).list_teams()}
    except Exception as e:
        return {"teams": [], "error": str(e)}


def _api_status():
    s = {"adb": _adb and _adb.is_connected() or False,
         "scrcpy": _adb and _adb.cfg.get("screencap_method") == "scrcpy" or False,
         "minitouch": hasattr(_adb, '_minitouch_socket') and _adb._minitouch_socket is not None}
    if _adb:
        try:
            s["screen"] = f"{_adb.screen['width']}x{_adb.screen['height']}"
        except Exception:
            pass
    return s


def _api_history():
    """返回歌曲历史记录。"""
    hist_file = os.path.join(ROOT_DIR, ".song_history.json")
    try:
        if os.path.exists(hist_file):
            with open(hist_file) as f:
                history = json.load(f)
            return {"history": history[-50:], "total": len(history)}
    except Exception:
        pass
    return {"history": [], "total": 0}


def _api_song_stats():
    """返回汇总统计。"""
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
                "total_duration": round(sum(s.get("duration", 0) for s in history) / 60, 1),
            }
    except Exception:
        pass
    return {}


def _api_auto_speed():
    from auto_play import Calibrator
    try:
        cal = Calibrator(_cfg)
        return cal.detect_game_speed(duration_s=8.0)
    except Exception as e:
        return {"detected": False, "message": str(e)}

def _api_versions():
    import subprocess
    try:
        r = subprocess.run(["git", "tag", "--sort=-version:refname"],
                           capture_output=True, text=True, timeout=5, cwd=ROOT_DIR)
        tags = [t for t in r.stdout.strip().split("\n") if t][:10]
        v = []
        for t in tags:
            d, m = "", ""
            try:
                r2 = subprocess.run(["git", "log", "-1", "--format=%ai|%s", t],
                                    capture_output=True, text=True, timeout=3, cwd=ROOT_DIR)
                p = r2.stdout.strip().split("|", 1)
                if len(p) == 2:
                    d, m = p[0][:10], p[1][:80]
            except Exception:
                pass
            v.append({"tag": t, "date": d, "message": m})
        return {"versions": v}
    except Exception:
        return {"versions": []}


# ══════════════════════════════════════════
# HTML 前端 (完整单页应用)
# ══════════════════════════════════════════

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PJSK Auto Player</title>
<style>
:root{--bg:#0d1117;--srf:#161b22;--bd:#30363d;--tx:#c9d1d9;--td:#8b949e;--ac:#58a6ff;--gr:#3fb950;--rd:#f85149}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--tx);height:100vh;display:flex;overflow:hidden}
.sb{width:220px;background:var(--srf);border-right:1px solid var(--bd);display:flex;flex-direction:column;flex-shrink:0}
.sbh{padding:20px;border-bottom:1px solid var(--bd)}
.sbh h1{font-size:16px;color:var(--ac)}
.sbh .v{font-size:11px;color:var(--td);margin-top:4px}
.nav{padding:12px 20px;cursor:pointer;display:flex;align-items:center;gap:10px;color:var(--td);font-size:14px;border-left:3px solid transparent}
.nav:hover{background:#1c2128;color:var(--tx)}
.nav.a{color:var(--tx);border-left-color:var(--ac);background:#1c2128}
.mn{flex:1;overflow-y:auto;padding:24px;min-width:0}
.pg{display:none}.pg.a{display:block}
.card{background:var(--srf);border:1px solid var(--bd);border-radius:8px;padding:20px;margin-bottom:16px}
.ct{font-size:12px;text-transform:uppercase;color:var(--td);letter-spacing:.5px;margin-bottom:14px}
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:12px}
.st{text-align:center;padding:12px;background:var(--bg);border-radius:6px}
.sv{font-size:22px;font-weight:700}
.sl{font-size:11px;color:var(--td);margin-top:2px}
.btn{padding:8px 20px;border-radius:6px;border:1px solid var(--bd);cursor:pointer;font-size:13px;background:transparent;color:var(--tx)}
.btn-p{background:var(--ac);color:#fff;border-color:var(--ac)}
.btn-d{background:var(--rd);color:#fff;border-color:var(--rd)}
.btn-s{padding:4px 14px;font-size:12px}
.cx{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px;align-items:center}
.lb{background:#010409;border:1px solid var(--bd);border-radius:6px;padding:12px;font-family:monospace;font-size:12px;max-height:360px;overflow-y:auto;line-height:1.6}
.ll{white-space:pre-wrap;word-break:break-all}
.lt{color:var(--td);margin-right:6px}
.sc{max-width:100%;max-height:60vh;border-radius:6px;border:1px solid var(--bd);display:block;margin:0 auto}
.fg{margin-bottom:12px}
.fg label{display:block;font-size:12px;color:var(--td);margin-bottom:4px}
.fg select,.fg input{padding:8px 12px;background:var(--bg);border:1px solid var(--bd);border-radius:6px;color:var(--tx);font-size:13px;width:100%}
.fr{display:grid;grid-template-columns:1fr 1fr;gap:12px}
textarea{width:100%;min-height:360px;background:#010409;border:1px solid var(--bd);border-radius:6px;padding:12px;color:var(--tx);font-family:monospace;font-size:12px;resize:vertical}
.bdg{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:12px;font-size:12px}
.bdg-g{background:rgba(63,185,80,.15);color:var(--gr)}
.bdg-r{background:rgba(248,81,73,.15);color:var(--rd)}
.bdg-y{background:rgba(210,153,34,.15);color:#d29922}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dg{background:var(--gr)}.dr{background:var(--rd)}.dy{background:#d29922}
.si{text-align:center;color:var(--td);font-size:12px;margin-top:6px}
.pg-about td{padding:6px 12px;font-size:13px;border-bottom:1px solid var(--bd)}
.pg-about td:first-child{color:var(--ac);font-weight:600}
@media(max-width:768px){.sb{width:60px}.sbh h1,.sbh .v,.nav span{display:none}.nav{padding:12px;justify-content:center}.mn{padding:12px}}
</style>
</head>
<body>
<div class="sb">
<div class="sbh"><h1>🎵 PJSK</h1><div class="v" id="sidebar-version">v4.3.0</div></div>
<div class="nav a" onclick="sp('dash')"><span>📊</span><span>仪表盘</span></div>
<div class="nav" onclick="sp('phone')"><span>📸</span><span>手机画面</span></div>
<div class="nav" onclick="sp('scripts')"><span>🎮</span><span>歌单&编队</span></div>
<div class="nav" onclick="sp('stats')"><span>📈</span><span>统计</span></div>
<div class="nav" onclick="sp('cfg')"><span>⚙️</span><span>设置</span></div>
<div class="nav" onclick="sp('about')"><span>ℹ️</span><span>关于</span></div>
</div>
<div class="mn">

<div id="p-dash" class="pg a">

<!-- 状态栏 -->
<div class="cx" style="justify-content:space-between;flex-wrap:wrap">
<div style="display:flex;gap:8px;align-items:center">
  <span id="st-bdg" class="bdg bdg-r"><span class="dot dr"></span>未连接</span>
  <span id="dev-info" style="color:var(--td);font-size:12px"></span>
</div>
<div style="display:flex;gap:8px">
  <button class="btn btn-s" onclick="setup()" id="btn-setup">🔌 连接</button>
  <button class="btn btn-d btn-s" onclick="act('stop')" id="btn-stop" style="display:none">⏹ 停止</button>
</div>
</div>

<!-- MAA 风格任务面板 -->
<div class="card" style="padding:0;overflow:hidden">
<table style="width:100%;border-collapse:collapse">
<tr style="border-bottom:1px solid var(--bd);background:var(--bg)">
  <td style="padding:4px 16px;width:40px"></td>
  <td style="padding:12px 8px;color:var(--td);font-size:12px;font-weight:600">步骤</td>
  <td style="padding:12px 8px;color:var(--td);font-size:12px;font-weight:600">配置</td>
  <td style="padding:12px 16px;color:var(--td);font-size:12px;font-weight:600;text-align:right">状态</td>
</tr>

<!-- 1. 校准 -->
<tr style="border-bottom:1px solid var(--bd)">
  <td style="padding:16px"><input type="checkbox" id="chk-calibrate" checked onchange="updateTaskUI()"></td>
  <td style="padding:12px 8px">
    <div style="font-weight:600;font-size:14px">📏 校准</div>
    <div style="color:var(--td);font-size:11px">测量延迟 + 判定线位置</div>
  </td>
  <td style="padding:12px 8px">
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <span style="font-size:12px;color:var(--td)">亮度阈值</span>
      <input type="range" id="cal-threshold" min="150" max="250" value="200" style="width:80px" onchange="document.getElementById('cal-thr-val').textContent=this.value">
      <span id="cal-thr-val" style="font-size:12px;color:var(--ac)">200</span>
    </div>
  </td>
  <td style="padding:12px 16px;text-align:right">
    <span id="st-cal" class="bdg bdg-r" style="font-size:11px">待执行</span>
  </td>
</tr>

<!-- 2. 编队 -->
<tr style="border-bottom:1px solid var(--bd)">
  <td style="padding:16px"><input type="checkbox" id="chk-team"></td>
  <td style="padding:12px 8px">
    <div style="font-weight:600;font-size:14px">👥 编队</div>
    <div style="color:var(--td);font-size:11px">应用编队模板</div>
  </td>
  <td style="padding:12px 8px">
    <select id="task-team" style="padding:6px 10px;background:var(--bg);border:1px solid var(--bd);border-radius:4px;color:var(--tx);font-size:12px" onchange="document.getElementById('chk-team').checked=true;updateTaskUI()">
      <option value="">-- 不编队 --</option>
    </select>
  </td>
  <td style="padding:12px 16px;text-align:right">
    <span id="st-team" class="bdg" style="font-size:11px">跳过</span>
  </td>
</tr>

<!-- 3. 选歌 -->
<tr style="border-bottom:1px solid var(--bd)">
  <td style="padding:16px"><input type="checkbox" id="chk-combo" checked></td>
  <td style="padding:12px 8px">
    <div style="font-weight:600;font-size:14px">🎵 选歌</div>
    <div style="color:var(--td);font-size:11px">歌单/自动切歌</div>
  </td>
  <td style="padding:12px 8px">
    <div style="display:flex;gap:8px;flex-wrap:wrap">
      <select id="task-combo" style="padding:6px 10px;background:var(--bg);border:1px solid var(--bd);border-radius:4px;color:var(--tx);font-size:12px;flex:1"></select>
      <select id="task-diff" style="padding:6px 10px;background:var(--bg);border:1px solid var(--bd);border-radius:4px;color:var(--tx);font-size:12px">
        <option value="any">任意</option>
        <option value="easy">EASY</option>
        <option value="normal">NORMAL</option>
        <option value="hard">HARD</option>
        <option value="expert" selected>EXPERT</option>
        <option value="master">MASTER</option>
      </select>
    </div>
  </td>
  <td style="padding:12px 16px;text-align:right">
    <span id="st-combo" class="bdg" style="font-size:11px">待开始</span>
  </td>
</tr>

<!-- 4. 打歌 -->
<tr>
  <td style="padding:16px"><input type="checkbox" id="chk-play" checked></td>
  <td style="padding:12px 8px">
    <div style="font-weight:600;font-size:14px">▶ 打歌</div>
    <div style="color:var(--td);font-size:11px">自动冲榜</div>
  </td>
  <td style="padding:12px 8px">
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <span style="font-size:12px;color:var(--td)">次数</span>
      <input type="number" id="task-count" value="10" min="0" style="width:60px;padding:6px;background:var(--bg);border:1px solid var(--bd);border-radius:4px;color:var(--tx);font-size:12px">
      <label style="font-size:12px;color:var(--td);display:flex;align-items:center;gap:4px">
        <input type="checkbox" id="task-infinite" onchange="document.getElementById('task-count').disabled=this.checked"> 无限
      </label>
    </div>
  </td>
  <td style="padding:12px 16px;text-align:right">
    <span id="st-play" class="bdg" style="font-size:11px">待开始</span>
  </td>
</tr>
</table>
</div>

<!-- 开始按钮 + 进度 -->
<div class="cx" style="justify-content:center;margin:16px 0">
<button class="btn btn-p" id="btn-go" onclick="runTasks()" style="padding:12px 48px;font-size:16px;font-weight:600">🚀 开始</button>
</div>

<div class="card">
<div class="cx" style="justify-content:space-between;margin-bottom:8px">
  <span class="ct" style="margin:0">实时状态</span>
  <div style="display:flex;gap:16px;font-size:12px">
    <span style="color:var(--td)">FPS: <b id="d-fps" style="color:var(--tx)">0</b></span>
    <span style="color:var(--td)">已打: <b id="d-done" style="color:var(--tx)">0</b></span>
    <span style="color:var(--td)">耗时: <b id="d-time" style="color:var(--tx)">0s</b></span>
  </div>
</div>
<div class="lb" id="log-box"><div class="ll">准备就绪</div></div>
</div>

</div>

<div id="p-phone" class="pg">
<div class="cx">
  <button class="btn btn-s btn-p" onclick="ss()">📸 刷新</button>
  <label style="font-size:12px;color:var(--td);display:flex;align-items:center;gap:4px">
    <input type="checkbox" id="ss-auto" onchange="toggleAutoSS()"> 自动刷新
  </label>
  <span class="si" id="ss-info"></span>
</div>
<div class="card" style="text-align:center"><img id="ss-img" class="sc" src="" alt="手机画面"></div>
</div>

<div id="p-scripts" class="pg">
<div class="card"><div class="ct">启动冲榜</div>
<div class="fr"><div class="fg"><label>歌单</label><select id="sel-combo"></select></div>
<div class="fg"><label>编队</label><select id="sel-team"></select></div></div>
<div class="fr"><div class="fg"><label>打歌模式</label><select id="sel-mode"><option value="FC">FC - Full Combo (默认)</option><option value="AP">AP - All Perfect</option><option value="LIVE">LIVE - 通关保底</option></select></div></div>
<div class="fr"><div class="fg"><label>次数 (0=无限)</label><input type="number" id="inp-count" value="10" min="0"></div>
<div class="fg"><label>&nbsp;</label><button class="btn btn-p" onclick="quickGo()" style="width:100%">🚀 一键启动</button></div></div></div>
<div class="card"><div class="ct">自动检测</div>
<div class="cx"><button class="btn btn-s btn-p" onclick="autoSpeed()">🎯 检测游戏速度</button>
<button class="btn btn-s" onclick="act('calibrate')">📏 校准判定线</button></div>
<div id="speed-result" style="font-size:12px;color:var(--td);margin-top:8px"></div></div>
<div class="card"><div class="ct">歌单</div><div id="combo-list"></div></div>
<div class="card"><div class="ct">编队</div><div id="team-list"></div></div>
</div>

<div id="p-cfg" class="pg">
<div class="card"><div class="ct">config.yaml</div><textarea id="cfg-editor"></textarea>
<div style="margin-top:8px;display:flex;gap:8px">
<button class="btn btn-p btn-s" onclick="saveCfg()">💾 保存</button>
<button class="btn btn-s" onclick="loadCfg()">🔄 刷新</button></div></div>
</div>

<div id="p-stats" class="pg">
<div class="card"><div class="ct">冲榜总览</div>
<div class="sg">
  <div class="st"><div class="sv" id="st-total">-</div><div class="sl">总曲数</div></div>
  <div class="st"><div class="sv" id="st-duration">-</div><div class="sl">总时间 (分钟)</div></div>
  <div class="st"><div class="sv" id="st-avg-dur">-</div><div class="sl">平均时长 (s)</div></div>
  <div class="st"><div class="sv" id="st-avg-tap">-</div><div class="sl">平均点击</div></div>
</div></div>
<div class="card"><div class="ct">模式分布</div><div class="sg" id="mode-dist"></div></div>
<div class="card"><div class="ct">最近记录 (最近 50 首)</div>
<div class="lb" id="history-list" style="max-height:300px"><div class="ll">暂无数据</div></div></div>
<div class="cx"><button class="btn btn-s btn-d" onclick="clearHistory()">🗑️ 清空历史</button></div>
</div>

<div id="p-about" class="pg">
<div class="card" style="text-align:center">
<h2 style="color:var(--ac);margin-bottom:4px">🎵 PJSK Auto Player</h2>
<p style="color:var(--td);font-size:14px" id="about-version">v4.3.0</p>
<p style="color:var(--td);font-size:13px;margin:8px 0">基于 ADB+OpenCV 的 Project Sekai 自动打歌<br>原生桌面窗口 · 预测引擎 · Pipeline · 冲榜 · 反封号</p>
<p style="font-size:13px"><a href="https://github.com/WeatherWind/pjsk-auto-player" target="_blank" style="color:var(--ac)">GitHub</a></p>
<div id="vt" style="margin-top:16px;text-align:left"></div></div>
</div>

</div>
<script>
function sp(n){document.querySelectorAll('.pg').forEach(p=>p.classList.remove('a'));document.querySelectorAll('.nav').forEach(p=>p.classList.remove('a'));document.getElementById('p-'+n).classList.add('a');document.querySelector(`.nav[onclick*="${n}"]`).classList.add('a')}
async function g(u){return(await fetch(u)).json()}
async function act(a){await fetch('/api/action?action='+a)}
async function setup(){document.getElementById('btn-setup').textContent='连接中...';await act('reconnect');setTimeout(poll,1000)}
async function poll(){try{
let d=await g('/api/status');syncVersion();
let e=document.getElementById('st-bdg');let r=d.adb;
e.innerHTML=r?'<span class="dot dg"></span>已连接':'<span class="dot dr"></span>未连接';e.className='bdg '+(r?'bdg-g':'bdg-r');
document.getElementById('dev-info').textContent=r?'📱 '+d.screen+' '+((d.scrcpy?'📡scrcpy':'')+(d.minitouch?' 🤏minitouch':'')):'';
document.getElementById('btn-stop').style.display=_appRunning?'':'none';
let s=await g('/api/stats');
document.getElementById('d-fps').textContent=(s.fps||0).toFixed(1);
document.getElementById('d-done').textContent=s.songs_played||0;
document.getElementById('d-time').textContent=(s.elapsed_seconds||0)+'s';
let l=await g('/api/log');
if(l.log){let lb=document.getElementById('log-box');
lb.innerHTML=l.log.split('\n').filter(x=>x).map(x=>'<div class="ll">'+esc(x)+'</div>').join('');
lb.scrollTop=lb.scrollHeight}
}catch(e){}
setTimeout(poll,2000)}

// ── 版本同步 ──
async function syncVersion(){
  try{let s=await g('/api/stats');let v=s.version||'4.3.0';
  document.getElementById('sidebar-version').textContent='v'+v;
  let av=document.getElementById('about-version');
  if(av)av.textContent='v'+v}catch(e){}
}

// ── 自动截图 ──
var _ssTimer=null;
function toggleAutoSS(){
  if(document.getElementById('ss-auto').checked){
    _ssTimer=setInterval(ss,3000)
  }else{if(_ssTimer){clearInterval(_ssTimer);_ssTimer=null}}
}

// ── Task runners ──
var _appRunning=false;

async function runTasks(){
  _appRunning=true;
  document.getElementById('btn-go').textContent='⏳ 执行中...';
  document.getElementById('btn-go').disabled=true;
  let lb=document.getElementById('log-box');
  lb.innerHTML='<div class="ll">🚀 开始执行...</div>';
  
  // 1. 连接
  await fetch('/api/action?action=reconnect');
  await new Promise(r=>setTimeout(r,2000));
  
  // 2. 校准 (如果勾选)
  if(document.getElementById('chk-calibrate').checked){
    document.getElementById('st-cal').className='bdg bdg-y';document.getElementById('st-cal').textContent='进行中';
    await fetch('/api/action?action=calibrate');
    await new Promise(r=>setTimeout(r,6000));
    document.getElementById('st-cal').className='bdg bdg-g';document.getElementById('st-cal').textContent='✅ 完成';
  }
  
  // 3. 编队 (如果勾选)
  if(document.getElementById('chk-team').checked){
    let team=document.getElementById('task-team').value;
    if(team){
      document.getElementById('st-team').className='bdg bdg-y';document.getElementById('st-team').textContent='进行中';
      await fetch('/api/action?action=team&team='+team);
      await new Promise(r=>setTimeout(r,3000));
      document.getElementById('st-team').className='bdg bdg-g';document.getElementById('st-team').textContent='✅ 完成';
    }
  }
  
  // 4. 冲榜
  if(document.getElementById('chk-play').checked){
    let combo=document.getElementById('task-combo').value||'grind-single';
    let count=document.getElementById('task-infinite').checked?0:parseInt(document.getElementById('task-count').value)||10;
    document.getElementById('st-play').className='bdg bdg-y';document.getElementById('st-play').textContent='进行中';
    await fetch('/api/action?action=start&combo='+combo+'&count='+count);
    document.getElementById('st-play').className='bdg bdg-g';document.getElementById('st-play').textContent='▶ 运行中';
  }
  
  document.getElementById('btn-go').textContent='🚀 开始';
  document.getElementById('btn-go').disabled=false;
}

function updateTaskUI(){
  document.getElementById('cal-threshold').value=document.getElementById('cal-thr-val').textContent;
}
async function ss(){try{
let d=await g('/api/screenshot');
if(d.image){document.getElementById('ss-img').src='data:image/jpeg;base64,'+d.image;document.getElementById('ss-info').textContent=(d.w||'?')+'x'+(d.h||'?')}
}catch(e){}}
async function loadCfg(){try{let d=await g('/api/config');document.getElementById('cfg-editor').value=d.content||''}catch(e){}}
async function saveCfg(){await fetch('/api/config',{method:'POST',headers:{'Content-Type':'text/plain'},body:document.getElementById('cfg-editor').value});alert('✅ 已保存')}
async function loadCombos(){try{
let d=await g('/api/combos');let s=document.getElementById('task-combo');let s2=document.getElementById('sel-combo');let l=document.getElementById('combo-list');
s.innerHTML='<option value="grind-single">单曲循环</option>';l.innerHTML='';
(d.combos||[]).forEach(c=>{s.innerHTML+=`<option value="${c.key}">${c.name} (${c.songs}首)</option>`;if(s2)s2.innerHTML+=`<option value="${c.key}">${c.name}</option>`;l.innerHTML+=`<div style="padding:6px 0;border-bottom:1px solid var(--bd)"><strong>${c.name}</strong> <span style="color:var(--td);font-size:12px">${c.songs}首</span>${c.description?'<div style="color:var(--td);font-size:12px">'+c.description+'</div>':''}</div>`})
}catch(e){}}
async function loadTeams(){try{
let d=await g('/api/teams');let s=document.getElementById('task-team');let s2=document.getElementById('sel-team');let l=document.getElementById('team-list');
s.innerHTML='<option value="">-- 不编队 --</option>';l.innerHTML='';
(d.teams||[]).forEach(t=>{s.innerHTML+=`<option value="${t.key}">${t.name} (${t.method})</option>`;if(s2)s2.innerHTML+=`<option value="${t.key}">${t.name}</option>`;l.innerHTML+=`<div style="padding:6px 0;border-bottom:1px solid var(--bd)"><strong>${t.name}</strong> <span style="color:var(--td);font-size:12px">${t.method}</span>${t.description?'<div style="color:var(--td);font-size:12px">'+t.description+'</div>':''}</div>`})
}catch(e){}}
async function loadVT(){try{
let d=await g('/api/versions');let h='<table style="width:100%;border-collapse:collapse">';
(d.versions||[]).forEach(v=>{h+=`<tr><td>${v.tag}</td><td style="color:var(--td)">${v.date}</td><td style="color:var(--td)">${(v.message||'').slice(0,60)}</td></tr>`});h+='</table>';document.getElementById('vt').innerHTML=h
}catch(e){}}
function quickGo(){let c=document.getElementById('sel-combo').value;let t=document.getElementById('sel-team').value;let n=document.getElementById('inp-count').value||0;let m=document.getElementById('sel-mode').value||'FC';
let p=['/api/action?action=start'];if(c)p.push('combo='+c);if(t)p.push('team='+t);if(n>0)p.push('count='+n);p.push('mode='+m);fetch(p.join('&'))
let lb=document.getElementById('log-box');lb.innerHTML='<div class="ll">🚀 启动冲榜...</div>'}
function esc(s){let d=document.createElement('div');d.textContent=s;return d.innerHTML}
async function autoSpeed(){let r=document.getElementById('speed-result');r.textContent='检测中...请确保在打歌界面 (约8秒)';try{let d=await g('/api/auto-speed');if(d.detected){r.innerHTML='✅ 速度: '+d.avg_velocity+' px/s<br>已自动更新 config.yaml (检测区域 + 预测窗口 + 延迟补偿)';setTimeout(()=>{loadCfg()},500)}else{r.textContent='❌ '+((d||{}).message||'检测失败, 请确保在打歌界面')}}catch(e){r.textContent='❌ 检测失败: '+e}}

// ── 傻瓜模式 ──
async function foolMode(){
  let lb=document.getElementById('log-box');
  lb.innerHTML='<div class="ll">🤖 傻瓜模式启动! 全自动进行中...</div>';
  // 1. 连接设备
  await fetch('/api/action?action=reconnect');
  await new Promise(r=>setTimeout(r,3000));
  // 2. 校准
  await fetch('/api/action?action=calibrate');
  await new Promise(r=>setTimeout(r,5000));
  // 3. 启动冲榜
  let c=document.getElementById('sel-combo').value||'grind-single';
  let t=document.getElementById('sel-team').value||'';
  let n=document.getElementById('inp-count').value||0;
  let p=['/api/action?action=start','combo='+c];if(t)p.push('team='+t);if(n>0)p.push('count='+n);
  await fetch(p.join('&'));
  lb.innerHTML='<div class="ll">🤖 傻瓜模式: 已连接+校准+启动! 坐等收菜~</div>';
}

// ── 桌面通知 ──
if(Notification&&Notification.permission==='default')Notification.requestPermission();

// ── 新手引导 ──
(function(){
  if(localStorage.getItem('pjsk_tour_done'))return;
  let ov=document.createElement('div');
  ov.id='tour-overlay';ov.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.7);z-index:999;display:flex;align-items:center;justify-content:center';
  ov.innerHTML=`<div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:32px;max-width:480px;text-align:center">
    <h2 style="color:#58a6ff;margin-bottom:12px">🎵 欢迎使用 PJSK Auto Player</h2>
    <p style="color:#c9d1d9;font-size:14px;line-height:1.6;margin-bottom:16px">
      只需三步:<br>
      1️⃣ 手机插上 USB → 点击「连接设备」<br>
      2️⃣ 点击「🤖 傻瓜模式」全自动搞定一切<br>
      3️⃣ 坐等收菜!
    </p>
    <p style="color:#8b949e;font-size:12px;margin-bottom:20px">
      也可手动选歌单/编队后点「一键启动」
    </p>
    <button class="btn btn-p" onclick="dismissTour()" style="padding:10px 32px;font-size:15px">🚀 开始使用</button>
  </div>`;
  document.body.appendChild(ov);
})();
function dismissTour(){
  document.getElementById('tour-overlay').remove();
  localStorage.setItem('pjsk_tour_done','1');
}

// ── 统计页面 ──
async function loadStats(){
  try{
    let d=await g('/api/song-stats');
    if(!d.total_songs)return;
    document.getElementById('st-total').textContent=d.total_songs;
    document.getElementById('st-duration').textContent=d.total_duration||0;
    document.getElementById('st-avg-dur').textContent=d.avg_duration||0;
    document.getElementById('st-avg-tap').textContent=d.avg_taps||0;
    // 模式分布
    let md=document.getElementById('mode-dist');md.innerHTML='';
    let colors={'AP':'#3fb950','FC':'#58a6ff','LIVE':'#d29922'};
    for(let[m,c]of Object.entries(d.mode_distribution||{})){
      md.innerHTML+='<div class="st"><div class="sv" style="color:'+(colors[m]||'var(--tx)')+'">'+c+'</div><div class="sl">'+m+'</div></div>'
    }
    // 历史列表
    let hist=await g('/api/history');
    let hl=document.getElementById('history-list');
    if(hist.history&&hist.history.length){
      hl.innerHTML=hist.history.slice().reverse().map(s=>{
        let t=new Date((s.timestamp||0)*1000);
        return '<div class="ll" style="border-bottom:1px solid var(--bd);padding:4px 0">'+
          '<span class="lt">'+t.toLocaleTimeString()+'</span>'+
          ' '+s.mode+' 点'+s.taps+' 划'+s.flicks+' 按'+s.holds+
          ' <span style="color:var(--td)">'+(s.duration?Math.round(s.duration)+'s':'')+'</span></div>'
      }).join('')
    }
  }catch(e){}
}
async function clearHistory(){
  if(!confirm('确定清空所有历史记录？'))return;
  await fetch('/api/action?action=clear-history');
  loadStats()
}
// 页面切换时加载统计
var _origSp=sp;
sp=function(n){_origSp(n);if(n==='stats')loadStats()};

loadCombos();loadTeams();loadCfg();loadVT();setTimeout(poll,500)
</script>
</body>
</html>"""

# ══════════════════════════════════════════
# 入口
# ── 入口 ──


def run(host: str = "0.0.0.0", port: int = 8080, native: bool = True):
    global _cfg
    # 加载配置
    import yaml
    cfg_path = os.path.join(ROOT_DIR, "config.yaml")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            _cfg = yaml.safe_load(f) or {}
    # 确保必要字段
    _cfg.setdefault("screen", {"width": 1080, "height": 2400,
                                "judgment_line_y": 0.78,
                                "left_lanes": [0.15, 0.25, 0.35],
                                "right_lanes": [0.65, 0.75, 0.85],
                                "detect_radius": 30})
    _cfg.setdefault("adb", {"executable": "adb", "screencap_method": "exec-out"})
    _cfg.setdefault("detection", {"method": "brightness",
                                   "brightness": {"threshold": 200,
                                                  "min_contour_area": 50,
                                                  "max_contour_area": 500}})
    _cfg.setdefault("timing", {"latency_compensation_ms": 0})
    _cfg.setdefault("touch", {"tap_duration_ms": 30})
    _cfg.setdefault("batch_play", {})
    _cfg.setdefault("scrcpy", {"auto_init": True, "max_fps": 30, "scale": 0.5})
    _cfg.setdefault("minitouch", {"auto_init": True})
    _cfg.setdefault("display", {"show_stats": True, "stats_interval_frames": 15})

    # 启动自动后端初始化
    threading.Thread(target=_init_backends, daemon=True).start()

    # HTTP 服务
    server = HTTPServer((host, port), Handler)

    # 尝试以原生窗口启动 (PyWebView)
    if native and port == 8080:
        try:
            import webview
            _native = True
            print(f"  ║  🪟 原生窗口模式 (PyWebView)               ║")
            # 在后台线程启动 HTTP 服务器
            import threading
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            # 创建原生窗口
            webview.create_window(
                "PJSK Auto Player",
                f"http://{host}:{port}",
                width=960, height=680,
                resizable=True,
                min_size=(640, 480),
            )
            webview.start()
            return
        except ImportError:
            _native = False
            print(f"  ║  🌐 浏览器模式 (pip install pywebview 可             ║")
            print(f"  ║     获得原生窗口体验)                             ║")

    print()
    print()
    print(f"  ╔══════════════════════════════════════════╗")
    print(f"  ║     PJSK Auto Player                     ║")
    print(f"  ║                                          ║")
    print(f"  ║  浏览器打开:                             ║")
    print(f"  ║    http://localhost:{port}")
    print(f"  ║    http://<电脑IP>:{port}")
    print(f"  ║                                          ║")
    print(f"  ║  手机连接后点击「连接设备」即可            ║")
    print(f"  ║  全部操作在浏览器完成, 无需命令行          ║")
    print(f"  ║                                          ║")
    print(f"  ║  Ctrl+C 停止                             ║")
    print(f"  ╚══════════════════════════════════════════╝")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="PJSK Auto Player")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--bind", default="0.0.0.0")
    args = parser.parse_args()
    run(host=args.bind, port=args.port)


if __name__ == "__main__":
    main()
