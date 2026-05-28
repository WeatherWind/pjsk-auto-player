# PJSK Auto Player

> 基于 ADB + OpenCV 的 Project Sekai (プロジェクトセカイ) 自动打歌 AP 工具。
> 在电脑上运行, 通过 USB 连接安卓手机, 自动完成打歌操作。

---

## ✨ 版本亮点

| 版本 | 特性 |
|------|------|
| **v3.1.0** 🆕 | Minitouch 低延迟触摸 + OCR 积分读取 + Pipeline 子任务弹窗处理 |
| **v3.0.0** | MAA 启发式流水线引擎 + JSON 任务定义 + 模板匹配 |
| **v2.0.0** | 冲榜模式: 自动连续打歌 + 结算画面导航 + 会话统计 |
| **v1.0.0** | 预测引擎 + 热键控制 + 自动校准 + 配置档案 + scrcpy 后端 |

## 🔥 主要特性

| 特性 | 说明 |
|------|------|
| **🎯 预测引擎** | 提前检测判定线上方的 note → 追踪滚动速度 → 计算到达时间 → 准时触发。补偿 ADB 的 100-300ms 延迟, 让纯反应式变主动式 |
| **🤏 Minitouch 后端** | 可选, 推送 minitouch 到手机后触摸延迟从 ~50ms 降到 <5ms |
| **🏭 Pipeline 引擎** | MAA 启发式任务流水线, 游戏状态机用 JSON 配置, 支持模板匹配 + 重试策略 + 子任务 |
| **♾️ 冲榜模式** | 自动连续打歌: 检测结算画面 → 点击跳过 → 返回选歌 → 下一首。支持 `--infinite` |
| **⌨️ 热键控制** | 运行时无需切窗口: P=暂停, Q=退出, +/-=微调延迟, </>=调阈值 |
| **📊 实时统计** | 终端显示 FPS、点击数、预测触发数 |
| **🔢 OCR 积分读取** | 冲榜时自动读取结算画面分数和判定计数 |
| **💾 校准自动写入** | `calibrate` 后自动更新 config.yaml, 无需手动复制 |
| **📁 配置档案** | 不同手机/歌曲可创建独立配置, `--profile` 快速切换 |
| **📡 scrcpy 后端** | 可选, 安装 scrcpy 后切换 `screencap_method: scrcpy` 即可获得 30-60 FPS |

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
| **P** | 暂停/继续 |
| **Q** | 退出 |
| **+** / **=** | 延迟补偿 +5ms |
| **-** / **_** | 延迟补偿 -5ms |
| **>** / **.** | 亮度阈值 +5 |
| **<** / **,** | 亮度阈值 -5 |

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
python main.py start                         # 自动打歌
python main.py start --profile expert        # 使用配置档案

python main.py auto                          # 冲榜模式 (5首)
python main.py auto -n 20                   # 冲榜模式 (20首)
python main.py auto --infinite               # 无限冲榜
python main.py auto --profile phone2         # 使用档案

python main.py calibrate                     # 自动校准
python main.py calibrate -i                  # 交互式校准
python main.py calibrate --profile phone2    # 保存到档案

python main.py test                          # 测试连接
python main.py test --loop                   # 持续测试

python main.py profiles                      # 列出配置档案
python main.py -c config2.yaml start         # 指定配置文件
```

---

## 架构

```
pjsk-auto-player/
├── main.py                 # CLI 入口 + 配置管理
├── pipeline.py             # Pipeline 任务引擎 (v3.0.0)
├── adb_controller.py       # ADB/scrcpy 控制器
├── scrcpy_controller.py    # scrcpy 视频流后端
├── screen_analyzer.py      # 画面分析 + 结算检测
├── auto_play.py            # 打歌引擎 + 冲榜模式
├── config.yaml             # 配置文件
├── requirements.txt        # Python 依赖
├── VERSION                 # 版本号
├── README.md               # 本文件
├── tasks/
│   └── pipeline.json       # 冲榜流水线任务定义
├── templates/              # 模板图片目录
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
| **v3.1.0** | 2026-05-28 | Minitouch 低延迟触摸 + OCR 积分读取 + Pipeline 子任务弹窗处理 |
| **v3.0.0** | 2026-05-28 | MAA 流水线引擎 + JSON 任务定义 + 模板匹配 |
| **v2.0.0** | 2026-05-28 | 冲榜模式: 自动连续打歌 + 结算导航 + 统计 |
| **v1.0.0** | 2026-05-28 | 初始: 预测引擎 + 热键 + 校准自动写入 + 档案 + scrcpy |

---

## 局限性

- **ADB 延迟**: 即使有预测引擎, ADB 触摸延迟 ~50ms 仍然存在
- **帧率**: ADB screencap 5-15 FPS, 对高速谱面不够 (建议用 scrcpy)
- **Flick 方向**: 方向检测依赖于画面中箭头特效的可识别性
- **Hold 处理**: 通过短按压模拟长按, 不是真正的持续按住
- **模板匹配**: 需要预先采集模板图片, 不同分辨率可能需要不同模板

## 未来改进方向

1. **谱面解析** → 直接解析谱面文件, 完美时序
2. **ML 检测** → 用轻量模型识别 note 类型和方向
3. **Web UI** → 手机浏览器实时监控和控制
4. **minitouch 预编译** → 内置各架构二进制, 开箱即用

## 免责声明

本项目仅供学习和研究使用。使用自动化工具可能违反游戏的服务条款,
请自行承担风险。开发者不对任何账号封禁或其他后果负责。

## License

MIT
