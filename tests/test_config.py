"""测试配置系统"""

import os
import tempfile
from pathlib import Path

import yaml

from pagetract.config import (
    PagetractConfig,
    load_config,
    save_config,
    _deep_merge,
    _resolve_env_vars,
)


def test_default_config():
    cfg = PagetractConfig()
    assert cfg.general.render_dpi == 300
    assert cfg.vlm.model == "qwen3.5-plus"
    assert cfg.cache.enable is True
    assert cfg.layout.engine == "doclayout-yolo"


def test_deep_merge():
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    override = {"b": {"c": 99}, "e": 5}
    result = _deep_merge(base, override)
    assert result["b"]["c"] == 99
    assert result["b"]["d"] == 3
    assert result["e"] == 5


def test_resolve_env_vars():
    os.environ["TEST_VAR_123"] = "hello"
    assert _resolve_env_vars("${TEST_VAR_123}") == "hello"
    assert _resolve_env_vars("plain") == "plain"
    assert _resolve_env_vars(42) == 42
    del os.environ["TEST_VAR_123"]


def test_load_config_default():
    # 无配置文件时使用默认值
    cfg = load_config(config_path="nonexistent.yaml")
    assert cfg.general.render_dpi == 300


def test_load_config_with_overrides():
    cfg = load_config(
        config_path="nonexistent.yaml",
        overrides={"vlm": {"model": "qwen3.5-plus"}},
    )
    assert cfg.vlm.model == "qwen3.5-plus"


def test_save_and_load_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test_config.yaml"
        cfg = PagetractConfig()
        cfg.vlm.api_key = "secret"
        save_config(cfg, path)

        # 确认 API key 被替换
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["vlm"]["api_key"] == "${SCANDOC_API_KEY}"

        # 加载回来
        loaded = load_config(config_path=path)
        assert loaded.general.render_dpi == 300
