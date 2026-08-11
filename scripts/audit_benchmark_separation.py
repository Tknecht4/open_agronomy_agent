#!/usr/bin/env python3
"""Prove that the frozen internal and external benchmark partitions do not mix."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agronomy_agent.benchmark_contract import read_json, read_jsonl, sha256, validate_benchmark  # noqa: E402


DEFAULT_INTERNAL = ROOT / "configs/open_agronomy_canadian_performance_v1.json"
DEFAULT_PUBLIC = ROOT / "configs/open_agronomy_external_agroqa_v1.json"
DEFAULT_OUTPUT = ROOT / "data/eval/open_agronomy_canadian_external_agroqa_separation_manifest.json"
NEAR_DUPLICATE_THRESHOLD = 0.80


def normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def token_jaccard(left: str, right: str) -> float:
    left_tokens = set(normalize(left).split())
    right_tokens = set(normalize(right).split())
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def semantic_question(row: dict[str, Any]) -> str:
    return str(row.get("public_source_question") or row["question"]).strip()


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _artifact_string_hashes(paths: Iterable[Path]) -> tuple[set[str], int, list[str]]:
    hashes: set[str] = set()
    records = 0
    scanned: list[str] = []
    for path in sorted({path.resolve() for path in paths if path.is_file()}):
        scanned.append(str(path.relative_to(ROOT)))
        if path.suffix == ".jsonl":
            values: list[Any] = []
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    values.append(json.loads(line))
                except json.JSONDecodeError:
                    values.append(line)
        elif path.suffix == ".json":
            try:
                values = [json.loads(path.read_text(encoding="utf-8", errors="replace"))]
            except json.JSONDecodeError:
                values = [path.read_text(encoding="utf-8", errors="replace")]
        else:
            values = [path.read_text(encoding="utf-8", errors="replace")]
        for value in values:
            records += 1
            for text in _strings(value):
                normalized = normalize(text)
                if normalized:
                    hashes.add(hashlib.sha256(normalized.encode("utf-8")).hexdigest())
    return hashes, records, scanned


def _rag_paths() -> list[Path]:
    import yaml

    config = yaml.safe_load((ROOT / "configs/rag_final_mvp.yaml").read_text(encoding="utf-8")) or {}
    retrieval = config.get("retrieval") or {}
    values = list(retrieval.get("corpus_paths") or []) + list(retrieval.get("graph_paths") or [])
    if retrieval.get("corpus_path"):
        values.append(retrieval["corpus_path"])
    if retrieval.get("graph_path"):
        values.append(retrieval["graph_path"])
    return [ROOT / str(value) for value in values]


def build_audit(internal_contract_path: Path, public_contract_path: Path) -> dict[str, Any]:
    internal_manifest = validate_benchmark(ROOT, internal_contract_path)
    public_manifest = validate_benchmark(ROOT, public_contract_path)
    internal_contract = read_json(internal_contract_path)
    public_contract = read_json(public_contract_path)
    if internal_manifest.get("evaluation_partition") != "internal":
        raise ValueError("internal contract is not marked internal")
    if public_manifest.get("evaluation_partition") != "public":
        raise ValueError("public contract is not marked public")
    internal_rows = read_jsonl(ROOT / internal_contract["suite_path"])
    public_rows = read_jsonl(ROOT / public_contract["suite_path"])
    internal_questions = [(row["eval_id"], semantic_question(row)) for row in internal_rows]
    public_questions = [(row["eval_id"], semantic_question(row)) for row in public_rows]
    internal_by_normalized = {normalize(question): eval_id for eval_id, question in internal_questions}
    exact: list[dict[str, str]] = []
    nearest: list[dict[str, Any]] = []
    for public_id, public_question in public_questions:
        normalized = normalize(public_question)
        if normalized in internal_by_normalized:
            exact.append({"public_eval_id": public_id, "internal_eval_id": internal_by_normalized[normalized]})
        best_score = 0.0
        best_id = ""
        for internal_id, internal_question in internal_questions:
            score = token_jaccard(public_question, internal_question)
            if score > best_score:
                best_score = score
                best_id = internal_id
        nearest.append({"public_eval_id": public_id, "internal_eval_id": best_id, "token_jaccard": round(best_score, 4)})
    nearest.sort(key=lambda item: item["token_jaccard"], reverse=True)

    public_question_hashes = {
        hashlib.sha256(normalize(question).encode("utf-8")).hexdigest(): eval_id
        for eval_id, question in public_questions
    }
    training_paths = list((ROOT / "data/training").rglob("*.jsonl"))
    training_hashes, training_records, scanned_training = _artifact_string_hashes(training_paths)
    rag_paths = _rag_paths()
    rag_hashes, rag_records, scanned_rag = _artifact_string_hashes(rag_paths)
    training_matches = sorted(public_question_hashes[key] for key in public_question_hashes.keys() & training_hashes)
    rag_matches = sorted(public_question_hashes[key] for key in public_question_hashes.keys() & rag_hashes)
    internal_source_paths = {str(source["path"]) for source in internal_contract.get("sources") or []}
    public_source_paths = {str(source["path"]) for source in public_contract.get("sources") or []}
    source_path_overlap = sorted(internal_source_paths & public_source_paths)
    public_dataset_ids = sorted({str(row.get("public_dataset_id")) for row in public_rows if row.get("public_dataset_id")})
    internal_public_dataset_ids = sorted({str(row.get("public_dataset_id")) for row in internal_rows if row.get("public_dataset_id")})
    public_id_overlap = sorted(set(public_dataset_ids) & set(internal_public_dataset_ids))
    maximum_jaccard = nearest[0]["token_jaccard"] if nearest else 0.0
    passed = not exact and maximum_jaccard < NEAR_DUPLICATE_THRESHOLD and not source_path_overlap and not public_id_overlap and not training_matches and not rag_matches
    return {
        "schema_version": "open_agronomy_agent.benchmark_separation.v1",
        "status": "pass" if passed else "fail",
        "internal": {
            "benchmark_id": internal_manifest["benchmark_id"],
            "contract_path": str(internal_contract_path.relative_to(ROOT)),
            "contract_sha256": sha256(internal_contract_path),
            "suite_path": internal_contract["suite_path"],
            "suite_sha256": internal_manifest["suite_sha256"],
            "rows": len(internal_rows),
        },
        "public": {
            "benchmark_id": public_manifest["benchmark_id"],
            "contract_path": str(public_contract_path.relative_to(ROOT)),
            "contract_sha256": sha256(public_contract_path),
            "suite_path": public_contract["suite_path"],
            "suite_sha256": public_manifest["suite_sha256"],
            "rows": len(public_rows),
            "dataset_ids": public_dataset_ids,
        },
        "question_overlap": {
            "normalization": "lowercase_ascii_alphanumeric_tokens",
            "exact_match_count": len(exact),
            "exact_matches": exact,
            "near_duplicate_threshold": NEAR_DUPLICATE_THRESHOLD,
            "maximum_token_jaccard": maximum_jaccard,
            "near_duplicate_count": sum(item["token_jaccard"] >= NEAR_DUPLICATE_THRESHOLD for item in nearest),
            "nearest_pairs": nearest[:20],
        },
        "source_overlap": {
            "source_path_overlap": source_path_overlap,
            "public_dataset_id_overlap": public_id_overlap,
        },
        "training_contamination": {
            "scanned_paths": scanned_training,
            "records_scanned": training_records,
            "exact_public_question_match_count": len(training_matches),
            "matching_public_eval_ids": training_matches,
        },
        "rag_contamination": {
            "scanned_paths": scanned_rag,
            "records_scanned": rag_records,
            "exact_public_question_match_count": len(rag_matches),
            "matching_public_eval_ids": rag_matches,
        },
        "policy": {
            "internal_for_model_selection": True,
            "public_for_finalist_verification_only": True,
            "public_results_may_not_drive_changes_retested_on_same_version": True,
            "public_questions_may_not_enter_training_rag_prompts_or_repairs": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--internal-contract", type=Path, default=DEFAULT_INTERNAL)
    parser.add_argument("--public-contract", type=Path, default=DEFAULT_PUBLIC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    audit = build_audit(args.internal_contract.resolve(), args.public_contract.resolve())
    if args.check:
        existing = read_json(args.output.resolve())
        if existing != audit:
            raise ValueError("benchmark separation manifest drift; rebuild it")
    else:
        args.output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
