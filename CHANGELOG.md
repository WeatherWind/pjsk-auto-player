# Changelog

所有 notable 变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/).

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

