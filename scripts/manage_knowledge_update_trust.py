#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.knowledge_update_trust import (
    build_knowledge_update_trust_policy,
    ed25519_public_key_id,
    load_ed25519_public_key,
    load_knowledge_update_trust_policy,
)
from agronomy_agent.paths import repo_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build or verify a root-signed threshold trust policy for offline "
            "knowledge-update packages."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    key_id = commands.add_parser("key-id")
    key_id.add_argument("--public-key", required=True)

    build = commands.add_parser("build")
    build.add_argument("--output", required=True)
    build.add_argument("--signature", required=True)
    build.add_argument("--root-private-key", required=True)
    build.add_argument("--policy-id", required=True)
    build.add_argument("--policy-sequence", type=int, required=True)
    build.add_argument("--threshold", type=int, required=True)
    build.add_argument("--active-public-key", action="append", required=True)
    build.add_argument("--revoked-public-key", action="append", default=[])
    build.add_argument("--revocation-reason", default="operator_revocation")
    build.add_argument("--expires-at", required=True)

    verify = commands.add_parser("verify")
    verify.add_argument("--policy", required=True)
    verify.add_argument("--signature", required=True)
    verify.add_argument("--root-public-key", required=True)
    verify.add_argument("--expected-policy-sha256", required=True)

    args = parser.parse_args()
    if args.command == "key-id":
        public_key = load_ed25519_public_key(repo_path(args.public_key))
        report = {
            "status": "pass",
            "algorithm": "Ed25519",
            "public_key": str(repo_path(args.public_key)),
            "key_id": ed25519_public_key_id(public_key),
        }
    elif args.command == "build":
        report = build_knowledge_update_trust_policy(
            output_path=repo_path(args.output),
            signature_path=repo_path(args.signature),
            root_private_key_path=repo_path(args.root_private_key),
            policy_id=args.policy_id,
            policy_sequence=args.policy_sequence,
            threshold=args.threshold,
            active_public_key_paths=[
                repo_path(value) for value in args.active_public_key
            ],
            revoked_public_key_paths=[
                repo_path(value) for value in args.revoked_public_key
            ],
            revocation_reason=args.revocation_reason,
            expires_at=args.expires_at,
        )
    else:
        policy = load_knowledge_update_trust_policy(
            policy_path=repo_path(args.policy),
            signature_path=repo_path(args.signature),
            root_public_key_path=repo_path(args.root_public_key),
            expected_policy_sha256=args.expected_policy_sha256,
        )
        report = {
            "status": "pass",
            "policy_id": policy.policy_id,
            "policy_sequence": policy.policy_sequence,
            "policy_sha256": policy.sha256,
            "signature_threshold": policy.threshold,
            "active_key_ids": sorted(
                key_id
                for key_id, key in policy.keys.items()
                if key.status == "active"
            ),
            "revoked_key_ids": sorted(
                key_id
                for key_id, key in policy.keys.items()
                if key.status == "revoked"
            ),
            "expires_at": policy.expires_at.isoformat(),
            "root_public_key_sha256": policy.root_public_key_sha256,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
