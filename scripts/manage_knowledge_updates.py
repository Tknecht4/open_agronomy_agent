#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.knowledge_updates import (
    build_knowledge_update,
    install_knowledge_update,
    knowledge_update_status,
    preview_knowledge_update,
    rollback_knowledge_update,
)
from agronomy_agent.knowledge_update_trust import (
    VerifiedKnowledgeUpdateTrustPolicy,
    load_knowledge_update_trust_policy,
)
from agronomy_agent.paths import repo_path


def _optional_path(value: str | None) -> Path | None:
    return repo_path(value) if value else None


def _add_trust_policy_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--trust-policy")
    parser.add_argument("--trust-policy-signature")
    parser.add_argument("--trust-root-public-key")
    parser.add_argument("--expected-trust-policy-sha256")


def _trust_policy(args: argparse.Namespace) -> VerifiedKnowledgeUpdateTrustPolicy | None:
    values = (
        args.trust_policy,
        args.trust_policy_signature,
        args.trust_root_public_key,
        args.expected_trust_policy_sha256,
    )
    if not any(values):
        return None
    if not all(values):
        raise ValueError(
            "trust policy, signature, root public key, and expected SHA-256 "
            "must be supplied together"
        )
    return load_knowledge_update_trust_policy(
        policy_path=repo_path(args.trust_policy),
        signature_path=repo_path(args.trust_policy_signature),
        root_public_key_path=repo_path(args.trust_root_public_key),
        expected_policy_sha256=args.expected_trust_policy_sha256,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build, verify, activate, inspect, or roll back signed offline knowledge updates."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--rag-config", required=True)
    build.add_argument("--output-archive", required=True)
    build.add_argument("--package-id", required=True)
    build.add_argument("--release-sequence", type=int, required=True)
    build.add_argument("--expires-at", required=True)
    build.add_argument("--private-key")
    build.add_argument("--signer-private-key", action="append", default=[])
    build.add_argument("--notes", default="")
    _add_trust_policy_arguments(build)

    install = subparsers.add_parser("install")
    install.add_argument("--archive", required=True)
    install.add_argument("--update-root", required=True)
    install.add_argument("--public-key")
    install.add_argument("--allow-unsigned", action="store_true")
    install.add_argument("--actor", default="local_admin")
    install.add_argument("--reason", default="knowledge_update")
    _add_trust_policy_arguments(install)
    install_binding = install.add_mutually_exclusive_group(required=True)
    install_binding.add_argument("--expected-manifest-sha256")
    install_binding.add_argument(
        "--allow-unreviewed-manifest",
        action="store_true",
        help="Explicitly bypass preview binding; isolated development only.",
    )

    preview = subparsers.add_parser("preview")
    preview.add_argument("--archive", required=True)
    preview.add_argument("--update-root", required=True)
    preview.add_argument("--public-key")
    preview.add_argument("--allow-unsigned", action="store_true")
    _add_trust_policy_arguments(preview)

    status = subparsers.add_parser("status")
    status.add_argument("--update-root", required=True)
    status.add_argument("--public-key")
    status.add_argument("--allow-unsigned", action="store_true")
    _add_trust_policy_arguments(status)

    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--update-root", required=True)
    rollback.add_argument("--public-key")
    rollback.add_argument("--allow-unsigned", action="store_true")
    rollback.add_argument("--actor", default="local_admin")
    rollback.add_argument("--reason", default="operator_rollback")
    _add_trust_policy_arguments(rollback)

    args = parser.parse_args()
    trust_policy = _trust_policy(args)
    if trust_policy is not None and (
        getattr(args, "public_key", None) or getattr(args, "allow_unsigned", False)
    ):
        raise ValueError(
            "threshold trust-policy mode cannot be combined with legacy public-key "
            "or unsigned verification"
        )
    if args.command == "build":
        result = build_knowledge_update(
            repo_root=repo_path("."),
            rag_config=repo_path(args.rag_config),
            output_archive=repo_path(args.output_archive),
            package_id=args.package_id,
            release_sequence=args.release_sequence,
            expires_at=args.expires_at,
            private_key=_optional_path(args.private_key),
            signer_private_keys=[
                repo_path(value) for value in args.signer_private_key
            ],
            trust_policy=trust_policy,
            notes=args.notes,
        )
    elif args.command == "install":
        result = install_knowledge_update(
            archive=repo_path(args.archive),
            update_root=repo_path(args.update_root),
            public_key=_optional_path(args.public_key),
            trust_policy=trust_policy,
            allow_unsigned=args.allow_unsigned,
            actor=args.actor,
            reason=args.reason,
            expected_manifest_sha256=args.expected_manifest_sha256,
        )
    elif args.command == "preview":
        result = preview_knowledge_update(
            archive=repo_path(args.archive),
            update_root=repo_path(args.update_root),
            public_key=_optional_path(args.public_key),
            trust_policy=trust_policy,
            allow_unsigned=args.allow_unsigned,
        )
    elif args.command == "status":
        result = knowledge_update_status(
            update_root=repo_path(args.update_root),
            public_key=_optional_path(args.public_key),
            trust_policy=trust_policy,
            allow_unsigned=args.allow_unsigned,
        )
    else:
        result = rollback_knowledge_update(
            update_root=repo_path(args.update_root),
            public_key=_optional_path(args.public_key),
            trust_policy=trust_policy,
            allow_unsigned=args.allow_unsigned,
            actor=args.actor,
            reason=args.reason,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
