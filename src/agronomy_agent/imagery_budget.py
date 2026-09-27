"""Admission-only storage limits for cooperating local imagery writers.

No cache entry is evicted. A process-held lock serializes writes across field
directories; process exit releases it, including after a worker timeout.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import stat
from typing import Iterator

DEFAULT_MAX_CACHE_BYTES = 2 * 1024**3
DEFAULT_MIN_FREE_BYTES = 1024**3
MAX_NEW_CHIP_BYTES = 16 * 1024**2
MAX_ENTRIES = 100_000


class StorageRefusal(RuntimeError):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def validate_policy(max_cache_bytes: int, min_free_bytes: int) -> None:
    if type(max_cache_bytes) is not int or max_cache_bytes <= 0:
        raise ValueError("imagery cache limit must be a positive integer")
    if type(min_free_bytes) is not int or min_free_bytes < 0:
        raise ValueError("imagery free-space reserve must be a nonnegative integer")


def cache_bytes(root: Path) -> int:
    """Count bounded logical bytes without following links or special files."""
    total = entries = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        if directory.is_symlink():
            raise StorageRefusal("storage_unavailable", "cache_contains_symlink")
        with os.scandir(directory) as children:
            for child in children:
                entries += 1
                if entries > MAX_ENTRIES:
                    raise StorageRefusal("storage_unavailable", "cache_inventory_limit")
                info = child.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(Path(child.path))
                elif stat.S_ISREG(info.st_mode):
                    total += info.st_size
                else:
                    raise StorageRefusal("storage_unavailable", "cache_contains_unsupported_entry")
    return total


class CacheAdmission:
    def __init__(self, root: Path, max_cache_bytes: int, min_free_bytes: int):
        self.root = root
        self.max_cache_bytes = max_cache_bytes
        self.min_free_bytes = min_free_bytes

    def ensure(self, additional_bytes: int = MAX_NEW_CHIP_BYTES) -> None:
        if not 0 <= additional_bytes <= MAX_NEW_CHIP_BYTES:
            raise StorageRefusal("storage_limit", "chip_exceeds_storage_reservation")
        if cache_bytes(self.root) + additional_bytes > self.max_cache_bytes:
            raise StorageRefusal("storage_limit", "imagery_cache_capacity_reached")
        if shutil.disk_usage(self.root).free < self.min_free_bytes + additional_bytes:
            raise StorageRefusal("storage_limit", "free_disk_reserve_reached")


@contextmanager
def reserve_cache(root: Path, *, max_cache_bytes: int = DEFAULT_MAX_CACHE_BYTES,
                  min_free_bytes: int = DEFAULT_MIN_FREE_BYTES) -> Iterator[CacheAdmission]:
    validate_policy(max_cache_bytes, min_free_bytes)
    supplied = Path(root).expanduser()
    if supplied.is_symlink():
        raise StorageRefusal("storage_unavailable", "cache_root_is_symlink")
    root = supplied.resolve()
    anchor = root
    while not anchor.exists():
        anchor = anchor.parent
    if shutil.disk_usage(anchor).free < min_free_bytes + MAX_NEW_CHIP_BYTES:
        raise StorageRefusal("storage_limit", "free_disk_reserve_reached")
    try:
        import fcntl
    except ImportError as exc:
        raise StorageRefusal("storage_unavailable", "platform_lock_unavailable") from exc
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)
    lock_path = root / ".imagery-writer.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise StorageRefusal("storage_unavailable", "invalid_cache_lock")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StorageRefusal("busy", "imagery_cache_writer_busy") from exc
        admission = CacheAdmission(root, max_cache_bytes, min_free_bytes)
        admission.ensure()
        yield admission
    finally:
        os.close(fd)
