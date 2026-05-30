# Obstruction & Recovery System v1

> **Version**: 5.5.0  
> **Date**: 2026-05-30  
> **Status**: Design Approved

## Problem

The script can be blocked by events that are not crashes but halt normal execution:

1. **Server time update / date change popups** — dark overlay + dialog box, require dismiss
2. **Event start/end notifications** — full-screen announcements
3. **Maintenance notices** — progress bars or "OK" buttons
4. **Actual app crashes / black screens / freezes** — need full recovery chain
5. **ADB disconnections** — need reconnect logic

Current `handle_popups()` only runs during game startup, not during gameplay.

## Architecture

```
recovery/
├── __init__.py           → ObstructionEngine export
├── detector.py           → ObstructionDetector (all detection)
├── machine.py            → RecoveryStateMachine (crash recovery)
└── scheduler.py          → HealthScheduler (periodic health checks)
```

### Integration Point

`PjskApp._main_loop` gets one new call per frame:

```python
if self._obstruction_engine:
    result = self._obstruction_engine.process_frame(frame, scene_name, frame_hash)
    if result == "RECOVERING":
        continue  # skip pipeline, enter recovery
    elif result == "DISMISSED":
        pass      # continue pipeline normally
```

## ObstructionDetector (`recovery/detector.py`)

Two detection tracks, run sequentially:

### Lightweight Track (per-frame, <1ms)

| Detection | Method | Output |
|-----------|--------|--------|
| Blocking dialog | Central 40% ROI: bright rectangle + dark surround | `"blocking_dialog"` |
| Frame freeze | frame_hash unchanged > 120 frames (excl. MENU) | `"frozen"` |

Dialog detection details:
- Crop central 40% of screen
- Apply OTSU threshold → find largest bright region
- Check if region size is dialog-proportional (between 5%-30% of screen area)
- Check surrounding pixels are dark (overlay)
- If match → OCR to confirm: scan for known keywords

Known blocking-dialog keyword list (per server):

```python
DIALOG_KEYWORDS = {
    "jp": ["時間", "更新", "お知らせ", "メンテナンス", "開始"],
    "cn": ["时间", "更新", "通知", "公告", "开始", "维护"],
    "tw": ["時間", "更新", "通知", "公告", "開始", "維護"],
    "en": ["update", "notice", "maintenance", "server"],
}
```

On match → auto-dismiss. Dismiss strategy:
1. Try `close_button` region (top-right corner)
2. Try `ok_button` region (center-bottom)
3. Try center-bottom 1/3 of dialog box
4. After 3 failed dismissals → escalate to RecoveryStateMachine

### Heavy Track (triggered by lightweight track hits)

| Detection | Method | Trigger |
|-----------|--------|---------|
| Black screen | mean < 8 for > 30 frames (excl. LOADING) | After freeze detected |
| Crash dialog | OCR "isn't responding / 已停止 / 閉じる" | After dialog detected |
| ADB disconnect | screencap returns None > 10 frames | Independent check |

### Dataclass

```python
@dataclass
class ObstructionEvent:
    type: str               # "blocking_dialog" / "frozen" / "black_screen" / ...
    severity: int           # 1 (dialog) ~ 3 (adb down)
    scene_before: str       # scene name before event
    frame_hash: int         # dedup
    timestamp: float
```

## RecoveryStateMachine (`recovery/machine.py`)

### States

```
IDLE → DETECTED → L1 → L2 → L3 → L4 → L5 (ESCALATED)
                  │      │     │     │
                  └──────┴─────┴─────┴──→ RECOVERED → IDLE
```

### Escalation Chain

| Level | Action | Max Attempts | Backoff | Verification |
|-------|--------|-------------|---------|-------------|
| L1 | `navigate_back` | 3 | 1s→2s→4s | Frame is not UNKNOWN |
| L2 | `restart_app` | 3 | 2s→4s→8s | Frame has content |
| L3 | `force_restart` | 2 | 3s→6s | Frame has content |
| L4 | `adb_reconnect` | 3 | 5s→10s→15s | `adb get-state="device"` |
| L5 | `notify` + `safe_stop` | 1 | — | N/A |

### Crash Pattern Detection

```python
crash_history: deque[(timestamp, type, scene_before)]
# 3 same-type crashes in 5 min → degraded_mode = True
# degraded_mode: L2 failure → skip to L5
# Clear degraded after 5 consecutive successful recoveries
```

### Interface

```python
class RecoveryState:
    IDLE = "idle"
    DETECTED = "detected"
    RECOVERING = "recovering"  # L1-L4 active
    RECOVERED = "recovered"
    ESCALATED = "escalated"

class RecoveryStateMachine:
    def report_crash(self, crash_type: str, scene_before: str = ""): ...
    def tick(self, frame, scene_name): ...
    @property def state(self) -> str: ...
    @property def degraded_mode(self) -> bool: ...
    def reset(self): ...
```

## HealthScheduler (`recovery/scheduler.py`)

Single-thread, driven by main loop `tick()` calls. No background thread.

| Check | Interval | Method | Failure Action |
|-------|----------|--------|---------------|
| ADB alive | 5s | `adb get-state` | `"adb_disconnected"` |
| scrcpy alive | 10s | `process.poll() is None` | Restart scrcpy |
| Latest frame | 5s | `time() - last_frame < 15s` | `"frozen"` |
| Minitouch | 10s | Socket ping | Re-init minitouch |

## ObstructionEngine (`recovery/__init__.py`)

Top-level coordinator:

```python
class ObstructionEngine:
    def __init__(self, controller, config): ...
    def process_frame(self, frame, scene_name, frame_hash) -> str:
        """Returns: "OK" | "DISMISSED" | "RECOVERING" | "ESCALATED" """
    @property def degraded_mode(self) -> bool: ...
    @property def state(self) -> str: ...
    def stop(self): ...
```

### Integration with PjskApp

```python
# __init__
self._obstruction_engine: Optional[ObstructionEngine] = None

# initialize()
from recovery import ObstructionEngine
self._obstruction_engine = ObstructionEngine(self.controller, self.config)

# _main_loop — after _detect_scene, before pipeline
if self._obstruction_engine:
    frame_hash = hash(cv2.resize(frame, (8, 8)).tobytes())
    result = self._obstruction_engine.process_frame(frame, task_name, frame_hash)
    if result == "RECOVERING":
        continue
    elif result == "ESCALATED":
        self.stop()
        break
```

## Error / Edge Cases

| Case | Behavior |
|------|----------|
| Dialog dismiss fails 3 times | Escalate to RecoveryStateMachine L1 |
| Recovery action itself fails | Log + try next level |
| Health check fires during active recovery | Ignore (debounce) |
| Multiple obstructions in one frame | Process by severity (dialog < freeze < crash) |
| Game is legitimately loading (black) | Not detected as crash (>30 frames threshold) |

## File Changes

### New files
- `recovery/__init__.py` — ~40 lines
- `recovery/detector.py` — ~120 lines
- `recovery/machine.py` — ~100 lines
- `recovery/scheduler.py` — ~60 lines
- `docs/2026-05-30-obstruction-recovery-design.md`

### Modified files
- `app.py` — +ObstructionEngine integration (~15 lines)
- `exceptions.py` — +recovery action for dialog block (~5 lines)
- `VERSION` — 5.4.0 → 5.5.0
- `CHANGELOG.md` — +v5.5.0 entry
