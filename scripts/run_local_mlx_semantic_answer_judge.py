#!/usr/bin/env python3
"""Run the blinded semantic answer judge with an offline MLX model.

This keeps locally restricted corpus derivatives on the device.  The review
artifact records whether the evaluated generator and judge are the same model,
from the same family, or from different families; none is human sign-off.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from agronomy_agent.agent import MLXGenerator


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "run_codex_semantic_answer_judge.py"


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("semantic_judge_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load semantic judge base: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def model_family(model_id: str | None) -> str:
    """Return a coarse, disclosed family label for judge-bias accounting."""

    normalized = str(model_id or "").lower()
    for token, family in (
        ("qwen", "qwen"),
        ("gemma", "gemma"),
        ("lfm", "lfm"),
        ("llama", "llama"),
        ("mistral", "mistral"),
        ("phi", "phi"),
    ):
        if token in normalized:
            return family
    return "unknown"


def judge_relationship(*, evaluated_model: str | None, judge_model: str) -> str:
    if not evaluated_model:
        return "unknown"
    if evaluated_model.casefold() == judge_model.casefold():
        return "same_exact_model"
    evaluated_family = model_family(evaluated_model)
    judge_family = model_family(judge_model)
    if "unknown" not in (evaluated_family, judge_family) and evaluated_family == judge_family:
        return "same_model_family"
    return "cross_model_family"


def source_model_identity(outputs_path: Path) -> tuple[str | None, str | None]:
    """Read the evaluated model identity and first available revision receipt."""

    model_id: str | None = None
    with outputs_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            config = row.get("model_config") if isinstance(row.get("model_config"), dict) else {}
            identity = row.get("model_identity") if isinstance(row.get("model_identity"), dict) else {}
            generation = (row.get("metadata") or {}).get("generation_stats") or {}
            model_id = model_id or str(row.get("model_id") or "") or None
            revision = str(
                config.get("model_revision")
                or identity.get("revision")
                or generation.get("generation_lock_model_revision")
                or ""
            )
            if revision:
                return model_id, revision
    return model_id, None


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract one balanced JSON object from model text."""

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("local judge returned no JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(cleaned[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                payload = json.loads(cleaned[start : index + 1])
                if not isinstance(payload, dict):
                    raise ValueError("local judge JSON root must be an object")
                return payload
    raise ValueError("local judge returned incomplete JSON")


class LocalMLXRunner:
    def __init__(
        self,
        *,
        model_id: str,
        model_revision: str | None,
        max_tokens: int,
        seed: int | None = None,
        shared_cache_dir: Path | None = None,
    ) -> None:
        self.seed = seed
        self.model_revision = model_revision
        self.shared_cache_dir = shared_cache_dir
        self.shared_cache_hits = 0
        self.shared_cache_writes = 0
        self.schema_repair_attempts = 0
        self.generation_calls = 0
        self.seed_application_receipts: list[dict[str, Any]] = []
        self.generator = MLXGenerator(
            model_id,
            model_revision=model_revision,
            max_tokens=max_tokens,
            temperature=0.0,
            top_p=1.0,
            top_k=0,
            seed=seed,
            use_stream_generate=False,
            prompt_cache_enabled=False,
        )

    def _generate(self, messages: list[dict[str, str]]) -> str:
        output = self.generator.generate(messages)
        self.generation_calls += 1
        receipt = (self.generator.last_generation_stats or {}).get("seed_application")
        if isinstance(receipt, dict):
            self.seed_application_receipts.append(dict(receipt))
        return output

    def __call__(
        self,
        *,
        prompt: str,
        schema_path: Path,
        result_path: Path,
        model: str,
        reasoning_effort: str,
        cwd: Path,
    ) -> dict[str, Any]:
        del schema_path, model, reasoning_effort, cwd
        shape_example = {
            "judgments": [
                {
                    "review_id": "COPY_THE_REVIEW_ID",
                    "question_validity": "valid",
                    "answer_disposition": "pass",
                    "dimensions": {
                        "agronomic_accuracy": 3,
                        "decision_relevance": 3,
                        "completeness_actionability": 3,
                        "calibration_safety": 3,
                        "crop_region_source_fit": 3,
                    },
                    "confidence": "medium",
                    "material_errors": [],
                    "rationale": "Specific rationale under 60 words.",
                    "needs_source_validation": False,
                }
            ]
        }
        instruction = (
            prompt
            + "\nLOCAL JUDGE CALIBRATION: Reserve a score of 4 for a dimension only when the answer "
            "fully satisfies the supplied semantic criteria for that dimension. A safe generic deferral that "
            "omits the requested observations or decision logic is revise, not pass, and completeness should be "
            "2 or lower. Use different dimension scores when the strengths differ; do not default every dimension "
            "to the same value."
            + "\nReturn strict JSON only. The judgments value MUST be a JSON array, not an object. "
            "Every array item MUST contain every field shown in this exact shape (values are only an example):\n"
            + json.dumps(shape_example, indent=2)
            + "\nDo not use markdown, commentary, alternate keys, or a keyed-by-ID object."
        )
        cache_path: Path | None = None
        if self.shared_cache_dir is not None:
            cache_key = hashlib.sha256(
                json.dumps(
                    {
                        "schema": "open_agronomy_agent.local_semantic_judge_cache.v1",
                        "model_id": self.generator.model_id,
                        "model_revision": self.model_revision,
                        "seed": self.seed,
                        "sampler": {
                            "temperature": self.generator.temperature,
                            "top_p": self.generator.top_p,
                            "top_k": self.generator.top_k,
                        },
                        "instruction": instruction,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            cache_path = self.shared_cache_dir / f"{cache_key}.json"
            if cache_path.is_file():
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError(f"shared judge cache root is not an object: {cache_path}")
                result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                self.shared_cache_hits += 1
                return payload
        system_message = {
            "role": "system",
            "content": (
                "You are a blinded agronomy answer reviewer. Follow the supplied rubric "
                "and emit only schema-conforming JSON."
            ),
        }
        raw = self._generate([system_message, {"role": "user", "content": instruction}])
        raw_path = result_path.with_suffix(".raw.txt")
        raw_path.write_text(raw, encoding="utf-8")
        try:
            payload = extract_json_object(raw)
        except (json.JSONDecodeError, ValueError):
            result_path.with_suffix(".attempt_1.raw.txt").write_text(raw, encoding="utf-8")
            repair_instruction = (
                instruction
                + "\nSCHEMA REPAIR: Your prior response was incomplete or invalid. Reissue the same "
                "substantive judgment in compact strict JSON. Include at most 3 unique material_errors; "
                "keep rationale under 35 words; do not repeat list items or analysis."
            )
            raw = self._generate(
                [system_message, {"role": "user", "content": repair_instruction}]
            )
            raw_path.write_text(raw, encoding="utf-8")
            payload = extract_json_object(raw)
            self.schema_repair_attempts += 1
        result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            temporary.replace(cache_path)
            self.shared_cache_writes += 1
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-revision")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=900)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--shared-cache-dir", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")
    source_rows = BASE.load_jsonl(args.outputs)
    declared_judge_seeds = {
        int(row["judge_seed"])
        for row in source_rows
        if row.get("judge_seed") is not None
    }
    if len(declared_judge_seeds) > 1:
        raise ValueError(f"source outputs declare multiple judge seeds: {sorted(declared_judge_seeds)}")
    if declared_judge_seeds and declared_judge_seeds != {args.seed}:
        raise ValueError(
            f"local judge seed {args.seed!r} does not match source receipt {sorted(declared_judge_seeds)}"
        )
    runner = LocalMLXRunner(
        model_id=args.model,
        model_revision=args.model_revision,
        max_tokens=args.max_tokens,
        seed=args.seed,
        shared_cache_dir=args.shared_cache_dir,
    )
    evaluated_model, evaluated_revision = source_model_identity(args.outputs)
    relationship = judge_relationship(evaluated_model=evaluated_model, judge_model=args.model)
    summary = BASE.run(
        outputs_path=args.outputs,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        model=args.model,
        reasoning_effort="local_deterministic",
        limit=args.limit,
        overwrite=args.overwrite,
        workers=1,
        runner=runner,
    )
    judgments_path = args.output_dir / "judgments.jsonl"
    judgments = BASE.load_jsonl(judgments_path)
    for judgment in judgments:
        provenance = judgment.setdefault("review_provenance", {})
        provenance.update(
            {
                "evaluated_model_id": evaluated_model,
                "evaluated_model_revision": evaluated_revision,
                "judge_model_id": args.model,
                "judge_model_revision": args.model_revision,
                "judge_seed": args.seed,
                "judge_generator_relationship": relationship,
                "judge_model_family": model_family(args.model),
                "evaluated_model_family": model_family(evaluated_model),
            }
        )
    BASE.write_jsonl(judgments_path, judgments)
    summary["review_boundary"] = (
        f"Uncalibrated offline blinded AI semantic triage ({relationship.replace('_', ' ')}). "
        "No rows left the device. Judge confidence is self-reported and scores may contain family, leniency, verbosity, "
        "reference-anchoring, or self-preference bias. Promotion remains blocked until agreement and false-accept rates "
        "are measured against blinded independent agronomist labels; this is not field validation or an official benchmark."
    )
    summary["external_export"] = False
    summary["judge_backend"] = "mlx_local"
    summary["evaluated_model_id"] = evaluated_model
    summary["evaluated_model_revision"] = evaluated_revision
    summary["judge_model_revision"] = args.model_revision
    summary["judge_seed"] = args.seed
    if args.seed is None:
        seed_status = "not_configured"
    elif runner.generation_calls == 0:
        seed_status = "not_applied_all_batches_reused_seed_bound_cache"
    elif len(runner.seed_application_receipts) != runner.generation_calls:
        seed_status = "application_receipt_incomplete"
    elif all(
        receipt.get("status") == "applied" and receipt.get("applied_seed") == args.seed
        for receipt in runner.seed_application_receipts
    ):
        seed_status = "applied"
    else:
        seed_status = "application_receipt_mismatch"
    summary["judge_seed_application"] = seed_status
    summary["judge_seed_application_receipt"] = {
        "schema_version": "open_agronomy_agent.local_judge_seed_application.v1",
        "requested_seed": args.seed,
        "backend": "mlx_local",
        "status": seed_status,
        "generation_calls": runner.generation_calls,
        "seed_application_receipts": runner.seed_application_receipts,
        "shared_cache_hits": runner.shared_cache_hits,
    }
    summary["judge_generator_relationship"] = relationship
    summary["judge_model_family"] = model_family(args.model)
    summary["evaluated_model_family"] = model_family(evaluated_model)
    summary["shared_prompt_cache"] = {
        "enabled": args.shared_cache_dir is not None,
        "path": str(args.shared_cache_dir) if args.shared_cache_dir is not None else None,
        "hits": runner.shared_cache_hits,
        "writes": runner.shared_cache_writes,
        "key_boundary": (
            "exact judge model revision, seed, sampler configuration, and blinded prompt only"
        ),
    }
    summary["schema_repair_attempts"] = runner.schema_repair_attempts
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "summary.md").write_text(BASE.render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
