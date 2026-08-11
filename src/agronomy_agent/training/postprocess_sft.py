from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer

from agronomy_agent.paths import repo_path


SPLITS = ("train", "valid", "test")
BLOCKED_LICENSE_PATTERNS = re.compile(r"copyright|citation_only|not_allowed|unknown_proprietary", re.I)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def row_text(row: dict[str, Any]) -> str:
    return "\n".join(str(msg.get("content", "")) for msg in row.get("messages", []))


def row_hash(row: dict[str, Any]) -> str:
    normalized = re.sub(r"\s+", " ", row_text(row).strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def token_count(tokenizer: Any, row: dict[str, Any]) -> int:
    messages = row.get("messages") or []
    try:
        tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False, enable_thinking=False)
    except TypeError:
        tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False)
    try:
        ids = tokens["input_ids"]
        return len(ids[0]) if ids and isinstance(ids[0], list) else len(ids)
    except Exception:
        pass
    if isinstance(tokens, dict):
        ids = tokens["input_ids"]
        return len(ids[0]) if ids and isinstance(ids[0], list) else len(ids)
    return len(tokens)


def is_license_allowed(row: dict[str, Any], allow_unknown: bool) -> bool:
    license_value = str(row.get("license", "") or "")
    if not license_value.strip():
        return allow_unknown
    if license_value.lower() in {"unknown", "check dataset card", "dataset_card_review_required"}:
        return allow_unknown
    return BLOCKED_LICENSE_PATTERNS.search(license_value) is None


def main() -> int:
    parser = argparse.ArgumentParser(description="Deduplicate, license-filter, and token-cap MLX chat SFT splits.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model", default="mlx-community/Qwen3.5-2B-OptiQ-4bit")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--allow-unknown-license", action="store_true")
    parser.add_argument("--include-regex", help="Keep rows whose concatenated text matches this regex.")
    parser.add_argument("--exclude-regex", help="Drop rows whose concatenated text matches this regex.")
    args = parser.parse_args()

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    include_re = re.compile(args.include_regex, re.I) if args.include_regex else None
    exclude_re = re.compile(args.exclude_regex, re.I) if args.exclude_regex else None
    input_dir = repo_path(args.input_dir)
    output_dir = repo_path(args.output_dir)
    seen: set[str] = set()
    summary: dict[str, Any] = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "model": args.model,
        "max_tokens": args.max_tokens,
        "allow_unknown_license": args.allow_unknown_license,
        "splits": {},
    }
    for split in SPLITS:
        kept = []
        dropped = {"duplicate": 0, "license": 0, "token_cap": 0, "empty": 0, "domain_filter": 0}
        lengths = []
        for row in load_jsonl(input_dir / f"{split}.jsonl"):
            if not row.get("messages"):
                dropped["empty"] += 1
                continue
            text = row_text(row)
            if include_re and not include_re.search(text):
                dropped["domain_filter"] += 1
                continue
            if exclude_re and exclude_re.search(text):
                dropped["domain_filter"] += 1
                continue
            digest = row_hash(row)
            if digest in seen:
                dropped["duplicate"] += 1
                continue
            if not is_license_allowed(row, args.allow_unknown_license):
                dropped["license"] += 1
                continue
            length = token_count(tokenizer, row)
            lengths.append(length)
            if length > args.max_tokens:
                dropped["token_cap"] += 1
                continue
            seen.add(digest)
            enriched = dict(row)
            enriched["token_count"] = length
            enriched["content_hash"] = digest
            kept.append(enriched)
        write_jsonl(output_dir / f"{split}.jsonl", kept)
        summary["splits"][split] = {
            "kept": len(kept),
            "dropped": dropped,
            "max_seen_tokens": max(lengths) if lengths else None,
            "max_kept_tokens": max((row["token_count"] for row in kept), default=None),
        }
    summary["totals"] = {
        "kept": sum(summary["splits"][split]["kept"] for split in SPLITS),
        "dropped": {
            reason: sum(summary["splits"][split]["dropped"][reason] for split in SPLITS)
            for reason in ("duplicate", "license", "token_cap", "empty", "domain_filter")
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "postprocess_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
