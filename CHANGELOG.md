# Changelog

所有 notable 变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/).

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

