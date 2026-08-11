from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.server.demo_seed import seed_demo_workspace
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the Phase 4 source-attributed public demo workspace.")
    parser.add_argument("--db-path", type=Path, help="SQLite database path. Defaults to AGRONOMY_AGENT_DB_PATH.")
    parser.add_argument("--artifact-root", type=Path, help="Artifact root. Defaults to AGRONOMY_AGENT_ARTIFACT_ROOT.")
    parser.add_argument("--corpus-path", default="data/seed/agronomy_rag_corpus.jsonl")
    args = parser.parse_args(argv)

    settings = build_settings(db_path=args.db_path, artifact_root=args.artifact_root)
    result = seed_demo_workspace(TraceStore(settings.db_path), corpus_path=args.corpus_path)
    print(json.dumps(result, sort_keys=True))
    return 0
