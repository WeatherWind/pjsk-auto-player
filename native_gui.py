#!/usr/bin/env python3
"""
PJSK Auto Player — 原生桌面 GUI (Native GUI)

像 MAA (MaaAssistantArknights) 一样的原生桌面应用体验：
  - 黑暗主题现代窗口
  - 设备连接状态 + 一键连接
  - 打歌控制 (开始/暂停/停止)
  - 实时日志输出 + 统计面板
  - 配置编辑 + 校准 + 设置向导
  - 零外部依赖 (仅 tkinter, Python 内置)

用法:
    python native_gui.py                启动 GUI
    python native_gui.py --web 8080     同时启动 Web 服务器
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))

# ═══════════════════════════════════════════════════════════════
# 主题颜色 (Dark Theme)
# ═══════════════════════════════════════════════════════════════

class Theme:
    """MAA 风格暗色主题。"""
    BG_DARK    = "#1a1a2e"   # 最深背景
    BG_PANEL   = "#16213e"   # 面板背景
    BG_CARD    = "#0f3460"   # 卡片背景
    BG_INPUT   = "#1a1a3e"   # 输入框背景
    FG_PRIMARY = "#e0e0e0"   # 主要文字
    FG_SECOND  = "#a0a0b0"   # 次要文字
    FG_MUTED   = "#606080"   # 暗淡文字
    ACCENT     = "#e94560"   # 强调色 (红)
    ACCENT2    = "#0f9b8e"   # 强调色2 (青)
    ACCENT3    = "#f5a623"   # 强调色3 (金)
    SUCCESS    = "#00c853"   # 成功绿
    WARNING    = "#ff9100"   # 警告橙
    ERROR      = "#ff1744"   # 错误红
    BORDER     = "#2a2a4a"   # 边框
    _IS_MAC = hasattr(os, 'uname') and Theme._IS_MAC
    FONT       = ("SF Mono" if _IS_MAC else "Consolas", 11)
    FONT_SM    = ("SF Mono" if _IS_MAC else "Consolas", 10)
    FONT_TITLE = ("SF Pro Display" if _IS_MAC else "Segoe UI", 14, "bold")


# ═══════════════════════════════════════════════════════════════
# 日志队列 (线程安全)
# ═══════════════════════════════════════════════════════════════

class LogQueue:
    """线程安全的日志队列，GUI 定时轮询。"""
    MAX_ENTRIES = 500

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._entries: list[tuple[str, str, str]] = []  # (timestamp, level, message)

    def put(self, level: str, message: str):
        ts = time.strftime("%H:%M:%S")
        entry = (ts, level, message)
        self._queue.put(entry)
        self._entries.append(entry)
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[-self.MAX_ENTRIES:]

    def drain(self) -> list[tuple[str, str, str]]:
        """获取所有未处理的新日志条目。"""
        new = []
        while True:
            try:
                new.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return new

    @property
    def entries(self):
        return self._entries


class GuiLogHandler(logging.Handler):
    """将 logging 输出重定向到 GUI 日志队列。"""
    def __init__(self, log_queue: LogQueue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        level = record.levelname.lower()
        msg = self.format(record)
        self.log_queue.put(level, msg)


# ═══════════════════════════════════════════════════════════════
# 主窗口
# ═══════════════════════════════════════════════════════════════

class PjskGui:
    """PJSK Auto Player 原生 GUI 窗口。

    像 MAA 一样：顶部工具栏 + 左侧状态面板 + 右侧日志面板。
    """

    def __init__(self, port: int = 8080):
        self.port = port
        self.log_queue = LogQueue()
        self._app_instance = None
        self._server_thread = None
        self._running = False

        # ── 创建窗口 ──────────────────────────────────
        self.root = tk.Tk()
        self.root.title(f"PJSK Auto Player v{self._get_version()}")
        self.root.geometry("960x640")
        self.root.minsize(800, 500)
        self.root.configure(bg=Theme.BG_DARK)

        # macOS 适配
        if Theme._IS_MAC:
            try:
                self.root.tk.call(
                    "::tk::unsupported::MacWindowStyle", "appearance", "dark"
                )
            except Exception:
                pass

        # ── 构建 UI ──────────────────────────────────
        self._build_menubar()
        self._build_ui()
        self._setup_logging()

        # 启动后台服务
        self._init_backend()

        # 定时刷新
        self._schedule_refresh()

        # 关闭处理
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 版本号 ─────────────────────────────────────

    @staticmethod
    def _get_version() -> str:
        try:
            return (ROOT_DIR / "VERSION").read_text().strip()
        except Exception:
            return "5.0.0"

    # ── 菜单栏 ─────────────────────────────────────

    def _build_menubar(self):
        menubar = tk.Menu(self.root, bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY,
                         activebackground=Theme.ACCENT, activeforeground="white")

        # 文件
        file_menu = tk.Menu(menubar, tearoff=0, bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY)
        file_menu.add_command(label="设置向导", command=self._run_setup)
        file_menu.add_command(label="编辑配置", command=self._edit_config)
        file_menu.add_command(label="一键校准", command=self._run_calibrate)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        # 控制
        ctrl_menu = tk.Menu(menubar, tearoff=0, bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY)
        ctrl_menu.add_command(label="开始打歌 (FC)", command=lambda: self._start_play("fc"))
        ctrl_menu.add_command(label="开始打歌 (AP)", command=lambda: self._start_play("ap"))
        ctrl_menu.add_command(label="冲榜模式", command=lambda: self._start_play("auto"))
        ctrl_menu.add_separator()
        ctrl_menu.add_command(label="暂停", command=self._pause)
        ctrl_menu.add_command(label="停止", command=self._stop)
        menubar.add_cascade(label="控制", menu=ctrl_menu)

        # 视图
        view_menu = tk.Menu(menubar, tearoff=0, bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY)
        view_menu.add_command(label="在浏览器中打开", command=self._open_browser)
        view_menu.add_command(label="清空日志", command=self._clear_log)
        menubar.add_cascade(label="视图", menu=view_menu)

        self.root.config(menu=menubar)

    # ── UI 构建 ────────────────────────────────────

    def _build_ui(self):
        # 主布局：左右分栏
        main_pane = tk.PanedWindow(
            self.root, orient=tk.HORIZONTAL, bg=Theme.BORDER,
            sashwidth=2, sashrelief=tk.FLAT
        )
        main_pane.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # 左侧面板
        left_frame = tk.Frame(main_pane, bg=Theme.BG_PANEL, width=300)
        main_pane.add(left_frame, minsize=260)

        self._build_status_panel(left_frame)
        self._build_control_panel(left_frame)
        self._build_stats_panel(left_frame)

        # 右侧日志面板
        right_frame = tk.Frame(main_pane, bg=Theme.BG_DARK)
        main_pane.add(right_frame, minsize=400)

        self._build_log_panel(right_frame)

    def _build_status_panel(self, parent):
        """设备状态面板。"""
        frame = tk.LabelFrame(
            parent, text=" 📱 设备状态 ", font=Theme.FONT_TITLE,
            bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY,
            relief=tk.FLAT, bd=0, padx=12, pady=8,
        )
        frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        # 连接状态
        self.status_var = tk.StringVar(value="🔴 未连接")
        status_lbl = tk.Label(
            frame, textvariable=self.status_var,
            font=Theme.FONT, bg=Theme.BG_PANEL, fg=Theme.ERROR,
            anchor=tk.W,
        )
        status_lbl.pack(fill=tk.X, pady=(0, 4))

        # 连接按钮
        btn_frame = tk.Frame(frame, bg=Theme.BG_PANEL)
        btn_frame.pack(fill=tk.X, pady=4)
        tk.Button(
            btn_frame, text="🔄 连接设备", command=self._connect_device,
            bg=Theme.ACCENT2, fg="white", font=Theme.FONT_SM,
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2",
            activebackground=Theme.ACCENT2, activeforeground="white",
        ).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(
            btn_frame, text="📏 校准", command=self._run_calibrate,
            bg=Theme.BG_CARD, fg=Theme.FG_PRIMARY, font=Theme.FONT_SM,
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2",
            activebackground=Theme.BG_CARD,
        ).pack(side=tk.LEFT)

        # 连接信息
        self.device_info_var = tk.StringVar(value="等待连接...")
        tk.Label(
            frame, textvariable=self.device_info_var,
            font=Theme.FONT_SM, bg=Theme.BG_PANEL, fg=Theme.FG_MUTED,
            anchor=tk.W, wraplength=240,
        ).pack(fill=tk.X, pady=(4, 0))

    def _build_control_panel(self, parent):
        """打歌控制面板。"""
        frame = tk.LabelFrame(
            parent, text=" 🎵 打歌控制 ", font=Theme.FONT_TITLE,
            bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY,
            relief=tk.FLAT, bd=0, padx=12, pady=8,
        )
        frame.pack(fill=tk.X, padx=8, pady=4)

        # 模式选择
        mode_frame = tk.Frame(frame, bg=Theme.BG_PANEL)
        mode_frame.pack(fill=tk.X, pady=(0, 6))
        self.mode_var = tk.StringVar(value="fc")
        for text, val, color in [
            ("FC", "fc", Theme.SUCCESS),
            ("AP", "ap", Theme.ACCENT3),
            ("LIVE", "live", Theme.FG_SECOND),
            ("AUTO", "auto", Theme.ACCENT),
        ]:
            tk.Radiobutton(
                mode_frame, text=text, variable=self.mode_var, value=val,
                bg=Theme.BG_PANEL, fg=color, font=Theme.FONT_SM,
                selectcolor=Theme.BG_CARD, activebackground=Theme.BG_PANEL,
                activeforeground=color,
            ).pack(side=tk.LEFT, padx=4)

        # 开始/停止按钮
        btn_frame = tk.Frame(frame, bg=Theme.BG_PANEL)
        btn_frame.pack(fill=tk.X, pady=4)

        self.start_btn = tk.Button(
            btn_frame, text="▶  开始打歌", command=self._start_play_gui,
            bg=Theme.SUCCESS, fg="white", font=("SF Pro Display" if Theme._IS_MAC else "Segoe UI", 12, "bold"),
            relief=tk.FLAT, padx=16, pady=6, cursor="hand2",
            activebackground=Theme.SUCCESS, activeforeground="white",
        )
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.stop_btn = tk.Button(
            btn_frame, text="⏹ 停止", command=self._stop,
            bg=Theme.ERROR, fg="white", font=Theme.FONT_SM,
            relief=tk.FLAT, padx=16, pady=6, cursor="hand2",
            state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(4, 0))

        # 暂停按钮
        self.pause_btn = tk.Button(
            frame, text="⏯ 暂停", command=self._pause,
            bg=Theme.BG_CARD, fg=Theme.FG_PRIMARY, font=Theme.FONT_SM,
            relief=tk.FLAT, padx=12, pady=4, cursor="hand2",
            state=tk.DISABLED,
        )
        self.pause_btn.pack(fill=tk.X, pady=(4, 0))

    def _build_stats_panel(self, parent):
        """统计面板。"""
        frame = tk.LabelFrame(
            parent, text=" 📊 实时统计 ", font=Theme.FONT_TITLE,
            bg=Theme.BG_PANEL, fg=Theme.FG_PRIMARY,
            relief=tk.FLAT, bd=0, padx=12, pady=8,
        )
        frame.pack(fill=tk.X, padx=8, pady=4)

        stats = [
            ("运行时间", "uptime_var", "0s"),
            ("歌曲数", "songs_var", "0"),
            ("点击数", "clicks_var", "0"),
            ("帧率", "fps_var", "0 FPS"),
            ("错误数", "errors_var", "0"),
        ]
        self.stats_widgets = {}
        for label, var_name, default in stats:
            row = tk.Frame(frame, bg=Theme.BG_PANEL)
            row.pack(fill=tk.X, pady=1)
            tk.Label(
                row, text=label, font=Theme.FONT_SM,
                bg=Theme.BG_PANEL, fg=Theme.FG_MUTED, width=8, anchor=tk.W,
            ).pack(side=tk.LEFT)
            var = tk.StringVar(value=default)
            self.stats_widgets[var_name] = var
            tk.Label(
                row, textvariable=var, font=Theme.FONT_SM,
                bg=Theme.BG_PANEL, fg=Theme.ACCENT2, anchor=tk.E,
            ).pack(side=tk.RIGHT)

    def _build_log_panel(self, parent):
        """日志面板。"""
        frame = tk.LabelFrame(
            parent, text=" 📝 运行日志 ", font=Theme.FONT_TITLE,
            bg=Theme.BG_DARK, fg=Theme.FG_PRIMARY,
            relief=tk.FLAT, bd=0, padx=8, pady=8,
        )
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 日志输出区域
        self.log_text = scrolledtext.ScrolledText(
            frame,
            bg=Theme.BG_INPUT,
            fg=Theme.FG_PRIMARY,
            insertbackground=Theme.FG_PRIMARY,
            font=Theme.FONT_SM,
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=8,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 配置日志颜色标签
        for level, color in [
            ("error", Theme.ERROR),
            ("warning", Theme.WARNING),
            ("success", Theme.SUCCESS),
            ("info", Theme.FG_PRIMARY),
            ("debug", Theme.FG_MUTED),
        ]:
            self.log_text.tag_config(level, foreground=color)

        self.log_text.tag_config("timestamp", foreground=Theme.FG_MUTED)

    # ── 后端初始化 ────────────────────────────────

    def _setup_logging(self):
        """设置日志处理器，将日志输出到 GUI。"""
        handler = GuiLogHandler(self.log_queue)
        handler.setFormatter(
            logging.Formatter("%(message)s")
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

    def _init_backend(self):
        """初始化后台 PjskApp 实例。"""
        self.log_queue.put("info", "正在初始化后端...")
        try:
            from app import PjskApp
            self._app_instance = PjskApp()
            self._app_instance.initialize()
            self.log_queue.put("success", "✅ 后端初始化完成")

            # 连接设备
            self._connect_device()
        except Exception as e:
            self.log_queue.put("error", f"❌ 后端初始化失败: {e}")

    # ── 操作 ──────────────────────────────────────

    def _connect_device(self):
        """连接设备。"""
        self.log_queue.put("info", "正在连接设备...")
        self.status_var.set("🟡 连接中...")
        self.root.update()

        def _connect():
            try:
                from controller.combined import CombinedController
                from config import load_config
                cfg = load_config()
                ctrl = CombinedController(cfg)
                if ctrl.connect():
                    size = ctrl.get_screen_size()
                    self.log_queue.put("success",
                        f"✅ 设备已连接 ({size[0]}x{size[1]})")
                    self.status_var.set("🟢 已连接")
                    self.device_info_var.set(
                        f"分辨率: {size[0]}x{size[1]}\n"
                        f"后端: {ctrl.active_backend or 'auto'}"
                    )
                else:
                    self.log_queue.put("error", "❌ 设备连接失败")
                    self.log_queue.put("info",
                        "💡 请确保:\n"
                        "  1. 手机已通过USB连接\n"
                        "  2. USB调试已开启\n"
                        "  3. 已授权此电脑")
                    self.status_var.set("🔴 未连接")
            except Exception as e:
                self.log_queue.put("error", f"❌ 连接异常: {e}")
                self.status_var.set("🔴 错误")

        threading.Thread(target=_connect, daemon=True).start()

    def _start_play_gui(self):
        mode = self.mode_var.get()
        self._start_play(mode)

    def _start_play(self, mode: str):
        """开始打歌。"""
        if not self._app_instance:
            self.log_queue.put("error", "❌ 后端未初始化")
            return

        self.log_queue.put("success", f"🎵 开始打歌 (模式: {mode.upper()})")
        self._running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.pause_btn.config(state=tk.NORMAL)
        self.status_var.set(f"🎵 打歌中 ({mode.upper()})")

        def _run():
            try:
                self._app_instance.run(mode=mode)
            except Exception as e:
                self.log_queue.put("error", f"❌ 打歌异常: {e}")
            finally:
                self._running = False
                self.root.after(0, self._on_play_stopped)

        threading.Thread(target=_run, daemon=True).start()

    def _on_play_stopped(self):
        """打歌停止后的 UI 更新。"""
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.pause_btn.config(state=tk.DISABLED)
        self.status_var.set("🟢 已连接" if self._app_instance else "🔴 未连接")

    def _pause(self):
        if self._app_instance:
            if self._app_instance.paused:
                self._app_instance.resume()
                self.log_queue.put("info", "▶️ 已恢复")
                self.pause_btn.config(text="⏯ 暂停")
            else:
                self._app_instance.pause()
                self.log_queue.put("info", "⏸️ 已暂停")
                self.pause_btn.config(text="▶ 继续")

    def _stop(self):
        if self._app_instance:
            self._app_instance.stop()
        self._running = False
        self.log_queue.put("warning", "⏹ 已停止")
        self._on_play_stopped()

    def _run_calibrate(self):
        self.log_queue.put("info", "📏 开始校准...")
        threading.Thread(target=self._calibrate_thread, daemon=True).start()

    def _calibrate_thread(self):
        try:
            if self._app_instance:
                self._app_instance.calibrate()
                self.log_queue.put("success", "✅ 校准完成")
        except Exception as e:
            self.log_queue.put("error", f"❌ 校准失败: {e}")

    def _run_setup(self):
        self.log_queue.put("info", "🔧 启动设置向导...")
        threading.Thread(target=self._setup_thread, daemon=True).start()

    def _setup_thread(self):
        try:
            from wizard.setup import SetupWizard
            wizard = SetupWizard()
            wizard.run()
            self.log_queue.put("success", "✅ 设置完成")
        except Exception as e:
            self.log_queue.put("error", f"❌ 设置失败: {e}")

    def _edit_config(self):
        cfg_path = ROOT_DIR / "config.yaml"
        if not cfg_path.exists():
            cfg_path = ROOT_DIR / "config" / "default.yaml"
        if Theme._IS_MAC:
            os.system(f"open '{cfg_path}'")
        elif os.name == "nt":
            os.system(f"notepad '{cfg_path}'")
        else:
            os.system(f"xdg-open '{cfg_path}' 2>/dev/null &")
        self.log_queue.put("info", f"📝 已打开配置文件: {cfg_path}")

    def _open_browser(self):
        import webbrowser
        webbrowser.open(f"http://localhost:{self.port}")
        self.log_queue.put("info", f"🌐 浏览器已打开: http://localhost:{self.port}")

    def _clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    # ── 定时刷新 ──────────────────────────────────

    def _schedule_refresh(self):
        """定时刷新日志和统计。"""
        self._drain_log()
        self._update_stats()
        self.root.after(200, self._schedule_refresh)  # 每 200ms 刷新

    def _drain_log(self):
        """将新日志输出到文本框。"""
        new_entries = self.log_queue.drain()
        if not new_entries:
            return

        self.log_text.config(state=tk.NORMAL)
        for ts, level, msg in new_entries:
            # 时间戳
            self.log_text.insert(tk.END, f"{ts}  ", "timestamp")
            # 日志级别 + 消息
            tag = level if level in ("error", "warning", "success", "info", "debug") else "info"
            self.log_text.insert(tk.END, f"{msg}\n", tag)
        self.log_text.see(tk.END)  # 自动滚动到底部
        self.log_text.config(state=tk.DISABLED)

        # 限制最大行数
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 500:
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete("1.0", f"{line_count - 400}.0")
            self.log_text.config(state=tk.DISABLED)

    def _update_stats(self):
        """更新统计面板。"""
        if not self._app_instance:
            return
        try:
            s = self._app_instance.stats
            self.stats_widgets["uptime_var"].set(
                self._app_instance._format_uptime()
            )
            self.stats_widgets["songs_var"].set(str(s.get("songs_played", 0)))
            self.stats_widgets["clicks_var"].set(str(s.get("clicks", 0)))
            self.stats_widgets["fps_var"].set(f"{s.get('fps', 0):.0f} FPS")
            self.stats_widgets["errors_var"].set(str(s.get("errors", 0)))
        except Exception:
            pass

    # ── 关闭 ──────────────────────────────────────

    def _on_close(self):
        """关闭窗口。"""
        if self._running:
            if not messagebox.askyesno("确认退出", "打歌正在进行中，确定退出吗？"):
                return
        if self._app_instance:
            self._app_instance.stop()
        self.root.destroy()

    def run(self):
        """启动 GUI 主循环。"""
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="PJSK Auto Player — 原生桌面 GUI")
    parser.add_argument("--web", type=int, default=0, help="同时启动 Web 服务器 (端口)")
    parser.add_argument("--port", type=int, default=8080, help="Web 服务器端口")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    # 可选：同时启动 Web 服务器
    if args.web:
        from desktop_app import start_web_server
        port = args.web or args.port
        start_web_server(port)
        print(f"🌐 Web 服务器: http://localhost:{port}")

    gui = PjskGui(port=args.port or args.web or 8080)
    gui.run()


if __name__ == "__main__":
    main()
