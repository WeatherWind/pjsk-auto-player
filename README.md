# PJSK Auto Player

> 基于 ADB + OpenCV 的 Project Sekai (プロジェクトセカイ) 自动打歌 AP 工具。
> 在电脑上运行, 通过 USB 连接安卓手机, 自动完成打歌操作。

---

## ✨ 版本亮点

| 版本 | 特性 |
|------|------|
| **v4.5.0** 🆕 | ⚡ 延迟大幅优化: scrcpy 自动检测+60FPS、向量化检测 5-10x、帧跳过、缓存加速、默认 frame_skip |
| **v4.4.0** | 打歌模式 (AP/FC/LIVE) + 模式浮动 + 点击随机化反封号 |
| **v4.0.0** | 纯 Web 操控 + scrcpy/minitouch 自动启用 + 原生窗口 (PyWebView) |
| **v3.9.0** | 开箱即用: ADB 自动下载 + 一键启动脚本 |
| **v3.8.0** | MAA 风格 Web 控制台 (完整仪表盘 + 截图 + 配置编辑) |
| **v3.7.0** | 自动编队系统 (活动/自定义编队 + 角色选择) |
| **v3.6.0** | 歌单系统 (多曲目自动切换 + 冲榜套餐) |
| **v3.5.0** | Windows 热键 + --version + 配置校验 |
| **v3.4.0** | 交互式设置向导 + 自动重连 |
| **v3.3.0** | ALAS 场景分类 + scrcpy PPM 30-60 FPS |

## 🔥 主要特性

| 特性 | 说明 |
|------|------|
| **🎯 预测引擎** | 提前检测判定线上方的 note → 追踪滚动速度 → 计算到达时间 → 准时触发。补偿 ADB 的 100-300ms 延迟, 让纯反应式变主动式 |
| **🎲 点击随机化** 🆕 | 模拟人类操作, 避免被封号: 时机抖动 ±15ms, 坐标偏移 ±5px, 随机漏键 0.1%, 长按时长抖动, 结算点击间隔随机化 |
| **🎮 打歌模式** 🆕 | 三种模式: AP (All Perfect), FC (Full Combo), LIVE (通关保底)。热键 M 运行时切换, 冲榜时自动浮动 (70% FC + 25% AP + 5% LIVE) |
| **🤏 Minitouch 后端** | 可选, 推送 minitouch 到手机后触摸延迟从 ~50ms 降到 <5ms |
| **🏭 Pipeline 引擎** | MAA 启发式任务流水线, 游戏状态机用 JSON 配置, 支持模板匹配 + 重试策略 + 子任务 |
| **♾️ 冲榜模式** | 自动连续打歌: 检测结算画面 → 点击跳过 → 返回选歌 → 下一首。支持 `--infinite` |
| **⌨️ 热键控制** | 运行时无需切窗口: P=暂停, Q=退出, +/-=微调延迟, </>=调阈值 |
| **📊 实时统计** | 终端显示 FPS、点击数、预测触发数 |
| **🔢 OCR 积分读取** | 冲榜时自动读取结算画面分数和判定计数 |
| **🌐 Web 仪表盘** | 手机浏览器实时监控冲榜进度, 电脑端运行 `python main.py web` |
| **💾 校准自动写入** | `calibrate` 后自动更新 config.yaml, 无需手动复制 |
| **📁 配置档案** | 不同手机/歌曲可创建独立配置, `--profile` 快速切换 |
| **📡 scrcpy 后端** | 可选, 安装 scrcpy 后获得 30-60 FPS (PPM 格式视频流) |
| **⚡ ALAS 场景分类** | <1ms 快速画面识别, 决策树预过滤 + 帧差跳过无变化帧 |

---

## 目录

- [工作原理](#工作原理)
- [快速开始](#快速开始)
- [使用指南](#使用指南)
  - [自动打歌](#-自动打歌)
  - [冲榜模式](#-冲榜模式)
  - [一键校准](#-一键校准)
  - [配置档案](#-配置档案)
  - [测试连接](#-测试连接)
- [Pipeline 流水线](#pipeline-流水线)
- [命令行参考](#命令行参考)
- [架构](#架构)
- [版本历史](#版本历史)
- [免责声明](#免责声明)

---

## 工作原理

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  ADB / scrcpy│ ──► │  Pipeline    │ ──► │  ADB 触摸    │
│  截图/视频流  │     │ 任务引擎      │     │  点击/滑动   │
└──────────────┘     └──────────────┘     └──────────────┘
       ↑                     ↑                     ↑
  5-60 FPS            状态机 + 任务链          30-100ms
```

### 预测引擎 (v1.0.0 核心)

传统的纯反应式方法:
```
        note 到达       触发触摸
  ──────●────────────────●────────→   延迟太大, MISS!
        ◄── 150ms ──►
```

预测引擎的工作方式:
```
  note 出现    追踪速度    预测到达  准时触发
  ──●────────────●──────────●────────●──  PERFECT!
    ◄── 提前发现 ──► ◄── 补偿 ──►
```

1. 在判定线上方 ~35% 屏幕区域检测刚出现的 note
2. 跨帧追踪 note 的 Y 位置变化, 计算滚动速度 (px/s)
3. 根据当前距离和速度, 预测 note 到达判定线的时间
4. 在需要提前触发的时机 (延迟补偿) 发送触摸指令

### Pipeline 引擎 (v3.0.0 新架构)

受 [MAA (MaaAssistantArknights)](https://github.com/MaaAssistantArknights/MaaAssistantArknights) 启发:

```
                    ┌─────────────────────────┐
                    │    PipelineEngine        │
                    │  加载JSON → 状态机跳转    │
                    └────┬─────────┬──────────┘
                         │         │
              ┌──────────┘         └──────────┐
              ▼                                ▼
      ┌──────────────┐               ┌──────────────┐
      │  DetectTask   │               │  ActionTask   │
      │ 模板匹配/亮度  │    ──→        │ ClickSelf/等待 │
      │ 识别当前画面   │               │ 执行动作      │
      └──────────────┘               └──────────────┘
              │                              │
              └──────────┬───────────────────┘
                         ▼
                  ┌──────────────┐
                  │  Next决策     │
                  │ next/failed/  │
                  │ exceededNext  │
                  └──────────────┘
```

每个任务是一个 JSON 对象:

```json
"DetectGameScreen": {
  "action": "DoNothing",
  "algorithm": "BrightnessDetect",
  "next": ["PlaySong", "DetectResultScreen"],
  "failed_next": ["DetectResultScreen", "DetectMenuScreen"],
  "maxRetries": 3
}
```

---

## 环境要求

| 组件 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 (本代码也兼容 macOS/Linux) |
| Python | 3.8+ |
| 手机 | 安卓手机, 已开启 USB 调试 |
| 数据线 | USB 数据线 (建议原装线) |
| 游戏 | Project Sekai (プロジェクトセカイ) 已安装 |

### 可选: scrcpy (大幅提升帧率)

默认使用 ADB screencap (5-15 FPS)。安装 scrcpy 后可切换到 30-60 FPS:

```bash
# macOS
brew install scrcpy

# Windows (scoop)
scoop install scrcpy

# Linux
apt install scrcpy
```

然后在 `config.yaml` 中设置 `screencap_method: scrcpy`。

---

## 快速开始

### 1. 安装 Python

从 [python.org](https://www.python.org/downloads/) 下载 Python 3.8+,
安装时**务必勾选** "Add Python to PATH"。

```bash
python --version
```

### 2. 安装 ADB

下载 [Android SDK Platform Tools](https://developer.android.com/studio/releases/platform-tools),
解压后把目录添加到系统 PATH。

验证:
```bash
adb --version
```

### 3. 手机设置

1. 设置 → 关于手机 → 连续点击「版本号」7 次 (开启开发者选项)
2. 设置 → 开发者选项 → USB 调试 → 开启
3. 用 USB 线连接电脑, 手机上授权「一律允许」
4. 验证:
   ```bash
   adb devices
   ```
   应显示 `xxxxxxx device`

### 4. 下载项目

```bash
git clone https://github.com/WeatherWind/pjsk-auto-player.git
cd pjsk-auto-player
```

### 5. 安装 Python 依赖

```bash
pip install -r requirements.txt

# 可选 (用于一键轨道校准):
pip install scipy
```

---

## 使用指南

### 🚀 自动打歌

```bash
python main.py start
```

运行时热键:
| 键 | 功能 |
|----|------|
| **M** | 切换打歌模式 (AP → FC → LIVE → 循环) |
| **P** | 暂停/继续 |
| **Q** | 退出 |
| **+** / **=** | 延迟补偿 +5ms |
| **-** / **_** | 延迟补偿 -5ms |
| **>** / **.** | 亮度阈值 +5 |
| **<** / **,** | 亮度阈值 -5 |
| **[** | 时机抖动 -3ms (降到 0 则禁用抖动) |
| **]** | 时机抖动 +3ms (自动启用随机化) |
| **\\** | 切换随机化 启用/禁用 |

### ♾️ 冲榜模式

自动连续打歌, 处理结算画面, 无需手动干预:

```bash
# 连续打 5 首 (默认)
python main.py auto

# 打 20 首
python main.py auto -n 20

# 无限循环 (按 Ctrl+C 停止)
python main.py auto --infinite

# 使用配置档案
python main.py auto --infinite --profile phone2
```

冲榜模式自动:
- 检测结算画面 (高亮背景 + 无 note 活动)
- 逐次点击跳过分数/结果/等级动画
- 等待返回选歌/打歌画面
- 单曲超时保护 (默认 6 分钟)
- 结算点击卡住自动退出 (15 次上限)
- 停止时打印完整统计

```
🔥 冲榜统计
  完成歌曲: 12 首
  失败歌曲: 0 首
  总运行时间: 360s (6.0min)
  平均每首: 29.5s
  总点击: 2850 次
```

### 📏 一键校准

```bash
# 自动校准并更新 config.yaml
python main.py calibrate

# 交互式校准 (需要电脑有显示器)
python main.py calibrate --interactive
```

校准内容:
- ADB 延迟测量 (截图 + 触摸)
- 判定线 Y 位置
- 轨道 X 位置
- ✅ **自动写入 config.yaml**

### 📁 配置档案

不同手机或歌曲可以用不同的配置:

```bash
# 创建配置档案 (校准后自动保存)
python main.py calibrate --profile phone2

# 使用指定档案启动
python main.py start --profile phone2

# 列出所有档案
python main.py profiles
```

### 🔍 测试连接

```bash
python main.py test
python main.py test --loop
```

---

## Pipeline 流水线

v3.0.0 引入的 Pipeline 引擎受 MAA 启发, 将游戏流程定义为可配置的 JSON 任务链。

### 任务定义

`tasks/pipeline.json` 定义了完整的冲榜流程:

```
BatchStart → WaitForNextSong → DetectGameScreen
                                   ↓
                            PlaySong (AutoPlayer)
                                   ↓
                            DetectResultScreen
                                   ↓
                            DismissResult → CheckAfterDismiss
                                   ↓
                            WaitForNextSong → (循环)
```

### 任务字段 (与 MAA 对照)

| 字段 | 含义 | MAA 对应 | 示例 |
|------|------|----------|------|
| `action` | 匹配后执行的动作 | `action` | `ClickSelf`, `DoNothing`, `Wait` |
| `algorithm` | 识别算法 | `algorithm` | `DirectHit`, `BrightnessDetect` |
| `roi` | 检测区域 `[x,y,w,h]` | `roi` | `[100, 200, 300, 50]` |
| `template` | 模板图片文件名 | `template` | `start_button.png` |
| `next` | 成功后跳转 | `next` | `["PlaySong", "#self"]` |
| `failed_next` | 失败后跳转 | — | `["DetectMenuScreen"]` |
| `exceeded_next` | 超重试跳转 | `exceededNext` | `["Stop"]` |
| `sub` | 子任务 (弹窗检测) | `sub` | `["ClosePopup"]` |
| `preDelay` | 执行前等待 ms | `preDelay` | `500` |
| `postDelay` | 执行后等待 ms | `postDelay` | `1000` |
| `maxRetries` | 最大重试次数 | `maxRetries` | `10` |

### 模板管理

通过 Pipeline 引擎保存按钮/画面的模板图片:

```python
from pipeline import PipelineEngine
engine = PipelineEngine(config, adb_controller=adb)
engine.save_template("start_button.png", frame, roi=[100,200,50,30])
```

之后在 JSON 任务中引用:

```json
"ClickStart": {
  "action": "ClickSelf",
  "template": "start_button.png",
  "next": ["#next"],
  "maxRetries": 5
}
```

---

## 命令行参考

```bash
python main.py start                         # 自动打歌 (默认 FC 模式)
python main.py start --mode AP               # AP 模式 (All Perfect)
python main.py start --mode LIVE             # LIVE 模式 (通关保底)
python main.py start --profile expert        # 使用配置档案

python main.py auto                          # 冲榜模式 (5首, 模式浮动)
python main.py auto -n 20                    # 冲榜模式 (20首)
python main.py auto --infinite               # 无限冲榜
python main.py auto --mode AP                # 冲榜基础模式 (浮动中心)
python main.py auto --profile phone2         # 使用档案

python main.py calibrate                     # 自动校准
python main.py calibrate -i                  # 交互式校准
python main.py calibrate --profile phone2    # 保存到档案

python main.py test                          # 测试连接
python main.py test --loop                   # 持续测试

python main.py profiles                      # 列出配置档案
python main.py -c config2.yaml start         # 指定配置文件
```

## 📦 打包成可执行文件

像 MAA 一样分发单文件可执行, 无需安装 Python:

### 本地打包

```bash
pip install pyinstaller
./scripts/build.sh            # macOS
./scripts/build.sh windows    # Windows (需在 Windows 上运行)
./scripts/build.sh linux      # Linux (需在 Linux 上运行)
```

输出在 `dist/` 目录, 单文件可直接运行:

```bash
./dist/pjsk-auto-player-macos start
./dist/pjsk-auto-player-macos auto -n 10
```

### 自动构建与发布 (GitHub Actions)

每次推送到 `main` 分支时:
1. CI 自动构建 **Windows / macOS / Linux** 三平台可执行文件
2. 自动发布到 GitHub Releases: **Continuous Build** (持续构建)
3. 可执行文件可直接从 Releases 页面下载

推送 `v*` tag 时:
1. 同样构建三平台可执行文件
2. 创建 **正式版本 Release** (带有版本号)
3. 自动生成更新日志 (基于 git log)

```bash
# 日常更新: 推送后自动构建, 从 Releases 下载
git push origin main

# 发版: 自动构建 + 正式 Release + 更新日志
git tag v3.5.0
git push origin main --tags
```

前往 https://github.com/WeatherWind/pjsk-auto-player/releases 下载。

---

## 架构

```
pjsk-auto-player/
├── main.py                 # CLI 入口 + 配置管理
├── pipeline.py             # Pipeline 任务引擎 (v3.0.0)
├── adb_controller.py       # ADB/scrcpy/minitouch 控制器
├── scrcpy_controller.py    # scrcpy 视频流后端
├── screen_analyzer.py      # 画面分析 + 结算检测
├── auto_play.py            # 打歌引擎 + 冲榜模式
├── ocr_reader.py           # OCR 积分读取 (v3.1.0)
├── web_dashboard.py        # Web 仪表盘 (v3.2.0)
├── config.yaml             # 配置文件
├── requirements.txt        # Python 依赖
├── VERSION                 # 版本号
├── README.md               # 本文件
├── build.spec              # PyInstaller 打包配置
├── .github/workflows/      # GitHub Actions 自动构建
│   └── build.yml
├── scripts/
│   └── build.sh            # 本地打包脚本
├── tasks/
│   └── pipeline.json       # 冲榜流水线任务定义
├── templates/              # 模板图片目录
├── bin/minitouch/          # minitouch 二进制 (自动下载)
└── profiles/               # 配置档案目录
```

### 模块关系

```
                        ┌──────────────────────┐
                        │     main.py (CLI)     │
                        │ 配置 + Profile 管理    │
                        └────┬──────────────┬──┘
                             │              │
              ┌──────────────┘              └──────────────┐
              ▼                                              ▼
      ┌──────────────┐                              ┌────────────────┐
      │ PipelineEngine│                              │  BatchPlayer   │
      │ JSON 任务引擎  │       ┌──────────────┐       │  冲榜主循环     │
      │ 模板匹配/状态机 │◄─────│ AutoPlayer   │◄──────│ 结算处理/统计   │
      └──────┬───────┘       │ 预测引擎      │       └────────────────┘
             │               │ 打歌循环      │
             ▼               └──────┬───────┘
      ┌──────────────┐              │
      │ ScreenAnaly  │              ▼
      │ 结算/菜单检测 │       ┌──────────────┐
      │ 预测区域扫描  │◄──────│ ADBController │
      └──────────────┘       │ ADB/scrcpy    │
                             └──────────────┘
                                    │
                                    ▼
                             ┌──────────┐
                             │  手机     │
                             └──────────┘
```

---

## 进阶技巧

### 提高 AP 成功率

1. **校准**: 先运行 `calibrate` 获取准确的判定线和轨道位置
2. **亮度阈值**: 漏 note 就降低阈值, 误触就提高 (热键 `</>`)
3. **延迟补偿**: 运行 `test` 看实际延迟, `+`/`-` 热键实时调整
4. **预测引擎**: 默认启用, 如不需要可设置 `prediction.enabled: false`
5. **点击随机化**: 默认启用, 首次 `[`/`]` 热键可以微调时机抖动幅度

### 🎲 点击随机化 (反封号)

自动打歌的最大封号风险在于**机器般的精确性** —— 每次点击都在完全相同的时间、完全相同的位置触发。随机化功能通过模拟人类操作的不精确性来降低风险:

| 随机化维度 | 默认值 | 说明 |
|-----------|--------|------|
| ⏱ **时机抖动** | ±15ms | 在预测引擎计算的触发时间上随机偏移, 模拟人类反应速度波动。PJSK 判定窗口: PERFECT ±25ms, GREAT ±50ms, 所以 ±15ms 大部分落在 PERFECT 内 |
| 📍 **坐标抖动** | ±5px | 每次点击位置随机偏移几像素, 模拟手指落点不完全精确 |
| 💤 **随机漏键** | 0.1% | 大约每 1000 个 note 漏 1 个, 模拟人类偶尔的失误。设置为 0 可关闭 |
| 👆 **长按时长抖动** | ±30ms | 长按时随机增减速续时间, 避免每次都按相同的长度 |
| 📊 **结算间隔抖动** | ±0.8s | 跳过结算画面时随机化点击间隔, 避免每次都等固定时间 |

### 🎮 打歌模式 (AP / FC / LIVE)

三种预设模式, 每个模式对应不同的随机化参数组合，模拟不同水平的玩家:

| 模式 | 时机抖动 | 坐标抖动 | 漏键率 | 效果 |
|------|---------|---------|-------|------|
| **AP** (All Perfect) | ±3ms | ±2px | 0% | 所有 note PERFECT, 极致精确 |
| **FC** (Full Combo) | ±15ms | ±5px | 0% | 不漏键, 但可能有 GREAT/GOOD |
| **LIVE** (通关保底) | ±35ms | ±10px | 0.3% | 允许 MISS/BAD, 保底通关 |

**单次打歌:** 通过 `--mode` 指定:
```bash
python main.py start --mode AP      # 全力 AP
python main.py start --mode FC      # Full Combo (默认)
python main.py start --mode LIVE    # 仅通关
```

**冲榜模式 (浮动):** 每首歌自动切换模式, 模拟人类发挥波动:
```bash
python main.py auto                  # 默认: 25% AP + 70% FC + 5% LIVE
python main.py auto --mode AP        # 调整浮动中心
```

**运行中热键:** 按 `M` 循环切换 AP → FC → LIVE → AP ...

**自定义权重 (config.yaml):**
```yaml
batch_play:
  mode_weights:
    AP: 25   # 25% 概率 AP
    FC: 70   # 70% 概率 FC (默认主力)
    LIVE: 5  # 5% 概率混入 LIVE
```

**配置方式 (config.yaml):**
```yaml
randomization:
  enabled: true               # 总开关
  timing_jitter_ms: 15        # 时机抖动 (ms)
  position_jitter_px: 5       # 坐标抖动 (px)
  miss_chance: 0.001          # 漏键概率 (0=关闭)
  hold_duration_jitter_ms: 30 # 长按时长抖动 (ms)
  result_tap_jitter: 0.8      # 结算点击间隔抖动 (秒)
```

**运行中热键调整:**
- `M` : 循环切换打歌模式 (AP → FC → LIVE → ...)
- `[` : 降低时机抖动 (3ms/步, 降到 0 禁用)
- `]` : 增加时机抖动 (3ms/步, 自动启用随机化)
- `\` : 切换随机化启用/禁用

### 多手机支持

```bash
python main.py calibrate --profile phone1
python main.py calibrate --profile phone2
python main.py auto --infinite --profile phone1
```

### scrcpy 高帧率模式

```yaml
# config.yaml
adb:
  screencap_method: scrcpy
scrcpy:
  max_fps: 60
  scale: 0.5
```

### Pipeline 弹窗处理

在 `tasks/pipeline.json` 中添加子任务来处理游戏弹窗:

```json
"ClosePopup": {
  "action": "ClickSelf",
  "template": "close_button.png",
  "next": ["#next"]
}
```

然后在其他任务的 `sub` 字段引用:

```json
"WaitForNextSong": {
  "action": "DoNothing",
  "sub": ["ClosePopup"],
  "next": ["DetectGameScreen"]
}
```

---

## 版本历史

| Tag | 日期 | 说明 |
|-----|------|------|
| **v3.2.0** | 2026-05-28 | Web 仪表盘 + Minitouch 一键下载 + 手机浏览器监控 |
| **v3.1.0** | 2026-05-28 | Minitouch 低延迟触摸 + OCR 积分读取 + Pipeline 子任务弹窗处理 |
| **v3.0.0** | 2026-05-28 | MAA 流水线引擎 + JSON 任务定义 + 模板匹配 |
| **v2.0.0** | 2026-05-28 | 冲榜模式: 自动连续打歌 + 结算导航 + 统计 |
| **v1.0.0** | 2026-05-28 | 初始: 预测引擎 + 热键 + 校准自动写入 + 档案 + scrcpy |

---

## 局限性

- **ADB 延迟**: ADB 触摸延迟 ~50ms 依然存在 (建议使用 minitouch <5ms)
- **预测引擎**: 对极端高速谱面 (32分音符连打) 需要稳定 60FPS 输入
- **Flick 方向**: 方向检测依赖于画面中箭头特效的可识别性, 极少数谱面可能不准
- **Hold 处理**: 通过短按压模拟长按, 不是真正的持续按住
- **模板匹配**: 需要预先采集模板图片, 不同分辨率可能需要不同模板

## 未来改进方向 (Roadmap)

### 短期 (v4.6.x — v4.7.x)

1. **ML 轻量 note 检测** → 用 ONNX 部署轻量模型 (如 YOLO-nano / MobileNet) 替换 OpenCV 形态学检测, 提高 flick 和 hold 识别率, 预计检测速度提升 3x
2. **WebSocket 实时推流** → 在 Web 仪表盘实时显示手机画面 (替代 opencv 窗口)
3. **minitouch 预编译二进制** → 内置主流架构 (arm64/arm/x86_64) minitouch, 开箱即用无需下载
4. **谱面缓存** → 热门歌曲缓存轨道位置和速度参数, 减少重复校准

### 中期 (v4.8.x — v5.0.x)

5. **自适应延迟 PID 控制器** → 基于实时 AP/FC 反馈自动调整延迟补偿, 替代固定补偿值
6. **多设备并行** → 一台电脑同时控制多台手机冲榜, 共享分析引擎
7. **谱面解析** → 直接解析 PJSK 谱面文件格式, 实现完美时序触发, 不再依赖视觉检测
8. **Native GUI (PyQt/Wails)** → 原生的桌面应用, 替代 Web 仪表盘, 更低开销

### 长期 (v5.x+)

9. **机器学习谱面适配** → 根据每首歌的 note 密度、速度变化自动选择最佳检测参数
10. **分布式冲榜集群** → 多台电脑/手机通过中央调度器协作冲榜
11. **反检测机制升级** → 更精细的人类行为模型: 疲劳曲线、注意力波动、反应速度变化

## 免责声明

本项目仅供学习和研究使用。使用自动化工具可能违反游戏的服务条款,
请自行承担风险。开发者不对任何账号封禁或其他后果负责。

## License

MIT
