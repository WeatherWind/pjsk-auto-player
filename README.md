# PJSK Auto Player — 一站式 Project Sekai 游戏助手

> 基于 ADB + OpenCV 的 Project Sekai (プロジェクトセカイ) 自动打歌工具。
> 吸收 MAA (MaaAssistantArknights) + ALAS (AzurLaneAutoScript) + MaaFramework 设计精华。
> 插上手机 → 运行 → 自动打歌，零配置一站式体验。

---

## 🚀 快速开始

```bash
# 一键设置向导
python main.py setup

# 开始打歌
python main.py start

# 冲榜模式（自动无限循环）
python main.py auto

# Web 控制面板
python main.py web

# 后台守护进程
python main.py daemon
```

---

## ✨ 版本亮点 v4.9.0

| 版本 | 特性 |
|------|------|
| **v4.9.0** | 🏗️ MAA/ALAS 融合架构: Pipeline V2 + 场景多算法投票 + Web 暗色面板 + 分级异常 + 守护进程 |
| **v4.8.1** | 🔧 Bugfix: hasattr→布尔标志、minitouch 断连恢复、scrcpy 帧丢失自动重启、PID 3-sigma 离群值过滤 |
| **v4.8.0** | 🎯 自适应延迟 PID 控制器: 每首歌自动微调补偿, kp=0.3/ki=0.05/kd=0.1, 自动收敛 |
| **v4.7.0** | 📦 Minitouch 预编译二进制: 下载脚本 + CI 打包 + build.spec 自动触发 |
| **v4.6.0** | 🎵 谱面缓存: 跨歌曲保留 note 滚动速度, 跳过 ~50ms 校准期 |

---

## 🔥 主要特性

### 🎯 预测引擎
提前检测判定线上方的 note → 追踪滚动速度 → 计算到达时间 → 准时触发。
补偿 ADB 的 100-300ms 延迟, 让纯反应式变主动式。

### 🧠 Pipeline V2 引擎 (受 MAA 启发)
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

### 🎲 反检测点击随机化
模拟人类操作：时机抖动 ±15ms、坐标偏移 ±5px、随机漏键 0.1%、长按时长抖动

### 🎮 打歌模式
- **AP (All Perfect)** — 追求全完美
- **FC (Full Combo)** — 全程连击
- **LIVE** — 通关保底
- **AUTO 浮动** — 冲榜时智能切换 (70% FC + 25% AP + 5% LIVE)

### ⚡ PID 自适应延迟
每首歌结束后基于实际触发提前量自动微调延迟补偿，逐步收敛到最佳值。

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

### 🛡️ 分级异常体系 (受 ALAS 启发)
| 异常 | 恢复策略 |
|------|---------|
| `GameStuckError` | 画面卡住 → 重启游戏 |
| `GameBugError` | 游戏异常 → 杀进程重启 |
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
- Android 手机 (USB 调试开启)
- ADB (自动检测或手动安装)

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

# 3. 开始打歌
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
| `python main.py start` | 开始打歌 |
| `python main.py auto` | 冲榜模式 |
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
