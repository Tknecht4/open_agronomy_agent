from __future__ import annotations

import ipaddress
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from scripts.validate_field_lan_launch import validate_launch


def _tls_dir(tmp_path: Path, *, host: str = "field-runtime.test") -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(host),
                    x509.IPAddress(ipaddress.ip_address("192.168.50.10")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir()
    (tls_dir / "tls.crt").write_bytes(
        certificate.public_bytes(serialization.Encoding.PEM)
    )
    keyfile = tls_dir / "tls.key"
    keyfile.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(keyfile, 0o600)
    return tls_dir


def test_field_lan_preflight_accepts_specific_private_bind_and_matching_tls(
    tmp_path: Path,
) -> None:
    report = validate_launch(
        bind_address="192.168.50.10",
        advertise_host="field-runtime.test",
        tls_dir=_tls_dir(tmp_path),
    )

    assert report["status"] == "pass"
    assert all(report["checks"].values())
    assert report["tls"]["private_key_hash_recorded"] is False
    assert report["tls"]["private_key_path_recorded"] is False


def test_field_lan_preflight_rejects_wildcard_public_and_ipv6_binds(
    tmp_path: Path,
) -> None:
    tls_dir = _tls_dir(tmp_path)

    for address in ("0.0.0.0", "8.8.8.8", "fd00::10"):
        report = validate_launch(
            bind_address=address,
            advertise_host="field-runtime.test",
            tls_dir=tls_dir,
        )
        assert report["status"] == "blocked"
        assert report["checks"]["specific_private_or_link_local_bind"] is False


def test_field_lan_preflight_rejects_permissive_key_and_wrong_certificate(
    tmp_path: Path,
) -> None:
    tls_dir = _tls_dir(tmp_path)
    os.chmod(tls_dir / "tls.key", 0o644)
    permissive = validate_launch(
        bind_address="192.168.50.10",
        advertise_host="field-runtime.test",
        tls_dir=tls_dir,
    )
    wrong_host = validate_launch(
        bind_address="192.168.50.10",
        advertise_host="wrong-host.test",
        tls_dir=tls_dir,
    )

    assert permissive["status"] == "blocked"
    assert permissive["checks"]["tls_private_key_restricted"] is False
    assert wrong_host["status"] == "blocked"
    assert wrong_host["checks"]["tls_identity_matches_advertised_host"] is False
