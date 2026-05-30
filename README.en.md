# PJSK Auto Player — CV Automation Research Tool

[![zh-CN](https://img.shields.io/badge/README-中文-lightgrey)](README.md)
[![en](https://img.shields.io/badge/README-English-blue)](README.en.md)
[![ja](https://img.shields.io/badge/README-日本語-lightgrey)](README.ja.md)

> Computer Vision & Automation Control research project using ADB + OpenCV.
> Architecture inspired by MAA (MaaAssistantArknights) + ALAS (AzurLaneAutoScript) + MaaFramework.

---

## 🚀 Quick Start — Works Out of the Box

### Method 1: Double-click to Launch (Recommended)

| System | Action |
|--------|--------|
| **macOS** | Double-click `PJSK Auto Player.command` |
| **Windows** | Double-click `run.bat` |
| **Linux** | Double-click `run.sh` or run `./run.sh` in terminal |

First run will auto-install dependencies and open the setup wizard. Subsequent launches open the native desktop GUI directly.

### Method 2: Command Line

```bash
python main.py              # 🖥️ Native desktop GUI (default)
python main.py desktop      # 🌐 Desktop mode — auto-opens browser dashboard
python main.py start        # Single run
python main.py auto         # Continuous run (auto-handles results & retry)
python main.py setup        # Setup wizard
```

---

## ✨ Version Highlights

| Version | Features |
|---------|---------|
| **v5.3.0** | 🎮 In-game settings auto-read + multi-server support (JP/TW/CN/KR/EN) + auto-calibration |
| **v5.2.0** | ⚡ Async capture + Raw ADB + Batch touch — massive latency reduction |
| **v5.1.0** | 🌍 i18n (zh/en/ja) + 📱 PWA mobile panel + 🌓 Dual theme + 🧪 Unit tests |
| **v5.0.0** | 🖥️ MAA-style native desktop GUI + Anti-detection + Event detection |
| **v4.11.0** | 🖥️ Out-of-box: Desktop app + auto browser + first-run wizard + system tray |
| **v4.10.0** | 🧬 Deep ALAS integration: cached_property/Resource/color preprocessing/Benchmark/Config Schema |
| **v4.9.0** | 🏗️ MAA/ALAS fusion architecture: Pipeline V2 + multi-algo scene voting + Web dark panel + tiered errors + daemon |

---

## 🔥 Key Features

### 🎯 Prediction Engine
Timing-based prediction system: detects notes above judgment line → tracks movement speed → calculates arrival time → triggers precisely. Compensates for 100-300ms ADB link latency, turning passive reaction into active prediction.

### ⚡ Screen Capture Acceleration (v5.2.0)
- **Async capture**: producer-consumer model, background thread continuously captures, main thread gets frames with zero delay
- **Raw ADB**: `adb exec-out screencap` raw RGBA format, 2-3x faster than PNG
- **Smart degradation**: scrcpy → raw ADB → PNG ADB auto-selects fastest available backend

### ⚡ Batch Touch (v5.2.0)
- **Merged dispatch**: `queue_tap()` + `flush_touch_batch()` — all touches in one frame merged into a single `adb shell` call
- **Overhead reduction**: adb process launches reduced 3-10x

### 🧠 Pipeline V2 Engine (inspired by MAA)
- **JSON task config driven** — declarative pipeline: recognize → act → jump
- **@Task inheritance** — `"ClickOK@ClickSelf"` reuses parent config, only overrides differences
- **Node lifecycle** — `pre_wait_freezes → pre_delay → action → post_wait_freezes → post_delay`
- **Plugin system** — AOP style, auto-injects logging/stats/error handling around tasks
- **Subtask parallelism** — scan popups/notifications in parallel during main task intervals

### 🖥️ Native Desktop GUI (v5.0.0)
- **MAA-style dark window**: tkinter native GUI, zero external deps, cross-platform
- **Device connection panel**: status indicator + one-click connect + real-time stats
- **Play control panel**: mode selection (FC/AP/LIVE/AUTO) + start/pause/stop
- **Menu bar**: wizard/config/calibrate/mode switch/clear log

### 🌐 Web Dashboard V2
Modern dark theme, zero external dependency SPA:
- Real-time frame preview (SSE push)
- Task status monitoring
- FPS/click count real-time line charts
- Online config editor + log viewer + screenshot browser
- 📱 **PWA support** (v5.1.0): installable as standalone app on phone, Service Worker offline cache
- 🌓 **Light/Dark dual theme** (v5.1.0): one-click toggle, localStorage persistence

### 🌍 Internationalization i18n (v5.1.0)
- Three languages: 简体中文 / English / 日本語
- Auto language detection, persistent config

### 🎲 Operation Randomization
Simulates human operation characteristics: Bezier curve swipe paths, timing jitter ±15ms, position offset ±5px, random miss 0.1%, hold micro-movement sequences

### 🎮 Play Strategies
- **AP** — High precision trigger strategy
- **FC** — Balanced stability strategy
- **LIVE** — Basic pass strategy
- **Mixed** — Smart switching strategy (70% FC + 25% AP + 5% LIVE)

### ⚡ PID Adaptive Latency
After each song, latency compensation auto-fine-tunes based on actual trigger advance, gradually converging to the optimal value.

### 🎮 In-game Settings Auto-Read (v5.3.0)
Auto-navigates to in-game LIVE settings, OCR reads `Timing Adjustment` and `Note Speed`, auto-maps to software parameters and calibrates the prediction engine.

- **Auto-calibration**: `timing_offset` → `advance_ms` / `note_speed` → `velocity_factor` auto-conversion
- **6 servers supported**: JP / TW / CN / KR / EN + auto-detection (package name/OCR labels/manual)
- **Zero-config launch**: enabled by default, reads on first run → caches for subsequent use
- **Standalone command**: `python main.py read-settings --server en`

```
┌──────────────────────────────────────────────┐
│  In-game LIVE Settings                        │
│  Timing Adjustment: +5  →   advance_ms -5ms   │
│  Note Speed:       10.5  →   velocity × 1.05  │
│  ─────────────────────────────────────────   │
│  Auto-writes config.yaml + updates predictor  │
└──────────────────────────────────────────────┘
```

### 📡 Multi-Backend Controller
- **scrcpy 60 FPS** — video stream high-speed capture
- **Minitouch <5ms** — ultra-low latency touch
- **Raw ADB** — raw RGBA capture, 2-3x faster than PNG
- **ADB fallback** — auto-detect optimal backend, seamless degradation

### 🛡️ Tiered Exception System (inspired by ALAS)
| Exception | Recovery Strategy |
|-----------|------------------|
| `GameStuckError` | Screen frozen → restart |
| `GameBugError` | State anomaly → kill & restart process |
| `GamePageUnknownError` | Unknown page → navigate back |
| `ConnectionLostError` | Connection lost → wait reconnect |
| `TooManyClickError` | Anti-infinite-loop → stop task |

### 🔧 Config System V2
- **Layered config**: Default < Profile < Local override < Runtime
- **Hot reload**: auto-reload on file change (ConfigWatcher)
- **CLI config management**: `pjsk config set play.mode ap`

### 🔐 Anti-Detection (v5.0.0)
- Bezier curve swipe paths, simulating human finger arcs
- HumanTouch simulator: normal distribution reaction delay, pressure variation
- Hold micro-movement sequences

### 🎵 Auto Event Detection (v5.0.0)
- HSV color analysis identifies event type (Marathon/Cheerful Carnival/Normal)
- Auto song recommendation

---

## Prerequisites

- Python 3.9+
- Android device (choose one):
  - **Physical device**: USB debugging enabled, USB data cable connected
  - **Emulator**: MuMu Player 12 (recommended) or LDPlayer 9
- ADB (auto-detected or manually installed)

---

## Connection Methods

### Method A: Physical Device (USB direct)
```bash
# 1. Enable USB debugging on phone (in Developer Options)
# 2. Connect USB data cable to computer
# 3. Verify connection
adb devices
# Should show: <serial>  device

# 4. Run setup wizard
python main.py setup
```

### Method B: MuMu Player 12 (Recommended)
```bash
# 1. Download MuMu Player 12: https://mumu.163.com/
# 2. Install PJSK in emulator (via Google Play / QooApp / APK)
# 3. Emulator settings → Other settings:
#    - Disable ROOT permission
#    - Resolution: 1280x720 (recommended)
#    - Enable ADB debugging
# 4. Connect to emulator ADB
adb connect 127.0.0.1:7555   # MuMu 12 default port

# 5. Verify connection
adb devices
# Should show: 127.0.0.1:7555  device

# 6. Run setup wizard
python main.py setup
```

### Method C: LDPlayer 9
```bash
# Similar to MuMu, port is 5555
adb connect 127.0.0.1:5555
python main.py setup
```

> ⚠️ **Emulator Notes**:
> - JP server has stricter detection, recommend MuMu 12 Android 9 image
> - EN and TW servers have relatively relaxed detection
> - Do NOT enable ROOT in emulator, may trigger game detection
> - If game crashes, try disabling "Developer Options" in emulator settings

---

## Installation (Developers)

```bash
git clone https://github.com/WeatherWind/pjsk-auto-player.git
cd pjsk-auto-player
pip install -r requirements.txt
```

```bash
# 1. First run → setup wizard
python main.py setup

# 2. Calibrate
python main.py calibrate

# 3. Start playing
python main.py start

# 4. Or launch Web dashboard (browser http://localhost:8080)
python main.py desktop
```

---

## 📂 Project Structure

```
pjsk-auto-player/
├── main.py                     # Entry point
├── app.py                      # App main class (orchestrates all modules)
├── cli.py                      # CLI command handler
├── exceptions.py               # Tiered exception system
│
├── config/                     # Config System V2
│   ├── __init__.py             # ConfigLoader (layered/hot-reload)
│   ├── default.yaml            # Default config
│   └── schema.py               # Config Schema validation
│
├── controller/                 # Device Controller
│   ├── base.py                 # BaseController abstract
│   ├── adb.py                  # ADB control (incl. raw/async)
│   ├── scrcpy.py               # scrcpy video stream
│   └── combined.py             # Smart router + Benchmark
│
├── pipeline/                   # Pipeline V2
│   ├── base.py                 # AbstractTask / PackageTask
│   ├── process.py              # ProcessTask execution engine
│   ├── node.py                 # Node lifecycle
│   ├── plugins.py              # Plugin system (AOP)
│   ├── task_data.py            # JSON + @inheritance parser
│   ├── scheduler.py            # Task scheduler
│   └── timer.py                # Timer (dual-condition)
│
├── scene/                      # Scene Detection
│   ├── classifier.py           # Multi-algo voting classifier
│   ├── states.py               # Scene state definitions
│   └── transitions.py          # State machine
│
├── vision/                     # Image Recognition Engine
│   ├── matcher.py              # Template matching (multi-scale)
│   ├── ocr.py                  # OCR (EasyOCR/Tesseract)
│   ├── color.py                # Color detection (HSV/RGB)
│   ├── scene.py                # Multi-algo fusion
│   └── button.py               # Button declarative UI (ALAS-style)
│
├── web/                        # Web GUI V2
│   ├── app.py                  # HTTP + SSE server
│   ├── websocket.py            # SSE real-time push
│   ├── dashboard.html          # Dashboard (dark/light dual theme)
│   ├── manifest.json           # PWA config
│   ├── sw.js                   # Service Worker offline cache
│   └── icon-*.png              # PWA icons
│
├── wizard/                     # Setup Wizard
│   └── setup.py                # 5-step wizard
│
├── game_settings/              # In-game Settings Reader (v5.3.0)
│   ├── server_config.py        # 5-server UI/OCR config + auto-detect
│   ├── reader.py               # Navigate → OCR read core
│   └── calibrator.py           # Parameter mapping + calibration engine
│
├── handlers/                   # Game Handlers
│   ├── goto_game.py            # Game launch/navigation
│   ├── handle_result.py        # Result/score processing
│   └── event_detect.py         # Event type detection
│
├── lib/                        # Utility Library
│   ├── decorators.py           # cached_property / classproperty
│   ├── resource.py             # Resource management
│   └── anti_detection.py       # Anti-detection (Bezier/pressure/delay)
│
├── notification/               # Notification System
│   ├── desktop.py              # Desktop notifications
│   └── web.py                  # Web push
│
├── locale/                     # i18n Internationalization
│   ├── zh_CN.json              # Simplified Chinese
│   ├── en_US.json              # English
│   └── ja_JP.json              # Japanese
│
├── tests/                      # Unit Tests (pytest, 58 cases)
│   ├── conftest.py             # Shared fixtures
│   ├── test_anti_detection.py
│   ├── test_exceptions.py
│   ├── test_pipeline.py
│   └── test_config.py
│
├── scripts/                    # Build & Release Scripts
│   ├── build.sh                # Local PyInstaller build
│   ├── release.sh              # Release workflow
│   ├── download_minitouch.sh   # Minitouch binary download
│   ├── gen_release_notes.py    # Generate Release Notes from CHANGELOG
│   └── gen_changelog.sh
│
├── .github/workflows/          # CI/CD
│   ├── ci.yml                  # Main CI (lint + test)
│   ├── build.yml               # Build Release (tag trigger)
│   └── auto-release.yml        # Auto Tag + Release (push main)
│
├── resource/                   # Resource Files
│   ├── tasks/                  # JSON task definitions
│   └── templates/              # Template images
│
├── bin/minitouch/              # Minitouch precompiled binaries
├── combos/                     # Chart configs
├── teams/                      # Team configs
├── tasks/                      # Legacy task configs
│
│   # ═══ Root-level core modules (backward-compatible) ═══
├── adb_controller.py
├── auto_play.py
├── pipeline.py
├── screen_analyzer.py
├── web_dashboard.py
├── scrcpy_controller.py
├── scene_classifier.py
├── ocr_reader.py
├── setup_wizard.py
├── native_gui.py
├── desktop_app.py
├── combo_player.py
├── team_builder.py
├── capture_optimizer.py
│
├── config.yaml                 # Runtime config
├── VERSION                     # Version number
├── requirements.txt            # Python dependencies
├── build.spec                  # PyInstaller build config
├── VISION.md                   # Architecture evolution doc
├── VISION_ALAS.md              # ALAS design pattern research
├── CHANGELOG.md                # Changelog
├── TERMS.md                    # Terms of Use
├── CLAUDE.md                   # AI assistant guide
├── run.bat / run.sh            # Launch scripts
└── PJSK Auto Player.command    # macOS double-click launcher
```

---

## Command Reference

| Command | Description |
|---------|-------------|
| `python main.py` | Native desktop GUI (default) |
| `python main.py desktop` | Web desktop mode |
| `python main.py gui` | Native desktop GUI |
| `python main.py start` | Single run |
| `python main.py auto` | Continuous run |
| `python main.py web` | Web server only |
| `python main.py daemon` | Background daemon |
| `python main.py calibrate` | One-click calibration |
| `python main.py read-settings` | Read in-game settings (v5.3.0) |
| `python main.py read-settings --server jp` | Read with specified server |
| `python main.py setup` | Setup wizard |
| `python main.py status` | View daemon status |
| `python main.py stop` | Stop daemon |
| `python main.py config list` | List config profiles |
| `python main.py config set play.mode ap` | Runtime config override |

---

## 🏗️ Architecture

```
                        ┌──────────────────────────────┐
                        │  Native GUI / Web Dashboard    │
                        │  tkinter · SSE push · PWA      │
                        ├──────────────────────────────┤
                        │    CLI / Daemon                │
                        │  status · stop · config · JSON │
                        ├──────────────────────────────┤
                        │     Pipeline V2 Task Engine    │
                        │  @inheritance · Lifecycle · AOP│
                        ├──────────┬──────────┬─────────┤
                        │ Scene    │ Vision   │ Ctrl    │
                        │ Detect   │ Engine   │         │
                        │ Multi-   │ OCR/Match│ ADB/raw │
                        │ algo     │ /Color   │ /scrcpy │
                        ├──────────┴──────────┴─────────┤
                        │  Config V2 (layered + hot-reload)│
                        │  Exception System (tiered + recovery)│
                        │  Anti-Detection (Bezier + pressure) │
                        └──────────────────────────────┘
```

### Design Philosophy
- **Layered decoupling**: Config → Controller → Recognition → Pipeline → GUI fully independent
- **Declarative config**: Behavior driven by JSON/YAML, not hardcoded
- **MAA task model**: ProcessTask engine + @inheritance syntax
- **ALAS exception system**: Tiered errors + auto-recovery strategies
- **MaaFramework architecture**: 3-layer separation (Controller → Resource → Agent)

### Tech Stack
- Python 3.9+
- OpenCV (image processing)
- ADB / scrcpy / minitouch (device control)
- EasyOCR / pytesseract (text recognition)
- http.server + SSE (web service)
- tkinter (native desktop GUI)

---

## 🚦 CI/CD

| Workflow | Trigger | Description |
|----------|---------|-------------|
| **ci.yml** | push (non-main) / PR | lint + pytest (58 tests) |
| **auto-release.yml** | push to main | Auto-read VERSION → create tag → trigger build |
| **build.yml** | tag (v*.*.*) | PyInstaller build → GitHub Release |

---

## Disclaimer

This software is for learning and research purposes only. Use may violate Project Sekai (SEGA/Colorful Palette) Terms of Service. Users assume all risks and responsibilities. The developer is not responsible for any account bans or other consequences.

See [TERMS.md](TERMS.md) for details.

---

## License

MIT License
