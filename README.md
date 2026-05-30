# PJSK Auto Player — CV 自动化研究工具

[![zh-CN](https://img.shields.io/badge/README-中文-blue)](README.md)
[![en](https://img.shields.io/badge/README-English-lightgrey)](README.en.md)
[![ja](https://img.shields.io/badge/README-日本語-lightgrey)](README.ja.md)

> 基于 ADB + OpenCV 的计算机视觉与自动化控制研究项目。
> 参考 MAA (MaaAssistantArknights) + ALAS (AzurLaneAutoScript) + MaaFramework 架构设计。

---

## 🚀 快速开始 — 开箱即用

### 方式 1：双击启动 (推荐)

| 系统 | 操作 |
|------|------|
| **macOS** | 双击 `PJSK Auto Player.command` |
| **Windows** | 双击 `run.bat` |
| **Linux** | 双击 `run.sh` 或终端运行 `./run.sh` |

首次运行会自动安装依赖并打开设置向导。之后每次双击直接启动原生桌面 GUI。

### 方式 2：命令行

```bash
python main.py              # 🖥️ 原生桌面 GUI (默认)
python main.py desktop      # 🌐 桌面模式 — 自动打开浏览器控制面板
python main.py start        # 单次执行
python main.py auto         # 连续执行（自动处理结算与重试）
python main.py setup        # 设置向导
```

---

## ✨ 版本亮点

| 版本 | 特性 |
|------|------|
| **v5.7.1** | 🐛 4 个关键修复 — OCR 安全漏洞 + 移除额外清除 + 高斯分布补全 + 代码清理 |
| **v5.7.0** | ⚡ 零分配帧缓冲 — scrcpy screencap 消除 per-frame malloc，CPU 分配开销降为 0 |
| **v5.6.0** | 🔐 操作行为多样性 — Session Fingerprint + 高斯抖动 + SAFE/PRECISION 模式 |
| **v5.5.0** | 🛡️ 阻塞检测与自动恢复系统 — 5 级恢复状态机 + 健康心跳 + 弹窗处理 |
| **v5.4.0** | ⚡ 性能优化 — 主循环热路径 + 缓存复用 + 帧差跳过 + termios 缓存 |
| **v5.3.0** | 🎮 游戏设置自动读取 + 多服适配 (JP/TW/CN/KR/EN) + 自动校准 |
| **v5.2.0** | ⚡ 异步截屏 + Raw ADB + 批量触摸 — 端到端延迟大幅降低 |
| **v5.1.0** | 🌍 i18n 国际化 (中/英/日) + 📱 PWA 手机控制面板 + 🌓 双主题 + 🧪 单元测试 |
| **v5.0.0** | 🖥️ MAA 风格原生桌面 GUI + 操作自然化 + 活动类型识别 |
| **v4.11.0** | 🖥️ 开箱即用: 桌面应用 + 自动打开浏览器 + 首次运行向导 + 系统托盘 |
| **v4.10.0** | 🧬 ALAS 深度集成: cached_property/Resource/颜色预处理/Benchmark/配置 Schema |
| **v4.9.0** | 🏗️ MAA/ALAS 融合架构: Pipeline V2 + 场景多算法投票 + Web 暗色面板 + 分级异常 + 守护进程 |

---

## 🔥 主要特性

### 🎯 预测引擎
基于时序预测的触发系统：检测判定区域上方目标 → 追踪移动速度 → 计算到达时间 → 准时触发。
补偿 ADB 链路的 100-300ms 传输延迟，变被动响应为主动预测。

### ⚡ 屏幕捕获提速 (v5.2.0)
- **异步截屏**: producer-consumer 模式，后台线程持续截屏，主线程零延迟取帧
- **Raw ADB**: `adb exec-out screencap` 原始 RGBA 格式，比 PNG 快 2-3x
- **智能降级**: scrcpy → raw ADB → PNG ADB 自动选最快可用后端

### ⚡ 批量触摸 (v5.2.0)
- **合并发送**: `queue_tap()` + `flush_touch_batch()` — 一帧内所有触摸合并为一次 `adb shell` 调用
- **减少开销**: adb 进程启动次数减少 3-10x

### 🧠 Pipeline V2 引擎 (参考 MAA 设计)
- **JSON 任务配置驱动** — 识别→动作→跳转的声明式流水线
- **@任务继承** — `"ClickOK@ClickSelf"` 复用父任务配置，只覆盖差异
- **节点生命周期** — `pre_wait_freezes → pre_delay → action → post_wait_freezes → post_delay`
- **插件系统** — AOP 风格，在任务前后自动注入日志/统计/错误处理
- **子任务并行** — 主任务间隙并行扫描弹窗/通知

### 🖥️ 原生桌面 GUI (v5.0.0)
- **MAA 风格暗色窗口**: tkinter 原生 GUI，零外部依赖，跨平台
- **设备连接面板**: 状态指示灯 + 一键连接 + 实时统计
- **执行控制面板**: 模式选择 (FC/AP/LIVE/AUTO) + 开始/暂停/停止
- **菜单栏**: 向导/配置/校准/模式切换/清空日志

### 🌐 Web 控制面板 V2
现代暗色主题，零外部依赖的单页应用：
- 实时帧预览 (SSE 推送)
- 任务状态监控
- FPS/点击量实时折线图
- 配置在线编辑 + 日志查看器 + 截图浏览器
- 📱 **PWA 支持** (v5.1.0): 手机可安装为独立应用，Service Worker 离线缓存
- 🌓 **亮色/暗色双主题** (v5.1.0): 一键切换，localStorage 持久化

### 🌍 国际化 i18n (v5.1.0)
- 三种语言: 简体中文 / English / 日本語
- 语言自动检测，配置持久化

### 🎲 操作随机化
模拟人工操作特征：贝塞尔曲线滑动、时机抖动 ±15ms、坐标偏移 ±5px、随机漏键 0.1%、长按微动序列

### 🎮 执行策略
- **AP** — 高精度触发策略
- **FC** — 平衡稳定性策略
- **LIVE** — 基础通过策略
- **混合** — 智能切换策略 (70% FC + 25% AP + 5% LIVE)

### ⚡ PID 自适应延迟
每次执行结束后基于实际触发提前量自动微调延迟补偿，逐步收敛到最佳值。

### ⚡ 性能优化 (v5.4.0)

#### 主循环热路径

- **任务缓存复用**: `ProcessTask` 按 `task_name` 复用实例，消除 hot-path 中的每帧对象分配
- **帧差跳过**: `CaptureOptimizer` 集成 — 画面无变化时直接跳过 Pipeline 处理
  - 菜单/加载/结算等静态场景下可跳过 90%+ 的处理帧
- **模块级导入**: 所有核心模块在文件顶部一次性导入，消除 hot-path 中的 import 系统调用

#### scrcpy PPM buffer 保护

添加 10MB buffer cap，防止主线程消费慢于 scrcpy 产生帧时内存无限增长。

#### auto_play.py 热路径

- `try/except KeyError` 替代 `dict.get()` 免去双次 dict 查找
- 局部变量提取消除重复 dict 查找
- cooldown 衰减从 `dict copy + del` 循环改为 `dict comprehension` 单次分配
- `_get_key_nonblocking` termios 缓存 — 消除每 5 帧的 3 次系统调用

### 🎮 游戏设置自动读取 (v5.3.0)
自动导航到游戏内 LIVE 设置页面，OCR 读取 `タイミング調整` (判定时移) 和 `ノーツ速度` (音符速度)，自动映射为软件参数并校准预测引擎。

- **自动校准**: `timing_offset` → `advance_ms` / `note_speed` → `velocity_factor` 自动换算
- **6 服务器支持**: JP / TW / CN / KR / EN + 自动检测 (包名/OCR 标签/手动指定)
- **零配置启动**: 默认开启，首次执行自动读取 → 后续复用缓存
- **独立命令**: `python main.py read-settings --server jp`

```
┌──────────────────────────────────────────────┐
│  游戏内 LIVE 设置                              │
│  タイミング調整: +5    →   advance_ms -5ms     │
│  ノーツ速度:    10.5   →   velocity × 1.05     │
│  ─────────────────────────────────────────   │
│  自动写入 config.yaml  +  更新预测引擎         │
└──────────────────────────────────────────────┘
```

### 🛡️ 阻塞检测与自动恢复系统 (v5.5.0)

新增 `recovery/` 模块，检测并自动处理游戏运行中的常见阻塞事件。

#### 检测能力

| 事件类型 | 检测方法 | 处理方式 |
|---------|---------|---------|
| 服务器时间更新 / 日期变更弹窗 | OTSU + 四角遮罩 + OCR 关键词 | 自动关闭 (仅右上角 X) |
| 活动公告 / 维护通知 | 同上 | 自动关闭 |
| 画面冻结 (>4s 无变化) | 8×8 帧哈希比对 | 状态机 L1 恢复 |
| 黑屏 (>30 帧持续) | 全图亮度均值 < 8 | 状态机 L2/L3 |
| ADB 断连 (>10 帧无画面) | 连续 None 帧计数 | 状态机 L4 |
| App 崩溃弹窗 | OCR 检测 | 状态机 L2/L3 |

#### 安全设计

- **弹窗关闭只操作右上角 X 按钮，不点中央 OK/确认**
- OCR 验证按钮文字为安全列表后才会点击
- 消费类弹窗 (抽卡/购买/課金) 不自动关闭，改走告警
- 3 次同类型崩溃/5 分钟 → degraded 模式，直接告警

#### 恢复状态机

5 级升级链: `navigate_back → restart_app → force_restart → adb_reconnect → safe_stop`
- 每级独立重试次数 + exponential backoff
- 恢复后自动验证画面是否正常
- 60s 总超时保护

#### 控制器健康心跳

- ADB 存活: 5s 间隔 \| scrcpy 进程: 10s 间隔
- 最新帧超时: 5s 间隔 \| Minitouch socket: 10s 间隔

### 📡 多后端控制器
- **scrcpy 60 FPS** — 视频流方式高速截图
- **Minitouch <5ms** — 超低延迟触摸
- **Raw ADB** — 原始 RGBA 截屏，比 PNG 快 2-3x
- **ADB 兜底** — 自动检测最优后端，无缝降级

### 🛡️ 分级异常体系 (参考 ALAS 设计)
| 异常 | 恢复策略 |
|------|---------|
| `GameStuckError` | 画面卡住 → 重启 |
| `GameBugError` | 状态异常 → 杀进程重启 |
| `GamePageUnknownError` | 未知页面 → 导航返回 |
| `ConnectionLostError` | 连接断开 → 等待重连 |
| `TooManyClickError` | 防死循环 → 停止任务 |

### 🔧 配置系统 V2
- **分层配置**: 默认 < Profile < 本地覆盖 < 运行时
- **热加载**: 修改文件自动重载 (ConfigWatcher)
- **CLI 配置管理**: `pjsk config set play.mode ap`

### 🔐 操作自然化 (v5.0.0)
- 贝塞尔曲线滑动路径，模拟人类手指弧线
- HumanTouch 模拟器: 正态分布反应延迟、触摸压力变化
- 长按微动序列

### 🔐 行为多样性增强 (v5.6.0)

#### Session Fingerprint 行为指纹系统

每次 `start()` 生成新的行为指纹，session 间参数各不相同，避免重复模式：
- 坐标抖动标准差、时机抖动标准差、贝塞尔弯曲度、漏键率
- 长按微动幅度、操作间隔基准、触摸持续时间
- 参数值符合自然统计分布，不重复

#### 高斯抖动

`_apply_position_jitter` 和 `_apply_hold_jitter` 从均匀分布改为高斯分布 (±3σ 截断)，点击坐标自然分布在目标点周围，极少极端值。

#### 新增 SAFE (冲榜) 和 PRECISION (AP) 模式

| 模式 | 坐标抖动 | 时机抖动 | 漏键率 | 连续 AP 限制 | 适用场景 |
|------|---------|---------|-------|-------------|---------|
| SAFE | ±8px (高斯) | ±25ms (高斯) | 0~0.2% | ✅ 30 次上限 | 长时间自动运行 |
| PRECISION | ±1px (高斯) | ±3ms (高斯) | 0% | 无 | 单次高精度尝试 |
| FC (默认) | ±5px (高斯) | ±15ms (高斯) | 0% | 无 | 日常 |

#### 自然操作间隔

`_interaction_delay`: 每次 touch 后模拟人类反应延迟，延迟值呈正态分布，基准值 session 间浮动 (30~90ms)。

### 🎵 活动类型识别 (v5.0.0)
- HSV 颜色分析识别活动类型 (马拉松/芝士嘉年华/一般)
- 选曲推荐

### ⚡ 零分配帧缓冲 (v5.7.0)

#### ScrcpyController: 消除每帧 malloc (核心)

**之前**: `screencap()` 每帧调用 `self._latest_frame.copy()` 产生一次 ~7.7MB 内存分配 + memcpy（1080×2400 画面，30fps = 231MB/s 分配带宽）。

**之后**: 预分配 `_out_frame` 缓冲，复用 `np.copyto()` 写入。分配成本从 `malloc + free + memcpy` 降为 `memcpy only`。

| 指标 | 之前 | 之后 | 受益 |
|------|------|------|------|
| 每帧调用 | `malloc(7.7MB) + free() + copy()` | `memcpy()` | 零分配 |
| CPU 分配开销 | ~0.15ms | 0ms | 100% |
| 30s GC 压力 | 900 次分配 | 0 次持久分配 | 减少 GC |
| Cache 局部性 | 每次不同地址 | 同一缓存行 | 更好 |

当前瓶颈已从"单帧处理延迟"转移到"帧率上限"（scrcpy 30fps 传输带宽限制）。

---

## 前置条件

- Python 3.9+
- Android 设备 (二选一):
  - **真机**: USB 调试开启，USB 数据线连接
  - **模拟器**: MuMu 模拟器 12 (推荐) 或雷电模拟器 9
- ADB (自动检测或手动安装)

---

## 连接方式

### 方式 A: 真机 (USB 直连)
```bash
# 1. 手机开启 USB 调试 (开发者选项中)
# 2. USB 数据线连接电脑
# 3. 验证连接
adb devices
# 应显示:  <serial>  device

# 4. 运行设置向导
python main.py setup
```

### 方式 B: MuMu 模拟器 12 (推荐)
```bash
# 1. 下载安装 MuMu 模拟器 12: https://mumu.163.com/
# 2. 在模拟器中安装 PJSK (通过 Google Play / QooApp / APK)
# 3. 模拟器设置 → 其他设置:
#    - 关闭 ROOT 权限
#    - 分辨率: 1280x720 (推荐)
#    - 开启 ADB 调试
# 4. 连接模拟器 ADB
adb connect 127.0.0.1:7555   # MuMu 12 默认端口

# 5. 验证连接
adb devices
# 应显示:  127.0.0.1:7555  device

# 6. 运行设置向导
python main.py setup
```

### 方式 C: 雷电模拟器 9
```bash
# 类似 MuMu，端口改为 5555
adb connect 127.0.0.1:5555
python main.py setup
```

> ⚠️ **模拟器注意事项**:
> - 日服 (jp) 检测较严，建议使用 MuMu 12 Android 9 镜像
> - 国际服 (en) 和台服 (tw) 检测相对宽松
> - 模拟器内**不要开启 ROOT**，否则可能被游戏检测
> - 如遇到游戏闪退，尝试在模拟器设置中关闭"开发者选项"

---

## 安装 (开发者)

```bash
git clone https://github.com/WeatherWind/pjsk-auto-player.git
cd pjsk-auto-player
pip install -r requirements.txt
```

```bash
# 1. 首次运行 → 设置向导
python main.py setup

# 2. 校准
python main.py calibrate

# 3. 开始执行
python main.py start

# 4. 或启动 Web 控制面板 (浏览器 http://localhost:8080)
python main.py desktop
```

---

## 📂 项目结构

```
pjsk-auto-player/
├── main.py                     # 入口
├── app.py                      # 应用主类 (协调所有模块)
├── cli.py                      # CLI 命令处理
├── exceptions.py               # 分级异常体系
│
├── config/                     # 配置系统 V2
│   ├── __init__.py             # ConfigLoader (分层/热加载)
│   ├── default.yaml            # 默认配置
│   └── schema.py               # 配置 Schema 校验
│
├── controller/                 # 设备控制器
│   ├── base.py                 # BaseController 抽象
│   ├── adb.py                  # ADB 控制 (含 raw/async)
│   ├── scrcpy.py               # scrcpy 视频流
│   └── combined.py             # 智能路由 + Benchmark
│
├── recovery/                   # 阻塞检测与自动恢复 (v5.5.0)
│   ├── __init__.py             # ObstructionEngine 顶层协调器
│   ├── detector.py             # ObstructionDetector 弹窗/冻结/黑屏检测
│   ├── machine.py              # RecoveryStateMachine 5 级恢复状态机
│   └── scheduler.py            # HealthScheduler 控制器健康心跳
│
├── game_settings/              # 游戏设置自动读取 (v5.3.0)
│   ├── server_config.py        # 5 服 UI/OCR 配置 + 自动检测
│   ├── reader.py               # 导航 → OCR 读取核心
│   └── calibrator.py           # 参数映射 + 校准引擎
│
├── pipeline/                   # Pipeline V2
│   ├── base.py                 # AbstractTask / PackageTask
│   ├── process.py              # ProcessTask 执行引擎
│   ├── node.py                 # 节点生命周期
│   ├── plugins.py              # 插件系统 (AOP)
│   ├── task_data.py            # JSON + @继承解析
│   ├── scheduler.py            # 任务调度器
│   └── timer.py                # Timer 双定时器
│
├── scene/                      # 场景检测
│   ├── classifier.py           # 多算法投票分类
│   ├── states.py               # 场景状态定义
│   └── transitions.py          # 状态机
│
├── vision/                     # 图像识别引擎
│   ├── matcher.py              # 模板匹配 (多尺度)
│   ├── ocr.py                  # OCR 识别 (EasyOCR/Tesseract)
│   ├── color.py                # 颜色检测 (HSV/RGB)
│   ├── scene.py                # 多算法融合
│   └── button.py               # Button 声明式 UI (ALAS 风格)
│
├── web/                        # Web GUI V2
│   ├── app.py                  # HTTP + SSE 服务器
│   ├── websocket.py            # SSE 实时推送
│   ├── dashboard.html          # 控制面板 (暗色/亮色双主题)
│   ├── manifest.json           # PWA 配置
│   ├── sw.js                   # Service Worker 离线缓存
│   └── icon-*.png              # PWA 图标
│
├── wizard/                     # 设置向导
│   └── setup.py                # 5 步向导
│
├── handlers/                   # 游戏处理器
│   ├── goto_game.py            # 游戏启动/导航
│   ├── handle_result.py        # 结算/分数处理
│   └── event_detect.py         # 活动类型检测
│
├── lib/                        # 工具库
│   ├── decorators.py           # cached_property / classproperty
│   ├── resource.py             # Resource 资源管理
│   └── anti_detection.py       # 反检测 (贝塞尔/触压/延迟)
│
├── notification/               # 通知系统
│   ├── desktop.py              # 桌面通知
│   └── web.py                  # Web 推送
│
├── locale/                     # i18n 国际化
│   ├── zh_CN.json              # 简体中文
│   ├── en_US.json              # English
│   └── ja_JP.json              # 日本語
│
├── tests/                      # 单元测试 (pytest, 6 文件)
│   ├── conftest.py             # 共享 fixtures
│   ├── test_anti_detection.py
│   ├── test_exceptions.py
│   ├── test_pipeline.py
│   └── test_config.py
│
├── scripts/                    # 构建 & 发布脚本
│   ├── build.sh                # 本地 PyInstaller 打包
│   ├── release.sh              # 发布流程
│   ├── download_minitouch.sh   # Minitouch 二进制下载
│   ├── gen_release_notes.py    # 从 CHANGELOG 生成 Release Notes
│   └── gen_changelog.sh
│
├── .github/workflows/          # CI/CD
│   ├── ci.yml                  # 主 CI (lint + test)
│   ├── build.yml               # 构建 Release (tag 触发)
│   └── auto-release.yml        # 自动 Tag + Release (push main)
│
├── resource/                   # 资源文件
│   ├── tasks/                  # JSON 任务定义
│   └── templates/              # 模板图片
│
├── bin/minitouch/              # Minitouch 预编译二进制
├── combos/                     # 谱面配置
├── teams/                      # 队伍配置
├── tasks/                      # 兼容旧任务配置
│
│   # ═══ 根目录核心模块 (向后兼容) ═══
├── adb_controller.py           # ADB 控制器 (935 行)
├── auto_play.py                # 自动执行引擎 (2038 行)
├── pipeline.py                 # Pipeline 引擎 (608 行)
├── screen_analyzer.py          # 屏幕分析 (702 行)
├── web_dashboard.py            # Web 仪表盘 (1035 行)
├── scrcpy_controller.py        # scrcpy 控制器 (300 行)
├── scene_classifier.py         # 场景分类 (189 行)
├── ocr_reader.py               # OCR 读取 (167 行)
├── setup_wizard.py             # 设置向导 (382 行)
├── native_gui.py               # 原生桌面 GUI (634 行)
├── desktop_app.py              # 桌面应用 (454 行)
├── combo_player.py             # 谱面播放器 (475 行)
├── team_builder.py             # 队伍构建 (333 行)
├── capture_optimizer.py        # 截图优化 (142 行)
│
├── config.yaml                 # 运行时配置
├── VERSION                     # 版本号
├── requirements.txt            # Python 依赖
├── build.spec                  # PyInstaller 构建配置
├── VISION.md                   # 架构演进文档
├── VISION_ALAS.md              # ALAS 设计模式研究
├── CHANGELOG.md                # 变更日志
├── TERMS.md                    # 用户协议
├── CLAUDE.md                   # AI 助手指南
├── run.bat / run.sh            # 启动脚本
└── PJSK Auto Player.command    # macOS 双击启动器
```

---

## 命令行参考

| 命令 | 说明 |
|------|------|
| `python main.py` | 原生桌面 GUI (默认) |
| `python main.py desktop` | Web 桌面模式 |
| `python main.py gui` | 原生桌面 GUI |
| `python main.py start` | 单次执行 |
| `python main.py auto` | 连续执行 |
| `python main.py web` | 仅启动 Web 服务器 |
| `python main.py daemon` | 后台守护进程 |
| `python main.py calibrate` | 一键校准 |
| `python main.py read-settings` | 读取游戏内设置 (v5.3.0) |
| `python main.py read-settings --server jp` | 指定日服读取 |
| `python main.py setup` | 设置向导 |
| `python main.py status` | 查看守护进程状态 |
| `python main.py stop` | 停止守护进程 |
| `python main.py config list` | 列出配置档案 |
| `python main.py config set play.mode ap` | 运行时修改配置 |

---

## 🏗️ 架构

```
                        ┌──────────────────────────────┐
                        │  原生桌面 GUI / Web 控制面板    │
                        │  tkinter · SSE 实时推送 · PWA  │
                        ├──────────────────────────────┤
                        │    CLI / 守护进程 (Daemon)    │
                        │  status · stop · config · JSON│
                        ├──────────────────────────────┤
                        │     Pipeline V2 任务引擎      │
                        │  @继承 · 生命周期 · 插件系统  │
                        ├──────────┬──────────┬────────┤
                        │ 场景检测  │ 识别引擎  │ 控制器  │
                        │ SceneCls. │ Vision   │ Ctrl   │
                        │ 多算法投票 │ OCR/匹配  │ADB/raw │
                        │           │ /颜色    │/scrcpy │
                        ├──────────┴──────────┴────────┤
                        │  阻塞检测 · 自动恢复 (Recovery)  │
                        │   5 级状态机 · 弹窗处理 · 心跳  │
                        ├──────────────────────────────┤
                        │  配置系统 V2 (分层 + 热加载)   │
                        │  异常体系 (分级 + 自动恢复)    │
                        │  反检测 (贝塞尔 + 触压 + 延迟)  │
                        └──────────────────────────────┘
```

### 设计理念
- **分层解耦**: 配置 → 控制器 → 识别 → Pipeline → 恢复 → GUI 完全独立
- **声明式配置**: 行为由 JSON/YAML 驱动，不硬编码
- **MAA 任务模型**: ProcessTask 执行引擎 + @继承语法
- **ALAS 异常体系**: 分级异常 + 自动恢复策略
- **MaaFramework 架构**: 3 层分离 (Controller → Resource → Agent)
- **无人值守运行**: Recovery 模块实现弹窗处理 + 崩溃恢复 + 健康心跳

### 技术栈
- Python 3.9+
- OpenCV (图像处理)
- ADB / scrcpy / minitouch (设备控制)
- EasyOCR / pytesseract (文字识别)
- http.server + SSE (Web 服务)
- tkinter (原生桌面 GUI)

---

## 🚦 CI/CD

| Workflow | 触发条件 | 说明 |
|----------|---------|------|
| **ci.yml** | push (非 main) / PR | lint + pytest |
| **auto-release.yml** | push to main | 自动读取 VERSION → 创建 tag → 触发构建 |
| **build.yml** | tag (v*.*.*) | PyInstaller 打包 → GitHub Release |

---

## 免责声明

本软件用于学习和研究目的。使用本软件可能违反 Project Sekai (SEGA/Colorful Palette) 的服务条款。用户应自行承担所有风险和责任。开发者不对任何账号封禁或其他后果负责。

详见 [TERMS.md](TERMS.md)。

---

## License

MIT License
