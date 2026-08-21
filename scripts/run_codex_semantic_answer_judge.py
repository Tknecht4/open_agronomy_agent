#!/usr/bin/env python3
"""Run blinded semantic answer adjudication with Codex.

This runner deliberately keeps deterministic proxy scores, keyword contracts,
generation paths, tool traces, and prior findings out of the judge prompt. Those
signals remain useful diagnostics, but they are not agronomic answer quality.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics
import re
import shutil
import subprocess
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Iterable

from agronomy_agent.codex_app_server import CodexAppServerClient, DEFAULT_APP_SERVER_COMMAND


SCHEMA_VERSION = "open_agronomy_agent.codex_semantic_answer_judge.v1"
DEFAULT_OUTPUTS = Path(
    "outputs/evals/public_domain_coverage_full_frozen_1056_v6_240/"
    "agronomic_rag_20260714T105848Z/outputs.jsonl"
)
DEFAULT_OUTPUT_DIR = Path(
    "outputs/evals/public_domain_coverage_full_frozen_1056_v6_240/codex_semantic_judge"
)
DIMENSION_WEIGHTS = {
    "agronomic_accuracy": 0.35,
    "decision_relevance": 0.20,
    "completeness_actionability": 0.20,
    "calibration_safety": 0.15,
    "crop_region_source_fit": 0.10,
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def archive_invalid_batch(
    *,
    result_path: Path,
    prompt_path: Path,
    error: Exception,
) -> Path:
    failed_dir = result_path.parent.parent / "failed_attempts"
    failed_dir.mkdir(parents=True, exist_ok=True)
    stem = result_path.stem
    attempt = 1
    while (failed_dir / f"{stem}_attempt_{attempt:04d}.error.json").exists():
        attempt += 1
    prefix = failed_dir / f"{stem}_attempt_{attempt:04d}"
    sources = {
        ".json": result_path,
        ".prompt.txt": prompt_path,
        ".receipt.json": result_path.with_suffix(".receipt.json"),
    }
    for suffix, source in sources.items():
        if source.is_file():
            shutil.copy2(source, Path(str(prefix) + suffix))
    Path(str(prefix) + ".error.json").write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.invalid_judge_batch_attempt.v1",
                "recorded_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
                "error_type": type(error).__name__,
                "error": str(error),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return prefix


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def judge_generator_relationship(judge_model: str, source_models: Iterable[str]) -> str:
    normalized = {str(value).strip().lower() for value in source_models if str(value).strip()}
    judge = judge_model.strip().lower()
    if not normalized:
        return "unknown"
    if judge in normalized:
        return "same_exact_model"
    if judge.startswith("gpt-") and any(value.startswith("gpt-") for value in normalized):
        return "same_provider_model_family"
    return "cross_model"


def blind_item(row: dict[str, Any]) -> dict[str, Any]:
    """Return only information a semantic answer judge should see."""

    metadata = row.get("eval_metadata") or {}
    semantic_reference = row.get("semantic_reference") or {}
    reference_answer = _clean(
        semantic_reference.get("reference_answer")
        or row.get("reference_answer")
        or row.get("expected_answer")
    )
    reference_points = semantic_reference.get("expert_reference_points") or row.get("expert_reference_points") or []
    material_errors = semantic_reference.get("material_errors") or row.get("material_errors") or []
    critical_evidence = semantic_reference.get("critical_evidence") or row.get("critical_evidence") or []
    safe_boundary = _clean(semantic_reference.get("safe_boundary") or row.get("safe_boundary"))
    acceptable_variants = (
        semantic_reference.get("acceptable_answer_variants")
        or row.get("acceptable_answer_variants")
        or []
    )
    return {
        # A post-hoc packet can carry an opaque, per-answer review ID.  Prefer
        # it to the repeated eval ID so paired raw/governed answers remain
        # blinded and unambiguous in one judge batch.
        "review_id": _clean(row.get("review_id") or row.get("eval_id") or row.get("source_id")),
        "question": _clean(row.get("question")),
        "answer": _clean(row.get("output") or row.get("answer") or row.get("saved_answer")),
        "crop": _clean(metadata.get("crop") or row.get("crop")),
        "region": _clean(metadata.get("region") or row.get("region") or row.get("context_label")),
        "jurisdiction": _clean(metadata.get("jurisdiction") or row.get("jurisdiction")),
        "scenario": _clean(metadata.get("scenario_type") or row.get("scenario_type")),
        "task_family": _clean(row.get("task_family") or row.get("coverage_domain")),
        "reference_answer": reference_answer,
        "expert_reference_points": [_clean(value) for value in reference_points if _clean(value)],
        "material_errors": [_clean(value) for value in material_errors if _clean(value)],
        "critical_evidence": [_clean(value) for value in critical_evidence if _clean(value)],
        "safe_boundary": safe_boundary,
        "acceptable_answer_variants": [_clean(value) for value in acceptable_variants if _clean(value)],
    }


def judge_schema() -> dict[str, Any]:
    dimension_properties = {
        name: {"type": "number", "minimum": 0, "maximum": 4}
        for name in DIMENSION_WEIGHTS
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["judgments"],
        "properties": {
            "judgments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "review_id",
                        "question_validity",
                        "answer_disposition",
                        "dimensions",
                        "confidence",
                        "material_errors",
                        "rationale",
                        "needs_source_validation",
                    ],
                    "properties": {
                        "review_id": {"type": "string"},
                        "question_validity": {
                            "type": "string",
                            "enum": ["valid", "questionable", "invalid"],
                        },
                        "answer_disposition": {
                            "type": "string",
                            "enum": ["pass", "revise", "fail"],
                        },
                        "dimensions": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": list(DIMENSION_WEIGHTS),
                            "properties": dimension_properties,
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                        "material_errors": {
                            "type": "array",
                            "maxItems": 5,
                            "items": {"type": "string"},
                        },
                        "rationale": {"type": "string", "maxLength": 600},
                        "needs_source_validation": {"type": "boolean"},
                    },
                },
            }
        },
    }


JUDGE_INSTRUCTIONS = """You are the independent semantic agronomy judge for an open agronomy agent.

Evaluate every question-answer pair on its actual meaning. Do not use keyword overlap,
checklist length, writing style, or the number of caveats as a substitute for quality.
The records are blinded: you do not know the proxy score, generation path, or verifier result.
Some records include a reference answer, expert points, known material errors, critical evidence,
a safety boundary, or acceptable answer variants. Treat all of these as non-exhaustive semantic
criteria, not as wording targets: a different answer can be fully correct, and a matching answer
can still be wrong if it mishandles the question's facts. Material errors describe mistakes that
would matter if the answer actually makes them; do not penalize an answer merely for not naming them.

Rubric, each 0 to 4:
- agronomic_accuracy: factual and causal correctness; no invented field facts.
- decision_relevance: directly resolves the grower's decision rather than reciting a generic checklist.
- completeness_actionability: includes the material observations, decision logic, and next action needed at this scope.
- calibration_safety: distinguishes evidence from inference and avoids unsupported rates, labels, diagnoses, or guarantees.
- crop_region_source_fit: terminology, production system, source coverage, crop biology, and jurisdiction fit the case.

Disposition:
- pass: sound and useful as written; only cosmetic improvements remain.
- revise: directionally sound but has a repairable omission, overgeneralization, or distracting claim.
- fail: a material factual error, wrong crop/source/system, invented premise, irrelevant response, unsafe certainty, or failure to answer the central decision.

Judge question validity separately. A bad or implausible question may be invalid, but still judge whether the answer notices and handles the bad premise. Use concise snake_case material error codes. Give a specific rationale of at most 60 words. Mark needs_source_validation when a current local label, regulation, numeric threshold, or niche factual claim would need authoritative confirmation. Return one judgment for every supplied review_id and no others.
"""

JUDGE_ROLE_FOCUS = {
    "semantic_answer_quality": (
        "Judge the complete answer across all rubric dimensions. Do not let style compensate for factual or safety defects."
    ),
    "evidence_fidelity": (
        "Prioritize whether every material claim is supported by the supplied case evidence, whether citations or source "
        "attributions are valid, and whether contradictions or missing evidence are disclosed."
    ),
    "agronomic_reasoning_applicability": (
        "Prioritize crop, production system, jurisdiction, date, units, causal reasoning, and whether the proposed action "
        "actually follows from the supplied observations and evidence."
    ),
    "decision_safety_uncertainty": (
        "Prioritize calibration, abstention when decision-critical facts are absent, current-label and jurisdiction boundaries, "
        "and whether a grower could be harmed by acting on unsupported certainty."
    ),
    "appeal": (
        "Resolve a documented disagreement among primary judge roles. Identify the decisive evidence and do not average away "
        "a material factual, jurisdictional, or safety defect."
    ),
}


def judge_instructions(judge_role: str) -> str:
    try:
        focus = JUDGE_ROLE_FOCUS[judge_role]
    except KeyError as exc:
        raise ValueError(f"unknown judge role: {judge_role}") from exc
    return JUDGE_INSTRUCTIONS + "\nRole-specific focus: " + focus + "\n"


def build_prompt(
    items: list[dict[str, Any]],
    judge_role: str = "semantic_answer_quality",
) -> str:
    return judge_instructions(judge_role) + "\nBlinded records:\n" + json.dumps(items, ensure_ascii=True, indent=2)


def semantic_score(judgment: dict[str, Any]) -> float:
    dimensions = judgment["dimensions"]
    return round(sum(float(dimensions[name]) * weight for name, weight in DIMENSION_WEIGHTS.items()) / 4 * 100, 2)


def validate_batch(payload: dict[str, Any], expected_ids: list[str]) -> list[dict[str, Any]]:
    judgments = payload.get("judgments")
    if not isinstance(judgments, list):
        raise ValueError("Judge output does not contain a judgments list")
    actual_ids = [str(item.get("review_id") or "") for item in judgments]
    if len(actual_ids) != len(set(actual_ids)):
        raise ValueError("Judge output contains duplicate review_id values")
    if set(actual_ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(actual_ids))
        extra = sorted(set(actual_ids) - set(expected_ids))
        raise ValueError(f"Judge output ID mismatch: missing={missing}, extra={extra}")
    by_id = {str(item["review_id"]): item for item in judgments}
    ordered = [by_id[review_id] for review_id in expected_ids]
    for item in ordered:
        item["semantic_score_0_to_100"] = semantic_score(item)
    return ordered


def recoverable_missing_ids(payload: dict[str, Any], expected_ids: list[str]) -> list[str]:
    """Return missing IDs only when the payload is an otherwise clean subset.

    Recovery is intentionally narrow. Duplicate IDs, unexpected IDs, malformed
    payloads, and complete payloads remain hard failures rather than being
    merged into a canonical batch.
    """

    judgments = payload.get("judgments")
    if not isinstance(judgments, list):
        return []
    actual_ids = [str(item.get("review_id") or "") for item in judgments]
    if not actual_ids or len(actual_ids) != len(set(actual_ids)):
        return []
    expected = set(expected_ids)
    actual = set(actual_ids)
    if not actual < expected:
        return []
    return [review_id for review_id in expected_ids if review_id not in actual]


def run_codex_batch(
    *,
    prompt: str,
    schema_path: Path,
    result_path: Path,
    model: str,
    reasoning_effort: str,
    cwd: Path,
) -> dict[str, Any]:
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(result_path),
        "-",
    ]
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
    )
    result_path.with_suffix(".stdout.log").write_text(completed.stdout, encoding="utf-8")
    result_path.with_suffix(".stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"Codex judge failed with exit code {completed.returncode}: {completed.stderr[-1200:]}")
    return json.loads(result_path.read_text(encoding="utf-8"))


class AppServerJudgeRunner:
    """Thread-local App Server runner with one reusable process per worker."""

    def __init__(
        self,
        *,
        command: tuple[str, ...] = DEFAULT_APP_SERVER_COMMAND,
        timeout_seconds: float = 360.0,
        collect_protocol_identity: bool = True,
        server_cwd: Path = Path("/private/tmp"),
        judge_role: str = "semantic_answer_quality",
    ) -> None:
        raise RuntimeError(
            "App Server semantic judging is disabled until a dedicated judge-egress "
            "authorization contract is implemented"
        )
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.collect_protocol_identity = collect_protocol_identity
        self.server_cwd = server_cwd.resolve()
        self.judge_role = judge_role
        self._local = threading.local()
        self._clients: list[CodexAppServerClient] = []
        self._clients_lock = threading.Lock()

    def _client(self, *, model: str, reasoning_effort: str, cwd: Path) -> CodexAppServerClient:
        client = getattr(self._local, "client", None)
        identity = getattr(self._local, "identity", None)
        expected_identity = (model, reasoning_effort, str(self.server_cwd))
        if client is not None and identity == expected_identity:
            return client
        client = CodexAppServerClient(
            command=self.command,
            cwd=self.server_cwd,
            timeout_seconds=self.timeout_seconds,
            expected_model=model,
            expected_reasoning_effort=reasoning_effort,
            collect_protocol_identity=self.collect_protocol_identity,
        )
        self._local.client = client
        self._local.identity = expected_identity
        with self._clients_lock:
            self._clients.append(client)
        return client

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
        client = self._client(model=model, reasoning_effort=reasoning_effort, cwd=cwd)
        blinded_records = prompt
        instructions = judge_instructions(self.judge_role)
        prefix = instructions + "\n"
        if blinded_records.startswith(prefix):
            blinded_records = blinded_records[len(prefix) :]
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        result = client.generate(
            user_text=blinded_records,
            base_instructions=instructions,
            output_schema=schema,
            metadata={"application": "open-agronomy-benchmark", "role": "semantic-judge"},
        )
        result_path.write_text(result.text + "\n", encoding="utf-8")
        result_path.with_suffix(".receipt.json").write_text(
            json.dumps(result.receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            payload = json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise ValueError("App Server judge returned invalid structured JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("App Server judge returned a non-object JSON result")
        return payload

    def close(self) -> None:
        for client in self._clients:
            client.close()
        self._clients.clear()


def _mean(values: Iterable[float]) -> float | None:
    materialized = list(values)
    return round(statistics.mean(materialized), 2) if materialized else None


def _pearson(pairs: Iterable[tuple[float, float]]) -> float | None:
    materialized = list(pairs)
    if len(materialized) < 2:
        return None
    left = [pair[0] for pair in materialized]
    right = [pair[1] for pair in materialized]
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in materialized)
    denominator = (
        sum((x - left_mean) ** 2 for x in left)
        * sum((y - right_mean) ** 2 for y in right)
    ) ** 0.5
    return round(numerator / denominator, 4) if denominator else None


def _answer_word_count(row: dict[str, Any]) -> int:
    return len(re.findall(r"\b\w+\b", str(row.get("answer") or "")))


def _group_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        value = row.get(key)
        if value in (None, ""):
            value = (row.get("eval_metadata") or {}).get(key)
        groups[_clean(value) or "unspecified"].append(row)
    return {
        label: {
            "rows": len(group),
            "semantic_score_mean": _mean(float(row["semantic_score_0_to_100"]) for row in group),
            "answer_disposition": dict(Counter(row["answer_disposition"] for row in group)),
            "needs_source_validation": sum(bool(row["needs_source_validation"]) for row in group),
        }
        for label, group in sorted(groups.items())
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid_rows = [row for row in rows if row["question_validity"] == "valid"]
    dimensions = {
        name: _mean(float(row["dimensions"][name]) / 4 * 100 for row in rows)
        for name in DIMENSION_WEIGHTS
    }
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_path[str(row.get("generation_path") or "unknown")].append(row)
    proxy_pairs = [
        (float(row["proxy_score_0_to_100"]), float(row["semantic_score_0_to_100"]))
        for row in rows
        if row.get("proxy_score_0_to_100") is not None
    ]
    semantic_mean = _mean(float(row["semantic_score_0_to_100"]) for row in rows)
    proxy_mean = _mean(pair[0] for pair in proxy_pairs)
    length_pairs = [
        (float(_answer_word_count(row)), float(row["semantic_score_0_to_100"]))
        for row in rows
    ]
    pass_rate = sum(row["answer_disposition"] == "pass" for row in rows) / max(1, len(rows))
    high_confidence_rate = sum(row["confidence"] == "high" for row in rows) / max(1, len(rows))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "primary_quality_signal": "blinded_automated_semantic_triage",
        "deterministic_signal_role": "diagnostic_only",
        "promotion_eligible": False,
        "human_calibration_status": "missing",
        "human_calibration_required": True,
        "composite_score": None,
        "row_count": len(rows),
        "question_validity": dict(Counter(row["question_validity"] for row in rows)),
        "answer_disposition": dict(Counter(row["answer_disposition"] for row in rows)),
        "confidence": dict(Counter(row["confidence"] for row in rows)),
        "semantic_score_mean": semantic_mean,
        "semantic_score_valid_questions": _mean(
            float(row["semantic_score_0_to_100"]) for row in valid_rows
        ),
        "proxy_score_mean": proxy_mean,
        "proxy_minus_semantic_points": (
            round(proxy_mean - semantic_mean, 2)
            if proxy_mean is not None and semantic_mean is not None
            else None
        ),
        "proxy_semantic_pearson": _pearson(proxy_pairs),
        "answer_length_semantic_pearson": _pearson(length_pairs),
        "judge_self_reported_high_confidence_rate": round(high_confidence_rate, 4),
        "ceiling_effect_flag": pass_rate >= 0.85 and high_confidence_rate >= 0.85,
        "high_proxy_semantic_failures": sum(
            row.get("proxy_score_0_to_100") is not None
            and float(row["proxy_score_0_to_100"]) >= 90
            and row["answer_disposition"] == "fail"
            for row in rows
        ),
        "dimensions_0_to_100": dimensions,
        "needs_source_validation": sum(bool(row["needs_source_validation"]) for row in rows),
        "top_material_errors": Counter(
            error for row in rows for error in row.get("material_errors") or []
        ).most_common(20),
        "by_generation_path": {
            path: {
                "rows": len(group),
                "semantic_score_mean": _mean(float(row["semantic_score_0_to_100"]) for row in group),
                "answer_disposition": dict(Counter(row["answer_disposition"] for row in group)),
            }
            for path, group in sorted(by_path.items())
        },
        "by_source": _group_summary(rows, "source"),
        "by_question_disposition": _group_summary(rows, "question_disposition"),
        "by_task_family": _group_summary(rows, "task_family"),
        "by_crop": _group_summary(rows, "crop"),
        "by_jurisdiction": _group_summary(rows, "jurisdiction"),
        "review_boundary": (
            "Uncalibrated blinded AI semantic triage of saved answers. Judge confidence is self-reported, not calibrated. "
            "The scores cannot support promotion or an answer-quality claim until agreement and false-accept rates are "
            "measured against blinded independent agronomist labels. This is not field validation or an official AI AgriBench score."
        ),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    dispositions = summary["answer_disposition"]
    validity = summary["question_validity"]
    lines = [
        "# Blinded Semantic Answer Adjudication",
        "",
        f"Generated: `{summary['generated_at']}`",
        "",
        "## Result",
        "",
        f"Rows judged: **{summary['row_count']}**",
        f"Semantic mean: **{summary['semantic_score_mean']}**",
        f"Semantic mean on valid questions: **{summary['semantic_score_valid_questions']}**",
        f"Saved deterministic proxy mean: **{summary['proxy_score_mean']}**",
        f"Proxy minus semantic: **{summary['proxy_minus_semantic_points']} points**",
        f"Proxy/semantic Pearson correlation: **{summary['proxy_semantic_pearson']}**",
        "",
        f"Answer dispositions: **{dispositions.get('pass', 0)} pass**, **{dispositions.get('revise', 0)} revise**, and **{dispositions.get('fail', 0)} fail**.",
        f"Question validity: **{validity.get('valid', 0)} valid**, **{validity.get('questionable', 0)} questionable**, and **{validity.get('invalid', 0)} invalid**.",
        f"High-proxy semantic failures: **{summary['high_proxy_semantic_failures']}**.",
        "",
        "## Dimensions",
        "",
        "| Dimension | Mean |",
        "|---|---:|",
    ]
    for name, value in summary["dimensions_0_to_100"].items():
        lines.append(f"| `{name}` | {value} |")
    lines.extend(["", "## Generation Path", "", "| Path | Rows | Semantic | Pass | Revise | Fail |", "|---|---:|---:|---:|---:|---:|"])
    for path, payload in summary["by_generation_path"].items():
        disp = payload["answer_disposition"]
        lines.append(
            f"| `{path}` | {payload['rows']} | {payload['semantic_score_mean']} | "
            f"{disp.get('pass', 0)} | {disp.get('revise', 0)} | {disp.get('fail', 0)} |"
        )
    for heading, key in (
        ("Source Packet", "by_source"),
        ("Question Disposition", "by_question_disposition"),
        ("Task Family", "by_task_family"),
        ("Crop", "by_crop"),
        ("Jurisdiction", "by_jurisdiction"),
    ):
        lines.extend(
            [
                "",
                f"## {heading}",
                "",
                "| Group | Rows | Semantic | Pass | Revise | Fail | Source validation |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for label, payload in summary[key].items():
            disp = payload["answer_disposition"]
            lines.append(
                f"| {label} | {payload['rows']} | {payload['semantic_score_mean']} | "
                f"{disp.get('pass', 0)} | {disp.get('revise', 0)} | {disp.get('fail', 0)} | "
                f"{payload['needs_source_validation']} |"
            )
    lines.extend(
        [
            "",
            "## Score Use",
            "",
            "Blinded semantic judgment is the primary local answer-quality signal. Deterministic proxy and verifier results are diagnostic only; no composite score is reported.",
            "",
            "## Boundary",
            "",
            summary["review_boundary"],
            "",
        ]
    )
    return "\n".join(lines)


def generation_path(row: dict[str, Any]) -> str:
    if "saved_answer" in row and "metadata" not in row:
        return "saved_review_answer"
    verification = (row.get("metadata") or {}).get("answer_verification") or {}
    if verification.get("fallback_applied"):
        return "deterministic_fallback"
    if verification.get("rewrite_accepted"):
        return "accepted_rewrite"
    return "accepted_draft"


def retained_answer(row: dict[str, Any]) -> str:
    """Return the exact answer that was presented to the blinded judge."""

    return str(row.get("output") or row.get("answer") or row.get("saved_answer") or "")


def retained_eval_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Preserve review stratifiers without exposing them to the judge prompt."""

    metadata = dict(row.get("eval_metadata") or {})
    for key in (
        "coverage_domain",
        "crop",
        "jurisdiction",
        "region",
        "context_label",
        "scenario_type",
        "source",
        "source_id",
        "question_disposition",
    ):
        value = row.get(key)
        if value not in (None, "", []):
            metadata.setdefault(key, value)
    return metadata


def run(
    *,
    outputs_path: Path,
    output_dir: Path,
    batch_size: int,
    model: str,
    reasoning_effort: str,
    limit: int | None,
    overwrite: bool,
    answered_only: bool = False,
    workers: int = 1,
    runner: Callable[..., dict[str, Any]] = run_codex_batch,
    judge_backend: str = "codex_exec",
    judge_role: str = "semantic_answer_quality",
    max_batch_attempts: int = 3,
) -> dict[str, Any]:
    if max_batch_attempts < 1:
        raise ValueError("max_batch_attempts must be at least 1")
    source_rows = load_jsonl(outputs_path)
    source_row_count = len(source_rows)
    source_model_ids = sorted(
        {str(row.get("model_id") or "").strip() for row in source_rows if str(row.get("model_id") or "").strip()}
    )
    model_relationship = judge_generator_relationship(model, source_model_ids)
    skipped_without_answer = 0
    if answered_only:
        answered_rows = [row for row in source_rows if blind_item(row)["answer"]]
        skipped_without_answer = len(source_rows) - len(answered_rows)
        source_rows = answered_rows
    if limit is not None:
        source_rows = source_rows[:limit]
    output_dir.mkdir(parents=True, exist_ok=True)
    batches_dir = output_dir / "batches"
    batches_dir.mkdir(exist_ok=True)
    schema_path = output_dir / "judge_output_schema.json"
    schema_path.write_text(json.dumps(judge_schema(), indent=2) + "\n", encoding="utf-8")

    all_judgments: list[dict[str, Any]] = []
    batch_count = (len(source_rows) + batch_size - 1) // batch_size
    batch_inputs = [
        (offset // batch_size + 1, source_rows[offset : offset + batch_size])
        for offset in range(0, len(source_rows), batch_size)
    ]

    def judge_one_batch(
        batch_input: tuple[int, list[dict[str, Any]]],
    ) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        batch_number, batch_rows = batch_input
        blind_rows = [blind_item(row) for row in batch_rows]
        expected_ids = [row["review_id"] for row in blind_rows]
        result_path = batches_dir / f"batch_{batch_number:04d}.json"
        prompt_path = batches_dir / f"batch_{batch_number:04d}.prompt.txt"
        prompt = build_prompt(blind_rows, judge_role=judge_role)
        prompt_path.write_text(prompt, encoding="utf-8")
        recovered_ids: list[str] = []
        used_cache = result_path.exists() and not overwrite
        if used_cache:
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                judgments = validate_batch(payload, expected_ids)
            except (json.JSONDecodeError, ValueError) as exc:
                archived = archive_invalid_batch(
                    result_path=result_path,
                    prompt_path=prompt_path,
                    error=exc,
                )
                print(f"archived invalid cached judge batch {batch_number}: {archived}", flush=True)
                used_cache = False
        if not used_cache:
            for attempt in range(1, max_batch_attempts + 1):
                payload = runner(
                    prompt=prompt,
                    schema_path=schema_path,
                    result_path=result_path,
                    model=model,
                    reasoning_effort=reasoning_effort,
                    cwd=Path.cwd(),
                )
                try:
                    judgments = validate_batch(payload, expected_ids)
                    break
                except (json.JSONDecodeError, ValueError) as exc:
                    archived = archive_invalid_batch(
                        result_path=result_path,
                        prompt_path=prompt_path,
                        error=exc,
                    )
                    print(
                        f"invalid judge batch {batch_number} attempt {attempt}/{max_batch_attempts}; "
                        f"archived={archived}",
                        flush=True,
                    )
                    if attempt == max_batch_attempts:
                        recovered_ids = recoverable_missing_ids(payload, expected_ids)
                        if not recovered_ids or len(batch_rows) == 1:
                            raise
                        recovered: list[dict[str, Any]] = []
                        rows_by_id = {
                            str(blind_row["review_id"]): blind_row for blind_row in blind_rows
                        }
                        for recovery_number, review_id in enumerate(recovered_ids, start=1):
                            recovery_result_path = (
                                batches_dir
                                / f"batch_{batch_number:04d}_recovery_{recovery_number:04d}.json"
                            )
                            recovery_prompt_path = recovery_result_path.with_suffix(".prompt.txt")
                            recovery_prompt = build_prompt(
                                [rows_by_id[review_id]], judge_role=judge_role
                            )
                            recovery_prompt_path.write_text(recovery_prompt, encoding="utf-8")
                            for recovery_attempt in range(1, max_batch_attempts + 1):
                                recovery_payload = runner(
                                    prompt=recovery_prompt,
                                    schema_path=schema_path,
                                    result_path=recovery_result_path,
                                    model=model,
                                    reasoning_effort=reasoning_effort,
                                    cwd=Path.cwd(),
                                )
                                try:
                                    recovered.extend(
                                        validate_batch(recovery_payload, [review_id])
                                    )
                                    break
                                except (json.JSONDecodeError, ValueError) as recovery_exc:
                                    archived_recovery = archive_invalid_batch(
                                        result_path=recovery_result_path,
                                        prompt_path=recovery_prompt_path,
                                        error=recovery_exc,
                                    )
                                    print(
                                        f"invalid judge recovery for batch {batch_number} "
                                        f"ID {review_id} attempt {recovery_attempt}/"
                                        f"{max_batch_attempts}; archived={archived_recovery}",
                                        flush=True,
                                    )
                                    if recovery_attempt == max_batch_attempts:
                                        raise
                        combined_payload = {
                            "judgments": list(payload.get("judgments") or []) + recovered
                        }
                        judgments = validate_batch(combined_payload, expected_ids)
                        # The full-batch receipt belongs to the archived invalid
                        # call, not to this deterministic merge. Keep only the
                        # valid recovery call receipts on the canonical surface.
                        result_path.with_suffix(".receipt.json").unlink(missing_ok=True)
                        result_path.write_text(
                            json.dumps(combined_payload, indent=2) + "\n",
                            encoding="utf-8",
                        )
                        print(
                            f"recovered judge batch {batch_number} through "
                            f"{len(recovered_ids)} isolated exact-ID request(s)",
                            flush=True,
                        )
                        break
        return batch_number, batch_rows, judgments, recovered_ids

    if workers == 1:
        batch_results = map(judge_one_batch, batch_inputs)
    else:
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="semantic-judge")
        batch_results = executor.map(judge_one_batch, batch_inputs)

    try:
        for batch_number, batch_rows, judgments, recovered_ids in batch_results:
            for source, judgment in zip(batch_rows, judgments, strict=True):
                judgment["question"] = source.get("question")
                judgment["answer"] = retained_answer(source)
                judgment["task_family"] = source.get("task_family") or source.get("coverage_domain")
                judgment["eval_metadata"] = retained_eval_metadata(source)
                source_score = source.get("score") if isinstance(source.get("score"), dict) else None
                judgment["proxy_score_0_to_100"] = (
                    source_score.get("score")
                    if source_score is not None and source_score.get("proxy_valid", True)
                    else source.get("saved_proxy_score") if source_score is None else None
                )
                judgment["generation_path"] = generation_path(source)
                judgment["review_provenance"] = {
                    "reviewer": f"Codex {model}",
                    "reviewer_type": "blinded_ai_semantic_judge",
                    "reasoning_effort": reasoning_effort,
                    "human_agronomist_signoff": False,
                    "official_ai_agribench": False,
                }
                all_judgments.append(judgment)
            print(
                f"judged batch {batch_number}/{batch_count} "
                f"({len(all_judgments)}/{len(source_rows)} rows)",
                flush=True,
            )
    finally:
        if workers != 1:
            executor.shutdown(wait=True, cancel_futures=True)

    rows_path = output_dir / "judgments.jsonl"
    write_jsonl(rows_path, all_judgments)
    receipt_paths = sorted(batches_dir.glob("batch_*.receipt.json"))
    receipt_hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in receipt_paths]
    recovery_paths = sorted(batches_dir.glob("batch_*_recovery_*.json"))
    recovered_batch_numbers: set[str] = set()
    recovered_ids_from_artifacts: set[str] = set()
    for recovery_path in recovery_paths:
        match = re.match(r"batch_(\d{4})_recovery_\d{4}\.json$", recovery_path.name)
        if not match:
            continue
        recovered_batch_numbers.add(match.group(1))
        recovery_payload = json.loads(recovery_path.read_text(encoding="utf-8"))
        for judgment in recovery_payload.get("judgments") or []:
            review_id = str(judgment.get("review_id") or "")
            if review_id:
                recovered_ids_from_artifacts.add(review_id)
    protocol_identity = None
    if receipt_paths:
        first_receipt = json.loads(receipt_paths[0].read_text(encoding="utf-8"))
        protocol_identity = first_receipt.get("protocol_identity")
    summary = summarize(all_judgments)
    summary.update(
        {
            "source_outputs": str(outputs_path),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "batch_size": batch_size,
            "max_batch_attempts": max_batch_attempts,
            "workers": workers,
            "source_row_count": source_row_count,
            "answered_only": answered_only,
            "skipped_without_answer": skipped_without_answer,
            "row_artifact": str(rows_path),
            "judge_backend": judge_backend,
            "judge_role": judge_role,
            "judge_prompt_sha256": _sha256_text(judge_instructions(judge_role)),
            "judge_output_schema_sha256": _sha256_text(
                json.dumps(judge_schema(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            ),
            "app_server_receipt_count": len(receipt_paths),
            "app_server_receipts_sha256": (
                _sha256_text("\n".join(receipt_hashes)) if receipt_hashes else None
            ),
            "app_server_protocol_identity": protocol_identity,
            "source_model_ids": source_model_ids,
            "judge_generator_relationship": model_relationship,
            "same_model_judge_conflict": model_relationship == "same_exact_model",
            "recovered_batch_count": len(recovered_batch_numbers),
            "recovered_judgment_count": len(recovered_ids_from_artifacts),
        }
    )
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (output_dir / "summary.md").write_text(render_markdown(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--workers", type=int, default=1, help="Independent judge batches to run concurrently.")
    parser.add_argument("--max-batch-attempts", type=int, default=3)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default="high",
    )
    parser.add_argument(
        "--transport",
        choices=["app-server", "exec"],
        default="app-server",
        help="Use the auditable App Server JSONL transport or the historical codex exec fallback.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=360.0)
    parser.add_argument(
        "--judge-role",
        choices=sorted(JUDGE_ROLE_FOCUS),
        default="semantic_answer_quality",
        help="Run one blinded judge role. Primary roles should be stored as separate judge runs.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--answered-only",
        action="store_true",
        help="Judge only rows containing output, answer, or saved_answer text.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def validate_judge_transport(args: argparse.Namespace) -> None:
    """Fail closed until a dedicated semantic-judge egress contract exists."""

    raise ValueError(
        f"Codex semantic judging via {args.transport} is disabled because no dedicated "
        "judge-egress authorization contract is implemented"
    )


def main() -> None:
    args = parse_args()
    validate_judge_transport(args)
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")
    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if args.max_batch_attempts < 1:
        raise SystemExit("--max-batch-attempts must be at least 1")
    app_server_runner = (
        AppServerJudgeRunner(timeout_seconds=args.timeout_seconds, judge_role=args.judge_role)
        if args.transport == "app-server"
        else None
    )
    try:
        summary = run(
            outputs_path=args.outputs,
            output_dir=args.output_dir,
            batch_size=args.batch_size,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            limit=args.limit,
            overwrite=args.overwrite,
            answered_only=args.answered_only,
            workers=args.workers,
            runner=app_server_runner or run_codex_batch,
            judge_backend=(
                "codex_app_server_chatgpt_auth"
                if args.transport == "app-server"
                else "codex_exec"
            ),
            judge_role=args.judge_role,
            max_batch_attempts=args.max_batch_attempts,
        )
    finally:
        if app_server_runner is not None:
            app_server_runner.close()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
