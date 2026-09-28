#!/usr/bin/env python3
"""Replay retained answer-stage traces as an offline, non-claim diagnostic.

Reads explicit JSON/JSONL input paths and writes one new JSON receipt. It never
loads a model, uses the network, changes product defaults, or overwrites output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.harness_intervention_replay import replay_files  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True, type=Path, metavar="JSON_OR_JSONL")
    parser.add_argument("--output", required=True, type=Path, metavar="NEW_JSON")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output already exists; choose a new path")
    if args.output.resolve() in {path.resolve() for path in args.input}:
        parser.error("output must differ from every input")
    try:
        receipt = replay_files(args.input)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
    except OSError:
        parser.error("input cannot be read or output cannot be written")
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": receipt["status"],
        "observation_count": receipt["observation_count"],
        "output_created": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
