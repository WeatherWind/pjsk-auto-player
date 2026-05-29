"""测试异常体系 (exceptions.py)。"""

import pytest


class TestPjskError:
    """测试基础异常。"""

    def test_base_exception_creation(self):
        """创建基础异常。"""
        from exceptions import PjskError
        e = PjskError("test error")
        assert e.code == "UNKNOWN"
        assert e.message == "test error"
        assert str(e) == "test error"

    def test_exception_with_context(self):
        """异常携带上下文。"""
        from exceptions import PjskError
        e = PjskError(context={"frame": 42, "scene": "game"})
        assert e.context["frame"] == 42
        assert e.context["scene"] == "game"

    def test_default_message(self):
        """默认消息。"""
        from exceptions import GameStuckError
        e = GameStuckError()
        assert "画面" in e.message

    def test_custom_message_overrides_default(self):
        """自定义消息覆盖默认。"""
        from exceptions import GameStuckError
        e = GameStuckError("卡住了!")
        assert e.message == "卡住了!"


class TestErrorHierarchy:
    """测试异常层级。"""

    def test_game_stuck_is_recoverable(self):
        from exceptions import GameStuckError
        assert GameStuckError().recoverable is True

    def test_config_error_is_not_recoverable(self):
        from exceptions import ConfigError
        assert ConfigError().recoverable is False

    def test_all_error_codes_unique(self):
        """所有异常代码必须唯一。"""
        from exceptions import PjskError
        codes = set()
        for cls in PjskError.__subclasses__():
            code = cls.code
            assert code not in codes, f"Duplicate code: {code}"
            codes.add(code)

    def test_request_human_takeover(self):
        from exceptions import RequestHumanTakeover
        e = RequestHumanTakeover()
        assert e.code == "HUMAN_TAKEOVER"
        assert e.should_notify is True

    def test_song_select_error(self):
        from exceptions import SongSelectError
        assert SongSelectError().code == "SONG_SELECT_ERROR"

    def test_resource_exhausted_error(self):
        from exceptions import ResourceExhaustedError
        assert ResourceExhaustedError().code == "RESOURCE_EXHAUSTED"


class TestRecoveryStrategies:
    """测试恢复策略。"""

    def test_all_error_codes_have_strategy(self):
        """所有异常代码都有恢复策略。"""
        from exceptions import (
            PjskError,
            DEFAULT_RECOVERY_STRATEGIES,
        )
        for cls in PjskError.__subclasses__():
            assert cls.code in DEFAULT_RECOVERY_STRATEGIES, (
                f"Missing strategy for {cls.code}"
            )

    def test_recovery_strategy_has_required_fields(self):
        """恢复策略包含必需字段。"""
        from exceptions import get_recovery_strategy
        strategy = get_recovery_strategy("GAME_STUCK")
        assert "action" in strategy
        assert "retry_delay" in strategy
        assert "max_retries" in strategy

    def test_unknown_code_returns_stop(self):
        """未知错误代码返回 stop 策略。"""
        from exceptions import get_recovery_strategy
        strategy = get_recovery_strategy("NONEXISTENT_ERROR")
        assert strategy["action"] == "stop"


class TestClassifyError:
    """测试异常分类。"""

    def test_pjsk_error_passes_through(self):
        from exceptions import classify_error, GameStuckError
        e = GameStuckError()
        result = classify_error(e)
        assert isinstance(result, GameStuckError)

    def test_timeout_error_converted(self):
        from exceptions import classify_error, TaskTimeoutError
        e = TimeoutError("timeout!")
        result = classify_error(e)
        assert isinstance(result, TaskTimeoutError)

    def test_connection_error_converted(self):
        from exceptions import classify_error, ConnectionLostError
        e = ConnectionError("connection lost!")
        result = classify_error(e)
        assert isinstance(result, ConnectionLostError)

    def test_unknown_error_gets_wrapped(self):
        from exceptions import classify_error
        e = ValueError("unexpected")
        result = classify_error(e)
        assert result.code != "UNKNOWN"
