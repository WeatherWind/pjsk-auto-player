# PJSK Auto Player — 一站式傻瓜版游戏助手 VISION

> 基于 MAA/ALAS/MaaFramework 设计理念的全面重构计划

---

## 🎯 总体目标

从"自动打歌工具"升级为 **一站式 Project Sekai 游戏助手**：
- **傻瓜化**：插上手机 → 运行 → 自动打歌，零配置
- **全功能**：选歌/打歌/冲榜/活动熔于一炉
- **可视化**：现代 Web 控制面板，实时监控一切
- **可靠**：分级异常处理 + 自动恢复，7x24 不崩溃

---

## 📐 架构蓝图

```
┌─────────────────────────────────────────────────┐
│                 前端层 (Web GUI)                   │
│  现代暗色仪表盘 · 实时帧预览 · 配置编辑 · 统计     │
├─────────────────────────────────────────────────┤
│                 CLI / 守护进程层                    │
│  daemon 模式 · 命令行操控 · JSON 输出 · 热键      │
├─────────────────────────────────────────────────┤
│                Agent 扩展层 (Python)               │
│  CustomRecognition · CustomAction · AI 模型      │
├─────────────────────────────────────────────────┤
│              任务调度层 (Pipeline V2)              │
│  任务继承 (@语法) · 生命周期钩子 · 插件系统        │
├──────────┬──────────┬──────────┬────────────────┤
│ 场景检测   │ 识别引擎  │ 触控引擎   │ 状态管理      │
│ SceneCls. │ Vision   │ Controller│ Status        │
│ (多算法)   │ (OCR/TM  │ (ADB/     │ (运行时状态    │
│           │  /Color) │ scrcpy/   │  /统计/计时)  │
│           │          │ minitouch)│              │
├──────────┴──────────┴──────────┴────────────────┤
│                  配置层 (Config V2)               │
│  分层: 默认 < profile < 运行时 · 热加载 · YAML    │
├─────────────────────────────────────────────────┤
│                  异常体系 (Exception)              │
│  GameStuckError · GameBugError · 自动恢复 · 截图  │
└─────────────────────────────────────────────────┘
```

---

## 🧱 模块设计

### 1. 配置系统 V2 (`config/`)
- `config/default.yaml` — 默认配置（内置，只读）
- `config/profiles/<name>.yaml` — 用户配置档案
- `config/local.yaml` — 本地覆盖（不提交 git）
- `config/auto_detect.yaml` — 自动检测结果缓存
- **热加载**：修改文件后自动重载（`ConfigWatcher` 模式）
- **分层覆盖**：默认 → profile → 局部 → 运行时

### 2. Pipeline V2 (`pipeline/`)
从当前 `pipeline.py` 升级为完整模块：
- `pipeline/base.py` — AbstractTask / PackageTask / InterfaceTask
- `pipeline/process.py` — ProcessTask 执行引擎
- `pipeline/plugins.py` — AbstractTaskPlugin + 内置插件
- `pipeline/task_data.py` — JSON 加载 + @继承解析
- `pipeline/scheduler.py` — 任务调度器（按时间/状态）
- `pipeline/node.py` — 节点生命周期（pre_wait → pre_delay → action → post_wait → post_delay）

**核心改进**：
- **@任务继承**：`"ClickOK@ClickSelf"` 复用父任务配置
- **生命周期钩子**：每个节点自动执行 `pre_wait_freezes → pre_delay → action → repeat? → post_wait_freezes → post_delay`
- **插件系统**：AOP 风格在 run() 前后自动调用
- **子任务并行**：主任务间隙并行扫描弹窗/通知

### 3. 识别引擎 V2 (`vision/`)
- `vision/matcher.py` — OpenCV 模板匹配
- `vision/ocr.py` — OCR 识别（数字/文字）
- `vision/color.py` — 颜色检测
- `vision/scene.py` — 场景分类器（多算法投票）
- `vision/nonote.py` — note 检测（判定线区域分析）

### 4. 场景检测 V2 (`scene/`)
ALAS 启发式场景分类，改为多算法投票：
- `scene/classifier.py` — 主分类器
- `scene/states.py` — 场景状态机定义
- `scene/transitions.py` — 场景转换检测

**检测流程**：
```
截图 → 多算法并行检测（模板/颜色/亮度/OCR）
     → 加权投票 → 最佳场景 → 状态机转换
     → 执行策略（打歌/结算/选歌/等待）
```

### 5. 异常体系 (`exceptions.py`)
ALAS 式分级异常 + 自动恢复：
```python
class PjskError(Exception): pass           # 基类
class GameStuckError(PjskError): pass       # 游戏卡住 → 重启游戏
class GameBugError(PjskError): pass         # 游戏异常 → 杀进程重启
class GamePageUnknownError(PjskError): pass # 未知页面 → 尝试返回
class ConnectionLostError(PjskError): pass  # 连接断开 → 重连
class TooManyClickError(PjskError): pass    # 防死循环保护
class TaskTimeoutError(PjskError): pass     # 任务超时
```

### 6. 控制器 V2 (`controller/`)
抽象接口 + 多实现：
- `controller/base.py` — `BaseController` 抽象类
- `controller/adb.py` — ADB 截图 + 点击
- `controller/scrcpy.py` — scrcpy 视频流 + minitouch
- `controller/combined.py` — 智能路由（自动选择最优后端）
- `controller/keyboard.py` — 模拟键盘 (Win32/macOS)

### 7. Web GUI V2 (`web/`)
现代单页 Web 控制面板：
- 暗色主题（仿 MAA/ALAS 风格）
- 实时帧预览（WebSocket 推送最新帧）
- 配置编辑（在线修改 config.yaml）
- 任务状态面板（当前步骤/进度/日志）
- 性能统计（FPS/延迟/命中率 图表）
- 截图浏览器（最近截图/调试截图）
- 日志查看器（颜色区分级别）
- 热键绑定配置
- 一键盘启动/暂停/停止

### 8. 设置向导 V2 (`wizard/`)
傻瓜式首次运行体验：
1. 选择语言
2. 连接手机 (ADB 自动检测)
3. 屏幕校准（自动检测分辨率/判定线位置）
4. 选择打歌模式 (AP/FC/LIVE/冲榜)
5. 保存配置 → 开始打歌

### 9. 通知系统 (`notification/`)
- `notification/desktop.py` — macOS/Windows 桌面通知
- `notification/web.py` — Web 推送通知
- `notification/sound.py` — 完成音效

### 10. CLI 守护进程
- `hermes` 风格 CLI：`pjsk [command] [options]`
- `pjsk daemon` — 后台守护进程
- `pjsk start` — 开始打歌
- `pjsk stop` — 停止
- `pjsk status` — 查看状态
- `pjsk config` — 配置管理

---

## 📂 新项目结构

```
pjsk-auto-player/
├── main.py                 # 🆕 轻量入口
├── VISION.md               # 🆕 本文档
├── config/
│   ├── __init__.py         # 🆕 ConfigManager
│   ├── default.yaml        # 🆕 默认配置
│   └── loader.py           # 🆕 YAML 加载 + 热加载
├── pipeline/
│   ├── __init__.py
│   ├── base.py             # 🆕 AbstractTask / PackageTask
│   ├── process.py          # 🆕 ProcessTask 执行引擎
│   ├── node.py             # 🆕 节点生命周期
│   ├── plugins.py          # 🆕 插件系统
│   ├── task_data.py        # 🆕 JSON 加载 + @继承
│   └── scheduler.py        # 🆕 任务调度器
├── vision/
│   ├── __init__.py
│   ├── matcher.py          # 🆕 模板匹配
│   ├── ocr.py              # 🆕 OCR 识别
│   ├── color.py            # 🆕 颜色检测
│   ├── scene.py            # 🆕 场景分类（多算法）
│   └── nonote.py           # 🆕 Note 检测
├── scene/
│   ├── __init__.py
│   ├── classifier.py       # 🆕 场景分类器
│   ├── states.py           # 🆕 场景定义
│   └── transitions.py      # 🆕 状态转换
├── controller/
│   ├── __init__.py
│   ├── base.py             # 🆕 BaseController
│   ├── adb.py              # 🆕 ADB 控制器
│   ├── scrcpy.py           # 🆕 scrcpy 控制器
│   ├── combined.py         # 🆕 智能路由
│   └── keyboard.py         # 🆕 键盘模拟
├── web/
│   ├── __init__.py
│   ├── app.py              # 🆕 Web 主应用
│   ├── dashboard.html      # 🆕 现代仪表盘
│   └── websocket.py        # 🆕 实时推送
├── wizard/
│   ├── __init__.py
│   └── setup.py            # 🆕 设置向导
├── notification/
│   ├── __init__.py
│   ├── desktop.py          # 🆕 桌面通知
│   └── web.py              # 🆕 Web 推送
├── resource/
│   ├── tasks/
│   │   ├── battle.json     # 🆕 打歌流程
│   │   ├── menu.json       # 🆕 菜单操作
│   │   └── event.json      # 🆕 活动流程
│   └── templates/          # 🆕 场景截图模板
├── exceptions.py           # 🆕 异常体系
├── app.py                  # 🆕 应用主类 (Manager)
├── cli.py                  # 🆕 CLI 入口
├── lib/                    # 📦 原代码保留
│   ├── adb_controller.py
│   ├── auto_play.py
│   ├── capture_optimizer.py
│   ├── combo_player.py
│   ├── ocr_reader.py
│   ├── scene_classifier.py
│   ├── screen_analyzer.py
│   └── ...
├── config.yaml             # 📦 保留兼容
├── requirements.txt
└── README.md
```

---

## 📋 实施路线

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| **Phase 1** | 新目录结构 + 配置系统 V2 + 异常体系 + CLI | P0 |
| **Phase 2** | Pipeline V2 (@继承 + 生命周期 + 插件) | P0 |
| **Phase 3** | 场景检测 V2 + 识别引擎 V2 | P1 |
| **Phase 4** | Web GUI V2 (一站式控制面板) | P1 |
| **Phase 5** | 设置向导 V2 + 通知系统 | P2 |
| **Phase 6** | 文档 + 测试 + 打包 | P2 |

---

## ⚡ 与 MAA/ALAS 对标

| 特性 | MAA | ALAS | 当前 PJSK | PJSK V2 |
|------|-----|------|-----------|---------|
| Pipeline JSON | ✅ | ❌ | ✅ 基础 | ✅ 完整 @继承 |
| 插件系统 | ✅ | ❌ | ❌ | ✅ |
| 分级异常 | ❌ | ✅ | ❌ | ✅ |
| 配置热加载 | ❌ | ✅ | ❌ | ✅ |
| 场景分类 | ✅ | ✅ | ✅ 基础 | ✅ 多算法投票 |
| OCR | ✅ | ✅ | ✅ 基础 | ✅ 数字/文字 |
| Web GUI | ❌ | ✅ | ✅ 基础 | ✅ 现代暗色 |
| 守护进程 | ❌ | ❌ | ❌ | ✅ |
| 设置向导 | ❌ | ✅ | ✅ | ✅ 完善 |
| 桌面通知 | ❌ | ❌ | ❌ | ✅ |
| 自动更新 | ✅ | ❌ | ✅ CI | ✅ 内置检查 |
| 多平台 | ❌ | ❌ | ❌ | ✅ ADB/Win32 |

> 目标：吸收三者精华，打造 Project Sekai 领域最好的自动化助手。
