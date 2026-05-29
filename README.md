# PJSK Auto Player — CV 自动化研究工具

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

首次运行会自动安装依赖并打开设置向导。之后每次双击直接启动桌面控制面板。

### 方式 2：命令行

```bash
python main.py              # 🖥️ 桌面模式 — 自动打开浏览器控制面板
python main.py start        # 单次执行
python main.py auto         # 连续执行（自动处理结算与重试）
python main.py setup        # 设置向导
```

---

## ✨ 版本亮点

| 版本 | 特性 |
|------|------|
| **v5.1.0** | 🌍 i18n 国际化 (中/英/日) + 社区项目调研 + 模拟器连接指南 |
| **v5.0.0** | 🖥️ MAA 风格原生桌面 GUI + 反检测 + 活动检测 |
| **v4.11.0** | 🖥️ 开箱即用: 桌面应用 + 自动打开浏览器 + 首次运行向导 + 系统托盘 |
| **v4.10.0** | 🧬 ALAS 深度集成: cached_property/Resource/颜色预处理/Benchmark/配置 Schema |
| **v4.9.0** | 🏗️ MAA/ALAS 融合架构: Pipeline V2 + 场景多算法投票 + Web 暗色面板 + 分级异常 + 守护进程 |

---

## 🔥 主要特性

### 🎯 预测引擎
基于时序预测的触发系统：检测判定区域上方目标 → 追踪移动速度 → 计算到达时间 → 准时触发。
补偿 ADB 链路的 100-300ms 传输延迟，变被动响应为主动预测。

### 🧠 Pipeline V2 引擎 (参考 MAA 设计)
- **JSON 任务配置驱动** — 识别→动作→跳转的声明式流水线
- **@任务继承** — `"ClickOK@ClickSelf"` 复用父任务配置，只覆盖差异
- **节点生命周期** — `pre_wait_freezes → pre_delay → action → post_wait_freezes → post_delay`
- **插件系统** — AOP 风格，在任务前后自动注入日志/统计/错误处理
- **子任务并行** — 主任务间隙并行扫描弹窗/通知

### 🏗️ 新架构 (v4.9.0+)

```
                        ┌──────────────────────────────┐
                        │      Web GUI V2 (暗色面板)    │
                        │  SSE 实时推送 · Canvas 图表   │
                        ├──────────────────────────────┤
                        │    CLI / 守护进程 (Daemon)    │
                        │  status · stop · config · JSON│
                        ├──────────────────────────────┤
                        │     Pipeline V2 任务引擎      │
                        │  @继承 · 生命周期 · 插件系统  │
                        ├──────────┬──────────┬────────┤
                        │ 场景检测  │ 识别引擎  │ 控制器  │
                        │ SceneCls. │ Vision   │ Ctrl   │
                        │ 多算法投票 │ OCR/匹配  │ADB/scre│
                        │           │ /颜色    │cpy/ADB │
                        ├──────────┴──────────┴────────┤
                        │  配置系统 V2 (分层 + 热加载)   │
                        │  异常体系 (分级 + 自动恢复)    │
                        └──────────────────────────────┘
```

### 🎲 操作随机化
模拟人工操作特征：时机抖动 ±15ms、坐标偏移 ±5px、随机漏键 0.1%、长按时长抖动

### 🎮 执行策略
- **AP** — 高精度触发策略
- **FC** — 平衡稳定性策略
- **LIVE** — 基础通过策略
- **混合** — 智能切换策略 (70% FC + 25% AP + 5% LIVE)

### ⚡ PID 自适应延迟
每次执行结束后基于实际触发提前量自动微调延迟补偿，逐步收敛到最佳值。

### 📡 多后端控制器
- **scrcpy 60 FPS** — 视频流方式高速截图
- **Minitouch <5ms** — 超低延迟触摸
- **ADB 兜底** — 自动检测最优后端，无缝降级

### 🌐 Web 控制面板 V2
现代暗色主题，零外部依赖的单页应用：
- 实时帧预览 (SSE 推送)
- 任务状态监控
- FPS/点击量实时折线图
- 配置在线编辑
- 日志查看器
- 截图浏览器

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

---

## 快速开始

### 前置条件
- Python 3.9+
- Android 设备 (二选一):
  - **真机**: USB 调试开启，USB 数据线连接
  - **模拟器**: MuMu 模拟器 12 (推荐) 或雷电模拟器 9
- ADB (自动检测或手动安装)

### 连接方式

#### 方式 A: 真机 (USB 直连)
```bash
# 1. 手机开启 USB 调试 (开发者选项中)
# 2. USB 数据线连接电脑
# 3. 验证连接
adb devices
# 应显示:  <serial>  device

# 4. 运行设置向导
python main.py setup
```

#### 方式 B: MuMu 模拟器 12 (推荐)
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

#### 方式 C: 雷电模拟器 9
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

### 安装
```bash
git clone https://github.com/WeatherWind/pjsk-auto-player.git
cd pjsk-auto-player
pip install -r requirements.txt
```

### 使用
```bash
# 1. 首次运行 → 设置向导
python main.py setup

# 2. 校准
python main.py calibrate

# 3. 开始执行
python main.py start

# 4. 或启动 Web 控制面板 (浏览器 http://localhost:8080)
python main.py web
```

---

## 📂 项目结构

```
pjsk-auto-player/
├── main.py                 # 入口
├── cli.py                  # CLI 命令处理
├── app.py                  # 应用主类 (协调所有模块)
├── config/                 # 配置系统 V2
│   ├── __init__.py         # ConfigLoader (分层/热加载)
│   └── default.yaml        # 默认配置
├── controller/             # 设备控制器
│   ├── base.py             # BaseController 抽象
│   ├── adb.py              # ADB 控制
│   ├── scrcpy.py           # scrcpy 视频流
│   └── combined.py         # 智能路由
├── pipeline/               # Pipeline V2
│   ├── base.py             # AbstractTask / PackageTask
│   ├── process.py          # ProcessTask 执行引擎
│   ├── node.py             # 节点生命周期
│   ├── plugins.py          # 插件系统 (AOP)
│   ├── task_data.py        # JSON + @继承解析
│   └── scheduler.py        # 任务调度器
├── scene/                  # 场景检测
│   ├── classifier.py       # 多算法投票分类
│   ├── states.py           # 场景状态定义
│   └── transitions.py      # 状态机
├── vision/                 # 图像识别引擎
│   ├── matcher.py          # 模板匹配
│   ├── ocr.py              # OCR 识别
│   ├── color.py            # 颜色检测
│   └── scene.py            # 多算法融合
├── web/                    # Web GUI V2
│   ├── app.py              # HTTP + SSE 服务器
│   ├── websocket.py        # SSE 实时推送
│   └── dashboard.html      # 暗色控制面板
├── wizard/                 # 设置向导
│   └── setup.py            # 5 步傻瓜式向导
├── notification/           # 通知系统
│   ├── desktop.py          # 桌面通知
│   └── web.py              # Web 推送
├── exceptions.py           # 分级异常体系
├── VISION.md               # 架构演进文档
├── lib/                    # 原代码 (向后兼容)
│   ├── adb_controller.py
│   ├── auto_play.py
│   ├── scrcpy_controller.py
│   ├── scene_classifier.py
│   ├── screen_analyzer.py
│   ├── ocr_reader.py
│   ├── pipeline.py
│   ├── web_dashboard.py
│   └── setup_wizard.py
├── resource/
│   └── tasks/
├── config.yaml             # 兼容旧配置文件
└── VERSION
```

---

## 命令行参考

| 命令 | 说明 |
|------|------|
| `python main.py` | Web 控制面板 (默认) |
| `python main.py start` | 单次执行 |
| `python main.py auto` | 连续执行 |
| `python main.py web` | Web 控制面板 |
| `python main.py daemon` | 后台守护进程 |
| `python main.py calibrate` | 一键校准 |
| `python main.py setup` | 设置向导 |
| `python main.py status` | 查看守护进程状态 |
| `python main.py stop` | 停止守护进程 |
| `python main.py config list` | 列出配置档案 |
| `python main.py config set play.mode ap` | 运行时修改配置 |

---

## 架构

### 设计理念
- **分层解耦**: 配置 → 控制器 → 识别 → Pipeline → Web/GUI 完全独立
- **声明式配置**: 行为由 JSON/YAML 驱动，不硬编码
- **MAA 任务模型**: ProcessTask 执行引擎 + @继承语法
- **ALAS 异常体系**: 分级异常 + 自动恢复策略
- **MaaFramework 架构**: 3 层分离 (Controller → Resource → Agent)

### 技术栈
- Python 3.9+
- OpenCV (图像处理)
- ADB / scrcpy / minitouch (设备控制)
- EasyOCR / pytesseract (文字识别)
- http.server + SSE (Web 服务)

---

## 免责声明

本软件用于学习和研究目的。使用本软件可能违反 Project Sekai (SEGA/Colorful Palette) 的服务条款。用户应自行承担所有风险和责任。开发者不对任何账号封禁或其他后果负责。

详见 [TERMS.md](TERMS.md)。

---

## License

MIT License
