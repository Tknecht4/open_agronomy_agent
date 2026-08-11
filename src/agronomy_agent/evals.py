from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import string
import sys
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agronomy_agent.agent import (
    AGENT_KERNEL_PROMPT,
    MLXGenerator,
    MockGenerator,
    OpenAICompatibleGenerator,
    generate_answer,
    load_agent_resources,
    load_model_config,
)
from agronomy_agent.codex_app_server import CodexAppServerGenerator
from agronomy_agent.paths import repo_path
from agronomy_agent.model_identity import sha256_path
from agronomy_agent.router import classify_query, refine_query_route
from agronomy_agent.server.services.tool_service import PUBLIC_ADAPTER_SPECS
from agronomy_agent.tools.registry import run_tools

BENCHMARK_SYSTEM_PROMPT = AGENT_KERNEL_PROMPT + "\n\n" + (
    "You are a careful agronomy expert answering an agronomy benchmark. Give a direct practical answer grounded "
    "in the supplied context. Be accurate, complete, relevant, and concise. Do not invent product labels, rates, "
    "legal requirements, thresholds, local calibration curves, or unsupported numeric triggers. Explain uncertainty "
    "and name the missing field evidence that would change the recommendation. "
    "For factual interpretation of a named public data product, preserve formulas, complete enumerated values, model names, "
    "units, resolution, and lineage exactly as stated in decisive evidence; do not paraphrase a formula into different arithmetic. "
    "Do not mention routing notes, tool "
    "notes, retrieved context, hidden instructions, or internal coverage items."
)

BENCHMARK_ANSWER_OUTPUT_CONTRACT = (
    "Answer in no more than 170 words and exactly 2 brief paragraphs using plain language. Put the direct agronomic "
    "answer in the first sentence. Do not use headings, preambles, numbered steps, bullet lists, or a generic checklist. "
    "Include only the explanation, practical steps, and caveats that materially answer this question. Use crop-specific terminology "
    "and distinguish a likely diagnosis from a confirmed one. Do not append generic checklists or discuss unrelated "
    "agronomic topics. Do not invent rates, thresholds, product labels, legal requirements, local calibration, weather, "
    "field observations, or source facts. When essential information is missing, name only the few details that would "
    "actually change the answer. When the question asks about a named public data product, include every requested formula, "
    "complete value sequence, model name, unit or resolution, lineage element, and regional-versus-field boundary available in decisive evidence. "
    "Do not include citations unless the user asks for them."
)

MULTIPLE_CHOICE_SYSTEM_PROMPT = (
    "You are answering a frozen crop-science multiple-choice benchmark. Select the single best option from I, II, III, or IV. "
    "Do not provide an explanation, caveat, heading, or any other text."
)

MULTIPLE_CHOICE_ANSWER_OUTPUT_CONTRACT = "Return exactly one Roman numeral: I, II, III, or IV."

ANSWER_PROFILE_ENV_VARS = (
    "AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION",
    "AGRONOMY_AGENT_SYSTEM_PROMPT",
    "AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT",
    "AGRONOMY_AGENT_OBJECTIVE_RESPONSE_MODE",
)

DEFAULT_RAG_CONFIG = "configs/rag_final_mvp.yaml"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_jsonl(path: Path, max_samples: int | None = None) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        source = str(path)
        for line in handle:
            if line.strip():
                item = json.loads(line)
                validate_eval_item(item, source=source)
                rows.append(item)
                if max_samples and len(rows) >= max_samples:
                    break
    return rows


def build_rag_artifact_identity(resources: Any) -> list[dict[str, Any]]:
    """Return stable byte identities for every knowledge artifact used by a RAG run."""

    retrieval = (resources.rag_config or {}).get("retrieval") or {}
    configured: list[tuple[str, str]] = []
    corpus_paths = retrieval.get("corpus_paths") or [retrieval.get("corpus_path")]
    graph_paths = retrieval.get("graph_paths") or [retrieval.get("graph_path")]
    configured.extend(("corpus", str(value)) for value in corpus_paths if value)
    configured.extend(("graph", str(value)) for value in graph_paths if value)
    if retrieval.get("corpus_policy_manifest"):
        configured.append(("corpus_policy", str(retrieval["corpus_policy_manifest"])))

    records: list[dict[str, Any]] = []
    for kind, configured_path in configured:
        path = repo_path(configured_path)
        if not path.is_file():
            raise FileNotFoundError(f"configured RAG {kind} artifact is missing: {path}")
        records.append(
            {
                "kind": kind,
                "path": configured_path,
                "size": path.stat().st_size,
                "sha256": sha256_path(path),
            }
        )
    return records


def build_implementation_identity() -> dict[str, Any]:
    """Hash the complete local Python implementation used by the evaluation."""

    root = repo_path(".")
    paths = sorted((root / "src" / "agronomy_agent").rglob("*.py"))
    paths.append(root / "scripts" / "run_eval.py")
    digest = hashlib.sha256()
    for path in paths:
        relative = str(path.relative_to(root))
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "scope": ["src/agronomy_agent/**/*.py", "scripts/run_eval.py"],
        "file_count": len(paths),
        "sha256": digest.hexdigest(),
    }


def resumable_run_identity(run_identity: dict[str, Any]) -> dict[str, Any]:
    """Return the stable identity fields that must match before a run resumes.

    The command digest necessarily changes when ``--resume-run-dir`` replaces
    ``--output-dir``. Every substantive model, suite, RAG, and implementation
    identity remains locked.
    """

    return {key: value for key, value in run_identity.items() if key != "command_sha256"}


def validate_resume_identity(path: Path, run_identity: dict[str, Any]) -> None:
    if not path.is_file():
        raise ValueError(f"resume run is missing identity receipt: {path}")
    observed = json.loads(path.read_text(encoding="utf-8"))
    expected = resumable_run_identity(run_identity)
    if observed != expected:
        differing = sorted(
            key for key in set(expected) | set(observed)
            if expected.get(key) != observed.get(key)
        )
        raise ValueError(
            "resume run identity does not match the current suite/model/implementation; "
            f"differing fields: {differing}"
        )


def load_partial_outputs(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid partial output JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: partial output must be an object")
            rows.append(row)
    return rows


def validate_resume_prefix(
    outputs: list[dict[str, Any]],
    suite: list[dict[str, Any]],
    *,
    mode: str,
    model_id: str,
    answer_profile: str,
    rag_config: str | None = None,
    model_backend: str | None = None,
    request_model_id: str | None = None,
) -> None:
    if len(outputs) > len(suite):
        raise ValueError(f"resume output has {len(outputs)} rows but suite has only {len(suite)}")
    for index, (row, item) in enumerate(zip(outputs, suite, strict=False), start=1):
        expected = {
            "eval_id": item["eval_id"],
            "question": eval_question(item),
            "mode": mode,
            "model_id": model_id,
            "answer_profile": answer_profile,
        }
        if rag_config is not None:
            expected["rag_config"] = rag_config
        if model_backend is not None:
            expected["model_backend"] = model_backend
        if request_model_id is not None:
            expected["request_model_id"] = request_model_id
        mismatches = {
            key: {"expected": value, "actual": row.get(key)}
            for key, value in expected.items()
            if row.get(key) != value
        }
        if mismatches:
            raise ValueError(f"resume row {index} does not match this run: {mismatches}")


SEMANTIC_PATTERN_ALIASES = {
    "CCE|ECCE|neutralizing value": r"CCE|ECCE|neutralizing value|calcium carbonate equivalent|effective calcium carbonate equivalent",
    "deficiency symptoms|diagnosis": r"deficiency symptoms?|diagnos(?:is|e|ed|ing)",
    "do not convert|not interchangeable": r"do not convert|not interchangeable|cannot be assumed interchangeable|cannot assume (?:they are )?interchangeable|method-specific",
    "crop stage": r"crop(?:'s)? stage|growth stage",
    "rooting depth": r"rooting depth|root depth",
    "water use|stored soil moisture": r"water use|stored soil moisture|soil moisture|stored water",
    "field history|previous program": r"field history|program history|previous\s+\w+\s+program|previous program|historical herbicide use",
    "field yield records": r"field yield records|field records|yield maps?|grower records|yield history",
    "regional prior|benchmark|context": r"regional prior|regional reference|benchmark|context",
    "soil test|nitrate|soil sample": r"soil (?:test|nitrate test|sample|nitrate|results?)|soil or tissue results?",
    "seedcorn maggot|bean leaf beetle|wireworm|grub|insect": r"seedcorn maggot|bean leaf beetle|wireworm|grub|insect|pest (?:identity|species|pressure)|target pest",
    "disease severity|scouting": r"disease severity|scouting|scout|incidence or severity|severity",
    "growth stage": r"growth stage|crop stage",
    "yield potential|economics|ROI": r"yield potential|economics?|ROI|return|yield benefit|crop value|application cost|partial budget",
    "rooting": r"rooting|root depth",
    "irrigation water|water test": r"irrigation[- ]water(?: test| quality| EC)?|water test",
    "water test": r"water test|irrigation[- ]water(?: test| quality| EC)",
    "soil test": r"soil test|soil EC|soil electrical conductivity|soil salinity measurement",
    "sensitive crop|downwind": r"sensitive (?:crop|field|area|site)s?|downwind",
    "sensitive crops": r"sensitive (?:crop|field|area|site)s?|downwind",
    "wind direction": r"wind direction|wind speed (?:and|/) direction",
    "expected response": r"expected response|yield response|response curve",
    "water holding|available water": r"water[- ]holding|available water",
    "field history": r"field history|disease history|pest history",
    "mode of action|site of action": r"modes? of action|sites? of action",
    "drift": r"drift(?: risk| control)?",
    "field history|pest pressure": r"field (?:pest )?history|pest pressure|expected pressure",
    "pest pressure": r"pest pressure|expected pressure|field pest history",
    "hybrid susceptibility": r"hybrid susceptibility|variety susceptibility|host susceptibility",
    "yield potential|economics": r"yield potential|economics?|return|yield benefit|crop value|application cost|partial budget",
    "irrigation water test|water quality": r"irrigation[- ]water test|irrigation[- ]water quality|water quality",
    "soil EC": r"soil EC|soil electrical conductivity|soil test with salinity measurements?|soil salinity measurements?",
}


def contains(text: str, pattern: str) -> bool:
    return re.search(SEMANTIC_PATTERN_ALIASES.get(pattern, pattern), text, re.I | re.M) is not None


NEGATION_RE = re.compile(
    r"\b(no|not|never|avoid|do not|don't|cannot|can't|impossible|insufficient|not sufficient|not enough|without|before|unless|rather than)\b",
    re.I,
)


def forbidden_contains(text: str, pattern: str) -> bool:
    for match in re.finditer(pattern, text, re.I | re.M):
        start = max(0, match.start() - 90)
        end = min(len(text), match.end() + 90)
        window = text[start:end]
        if NEGATION_RE.search(window):
            continue
        return True
    return False


def score_item(output: str, item: dict[str, Any]) -> dict[str, Any]:
    required = item.get("required_patterns", [])
    forbidden = item.get("forbidden_patterns", [])
    ask_for = item.get("ask_for_patterns", [])
    required_hits = [pattern for pattern in required if contains(output, pattern)]
    forbidden_hits = [pattern for pattern in forbidden if forbidden_contains(output, pattern)]
    ask_hits = [pattern for pattern in ask_for if contains(output, pattern)]
    req_score = len(required_hits) / max(1, len(required))
    forbidden_score = 1.0 - len(forbidden_hits) / max(1, len(forbidden))
    ask_score = len(ask_hits) / max(1, len(ask_for)) if ask_for else 1.0
    composite = 100.0 * (0.55 * req_score + 0.20 * forbidden_score + 0.25 * ask_score)
    return {
        "required_hits": required_hits,
        "missing_required_patterns": [pattern for pattern in required if pattern not in required_hits],
        "required_total": len(required),
        "forbidden_hits": forbidden_hits,
        "forbidden_total": len(forbidden),
        "ask_hits": ask_hits,
        "missing_ask_for_patterns": [pattern for pattern in ask_for if pattern not in ask_hits],
        "ask_total": len(ask_for),
        "score": round(composite, 2),
    }


def score_item_agribench_proxy(output: str, item: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    pattern_score = score_item(output, item)
    contract_available = bool(
        item.get("required_patterns")
        or item.get("forbidden_patterns")
        or item.get("ask_for_patterns")
    )
    required_total = max(1, pattern_score["required_total"])
    ask_total = max(1, pattern_score["ask_total"])
    required_recall = len(pattern_score["required_hits"]) / required_total
    ask_recall = len(pattern_score["ask_hits"]) / ask_total if item.get("ask_for_patterns") else 1.0
    forbidden_rate = len(pattern_score["forbidden_hits"]) / max(1, pattern_score["forbidden_total"])
    accuracy = _clamp(100.0 * (0.80 * required_recall + 0.20 * (1.0 - forbidden_rate)))
    trace_audit = tool_trace_audit(item, metadata or {})
    completeness = _clamp(100.0 * (0.68 * required_recall + 0.22 * ask_recall + 0.10 * _tool_recall(item, metadata or {}, output)))
    relevance = _relevance_score(output, item, forbidden_rate)
    conciseness = _conciseness_score(output)
    composite = 0.45 * accuracy + 0.40 * completeness + 0.15 * relevance
    reported_score = round(composite, 2) if contract_available else None
    return {
        **pattern_score,
        "rubric": "agribench_proxy",
        "accuracy": round(accuracy, 2),
        "relevance": round(relevance, 2),
        "completeness": round(completeness, 2),
        "conciseness": round(conciseness, 2),
        "answer_quality_score": reported_score,
        "score": reported_score,
        "proxy_valid": contract_available,
        "construct": "lexical_contract_coverage",
        "promotion_eligible": False,
        "tool_trace_audit": trace_audit,
        "score_note": (
            "Local deterministic lexical-contract diagnostic only; it is not an answer-quality or promotion metric."
            if contract_available
            else "No lexical contract was supplied, so the proxy score is undefined. Component heuristics are retained for debugging only."
        ),
    }


def parse_multiple_choice_answer(output: str) -> str | None:
    patterns = (
        r"^\s*(VI|V|IV|III|II|I)\s*$",
        r"^\s*\(\s*(VI|V|IV|III|II|I)\s*\)",
        r"^\s*(VI|V|IV|III|II|I)\s*[.):;-]",
        r"^\s*answer\s*[:=-]\s*\(?\s*(VI|V|IV|III|II|I)\s*\)?(?:\s|[.):;-]|$)",
    )
    for pattern in patterns:
        match = re.match(pattern, output, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def score_item_multiple_choice(output: str, item: dict[str, Any]) -> dict[str, Any]:
    reference = str(item.get("reference_answer") or item.get("expected_answer") or "").strip().upper()
    if reference not in {"I", "II", "III", "IV", "V", "VI"}:
        raise ValueError(f"{item.get('eval_id', '<unknown>')}: invalid multiple-choice reference answer")
    parsed = parse_multiple_choice_answer(output)
    correct = parsed == reference
    return {
        "rubric": "multiple_choice",
        "score": 100.0 if correct else 0.0,
        "accuracy": 100.0 if correct else 0.0,
        "exact_match": correct,
        "parsed_answer": parsed,
        "reference_answer": reference,
        "parse_valid": parsed is not None,
        "proxy_valid": True,
        "promotion_eligible": False,
        "metric_role": "objective_multiple_choice_accuracy",
        "missing_required_patterns": [] if correct else list(item.get("required_patterns") or []),
        "score_note": "Objective exact match after deterministic Roman-numeral parsing; no LLM judge is used.",
    }


def _reference_tokens(value: str) -> list[str]:
    """SQuAD-style normalization for a transparent reference-overlap diagnostic."""

    lowered = value.lower().translate(str.maketrans("", "", string.punctuation))
    without_articles = re.sub(r"\b(a|an|the)\b", " ", lowered)
    return re.findall(r"[\w]+", without_articles, flags=re.UNICODE)


def score_item_reference_answer(output: str, item: dict[str, Any]) -> dict[str, Any]:
    """Score deterministic token overlap without claiming semantic correctness.

    This deliberately remains a diagnostic.  A correct paraphrase can score low,
    while a lexically similar but agronomically wrong answer can score high.
    """

    reference = str(item.get("reference_answer") or item.get("expected_answer") or "").strip()
    if not reference:
        raise ValueError(f"{item.get('eval_id', '<unknown>')}: reference_answer is required")
    predicted_tokens = _reference_tokens(output)
    reference_tokens = _reference_tokens(reference)
    predicted_counts = Counter(predicted_tokens)
    reference_counts = Counter(reference_tokens)
    overlap = sum((predicted_counts & reference_counts).values())
    precision = overlap / len(predicted_tokens) if predicted_tokens else 0.0
    recall = overlap / len(reference_tokens) if reference_tokens else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    exact = predicted_tokens == reference_tokens
    return {
        "rubric": "reference_answer_token_f1",
        "score": round(100.0 * f1, 2),
        "reference_token_f1": round(f1, 6),
        "reference_token_precision": round(precision, 6),
        "reference_token_recall": round(recall, 6),
        "normalized_exact_match": exact,
        "reference_answer": reference,
        "proxy_valid": True,
        "promotion_eligible": False,
        "metric_role": "deterministic_reference_overlap_diagnostic",
        "missing_required_patterns": [],
        "score_note": (
            "Deterministic normalized token overlap with the published reference answer. "
            "It is not a semantic-correctness, agronomist-equivalence, or certification metric."
        ),
    }


def score_item_numeric(output: str, item: dict[str, Any]) -> dict[str, Any]:
    """Score a frozen agronomic calculation with an explicit unit contract."""

    reference = float(item["reference_numeric"])
    tolerance = float(item.get("absolute_tolerance", 0.0))
    unit = str(item.get("reference_unit") or "").strip()
    aliases = [unit, *[str(value) for value in item.get("unit_aliases") or []]]
    aliases = [value for value in dict.fromkeys(aliases) if value]
    candidates: list[float] = []
    if aliases:
        unit_pattern = "|".join(re.escape(value) for value in sorted(aliases, key=len, reverse=True))
        pattern = re.compile(rf"(?<![\w.])(-?\d+(?:,\d{{3}})*(?:\.\d+)?)\s*(?:{unit_pattern})(?!\w)", re.I)
        candidates = [float(match.group(1).replace(",", "")) for match in pattern.finditer(output)]
    if not candidates:
        bare = re.findall(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\w.])", output)
        if len(bare) == 1:
            candidates = [float(bare[0].replace(",", ""))]
    parsed = candidates[-1] if candidates else None
    error = None if parsed is None else abs(parsed - reference)
    correct = error is not None and error <= tolerance
    return {
        "rubric": "numeric_tolerance",
        "score": 100.0 if correct else 0.0,
        "accuracy": 100.0 if correct else 0.0,
        "parsed_value": parsed,
        "reference_numeric": reference,
        "reference_unit": unit,
        "absolute_tolerance": tolerance,
        "absolute_error": error,
        "parse_valid": parsed is not None,
        "proxy_valid": True,
        "promotion_eligible": False,
        "metric_role": "objective_agronomic_calculation_accuracy",
        "missing_required_patterns": [] if correct else [f"{reference} {unit}".strip()],
        "score_note": "Objective numeric tolerance with an explicit unit contract; no LLM judge is used.",
    }


def eval_question(item: dict[str, Any]) -> str:
    if item.get("question") is not None and str(item["question"]).strip():
        return str(item["question"]).strip()
    turns = item.get("turns")
    if not isinstance(turns, list) or not turns:
        raise ValueError(f"{item.get('eval_id', '<unknown>')} must include question or turns")
    rendered = ["Conversation history:"]
    for idx, turn in enumerate(turns, start=1):
        role = str(turn.get("role", "user")).strip().title() or "User"
        content = str(turn.get("content", "")).strip()
        rendered.append(f"{idx}. {role}: {content}")
    rendered.append("Answer the user's latest agronomy question using the full conversation context.")
    return "\n".join(rendered)


def build_eval_field_context(item: dict[str, Any]) -> dict[str, Any]:
    """Preserve executable benchmark context while filling legacy text fields."""

    configured = item.get("field_context")
    context = dict(configured) if isinstance(configured, dict) else {}
    context.setdefault("crop_current", context.get("crop") or item.get("crop"))
    context.setdefault(
        "province_state",
        context.get("province") or context.get("jurisdiction") or item.get("jurisdiction"),
    )
    context.setdefault("region_text", context.get("region") or item.get("region"))
    return {key: value for key, value in context.items() if value is not None}


def validate_eval_item(item: dict[str, Any], source: str) -> None:
    eval_id = item.get("eval_id")
    if not isinstance(eval_id, str) or not eval_id:
        raise ValueError(f"{source}: eval row missing eval_id")
    if not isinstance(item.get("task_family"), str) or not item.get("task_family"):
        raise ValueError(f"{source}:{eval_id}: missing task_family")
    if "question" not in item and "turns" not in item:
        raise ValueError(f"{source}:{eval_id}: missing question or turns")
    if "turns" in item:
        turns = item["turns"]
        if not isinstance(turns, list) or len(turns) < 2:
            raise ValueError(f"{source}:{eval_id}: turns must contain at least two turns")
        for idx, turn in enumerate(turns, start=1):
            if not isinstance(turn, dict) or not str(turn.get("content", "")).strip():
                raise ValueError(f"{source}:{eval_id}: turn {idx} missing content")
    for key in ("required_patterns", "forbidden_patterns"):
        if key not in item or not isinstance(item[key], list):
            raise ValueError(f"{source}:{eval_id}: missing {key}")
    if "ask_for_patterns" in item and not isinstance(item["ask_for_patterns"], list):
        raise ValueError(f"{source}:{eval_id}: ask_for_patterns must be a list")
    if "hardness_bucket" in item and item["hardness_bucket"] not in {"easy", "medium", "hard", "expert"}:
        raise ValueError(f"{source}:{eval_id}: invalid hardness_bucket")
    if item.get("scoring_method") == "numeric_tolerance":
        if not isinstance(item.get("reference_numeric"), (int, float)):
            raise ValueError(f"{source}:{eval_id}: numeric_tolerance requires reference_numeric")
        if not isinstance(item.get("absolute_tolerance"), (int, float)) or item["absolute_tolerance"] < 0:
            raise ValueError(f"{source}:{eval_id}: numeric_tolerance requires non-negative absolute_tolerance")
        if not str(item.get("reference_unit") or "").strip():
            raise ValueError(f"{source}:{eval_id}: numeric_tolerance requires reference_unit")
    if item.get("scoring_method") == "reference_answer_token_f1":
        if not str(item.get("reference_answer") or "").strip():
            raise ValueError(f"{source}:{eval_id}: reference_answer_token_f1 requires reference_answer")


def aggregate(rows: list[dict[str, Any]], mode: str, model_id: str) -> dict[str, Any]:
    scores = [
        float(row["score"]["score"])
        for row in rows
        if row.get("score", {}).get("score") is not None
        and row.get("score", {}).get("proxy_valid", True)
    ]
    metric_names = ("accuracy", "relevance", "completeness", "conciseness")
    metric_means = {
        name: round(sum(row["score"][name] for row in rows if name in row["score"]) / max(1, sum(1 for row in rows if name in row["score"])), 2)
        for name in metric_names
        if any(name in row["score"] for row in rows)
    }
    metadata_keys = sorted({key for row in rows for key in row.get("eval_metadata", {})})
    rubrics = {str(row.get("score", {}).get("rubric") or "") for row in rows}
    multiple_choice = bool(rows) and rubrics == {"multiple_choice"}
    numeric = bool(rows) and rubrics == {"numeric_tolerance"}
    mixed_capability = "numeric_tolerance" in rubrics and len(rubrics) > 1
    reference_answer = bool(rows) and rubrics == {"reference_answer_token_f1"}
    mixed_external = "reference_answer_token_f1" in rubrics and len(rubrics) > 1
    if mixed_capability or mixed_external:
        metric_means = {}
    return {
        "created_at": now(),
        "mode": mode,
        "model_id": model_id,
        "samples": len(rows),
        "mean_score": None if mixed_capability or mixed_external else round(sum(scores) / len(scores), 2) if scores else None,
        "scored_samples": len(scores),
        "unscored_samples": len(rows) - len(scores),
        "promotion_eligible": False,
        "metric_role": (
            "objective_multiple_choice_accuracy"
            if multiple_choice
            else "objective_agronomic_calculation_accuracy"
            if numeric
            else "lane_separated_mixed_capability"
            if mixed_capability
            else "deterministic_reference_overlap_diagnostic"
            if reference_answer
            else "lane_separated_external_knowledge_proxy"
            if mixed_external
            else "deterministic_regression_diagnostic_only"
        ),
        "metric_means": metric_means,
        "by_family": group_summary(rows, lambda row: row["task_family"]),
        "by_benchmark_lane": group_summary(
            rows,
            lambda row: str(row.get("eval_metadata", {}).get("benchmark_lane", "unspecified")),
        ),
        "by_hardness": group_summary(rows, lambda row: hardness_bucket(row)),
        "by_difficulty": group_summary(rows, lambda row: str(row.get("eval_metadata", {}).get("difficulty", "unspecified"))),
        "by_turn_type": group_summary(rows, lambda row: "multi_turn" if row.get("eval_metadata", {}).get("is_multi_turn") else "single_turn"),
        "by_expected_tool_count": group_summary(rows, lambda row: str(len(row.get("eval_metadata", {}).get("expected_tools", [])))),
        "metadata_keys": metadata_keys,
        "score_warning": (
            "Objective accuracy on a public crop-science multiple-choice set. It does not establish Canadian field-advisory safety or usefulness."
            if multiple_choice
            else "Objective agronomic calculation accuracy with explicit units and numeric tolerances; it does not establish advisory quality."
            if numeric
            else "Mixed benchmark: objective calculations, semantic answer review, retrieval, and lineage must be reported by lane; the aggregate mean is not a valid capability score."
            if mixed_capability
            else "Normalized token overlap with published external answers. It can measure answer resemblance, not semantic correctness, Canadian applicability, or certification readiness."
            if reference_answer
            else "Mixed public knowledge proxy: objective quiz accuracy and reference-answer overlap are reported separately by lane; no aggregate score is valid."
            if mixed_external
            else "Deterministic lexical-contract regression diagnostic only. Rows without an explicit lexical contract are unscored; "
            "this summary is not an answer-quality, agronomist, field-validity, or public capability benchmark."
        ),
    }


@contextmanager
def answer_profile_environment(answer_profile: str) -> Any:
    previous = {name: os.environ.get(name) for name in ANSWER_PROFILE_ENV_VARS}
    try:
        if answer_profile == "benchmark":
            os.environ["AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION"] = "1"
            os.environ["AGRONOMY_AGENT_SYSTEM_PROMPT"] = BENCHMARK_SYSTEM_PROMPT
            os.environ["AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT"] = BENCHMARK_ANSWER_OUTPUT_CONTRACT
        elif answer_profile == "multiple_choice":
            os.environ["AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION"] = "1"
            os.environ["AGRONOMY_AGENT_SYSTEM_PROMPT"] = MULTIPLE_CHOICE_SYSTEM_PROMPT
            os.environ["AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT"] = MULTIPLE_CHOICE_ANSWER_OUTPUT_CONTRACT
            os.environ["AGRONOMY_AGENT_OBJECTIVE_RESPONSE_MODE"] = "multiple_choice"
        elif answer_profile in {"public", "production"}:
            for name in ANSWER_PROFILE_ENV_VARS:
                os.environ.pop(name, None)
        elif answer_profile != "environment":
            raise ValueError(f"unknown answer profile: {answer_profile}")
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def hardness_bucket(row: dict[str, Any]) -> str:
    metadata = row.get("eval_metadata", {})
    explicit = metadata.get("hardness_bucket")
    if explicit:
        return str(explicit)
    difficulty = metadata.get("difficulty")
    if difficulty == "expert":
        return "expert"
    if difficulty == "medium":
        return "medium"
    if difficulty == "easy":
        return "easy"
    return "unspecified"


def group_summary(rows: list[dict[str, Any]], key_fn: Any) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(key_fn(row)), []).append(row)
    summaries: dict[str, dict[str, Any]] = {}
    for key, items in sorted(grouped.items()):
        valid_scores = [
            float(item["score"]["score"])
            for item in items
            if item.get("score", {}).get("score") is not None
            and item.get("score", {}).get("proxy_valid", True)
        ]
        summaries[key] = {
            "samples": len(items),
            "scored_samples": len(valid_scores),
            "mean_score": round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else None,
            "min_score": round(min(valid_scores), 2) if valid_scores else None,
            "max_score": round(max(valid_scores), 2) if valid_scores else None,
            "flagged_missing_required": sum(1 for item in items if item["score"].get("missing_required_patterns")),
            "common_missing_required": Counter(
                pattern for item in items for pattern in item["score"].get("missing_required_patterns", [])
            ).most_common(8),
        }
    return summaries


PUBLIC_ADAPTER_SPEC_BY_ID = {str(spec["id"]): spec for spec in PUBLIC_ADAPTER_SPECS}


def enrich_eval_metadata_with_expected_source_trace(metadata: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Attach an honest source-tool trace for text-only benchmark rehearsal rows.

    The local eval runner does not execute live public adapters because most rows
    are text-only and do not include executable geometry, date, or product payloads.
    We still need the output artifact to record that a public source check was
    expected and not executed, rather than silently dropping the trace.
    """

    enriched = dict(metadata or {})
    question = eval_question(item)
    route = refine_query_route(question, classify_query(question))
    refreshed_tool_notes = run_tools(question, route.required_tools)
    if enriched.get("tool_trace_refresh"):
        # Older eval postprocessing merged broad route expectations into the
        # generation trace. Reconstruct the current generation route on rescore.
        enriched["tool_notes"] = [note.name for note in refreshed_tool_notes]
        enriched["generation_tool_notes_reconstructed"] = True
    enriched["route_tool_notes"] = [note.name for note in refreshed_tool_notes]
    if refreshed_tool_notes:
        enriched["route_tool_note_records"] = [
            {
                "name": note.name,
                "skill_id": note.skill_id,
                "boundary": note.boundary,
                "risk_class": note.risk_class,
                "provenance": list(note.provenance),
                "eval_tags": list(note.eval_tags),
            }
            for note in refreshed_tool_notes
        ]
    enriched["route"] = asdict(route)
    enriched["tool_trace_refresh"] = {
        "source": "current_router_and_local_guard_registry",
        "required_tools": list(route.required_tools),
        "note": "Current refined-route expectations only. The tool_notes field records the generation path and must not be expanded by this refresh.",
    }

    expected_adapters = [str(adapter) for adapter in item.get("expected_public_adapters") or [] if str(adapter).strip()]
    if expected_adapters:
        enriched["expected_public_adapters"] = expected_adapters

    expected_tools = [str(tool) for tool in item.get("expected_tools") or [] if str(tool).strip()]
    if expected_tools:
        enriched["expected_tools"] = expected_tools
        seen_tools = set(enriched.get("route_tool_notes") or [])
        missing_tools = [tool for tool in expected_tools if tool not in seen_tools]
        if missing_tools:
            enriched["missing_expected_tools"] = missing_tools
        else:
            enriched.pop("missing_expected_tools", None)

    if not expected_adapters:
        return enriched

    seen_adapters = _metadata_public_adapter_names(enriched)
    planned_records = [
        _expected_public_adapter_eval_record(adapter, item)
        for adapter in expected_adapters
        if adapter not in seen_adapters
    ]
    if not planned_records:
        return enriched

    enriched["public_adapter_results"] = [
        *[record for record in enriched.get("public_adapter_results") or [] if isinstance(record, dict)],
        *planned_records,
    ]
    enriched["tool_invocations"] = [
        *[record for record in enriched.get("tool_invocations") or [] if isinstance(record, dict)],
        *planned_records,
    ]
    enriched["source_trace_boundary"] = (
        "Expected public-adapter traces in this eval artifact mark required source checks. "
        "Records with status not_run_in_eval are not provider results and must not be treated as checked field evidence."
    )
    return enriched


def _metadata_tool_note_names(records: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(records, list):
        return names
    for record in records:
        if isinstance(record, dict):
            name = str(record.get("name") or "").strip()
        else:
            name = str(record).strip()
        if name:
            names.append(name)
    return names


def _metadata_public_adapter_names(metadata: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("tool_invocations", "public_adapter_results", "public_adapters", "adapter_results"):
        records = metadata.get(key)
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            if payload.get("kind") == "public_adapter" or key != "tool_invocations":
                name = str(record.get("name") or record.get("adapter") or record.get("id") or "").strip()
                if name:
                    names.add(name)
    return names


def _expected_public_adapter_eval_record(adapter_id: str, item: dict[str, Any]) -> dict[str, Any]:
    spec = PUBLIC_ADAPTER_SPEC_BY_ID.get(adapter_id, {})
    label = str(spec.get("label") or adapter_id.replace("_", " "))
    provider = str(spec.get("provider") or "public source")
    reason = _expected_public_adapter_not_run_reason(adapter_id, item, spec)
    boundary = str(spec.get("boundary") or "Public source context is not field truth.")
    return {
        "name": adapter_id,
        "text": f"{label} was expected by the eval suite but not executed in this text-only eval run: {reason}.",
        "payload": {
            "kind": "public_adapter",
            "status": "not_run_in_eval",
            "source": spec.get("source"),
            "boundary": (
                f"{boundary} This eval trace records a required public-source check; "
                "it is not evidence that the provider returned data."
            ),
            "summary": {
                "adapter_id": adapter_id,
                "adapter_label": label,
                "provider": provider,
                "expected_by_suite": True,
                "eval_id": item.get("eval_id"),
                "public_source_lane": item.get("public_source_lane"),
                "scenario_type": item.get("scenario_type"),
                "field_context_required": bool(spec.get("field_context_required")),
                "not_run_reason": reason,
                "eval_harness": "text_only",
            },
        },
    }


def _expected_public_adapter_not_run_reason(adapter_id: str, item: dict[str, Any], spec: dict[str, Any]) -> str:
    if bool(spec.get("field_context_required")):
        return "the row did not provide an executable field point or boundary payload to the adapter"
    if adapter_id == "epa_ppls_product_search":
        return "the row did not pass a disambiguated product identifier into the PPLS adapter"
    if adapter_id in {"openet_point_timeseries", "nass_quickstats_crop_stats"}:
        return "the text-only eval harness does not use keyed live adapters"
    return "the text-only eval harness records expected source coverage without making live provider calls"


def tool_trace_audit(item: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Separate routing evidence from actual public-adapter execution.

    Answer vocabulary is intentionally excluded: saying "check the weather" is
    not evidence that a weather provider ran or returned usable data.
    """

    expected = set(item.get("expected_tools") or item.get("eval_metadata", {}).get("expected_tools") or [])
    routed = set(_metadata_tool_note_names(metadata.get("tool_notes") or []))
    expected_adapters = set(item.get("expected_public_adapters") or [])
    adapter_records: list[dict[str, Any]] = []
    for key in ("public_adapter_results", "tool_invocations", "public_adapters", "adapter_results"):
        records = metadata.get(key)
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            name = str(record.get("name") or record.get("adapter") or record.get("id") or "").strip()
            if not name or (key == "tool_invocations" and payload.get("kind") != "public_adapter"):
                continue
            status = str(payload.get("status") or record.get("status") or "unknown").strip().lower()
            adapter_records.append({"name": name, "status": status, "source_key": key})
    # Deduplicate records repeated across the service trace surfaces.
    unique_records = {(record["name"], record["status"]): record for record in adapter_records}
    executed_statuses = {"ok", "success", "succeeded", "completed"}
    executed = {name for name, status in unique_records if status in executed_statuses}
    planned_not_run = {
        name
        for name, status in unique_records
        if status in {"not_run_in_eval", "planned", "expected", "skipped", "not_run"}
    }
    return {
        "expected_local_guards": sorted(expected),
        "routed_local_guards": sorted(routed),
        "missing_local_guards": sorted(expected - routed),
        "local_guard_routing_recall": len(expected & routed) / len(expected) if expected else 1.0,
        "expected_public_adapters": sorted(expected_adapters),
        "executed_public_adapters": sorted(executed),
        "planned_not_run_public_adapters": sorted(planned_not_run),
        "missing_public_adapters": sorted(expected_adapters - executed - planned_not_run),
        "public_adapter_execution_recall": (
            len(expected_adapters & executed) / len(expected_adapters) if expected_adapters else None
        ),
        "answer_text_used_as_execution_evidence": False,
    }


def _tool_recall(item: dict[str, Any], metadata: dict[str, Any], output: str) -> float:
    del output
    return float(tool_trace_audit(item, metadata)["local_guard_routing_recall"])


def _relevance_score(output: str, item: dict[str, Any], forbidden_rate: float) -> float:
    text = output.lower()
    score = 100.0 - 30.0 * forbidden_rate
    crop = str(item.get("crop", "")).lower()
    if crop and crop not in {"na", "all"} and crop not in text:
        score -= 6.0
    family_terms = {
        "nutrient": ("fertil", "nutrient", "soil test", "nitrogen", "phosphorus", "potassium", "lime"),
        "soil": ("soil", "water", "drainage", "compaction", "salinity", "erosion"),
        "product": ("label", "product", "spray", "wind", "target pest", "rate"),
        "plant": ("scout", "disease", "pest", "weed", "threshold", "symptom"),
        "precision": ("yield map", "zone", "prescription", "calibration", "field data"),
    }
    family = str(item.get("task_family", "")).lower()
    matched_family = False
    for hint, terms in family_terms.items():
        if hint in family:
            matched_family = any(term in text for term in terms)
            break
    if family and not matched_family and any(hint in family for hint in family_terms):
        score -= 10.0
    if re.search(r"\b(as an ai|i cannot answer|consult an expert only|not enough information to answer anything)\b", text):
        score -= 15.0
    return _clamp(score)


def _conciseness_score(output: str) -> float:
    words = re.findall(r"\b\w+\b", output)
    count = len(words)
    if count < 35:
        score = 55.0 + count
    elif count <= 260:
        score = 100.0
    elif count <= 420:
        score = 100.0 - (count - 260) * 0.25
    else:
        score = 60.0 - min(35.0, (count - 420) * 0.08)
    repeated = _repeated_ngram_count(words, n=5)
    if repeated:
        score -= min(30.0, repeated * 6.0)
    return _clamp(score)


def _repeated_ngram_count(words: list[str], n: int = 5) -> int:
    if len(words) < n * 2:
        return 0
    grams = Counter(tuple(word.lower() for word in words[idx : idx + n]) for idx in range(len(words) - n + 1))
    return sum(1 for count in grams.values() if count > 1)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def build_eval_generators(args: argparse.Namespace, model_cfg: dict[str, Any]) -> tuple[Any, Any, str, str, str | None]:
    """Build one local or host-native generation contract for an eval run."""

    model_id = args.model or str(model_cfg.get("model_id"))
    verification_cfg = model_cfg.get("answer_verification") or {}
    request_model_id = str(getattr(args, "request_model_id", "default_model") or "default_model")
    model_base_url = str(getattr(args, "model_base_url", "") or "").strip()
    codex_app_server = bool(getattr(args, "codex_app_server", False))
    if args.mock:
        return MockGenerator(), None, model_id, "mock", None

    if codex_app_server and model_base_url:
        raise ValueError("--codex-app-server and --model-base-url are mutually exclusive")

    max_tokens = int(args.max_tokens or model_cfg.get("max_tokens", 360))
    temperature = float(model_cfg.get("temperature", 0.0))
    top_p = float(model_cfg.get("top_p", 0.9))
    top_k = int(model_cfg.get("top_k", 0))
    verifier_enabled = bool(verification_cfg.get("enabled", False)) and args.mode == "agronomic_rag"
    verifier_model_id = str(verification_cfg.get("model_id") or model_id)
    verifier_model_revision = str(verification_cfg.get("model_revision") or model_cfg.get("model_revision") or "") or None
    if codex_app_server:
        reasoning_effort = str(getattr(args, "reasoning_effort", "high") or "high")
        timeout_seconds = float(getattr(args, "model_timeout_seconds", 360.0))
        generator = CodexAppServerGenerator(
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            timeout_seconds=timeout_seconds,
        )
        verifier = (
            CodexAppServerGenerator(
                model_id=verifier_model_id,
                reasoning_effort=reasoning_effort,
                timeout_seconds=timeout_seconds,
            )
            if verifier_enabled
            else None
        )
        return generator, verifier, model_id, "codex_app_server_chatgpt_auth", model_id
    if model_base_url:
        common = {
            "base_url": model_base_url,
            "request_model_id": request_model_id,
            "api_key": os.getenv("AGRONOMY_AGENT_MODEL_API_KEY") or None,
            "timeout_seconds": float(getattr(args, "model_timeout_seconds", 360.0)),
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "model_revision": str(model_cfg.get("model_revision") or "") or None,
            "model_config_path": args.model_config,
            "identity_receipt_path": getattr(args, "model_identity_receipt", None),
            "identity_required": bool(getattr(args, "require_model_identity", False)),
        }
        generator = OpenAICompatibleGenerator(model_id=model_id, max_tokens=max_tokens, **common)
        verifier = (
            OpenAICompatibleGenerator(
                model_id=verifier_model_id,
                max_tokens=int(verification_cfg.get("max_tokens", 180)),
                **{**common, "model_revision": verifier_model_revision},
            )
            if verifier_enabled
            else None
        )
        return generator, verifier, model_id, "openai_compatible_http", request_model_id

    generator = MLXGenerator(
        model_id=model_id,
        model_revision=str(model_cfg.get("model_revision") or "") or None,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
    )
    verifier = (
        MLXGenerator(
            model_id=verifier_model_id,
            model_revision=verifier_model_revision,
            max_tokens=int(verification_cfg.get("max_tokens", 180)),
            temperature=0.0,
            top_p=top_p,
            top_k=top_k,
        )
        if verifier_enabled
        else None
    )
    return generator, verifier, model_id, "mlx_local", None


def run_eval(args: argparse.Namespace) -> int:
    model_cfg = load_model_config(args.model_config)
    verification_cfg = model_cfg.get("answer_verification") or {}
    generator, verifier, model_id, model_backend, request_model_id = build_eval_generators(args, model_cfg)
    suite_path = repo_path(args.suite)
    model_config_path = repo_path(args.model_config)
    rag_config_path = repo_path(args.rag_config) if args.mode == "agronomic_rag" else None
    resources = load_agent_resources(args.rag_config) if args.mode == "agronomic_rag" else None
    rag_artifacts = build_rag_artifact_identity(resources) if resources is not None else []
    command_sha256 = hashlib.sha256(
        json.dumps(sys.argv, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    run_identity = {
        "schema_version": "open_agronomy_agent.eval_run_identity.v2",
        "model_id": model_id if not args.mock else "mock",
        "model_revision": str(model_cfg.get("model_revision") or "") or None,
        "model_backend": model_backend,
        "request_model_id": request_model_id,
        "suite": args.suite,
        "suite_sha256": sha256_path(suite_path),
        "model_config": args.model_config,
        "model_config_sha256": sha256_path(model_config_path),
        "rag_config": args.rag_config if args.mode == "agronomic_rag" else None,
        "rag_config_sha256": sha256_path(rag_config_path) if rag_config_path is not None else None,
        "rag_artifacts": rag_artifacts,
        "corpus_bundle_version": resources.corpus_bundle_version if resources is not None else None,
        "runner": str(Path(__file__).resolve()),
        "runner_sha256": sha256_path(Path(__file__).resolve()),
        "implementation": build_implementation_identity(),
        "command_sha256": command_sha256,
        "context_packet_capture": bool(getattr(args, "capture_context_packets", False)),
        "prompt_profile": str(model_cfg.get("prompt_profile") or "default"),
        "answer_verification": {
            "configured_enabled": bool(verification_cfg.get("enabled", False)),
            "effective_enabled": bool(
                verification_cfg.get("enabled", False)
                and args.mode == "agronomic_rag"
            ),
            "mode": str(verification_cfg.get("mode") or "risk_gated"),
            "model_id": str(verification_cfg.get("model_id") or model_id),
            "model_revision": str(
                verification_cfg.get("model_revision")
                or model_cfg.get("model_revision")
                or ""
            )
            or None,
        },
    }
    run_identity_sha256 = hashlib.sha256(
        json.dumps(run_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    suite = load_jsonl(repo_path(args.suite), args.max_samples)
    eval_ids_raw = str(getattr(args, "eval_ids", "") or "").strip()
    if eval_ids_raw:
        requested_ids = {value.strip() for value in eval_ids_raw.split(",") if value.strip()}
        available_ids = {str(item.get("eval_id") or "") for item in suite}
        missing_ids = sorted(requested_ids - available_ids)
        if missing_ids:
            raise ValueError(f"requested eval IDs are not in the selected suite: {missing_ids}")
        suite = [item for item in suite if str(item.get("eval_id") or "") in requested_ids]
    resume_run_dir = getattr(args, "resume_run_dir", None)
    if resume_run_dir:
        out_dir = repo_path(resume_run_dir)
        if not out_dir.is_dir():
            raise ValueError(f"resume run directory does not exist: {out_dir}")
    else:
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = repo_path(args.output_dir) / f"{args.mode}_{run_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
    partial_path = out_dir / "outputs.partial.jsonl"
    identity_path = out_dir / "resumable_run_identity.json"
    if resume_run_dir:
        if not partial_path.is_file():
            raise ValueError(f"resume run is missing partial outputs: {partial_path}")
        validate_resume_identity(identity_path, run_identity)
        outputs = load_partial_outputs(partial_path)
        validate_resume_prefix(
            outputs,
            suite,
            mode=args.mode,
            model_id=model_id if not args.mock else "mock",
            answer_profile=args.answer_profile,
            rag_config=args.rag_config if args.mode == "agronomic_rag" else None,
            model_backend=model_backend,
            request_model_id=request_model_id,
        )
        print(json.dumps({"resumed_rows": len(outputs), "remaining_rows": len(suite) - len(outputs), "run_dir": str(out_dir)}))
    else:
        identity_path.write_text(
            json.dumps(resumable_run_identity(run_identity), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        partial_path.write_text("", encoding="utf-8")
        outputs = []
    with answer_profile_environment(args.answer_profile):
        for idx, item in enumerate(suite[len(outputs) :], start=len(outputs) + 1):
            started = time.time()
            field_context = None
            if bool(getattr(args, "use_eval_field_context", False)):
                field_context = build_eval_field_context(item)
            output, metadata = generate_answer(
                eval_question(item),
                args.mode,
                generator,
                resources=resources,
                verifier=verifier,
                field_context=field_context,
                verification_enabled=bool(verification_cfg.get("enabled", False)),
                verification_mode=str(verification_cfg.get("mode") or "risk_gated"),
                capture_context_packet=bool(getattr(args, "capture_context_packets", False)),
                prompt_profile=str(model_cfg.get("prompt_profile") or "default"),
                intervention_profile=str(model_cfg.get("intervention_profile") or "") or None,
            )
            metadata = enrich_eval_metadata_with_expected_source_trace(metadata, item)
            metadata["tool_execution_audit"] = tool_trace_audit(item, metadata)
            if args.rubric == "mixed_capability" and item.get("scoring_method") == "numeric_tolerance":
                score = score_item_numeric(output, item)
            elif args.rubric == "mixed_external" and item.get("scoring_method") == "multiple_choice":
                score = score_item_multiple_choice(output, item)
            elif args.rubric in {"reference_answer", "mixed_external"}:
                score = score_item_reference_answer(output, item)
            elif args.rubric in {"agribench_proxy", "mixed_capability"}:
                score = score_item_agribench_proxy(output, item, metadata)
            elif args.rubric == "multiple_choice":
                score = score_item_multiple_choice(output, item)
            else:
                score = score_item(output, item)
            row = {
                "eval_id": item["eval_id"],
                "task_family": item.get("task_family", "unknown"),
                "question": eval_question(item),
                "semantic_reference": {
                    "reference_answer": item.get("reference_answer") or item.get("expected_answer"),
                    "expert_reference_points": list(item.get("expert_reference_points") or []),
                    "material_errors": list(item.get("material_errors") or []),
                    "critical_evidence": list(item.get("critical_evidence") or []),
                    "safe_boundary": item.get("safe_boundary"),
                    "acceptable_answer_variants": list(item.get("acceptable_answer_variants") or []),
                },
                "eval_metadata": {
                    key: item[key]
                    for key in (
                        "difficulty",
                        "hardness_bucket",
                        "hardness_score",
                        "region",
                        "crop",
                        "jurisdiction",
                        "scenario_type",
                        "expected_tools",
                        "source_basis",
                        "reasoning_mode",
                        "is_multi_turn",
                        "coverage_domain",
                        "public_source_lane",
                        "category",
                        "partition",
                        "question_style",
                        "geometry_mode",
                        "evidence_condition",
                        "benchmark_lane",
                        "metric_role",
                        "primary_benchmark_lane",
                        "question_origin",
                        "support_mode",
                        "language",
                        "evaluation_partition",
                        "public_dataset_id",
                        "public_dataset_revision",
                        "public_source_row_index",
                        "correct_option_roman",
                        "correct_option_word_length_rank",
                        "original_difficulty_level",
                        "source_url",
                        "source_license",
                        "source_revision",
                        "cca_domain_alignment",
                        "reference_answer_status",
                    )
                    if key in item
                },
                "mode": args.mode,
                "answer_profile": args.answer_profile,
                "eval_field_context_used": bool(getattr(args, "use_eval_field_context", False)),
                "eval_field_context": field_context,
                "model_id": model_id if not args.mock else "mock",
                "model_backend": model_backend,
                "request_model_id": request_model_id,
                "model_identity": dict(getattr(generator, "model_identity", {}) or {}),
                "run_identity_sha256": run_identity_sha256,
                "model_config": args.model_config,
                "rag_config": args.rag_config if args.mode == "agronomic_rag" else None,
                "elapsed_seconds": round(time.time() - started, 3),
                "output": output,
                "score": score,
                "metadata": metadata,
            }
            outputs.append(row)
            with partial_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(json.dumps({"sample": idx, "eval_id": row["eval_id"], "score": score["score"], "seconds": row["elapsed_seconds"]}))
    outputs_path = out_dir / "outputs.jsonl"
    with outputs_path.open("w", encoding="utf-8") as handle:
        for row in outputs:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = aggregate(outputs, args.mode, model_id if not args.mock else "mock")
    summary["answer_profile"] = args.answer_profile
    summary["suite"] = args.suite
    summary["model_config"] = args.model_config
    summary["model_backend"] = model_backend
    summary["request_model_id"] = request_model_id
    summary["rag_config"] = args.rag_config if args.mode == "agronomic_rag" else None
    summary["rubric"] = args.rubric
    summary["max_tokens"] = int(args.max_tokens or model_cfg.get("max_tokens", 360))
    summary["eval_field_context_used"] = bool(getattr(args, "use_eval_field_context", False))
    summary["context_packet_capture"] = bool(getattr(args, "capture_context_packets", False))
    summary["run_identity"] = run_identity
    summary["run_identity_sha256"] = run_identity_sha256
    summary["model_identity"] = dict(getattr(generator, "model_identity", {}) or {})
    summary["outputs_sha256"] = sha256_path(outputs_path)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    run_manifest = {
        **run_identity,
        "run_identity_sha256": run_identity_sha256,
        "model_identity": summary["model_identity"],
        "outputs": str(outputs_path),
        "outputs_sha256": summary["outputs_sha256"],
        "summary": str(out_dir / "summary.json"),
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(run_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MVP agronomy evals.")
    parser.add_argument(
        "--mode",
        choices=["raw_model", "baseline", "kernel_field_context", "agronomic_rag"],
        required=True,
        help=(
            "raw_model sends only the user question and preserves raw output; baseline applies the "
            "Open Agronomy kernel without retrieval; kernel_field_context adds only the shared structured "
            "field context; agronomic_rag runs the full text-agent path."
        ),
    )
    parser.add_argument("--suite", default="data/eval/agronomy_mvp_eval.jsonl")
    parser.add_argument("--output-dir", default="outputs/evals")
    parser.add_argument("--model-config", default="configs/model.yaml")
    parser.add_argument("--rag-config", default=DEFAULT_RAG_CONFIG)
    parser.add_argument("--model")
    parser.add_argument(
        "--model-base-url",
        help="Use an OpenAI-compatible host model endpoint, for example http://127.0.0.1:8081/v1.",
    )
    parser.add_argument(
        "--codex-app-server",
        action="store_true",
        help=(
            "Generate through the local ChatGPT-authenticated Codex App Server. "
            "Turns are ephemeral, read-only, network-disabled, and fail closed on model rerouting."
        ),
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=["none", "low", "medium", "high", "xhigh", "max"],
        default="high",
        help="Reasoning effort for the Codex App Server model backend.",
    )
    parser.add_argument(
        "--request-model-id",
        default="default_model",
        help="Model name sent to an OpenAI-compatible host endpoint.",
    )
    parser.add_argument("--model-timeout-seconds", type=float, default=360.0)
    parser.add_argument(
        "--model-identity-receipt",
        help="Model-host identity receipt produced by the native launcher.",
    )
    parser.add_argument(
        "--require-model-identity",
        action="store_true",
        help="Fail closed before HTTP generation unless the model-host receipt verifies.",
    )
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--eval-ids", help="Comma-separated eval IDs to run from the selected suite.")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument(
        "--use-eval-field-context",
        action="store_true",
        help="Pass suite crop, jurisdiction, and region metadata as map-style field context.",
    )
    parser.add_argument(
        "--capture-context-packets",
        action="store_true",
        help=(
            "Persist exact model messages and full retrieved context in local eval outputs. "
            "These artifacts may contain machine-local private source text and must not be redistributed."
        ),
    )
    parser.add_argument(
        "--rubric",
        choices=["pattern", "agribench_proxy", "multiple_choice", "reference_answer", "mixed_capability", "mixed_external"],
        default="pattern",
    )
    parser.add_argument(
        "--answer-profile",
        choices=["public", "production", "benchmark", "multiple_choice", "environment"],
        default="public",
        help="Use the public compact answer contract, the official-style benchmark contract, or the current process environment.",
    )
    parser.add_argument(
        "--resume-run-dir",
        help="Continue a run from its validated outputs.partial.jsonl prefix instead of creating a new run directory.",
    )
    parser.add_argument("--mock", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run_eval(args)


if __name__ == "__main__":
    raise SystemExit(main())
