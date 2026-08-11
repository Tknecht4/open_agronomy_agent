#!/usr/bin/env python3
from pathlib import Path
import sys
import argparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agronomy_agent.agno_runtime.source_ingest import main as ingest_main


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Agno knowledge sources from manifest with optional staggering.")
    parser.add_argument("--manifest", default="data/manifests/rag_sources.json")
    parser.add_argument("--source-id", action="append", help="One or more source IDs to ingest. Omit for defaults.")
    parser.add_argument(
        "--source-kind",
        default="forum_board",
        help="Filter manifest sources by kind when --source-id is not supplied.",
    )
    parser.add_argument("--inter-source-delay", type=float, default=2.5)
    parser.add_argument("--inter-source-jitter", type=float, default=0.75)
    parser.add_argument("--max-sources", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output-dir", default="data/derived/rag")
    parser.add_argument("--raw-dir", default="data/raw/rag")
    args = parser.parse_args()

    source_kind = None if args.source_id else args.source_kind
    cli_args = [
        "--manifest",
        args.manifest,
        "--output-dir",
        args.output_dir,
        "--raw-dir",
        args.raw_dir,
        "--force" if args.force else "",
        "--inter-source-delay",
        str(args.inter_source_delay),
        "--inter-source-jitter",
        str(args.inter_source_jitter),
    ]
    if source_kind:
        cli_args.extend(["--source-kind", source_kind])
    if args.max_sources is not None:
        cli_args.extend(["--max-sources", str(args.max_sources)])
    if args.source_id:
        for source_id in args.source_id:
            cli_args.extend(["--source-id", source_id])
    cli_args = [item for item in cli_args if item]
    return ingest_main(cli_args)


if __name__ == "__main__":
    raise SystemExit(main())
