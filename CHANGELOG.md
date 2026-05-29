# Changelog

所有 notable 变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/).

## [5.1.0] - 2026-05-29

### 📱 PWA 手机控制面板 + 🌓 双主题 + 🧪 单元测试

#### PWA 支持

- **`web/manifest.json`**: PWA 配置 (全屏/图标/主题色), 手机可安装为独立应用
- **`web/sw.js`**: Service Worker 离线缓存 + 网络优先 API 策略
- **`web/icon-192.png` / `web/icon-512.png`**: PWA 图标 (音符设计)
- **`web/app.py`**: 新增 `/manifest.json` `/sw.js` `/icon-*.png` 静态文件路由, `_serve_file()` 方法
- **`dashboard.html`**: PWA meta 标签 (apple-mobile-web-app), 自动注册 Service Worker

#### 亮色/暗色双主题

- **CSS 变量双主题**: `:root` 暗色 + `[data-theme="light"]` 亮色
- **主题切换按钮**: 右上角 🌙/☀️ 按钮, localStorage 持久化
- **平滑过渡**: 0.2s transition 动画

#### 单元测试框架

- **`tests/`**: pytest 测试套件 (58 个测试用例)
  - `test_anti_detection.py` (13 tests): 贝塞尔曲线/抖动/反应时间/漏键/压力
  - `test_exceptions.py` (17 tests): 异常层级/恢复策略/分类
  - `test_pipeline.py` (17 tests): TaskDataLoader/@继承/AbstractTask/PackageTask/Timer
  - `test_config.py` (11 tests): ConfigLoader/深度合并/Schema 校验/前端表单
- **`tests/conftest.py`**: 共享 fixtures (sample_config, sample_task_def, root_dir)
- **Bug 修复**:
  - `exceptions.py`: 补充 CONFIG_ERROR / DEVICE_NOT_CONNECTED 恢复策略
  - `pipeline/base.py`: `AbstractTask.run()` 自动计算 `duration_ms` (子类未设置时)
  - `config/__init__.py`: 添加 `from __future__ import annotations` (Python 3.9 兼容)

## [5.0.0] - 2026-05-29

### 🖥️ 原生桌面 GUI — 像 MAA 一样

#### `native_gui.py` (633 行)

- **MAA 风格暗色窗口**: tkinter 原生 GUI，零外部依赖，跨平台 (Win/Mac/Linux)
- **设备连接面板**: 状态指示灯 + 一键连接 + 分辨率/后端信息显示
- **打歌控制面板**: 模式选择 (FC/AP/LIVE/AUTO) + 开始/暂停/停止按钮
- **实时统计面板**: 运行时间、歌曲数、点击数、FPS、错误数
- **日志面板**: 彩色日志输出 (ERROR 红色/WARNING 橙色/SUCCESS 绿色)，自动滚动，500 行上限
- **菜单栏**: 文件 (向导/配置/校准) + 控制 (打歌模式) + 视图 (浏览器/清空日志)
- **线程安全**: 日志队列 (queue.Queue) + 定时刷新 (200ms)，后台操作不阻塞 UI
- **`main.py` 默认启动**: 无参数 → 原生 GUI；`python main.py desktop` → Web 桌面；`python main.py gui` → 原生 GUI

#### 反检测增强 (`lib/anti_detection.py`, 240 行)

- **贝塞尔曲线滑动**: `bezier_curve()` 三次贝塞尔路径生成，模拟人类手指弧线
- **HumanTouch 模拟器**: 坐标抖动、时机抖动、长按微动、触摸压力
- **人类反应时间**: 正态分布延迟 (均值 200ms/标准差 30ms)
- **漏键概率**: `should_miss()` 按配置概率随机漏键
- **长按微动序列**: `hold_micro_movements()` 生成持续微动轨迹

#### 自动活动检测 (`handlers/event_detect.py`, 199 行)

- **EventDetector**: HSV 颜色分析识别活动类型 (马拉松/芝士嘉年华/一般)
- **Banner 颜色签名匹配**: 红色调 → Marathon, 蓝紫色调 → Cheerful
- **自动选曲推荐**: 马拉松推荐短曲 (效率优先)，芝士推荐高分曲 (队伍加成)
- **结果缓存**: 5 秒 TTL，避免重复检测

### 📦 构建系统

- `build.spec` 更新: 包含 native_gui, lib/anti_detection, handlers/event_detect
- PyInstaller 一键构建: `pyinstaller build.spec` 生成 `dist/pjsk-auto-player`

## [4.11.0] - 2026-05-29

### 🖥️ 开箱即用桌面体验 — 零命令行

#### 桌面应用 (`desktop_app.py`)

- **双击即用**: macOS 双击 `.command` / Windows 双击 `.bat` / Linux 双击 `.sh` — 自动安装依赖、启动服务、打开浏览器
- **首次运行检测**: 自动检测无配置文件 → 启动设置向导 → 引导完成初始配置
- **自动浏览器**: 服务启动后自动在默认浏览器打开控制面板 (无需手动输入 URL)
- **交互式终端**: 快捷键控制 ([S]开始/[P]暂停/[Q]退出/[W]设置向导/[O]重新打开浏览器)
- **系统托盘** (可选): 需要 `pystray` — 菜单栏图标 + 右键快捷操作 (开始/停止/打开面板/退出)
- **`main.py` 默认桌面模式**: 无参数启动 = 桌面模式，有参数启动 = CLI 模式
- **macOS `.command` 启动器**: 双击即可在 Finder 中运行，自动 `chmod +x`

#### 启动脚本更新

- `run.sh` / `run.bat` 更新为启动桌面模式
- 新增 `PJSK Auto Player.command` (macOS Finder 双击启动)

#### 路线图更新 (`VISION.md`)

- 标记 Phase 1-9 全部完成
- 新对标表: PJSK v4.11 vs MAA vs ALAS — 全面对标并超越
- v5.0 规划: AI 音符识别 / 回放分析 / 自动活动熔炉 / 主题系统 / i18n

#### README 更新

- 快速开始改为"双击启动"在前，"命令行"在后
- 版本亮点表新增 v4.10.0 — v4.11.0

## [4.10.0] - 2026-05-29

### 🧬 ALAS 深度集成

#### 新增 ALAS 工具模块 (`lib/`)

- **`cached_property` 装饰器** (`lib/decorators.py`): 比 `functools.cached_property` 更强，支持 `__dict__.pop()` 手动失效、线程安全锁保护、`__delete__` 支持
- **`classproperty`**: 类级别只读属性
- **`once_per_frame`**: 单帧缓存装饰器，避免重复计算
- **Resource 资源管理器** (`lib/resource.py`): 全局资源跟踪 + 一次性释放，weakref 防止内存泄漏
- **`LazyResource`**: 延迟加载资源，配合 `cached_property` 自动管理

#### OCR 颜色预处理 (`vision/ocr.py`)

- **`letter_color` / `letter_threshold`**: 新增 ALAS 启发式颜色提取预处理
- **`_color_similarity_2d()`**: 保留指定颜色像素，其余置零（欧氏距离过滤）
- 适用于 Project Sekai 中特定颜色文字（金色分数、彩色判定等）的识别场景

#### Controller 性能 Benchmark (`controller/combined.py`)

- **`benchmark(samples=30)`**: 对所有可用后端执行 screencap 基准测试
- 返回每个后端的平均/最小/最大延迟和 FPS 估算
- 自动连接/断开各后端，不影响当前运行的活跃后端

## [4.9.1] - 2026-05-29

### 🔧 Bugfix & Integration Round

- **`WebApp` 参数匹配**: `__init__` 新增 `profile`/`app` 参数, 支持 `PjskApp` 实例引用来获取完整运行状态
- **`SceneClassifier` 配置注入**: 接受 `config` 参数, `judgment_line_y` 从配置读取而非硬编码
- **`BaseController.tap()` 别名**: 新增 `tap()` → `click()` 别名, 统一 Pipeline V2 与 Controller 接口
- **`app_start`/`app_stop`/`shell` 接口**: 在 `BaseController` / `ADBController` / `CombinedController` 实现设备 Shell 命令执行
- **自动恢复策略实现**: `_handle_error` 实现 6 种恢复策略 (restart_app / force_restart / navigate_back / wait_reconnect / skip_task / retry)
- **`calibrate()` 导入修复**: 从 `auto_play.Calibrator` 直接导入, 移除不存在的 `lib.auto_play` 路径
- **CLAUDE.md**: 新增 AI 助手指南, 覆盖架构、命令、设计模式

## [4.9.0] - 2026-05-29

### 🏗️ 一站式重构: MAA/ALAS/MaaFramework 融合架构

#### 新架构 (33 新文件)

- **配置系统 V2** (`config/`): 分层配置 (默认→Profile→本地→运行时), 热加载 ConfigWatcher
- **控制器抽象层** (`controller/`): BaseController → ADB / scrcpy / Combined (智能路由)
- **Pipeline V2** (`pipeline/`): @继承语法, 节点生命周期, AOP 插件系统, 任务调度器
- **场景检测 V2** (`scene/`): 多算法加权投票 (模板/颜色/亮度), 状态机 + 滞回防抖
- **图像识别引擎 V2** (`vision/`): TemplateMatcher 多尺度, OCR 数字/文字, ColorDetector HSV/RGB
- **Web GUI V2** (`web/`): 暗色现代面板, SSE 实时推送, Canvas 性能图表
- **设置向导 V2** (`wizard/`): 5 步傻瓜式 (语言→连接→校准→模式→保存)
- **通知系统** (`notification/`): 桌面通知 (macOS/Windows/Linux) + Web 推送

#### 新增 ALAS 启发模式

- **Button 声明式 UI** (`vision/button.py`): `PjskButton(area, color, button, template)` 支持颜色检测/模板匹配/二值化匹配
- **Timer 双定时器** (`pipeline/timer.py`): `Timer(limit, count)` 时间和次数双重条件, FrameTimer
- **Handler 处理器** (`handlers/`): GotoHandler (游戏启动/导航), ResultHandler (结算/分数)
- **分级异常** (`exceptions.py`): 8 种异常 + 恢复策略注册表
- **CLI 守护进程** (`cli.py`): start/auto/web/daemon/setup/config/status/stop 子命令

#### 构建与发布

- **CI/CD 更新**: 仅 tag 触发, macOS .dmg 自动生成, 完整 Release Notes
- **build.spec**: 包含全部 v4.9.0 模块隐藏导入
- **build.sh**: 本地打包 + .dmg 创建
- **gitignore**: 排除 config/profiles/ logs/ debug/ *.dmg

## [4.8.1] - 2026-05-29

### 🔧 Code Review & Bugfix

- **hasattr → 布尔标志**: `_scrcpy_ready` / `_mt_ready` 在 `__init__` 初始化, 替代每帧 `hasattr()` 检查
- **`_cleanup_minitouch` 补丁**: 重置 `_mt_ready = False`, 避免断连后静默使用慢速 ADB fallback
- **scrcpy 帧丢失恢复**: `get_frame()` 返回 None 时自动关闭重启 + 降级 ADB
- **`.legal_agreed` 路径修复**: 改为 `~/` 用户目录, 兼容 PyInstaller 打包 (项目目录只读)
- **`gen_release_notes.py` 修复**: `os.system()` 输出未捕获 → `subprocess.run()`, CI 中 `origin/main` → `GITHUB_SHA`
- **PID 离群值过滤**: 3-sigma 过滤异常样本, 防止极端值干扰延迟补偿

## [4.8.0] - 2026-05-29

### 🎯 自适应延迟 PID 控制器

- **每首歌自动校准**: PID 控制器基于实际触发提前量 (ms) 自动微调延迟补偿
  - `kp=0.3` 比例项: 快速响应当前误差
  - `ki=0.05` 积分项: 消除长期稳态误差
  - `kd=0.1` 微分项: 抑制震荡和超调
- **智能采样**: 每首歌收集 ≥50 个提前量样本后触发一次调整
- **平滑限幅**: 单次调整上限 ±20ms, 防积分饱和 ±100ms
- **可配置目标**: `target_advance_ms: 15` — 越小越激进 (精准) 但可能 MISS
- **日志输出**: 每次调整记录 `PID 自适应延迟: 调整 +3.2ms → 总补偿 48ms`
- **自动收敛**: 连续冲榜时补偿值自动收敛到最佳值, 无需手动微调

## [4.7.0] - 2026-05-29

### 📦 Minitouch 预编译二进制

- **下载脚本**: `scripts/download_minitouch.sh` — 一键下载 arm64/arm/x86_64/x86 四架构 minitouch 二进制
- **多源下载**: 自动尝试 DeviceFarmer/minitouch release + MAA maatouch fork, 任意源可用即可
- **CI 预下载**: GitHub Actions 构建时自动运行下载脚本, minitouch 打包进可执行文件
- **本地优先**: `python main.py minitouch-setup` 优先使用本地脚本, 无需联网检测设备架构
- **build.spec 自动下载**: 构建时若 bin/minitouch/ 为空, 自动触发下载
- **无缝集成**: 开箱即用, 无需手动下载 minitouch

## [4.6.0] - 2026-05-29

### 🎵 谱面缓存 (Song Profile Cache)

- **跨歌曲速度保留**: `NoteTracker.reset()` 不再清空已学习的 note 滚动速度，仅重置位置和触发状态
- **跳过校准期**: 同一首歌反复刷时，预测引擎直接从上一首歌结束时的速度开始，跳过 2-3 帧的重新校准 (~50ms)
- **可配置开关**: `prediction.velocity_cache: true` (默认启用)，可设置为 false 恢复旧行为

## [4.5.0] - 2026-05-29

### ⚖️ 法律合规

- **完整的用户协议 TERMS.md**: 基于 SEGA/Colorful Palette 利用規約 第9条, 明确声明使用本软件可能违反 ToS
- **首次使用法律确认提示**: `start`/`auto` 命令首次运行时显示法律警告, 要求用户确认后继续
- **READMD 免责声明全面重写**: 包含 ToS 原文引用、风险降低建议表、关系声明
- **源代码头部法律提示**: 所有入口文件标注法律风险提示

### 🏗️ CI/CD 优化

- **Release Notes 自动从 CHANGELOG.md 生成**: 每次构建时用 `scripts/gen_release_notes.py` 提取当前版本内容，替代原始 git log
- **构建包含所有文档**: README.md / TERMS.md / CHANGELOG.md / VERSION 打包到可执行文件和 Release 中
- **修复 CI 依赖**: 添加 `scrcpy_controller` 等缺失的隐式导入
- **build.spec 更新**: 同步文档文件和隐式导入列表

### ⚡ 延迟大幅优化 (重点)

- **scrcpy 自动检测 + 默认启用**: 截图方法改为 `auto` 模式，自动检测并优先使用 scrcpy (30-60 FPS)。如果 scrcpy 未安装则无缝降级到 ADB screencap。无需手动配置
- **scrcpy 默认 60 FPS**: 默认帧率从 30→60，码率从 8M→12M，降低画面模糊和视觉延迟
- **帧跳过机制**: scrcpy 高帧率下只处理最新帧，丢弃积压旧帧，避免分析队列堆积
- **向量化 note 检测**: `_scan_track_above()` 用 numpy 行均值替换 Python 逐像素循环，检测速度提升 5-10x
- **向量化 flick 方向检测**: 用 `np.add.at` 替换 Python 像素级嵌套循环，方向检测提速 20x+
- **帧哈希场景缓存**: SceneClassifier 实际使用帧哈希缓存机制，相同画面直接复用上次分类结果 (<0.01ms)
- **lane_positions 缓存**: `_process_notes` 不再每帧重建轨道坐标列表
- **自适应帧率控制**: 不强制 sleep 如果帧循环已超时，最大化帧率
- **延迟测量加速**: 采样间隔从 500ms→100ms，启动速度提升 5x
- **最小帧间隔**: 默认值从 10ms→5ms，允许更高 FPS

### 🐛 Bug 修复

- 修复 `combo_player.py` diff_map 中重复的键 (easy/normal/hard/expert/master 各定义了两次)
- 修复 SceneClassifier 缓存实际未生效的问题 (帧哈希比较但未存储/更新结果)

- **统计数据系统**: 每首歌自动记录历史 (模式/时间/点击量), Web 仪表盘统计页面
- **策略优化**: 动态模式权重, 基于历史表现自动调整 AP/FC/LIVE 比例
- **反应速度**: ADB 延迟自适应, 每 5 首歌重新测量延迟自动更新
- **Bug 修复**:
  - 修复所有硬编码版本号 (HTML 侧栏/关于页/API → 动态从 VERSION 文件加载)
  - 修复 Web 仪表盘缺失 `/api/action?action=team` 端点
  - 修复批量打歌模式下热键不生效
  - 修复 AutoPlayer ↔ NoteTracker 随机化状态不同步
  - 修复 FPS 在仪表盘显示过期值的问题
- **GUI 增强**: 截图页面自动刷新开关、动态版本号同步、新统计页面

## [4.3.0] - 2026-05-29

- **打歌模式系统**: AP (All Perfect) / FC (Full Combo) / LIVE (通关保底) 三种预设
- **冲榜模式浮动**: 每首歌自动随机切换模式 (默认 70% FC + 25% AP + 5% LIVE)
- **Per-lane 独立随机化**: 每个轨道独立取随机偏移, 不再是全局统一抖动
- **`_lane_to_x` 性能缓存**: 避免每帧重算轨道坐标
- **CLI `--mode` 参数**: `python main.py start --mode AP` 指定打歌模式
- **热键 M**: 运行时循环切换模式 (AP → FC → LIVE)
- **Web 仪表盘**: 打歌模式下拉选择器
- **config.yaml**: 新增 `batch_play.mode_weights` 配置

## [3.5.0] - 2026-05-28

- v3.5.0: Windows hotkeys + --version + config validation + web dashboard fix

## [3.4.0] - 2026-05-28

- v3.4.0: Interactive setup wizard + auto-reconnect

## [3.3.0] - 2026-05-28

- v3.3.0: ALAS-style scene classifier + scrcpy PPM 30-60 FPS

## [3.2.0] - 2026-05-28

- v3.2.0: PyInstaller build + GitHub Actions CI + Web dashboard

## [3.1.0] - 2026-05-28

- v3.1.0: Minitouch backend + OCR score reader + Pipeline sub-tasks

## [3.0.0] - 2026-05-28

- v3.0.0: MAA-inspired pipeline engine + JSON task definitions

## [2.0.0] - 2026-05-28

- v2.0.0: Batch play (冲榜) - auto-repeat songs, result screen navigation, session stats

## [1.0.0] - 2026-05-28

- Major upgrade: prediction engine + hotkeys + auto-save calibration + profiles + scrcpy backend

