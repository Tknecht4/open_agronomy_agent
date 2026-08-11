from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from agronomy_agent.artifact_signature import sign_manifest, verify_manifest_signature


TRUST_POLICY_SCHEMA = "open_agronomy_agent.knowledge_update_trust_policy.v1"
TRUST_POLICY_SIGNATURE_NAME = "knowledge_update_trust_policy.sig"
MAX_FUTURE_CLOCK_SKEW = dt.timedelta(minutes=5)
MAX_POLICY_VALIDITY = dt.timedelta(days=366)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class TrustedUpdateKey:
    key_id: str
    public_key: ed25519.Ed25519PublicKey
    status: str
    not_before: dt.datetime
    not_after: dt.datetime
    revoked_at: dt.datetime | None
    revocation_reason: str | None


@dataclass(frozen=True)
class VerifiedKnowledgeUpdateTrustPolicy:
    policy_id: str
    policy_sequence: int
    threshold: int
    issued_at: dt.datetime
    expires_at: dt.datetime
    sha256: str
    root_public_key_sha256: str
    keys: dict[str, TrustedUpdateKey]
    source_path: Path

    def validate_freshness(
        self,
        *,
        now: dt.datetime | None = None,
    ) -> None:
        checked_at = _coerce_now(now)
        if checked_at < self.issued_at - MAX_FUTURE_CLOCK_SKEW:
            raise ValueError("knowledge update trust policy is not yet valid")
        if checked_at >= self.expires_at:
            raise ValueError("knowledge update trust policy has expired")

    def key_for_signature(
        self,
        key_id: str,
        *,
        signed_at: dt.datetime,
    ) -> TrustedUpdateKey:
        key = self.keys.get(key_id)
        if key is None:
            raise ValueError(f"knowledge update signing key is not trusted: {key_id}")
        if key.status != "active":
            raise ValueError(f"knowledge update signing key is revoked: {key_id}")
        if signed_at < key.not_before or signed_at > key.not_after:
            raise ValueError(
                f"knowledge update signing key was outside its authorized signing period: {key_id}"
            )
        return key


def ed25519_public_key_id(public_key: ed25519.Ed25519PublicKey) -> str:
    encoded = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(encoded).hexdigest()


def load_ed25519_public_key(path: Path) -> ed25519.Ed25519PublicKey:
    path = _safe_key_path(path, label="public key")
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise ValueError(f"expected an Ed25519 PEM public key: {path}")
    return key


def load_ed25519_private_key(path: Path) -> ed25519.Ed25519PrivateKey:
    path = _safe_key_path(path, label="private key")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise ValueError(f"expected an unencrypted Ed25519 PEM private key: {path}")
    return key


def private_key_id(path: Path) -> str:
    return ed25519_public_key_id(load_ed25519_private_key(path).public_key())


def build_knowledge_update_trust_policy(
    *,
    output_path: Path,
    signature_path: Path,
    root_private_key_path: Path,
    policy_id: str,
    policy_sequence: int,
    threshold: int,
    active_public_key_paths: Iterable[Path],
    expires_at: str | dt.datetime,
    revoked_public_key_paths: Iterable[Path] = (),
    revocation_reason: str = "operator_revocation",
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    issued_at = _coerce_now(now)
    expires = _parse_time(expires_at, field="expires_at")
    if expires <= issued_at:
        raise ValueError("trust policy expires_at must be after issued_at")
    if expires - issued_at > MAX_POLICY_VALIDITY:
        raise ValueError("trust policy validity must not exceed 366 days")
    policy_id = _safe_id(policy_id, label="policy_id")
    if isinstance(policy_sequence, bool) or not isinstance(policy_sequence, int) or policy_sequence < 1:
        raise ValueError("policy_sequence must be a positive integer")
    active_paths = [path.resolve() for path in active_public_key_paths]
    revoked_paths = [path.resolve() for path in revoked_public_key_paths]
    if not active_paths:
        raise ValueError("at least one active update signing key is required")
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 2:
        raise ValueError("threshold must be at least two for compromise resilience")
    if threshold > len(active_paths):
        raise ValueError("threshold cannot exceed the number of active update signing keys")
    if not revocation_reason.strip():
        raise ValueError("revocation_reason must be non-empty")

    keys: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path, status in [
        *((path, "active") for path in active_paths),
        *((path, "revoked") for path in revoked_paths),
    ]:
        public_key = load_ed25519_public_key(path)
        key_id = ed25519_public_key_id(public_key)
        if key_id in seen:
            raise ValueError(f"duplicate trust-policy key: {key_id}")
        seen.add(key_id)
        pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        keys.append(
            {
                "key_id": key_id,
                "algorithm": "Ed25519",
                "public_key_pem": pem,
                "status": status,
                "not_before": _format_time(issued_at),
                "not_after": _format_time(expires),
                "revoked_at": _format_time(issued_at) if status == "revoked" else None,
                "revocation_reason": revocation_reason if status == "revoked" else None,
            }
        )
    root_key_id = ed25519_public_key_id(
        load_ed25519_private_key(root_private_key_path).public_key()
    )
    if root_key_id in seen:
        raise ValueError("offline trust root key must not also sign knowledge updates")
    payload = {
        "schema_version": TRUST_POLICY_SCHEMA,
        "policy_id": policy_id,
        "policy_sequence": policy_sequence,
        "issued_at": _format_time(issued_at),
        "expires_at": _format_time(expires),
        "signature_threshold": threshold,
        "keys": sorted(keys, key=lambda row: row["key_id"]),
        "security_boundary": (
            "The detached root signature authenticates this complete signer inventory, threshold, "
            "cryptoperiod and revocation state. Runtime configuration must pin the exact policy SHA-256 "
            "to prevent rollback to an older root-signed policy."
        ),
    }
    output_path = _exclusive_output(output_path, label="trust policy")
    signature_path = _exclusive_output(signature_path, label="trust policy signature")
    if output_path == signature_path:
        raise ValueError("trust policy and signature output paths must differ")
    try:
        _write_private_json(output_path, payload)
        temporary_signature = signature_path.with_name(
            f".{signature_path.name}.{uuid.uuid4().hex}.tmp"
        )
        sign_manifest(
            manifest=output_path,
            private_key=root_private_key_path.resolve(),
            signature=temporary_signature,
        )
        os.link(temporary_signature, signature_path)
        temporary_signature.unlink()
        _fsync_directory(signature_path.parent)
    except BaseException:
        output_path.unlink(missing_ok=True)
        signature_path.unlink(missing_ok=True)
        if "temporary_signature" in locals():
            temporary_signature.unlink(missing_ok=True)
        raise
    return {
        "schema_version": TRUST_POLICY_SCHEMA,
        "status": "built",
        "policy": str(output_path),
        "policy_sha256": _sha256(output_path),
        "signature": str(signature_path),
        "signature_sha256": _sha256(signature_path),
        "policy_id": policy_id,
        "policy_sequence": policy_sequence,
        "signature_threshold": threshold,
        "active_key_ids": sorted(
            row["key_id"] for row in keys if row["status"] == "active"
        ),
        "revoked_key_ids": sorted(
            row["key_id"] for row in keys if row["status"] == "revoked"
        ),
    }


def load_knowledge_update_trust_policy(
    *,
    policy_path: Path,
    signature_path: Path,
    root_public_key_path: Path,
    expected_policy_sha256: str,
    now: dt.datetime | None = None,
) -> VerifiedKnowledgeUpdateTrustPolicy:
    policy_path = _safe_key_path(policy_path, label="trust policy")
    signature_path = _safe_key_path(signature_path, label="trust policy signature")
    root_public_key_path = _safe_key_path(
        root_public_key_path,
        label="trust root public key",
    )
    if not _SHA256_RE.fullmatch(expected_policy_sha256):
        raise ValueError("expected trust policy SHA-256 must be 64 lowercase hexadecimal characters")
    actual_sha256 = _sha256(policy_path)
    if actual_sha256 != expected_policy_sha256:
        raise ValueError("knowledge update trust policy does not match the pinned SHA-256")
    signature = verify_manifest_signature(
        manifest=policy_path,
        signature=signature_path,
        public_key=root_public_key_path,
    )
    if not signature["verified"]:
        raise ValueError("knowledge update trust policy root signature is invalid")
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("knowledge update trust policy must be an object")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "policy_id",
            "policy_sequence",
            "issued_at",
            "expires_at",
            "signature_threshold",
            "keys",
            "security_boundary",
        },
        "trust policy",
    )
    if payload["schema_version"] != TRUST_POLICY_SCHEMA:
        raise ValueError("unsupported knowledge update trust policy schema")
    policy_id = _safe_id(payload["policy_id"], label="policy_id")
    policy_sequence = payload["policy_sequence"]
    if isinstance(policy_sequence, bool) or not isinstance(policy_sequence, int) or policy_sequence < 1:
        raise ValueError("trust policy sequence must be a positive integer")
    issued_at = _parse_time(payload["issued_at"], field="issued_at")
    expires_at = _parse_time(payload["expires_at"], field="expires_at")
    checked_at = _coerce_now(now)
    if issued_at > checked_at + MAX_FUTURE_CLOCK_SKEW:
        raise ValueError("knowledge update trust policy is not yet valid")
    if checked_at >= expires_at:
        raise ValueError("knowledge update trust policy has expired")
    if expires_at <= issued_at or expires_at - issued_at > MAX_POLICY_VALIDITY:
        raise ValueError("knowledge update trust policy validity is invalid")
    threshold = payload["signature_threshold"]
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 2:
        raise ValueError(
            "trust policy threshold must be at least two for compromise resilience"
        )
    raw_keys = payload["keys"]
    if not isinstance(raw_keys, list) or not raw_keys:
        raise ValueError("trust policy keys must be a non-empty array")
    keys: dict[str, TrustedUpdateKey] = {}
    eligible_now = 0
    for raw in raw_keys:
        if not isinstance(raw, dict):
            raise ValueError("trust policy key records must be objects")
        _require_exact_keys(
            raw,
            {
                "key_id",
                "algorithm",
                "public_key_pem",
                "status",
                "not_before",
                "not_after",
                "revoked_at",
                "revocation_reason",
            },
            "trust policy key",
        )
        if raw["algorithm"] != "Ed25519":
            raise ValueError("trust policy supports only Ed25519 signer keys")
        if raw["status"] not in {"active", "revoked"}:
            raise ValueError("trust policy key status must be active or revoked")
        try:
            loaded = serialization.load_pem_public_key(
                str(raw["public_key_pem"]).encode("ascii")
            )
        except (ValueError, TypeError, UnicodeEncodeError) as exc:
            raise ValueError("trust policy contains an invalid public key") from exc
        if not isinstance(loaded, ed25519.Ed25519PublicKey):
            raise ValueError("trust policy contains a non-Ed25519 public key")
        key_id = ed25519_public_key_id(loaded)
        if raw["key_id"] != key_id or not _SHA256_RE.fullmatch(key_id):
            raise ValueError("trust policy key_id does not match its public key")
        if key_id in keys:
            raise ValueError(f"duplicate trust policy key_id: {key_id}")
        not_before = _parse_time(raw["not_before"], field=f"{key_id}.not_before")
        not_after = _parse_time(raw["not_after"], field=f"{key_id}.not_after")
        if not_after <= not_before:
            raise ValueError("trust policy key signing period is invalid")
        revoked_at: dt.datetime | None = None
        reason: str | None = None
        if raw["status"] == "revoked":
            revoked_at = _parse_time(raw["revoked_at"], field=f"{key_id}.revoked_at")
            reason = str(raw["revocation_reason"] or "").strip()
            if not reason:
                raise ValueError("revoked trust policy key requires a reason")
        elif raw["revoked_at"] is not None or raw["revocation_reason"] is not None:
            raise ValueError("active trust policy key cannot contain revocation metadata")
        key = TrustedUpdateKey(
            key_id=key_id,
            public_key=loaded,
            status=raw["status"],
            not_before=not_before,
            not_after=not_after,
            revoked_at=revoked_at,
            revocation_reason=reason,
        )
        keys[key_id] = key
        if (
            key.status == "active"
            and key.not_before <= checked_at <= key.not_after
        ):
            eligible_now += 1
    if threshold > eligible_now:
        raise ValueError(
            "trust policy threshold exceeds active keys in their current signing periods"
        )
    root_key = load_ed25519_public_key(root_public_key_path)
    if ed25519_public_key_id(root_key) in keys:
        raise ValueError("offline trust root key must not also sign knowledge updates")
    if not isinstance(payload["security_boundary"], str) or not payload[
        "security_boundary"
    ].strip():
        raise ValueError("trust policy security_boundary must be non-empty")
    return VerifiedKnowledgeUpdateTrustPolicy(
        policy_id=policy_id,
        policy_sequence=policy_sequence,
        threshold=threshold,
        issued_at=issued_at,
        expires_at=expires_at,
        sha256=actual_sha256,
        root_public_key_sha256=_sha256(root_public_key_path),
        keys=keys,
        source_path=policy_path,
    )


def sign_bytes(private_key_path: Path, payload: bytes) -> tuple[str, bytes]:
    key = load_ed25519_private_key(private_key_path)
    key_id = ed25519_public_key_id(key.public_key())
    return key_id, key.sign(payload)


def verify_bytes(
    public_key: ed25519.Ed25519PublicKey,
    *,
    payload: bytes,
    signature: bytes,
) -> None:
    try:
        public_key.verify(signature, payload)
    except InvalidSignature as exc:
        raise ValueError("knowledge update manifest signature is invalid") from exc


def _safe_key_path(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _exclusive_output(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} output must not be a symlink: {path}")
    parent = path.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    resolved = parent / path.name
    if resolved.exists() or resolved.is_symlink():
        raise FileExistsError(f"{label} output already exists: {resolved}")
    return resolved


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        temporary.unlink()
        path.chmod(0o600)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_id(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    return value


def _parse_time(value: Any, *, field: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an RFC3339 timestamp") from exc
    else:
        raise ValueError(f"{field} must be an RFC3339 timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(dt.UTC)


def _coerce_now(value: dt.datetime | None) -> dt.datetime:
    return (value or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)


def _format_time(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _require_exact_keys(
    payload: dict[str, Any],
    expected: set[str],
    field: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValueError(
            f"{field} keys mismatch; missing={sorted(expected - actual)}; "
            f"unexpected={sorted(actual - expected)}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
