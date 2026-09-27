from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoredObject:
    uri: str
    path: Path
    size_bytes: int


class LocalObjectStore:
    """Filesystem-backed artifact storage for the local-private runtime."""

    backend = "local"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def path_for_key(self, key: str) -> Path:
        normalized = key.strip().lstrip("/")
        if not normalized:
            raise ValueError("object key is required")
        path = (self.root / normalized).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError(f"object key escapes storage root: {key}")
        return path

    def put_bytes(self, key: str, content: bytes) -> StoredObject:
        path = self.path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        path.write_bytes(content)
        path.chmod(0o600)
        return StoredObject(uri=str(path), path=path, size_bytes=len(content))

    def put_text(self, key: str, content: str) -> StoredObject:
        return self.put_bytes(key, content.encode("utf-8"))

    def put_json(self, key: str, payload: Any) -> StoredObject:
        return self.put_text(key, json.dumps(payload, indent=2))

    def delete_uri(self, uri: str) -> bool:
        path = self.path_for_key(self._key_from_uri(uri))
        if path.is_dir():
            shutil.rmtree(path)
            return True
        if path.is_file():
            path.unlink()
            return True
        return False

    def file_path_for_uri(self, uri: str) -> Path:
        path = self.path_for_key(self._key_from_uri(uri))
        if not path.is_file():
            raise FileNotFoundError(uri)
        return path

    def get_bytes(self, uri: str) -> bytes:
        return self.file_path_for_uri(uri).read_bytes()

    def reference_for_uri(self, uri: str) -> str:
        """Return a root-relative key suitable for durable local metadata."""

        return self._key_from_uri(uri)

    def _key_from_uri(self, uri: str) -> str:
        path = Path(uri)
        if path.is_absolute():
            resolved = path.resolve()
            if self.root != resolved and self.root not in resolved.parents:
                raise ValueError(f"object uri is outside storage root: {uri}")
            return str(resolved.relative_to(self.root))
        return uri
