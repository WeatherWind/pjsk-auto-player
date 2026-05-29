"""
PJSK Auto Player — 分层配置系统 (Config V2)

受 ALAS ConfigUpdater + ConfigWatcher 设计启发。
三层次：默认配置 < Profile配置 < 运行时覆盖

设计要点:
  - 默认配置嵌入代码 (default.yaml)
  - Profile 配置覆盖 (config/profiles/<name>.yaml)
  - 本地覆盖 (config/local.yaml, .gitignored)
  - 热加载: watch=True 时文件修改自动重载
  - 分层合并: default → profile → local → runtime
"""

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

logger = logging.getLogger("pjsk.config")

ROOT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "default.yaml"
LOCAL_CONFIG_PATH = ROOT_DIR / "config" / "local.yaml"
PROFILES_DIR = ROOT_DIR / "config" / "profiles"
ORIG_CONFIG_PATH = ROOT_DIR / "config.yaml"  # 兼容原路径


# ── 默认配置 ──

def get_default_config() -> dict:
    """加载内置默认配置。"""
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}
    return _ensure_defaults(cfg)


def _ensure_defaults(cfg: dict) -> dict:
    """确保配置中所有字段都有默认值。"""
    defaults = {
        "adb": {
            "executable": "adb",
            "device_serial": "",
            "screencap_method": "auto",
            "temp_dir": "/sdcard/",
            "auto_connect": True,
            "reconnect_delay": 2.0,
            "max_reconnect_attempts": 30,
        },
        "scrcpy": {
            "executable": "scrcpy",
            "max_fps": 60,
            "bit_rate": 12000000,
            "scale": 0.5,
            "frame_skip": True,
            "auto_install": True,
        },
        "minitouch": {
            "auto_push": True,
            "binary_path": "bin/minitouch",
            "port": 1111,
        },
        "screen": {
            "width": 1080,
            "height": 2400,
            "judgment_line_y": 0.78,
            "detection_top_ratio": 0.35,
            "lane_count": 5,
            "lane_start_ratio": 0.05,
            "lane_end_ratio": 0.95,
        },
        "play": {
            "mode": "live",  # ap | fc | live | auto (浮动)
            "infinite": False,
            "combo_songs": [],
            "randomize_clicks": True,
            "jitter_ms": 15,
            "position_jitter_px": 5,
            "miss_rate": 0.001,
            "hold_jitter_ms": 30,
            "result_click_delay_min": 0.5,
            "result_click_delay_max": 2.0,
        },
        "pid": {
            "enabled": True,
            "kp": 0.3,
            "ki": 0.05,
            "kd": 0.1,
            "auto_tune": True,
            "samples_per_song": 50,
        },
        "pipeline": {
            "task_timeout": 300,
            "default_retry_times": 5,
            "screenshot_interval": 0.1,
        },
        "scene": {
            "detection_interval": 0.05,
            "stuck_threshold": 15,  # 多少帧无变化视为卡住
            "confidence_threshold": 0.85,
            "algorithms": ["template", "brightness", "color"],
        },
        "web": {
            "enabled": True,
            "port": 8080,
            "host": "0.0.0.0",
            "dark_mode": True,
            "auto_open_browser": False,
        },
        "notification": {
            "desktop": True,
            "sound": True,
            "on_complete": True,
            "on_error": True,
        },
        "logging": {
            "level": "INFO",
            "file": "logs/pjsk.log",
            "max_bytes": 10485760,
            "backup_count": 5,
            "save_screenshots_on_error": True,
        },
        "hotkeys": {
            "pause": "p",
            "quit": "q",
            "delay_up": "=",
            "delay_down": "-",
            "threshold_up": ".",
            "threshold_down": ",",
            "mode_cycle": "m",
        },
    }
    # 递归合并
    for key, val in defaults.items():
        if key not in cfg:
            cfg[key] = val
        elif isinstance(val, dict):
            for sub_key, sub_val in val.items():
                if sub_key not in cfg[key]:
                    cfg[key][sub_key] = sub_val
    return cfg


# ── 配置加载器 ──


class ConfigLoader:
    """分层配置加载器，支持热加载。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_running = False
        self._watch_paths: list[Path] = []
        self._watch_mtimes: dict[str, float] = {}
        self._on_change_callbacks: list[Callable[[dict], None]] = []
        self._config: dict = {}
        self._profile: str = ""
        self._loaded = False
        self._local_overrides: dict = {}

    @property
    def config(self) -> dict:
        """获取当前配置（只读视图）。"""
        if not self._loaded:
            self.load()
        return self._config

    def load(self, profile: str = "") -> dict:
        """加载所有层配置并合并。"""
        with self._lock:
            self._profile = profile or ""
            cfg = get_default_config()
            # Layer 1: profile 覆盖
            if profile:
                profile_cfg = self._load_profile(profile)
                if profile_cfg:
                    cfg = self._deep_merge(cfg, profile_cfg)
            # Layer 2: local.yaml 覆盖
            if LOCAL_CONFIG_PATH.exists():
                local_cfg = self._load_yaml(LOCAL_CONFIG_PATH)
                if local_cfg:
                    cfg = self._deep_merge(cfg, local_cfg)
            # Layer 3: 运行时覆盖
            if self._local_overrides:
                cfg = self._deep_merge(cfg, self._local_overrides)
            # 兼容旧 config.yaml
            if ORIG_CONFIG_PATH.exists():
                orig_cfg = self._load_yaml(ORIG_CONFIG_PATH)
                if orig_cfg:
                    cfg = self._deep_merge(cfg, orig_cfg)
            self._config = cfg
            self._loaded = True
            return cfg

    def reload(self) -> dict:
        """强制重新加载配置。"""
        self._loaded = False
        return self.load(self._profile)

    def set_local_override(self, key_path: str, value: Any):
        """设置运行时覆盖 (如: 'play.mode' -> 'ap')。"""
        with self._lock:
            keys = key_path.split(".")
            target = self._local_overrides
            for k in keys[:-1]:
                if k not in target:
                    target[k] = {}
                target = target[k]
            target[keys[-1]] = value
            self.reload()

    def on_change(self, callback: Callable[[dict], None]):
        """注册配置变更回调。"""
        self._on_change_callbacks.append(callback)

    def start_watching(self, interval: float = 2.0):
        """启动文件变动监听线程。"""
        if self._watcher_running:
            return
        self._watcher_running = True
        self._watch_paths = [DEFAULT_CONFIG_PATH, LOCAL_CONFIG_PATH]
        if self._profile:
            profile_path = PROFILES_DIR / f"{self._profile}.yaml"
            if profile_path.exists():
                self._watch_paths.append(profile_path)
        for p in self._watch_paths:
            if p.exists():
                self._watch_mtimes[str(p)] = p.stat().st_mtime
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            args=(interval,),
            daemon=True,
            name="config-watcher",
        )
        self._watcher_thread.start()
        logger.info("Config watcher started (interval=%.1fs)", interval)

    def stop_watching(self):
        self._watcher_running = False

    def save_profile(self, profile: str, cfg: dict):
        """保存配置到 profile 文件。"""
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        path = PROFILES_DIR / f"{profile}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        logger.info("Profile saved: %s -> %s", profile, path)

    def list_profiles(self) -> list[str]:
        """列出所有可用 profile。"""
        if not PROFILES_DIR.exists():
            return []
        return sorted(
            p.stem for p in PROFILES_DIR.glob("*.yaml")
        )

    # ── 私有方法 ──

    def _load_yaml(self, path: Path) -> Optional[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning("Failed to load %s: %s", path, e)
            return None

    def _load_profile(self, name: str) -> Optional[dict]:
        paths = [
            PROFILES_DIR / f"{name}.yaml",
            ROOT_DIR / f"profiles/{name}.yaml",  # 兼容旧结构
            Path(name) if os.path.exists(name) else None,
        ]
        for p in paths:
            if p and p.exists():
                return self._load_yaml(p)
        return None

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """递归合并两个字典。"""
        result = dict(base)
        for key, val in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = self._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    def _watch_loop(self, interval: float):
        while self._watcher_running:
            time.sleep(interval)
            try:
                changed = False
                for path_str, mtime in list(self._watch_mtimes.items()):
                    p = Path(path_str)
                    if p.exists():
                        new_mtime = p.stat().st_mtime
                        if new_mtime > mtime:
                            self._watch_mtimes[path_str] = new_mtime
                            changed = True
                if changed:
                    logger.info("Config file changed, reloading...")
                    self.reload()
                    for cb in self._on_change_callbacks:
                        try:
                            cb(self._config)
                        except Exception as e:
                            logger.warning("Config change callback error: %s", e)
            except Exception as e:
                logger.debug("Config watch error: %s", e)


# ── 全局单例 ──

_loader: Optional[ConfigLoader] = None


def get_config_loader() -> ConfigLoader:
    global _loader
    if _loader is None:
        _loader = ConfigLoader()
    return _loader


def load_config(profile: str = "") -> dict:
    """便捷方法：加载配置。"""
    return get_config_loader().load(profile)
