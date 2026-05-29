# Changelog

所有 notable 变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/),
版本号遵循 [Semantic Versioning](https://semver.org/).

## [4.4.0] - 2026-05-29

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

