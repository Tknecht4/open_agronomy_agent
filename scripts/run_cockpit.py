#!/usr/bin/env python

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import os
import secrets
import signal
import ssl
import subprocess
import sys
import time
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import ExtensionOID

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"

if SRC_DIR.exists():
    src_path = str(SRC_DIR)
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

from agronomy_agent.server.app import create_app
from agronomy_agent.server.services.chat_service import _build_mlx_generator
from agronomy_agent.server.settings import build_settings
from agronomy_agent.agent import load_model_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run agronomy cockpit API (and optional frontend).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--db-path", default="outputs/cockpit/phase3.sqlite3")
    parser.add_argument("--artifact-root", default="outputs/cockpit/artifacts")
    parser.add_argument("--static-dir", default=None)
    parser.add_argument("--model-config", default=None, help="model profile YAML; defaults to configs/model.yaml")
    parser.add_argument("--frontend", action="store_true", help="launch npm dev server for the frontend")
    parser.add_argument("--frontend-dir", default="frontend")
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument(
        "--field-lan",
        action="store_true",
        help=(
            "serve the built frontend over operator-supplied HTTPS with one-time "
            "local client pairing, local development auth disabled, and public "
            "network adapters blocked"
        ),
    )
    parser.add_argument(
        "--advertise-host",
        default=None,
        help="LAN DNS name or IP covered by the TLS certificate and opened by the field client",
    )
    parser.add_argument(
        "--advertise-port",
        type=int,
        default=None,
        help="host-side HTTPS port when it differs from the API listen port",
    )
    parser.add_argument("--tls-certfile", default=None)
    parser.add_argument("--tls-keyfile", default=None)
    parser.add_argument(
        "--warm-model",
        action="store_true",
        help="load the configured local serving model before accepting requests",
    )
    return parser


def _is_loopback_host(value: str) -> bool:
    normalized = value.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_tls_identity(
    *,
    certfile: Path,
    keyfile: Path,
    advertise_host: str,
) -> None:
    if not certfile.is_file():
        raise ValueError(f"TLS certificate is missing: {certfile}")
    if not keyfile.is_file():
        raise ValueError(f"TLS private key is missing: {keyfile}")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
    certificate = x509.load_pem_x509_certificate(certfile.read_bytes())
    host = advertise_host.strip().strip("[]").lower()
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None
    try:
        subject_alt_names = certificate.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value
    except x509.ExtensionNotFound:
        subject_alt_names = x509.SubjectAlternativeName([])
    if host_ip is not None:
        matched = any(
            candidate == host_ip
            for candidate in subject_alt_names.get_values_for_type(x509.IPAddress)
        )
    else:
        matched = any(
            _dns_san_matches_host(str(candidate), host)
            for candidate in subject_alt_names.get_values_for_type(x509.DNSName)
        )
    if not matched:
        raise ssl.CertificateError(
            f"TLS certificate subjectAltName does not cover {advertise_host}"
        )
    if certificate.not_valid_after_utc.timestamp() <= time.time():
        raise ValueError("TLS certificate is expired")


def _dns_san_matches_host(candidate: str, host: str) -> bool:
    candidate_labels = candidate.strip().lower().split(".")
    host_labels = host.strip().lower().split(".")
    if "*" not in candidate:
        return hmac.compare_digest(candidate.strip().lower(), host.strip().lower())
    return (
        len(candidate_labels) == len(host_labels)
        and len(candidate_labels) >= 2
        and candidate_labels[0] == "*"
        and all(
            hmac.compare_digest(expected, observed)
            for expected, observed in zip(candidate_labels[1:], host_labels[1:])
        )
    )


def _field_pair_url(*, advertise_host: str, port: int, token: str) -> str:
    host = advertise_host.strip().strip("[]")
    if ":" in host:
        host = f"[{host}]"
    return f"https://{host}:{port}/#pair={token}"


def _validate_bind_security(*, host: str, allow_local_dev_auth: bool) -> None:
    if not _is_loopback_host(host) and allow_local_dev_auth:
        raise ValueError(
            "refusing a non-loopback bind while local development authentication is enabled; "
            "use --field-lan or configure JWT/OIDC with AGRONOMY_AGENT_ALLOW_LOCAL_DEV_AUTH=false"
        )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    pairing_token = None
    session_secret = None
    if args.field_lan:
        if args.frontend:
            parser.error("--field-lan serves a built static frontend; do not combine it with --frontend")
        if not args.static_dir:
            parser.error("--field-lan requires --static-dir pointing to the built frontend")
        static_index = Path(args.static_dir) / "index.html"
        if not static_index.is_file():
            parser.error(f"--field-lan static frontend is missing {static_index}")
        if not args.advertise_host:
            parser.error("--field-lan requires --advertise-host")
        if args.advertise_port is not None and not 1 <= args.advertise_port <= 65535:
            parser.error("--advertise-port must be between 1 and 65535")
        if _is_loopback_host(args.advertise_host) or args.advertise_host in {"0.0.0.0", "::"}:
            parser.error("--advertise-host must identify the LAN address used by the separate field client")
        if not args.tls_certfile or not args.tls_keyfile:
            parser.error("--field-lan requires --tls-certfile and --tls-keyfile")
        try:
            _validate_tls_identity(
                certfile=Path(args.tls_certfile),
                keyfile=Path(args.tls_keyfile),
                advertise_host=args.advertise_host,
            )
        except (OSError, ssl.SSLError, ssl.CertificateError, ValueError) as exc:
            parser.error(f"field-LAN TLS identity failed: {exc}")
        if args.host == "127.0.0.1":
            args.host = "0.0.0.0"
        pairing_token = secrets.token_urlsafe(32)
        session_secret = secrets.token_urlsafe(48)
    settings = build_settings(
        db_path=Path(args.db_path),
        artifact_root=Path(args.artifact_root),
        static_dir=Path(args.static_dir) if args.static_dir else None,
        model_config_path=args.model_config,
        allow_local_dev_auth=False if args.field_lan else None,
        local_pairing_token_sha256=(
            hashlib.sha256(pairing_token.encode("utf-8")).hexdigest()
            if pairing_token
            else None
        ),
        oidc_session_secret=session_secret,
        network_mode="offline" if args.field_lan else None,
    )
    try:
        _validate_bind_security(
            host=args.host,
            allow_local_dev_auth=settings.allow_local_dev_auth,
        )
    except ValueError as exc:
        parser.error(str(exc))
    app = create_app(settings)

    if args.warm_model:
        model_config = load_model_config(settings.model_config_path)
        serving_model_id = str(model_config.get("serving_model_id") or model_config["model_id"])
        print(f"Warming local model {serving_model_id}...", flush=True)
        _build_mlx_generator(serving_model_id, model_config, settings.model_config_path).warmup()
        print("Local model weights ready.", flush=True)

    frontend_proc = None
    if args.frontend:
        frontend_env = {
            **os.environ,
            "VITE_API_TARGET": f"http://{args.host}:{args.port}",
        }
        frontend_proc = subprocess.Popen(
            ["npm", "run", "--prefix", args.frontend_dir, "dev", "--", "--host", args.host, "--port", str(args.frontend_port)],
            env=frontend_env,
        )

    try:
        import uvicorn

        config = uvicorn.Config(
            app,
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info",
            ssl_certfile=args.tls_certfile if args.field_lan else None,
            ssl_keyfile=args.tls_keyfile if args.field_lan else None,
        )
        server = uvicorn.Server(config)
        scheme = "https" if args.field_lan else "http"
        print(f"Cockpit API available at {scheme}://{args.host}:{args.port}")
        if pairing_token and args.advertise_host:
            print(
                "Open this one-time field-client pairing link on the separately prepared device:",
                flush=True,
            )
            print(
                _field_pair_url(
                    advertise_host=args.advertise_host,
                    port=args.advertise_port or args.port,
                    token=pairing_token,
                ),
                flush=True,
            )
            print(
                "The client must already trust this certificate. The URL fragment is cleared "
                "before the token is sent, and the token is accepted once.",
                flush=True,
            )
        return int(server.run())
    except KeyboardInterrupt:
        if frontend_proc:
            frontend_proc.send_signal(signal.SIGINT)
        return 0


if __name__ == "__main__":
    sys.exit(main())
