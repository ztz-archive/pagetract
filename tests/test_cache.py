"""测试缓存系统"""

import tempfile
from pathlib import Path

from pagetract.config import CacheConfig
from pagetract.core.cache import CacheManager


def test_cache_disabled():
    cache = CacheManager(CacheConfig(enable=False))
    cache.set_layout("hash1", 1, {"test": True})
    assert cache.get_layout("hash1", 1) is None


def test_cache_layout():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CacheManager(CacheConfig(enable=True, directory=tmpdir))
        data = [{"block_type": "text", "bbox": [0, 0, 100, 50]}]
        cache.set_layout("hash1", 1, data)

        result = cache.get_layout("hash1", 1)
        assert result is not None
        assert result[0]["block_type"] == "text"


def test_cache_vlm():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CacheManager(CacheConfig(enable=True, directory=tmpdir))
        cache.set_vlm("hash1", 1, (0, 0, 100, 50), "text", "qwen3.5-plus", "Hello World")

        result = cache.get_vlm("hash1", 1, (0, 0, 100, 50), "text", "qwen3.5-plus")
        assert result == "Hello World"


def test_cache_clear():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = CacheManager(CacheConfig(enable=True, directory=tmpdir))
        cache.set_layout("hash1", 1, {"test": True})
        count = cache.clear("layout")
        assert count >= 1
        assert cache.get_layout("hash1", 1) is None


def test_cache_hash():
    h1 = CacheManager._hash_key("test1")
    h2 = CacheManager._hash_key("test2")
    assert h1 != h2
    assert len(h1) == 32  # MD5
