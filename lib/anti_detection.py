"""
PJSK Auto Player — 反检测增强模块 (v5.0.0)

模拟人工操作特征，用于人机交互研究：
  - 贝塞尔曲线滑动路径 (替代直线 swipe)
  - 触摸压力模拟 (随机力度变化)
  - 点击间隔随机化 (人类反应时间分布)
  - 长按微动模拟 (手指微小抖动)

用法:
    from lib.anti_detection import HumanTouch

    ht = HumanTouch()
    x, y = ht.jitter(0.5, 0.5)           # 坐标抖动
    path = ht.bezier_swipe(x1,y1, x2,y2)  # 贝塞尔曲线路径
    delay = ht.reaction_delay()           # 人类反应延迟
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable


# ═══════════════════════════════════════════════════════════════
# 贝塞尔曲线
# ═══════════════════════════════════════════════════════════════


def bezier_point(t: float, p0: float, p1: float, p2: float, p3: float) -> float:
    """三次贝塞尔曲线 B(t)。"""
    u = 1 - t
    return u**3 * p0 + 3 * u**2 * t * p1 + 3 * u * t**2 * p2 + t**3 * p3


def bezier_curve(
    x1: float, y1: float, x2: float, y2: float,
    points: int = 20,
    randomness: float = 0.02,
) -> list[tuple[float, float]]:
    """生成从 (x1,y1) 到 (x2,y2) 的贝塞尔曲线路径。

    人类手指滑动不是直线，而是带有弧度的曲线。
    贝塞尔曲线模拟这种自然轨迹。

    Args:
        x1, y1: 起点 (相对坐标 0~1)
        x2, y2: 终点 (相对坐标 0~1)
        points: 路径上的采样点数
        randomness: 控制点随机偏移量 (越大越弯曲)

    Returns:
        采样点列表 [(x, y), ...]
    """
    # 计算距离和方向
    dx = x2 - x1
    dy = y2 - y1
    dist = math.sqrt(dx**2 + dy**2)

    # 如果距离太短，直接返回直线
    if dist < 0.01:
        mid_x = (x1 + x2) / 2
        mid_y = (y1 + y2) / 2
        return [(x1, y1), (mid_x, mid_y), (x2, y2)]

    # 计算法线方向 (垂直于滑动方向)
    nx = -dy / dist
    ny = dx / dist

    # 控制点: 在路径中点两侧偏移
    offset = dist * randomness * random.uniform(0.5, 1.5)
    # 随机决定弯曲方向
    if random.random() < 0.5:
        offset = -offset

    cp1_x = x1 + dx * 0.3 + nx * offset * random.uniform(0.8, 1.2)
    cp1_y = y1 + dy * 0.3 + ny * offset * random.uniform(0.8, 1.2)
    cp2_x = x1 + dx * 0.7 + nx * offset * random.uniform(0.8, 1.2)
    cp2_y = y1 + dy * 0.7 + ny * offset * random.uniform(0.8, 1.2)

    # 生成路径
    path = []
    for i in range(points):
        t = i / max(points - 1, 1)
        x = bezier_point(t, x1, cp1_x, cp2_x, x2)
        y = bezier_point(t, y1, cp1_y, cp2_y, y2)
        path.append((x, y))

    return path


# ═══════════════════════════════════════════════════════════════
# 人类触摸模拟
# ═══════════════════════════════════════════════════════════════


@dataclass
class HumanTouchConfig:
    """人类触摸参数配置。"""
    # 坐标抖动
    position_jitter_px: float = 5.0      # ±像素
    # 时机抖动
    timing_jitter_ms: float = 15.0       # ±毫秒
    # 长按微动
    hold_micro_jitter_px: float = 2.0    # 长按时的微小抖动
    hold_micro_interval_ms: float = 50.0 # 微动间隔
    # 漏键概率
    miss_chance: float = 0.001           # 每帧漏键概率
    # 滑动
    bezier_points: int = 20              # 贝塞尔采样点
    bezier_randomness: float = 0.02      # 弯曲度
    # 反应时间
    reaction_mean_ms: float = 200.0      # 平均反应时间
    reaction_std_ms: float = 30.0        # 反应时间标准差
    # 压力模拟 (0~1)
    pressure_mean: float = 0.7
    pressure_std: float = 0.15


class HumanTouch:
    """人类触摸模拟器。

    为自动化操作注入人类特征，降低检测风险。

    用法:
        ht = HumanTouch()
        x_j, y_j = ht.jitter(x, y)           # 坐标抖动
        ht.random_delay()                     # 随机等待
        path = ht.flick_path(x1, y1, x2, y2) # Flick 路径
        pressure = ht.random_pressure()       # 随机压力
    """

    def __init__(self, config: HumanTouchConfig | None = None):
        self.config = config or HumanTouchConfig()

    # ── 坐标抖动 ──

    def jitter(self, x: float, y: float, screen_w: int = 1080) -> tuple[float, float]:
        """对坐标添加随机 ±N 像素抖动 (相对坐标)。"""
        cfg = self.config
        jx = random.uniform(-cfg.position_jitter_px, cfg.position_jitter_px) / screen_w
        jy = random.uniform(-cfg.position_jitter_px, cfg.position_jitter_px) / screen_w
        return (x + jx, y + jy)

    # ── 时机抖动 ──

    def random_delay(self, base_ms: float = 0) -> None:
        """随机等待 (基础延迟 + 抖动)。"""
        cfg = self.config
        jitter = random.uniform(-cfg.timing_jitter_ms, cfg.timing_jitter_ms)
        total = base_ms + jitter
        if total > 0:
            time.sleep(total / 1000.0)

    def reaction_delay(self) -> float:
        """模拟人类反应时间 (正态分布，单位毫秒)。"""
        cfg = self.config
        delay = random.gauss(cfg.reaction_mean_ms, cfg.reaction_std_ms)
        return max(50.0, delay)  # 最少 50ms

    # ── Flick / Swipe 路径 ──

    def flick_path(
        self, x1: float, y1: float, x2: float, y2: float,
    ) -> list[tuple[float, float]]:
        """生成贝塞尔曲线 Flick 路径。"""
        cfg = self.config
        return bezier_curve(
            x1, y1, x2, y2,
            points=cfg.bezier_points,
            randomness=cfg.bezier_randomness,
        )

    # ── 漏键判断 ──

    def should_miss(self) -> bool:
        """以 miss_chance 概率返回 True (模拟人类偶尔漏键)。"""
        return random.random() < self.config.miss_chance

    # ── 长按微动 ──

    def hold_micro_movements(
        self, x: float, y: float, duration_ms: float,
    ) -> list[tuple[float, float, float]]:
        """生成长按期间的微动序列。

        Returns:
            [(x, y, delay_ms), ...]  微动坐标 + 持续时间
        """
        cfg = self.config
        movements = []
        elapsed = 0.0
        interval = cfg.hold_micro_interval_ms
        screen_w = 1080  # 相对坐标归一化用

        while elapsed < duration_ms:
            jx, jy = self.jitter(x, y, screen_w)
            # 微动幅度小于普通抖动
            micro_jx = random.uniform(-cfg.hold_micro_jitter_px,
                                       cfg.hold_micro_jitter_px) / screen_w
            micro_jy = random.uniform(-cfg.hold_micro_jitter_px,
                                       cfg.hold_micro_jitter_px) / screen_w
            movements.append((jx + micro_jx, jy + micro_jy, interval))
            elapsed += interval

        return movements

    # ── 触摸压力 ──

    def random_pressure(self) -> float:
        """生成随机触摸压力 (0~1, 正态分布)。"""
        cfg = self.config
        p = random.gauss(cfg.pressure_mean, cfg.pressure_std)
        return max(0.1, min(1.0, p))

    # ── 随机化点击间隔 ──

    def random_click_interval(self, min_ms: float = 100, max_ms: float = 500) -> float:
        """生成随机点击间隔 (指数分布偏向短间隔，模拟连打节奏)。"""
        # 使用指数分布模拟连打: 大多数间隔较短，偶尔较长
        base = random.expovariate(1.0 / ((max_ms - min_ms) * 0.3))
        return min_ms + min(base, max_ms - min_ms)


# ═══════════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════════

_global_touch: HumanTouch | None = None


def get_human_touch() -> HumanTouch:
    """获取全局 HumanTouch 实例。"""
    global _global_touch
    if _global_touch is None:
        _global_touch = HumanTouch()
    return _global_touch

# v5.6.0: Session Fingerprint
from dataclasses import dataclass
import random

@dataclass
class SessionFingerprint:
    position_std_rel: float = 0.005
    timing_std_ms: float = 15.0
    bezier_randomness: float = 0.02
    miss_rate: float = 0.001
    hold_jitter_rel: float = 0.002
    reaction_base_ms: float = 60.0
    touch_duration_ms: float = 40.0
    max_consecutive_perfect: int = 0

    def __repr__(self):
        parts = []
        parts.append('pos_std=' + f'{self.position_std_rel:.4f}')
        parts.append('timing_std=' + f'{self.timing_std_ms:.1f}ms')
        parts.append('miss=' + f'{self.miss_rate:.4f}')
        parts.append('bezier=' + f'{self.bezier_randomness:.3f}')
        parts.append('max_perfect=' + str(self.max_consecutive_perfect))
        return 'SessionFingerprint(' + ', '.join(parts) + ')'


def gauss_jitter(value, std, clamp=3.0):
    j = random.gauss(0, std)
    j = max(-clamp * std, min(clamp * std, j))
    return value + j


def generate_session_fingerprint(mode="fc"):
    fp = SessionFingerprint()
    if mode == 'safe':
        fp.position_std_rel = random.uniform(0.004, 0.010)
        fp.timing_std_ms = random.uniform(12, 28)
        fp.bezier_randomness = random.uniform(0.02, 0.05)
        fp.miss_rate = random.choices([0, 0.0005, 0.001, 0.002], weights=[4,3,2,1])[0]
        fp.hold_jitter_rel = random.uniform(0.001, 0.004)
        fp.reaction_base_ms = random.uniform(50, 90)
        fp.touch_duration_ms = random.uniform(30, 60)
        fp.max_consecutive_perfect = random.randint(20, 80)
    elif mode == 'precision':
        fp.position_std_rel = random.uniform(0.001, 0.003)
        fp.timing_std_ms = random.uniform(3, 8)
        fp.bezier_randomness = random.uniform(0.005, 0.015)
        fp.miss_rate = 0.0
        fp.hold_jitter_rel = random.uniform(0.0005, 0.002)
        fp.reaction_base_ms = random.uniform(30, 50)
        fp.touch_duration_ms = random.uniform(25, 40)
        fp.max_consecutive_perfect = 0
    else:
        fp.position_std_rel = random.uniform(0.003, 0.006)
        fp.timing_std_ms = random.uniform(8, 18)
        fp.bezier_randomness = random.uniform(0.01, 0.03)
        fp.miss_rate = 0.0 if mode == 'ap' else random.uniform(0, 0.001)
        fp.hold_jitter_rel = random.uniform(0.001, 0.003)
        fp.reaction_base_ms = random.uniform(40, 70)
        fp.touch_duration_ms = random.uniform(30, 50)
        fp.max_consecutive_perfect = 0
    return fp
