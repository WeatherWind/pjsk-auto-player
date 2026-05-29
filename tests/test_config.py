"""测试配置系统 (config/)。"""

import pytest


class TestConfigLoader:
    """测试 ConfigLoader 分层加载。"""

    def test_ensure_defaults_fills_all_sections(self):
        """默认值填充所有必需的配置节。"""
        from config import get_config_loader
        loader = get_config_loader()
        # 不加载任何 profile 或 local 覆盖
        from config import get_default_config
        cfg = get_default_config()
        from config import _ensure_defaults
        cfg = _ensure_defaults({})

        required_sections = [
            "adb", "scrcpy", "minitouch", "screen", "play",
            "pid", "pipeline", "scene", "web", "notification",
            "logging", "hotkeys",
        ]
        for section in required_sections:
            assert section in cfg, f"Missing section: {section}"
            assert isinstance(cfg[section], dict), f"Section {section} not dict"

    def test_ensure_defaults_preserves_user_values(self):
        """用户值不被默认值覆盖。"""
        from config import _ensure_defaults
        user_cfg = {
            "play": {"mode": "ap"},
            "screen": {"judgment_line_y": 0.72},
        }
        result = _ensure_defaults(user_cfg)
        assert result["play"]["mode"] == "ap"
        assert result["screen"]["judgment_line_y"] == 0.72
        # 默认值仍然存在
        assert result["adb"]["executable"] == "adb"

    def test_deep_merge_nested(self):
        """递归合并嵌套字典。"""
        from config import ConfigLoader
        loader = ConfigLoader()
        base = {
            "a": {"x": 1, "y": 2},
            "b": 10,
        }
        override = {
            "a": {"y": 99, "z": 3},
        }
        result = loader._deep_merge(base, override)
        assert result["a"]["x"] == 1    # 保留
        assert result["a"]["y"] == 99   # 覆盖
        assert result["a"]["z"] == 3    # 新增
        assert result["b"] == 10        # 不变

    def test_deep_merge_does_not_mutate_base(self):
        """deep_merge 不修改原字典。"""
        from config import ConfigLoader
        loader = ConfigLoader()
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        result = loader._deep_merge(base, override)
        assert base["a"] == {"x": 1}  # 原字典不变
        assert result["a"] == {"x": 1, "y": 2}

    def test_set_local_override(self):
        """运行时覆盖。"""
        from config import get_config_loader
        loader = get_config_loader()
        loader.set_local_override("play.mode", "ap")
        cfg = loader.load()
        assert cfg["play"]["mode"] == "ap"


class TestConfigSchema:
    """测试配置 Schema 校验。"""

    def test_valid_config_passes(self, sample_config):
        """合法配置通过校验。"""
        from config.schema import validate_config
        errors = validate_config(sample_config)
        # 可能有 warning，但没有 error
        error_errors = [e for e in errors if e.severity == "error"]
        assert len(error_errors) == 0, f"Unexpected errors: {error_errors}"

    def test_invalid_type_reported(self):
        """类型错误被报告。"""
        from config.schema import validate_config
        cfg = {"play": {"mode": 123}}  # mode 应该是 str
        errors = validate_config(cfg)
        type_errors = [
            e for e in errors
            if "play.mode" in e.path and "类型" in e.message
        ]
        assert len(type_errors) > 0

    def test_invalid_choice_reported(self):
        """非法选项被报告。"""
        from config.schema import validate_config
        cfg = {"play": {"mode": "invalid_mode"}}
        errors = validate_config(cfg)
        choice_errors = [
            e for e in errors
            if "play.mode" in e.path
        ]
        assert len(choice_errors) > 0

    def test_portrait_warning(self):
        """横屏警告。"""
        from config.schema import validate_config
        cfg = {"screen": {"width": 2400, "height": 1080}}
        errors = validate_config(cfg)
        warnings = [e for e in errors if e.severity == "warning"]
        assert any("横屏" in str(e) for e in warnings)

    def test_generate_template_has_all_sections(self):
        """生成的模板包含所有配置节。"""
        from config.schema import generate_config_template
        template = generate_config_template()
        assert "adb" in template
        assert "screen" in template
        assert "play" in template

    def test_schema_for_frontend(self):
        """前端表单 Schema 生成。"""
        from config.schema import schema_for_frontend
        sections = schema_for_frontend()
        assert len(sections) > 5
        # 每个 section 有 label 和 properties
        for s in sections:
            assert "section" in s
            assert "properties" in s
            assert isinstance(s["properties"], list)
