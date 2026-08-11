from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.request import Request, urlopen

from agronomy_agent.server.settings import ServerSettings


class AttachmentScanError(RuntimeError):
    pass


class AttachmentRejected(AttachmentScanError):
    pass


@dataclass(frozen=True)
class AttachmentScanInput:
    content: bytes
    filename: str
    content_type: str


class LocalAttachmentScanner:
    backend = "local"
    engine = "local_eicar_signature_stub"

    def scan(self, scan_input: AttachmentScanInput) -> dict[str, Any]:
        if not scan_input.content:
            raise AttachmentRejected("attachment is empty")
        if b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR" in scan_input.content:
            raise AttachmentRejected("attachment failed local malware signature scan")
        return {
            "scan_status": "passed_local_signature_stub",
            "scan_engine": self.engine,
            "scan_backend": self.backend,
            "content_type_validated": scan_input.content_type,
            "original_filename": scan_input.filename,
        }


class HttpAttachmentScanner:
    backend = "http"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if not endpoint.strip():
            raise ValueError("attachment scan endpoint is required")
        if timeout_seconds <= 0:
            raise ValueError("attachment scan timeout must be > 0")
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def scan(self, scan_input: AttachmentScanInput) -> dict[str, Any]:
        if not scan_input.content:
            raise AttachmentRejected("attachment is empty")
        payload = {
            "filename": scan_input.filename,
            "content_type": scan_input.content_type,
            "size_bytes": len(scan_input.content),
            "sha256": hashlib.sha256(scan_input.content).hexdigest(),
            "content_base64": base64.b64encode(scan_input.content).decode("ascii"),
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            response = self._opener(request, timeout=self.timeout_seconds)
            raw = response.read()
            status = int(getattr(response, "status", 200))
            response_payload = json.loads(raw.decode("utf-8"))
        except AttachmentScanError:
            raise
        except Exception as exc:
            raise AttachmentScanError(f"attachment scan provider unavailable: {exc}") from exc
        if status >= 400:
            raise AttachmentScanError(f"attachment scan provider returned HTTP {status}")
        if not isinstance(response_payload, dict):
            raise AttachmentScanError("attachment scan provider returned invalid JSON")
        verdict = str(response_payload.get("verdict") or response_payload.get("scan_status") or "").strip().lower()
        if verdict not in {"clean", "passed", "allow"}:
            reason = str(response_payload.get("reason") or response_payload.get("detail") or "attachment scan rejected file")
            raise AttachmentRejected(reason)
        engine = str(response_payload.get("engine") or "http_attachment_scanner")
        return {
            "scan_status": "passed_provider_scan",
            "scan_engine": engine,
            "scan_backend": self.backend,
            "scan_verdict": verdict,
            "scan_provider_reference": response_payload.get("reference") or response_payload.get("scan_id"),
            "content_type_validated": scan_input.content_type,
            "original_filename": scan_input.filename,
        }


def build_attachment_scanner(settings: ServerSettings) -> LocalAttachmentScanner | HttpAttachmentScanner:
    if settings.attachment_scan_backend == "http":
        if not settings.attachment_scan_endpoint:
            raise ValueError("AGRONOMY_AGENT_ATTACHMENT_SCAN_ENDPOINT is required when attachment scan backend is http")
        return HttpAttachmentScanner(
            endpoint=settings.attachment_scan_endpoint,
            api_key=settings.attachment_scan_api_key,
            timeout_seconds=settings.attachment_scan_timeout_seconds,
            opener=urlopen,
        )
    return LocalAttachmentScanner()
