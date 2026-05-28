# PJSK Auto Player

> 基于 ADB + OpenCV 的 Project Sekai (プロジェクトセカイ) 自动打歌 AP 工具。
> 在电脑上运行, 通过 USB 连接安卓手机, 自动完成打歌操作。
>
> **核心亮点**: 预测引擎 + 热键控制 + 自动校准 + 配置档案

---

## 🔥 主要特性

| 特性 | 说明 |
|------|------|
| **🎯 预测引擎** | 提前检测判定线上方的 note → 追踪滚动速度 → 计算到达时间 → 准时触发。补偿 ADB 的 100-300ms 延迟, 让纯反应式变主动式 |
| **⌨️ 热键控制** | 运行时无需切窗口: P=暂停, Q=退出, +/-=微调延迟, </>=调阈值 |
| **📊 实时统计** | 终端显示 FPS、点击数、预测触发数 |
| **💾 校准自动写入** | `calibrate` 后自动更新 config.yaml, 无需手动复制 |
| **📁 配置档案** | 不同手机/歌曲可创建独立配置, `--profile` 快速切换 |
| **📡 scrcpy 后端** | 可选, 安装 scrcpy 后切换 `screencap_method: scrcpy` 即可获得 30-60 FPS |

## 工作原理

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  ADB / scrcpy│ ──► │  OpenCV 分析  │ ──► │  ADB 触摸    │
│  截图/视频流  │     │  预测引擎     │     │  点击/滑动   │
└──────────────┘     └──────────────┘     └──────────────┘
       ↑                     ↑                     ↑
  5-60 FPS            检测+预测+追踪          30-100ms
```

### 预测引擎 (核心改进)

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

# Windows (winget)
winget install scrcpy

# Linux
apt install scrcpy
```

然后在 `config.yaml` 中设置 `screencap_method: scrcpy`。

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

## 使用指南

### 🚀 一键启动

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

### 📏 一键校准

```bash
# 自动校准并更新 config.yaml
python main.py calibrate

# 交互式校准 (需要电脑有显示器)
python main.py calibrate --interactive
```

校准内容:
- ADB 延迟测量 (截图 + 触摸)
- 判定线 Y 位置 (自动寻找画面特征)
- 轨道 X 位置 (基于亮度峰值)
- 校准结果截图保存到 `calibration_result.jpg`
- ✅ **自动写入 config.yaml**, 无需手动复制

### 📁 配置档案 (Profile)

不同手机或歌曲可以用不同的配置:

```bash
# 创建配置档案 (校准后自动保存)
python main.py calibrate --profile phone2

# 使用指定档案启动
python main.py start --profile phone2

# 列出所有档案
python main.py profiles
```

档案保存在 `profiles/` 目录下, 每个档案是一个独立的 YAML 文件。

### 🔍 测试连接

```bash
# 测试 ADB 连接和延迟
python main.py test

# 持续测试截图性能
python main.py test --loop
```

## 命令行参考

```bash
python main.py start                         # 启动自动打歌
python main.py start --profile expert        # 使用 expert 档案
python main.py calibrate                     # 自动校准参数
python main.py calibrate -i                  # 交互式校准 (实时预览)
python main.py calibrate --profile phone2    # 校准时保存到指定档案
python main.py test                          # 测试连接
python main.py test --loop                   # 持续测试截图性能
python main.py profiles                      # 列出配置档案
python main.py -c my_config.yaml start       # 使用指定配置文件
```

## 配置说明

详细配置见 `config.yaml`, 主要部分:

| 配置项 | 说明 |
|--------|------|
| `adb.screencap_method` | 截图方式: exec-out (默认), file, scrcpy |
| `screen.judgment_line_y` | 判定线 Y 位置 (相对比例 0~1) |
| `screen.note_detect_region_ratio` | 预测引擎检测区域大小 (相对比例) |
| `detection.brightness.threshold` | 亮度阈值 (越高越严格) |
| `prediction.enabled` | 是否启用预测引擎 |
| `timing.latency_compensation_ms` | 延迟补偿 (ms) |
| `display.show_stats` | 是否显示实时统计 |
| `profile.name` | 当前使用的配置档案名称 |

运行 `python main.py calibrate` 会自动测量并更新这些值。

## 架构

```
pjsk-auto-player/
├── main.py                # CLI 入口 + 配置管理 (Profile 支持)
├── adb_controller.py      # ADB 控制 (截图/触摸/设备管理 + scrcpy 后端)
├── scrcpy_controller.py   # scrcpy 视频流后端 (可选)
├── screen_analyzer.py     # 画面分析 (CV 检测 + 预测区域扫描)
├── auto_play.py           # 自动打歌引擎 (预测引擎 + 校准工具)
├── config.yaml            # 配置文件
├── requirements.txt       # Python 依赖
├── README.md              # 本文件
└── profiles/              # 配置档案目录
    └── phone2.yaml        # (示例) 第二个手机的配置
```

### 模块关系

```
                        ┌─────────────────────┐
                        │    main.py (CLI)     │
                        │  配置 + Profile 管理  │
                        └─────┬───────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
      ┌────────────┐  ┌────────────┐  ┌────────────┐
      │ADBController│  │ScreenAnaly│  │ AutoPlayer │
      │ ADB/scrcpy  │  │ CV检测    │  │ 预测引擎    │
      │ 截图/触摸   │  │ 预测区域  │  │ NoteTracker│
      └────────────┘  └────────────┘  └────────────┘
              │               │               │
              └───────────────┴───────────────┘
                          ┌─────────┐
                          │ 手机    │
                          └─────────┘
```

## 进阶技巧

### 提升准确率

1. **校准**: 先运行 `calibrate` 获取准确的判定线和轨道位置
2. **亮度阈值**: 如果漏 note 就降低阈值 (`>` / `<` 热键), 如果误触就提高
3. **延迟补偿**: 运行 `test` 看实际延迟, `+` / `-` 热键实时调整
4. **预测引擎**: 默认启用, 如果需要禁用可设置 `prediction.enabled: false`

### 多手机支持

```bash
# 手机 1: 校准并保存
python main.py calibrate --profile phone1

# 手机 2: 连接另一台手机, 校准并保存
python main.py calibrate --profile phone2

# 启动时指定手机
python main.py start --profile phone1
```

### scrcpy 高帧率模式

1. 安装 scrcpy
2. 在 `config.yaml` 中设置:
   ```yaml
   adb:
     screencap_method: scrcpy
   scrcpy:
     max_fps: 60
     scale: 0.5
   ```
3. 启动自动打歌

## 局限性

- **ADB 延迟**: 即使有预测引擎, ADB 触摸延迟 ~50ms 仍然存在
- **帧率**: ADB screencap 5-15 FPS, 对高速谱面不够 (建议用 scrcpy)
- **Flick 方向**: 方向检测依赖于画面中箭头特效的可识别性
- **Hold 处理**: 通过短按压模拟长按, 不是真正的持续按住

## 未来改进方向

1. **minitouch** → 替代 ADB input, 触摸延迟从 ~50ms 降到 <5ms
2. **谱面解析** → 直接解析谱面文件, 完美时序
3. **ML 检测** → 用轻量模型识别 note 类型和方向
4. **Web UI** → 手机浏览器实时监控和控制
5. **AutoF4 风格轨道** → 自动识别复杂轨道布局

## 免责声明

本项目仅供学习和研究使用。使用自动化工具可能违反游戏的服务条款,
请自行承担风险。开发者不对任何账号封禁或其他后果负责。

## License

MIT
