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
        log("✅ 后端就绪")
    except Exception as e:
        log(f"❌ 初始化失败: {e}")


def cmd_start(song_count=0, combo="", team=""):
    """后台启动冲榜。"""
    global _app_thread, _app_running, _app_paused
    if _app_running:
        log("⚠️ 已在运行")
        return
    def _run():
        global _app_running, _app_paused
        try:
            from auto_play import BatchPlayer
            p = BatchPlayer(_cfg, song_count=song_count)
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
                              q.get("team", ""))
                elif a == "stop":
                    cmd_stop()
                elif a in ("pause", "resume"):
                    cmd_pause()
                elif a == "calibrate":
                    cmd_calibrate()
                elif a == "reconnect":
                    threading.Thread(target=_init_backends, daemon=True).start()
                return self._json({"ok": True})
            if path == "/api/versions":
                return self._json(_api_versions())
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
         "version": "3.9.0", "adb": _adb and _adb.is_connected() or False}
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
<div class="sbh"><h1>🎵 PJSK</h1><div class="v">v4.0.0 · 原生窗口</div></div>
<div class="nav a" onclick="sp('dash')"><span>📊</span><span>仪表盘</span></div>
<div class="nav" onclick="sp('phone')"><span>📸</span><span>手机画面</span></div>
<div class="nav" onclick="sp('scripts')"><span>🎮</span><span>歌单&编队</span></div>
<div class="nav" onclick="sp('cfg')"><span>⚙️</span><span>设置</span></div>
<div class="nav" onclick="sp('about')"><span>ℹ️</span><span>关于</span></div>
</div>
<div class="mn">

<div id="p-dash" class="pg a">
<div class="cx">
<span id="st-bdg" class="bdg bdg-r"><span class="dot dr"></span>未连接</span>
<button class="btn btn-s btn-p" id="btn-setup" onclick="setup()">🔌 连接设备</button>
<button class="btn btn-s btn-p" id="btn-start" onclick="act('start')" style="display:none">▶ 开始冲榜</button>
<button class="btn btn-s btn-d" id="btn-stop" onclick="act('stop')" style="display:none">⏹ 停止</button>
<button class="btn btn-s" id="btn-pause" onclick="act('pause')" style="display:none">⏸ 暂停</button>
</div>
<div class="card"><div class="ct">冲榜进度</div>
<div class="sg"><div class="st"><div class="sv" id="s-p">0</div><div class="sl">已完成</div></div>
<div class="st"><div class="sv" id="s-t">∞</div><div class="sl">目标</div></div>
<div class="st"><div class="sv" id="s-e">0s</div><div class="sl">运行时间</div></div>
<div class="st"><div class="sv" id="s-f">0</div><div class="sl">FPS</div></div></div></div>
<div class="card"><div class="ct">操作统计</div>
<div class="sg"><div class="st"><div class="sv" id="s-tap">0</div><div class="sl">点击</div></div>
<div class="st"><div class="sv" id="s-fl">0</div><div class="sl">Flick</div></div>
<div class="st"><div class="sv" id="s-hl">0</div><div class="sl">长按</div></div>
<div class="st"><div class="sv" id="s-lc">0ms</div><div class="sl">延迟补偿</div></div></div></div>
<div class="card"><div class="ct">实时日志</div><div class="lb" id="log-box"><div class="ll">等待中...</div></div></div>
</div>

<div id="p-phone" class="pg">
<div class="cx"><button class="btn btn-s btn-p" onclick="ss()">📸 刷新</button><span class="si" id="ss-info"></span></div>
<div class="card" style="text-align:center"><img id="ss-img" class="sc" src="" alt="手机画面"></div>
</div>

<div id="p-scripts" class="pg">
<div class="card"><div class="ct">启动冲榜</div>
<div class="fr"><div class="fg"><label>歌单</label><select id="sel-combo"></select></div>
<div class="fg"><label>编队</label><select id="sel-team"></select></div></div>
<div class="fr"><div class="fg"><label>次数 (0=无限)</label><input type="number" id="inp-count" value="10" min="0"></div>
<div class="fg"><label>&nbsp;</label><button class="btn btn-p" onclick="quickGo()" style="width:100%">🚀 一键启动</button></div></div></div>
<div class="card"><div class="ct">歌单</div><div id="combo-list"></div></div>
<div class="card"><div class="ct">编队</div><div id="team-list"></div></div>
</div>

<div id="p-cfg" class="pg">
<div class="card"><div class="ct">config.yaml</div><textarea id="cfg-editor"></textarea>
<div style="margin-top:8px;display:flex;gap:8px">
<button class="btn btn-p btn-s" onclick="saveCfg()">💾 保存</button>
<button class="btn btn-s" onclick="loadCfg()">🔄 刷新</button></div></div>
</div>

<div id="p-about" class="pg">
<div class="card" style="text-align:center">
<h2 style="color:var(--ac);margin-bottom:4px">🎵 PJSK Auto Player</h2>
<p style="color:var(--td);font-size:14px">v3.9.0</p>
<p style="color:var(--td);font-size:13px;margin:8px 0">基于 ADB+OpenCV 的 Project Sekai 自动打歌<br>完全浏览器操控 · 预测引擎 · Pipeline 流水线 · 冲榜模式</p>
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
let d=await g('/api/status');
let e=document.getElementById('st-bdg');let r=d.adb;
e.innerHTML=r?'<span class="dot dg"></span>已连接':'<span class="dot dr"></span>未连接';e.className='bdg '+(r?'bdg-g':'bdg-r');
['btn-start','btn-stop','btn-pause'].forEach(id=>document.getElementById(id).style.display=r?'':'none');
let s=await g('/api/stats');let p=s.running;
document.getElementById('s-p').textContent=s.songs_played;
document.getElementById('s-t').textContent=s.target||'∞';
document.getElementById('s-e').textContent=(s.elapsed_seconds||0)+'s';
document.getElementById('s-f').textContent=(s.fps||0).toFixed(1);
document.getElementById('s-tap').textContent=s.total_taps;
document.getElementById('s-fl').textContent=s.total_flicks;
document.getElementById('s-hl').textContent=s.total_holds;
document.getElementById('s-lc').textContent=(s.latency_comp_ms||0)+'ms';
let l=await g('/api/log');let lb=document.getElementById('log-box');
if(l.log){lb.innerHTML=l.log.split('\n').filter(x=>x).map(x=>'<div class="ll">'+esc(x)+'</div>').join('');lb.scrollTop=lb.scrollHeight}
if(r&&document.getElementById('btn-setup').textContent!='已连接'){document.getElementById('btn-setup').textContent='已连接 ✓'}
if(document.getElementById('ss-img').src)ss()
}catch(e){}
setTimeout(poll,2000)}
async function ss(){try{
let d=await g('/api/screenshot');
if(d.image){document.getElementById('ss-img').src='data:image/jpeg;base64,'+d.image;document.getElementById('ss-info').textContent=(d.w||'?')+'x'+(d.h||'?')}
}catch(e){}}
async function loadCfg(){try{let d=await g('/api/config');document.getElementById('cfg-editor').value=d.content||''}catch(e){}}
async function saveCfg(){await fetch('/api/config',{method:'POST',headers:{'Content-Type':'text/plain'},body:document.getElementById('cfg-editor').value});alert('✅ 已保存')}
async function loadCombos(){try{
let d=await g('/api/combos');let s=document.getElementById('sel-combo');let l=document.getElementById('combo-list');
s.innerHTML='<option value="">-- 选择 --</option>';l.innerHTML='';
(d.combos||[]).forEach(c=>{s.innerHTML+=`<option value="${c.key}">${c.name} (${c.songs}首)</option>`;l.innerHTML+=`<div style="padding:6px 0;border-bottom:1px solid var(--bd)"><strong>${c.name}</strong> <span style="color:var(--td);font-size:12px">${c.songs}首</span>${c.description?'<div style="color:var(--td);font-size:12px">'+c.description+'</div>':''}</div>`})
}catch(e){}}
async function loadTeams(){try{
let d=await g('/api/teams');let s=document.getElementById('sel-team');let l=document.getElementById('team-list');
s.innerHTML='<option value="">-- 不编队 --</option>';l.innerHTML='';
(d.teams||[]).forEach(t=>{s.innerHTML+=`<option value="${t.key}">${t.name} (${t.method})</option>`;l.innerHTML+=`<div style="padding:6px 0;border-bottom:1px solid var(--bd)"><strong>${t.name}</strong> <span style="color:var(--td);font-size:12px">${t.method}</span>${t.description?'<div style="color:var(--td);font-size:12px">'+t.description+'</div>':''}</div>`})
}catch(e){}}
async function loadVT(){try{
let d=await g('/api/versions');let h='<table style="width:100%;border-collapse:collapse">';
(d.versions||[]).forEach(v=>{h+=`<tr><td>${v.tag}</td><td style="color:var(--td)">${v.date}</td><td style="color:var(--td)">${(v.message||'').slice(0,60)}</td></tr>`});h+='</table>';document.getElementById('vt').innerHTML=h
}catch(e){}}
function quickGo(){let c=document.getElementById('sel-combo').value;let t=document.getElementById('sel-team').value;let n=document.getElementById('inp-count').value||0;
let p=['/api/action?action=start'];if(c)p.push('combo='+c);if(t)p.push('team='+t);if(n>0)p.push('count='+n);fetch(p.join('&'))
let lb=document.getElementById('log-box');lb.innerHTML='<div class="ll">🚀 启动冲榜...</div>'}
function esc(s){let d=document.createElement('div');d.textContent=s;return d.innerHTML}
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
