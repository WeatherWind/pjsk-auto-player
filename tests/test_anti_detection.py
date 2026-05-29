"""测试反检测模块 (lib/anti_detection.py)。"""

import math
import pytest


class TestBezierCurve:
    """测试贝塞尔曲线。"""

    def test_basic_curve(self):
        from lib.anti_detection import bezier_curve
        path = bezier_curve(0.1, 0.5, 0.9, 0.5, points=20)
        assert len(path) == 20
        # 起点
        assert abs(path[0][0] - 0.1) < 0.01
        assert abs(path[0][1] - 0.5) < 0.01
        # 终点
        assert abs(path[-1][0] - 0.9) < 0.01
        assert abs(path[-1][1] - 0.5) < 0.01

    def test_short_distance_returns_line(self):
        from lib.anti_detection import bezier_curve
        # 非常短的距离
        path = bezier_curve(0.5, 0.5, 0.5001, 0.5001, points=10)
        assert len(path) > 0

    def test_vertical_swipe(self):
        from lib.anti_detection import bezier_curve
        path = bezier_curve(0.5, 0.8, 0.5, 0.2, points=15)
        assert len(path) == 15
        # 起点和终点的 y 坐标
        assert path[0][1] > path[-1][1]  # 向上滑动

    def test_curve_is_smooth(self):
        """检查曲线是否平滑 (相邻点距离合理)。"""
        from lib.anti_detection import bezier_curve
        path = bezier_curve(0.2, 0.2, 0.8, 0.8, points=50)
        for i in range(len(path) - 1):
            dx = path[i+1][0] - path[i][0]
            dy = path[i+1][1] - path[i][1]
            dist = math.sqrt(dx**2 + dy**2)
            # 相邻点距离不应该超过总距离的 30%
            assert dist < 0.3, f"Step {i} too large: {dist}"


class TestHumanTouch:
    """测试 HumanTouch 模拟器。"""

    def test_jitter_within_range(self):
        from lib.anti_detection import HumanTouch, HumanTouchConfig
        config = HumanTouchConfig(position_jitter_px=5.0)
        ht = HumanTouch(config)
        for _ in range(100):
            x, y = ht.jitter(0.5, 0.5, screen_w=1080)
            # 抖动应该在 ±5px / 1080 范围内
            assert abs(x - 0.5) <= 5.5 / 1080
            assert abs(y - 0.5) <= 5.5 / 1080

    def test_random_delay_does_not_throw(self):
        from lib.anti_detection import HumanTouch
        ht = HumanTouch()
        ht.random_delay(base_ms=10)

    def test_reaction_delay_positive(self):
        from lib.anti_detection import HumanTouch
        ht = HumanTouch()
        for _ in range(20):
            delay = ht.reaction_delay()
            assert delay >= 50.0  # 最少 50ms

    def test_should_miss_probability(self):
        from lib.anti_detection import HumanTouch, HumanTouchConfig
        config = HumanTouchConfig(miss_chance=0.0)
        ht = HumanTouch(config)
        for _ in range(100):
            assert not ht.should_miss()

        config2 = HumanTouchConfig(miss_chance=1.0)
        ht2 = HumanTouch(config2)
        for _ in range(100):
            assert ht2.should_miss()

    def test_random_pressure_in_range(self):
        from lib.anti_detection import HumanTouch
        ht = HumanTouch()
        for _ in range(50):
            p = ht.random_pressure()
            assert 0.0 <= p <= 1.0

    def test_random_click_interval_in_range(self):
        from lib.anti_detection import HumanTouch
        ht = HumanTouch()
        for _ in range(50):
            interval = ht.random_click_interval(100, 500)
            assert 100 <= interval

    def test_hold_micro_movements(self):
        from lib.anti_detection import HumanTouch
        ht = HumanTouch()
        movements = ht.hold_micro_movements(0.5, 0.5, duration_ms=200)
        assert len(movements) > 0
        for x, y, delay in movements:
            assert 0 <= x <= 1
            assert 0 <= y <= 1
            assert delay > 0

    def test_flick_path_generates_bezier(self):
        from lib.anti_detection import HumanTouch
        ht = HumanTouch()
        path = ht.flick_path(0.1, 0.5, 0.9, 0.5)
        assert len(path) == 20
        # 起点和终点
        assert abs(path[0][0] - 0.1) < 0.01
        assert abs(path[-1][0] - 0.9) < 0.01


class TestGlobalTouch:
    """测试全局 HumanTouch 单例。"""

    def test_get_human_touch_returns_same_instance(self):
        from lib.anti_detection import get_human_touch, _global_touch
        # 重置
        import lib.anti_detection as ad
        ad._global_touch = None

        t1 = get_human_touch()
        t2 = get_human_touch()
        assert t1 is t2
