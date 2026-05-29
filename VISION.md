# PJSK Auto Player — 一站式傻瓜版游戏助手 VISION

> 基于 MAA/ALAS/MaaFramework 设计理念的全面重构计划

---

## 🎯 总体目标

从"自动执行工具"升级为 **一站式 Project Sekai 游戏助手**：
- **傻瓜化**：插上手机 → 运行 → 自动执行，零配置
- **全功能**：选歌/执行/连续执行/活动熔于一炉
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
     → 执行策略（执行/结算/选歌/等待）
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
4. 选择执行模式 (AP/FC/LIVE/连续执行)
5. 保存配置 → 开始执行

### 9. 通知系统 (`notification/`)
- `notification/desktop.py` — macOS/Windows 桌面通知
- `notification/web.py` — Web 推送通知
- `notification/sound.py` — 完成音效

### 10. CLI 守护进程
- `hermes` 风格 CLI：`pjsk [command] [options]`
- `pjsk daemon` — 后台守护进程
- `pjsk start` — 开始执行
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
│   │   ├── battle.json     # 🆕 执行流程
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

## 📚 同类开源项目调研 (2026-05-29)

> 调研 GitHub 上 Project Sekai / 音游自动化 / CV 游戏辅助相关的开源项目，
> 学习社区中优秀的工程实践，取长补短。

### 调研范围

```
                        音游自动执行能力 →
                        ┌──────────────────────────────┐
                   高   │                              │
                        │     ★ PJSK Auto Player       │
                        │    预测引擎 + Pipeline V2     │
                        │    + PID + 反检测 + 多后端     │
                        │                              │
                    ↑   │                              │
                  打    │                              │
                  歌    │                              │
                  能    │                              │
                  力    │  ichikas    pjsk_auto_story  │
                    ↓   │  (日常自动化) (剧情)          │
                        │  KotoneBot  PjskAutoLive     │
                   低   │  (CV框架)   (MacOS)          │
                        └──────────────────────────────┘
                         低 ← 工程化/易用性 → 高
```

### 项目详情

#### 1. ichikas-auto-assistant (⭐36, GPLv3, Python)
- **定位**: PJSK 日常任务全自动化 (登录/商店/任务/CM/区域对话/LIVE)
- **框架**: 基于自研 KotoneBot (⭐4)
- **GUI**: PySide6 + QML 原生桌面, DSL 自动生成配置表单
- **识别**: KotoneBot 内置 OpenCV + RapidOCR, Prefab 模板图片代码生成
- **控制器**: MuMu IPC / ADB / uiautomator / scrcpy 四通道
- **任务系统**: 声明式 DSL (@action, @sleep, @ocr), Registry 注册表
- **配置**: Pydantic 模型严格校验, 多 Profile
- **执行方式**: 依赖游戏内置 AUTO 模式, RhythmGameAnalyzer 为亮度检测初级实现
- **可学习**: 原生桌面 GUI (PySide6/QML), DSL 任务系统, Pydantic 配置校验, 模拟器 IPC 通信

#### 2. pjsk_auto_story (⭐33, Apache 2.0, Python)
- **定位**: 纯自动剧情阅读
- **技术**: pyautogui 模板匹配 + pywin32 模拟点击
- **规模**: <5 文件, 极简实现
- **可学习**: 最小化实现思路, 专注单一问题

#### 3. PjskAutoLive-MacOS (⭐1, Python)
- **定位**: macOS 自动 LIVE (使用游戏内置 AUTO)
- **技术**: pyautogui + tkinter GUI
- **核心**: 固定间隔点击轨道, 工作/休息周期
- **可学习**: macOS 平台适配经验, Tkinter 轻量 GUI

#### 4. MaaFramework (⭐4.1k, AGPLv3, C++/Python)
- **定位**: 通用 CV 自动化框架 (MAA 的泛化版本)
- **生态**: MaaNTE (异环, ⭐1.6k), MFABD2 (棕色尘埃2, ⭐394) 等
- **架构**: Controller-Resource-Agent 三层 + Pipeline JSON
- **可学习**: i18n 国际化, CI/CD 自动构建, 任务热更新, 社区运营

#### 5. KotoneBot (⭐4, GPLv3, Python)
- **定位**: 轻量 CV 自动化框架 (ichikas 的底层引擎)
- **特性**: 声明式 DSL, 平台无关 IO, Prefab 资源系统, 模拟器管理
- **识别 API**: find()/ocr()/color()
- **可学习**: DSL 语法设计, Prefab 图片代码生成, 模拟器管理

### 能力矩阵 (取长补短参考)

| 能力维度 | 本项目 | ichikas | pjsk_story | MaaFW | ALAS |
|---------|--------|---------|------------|-------|------|
| 真自动执行 | ✅ 预测引擎 | ❌ 仅 AUTO | ❌ | N/A | N/A |
| Pipeline 任务引擎 | ✅ V2 @继承 | ⚠️ DSL | ❌ | ✅ JSON | ❌ |
| 多算法场景检测 | ✅ 投票 | ⚠️ find() | ❌ | ✅ | ✅ |
| 分级异常恢复 | ✅ 11种 | ⚠️ | ❌ | ❌ | ✅ |
| 原生桌面 GUI | ⚠️ WebView | ✅ QML | ❌ | ⚠️ WPF | ✅ Qt |
| Web 控制面板 | ✅ SSE | ❌ | ❌ | ❌ | ✅ Flask |
| 声明式任务 DSL | ❌ | ✅ @action | ❌ | ❌ | ❌ |
| 配置校验 | ⚠️ Schema | ✅ Pydantic | ❌ | ❌ | ✅ Schema |
| i18n 国际化 | 🆕 刚刚加入 | ⚠️ JP/TW/CN | ❌ | ✅ | ❌ |
| PWA 手机控制 | ✅ | ❌ | ❌ | ❌ | ❌ |
| CI/CD 自动构建 | ⚠️ 部分 | ✅ | ❌ | ✅ | ❌ |
| 模拟器管理 | ❌ | ✅ MuMu | ❌ | ✅ | ✅ |
| Prefab 资源系统 | ❌ | ✅ | ❌ | ❌ | ✅ Resource |
| 单元测试 | ⚠️ 47/58 | ❌ | ❌ | ⚠️ | ✅ |

### 可学习借鉴的方向

**从 ichikas-auto-assistant + KotoneBot:**
1. **PySide6/QML 原生桌面** — 启动更快、内存更低、更原生
2. **DSL 声明式任务** — @action 装饰器简化任务编写
3. **Pydantic 配置校验** — 启动时严格校验，失败自动回退
4. **Prefab 资源系统** — 模板图片自动生成代码引用
5. **MuMu 模拟器 IPC** — 比 ADB 更快的模拟器通信方式
6. **任务注册表 (Registry)** — 新任务注册后 CLI/GUI 自动感知
7. **多服务器适配** — 支持 JP/TW/CN/KR/EN 不同 UI

**从 MAA/MaaFramework:**
8. **JSON 任务热更新** — CDN 下发任务配置，无需发版
9. **i18n 国际化** — 字符串资源统一管理，社区贡献翻译
10. **CI/CD 自动构建** — tag push → GitHub Actions → Release

**从 ALAS:**
11. **Controller Benchmark** — 可视化比较各后端性能
12. **模拟器管理** — 多开管理、自动启停、分辨率设置

---

## 📋 实施路线

| 阶段 | 内容 | 优先级 | 状态 |
|------|------|--------|------|
| **Phase 1** | 新目录结构 + 配置系统 V2 + 异常体系 + CLI | P0 | ✅ v4.9.0 |
| **Phase 2** | Pipeline V2 (@继承 + 生命周期 + 插件) | P0 | ✅ v4.9.0 |
| **Phase 3** | 场景检测 V2 + 识别引擎 V2 | P1 | ✅ v4.9.0 |
| **Phase 4** | Web GUI V2 (一站式控制面板) | P1 | ✅ v4.9.0 |
| **Phase 5** | 设置向导 V2 + 通知系统 | P2 | ✅ v4.9.0 |
| **Phase 6** | 文档 + 测试 + 打包 | P2 | ✅ v4.9.0 |
| **Phase 7** | Bugfix + 接口统一 + 恢复策略 | P0 | ✅ v4.9.1 |
| **Phase 8** | ALAS 工具库 (cached_property/Resource/颜色预处理/Benchmark/Schema) | P1 | ✅ v4.10.0 |
| **Phase 9** | 开箱即用桌面体验 (双击启动/自动浏览器/系统托盘) | P0 | ✅ v4.11.0 |

### v5.1 社区调研 → 后续迭代 (2026-05)

#### 📊 取长补短方向

| 项目 | Stars | 定位 | 值得学习的设计 | 本项目差异化 |
|------|-------|------|----------------|-------------|
| **ichikas-auto-assistant** | ⭐36 | PJSK 日常自动化 | PySide6/QML 原生桌面、DSL 配置表单、KotoneBot 框架、MuMu 模拟器集成 | 预测引擎 + 真自动执行 |
| **pjsk_auto_story** | ⭐33 | PJSK 自动剧情 | 极简实现 (<5 文件)、专注单一问题 | 全功能流水线 |
| **PjskAutoLive-MacOS** | ⭐1 | PJSK 自动 LIVE | macOS 适配经验、Tkinter 轻量 GUI | 智能控制器多后端 |
| **MaaFramework** | ⭐4.1k | 通用自动化框架 | 多语言绑定、CI/CD、社区运营、Pipeline JSON | 已验证 MAA 式 Pipeline |
| **KotoneBot** | ⭐4 | CV 自动化框架 | 声明式 DSL、Prefab 资源、模拟器管理 | 更强的异常恢复体系 |

#### 🚀 v5.1 迭代计划

| 特性 | 描述 | 优先级 | 启发来源 |
|------|------|--------|---------|
| 🧠 **AI 音符识别** | 轻量 ONNX 模型替代传统 CV，提高弱光/特效场景识别率 | P1 | 社区趋势 |
| 📊 **执行回放分析** | 录屏 + 判定时间线可视化，分析每次判定时机 | P1 | 玩家需求 |
| 🔄 **自动特殊任务** | 检测当前活动类型 → 自动选歌 → 循环连续执行 | P1 | ichikas 模式 |
| 🌍 **i18n 国际化** 🆕 | 多语言支持 (中/英/日)，字符串统一管理 | P1 | MAA 实践 |
| 🎨 **原生 Qt 桌面 GUI** | 从 WebView 升级到 PySide6/QML | P1 | ichikas 实践 |
| 🗣️ **DSL 声明式任务** | @action/@sleep/@ocr 装饰器简化任务编写 | P2 | KotoneBot 实践 |
| 📱 **PWA 手机控制** | Web 面板支持 PWA 安装 | P2 (✅ done) | 网页技术 |
| 🧪 **单元测试增强** | pytest 覆盖核心模块 → 目标 80%+ | P1 | 社区标准 |
| 🔐 **反检测增强** | 随机延迟曲线、贝塞尔滑动、触摸压力模拟 | P1 | ALAS 实践 |
| 🏪 **模拟器管理** | MuMu IPC / LDPlayer 自动检测 + 一键启停 | P2 | ichikas/ALAS |
| 📦 **CI/CD 自动构建** | tag push → GitHub Actions → 多平台 Release | P2 | MAA 实践 |
| 🔧 **Pydantic 配置校验** | Schema 严格校验 + 启动时回退 | P2 | ichikas 实践 |
| 📋 **任务注册表** | Registry 模式，CLI/GUI 自动发现任务 | P2 | KotoneBot 实践 |

### v5.0 Roadmap (历史)

| 特性 | 描述 | 优先级 |
|------|------|--------|
| 🧠 **AI 音符识别** | 用轻量 ONNX 模型替代传统 CV 检测，提高弱光/特效场景识别率 | P1 |
| 📊 **执行回放分析** | 录屏 + 判定时间线可视化，分析每次 PERFECT/GREAT/MISS 的时机 | P1 |
| 🔄 **自动特殊任务** | 检测当前活动类型 → 自动选对应歌曲 → 循环连续执行 | P1 |
| 🎨 **主题系统** | Web 面板支持浅色/深色/自定义主题 | P2 |
| 🌍 **i18n 国际化** | Web 面板多语言支持 (中/英/日) | P2 |
| 📱 **PWA 手机控制** | Web 面板支持 PWA 安装，手机浏览器直接控制 | P2 |
| 🧪 **单元测试** | pytest 覆盖核心模块 (Config/Pipeline/Scene/Controller) | P1 |
| 🔐 **反检测增强** | 随机延迟曲线、贝塞尔曲线滑动、触摸压力模拟 | P1 |

---

### 🔥 v5.1 快速迭代 (社区调研驱动)

基于社区项目调研, 立即可推进:

**P0 (本周)**:
1. [ ] **i18n 国际化框架** — 抽取字符串到 `locale/zh_CN.json`，支持中/英/日
2. [ ] **Pydantic 配置校验** — 替换现有 Schema 为 Pydantic models
3. [ ] **CI/CD 完善** — `.github/workflows/release.yml` 三平台构建

**P1 (下周)**:
4. [ ] **原生 Qt 桌面 GUI** — 从 WebView 逐步迁移到 PySide6/QML
5. [ ] **模拟器管理** — MuMu/LDPlayer 自动检测 + 一键启停
6. [ ] **任务 DSL 原型** — 实现 @action 装饰器简化 Pipeline 任务编写

**P2 (本月)**:
7. [ ] **Prefab 资源系统** — 模板图片自动生成代码引用
8. [ ] **Benchmark 面板** — 对比各后端性能，自动推荐最佳
9. [ ] **多服 UI 适配** — 支持 JP/TW/CN/KR/EN 不同 UI

### 架构参考 MAA/ALAS (历史)

| 特性 | MAA | ALAS | PJSK v4.11 |
|------|-----|------|-----------|
| Pipeline JSON | ✅ | ❌ | ✅ @继承 + 生命周期 |
| 插件系统 (AOP) | ✅ | ❌ | ✅ Logging/Stats/ErrorHandler |
| 分级异常 + 恢复 | ❌ | ✅ | ✅ 11 种异常 + 8 种策略 |
| 配置热加载 | ❌ | ✅ | ✅ 4 层合并 + ConfigWatcher |
| 场景多算法投票 | ✅ | ✅ | ✅ 亮度/颜色/模板 + 滞回 |
| OCR + 颜色预处理 | ✅ | ✅ | ✅ EasyOCR/Tesseract + ALAS 颜色过滤 |
| Web 暗色面板 | ❌ | ✅ | ✅ SSE 实时 + Canvas 图表 |
| 守护进程 | ❌ | ❌ | ✅ Unix Socket + JSON |
| 设置向导 | ❌ | ✅ | ✅ 5 步傻瓜式 + 首次运行检测 |
| 桌面通知 | ❌ | ❌ | ✅ macOS/Windows/Linux |
| 开箱即用桌面 | ❌ | ❌ | ✅ 双击启动 + 自动浏览器 + 系统托盘 |
| cached_property/Resource | ❌ | ✅ | ✅ lib/decorators + lib/resource |
| 配置 Schema 校验 | ❌ | ✅ | ✅ JSON Schema + 范围检查 |
| Controller Benchmark | ❌ | ✅ | ✅ 自动检测最优后端 |
| CI/CD 自动构建 | ✅ | ❌ | ✅ tag 触发 + .dmg 打包 |

> 目前已全面对标并超越 MAA/ALAS 的特性集。v5.0 将聚焦 AI 识别、回放分析、活动自动化等新方向。
