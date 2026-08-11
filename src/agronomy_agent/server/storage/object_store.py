from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from agronomy_agent.server.settings import ServerSettings


@dataclass(frozen=True)
class StoredObject:
    uri: str
    path: Path | None
    size_bytes: int


class ObjectStorePreflightError(RuntimeError):
    """Raised when the configured object store cannot safely serve artifacts."""


@dataclass(frozen=True)
class ObjectStorePreflightResult:
    backend: str
    bucket: str | None
    endpoint: str | None
    probe_key: str | None
    bucket_created: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "bucket": self.bucket,
            "endpoint": self.endpoint,
            "probe_key": self.probe_key,
            "bucket_created": self.bucket_created,
        }


class LocalObjectStore:
    """Filesystem-backed object-store boundary for local/dev hosted artifacts."""

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
        """Return a portable object key suitable for durable application metadata."""
        return self._key_from_uri(uri)

    def preflight(self) -> ObjectStorePreflightResult:
        self.root.mkdir(parents=True, exist_ok=True)
        probe = self.put_bytes(".phase4-preflight/probe.txt", b"agronomy-agent-object-store-preflight")
        try:
            if self.get_bytes(probe.uri) != b"agronomy-agent-object-store-preflight":
                raise ObjectStorePreflightError("local object-store readback mismatch")
        finally:
            self.delete_uri(probe.uri)
        return ObjectStorePreflightResult(backend="local", bucket=None, endpoint=None, probe_key=None)

    def _key_from_uri(self, uri: str) -> str:
        path = Path(uri)
        if path.is_absolute():
            resolved = path.resolve()
            if self.root != resolved and self.root not in resolved.parents:
                raise ValueError(f"object uri is outside storage root: {uri}")
            return str(resolved.relative_to(self.root))
        return uri


class S3ObjectStore:
    """Small S3-compatible object store adapter using AWS Signature V4.

    The adapter intentionally covers only the operations the hosted foundation
    needs today: write bytes/text/json artifacts and tombstone/delete objects.
    It uses path-style URLs so MinIO and common S3-compatible stores work with
    the same request shape.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        opener: Callable[[Request], Any] = urlopen,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket.strip()
        self.access_key = access_key.strip()
        self.secret_key = secret_key
        self.region = region.strip()
        self._opener = opener
        self._now = now or (lambda: dt.datetime.now(dt.timezone.utc))
        if not self.endpoint:
            raise ValueError("S3 object store endpoint is required")
        if not self.bucket:
            raise ValueError("S3 object store bucket is required")
        if not self.access_key:
            raise ValueError("S3 object store access key is required")
        if not self.secret_key:
            raise ValueError("S3 object store secret key is required")
        if not self.region:
            raise ValueError("S3 object store region is required")

    def put_bytes(self, key: str, content: bytes) -> StoredObject:
        normalized = self._normalize_key(key)
        request = self._signed_request(
            method="PUT",
            key=normalized,
            content=content,
            content_type="application/octet-stream",
        )
        self._send(request)
        return StoredObject(uri=f"s3://{self.bucket}/{normalized}", path=None, size_bytes=len(content))

    def put_text(self, key: str, content: str) -> StoredObject:
        return self.put_bytes(key, content.encode("utf-8"))

    def put_json(self, key: str, payload: Any) -> StoredObject:
        return self.put_text(key, json.dumps(payload, indent=2))

    def delete_uri(self, uri: str) -> bool:
        normalized = self._key_from_uri(uri)
        request = self._signed_request(method="DELETE", key=normalized, content=b"", content_type="application/octet-stream")
        try:
            self._send(request)
        except HTTPError as exc:
            if exc.code == 404:
                return False
            raise
        return True

    def file_path_for_uri(self, uri: str) -> Path:
        raise FileNotFoundError(f"S3 object does not have a local file path: {uri}")

    def get_bytes(self, uri: str) -> bytes:
        normalized = self._key_from_uri(uri)
        request = self._signed_request(method="GET", key=normalized, content=b"", content_type="application/octet-stream")
        return self._send(request)

    def reference_for_uri(self, uri: str) -> str:
        """Return a bucket-relative key suitable for durable application metadata."""
        return self._key_from_uri(uri)

    def preflight(self, *, create_bucket: bool = False, probe_prefix: str = ".phase4-preflight") -> ObjectStorePreflightResult:
        """Verify bucket access with a write/read/delete probe.

        The probe is intentionally a real object round-trip: a successful bucket
        HEAD alone does not prove the credentials can write exports, read private
        attachments, or clean up tombstoned objects.
        """

        bucket_created = False
        try:
            self._head_bucket()
        except HTTPError as exc:
            if exc.code != 404 or not create_bucket:
                raise ObjectStorePreflightError(self._http_error_message("S3 bucket preflight failed", exc)) from exc
            self._create_bucket()
            bucket_created = True
            self._head_bucket()
        except URLError as exc:
            raise ObjectStorePreflightError(f"S3 bucket preflight failed: {exc.reason}") from exc

        probe_key = f"{self._normalize_key(probe_prefix)}/probe.txt"
        payload = b"agronomy-agent-object-store-preflight"
        wrote_probe = False
        try:
            self.put_bytes(probe_key, payload)
            wrote_probe = True
            observed = self.get_bytes(f"s3://{self.bucket}/{probe_key}")
            if observed != payload:
                raise ObjectStorePreflightError("S3 bucket preflight failed: probe readback mismatch")
        except HTTPError as exc:
            raise ObjectStorePreflightError(self._http_error_message("S3 bucket preflight failed", exc)) from exc
        except URLError as exc:
            raise ObjectStorePreflightError(f"S3 bucket preflight failed: {exc.reason}") from exc
        finally:
            if wrote_probe:
                try:
                    self.delete_uri(f"s3://{self.bucket}/{probe_key}")
                except HTTPError as exc:
                    raise ObjectStorePreflightError(self._http_error_message("S3 bucket preflight cleanup failed", exc)) from exc
                except URLError as exc:
                    raise ObjectStorePreflightError(f"S3 bucket preflight cleanup failed: {exc.reason}") from exc
        return ObjectStorePreflightResult(
            backend="s3",
            bucket=self.bucket,
            endpoint=self.endpoint,
            probe_key=probe_key,
            bucket_created=bucket_created,
        )

    def _head_bucket(self) -> None:
        self._send(self._signed_bucket_request(method="HEAD"))

    def _create_bucket(self) -> None:
        self._send(self._signed_bucket_request(method="PUT"))

    def _send(self, request: Request) -> bytes:
        response = self._opener(request)
        close = getattr(response, "close", None)
        try:
            read = getattr(response, "read", None)
            if callable(read):
                payload = read()
                return payload if isinstance(payload, bytes) else b""
            return b""
        finally:
            if callable(close):
                close()

    def _signed_request(self, *, method: str, key: str, content: bytes, content_type: str) -> Request:
        normalized = self._normalize_key(key)
        return self._signed_request_for_path(
            method=method,
            canonical_uri=self._canonical_uri(normalized),
            content=content,
            content_type=content_type,
        )

    def _signed_bucket_request(self, *, method: str) -> Request:
        return self._signed_request_for_path(
            method=method,
            canonical_uri=self._canonical_uri(None),
            content=b"",
            content_type="application/octet-stream",
        )

    def _signed_request_for_path(self, *, method: str, canonical_uri: str, content: bytes, content_type: str) -> Request:
        timestamp = self._now()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
        timestamp = timestamp.astimezone(dt.timezone.utc)
        amz_date = timestamp.strftime("%Y%m%dT%H%M%SZ")
        date_scope = timestamp.strftime("%Y%m%d")
        parsed = urlparse(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("S3 endpoint must be an http(s) URL")
        url = f"{self.endpoint}{canonical_uri}"
        payload_hash = hashlib.sha256(content).hexdigest()
        headers = {
            "content-type": content_type,
            "host": parsed.netloc,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in sorted(headers))
        canonical_request = "\n".join([method, canonical_uri, "", canonical_headers, signed_headers, payload_hash])
        credential_scope = f"{date_scope}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(
            self._signing_key(date_scope),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers["authorization"] = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return Request(url, data=content if method not in {"DELETE", "GET", "HEAD"} else None, headers=headers, method=method)

    def _canonical_uri(self, key: str | None) -> str:
        segments = [self.bucket] if key is None else [self.bucket, *key.split("/")]
        return "/" + "/".join(quote(segment, safe="") for segment in segments)

    def _signing_key(self, date_scope: str) -> bytes:
        date_key = hmac.new(f"AWS4{self.secret_key}".encode("utf-8"), date_scope.encode("utf-8"), hashlib.sha256).digest()
        region_key = hmac.new(date_key, self.region.encode("utf-8"), hashlib.sha256).digest()
        service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
        return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()

    def _normalize_key(self, key: str) -> str:
        normalized = key.strip().lstrip("/")
        if not normalized:
            raise ValueError("object key is required")
        parts = Path(normalized).parts
        if any(part in {"..", ""} for part in parts):
            raise ValueError(f"object key escapes bucket root: {key}")
        return "/".join(parts)

    def _key_from_uri(self, uri: str) -> str:
        if uri.startswith("s3://"):
            parsed = urlparse(uri)
            if parsed.netloc != self.bucket:
                raise ValueError(f"object uri is outside configured bucket: {uri}")
            return self._normalize_key(parsed.path)
        return self._normalize_key(uri)

    def _http_error_message(self, prefix: str, exc: HTTPError) -> str:
        if exc.code == 403:
            reason = "access denied"
        elif exc.code == 404:
            reason = "bucket or object not found"
        else:
            reason = (exc.reason or "request failed").strip()
        return f"{prefix}: HTTP {exc.code} {reason}"


def build_object_store(settings: ServerSettings) -> LocalObjectStore | S3ObjectStore:
    if settings.object_store_backend == "local":
        return LocalObjectStore(settings.artifact_root)
    missing = [
        name
        for name, value in {
            "AGRONOMY_AGENT_OBJECT_STORE_ENDPOINT": settings.object_store_endpoint,
            "AGRONOMY_AGENT_OBJECT_STORE_BUCKET": settings.object_store_bucket,
            "AGRONOMY_AGENT_OBJECT_STORE_ACCESS_KEY": settings.object_store_access_key,
            "AGRONOMY_AGENT_OBJECT_STORE_SECRET_KEY": settings.object_store_secret_key,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"S3 object store configuration missing: {', '.join(missing)}")
    return S3ObjectStore(
        endpoint=str(settings.object_store_endpoint),
        bucket=str(settings.object_store_bucket),
        access_key=str(settings.object_store_access_key),
        secret_key=str(settings.object_store_secret_key),
        region=settings.object_store_region,
    )
