from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Generic, TypeVar


T = TypeVar("T")
_FINGERPRINT_CACHE: dict[tuple[str, int, int, int], dict[str, object]] = {}
_FINGERPRINT_LOCK = RLock()


@dataclass(frozen=True)
class CacheResult(Generic[T]):
    value: T
    cache_status: str


class Phase5LRUCache(Generic[T]):
    """Small process-local LRU cache for deterministic routing/retrieval/KG work."""

    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max(1, max_entries)
        self._items: OrderedDict[Hashable, T] = OrderedDict()
        self._lock = RLock()
        self.hits = 0
        self.misses = 0

    def get_or_compute(self, key: Hashable, factory: Callable[[], T]) -> CacheResult[T]:
        with self._lock:
            if key in self._items:
                value = self._items.pop(key)
                self._items[key] = value
                self.hits += 1
                return CacheResult(value=value, cache_status="hit")
        value = factory()
        with self._lock:
            self._items[key] = value
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
            self.misses += 1
        return CacheResult(value=value, cache_status="miss")

    def get(self, key: Hashable) -> CacheResult[T] | None:
        with self._lock:
            if key not in self._items:
                self.misses += 1
                return None
            value = self._items.pop(key)
            self._items[key] = value
            self.hits += 1
            return CacheResult(value=value, cache_status="hit")

    def put(self, key: Hashable, value: T) -> None:
        with self._lock:
            self._items[key] = value
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"entries": len(self._items), "hits": self.hits, "misses": self.misses}

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self.hits = 0
            self.misses = 0


def stable_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_fingerprint(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    cache_key = (str(path.resolve()), int(getattr(stat, "st_ino", 0)), stat.st_size, stat.st_mtime_ns)
    with _FINGERPRINT_LOCK:
        cached = _FINGERPRINT_CACHE.get(cache_key)
        if cached is not None:
            return dict(cached)
    fingerprint = {
        "path": str(path),
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    with _FINGERPRINT_LOCK:
        _FINGERPRINT_CACHE[cache_key] = dict(fingerprint)
    return fingerprint
