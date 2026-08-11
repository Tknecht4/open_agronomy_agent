from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path
from typing import Any

from datasets import load_dataset
from huggingface_hub import hf_hub_download, list_repo_files

from agronomy_agent.paths import repo_path


QUESTION_KEYS = ("question", "query", "instruction", "prompt", "input")
ANSWER_KEYS = ("answer", "response", "output", "completion", "final_answer")


def first_value(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def row_to_messages(row: dict[str, Any]) -> list[dict[str, str]] | None:
    messages = row.get("messages")
    if isinstance(messages, list) and messages:
        clean = [{"role": str(m.get("role", "user")), "content": str(m.get("content", ""))} for m in messages if m.get("content")]
        return clean if clean else None
    turns = row.get("turns")
    if isinstance(turns, list) and turns:
        clean = []
        system_prompt = row.get("system_prompt")
        if isinstance(system_prompt, str) and system_prompt.strip():
            clean.append({"role": "system", "content": system_prompt.strip()})
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            if turn.get("user"):
                clean.append({"role": "user", "content": str(turn["user"]).strip()})
            if turn.get("assistant"):
                clean.append({"role": "assistant", "content": str(turn["assistant"]).strip()})
        return clean if any(msg["role"] == "assistant" for msg in clean) else None
    question = first_value(row, QUESTION_KEYS)
    answer = first_value(row, ANSWER_KEYS)
    if answer is None and isinstance(row.get("answers"), dict):
        text = row["answers"].get("text")
        if isinstance(text, list) and text:
            answer = str(text[0]).strip()
        elif isinstance(text, str):
            answer = text.strip()
    context = row.get("context")
    if question and answer and isinstance(context, str) and context.strip():
        question = f"Context:\n{context.strip()}\n\nQuestion:\n{question}"
    if question and answer:
        return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    return None


def sample_source(source: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    if source.get("loader") == "hf_csv_glob":
        return sample_hf_csv_glob(source, seed)
    dataset = load_dataset(source["dataset"], source.get("subset"), split=source.get("split", "train"), streaming=False)
    rows = list(dataset)
    rng = random.Random(seed)
    rng.shuffle(rows)
    out = []
    for row in rows:
        messages = row_to_messages(dict(row))
        if not messages:
            continue
        out.append({"messages": messages, "source_dataset": source["dataset"], "license": source.get("license", "unknown")})
        if len(out) >= int(source.get("samples", 100)):
            break
    return out


def sample_hf_csv_glob(source: dict[str, Any], seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    files = [name for name in list_repo_files(source["dataset"], repo_type="dataset") if name.endswith(".csv")]
    rng.shuffle(files)
    max_files = int(source.get("max_files", 4))
    rows: list[dict[str, Any]] = []
    for filename in files[:max_files]:
        path = Path(hf_hub_download(source["dataset"], filename, repo_type="dataset"))
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                continue
            fieldnames = {name.strip() for name in reader.fieldnames if name}
            if not {"query", "response"}.issubset(fieldnames):
                continue
            file_rows = list(reader)
            rng.shuffle(file_rows)
            for row in file_rows:
                messages = row_to_messages(row)
                if messages:
                    rows.append({"messages": messages, "source_dataset": source["dataset"], "source_file": filename, "license": source.get("license", "unknown")})
                if len(rows) >= int(source.get("samples", 100)):
                    return rows
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a small public agronomy SFT mix in MLX chat JSONL format.")
    parser.add_argument("--manifest", default="data/manifests/public_sft_sources.json")
    parser.add_argument("--output-dir", default="data/derived/sft_mix")
    parser.add_argument("--target-rows", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    manifest = json.loads(repo_path(args.manifest).read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for idx, source in enumerate(manifest["sources"]):
        if source.get("enabled") is False:
            print(json.dumps({"info": "source_skipped", "dataset": source["dataset"], "reason": source.get("skip_reason", "disabled")}))
            continue
        try:
            rows.extend(sample_source(source, args.seed + idx))
        except Exception as exc:
            print(json.dumps({"warning": "source_failed", "dataset": source["dataset"], "error": str(exc)}))
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    rows = rows[: args.target_rows]
    n_train = int(len(rows) * 0.88)
    n_valid = int(len(rows) * 0.06)
    out = repo_path(args.output_dir)
    write_jsonl(out / "train.jsonl", rows[:n_train])
    write_jsonl(out / "valid.jsonl", rows[n_train : n_train + n_valid])
    write_jsonl(out / "test.jsonl", rows[n_train + n_valid :])
    summary = {"rows": len(rows), "train": n_train, "valid": n_valid, "test": len(rows) - n_train - n_valid, "output_dir": str(out)}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
