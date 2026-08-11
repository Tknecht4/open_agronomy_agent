from __future__ import annotations

import argparse
import json

from agronomy_agent.agent import (
    MLXGenerator,
    MockGenerator,
    build_context,
    config_model_id,
    generate_answer,
    load_model_config,
)
from agronomy_agent.evals import main as eval_main
from agronomy_agent.tool_cli import main as tool_main


def main() -> int:
    parser = argparse.ArgumentParser(description="Agronomy agent MVP CLI.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask")
    ask.add_argument("question")
    ask.add_argument("--mode", choices=["baseline", "agronomic_rag"], default="agronomic_rag")
    ask.add_argument("--model", default=None)
    ask.add_argument("--mock", action="store_true")
    ctx = sub.add_parser("context")
    ctx.add_argument("question")
    ev = sub.add_parser("eval")
    ev.add_argument("args", nargs=argparse.REMAINDER)
    tools = sub.add_parser("tools")
    tools.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.cmd == "ask":
        model_config = load_model_config()
        generator = MockGenerator() if args.mock else MLXGenerator(args.model or config_model_id())
        verification_config = model_config.get("answer_verification") or {}
        output, metadata = generate_answer(
            args.question,
            args.mode,
            generator,
            verification_enabled=bool(verification_config.get("enabled", False)),
            verification_mode=str(verification_config.get("mode") or "risk_gated"),
            intervention_profile=str(model_config.get("intervention_profile") or "") or None,
        )
        print(output)
        print(json.dumps(metadata, indent=2))
        return 0
    if args.cmd == "context":
        context = build_context(args.question)
        print(json.dumps({
            "docs": [doc.__dict__ for doc in context.retrieved_docs],
            "graph": [hit.__dict__ for hit in context.graph_hits],
            "tools": [note.__dict__ for note in context.tool_notes],
        }, indent=2))
        return 0
    if args.cmd == "eval":
        import sys

        sys.argv = [sys.argv[0], *args.args]
        return eval_main()
    if args.cmd == "tools":
        return tool_main(args.args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
