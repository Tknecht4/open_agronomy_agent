"""Offline, source-bound diagnostics for retained answer-stage traces.

This module observes stored text transitions. It neither reruns a model nor
attributes quality or causal benefit to any intervention.
"""

from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Mapping

from agronomy_agent.answer_verifier import assess_claim_risk

SCHEMA = "open_agronomy_agent.harness_intervention_replay.v1"
STAGE_SCHEMA = "open_agronomy_agent.answer_stages.v1"
MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_ROWS = 2000
MAX_STAGE_CHARS = 50_000
STAGES = ("draft", "post_verification", "final")


def python_source_tree_identity(root: Path | None = None) -> dict[str, Any]:
    """Hash every package Python file by relative name and exact bytes."""

    package_root = root or Path(__file__).resolve().parent
    paths = sorted(package_root.rglob("*.py"), key=lambda path: path.relative_to(package_root).as_posix())
    if not paths:
        raise ValueError("Python package source tree is unavailable")
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(package_root).as_posix()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return {
        "algorithm": "sha256(relative_utf8_nul_file_sha256_bytes_newline)",
        "sha256": digest.hexdigest(),
        "python_file_count": len(paths),
    }


def _installed_package_version() -> str | None:
    try:
        return version("agronomy-agent")
    except PackageNotFoundError:
        return None


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _prompt_identity(
    generation_input: Mapping[str, Any], trace: Mapping[str, Any], *, row_number: int,
) -> dict[str, Any]:
    """Hash only a retained, structurally valid, nonempty prompt message list."""

    candidates = []
    if "messages" in generation_input:
        candidates.append(generation_input["messages"])
    if "prompt_messages" in trace:
        candidates.append(trace["prompt_messages"])
    retained: list[list[Mapping[str, Any]]] = []
    for messages in candidates:
        if messages is None or messages == []:
            continue
        if not isinstance(messages, list) or not all(
            isinstance(item, Mapping)
            and isinstance(item.get("role"), str) and bool(item["role"].strip())
            and isinstance(item.get("content"), str)
            for item in messages
        ):
            raise ValueError(f"row {row_number}: malformed retained prompt_messages")
        retained.append(messages)
    if not retained:
        return {
            "status": "unavailable",
            "reason": "prompt_messages_empty" if candidates else "prompt_messages_missing",
            "sha256": None,
        }
    canonical = [
        json.dumps(messages, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        for messages in retained
    ]
    if len(set(canonical)) != 1:
        raise ValueError(f"row {row_number}: retained prompt_messages disagree")
    return {"status": "observed", "reason": None, "sha256": _sha(canonical[0])}


def _stage_record(stages: Mapping[str, Any], name: str) -> tuple[dict[str, Any], str | None]:
    raw = stages.get(name)
    if raw is None:
        return {"status": "unavailable", "reason": "stage_missing"}, None
    if not isinstance(raw, Mapping) or not isinstance(raw.get("text"), str):
        raise ValueError(f"answer stage {name} is malformed")
    text = raw["text"]
    if len(text) > MAX_STAGE_CHARS:
        raise ValueError(f"answer stage {name} exceeds the 50000-character diagnostic limit")
    digest = _sha(text)
    if raw.get("sha256") != digest:
        raise ValueError(f"answer stage {name} hash mismatch")
    return {"status": "observed", "sha256": digest, "characters": len(text)}, text


def _delta(before: str | None, after: str | None) -> dict[str, Any]:
    if before is None or after is None:
        return {"status": "unavailable", "reason": "stage_missing"}
    if before == after:
        return {
            "status": "observed", "changed": False, "inserted": 0, "deleted": 0,
            "replaced_before": 0, "replaced_after": 0,
        }
    inserted = deleted = replaced_before = replaced_after = 0
    for operation, left_start, left_end, right_start, right_end in SequenceMatcher(
        None, before, after, autojunk=False,
    ).get_opcodes():
        if operation == "insert":
            inserted += right_end - right_start
        elif operation == "delete":
            deleted += left_end - left_start
        elif operation == "replace":
            replaced_before += left_end - left_start
            replaced_after += right_end - right_start
    return {
        "status": "observed", "changed": True,
        "inserted": inserted, "deleted": deleted,
        "replaced_before": replaced_before, "replaced_after": replaced_after,
    }


def _shadow_risk(
    question: Any, metadata: Mapping[str, Any], route: Mapping[str, Any],
    texts: Mapping[str, str | None],
) -> dict[str, Any]:
    verification = _mapping(metadata.get("answer_verification"))
    evidence = verification.get("evidence")
    if not isinstance(question, str) or not isinstance(evidence, str):
        return {
            "status": "unavailable",
            "reason": "captured_question_or_verifier_evidence_missing",
        }
    question_type = route.get("question_type")
    risk_level = route.get("risk_level")
    if not isinstance(question_type, str) or not isinstance(risk_level, str):
        return {"status": "unavailable", "reason": "captured_route_missing"}
    assessments: dict[str, Any] = {}
    for name in (*STAGES, "editor_candidate"):
        draft = texts[name]
        if draft is None:
            assessments[name] = {"status": "unavailable", "reason": "stage_missing"}
            continue
        result = assess_claim_risk(
            draft, question=question, evidence_text=evidence,
            question_type=question_type, risk_level=risk_level,
        )
        assessments[name] = {
            "status": "shadow_diagnostic", "requires_review": result.requires_review,
            "score": result.score, "reasons": list(result.reasons),
        }
    return {
        "status": "shadow_diagnostic",
        "input_identity": {
            "question_sha256": _sha(question),
            "captured_verifier_evidence_sha256": _sha(evidence),
            "question_type": question_type,
            "risk_level": risk_level,
        },
        "assessments": assessments,
        "limitation": "Stored document objects and verifier settings may be absent; this is not a reproduction of the original verifier decision.",
    }


def replay_trace(row: Mapping[str, Any], *, source_sha256: str, row_number: int) -> dict[str, Any]:
    """Analyze one observed trace row; missing individual stages stay unknown."""

    execution = _mapping(row.get("execution"))
    turn = _mapping(execution.get("turn"))
    trace = _mapping(turn.get("trace"))
    metadata = _mapping(row.get("metadata")) or _mapping(trace.get("metadata"))
    trace_stages = metadata.get("answer_stages")
    execution_stages = execution.get("answer_stages")
    if trace_stages is not None and execution_stages is not None and trace_stages != execution_stages:
        raise ValueError(f"row {row_number}: execution and trace answer_stages disagree")
    stages = trace_stages or execution_stages or row.get("answer_stages")
    if not isinstance(stages, Mapping):
        raise ValueError(f"row {row_number}: observed answer_stages are missing")
    if stages.get("schema_version") != STAGE_SCHEMA:
        raise ValueError(f"row {row_number}: unsupported answer_stages schema")
    stage_records: dict[str, Any] = {}
    texts: dict[str, str | None] = {}
    for name in STAGES:
        stage_records[name], texts[name] = _stage_record(stages, name)
    verification = _mapping(metadata.get("answer_verification"))
    editor = verification.get("editor_output")
    editor_record = (
        {"status": "observed", "sha256": _sha(editor), "characters": len(editor)}
        if isinstance(editor, str)
        else {"status": "unavailable", "reason": "editor_output_missing"}
    )
    texts["editor_candidate"] = editor if isinstance(editor, str) else None
    draft_echo = verification.get("draft_output")
    draft_echo_relation = (
        "matches_stage" if draft_echo == texts["draft"] else "differs_from_stage"
    ) if isinstance(draft_echo, str) and texts["draft"] is not None else "unavailable"
    generation_input = _mapping(metadata.get("benchmark_generation_input"))
    prompt_identity = _prompt_identity(generation_input, trace, row_number=row_number)
    question = row.get("question") or row.get("message") or turn.get("user_message")
    route = _mapping(metadata.get("route")) or _mapping(trace.get("route"))
    return {
        "source": {
            "input_sha256": source_sha256,
            "row_number": row_number,
            "row_canonical_sha256": _sha(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))),
            "run_identity_sha256": row.get("run_identity_sha256"),
            "observation_id": row.get("observation_id"),
            "turn_id": execution.get("turn_id") or turn.get("turn_id"),
            "result_class": row.get("result_class"),
            "model_id": row.get("model_id"),
            "model_backend": row.get("model_backend"),
            "prompt_messages_sha256": prompt_identity["sha256"],
            "prompt_messages_status": prompt_identity["status"],
            "prompt_messages_reason": prompt_identity["reason"],
        },
        "stages": stage_records,
        "editor_candidate": editor_record,
        "verifier_draft_echo": draft_echo_relation,
        "observed_verifier_flags": {
            key: verification.get(key) if type(verification.get(key)) is bool else None
            for key in ("triggered", "rewrite_accepted", "fallback_applied")
        },
        "transitions": {
            "draft_to_post_verification": _delta(texts["draft"], texts["post_verification"]),
            "post_verification_to_final": _delta(texts["post_verification"], texts["final"]),
            "draft_to_editor_candidate": _delta(texts["draft"], texts["editor_candidate"]),
            "editor_candidate_to_post_verification": _delta(
                texts["editor_candidate"], texts["post_verification"],
            ),
        },
        "shadow_claim_risk": _shadow_risk(question, metadata, route, texts),
    }


def replay_files(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("at least one input is required")
    source_identity = python_source_tree_identity()
    observations: list[dict[str, Any]] = []
    for path in paths:
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("input exceeds the 128 MiB diagnostic limit")
        raw = path.read_bytes()
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("input exceeds the 128 MiB diagnostic limit")
        source_sha = _sha(raw)
        try:
            if path.suffix == ".jsonl":
                rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
            elif path.suffix == ".json":
                parsed = json.loads(raw)
                rows = parsed if isinstance(parsed, list) else [parsed]
            else:
                raise ValueError("input must be .json or .jsonl")
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("input is not valid UTF-8 JSON") from exc
        if not rows or len(rows) + len(observations) > MAX_ROWS:
            raise ValueError("input row count is empty or exceeds the 2000-row limit")
        for index, row in enumerate(rows, 1):
            if not isinstance(row, Mapping):
                raise ValueError(f"row {index}: expected an object")
            observations.append(replay_trace(row, source_sha256=source_sha, row_number=index))
    if python_source_tree_identity() != source_identity:
        raise ValueError("Python package source changed during replay")
    return {
        "schema_version": SCHEMA,
        "status": "diagnostic_only",
        "current_implementation": {
            "source_tree": source_identity,
            "installed_package_version": _installed_package_version(),
            "historical_assessor_equivalence": "unavailable",
        },
        "source_count": len(paths),
        "observation_count": len(observations),
        "observations": observations,
        "interpretation_boundary": "Text changes and shadow risk flags do not establish answer quality, intervention benefit, or benchmark eligibility.",
    }
