#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agronomy_agent.corpus_governance import audit_runtime_corpora


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the configured runtime corpus against its rights and evidence policy.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--rag-config", type=Path, default=Path("configs/rag_governed_runtime_v1.yaml"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    rag_config = args.rag_config if args.rag_config.is_absolute() else root / args.rag_config
    report = audit_runtime_corpora(root=root, rag_config_path=rag_config)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
