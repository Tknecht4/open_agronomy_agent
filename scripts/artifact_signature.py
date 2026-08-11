#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.artifact_signature import sign_manifest, verify_manifest_signature


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign or verify a release checksum manifest with an Ed25519 key.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    sign = subparsers.add_parser("sign")
    sign.add_argument("--manifest", type=Path, required=True)
    sign.add_argument("--private-key", type=Path, required=True)
    sign.add_argument("--signature", type=Path, required=True)
    sign.add_argument(
        "--replace-existing-signature",
        action="store_true",
        help="Explicitly replace an existing detached signature after a successful new signature is written.",
    )
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--public-key", type=Path, required=True)
    verify.add_argument("--signature", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "sign":
        report = sign_manifest(
            manifest=args.manifest.resolve(),
            private_key=args.private_key.resolve(),
            signature=args.signature.resolve(),
            replace_existing=args.replace_existing_signature,
        )
        status = 0
    else:
        report = verify_manifest_signature(
            manifest=args.manifest.resolve(),
            public_key=args.public_key.resolve(),
            signature=args.signature.resolve(),
        )
        status = 0 if report["verified"] else 1
    print(json.dumps(report, indent=2))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
