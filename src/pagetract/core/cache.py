"""缓存系统 — 三层缓存架构（布局/VLM/文档）"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from pagetract.config import CacheConfig

logger = logging.getLogger(__name__)


class CacheManager:
    """三层缓存管理器"""

    def __init__(self, config: CacheConfig | None = None):
        self.config = config or CacheConfig()
        self._cache_dir = Path(self.config.directory)
        self._memory_cache: dict[str, tuple[float, Any]] = {}

        if self.config.enable:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self.config.enable

    # ----------------------------------------------------------
    # L1: 布局检测缓存
    # ----------------------------------------------------------

    def get_layout(self, pdf_hash: str, page_number: int) -> Any | None:
        if not self.enabled:
            return None
        key = f"layout:{pdf_hash}:{page_number}"
        return self._get(key, "layout", self.config.layout_cache_ttl_hours * 3600)

    def set_layout(self, pdf_hash: str, page_number: int, data: Any) -> None:
        if not self.enabled:
            return
        key = f"layout:{pdf_hash}:{page_number}"
        self._set(key, "layout", data)

    # ----------------------------------------------------------
    # L2: VLM 响应缓存
    # ----------------------------------------------------------

    def get_vlm(
        self,
        pdf_hash: str,
        page_number: int,
        bbox: tuple[int, int, int, int],
        block_type: str,
        model: str,
    ) -> str | None:
        if not self.enabled:
            return None
        key = f"vlm:{pdf_hash}:{page_number}:{bbox}:{block_type}:{model}"
        return self._get(key, "vlm", self.config.vlm_cache_ttl_days * 86400)

    def set_vlm(
        self,
        pdf_hash: str,
        page_number: int,
        bbox: tuple[int, int, int, int],
        block_type: str,
        model: str,
        content: str,
    ) -> None:
        if not self.enabled:
            return
        key = f"vlm:{pdf_hash}:{page_number}:{bbox}:{block_type}:{model}"
        self._set(key, "vlm", content)

    # ----------------------------------------------------------
    # L3: 文档完整结果缓存
    # ----------------------------------------------------------

    def get_document(self, pdf_hash: str, config_hash: str) -> Any | None:
        if not self.enabled:
            return None
        key = f"doc:{pdf_hash}:{config_hash}"
        return self._get(key, "document", self.config.document_cache_ttl_days * 86400)

    def set_document(self, pdf_hash: str, config_hash: str, data: Any) -> None:
        if not self.enabled:
            return
        key = f"doc:{pdf_hash}:{config_hash}"
        self._set(key, "document", data)

    # ----------------------------------------------------------
    # 内部实现
    # ----------------------------------------------------------

    def _get(self, key: str, tier: str, ttl_seconds: float) -> Any | None:
        cache_key = self._hash_key(key)

        # 内存缓存
        if cache_key in self._memory_cache:
            ts, data = self._memory_cache[cache_key]
            if time.time() - ts < ttl_seconds:
                return data
            del self._memory_cache[cache_key]

        # 磁盘缓存
        file_path = self._cache_dir / tier / f"{cache_key}.json"
        if file_path.exists():
            try:
                raw = json.loads(file_path.read_text(encoding="utf-8"))
                ts = raw.get("_timestamp", 0)
                if time.time() - ts < ttl_seconds:
                    data = raw.get("data")
                    self._memory_cache[cache_key] = (ts, data)
                    return data
                # 过期删除
                file_path.unlink(missing_ok=True)
            except Exception:
                pass

        return None

    def _set(self, key: str, tier: str, data: Any) -> None:
        cache_key = self._hash_key(key)
        ts = time.time()

        # 内存
        self._memory_cache[cache_key] = (ts, data)

        # 磁盘
        tier_dir = self._cache_dir / tier
        tier_dir.mkdir(parents=True, exist_ok=True)
        file_path = tier_dir / f"{cache_key}.json"

        try:
            payload = {"_timestamp": ts, "_key": key, "data": data}
            file_path.write_text(
                json.dumps(payload, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Cache write failed: %s", e)

    def clear(self, tier: str | None = None) -> int:
        """清理缓存，返回清理数量"""
        count = 0
        if tier:
            tier_dir = self._cache_dir / tier
            if tier_dir.exists():
                for f in tier_dir.glob("*.json"):
                    f.unlink()
                    count += 1
            # 清理对应 tier 的内存缓存
            to_remove = [k for k in self._memory_cache if k.startswith(self._hash_key(f"{tier}:")[:8]) or True]
            # 简单清理：清除所有内存缓存
            self._memory_cache.clear()
        else:
            for t in ("layout", "vlm", "document"):
                count += self.clear(t)
        return count

    def cleanup_expired(self) -> int:
        """清理所有过期条目"""
        count = 0
        ttl_map = {
            "layout": self.config.layout_cache_ttl_hours * 3600,
            "vlm": self.config.vlm_cache_ttl_days * 86400,
            "document": self.config.document_cache_ttl_days * 86400,
        }
        now = time.time()

        for tier, ttl in ttl_map.items():
            tier_dir = self._cache_dir / tier
            if not tier_dir.exists():
                continue
            for f in tier_dir.glob("*.json"):
                try:
                    raw = json.loads(f.read_text(encoding="utf-8"))
                    if now - raw.get("_timestamp", 0) > ttl:
                        f.unlink()
                        count += 1
                except Exception:
                    f.unlink(missing_ok=True)
                    count += 1

        return count

    # ----------------------------------------------------------
    # 工具
    # ----------------------------------------------------------

    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.md5(key.encode()).hexdigest()

    @staticmethod
    def compute_pdf_hash(pdf_path: str | Path) -> str:
        """计算 PDF 文件的 MD5 哈希"""
        h = hashlib.md5()
        with open(pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def compute_config_hash(config_dict: dict) -> str:
        """计算配置的哈希"""
        serialized = json.dumps(config_dict, sort_keys=True, default=str)
        return hashlib.md5(serialized.encode()).hexdigest()
