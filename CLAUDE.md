# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PJSK Auto Player is an automated gameplay tool for Project Sekai (プロジェクトセカイ), the rhythm game by SEGA/Colorful Palette. It uses ADB + OpenCV for screen capture and touch injection, with a predictive engine that detects notes above the judgment line and triggers taps at the right time (compensating for 100-300ms ADB latency).

Currently at **v4.9.0-dev** — a major refactor absorbing design patterns from MAA (MaaAssistantArknights), ALAS (AzurLaneAutoScript), and MaaFramework.

## Commands

```bash
python main.py                  # Web dashboard (default, http://localhost:8080)
python main.py start            # Start auto-play (single song)
python main.py auto             # Batch/infinite looping mode
python main.py web              # Web dashboard only
python main.py daemon           # Background daemon (Unix socket on ~/.pjskd.sock)
python main.py setup            # Setup wizard
python main.py calibrate        # Auto-calibrate screen params
python main.py status           # Query daemon status
python main.py stop             # Stop daemon
python main.py config list      # List config profiles
python main.py config set play.mode ap  # Runtime config override
python main.py --version        # Print version

# Build single-file executable
pip install pyinstaller
pyinstaller build.spec
```

There is no test suite or linter configured at this stage. Dependencies: `pip install -r requirements.txt` (opencv-python, numpy, pyyaml; optional: scipy, python-scrcpy, pywebview).

## Architecture

### Design Philosophy
- **MAA-style task model**: JSON-driven declared pipelines with `@` inheritance syntax (`TaskA@BaseTask`), `next`/`failed_next`/`exceeded_next` chaining, and retry management.
- **ALAS-style error handling**: Tiered exception hierarchy with automatic recovery strategies (restart game, kill process, navigate back, wait reconnect).
- **MaaFramework 3-layer separation**: Controller → Resource → Agent.
- **Config layering**: default → profile → local override → runtime override, with file-watching hot reload.

### High-Level Architecture

```
│  Web Dashboard (SSE real-time)  │
│  CLI / Daemon (Unix socket)     │
├─────────────────────────────────│
│  Pipeline V2 (JSON task engine) │
│  @inheritance · lifecycle · AOP │
├──────────┬──────────┬───────────│
│ Scene    │ Vision   │ Controller│
│ Detect   │ Engine   │ (ADB/     │
│ (multi-  │ (OCR/TM/ │  scrcpy/  │
│  algo)   │  Color)  │  minitouch│
├──────────┴──────────┴───────────│
│  Config V2 (layered + hot-reload)│
│  Exception V2 (tiered + recovery)│
```

### Key Modules

**`app.py`** — `PjskApp`: The central coordinator. Orchestrates controller, scene detection, pipeline execution, Web server, and daemon. Holds runtime state (running/paused, stats, mode).

**`cli.py`** — CLI entry point. Subcommands: `start`, `auto`, `web`, `daemon`, `setup`, `calibrate`, `status`, `stop`, `config`. Each dispatches to `PjskApp` or direct module calls.

**`config/`** — Config V2 system. `ConfigLoader` merges four layers (default.yaml → profile → local.yaml → runtime). Supports file-watching hot reload (`start_watching()`), on-change callbacks, and CLI overrides (`set_local_override`).

**`controller/`** — Device I/O abstraction:
- `base.py` — `BaseController` ABC: `connect()`, `disconnect()`, `screencap() -> np.ndarray`, `click(x_rel, y_rel)`, `swipe()`. All coordinates are relative 0~1.
- `adb.py` — ADB-based screencap + input tap.
- `scrcpy.py` — scrcpy PPM stream (30-60 FPS) + minitouch low-latency touch.
- `combined.py` — `CombinedController`: auto-detects available backends, tries scrcpy first then ADB fallback, supports runtime switching and performance tracking.

**`pipeline/`** — Pipeline V2 task engine (MAA-inspired):
- `base.py` — `AbstractTask` (template method with plugin hooks), `PackageTask` (subtask container with stop-on-failure), `InterfaceTask` (top-level entry integrating scene detection + scheduling).
- `process.py` — `ProcessTask`: core execution engine. Recognizes (template/OCR/brightness/color) → executes action (ClickSelf/ClickXY/Swipe/Tap/Wait/DoNothing) → decides next via `next`/`failed_next`/`exceeded_next` chaining.
- `task_data.py` — `TaskDataLoader`: loads JSON task definitions, resolves `@` inheritance (e.g., `"TaskA@BaseTask@GrandParent"`), detects circular inheritance.
- `plugins.py` — AOP plugin system. `LoggingPlugin`, `StatisticsPlugin` (success rate, avg duration), `ErrorHandlerPlugin` (consecutive error threshold + alerts). Managed by `PluginManager`.
- `timer.py` — `Timer(limit, count)`: dual-condition timer (time OR access count), from ALAS. Also `FrameTimer` for FPS tracking.
- `scheduler.py` — Task scheduler.

**`scene/`** — Scene detection (ALAS-inspired multi-algorithm voting):
- `states.py` — `GameScene` enum: GAME, RESULT, MENU, LOADING, UNKNOWN. `SceneTask` maps each scene to a default automation task.
- `classifier.py` — `SceneClassifier`: runs `BrightnessDetector`, `ColorDetector`, `TemplateDetector` in parallel, weighted voting to determine current scene. Frame hash caching for performance.
- `transitions.py` — `SceneTransitions`: state machine with valid transition matrix, hysteresis counting to prevent single-frame flicker, callback system.

**`vision/`** — Image recognition engine:
- `button.py` — `PjskButton`: ALAS-style declarative UI elements. Each button has `area` (relative coords), `color`, `button` (click region), and optional `template`. Detection methods: `appear_on()` (color), `match_template()`, `match_binary()` (Otsu threshold). Pre-defined game UI buttons in `PJSK_BUTTONS` dict.
- `matcher.py` — Template matching.
- `ocr.py` — OCR reader.
- `color.py` — Color detection.
- `scene.py` — Multi-algorithm scene detection.

**`web/`** — Web dashboard V2 (zero external dependencies):
- `app.py` — `WebApp`: HTTP server on `http.server`. REST API endpoints (`/status`, `/screenshot`, `/log`, `/config`, `/stats`, `/history`, `/command`). `PjskApp`-independent fallback path that directly instantiates `lib.auto_play.ContinuousPlayer`.
- `websocket.py` — SSE-based real-time push: `SSEHandler` (EventSource-compatible long-polling), `MessageBus` (pub-sub), helper functions (`push_status`, `push_frame`, `push_log`, `push_stats`).

**`handlers/`** — Game interaction handlers (ALAS-inspired):
- `BaseHandler` — shared controller + config.
- `goto_game.py` — `GotoHandler`: start/stop/restart game, navigate to live, handle popups.
- `handle_result.py` — `ResultHandler`: detect result screen, read score, dismiss settlement with jittered clicks.

**`notification/`** — Desktop notifications + web push.

**`wizard/`** — Setup wizard for first-time configuration.

**`exceptions.py`** — Tiered exception hierarchy: `PjskError` → `GameStuckError`, `GameBugError`, `GamePageUnknownError`, `ConnectionLostError`, `TooManyClickError`, `TaskTimeoutError`, `RecognitionError`, `ConfigError`, `DeviceNotConnectedError`. Each has a registered recovery strategy dict (action, retry_delay, max_retries).

**`lib/`** — Backward-compatible legacy code: `adb_controller.py`, `auto_play.py`, `scrcpy_controller.py`, `scene_classifier.py`, `screen_analyzer.py`, `ocr_reader.py`, `pipeline.py`, `web_dashboard.py`, `setup_wizard.py`, `combo_player.py`, `team_builder.py`, `capture_optimizer.py`. The new modules (`app.py`, `controller/`, `pipeline/`, etc.) have their own independent implementations.

### Task Definition Format (JSON)

Tasks are defined in `resource/tasks/` and `tasks/` as JSON. Key fields:
- `action`: `DoNothing` | `ClickSelf` | `ClickXY` | `Swipe` | `Tap` | `Wait`
- `algorithm`: `DirectHit` | `OcrDetect` | `BrightnessDetect` | `ColorDetect`
- `next`: list of task names to try on success; `#next` = sequential, `#self` = retry, `Stop` = halt
- `failed_next`: task names when match fails but within retry limit
- `exceeded_next`: task names when retries exhausted
- `sub`: parallel subtask names (e.g., popup dismissals running alongside main task)
- `preDelay` / `postDelay`: milliseconds
- `maxRetries`: integer
- `roi`: `[x, y, w, h]`
- `template`: template image path (for DirectHit)
- `@` inheritance: `"MyTask@BaseTask"` merges fields, with derived overriding base

### Configuration

Primary config: `config/default.yaml` (built-in defaults via `_ensure_defaults()`). Legacy `config.yaml` still supported and merged at load time. Profile files in `config/profiles/<name>.yaml`. Local overrides in `config/local.yaml` (gitignored). Runtime overrides via CLI `config set` or `ConfigLoader.set_local_override()`.

### Key Design Patterns

1. **Template Method**: `AbstractTask.run()` wraps `_run()` with plugin pre/post hooks.
2. **Plugin/AOP**: Plugins attach to tasks, invoked at lifecycle points — no code changes needed in task implementations.
3. **Strategy + Router**: `CombinedController` selects backends based on availability, with runtime performance monitoring and auto-switching.
4. **Observer**: Config watcher thread monitors file mtimes; callbacks notify subscribers on change.
5. **Command**: Daemon mode uses Unix socket with JSON command messages (status/stop/pause/resume).
6. **State Machine**: `SceneTransitions` with weighted transition matrix and hysteresis for stable scene transitions.
