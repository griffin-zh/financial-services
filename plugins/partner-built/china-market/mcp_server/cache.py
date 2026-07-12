"""Cache abstraction for the china-market MCP server.

架构预留 (依赖倒置):调用方 (server.py 的 tool) 只依赖 `Cache` 抽象接口。
当前单机实现 = 本地 parquet (历史 bars, 不变数据) + 内存 TTL (实时快照, 短 TTL)。
未来产品化 (100 用户) 时把实现换成 RedisCache / PostgresCache, 并把「请求时拉」
改成后台 IngestionJob「定时入库」—— server.py 调用方零改动。这是平滑演进点。
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

import pandas as pd


class Cache(ABC):
    """键值缓存抽象。value 可以是任意 JSON-safe 对象或 DataFrame。"""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """命中返回 value, 未命中 / 过期返回 None。"""

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """写入 value。ttl 单位秒, None 表示用实现默认 / 永不过期。"""


class InMemoryTTLCache(Cache):
    """线程安全的内存 TTL 缓存, 用于实时快照 (短 TTL, 默认 5s)。

    多 tool 并发调用共享同一实例, 所以用 Lock 保护。TTL 内重复查同一 symbol
    直接命中, 不重复打上游 —— 这是 100 用户场景「客户并发 != 上游调用」的雏形。
    """

    def __init__(self, default_ttl: float = 5.0) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, value = item
            if time.monotonic() >= expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        ttl = self._default_ttl if ttl is None else ttl
        with self._lock:
            self._store[key] = (time.monotonic() + ttl, value)


class LocalParquetCache(Cache):
    """按 key (通常是 symbol) 存整段 DataFrame 到 parquet, 用于历史日线。

    历史 bars 是不变数据, ttl 无意义 (忽略)。兼容既有 data_cache/market/ 里
    已有的 <symbol>.parquet。get 返回整段 df, 上层再按 date range 过滤。
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self._root / f"{key}.parquet"

    def get(self, key: str) -> Optional[pd.DataFrame]:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return pd.read_parquet(p)
        except Exception:  # noqa: BLE001 — 坏缓存当未命中处理
            return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        if value is None or getattr(value, "empty", True):
            return
        try:
            value.to_parquet(self._path(key), index=False)
        except Exception:  # noqa: BLE001 — 写缓存失败不应影响主流程
            pass


class DictCache(Cache):
    """纯内存字典缓存 (无 TTL), 主要用于测试「缓存接口可替换性」。

    验证 server.py tool 只依赖 Cache 抽象: 注入本实现应零改动跑通。
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(self, key: str) -> Optional[Any]:
        return self._store.get(key)

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self._store[key] = value
