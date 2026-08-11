from __future__ import annotations

import hashlib
from typing import Any


GOLDEN_TRACE_REPLAY_VERSION = "phase5_golden_trace_replay_v1"


def golden_trace_replay_report(rows: list[dict[str, Any]], *, min_pass_rate: float = 1.0) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    approved_diff_ids: list[str] = []
    for row in rows:
        row_id = _row_id(row)
        expected = row.get("expected") or row.get("golden") or row.get("base_trace")
        actual = row.get("actual") or row.get("replay") or row.get("replayed_trace")
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            failures.append({"id": row_id, "diffs": [{"path": "trace", "expected": "present", "actual": "missing"}]})
            continue
        diffs = compare_trace_metadata(expected, actual)
        if not diffs:
            continue
        if bool(row.get("approved_diff")):
            approved_diff_ids.append(row_id)
            continue
        failures.append({"id": row_id, "diffs": diffs})
    checked_count = len(rows)
    pass_count = max(0, checked_count - len(failures))
    pass_rate = pass_count / max(1, checked_count)
    return {
        "name": "golden_trace_replay",
        "report_version": GOLDEN_TRACE_REPLAY_VERSION,
        "samples": checked_count,
        "pass_count": pass_count,
        "failure_count": len(failures),
        "approved_diff_count": len(approved_diff_ids),
        "approved_diff_ids": approved_diff_ids,
        "pass_rate": round(pass_rate, 4),
        "trace_diff_score": round(pass_rate, 4),
        "min_pass_rate": min_pass_rate,
        "blocked": bool(rows) and pass_rate < min_pass_rate,
        "failures": failures,
    }


def compare_trace_metadata(expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    expected_snapshot = trace_metadata_snapshot(expected)
    actual_snapshot = trace_metadata_snapshot(actual)
    diffs: list[dict[str, Any]] = []
    for key in sorted(expected_snapshot.keys() | actual_snapshot.keys()):
        expected_value = expected_snapshot.get(key)
        actual_value = actual_snapshot.get(key)
        if expected_value != actual_value:
            diffs.append({"path": key, "expected": expected_value, "actual": actual_value})
    return diffs


def trace_metadata_snapshot(trace: dict[str, Any]) -> dict[str, Any]:
    trace_payload = trace.get("trace") if isinstance(trace.get("trace"), dict) else trace
    route = trace_payload.get("route") if isinstance(trace_payload.get("route"), dict) else {}
    metadata = trace_payload.get("metadata") if isinstance(trace_payload.get("metadata"), dict) else {}
    structured_answer = trace_payload.get("structured_answer") if isinstance(trace_payload.get("structured_answer"), dict) else {}
    return {
        "route.question_type": route.get("question_type"),
        "route.risk_level": route.get("risk_level"),
        "route.namespaces": _string_list(route.get("namespaces")),
        "route.required_tools": _string_list(route.get("required_tools")),
        "retrieval.doc_ids": _retrieved_doc_ids(trace_payload),
        "context.coverage_checklist": _string_list(trace_payload.get("coverage_checklist")),
        "context.tool_names": _tool_names(trace_payload.get("tool_invocations")),
        "context.packer_version": metadata.get("context_packer_version"),
        "context.tokens_est": metadata.get("context_tokens_est"),
        "output.answer_hash": _answer_hash(trace, trace_payload, structured_answer),
        "output.risk_banner": structured_answer.get("risk_banner"),
        "output.missing_data": _string_list(structured_answer.get("missing_data")),
    }


def _answer_hash(trace: dict[str, Any], trace_payload: dict[str, Any], structured_answer: dict[str, Any]) -> str | None:
    answer = structured_answer.get("answer") or trace_payload.get("answer") or trace.get("answer")
    if not answer:
        return trace.get("output_hash") or trace_payload.get("output_hash")
    return hashlib.sha256(str(answer).strip().encode("utf-8")).hexdigest()


def _retrieved_doc_ids(trace_payload: dict[str, Any]) -> list[str]:
    ids = []
    for doc in trace_payload.get("retrieved_docs", []) or []:
        if isinstance(doc, dict):
            value = doc.get("doc_id") or doc.get("id")
        else:
            value = str(doc)
        if value:
            ids.append(str(value))
    return ids


def _tool_names(tools: Any) -> list[str]:
    names = []
    for tool in tools or []:
        if isinstance(tool, dict):
            value = tool.get("name") or tool.get("tool_name")
        else:
            value = str(tool)
        if value:
            names.append(str(value))
    return sorted(names)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return sorted(str(item) for item in value)
    return [str(value)]


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("eval_id") or row.get("id") or row.get("trace_id") or "unknown")

