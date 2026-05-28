# PJSK Auto Player

> 基于 ADB + OpenCV 的 Project Sekai (プロジェクトセカイ) 自动打歌 AP 工具。
> 在 Windows 电脑上运行, 通过 USB 连接安卓手机, 自动完成打歌操作。

## 工作原理

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  ADB 截图     │ ──► │  OpenCV 分析  │ ──► │  ADB 触摸    │
│  手机画面     │     │  检测note位置  │     │  点击/滑动   │
└──────────────┘     └──────────────┘     └──────────────┘
       ↑                      ↑                     ↑
   ~100ms/帧            ~10ms/帧              ~50ms/次
```

核心思路: 通过 ADB 不断截取手机屏幕 → OpenCV 识别判定线上的 note → ADB 发送触摸。

### 检测策略

- **亮度法 (默认)**: 判定线区域找亮色轮廓 (PJSK 的 note 在深色背景上非常亮)
- **颜色法**: HSV 颜色空间匹配 note 特征 (白色中心 + 彩色边缘)
- **Hold 检测**: 同一轨道连续多帧检测到 -> 判定为长按
- **Flick 检测**: Sobel 梯度分析箭头方向

## 环境要求

| 组件 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 (本代码也兼容 macOS/Linux) |
| Python | 3.8+ |
| 手机 | 安卓手机, 已开启 USB 调试 |
| 数据线 | USB 数据线 (建议原装线) |
| 游戏 | Project Sekai (プロジェクトセカイ) 已安装 |

## 安装步骤

### 1. 安装 Python

从 [python.org](https://www.python.org/downloads/) 下载 Python 3.8+,
安装时**务必勾选** "Add Python to PATH"。

验证安装:
```
python --version
```

### 2. 安装 ADB (Android Debug Bridge)

**方法一: 通过 Android Studio (推荐)**
- 下载 [Android SDK Platform Tools](https://developer.android.com/studio/releases/platform-tools)
- 解压到一个目录 (如 `C:\adb`)
- **把该目录添加到系统 PATH 环境变量**

**方法二: 通过 Scoop (如果安装了 Scoop)**
```
scoop install adb
```

验证安装:
```
adb --version
```

### 3. 手机设置

1. 开启「开发者选项」:
   - 设置 → 关于手机 → 连续点击「版本号」7 次
2. 开启「USB 调试」:
   - 设置 → 开发者选项 → USB 调试 → 开启
3. 连接电脑:
   - 用 USB 线连接手机
   - 手机上弹出授权对话框 → 勾选「一律允许」→ 确定
4. 验证连接:
   ```
   adb devices
   ```
   应显示 `xxxxxxx device`

> **⚠️ 重要**: 某些手机需要开启「禁止权限监控」或「关闭 MIUI 优化」(小米),
> 否则 ADB screencap 可能失败。华为/荣耀需要开启「允许 ADB 调试在充电模式修」。

### 4. 下载本项目

```
git clone https://github.com/WeatherWind/pjsk-auto-player.git
cd pjsk-auto-player
```

或者直接下载 ZIP 解压。

### 5. 安装 Python 依赖

```
pip install -r requirements.txt
```

可选 (用于自动轨道校准):
```
pip install scipy
```

## 使用指南

### 第一步: 测试连接

```bash
python main.py test
```

正常输出:
```
✅ 检测到 1 台设备
✅ 截图成功: 1080x2400
   截图延迟: 89.3ms
   触摸延迟: 42.1ms
```

### 第二步: 校准参数

**方法 A: 自动校准** (推荐先试这个)
```bash
python main.py calibrate
```
会测量延迟、截图分析判定线和轨道位置, 输出建议配置。

**方法 B: 交互式校准** (需要电脑有显示器)
```bash
python main.py calibrate --interactive
```
会打开实时预览窗口:
- `q` - 退出
- `r` - 自动重新校准判定线
- `+/-` - 微调判定线 Y 位置
- `</>` - 调整亮度阈值

> 校准后请把输出的参数更新到 `config.yaml` 中。

### 第三步: 启动自动打歌

```bash
python main.py start
```

流程:
1. 确保手机已连接
2. 在手机上打开 PJSK, 选好歌曲和难度
3. 进入打歌准备界面 (选好支援成员, 等待开始)
4. 在电脑上按 Enter
5. 程序会自动等待进入打歌画面 → 开始检测 → 自动点击

**按 Ctrl+C 停止。**

## 配置说明

### 屏幕参数 (`screen` 部分)

最关键的部分, 需要根据你的手机分辨率校准。

`config.yaml` 中:
```yaml
screen:
  width: 1080         # 手机宽度 (像素)
  height: 2400        # 手机高度 (像素)
  judgment_line_y: 0.78   # 判定线 Y (比例 0~1)
  left_lanes: [0.15, 0.25, 0.35]   # 左侧 3 条轨道 X
  right_lanes: [0.65, 0.75, 0.85]  # 右侧 3 条轨道 X
```

运行 `python main.py calibrate` 会自动测量这些值。

### 检测参数

```yaml
detection:
  method: "brightness"       # brightness 或 color
  brightness:
    threshold: 200           # 亮度阈值 (越高越严格, 只检测很亮的 note)
    min_contour_area: 50     # 最小轮廓面积 (过滤噪点)
    max_contour_area: 500    # 最大轮廓面积 (过滤大 UI 元素)
```

- **阈值太高** → 漏掉 note (假阴性, 导致 MISS)
- **阈值太低** → 误触 (特效被当作 note, 导致 BAD/MISS)

### 延迟补偿

```yaml
timing:
  latency_compensation_ms: 0   # 延迟补偿 (毫秒, 正值=提前触发)
```

延迟来源:
- `screencap`: ADB 截图传输 ~50~200ms
- `processing`: OpenCV 分析 ~5~30ms
- `touch`: ADB 触摸 ~30~100ms

总延迟通常 100~300ms。对于 PJSK 的 PERFECT 判定 (~±33ms),
**纯反应式太慢**。

更好的方案是:
1. 先用 `python main.py calibrate` 测出总延迟
2. 设置 `latency_compensation_ms` 为总延迟的值
3. 这样程序会提前触发 = 检测到 note 时立即发送触摸,
   结合网络延迟实际刚好在 note 到达判定线时触发

## 架构

```
pjsk-auto-player/
├── main.py               # CLI 入口
├── adb_controller.py     # ADB 控制 (截图/触摸/设备管理)
├── screen_analyzer.py    # 画面分析 (CV 检测 note)
├── auto_play.py          # 自动打歌引擎 (主循环 + 校准)
├── config.yaml           # 配置文件
├── requirements.txt      # Python 依赖
└── README.md             # 本文件
```

## 进阶: 使用 scrcpy 提升性能

纯 ADB screencap 帧率低 (5-10 FPS), 用 [scrcpy](https://github.com/Genymobile/scrcpy) 可达到 30-60 FPS:

1. 安装 scrcpy:
   ```
   scoop install scrcpy   # 或用 winget
   ```

2. 修改 `adb_controller.py`, 增加 scrcpy 截图后端的支持:
   利用 `scrcpy --no-control` 以 30+ FPS 输出视频流,
   用 OpenCV 读取视频帧进行分析。

## 局限性

- **帧率瓶颈**: ADB exec-out screencap 约 5-15 FPS, 对高速谱面不够
- **延迟问题**: ADB 触摸路径较长, 低延迟手机 ~50ms, 有些手机 >100ms
- **AP 难度**: 纯反应式 + ADB 延迟, 目前更适合 MAS 以下难度,
  AP 需要结合**预测算法** (提前检测刚出现的 note, 计算到达时间)
- **Flick 检测**: 方向检测准确性取决于游戏画面, 可能需要多次校准

## 未来改进方向

1. **scrcpy 视频流** → 30+ FPS 实时分析
2. **minitouch** → 替代 ADB input, 触摸延迟 <5ms
3. **预测算法** → 检测 note 刚出现位置, 按 BPM 计算到达时间
4. **AutoF4 风格的轨道识别** → ML 模型识别轨道布局
5. **谱面解析** → 直接解析谱面文件, 完美时序

## 免责声明

本项目仅供学习和研究使用。使用自动化工具可能违反游戏的服务条款,
请自行承担风险。开发者不对任何账号封禁或其他后果负责。

## License

MIT
