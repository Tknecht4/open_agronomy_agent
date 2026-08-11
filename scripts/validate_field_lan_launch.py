#!/usr/bin/env python3
"""Fail closed before exposing the sealed runtime on a field LAN."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import stat
from pathlib import Path
from typing import Any

from scripts.run_cockpit import _validate_tls_identity


SCHEMA_VERSION = "open_agronomy_agent.field_lan_launch_preflight.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_launch(
    *,
    bind_address: str,
    advertise_host: str,
    tls_dir: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        bind_ip = ipaddress.ip_address(bind_address.strip())
    except ValueError:
        bind_ip = None
        errors.append("field-LAN bind address must be a literal IP address")
    if bind_ip is not None and (
        bind_ip.version != 4
        or bind_ip.is_loopback
        or bind_ip.is_unspecified
        or bind_ip.is_multicast
        or not (bind_ip.is_private or bind_ip.is_link_local)
    ):
        errors.append(
            "field-LAN bind address must be a specific private or link-local IPv4 address"
        )

    advertised = advertise_host.strip().strip("[]")
    if not advertised or advertised.lower() == "localhost":
        errors.append("advertised host must identify the separate-client LAN endpoint")
    else:
        try:
            advertised_ip = ipaddress.ip_address(advertised)
        except ValueError:
            advertised_ip = None
        if advertised_ip is not None and (
            advertised_ip.is_loopback or advertised_ip.is_unspecified
        ):
            errors.append(
                "advertised host must identify the separate-client LAN endpoint"
            )

    certfile = tls_dir / "tls.crt"
    keyfile = tls_dir / "tls.key"
    if not tls_dir.is_dir():
        errors.append("field-LAN TLS directory is missing")
    if keyfile.is_file() and stat.S_IMODE(keyfile.stat().st_mode) & 0o077:
        errors.append("field-LAN TLS private key must not be group- or world-readable")
    if certfile.is_file() and keyfile.is_file() and advertised:
        try:
            _validate_tls_identity(
                certfile=certfile,
                keyfile=keyfile,
                advertise_host=advertised,
            )
        except Exception as exc:  # the caller needs one fail-closed error surface
            errors.append(f"field-LAN TLS identity failed: {exc}")
    elif not certfile.is_file() or not keyfile.is_file():
        errors.append("field-LAN TLS certificate or private key is missing")

    checks = {
        "specific_private_or_link_local_bind": not any(
            "bind address" in error for error in errors
        ),
        "separate_client_endpoint_advertised": not any(
            "advertised host" in error for error in errors
        ),
        "tls_directory_present": tls_dir.is_dir(),
        "tls_private_key_restricted": keyfile.is_file()
        and not bool(stat.S_IMODE(keyfile.stat().st_mode) & 0o077),
        "tls_identity_matches_advertised_host": not any(
            "TLS identity" in error for error in errors
        )
        and certfile.is_file()
        and keyfile.is_file(),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "status": "pass" if not errors and all(checks.values()) else "blocked",
        "checks": checks,
        "network": {
            "bind_address": bind_address,
            "advertise_host": advertise_host,
            "public_runtime_egress": "blocked_by_internal_container_network",
        },
        "tls": {
            "certificate_sha256": _sha256(certfile) if certfile.is_file() else None,
            "private_key_hash_recorded": False,
            "private_key_path_recorded": False,
        },
        "errors": errors,
        "boundary": (
            "This preflight validates a launch configuration. It does not prove that "
            "a distinct client reached the runtime, trusted the certificate, ran on "
            "portable power, or was observed by an independent witness."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind-address", required=True)
    parser.add_argument("--advertise-host", required=True)
    parser.add_argument("--tls-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()
    report = validate_launch(
        bind_address=args.bind_address,
        advertise_host=args.advertise_host,
        tls_dir=args.tls_dir,
    )
    payload = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return int(args.require_pass and report["status"] != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
