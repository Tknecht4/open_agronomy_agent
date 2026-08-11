from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import tarfile
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from agronomy_agent.server.storage.backup import (
    ARTIFACTS_DIR_NAME,
    DB_SNAPSHOT_NAME,
    KNOWLEDGE_UPDATES_DIR_NAME,
    MANIFEST_DIGEST_NAME,
    MANIFEST_NAME,
    restore_backup,
    validate_backup,
)


ENCRYPTED_BACKUP_SCHEMA = "open_agronomy_agent.encrypted_backup.v1"
ENCRYPTED_BACKUP_MAGIC = b"OAABKENC1\n"
ENCRYPTED_BACKUP_ALGORITHM = "X25519-HKDF-SHA256-AES-256-GCM"
ENCRYPTED_BACKUP_KDF_INFO = b"open-agronomy-agent/encrypted-backup/v1"
GCM_NONCE_BYTES = 12
GCM_TAG_BYTES = 16
HKDF_SALT_BYTES = 32
MAX_HEADER_BYTES = 64 * 1024
MAX_ARCHIVE_MEMBERS = 1_000_000
STREAM_CHUNK_BYTES = 1024 * 1024
# SP 800-38D bounds one GCM plaintext to 2^39 - 256 bits.
MAX_GCM_PAYLOAD_BYTES = (2**39 - 256) // 8


@dataclass(frozen=True)
class EncryptedBackupResult:
    bundle_path: Path
    header: dict[str, Any]
    sha256: str


def generate_backup_encryption_keypair(
    *,
    private_key_path: Path,
    public_key_path: Path,
) -> dict[str, Any]:
    private_key_path = _safe_output_path(private_key_path)
    public_key_path = _safe_output_path(public_key_path)
    if private_key_path == public_key_path:
        raise ValueError("private and public key paths must differ")
    private_key = x25519.X25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _write_exclusive(private_key_path, private_pem, mode=0o600)
    try:
        _write_exclusive(public_key_path, public_pem, mode=0o644)
    except BaseException:
        private_key_path.unlink(missing_ok=True)
        raise
    return {
        "schema_version": "open_agronomy_agent.backup_encryption_keypair.v1",
        "algorithm": "X25519",
        "recipient_key_id": _public_key_id(public_key),
        "private_key_path": str(private_key_path),
        "public_key_path": str(public_key_path),
        "private_key_mode": "0600",
        "warning": (
            "The private key is not password-encrypted. Keep it off the field device on "
            "access-controlled encrypted storage; loss of this key makes the backup unrecoverable."
        ),
    }


def encrypt_backup(
    *,
    backup_dir: Path,
    recipient_public_key_path: Path,
    output_path: Path,
) -> EncryptedBackupResult:
    backup_dir = backup_dir.resolve()
    manifest = validate_backup(backup_dir)
    source_files = _backup_source_files(backup_dir, manifest)
    public_key = _load_public_key(recipient_public_key_path)
    recipient_key_id = _public_key_id(public_key)
    output_path = _safe_output_path(output_path)

    archive_path: Path | None = None
    partial_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".open-agronomy-backup-",
            suffix=".tar",
            delete=False,
        ) as archive_handle:
            archive_path = Path(archive_handle.name)
        archive_path.chmod(0o600)
        _write_backup_archive(
            backup_dir=backup_dir,
            source_files=source_files,
            archive_path=archive_path,
            created_at_unix=int(manifest["created_at_unix"]),
        )
        if archive_path.stat().st_size > MAX_GCM_PAYLOAD_BYTES:
            raise ValueError("backup payload exceeds the AES-GCM per-invocation limit")

        ephemeral_private = x25519.X25519PrivateKey.generate()
        ephemeral_public = ephemeral_private.public_key()
        salt = os.urandom(HKDF_SALT_BYTES)
        nonce = os.urandom(GCM_NONCE_BYTES)
        header = {
            "schema_version": ENCRYPTED_BACKUP_SCHEMA,
            "algorithm": ENCRYPTED_BACKUP_ALGORITHM,
            "archive_format": "tar",
            "backup_id": str(manifest["backup_id"]),
            "backup_manifest_sha256": _sha256(backup_dir / MANIFEST_NAME),
            "created_at_unix": int(time.time()),
            "payload_size_bytes": archive_path.stat().st_size,
            "recipient_key_id": recipient_key_id,
            "ephemeral_public_key_base64": _b64(
                ephemeral_public.public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
            ),
            "hkdf_salt_base64": _b64(salt),
            "nonce_base64": _b64(nonce),
            "authentication_tag_bytes": GCM_TAG_BYTES,
        }
        header_bytes = _canonical_json(header)
        if len(header_bytes) > MAX_HEADER_BYTES:
            raise ValueError("encrypted backup header exceeds limit")
        key = _derive_key(
            ephemeral_private.exchange(public_key),
            salt=salt,
            recipient_key_id=recipient_key_id,
        )

        partial_path = output_path.with_name(
            f".{output_path.name}.{uuid.uuid4().hex}.partial"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(partial_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output_handle, archive_path.open("rb") as archive_handle:
                output_handle.write(ENCRYPTED_BACKUP_MAGIC)
                output_handle.write(struct.pack(">I", len(header_bytes)))
                output_handle.write(header_bytes)
                encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
                encryptor.authenticate_additional_data(header_bytes)
                for chunk in iter(lambda: archive_handle.read(STREAM_CHUNK_BYTES), b""):
                    output_handle.write(encryptor.update(chunk))
                output_handle.write(encryptor.finalize())
                output_handle.write(encryptor.tag)
                output_handle.flush()
                os.fsync(output_handle.fileno())
            os.link(partial_path, output_path)
            partial_path.unlink()
            partial_path = None
            _fsync_directory(output_path.parent)
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        return EncryptedBackupResult(
            bundle_path=output_path,
            header=header,
            sha256=_sha256(output_path),
        )
    finally:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)
        if partial_path is not None:
            partial_path.unlink(missing_ok=True)


def inspect_encrypted_backup(bundle_path: Path) -> dict[str, Any]:
    bundle_path = _safe_input_file(bundle_path, label="encrypted backup")
    with bundle_path.open("rb") as handle:
        header, _, _ = _read_header(handle, bundle_size=bundle_path.stat().st_size)
    return {
        **header,
        "bundle_path": str(bundle_path),
        "bundle_sha256": _sha256(bundle_path),
        "authenticated": False,
        "warning": "Header metadata is not authenticated until decryption succeeds.",
    }


def restore_encrypted_backup(
    *,
    bundle_path: Path,
    expected_bundle_sha256: str,
    recipient_private_key_path: Path,
    target_db_path: Path,
    target_artifact_root: Path,
    target_knowledge_update_root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    bundle_path = _safe_input_file(bundle_path, label="encrypted backup")
    _validate_sha256(
        expected_bundle_sha256,
        label="reviewed encrypted backup SHA-256",
    )
    bundle_sha256 = _sha256(bundle_path)
    if bundle_sha256 != expected_bundle_sha256:
        raise ValueError(
            "encrypted backup does not match the reviewed SHA-256; "
            "obtain the expected digest from the signed export receipt or "
            "another trusted channel"
        )
    with decrypted_backup_directory(
        bundle_path=bundle_path,
        recipient_private_key_path=recipient_private_key_path,
    ) as (backup_dir, header):
        manifest = validate_backup(backup_dir)
        restored_manifest = restore_backup(
            backup_dir=backup_dir,
            target_db_path=target_db_path,
            target_artifact_root=target_artifact_root,
            target_knowledge_update_root=target_knowledge_update_root,
            overwrite=overwrite,
        )
    return {
        "schema_version": "open_agronomy_agent.encrypted_backup_restore.v1",
        "status": "pass",
        "authenticated": True,
        "content_authenticated": True,
        "exporter_authenticated": False,
        "authentication_scope": (
            "AES-GCM authenticates the encrypted content and the reviewed SHA-256 "
            "binds the selected bundle. Exporter identity requires a separately "
            "signed backup export receipt."
        ),
        "algorithm": ENCRYPTED_BACKUP_ALGORITHM,
        "bundle_path": str(bundle_path),
        "bundle_sha256": bundle_sha256,
        "expected_bundle_sha256": expected_bundle_sha256,
        "reviewed_bundle_sha256_match": True,
        "recipient_key_id": str(header["recipient_key_id"]),
        "backup_id": str(restored_manifest["backup_id"]),
        "backup_manifest_sha256": str(header["backup_manifest_sha256"]),
        "manifest": restored_manifest,
    }


@contextmanager
def decrypted_backup_directory(
    *,
    bundle_path: Path,
    recipient_private_key_path: Path,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield an authenticated plaintext backup inside a private temporary directory."""

    bundle_path = _safe_input_file(bundle_path, label="encrypted backup")
    private_key = _load_private_key(recipient_private_key_path)
    with tempfile.TemporaryDirectory(prefix="open-agronomy-encrypted-restore-") as temp_name:
        private_root = Path(temp_name)
        private_root.chmod(0o700)
        archive_path = private_root / "backup.tar"
        header = _decrypt_to_archive(
            bundle_path=bundle_path,
            private_key=private_key,
            archive_path=archive_path,
        )
        backup_dir = private_root / "backup"
        backup_dir.mkdir(mode=0o700)
        _extract_backup_archive(
            archive_path=archive_path,
            backup_dir=backup_dir,
            expected_payload_size=int(header["payload_size_bytes"]),
        )
        archive_path.unlink(missing_ok=True)
        manifest = validate_backup(backup_dir)
        _validate_decrypted_binding(
            backup_dir=backup_dir,
            manifest=manifest,
            header=header,
        )
        yield backup_dir, header


def _decrypt_to_archive(
    *,
    bundle_path: Path,
    private_key: x25519.X25519PrivateKey,
    archive_path: Path,
) -> dict[str, Any]:
    bundle_size = bundle_path.stat().st_size
    with bundle_path.open("rb") as input_handle:
        header, header_bytes, ciphertext_offset = _read_header(
            input_handle,
            bundle_size=bundle_size,
        )
        private_public = private_key.public_key()
        recipient_key_id = _public_key_id(private_public)
        if header["recipient_key_id"] != recipient_key_id:
            raise ValueError("encrypted backup recipient key does not match the private key")
        ephemeral_bytes = _decode_b64_exact(
            header["ephemeral_public_key_base64"],
            length=32,
            label="ephemeral public key",
        )
        salt = _decode_b64_exact(
            header["hkdf_salt_base64"],
            length=HKDF_SALT_BYTES,
            label="HKDF salt",
        )
        nonce = _decode_b64_exact(
            header["nonce_base64"],
            length=GCM_NONCE_BYTES,
            label="GCM nonce",
        )
        ephemeral_public = x25519.X25519PublicKey.from_public_bytes(ephemeral_bytes)
        key = _derive_key(
            private_key.exchange(ephemeral_public),
            salt=salt,
            recipient_key_id=recipient_key_id,
        )
        payload_size = int(header["payload_size_bytes"])
        input_handle.seek(ciphertext_offset + payload_size)
        tag = input_handle.read(GCM_TAG_BYTES)
        if len(tag) != GCM_TAG_BYTES:
            raise ValueError("encrypted backup authentication tag is truncated")
        input_handle.seek(ciphertext_offset)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(header_bytes)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(archive_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output_handle:
                remaining = payload_size
                while remaining:
                    chunk = input_handle.read(min(STREAM_CHUNK_BYTES, remaining))
                    if not chunk:
                        raise ValueError("encrypted backup payload is truncated")
                    output_handle.write(decryptor.update(chunk))
                    remaining -= len(chunk)
                try:
                    output_handle.write(decryptor.finalize())
                except InvalidTag as exc:
                    raise ValueError(
                        "encrypted backup authentication failed; wrong key or tampered bundle"
                    ) from exc
                output_handle.flush()
                os.fsync(output_handle.fileno())
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            archive_path.unlink(missing_ok=True)
            raise
    return header


def _read_header(
    handle: BinaryIO,
    *,
    bundle_size: int,
) -> tuple[dict[str, Any], bytes, int]:
    if handle.read(len(ENCRYPTED_BACKUP_MAGIC)) != ENCRYPTED_BACKUP_MAGIC:
        raise ValueError("unsupported encrypted backup magic")
    encoded_length = handle.read(4)
    if len(encoded_length) != 4:
        raise ValueError("encrypted backup header length is truncated")
    header_length = struct.unpack(">I", encoded_length)[0]
    if header_length <= 0 or header_length > MAX_HEADER_BYTES:
        raise ValueError("encrypted backup header length is invalid")
    header_bytes = handle.read(header_length)
    if len(header_bytes) != header_length:
        raise ValueError("encrypted backup header is truncated")
    try:
        header = json.loads(header_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("encrypted backup header is invalid JSON") from exc
    if not isinstance(header, dict) or _canonical_json(header) != header_bytes:
        raise ValueError("encrypted backup header is not canonical JSON")
    required = {
        "schema_version",
        "algorithm",
        "archive_format",
        "backup_id",
        "backup_manifest_sha256",
        "created_at_unix",
        "payload_size_bytes",
        "recipient_key_id",
        "ephemeral_public_key_base64",
        "hkdf_salt_base64",
        "nonce_base64",
        "authentication_tag_bytes",
    }
    if set(header) != required:
        raise ValueError("encrypted backup header fields are invalid")
    if header["schema_version"] != ENCRYPTED_BACKUP_SCHEMA:
        raise ValueError("unsupported encrypted backup schema")
    if header["algorithm"] != ENCRYPTED_BACKUP_ALGORITHM:
        raise ValueError("unsupported encrypted backup algorithm")
    if header["archive_format"] != "tar":
        raise ValueError("unsupported encrypted backup archive format")
    if header["authentication_tag_bytes"] != GCM_TAG_BYTES:
        raise ValueError("unsupported encrypted backup authentication tag length")
    _validate_identifier(header["backup_id"], label="backup id")
    _validate_sha256(header["backup_manifest_sha256"], label="backup manifest SHA-256")
    _validate_sha256(header["recipient_key_id"], label="recipient key id")
    if not isinstance(header["created_at_unix"], int) or header["created_at_unix"] <= 0:
        raise ValueError("encrypted backup creation time is invalid")
    payload_size = header["payload_size_bytes"]
    if not isinstance(payload_size, int) or payload_size <= 0:
        raise ValueError("encrypted backup payload size is invalid")
    if payload_size > MAX_GCM_PAYLOAD_BYTES:
        raise ValueError("encrypted backup payload exceeds the AES-GCM limit")
    ciphertext_offset = len(ENCRYPTED_BACKUP_MAGIC) + 4 + header_length
    expected_size = ciphertext_offset + payload_size + GCM_TAG_BYTES
    if expected_size != bundle_size:
        raise ValueError("encrypted backup size does not match authenticated metadata")
    return header, header_bytes, ciphertext_offset


def _backup_source_files(
    backup_dir: Path,
    manifest: dict[str, Any],
) -> list[tuple[Path, str]]:
    relative_names = [MANIFEST_NAME, MANIFEST_DIGEST_NAME, DB_SNAPSHOT_NAME]
    relative_names.extend(
        str(Path(ARTIFACTS_DIR_NAME) / _safe_relative(entry["path"]))
        for entry in manifest.get("artifacts", [])
    )
    relative_names.extend(
        str(Path(KNOWLEDGE_UPDATES_DIR_NAME) / _safe_relative(entry["path"]))
        for entry in manifest.get("knowledge_updates", [])
    )
    if len(relative_names) != len(set(relative_names)):
        raise ValueError("backup manifest contains duplicate archive paths")
    files: list[tuple[Path, str]] = []
    for relative_name in relative_names:
        source = backup_dir / relative_name
        if source.is_symlink():
            raise ValueError(f"backup symlinks are not supported: {relative_name}")
        if not source.is_file():
            raise FileNotFoundError(f"backup file missing: {source}")
        files.append((source, relative_name))
    return files


def _write_backup_archive(
    *,
    backup_dir: Path,
    source_files: list[tuple[Path, str]],
    archive_path: Path,
    created_at_unix: int,
) -> None:
    del backup_dir
    with tarfile.open(archive_path, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for source, relative_name in source_files:
            info = tarfile.TarInfo(name=relative_name)
            info.size = source.stat().st_size
            info.mode = 0o600
            info.mtime = created_at_unix
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            with source.open("rb") as source_handle:
                archive.addfile(info, fileobj=source_handle)
    archive_path.chmod(0o600)


def _extract_backup_archive(
    *,
    archive_path: Path,
    backup_dir: Path,
    expected_payload_size: int,
) -> None:
    if archive_path.stat().st_size != expected_payload_size:
        raise ValueError("decrypted backup archive size does not match authenticated metadata")
    with tarfile.open(archive_path, mode="r:") as archive:
        members = archive.getmembers()
        if not members or len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("decrypted backup archive member count is invalid")
        names: set[str] = set()
        for member in members:
            relative = _safe_relative(member.name)
            normalized = relative.as_posix()
            if normalized in names:
                raise ValueError(f"duplicate encrypted backup archive path: {normalized}")
            names.add(normalized)
            if not member.isfile():
                raise ValueError(
                    f"encrypted backup archive contains a non-regular member: {normalized}"
                )
            target = backup_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ValueError(f"encrypted backup archive member cannot be read: {normalized}")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(target, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as output_handle:
                    while chunk := extracted.read(STREAM_CHUNK_BYTES):
                        output_handle.write(chunk)
                    output_handle.flush()
                    os.fsync(output_handle.fileno())
            except BaseException:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                raise
        for directory in sorted(
            (path for path in backup_dir.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(0o700)
        backup_dir.chmod(0o700)


def _validate_decrypted_binding(
    *,
    backup_dir: Path,
    manifest: dict[str, Any],
    header: dict[str, Any],
) -> None:
    if str(manifest["backup_id"]) != header["backup_id"]:
        raise ValueError("decrypted backup id does not match authenticated metadata")
    if _sha256(backup_dir / MANIFEST_NAME) != header["backup_manifest_sha256"]:
        raise ValueError("decrypted backup manifest does not match authenticated metadata")
    expected = {
        MANIFEST_NAME,
        MANIFEST_DIGEST_NAME,
        DB_SNAPSHOT_NAME,
        *(
            str(Path(ARTIFACTS_DIR_NAME) / _safe_relative(entry["path"]))
            for entry in manifest.get("artifacts", [])
        ),
        *(
            str(Path(KNOWLEDGE_UPDATES_DIR_NAME) / _safe_relative(entry["path"]))
            for entry in manifest.get("knowledge_updates", [])
        ),
    }
    actual = {
        path.relative_to(backup_dir).as_posix()
        for path in backup_dir.rglob("*")
        if path.is_file()
    }
    if actual != expected:
        raise ValueError("decrypted backup archive contents do not match its manifest")


def _derive_key(
    shared_secret: bytes,
    *,
    salt: bytes,
    recipient_key_id: str,
) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=ENCRYPTED_BACKUP_KDF_INFO + b"\x00" + recipient_key_id.encode("ascii"),
    ).derive(shared_secret)


def _load_public_key(path: Path) -> x25519.X25519PublicKey:
    path = _safe_input_file(path, label="recipient public key")
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, x25519.X25519PublicKey):
        raise ValueError("recipient public key must be an X25519 PEM public key")
    return key


def _load_private_key(path: Path) -> x25519.X25519PrivateKey:
    path = _safe_input_file(path, label="recipient private key")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, x25519.X25519PrivateKey):
        raise ValueError("recipient private key must be an unencrypted X25519 PEM private key")
    return key


def _public_key_id(key: x25519.X25519PublicKey) -> str:
    encoded = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(encoded).hexdigest()


def _safe_output_path(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError(f"output path must not be a symlink: {path}")
    parent = path.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    resolved = parent / path.name
    if resolved.exists() or resolved.is_symlink():
        raise FileExistsError(f"output path already exists: {resolved}")
    return resolved


def _safe_input_file(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink: {path}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


def _write_exclusive(path: Path, payload: bytes, *, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        raise
    path.chmod(mode)
    _fsync_directory(path.parent)


def _safe_relative(value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("encrypted backup archive path is invalid")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() in {".", ""}:
        raise ValueError(f"unsafe encrypted backup archive path: {value}")
    return path


def _validate_identifier(value: Any, *, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 255
        or any(not (character.isalnum() or character in {"-", "_", "."}) for character in value)
    ):
        raise ValueError(f"encrypted backup {label} is invalid")


def _validate_sha256(value: Any, *, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"encrypted backup {label} is invalid")


def _decode_b64_exact(value: Any, *, length: int, label: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"encrypted backup {label} is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"encrypted backup {label} is invalid") from exc
    if len(decoded) != length:
        raise ValueError(f"encrypted backup {label} length is invalid")
    return decoded


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(STREAM_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
