from __future__ import annotations

import argparse
import json
import sys

from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.object_store import ObjectStorePreflightError, build_object_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preflight the Phase 4 object-store backend.")
    parser.add_argument("--backend", choices=["local", "s3"], help="Override AGRONOMY_AGENT_OBJECT_STORE_BACKEND.")
    parser.add_argument("--endpoint", help="Override AGRONOMY_AGENT_OBJECT_STORE_ENDPOINT.")
    parser.add_argument("--bucket", help="Override AGRONOMY_AGENT_OBJECT_STORE_BUCKET.")
    parser.add_argument("--region", help="Override AGRONOMY_AGENT_OBJECT_STORE_REGION.")
    parser.add_argument("--access-key", help="Override AGRONOMY_AGENT_OBJECT_STORE_ACCESS_KEY.")
    parser.add_argument("--secret-key", help="Override AGRONOMY_AGENT_OBJECT_STORE_SECRET_KEY.")
    parser.add_argument("--create-bucket", action="store_true", help="Create the configured S3 bucket when it is missing.")
    parser.add_argument("--probe-prefix", default=".phase4-preflight", help="S3 key prefix for the temporary probe object.")
    args = parser.parse_args(argv)

    try:
        settings = build_settings(
            object_store_backend=args.backend,
            object_store_endpoint=args.endpoint,
            object_store_bucket=args.bucket,
            object_store_region=args.region,
            object_store_access_key=args.access_key,
            object_store_secret_key=args.secret_key,
        )
        store = build_object_store(settings)
        if settings.object_store_backend == "s3":
            result = store.preflight(create_bucket=args.create_bucket, probe_prefix=args.probe_prefix)
        else:
            result = store.preflight()
    except (ObjectStorePreflightError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2

    print(json.dumps({"status": "ok", **result.as_dict()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
