"""Synthetic release cells executed through the persisted product answer path.

This instrument observes mechanics, not agronomic validity. Assertions never
enter the generator prompt. A failed cell and an unreviewed judgment remain
explicit; reference arms never receive fabricated production stage receipts.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Mapping, Sequence

from agronomy_agent.agent import (
    MLXGenerator,
    MockGenerator,
    OpenAICompatibleGenerator,
    load_model_config,
    resolve_local_model_snapshot,
    system_prompt,
)
from agronomy_agent.benchmark_arms import ALL_ARM_IDS, execution_arm
from agronomy_agent.release_evaluation import TASK_FIELD_ALIASES, digest, worker_case
from agronomy_agent.execution_core import (
    AgentExecutionRequest,
    EXECUTION_STAGE_IDS,
    stable_sha256,
)
from agronomy_agent.server.services import chat_service
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore
from agronomy_agent.server.trace_timer import TraceProfiler


EXECUTOR_SCHEMA_VERSION = "open_agronomy_agent.release_product_cell.v1"
FIELD_ALIASES = TASK_FIELD_ALIASES


def exception_evidence(exc: BaseException) -> dict[str, Any]:
    """Bound actual exception leaves, including hostile messages and cycles.

    The four-KiB charge includes the persisted indent-two encoding plus sixteen
    extra spaces per line, covering its nesting in an executor turn result.
    """
    evidence: dict[str, Any] = {
        "schema_version": "open_agronomy_agent.exception_evidence.v1",
        "nodes": [], "truncated": False, "message_errors": False,
        "max_nodes": 12, "max_depth": 6, "max_encoded_bytes": 4096,
    }
    seen: set[int] = set()

    def message(value: BaseException) -> str:
        try:
            text = str(value)
        except BaseException:
            evidence["message_errors"] = True
            return "<exception message unavailable>"
        raw = text[:193].encode("utf-8", errors="replace")
        if len(text) > 192 or len(raw) > 192:
            evidence["truncated"] = True
            raw = raw[:192]
        return raw.decode("utf-8", errors="ignore")

    def visit(value: BaseException, path: str, depth: int) -> None:
        if id(value) in seen or depth > 6 or len(evidence["nodes"]) >= 12:
            evidence["truncated"] = True
            return
        seen.add(id(value))
        name = type(value).__name__
        if len(name) > 96:
            evidence["truncated"] = True
        evidence["nodes"].append({"path": path, "type": name[:96], "message": message(value)})
        if isinstance(value, BaseExceptionGroup):
            for index, child in enumerate(value.exceptions):
                if len(evidence["nodes"]) >= 12:
                    evidence["truncated"] = True
                    break
                visit(child, path + "." + str(index), depth + 1)
        related = value.__cause__ or (None if value.__suppress_context__ else value.__context__)
        if related is not None:
            visit(related, path + ".cause", depth + 1)

    visit(exc, "root", 0)
    def charge() -> int:
        data = json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return len(data) + 16 * (data.count(b"\n") + 1)
    while charge() > 4096:
        evidence["truncated"] = True
        node = max(evidence["nodes"], key=lambda item: len(item["message"].encode("utf-8")))
        if node["message"]:
            node["message"] = node["message"][:len(node["message"]) // 2]
        elif len(evidence["nodes"]) > 1:
            evidence["nodes"].pop()
        else:
            break
    return evidence


def _observed_error(exc: BaseException) -> dict[str, Any]:
    evidence = exception_evidence(exc)
    return {"type": evidence["nodes"][0]["type"], "message": evidence["nodes"][0]["message"],
            "exception_evidence": evidence}


class _DraftCheckpoint:
    """One exclusive evaluation sidecar, never a product turn or final answer."""

    def __init__(self, path: Path, bindings: Mapping[str, Any]) -> None:
        self.path = path
        self.bindings = deepcopy(dict(bindings))
        self.file_sha256: str | None = None
        self.attempted = False

    def __call__(self, observation: Mapping[str, Any]) -> None:
        if self.attempted:
            raise ValueError("completed draft checkpoint cannot be reused")
        self.attempted = True
        keys = {"schema_version", "draft", "prompt_messages", "generation_stats", "model_identity", "context_budget"}
        if (
            not isinstance(observation, Mapping) or set(observation) != keys
            or observation.get("schema_version") != "open_agronomy_agent.completed_draft_observation.v1"
            or not isinstance(observation.get("draft"), str)
            or not isinstance(observation.get("prompt_messages"), list)
            or any(not isinstance(item, dict) or not isinstance(item.get("role"), str)
                   or not isinstance(item.get("content"), str) for item in observation["prompt_messages"])
            or any(observation[key] is not None and not isinstance(observation[key], Mapping)
                   for key in ("generation_stats", "model_identity", "context_budget"))
        ):
            raise ValueError("invalid completed draft observation")
        record = {"schema_version": "open_agronomy_agent.completed_draft_checkpoint.v1",
                  "scope": "provider_returned_before_verification; terminal status is separate",
                  "bindings": self.bindings, "observation": deepcopy(dict(observation)),
                  "draft_sha256": stable_sha256(observation["draft"])}
        data = (json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        if len(data) > 262144:
            raise ValueError("completed draft checkpoint exceeds 256 KiB")
        with self.path.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        self.file_sha256 = hashlib.sha256(data).hexdigest()
        self.read()

    def read(self) -> dict[str, Any] | None:
        if self.file_sha256 is None:
            return None
        data = self.path.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.file_sha256:
            raise ValueError("completed draft checkpoint changed after capture")
        record = json.loads(data)
        if record["bindings"] != self.bindings:
            raise ValueError("completed draft checkpoint bindings changed")
        return record

    def receipt(self) -> dict[str, Any]:
        record = self.read()
        return {"status": "retained" if record is not None else "unavailable" if self.attempted else "not_observed",
                "path": str(self.path), "file_sha256": self.file_sha256,
                "draft_sha256": record["draft_sha256"] if record is not None else None,
                "scope": "partial observation; no final answer or product completion asserted"}


class SyntheticBackendUnavailable(RuntimeError):
    """A deliberately injected mock fault, distinct from a real outage."""


class _RecordedMock:
    backend_id = "release_eval_mock_v1"

    def __init__(self, fault: Mapping[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fault = dict(fault or {})
        self.last_generation_stats: dict[str, Any] | None = None
        self.model_identity = {
            "model_id": "mock",
            "backend": self.backend_id,
            "model_execution_eligible": False,
        }

    def generate(self, messages: Sequence[Mapping[str, str]]) -> str:
        call = {
            "call_index": len(self.calls) + 1,
            "messages": [dict(row) for row in messages],
        }
        self.calls.append(call)
        fail_count = int(self.fault.get("fail_calls", 0))
        if len(self.calls) <= fail_count:
            call.update(status="failed", error_type="SyntheticBackendUnavailable")
            raise SyntheticBackendUnavailable("synthetic mock backend unavailable")
        started = time.monotonic()
        answer = MockGenerator().generate([dict(row) for row in messages])
        self.last_generation_stats = {
            "backend": self.backend_id,
            "elapsed_seconds": time.monotonic() - started,
            "generation_tokens": None,
            "prompt_tokens": None,
            "synthetic": True,
        }
        call.update(status="completed", answer_sha256=stable_sha256(answer))
        return answer


def compile_case_field_context(
    value: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project explicit aliases without discarding conflicting user values."""
    compiled = deepcopy(dict(value))
    aliases: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    for alias, canonical in FIELD_ALIASES.items():
        if alias not in compiled:
            continue
        if canonical in compiled and digest(compiled[canonical]) != digest(compiled[alias]):
            conflicts.append(
                {
                    "alias": alias,
                    "canonical": canonical,
                    "alias_value": compiled[alias],
                    "canonical_value": compiled[canonical],
                }
            )
        elif canonical not in compiled:
            compiled[canonical] = compiled[alias]
            aliases[alias] = canonical
    return compiled, {
        "schema_version": "open_agronomy_agent.release_field_aliases.v1",
        "aliases_applied": aliases,
        "conflicts": conflicts,
        "input_sha256": stable_sha256(value),
        "compiled_sha256": stable_sha256(compiled),
    }


def _questions(case: Mapping[str, Any]) -> list[str]:
    if ("question" in case) == ("turns" in case):
        raise ValueError("case requires exactly one of question or turns")
    raw = [case["question"]] if "question" in case else case["turns"]
    if not isinstance(raw, list) or not raw:
        raise ValueError("turns must be a nonempty list")
    questions = [
        item.get("content") if isinstance(item, Mapping) else item for item in raw
    ]
    if any(not isinstance(item, str) or not item.strip() for item in questions):
        raise ValueError("every turn must contain nonempty user content")
    return questions


def _selected_assertions(
    case: Mapping[str, Any], arm_id: str
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    product = case.get("assertions", {})
    by_arm = case.get("assertions_by_arm", {})
    if not isinstance(product, Mapping):
        raise ValueError("assertions must be a mapping")
    if not isinstance(by_arm, Mapping) or set(by_arm) - set(ALL_ARM_IDS):
        raise ValueError("assertions_by_arm must map known execution arms")
    if any(not isinstance(value, Mapping) for value in by_arm.values()):
        raise ValueError("every assertions_by_arm entry must be a mapping")
    selected = product if arm_id == "production_full" else by_arm.get(arm_id, {})
    scope = {
        "arm_id": arm_id,
        "policy": (
            "production_required"
            if arm_id == "production_full"
            else "arm_specific_diagnostic"
        ),
        "selected_assertion_ids": sorted(selected),
        "automatic_receipt_invariants": (
            "production"
            if arm_id not in {"raw_model", "kernel_only"}
            else "ungoverned_reference"
        ),
        "not_applicable_product_expectations": [
            {"id": name, "status": "not_applicable_diagnostic_arm"}
            for name in sorted(product)
            if arm_id != "production_full"
        ],
    }
    return selected, scope


def _reference_turn(
    question: str,
    *,
    arm_id: str,
    generator: Any,
    store: TraceStore,
    session_id: str,
    history: list[dict[str, str]],
    evaluation_draft_hook: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    messages = (
        (
            [{"role": "system", "content": system_prompt()}]
            if arm_id == "kernel_only"
            else []
        )
        + history
        + [{"role": "user", "content": question}]
    )
    started = time.monotonic()
    previous_marker = getattr(generator, "generation_stats_call_id", None)
    cleared = False
    try:
        generator.last_generation_stats = None
        cleared = getattr(generator, "last_generation_stats", None) is None
    except (AttributeError, TypeError):
        pass
    answer = str(generator.generate(messages))
    current_stats = getattr(generator, "last_generation_stats", None)
    marker = getattr(generator, "generation_stats_call_id", None)
    marked = (type(previous_marker) is int and previous_marker >= 0 and type(marker) is int
              and marker > previous_marker and isinstance(current_stats, Mapping)
              and type(current_stats.get("generation_stats_call_id")) is int
              and current_stats["generation_stats_call_id"] == marker)
    # These supported implementations publish call-scoped receipts after a
    # successful return. Object identity/value changes alone prove no freshness.
    supported = type(generator) in {MLXGenerator, OpenAICompatibleGenerator, _RecordedMock}
    fresh = marked or cleared and supported
    stats = deepcopy(current_stats) if fresh and isinstance(current_stats, Mapping) else None
    receipt = {
        "schema_version": "open_agronomy_agent.ungoverned_reference_receipt.v1",
        "arm_id": arm_id,
        "backend_id": str(getattr(generator, "backend_id", type(generator).__name__)),
        "prompt_sha256": stable_sha256(messages),
        "answer_sha256": stable_sha256(answer),
        "generation_stats_freshness": "advanced_call_marker" if marked else "supported_call_scoped_provider" if fresh else "unknown",
        "generation_stats_sha256": stable_sha256(stats) if stats is not None else None,
        "generation_stats_call_id": marker if marked else None,
        "requested_max_tokens": getattr(generator, "max_tokens", None) if supported else None,
        "topology_receipts_present": False,
        "elapsed_seconds": time.monotonic() - started,
    }
    receipt["receipt_sha256"] = stable_sha256(receipt)
    if evaluation_draft_hook is not None:
        evaluation_draft_hook({
            "schema_version": "open_agronomy_agent.completed_draft_observation.v1",
            "draft": answer, "prompt_messages": deepcopy(messages),
            "generation_stats": deepcopy(stats),
            "model_identity": deepcopy(getattr(generator, "model_identity", None)),
            "context_budget": None,
        })
    turn_id = store.create_turn(
        session_id,
        question,
        answer,
        parent_turn_id=None,
        system_state={"mode": "ungoverned_reference", "arm_id": arm_id},
        trace={
            "metadata": {"reference_receipt": receipt},
            "retrieved_docs": [],
            "graph_hits": [],
            "tool_invocations": [],
        },
        objectives={},
        prompt_messages=messages,
    )
    history.extend(
        [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    )
    return {
        "status": "completed",
        "turn_id": turn_id,
        "question": question,
        "answer": answer,
        "execution_kind": "ungoverned_reference",
        "reference_receipt": receipt,
        "stage_receipts": [],
        "prompt_messages": messages,
        "task_request": {"message": question, "prompt_messages": deepcopy(messages), "field_context_delivered": None},
        "persisted_turn": store.get_turn(turn_id),
        "generation_stats": stats,
        "model_identity": deepcopy(getattr(generator, "model_identity", None)),
        "elapsed_seconds": receipt["elapsed_seconds"],
    }


def _production_turn(
    question: str, request: AgentExecutionRequest, *,
    evaluation_draft_hook: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    execution = chat_service.execute_agent_request(request, evaluation_draft_hook=evaluation_draft_hook)
    record = execution.to_record()
    trace = dict(execution.turn["trace"])
    metadata = dict(trace["metadata"])
    record.update(
        status="completed",
        question=question,
        execution_kind="production",
        persisted_turn=dict(execution.turn),
        prompt_messages=deepcopy(trace.get("prompt_messages") or []),
        generation_stats=deepcopy(metadata.get("generation_stats")),
        model_identity=deepcopy(metadata.get("model_identity")),
        source_receipts=deepcopy(trace.get("retrieved_docs") or []),
        graph_receipts=deepcopy(trace.get("graph_hits") or []),
        tool_receipts=deepcopy(trace.get("tool_invocations") or []),
        tool_results=deepcopy(
            (metadata.get("agno_runtime") or {}).get("tool_results") or []
        ),
        metadata=metadata,
        elapsed_seconds=time.monotonic() - started,
        task_request={"message": request.message,
                      "field_context_delivered": deepcopy((request.session_context or {}).get("field_context") or {})},
    )
    record["draft"] = record["answer_stages"]["draft"]["text"]
    record["editor"] = deepcopy(metadata.get("answer_verification"))
    record["final"] = record["answer_stages"]["final"]["text"]
    return record


def generation_termination(stats: Any, *, required: bool = True) -> dict[str, Any]:
    """Observe provider terminal data; token counts never establish termination."""
    reason = stats.get("finish_reason") if isinstance(stats, Mapping) else None
    known = reason in {"stop", "length"} if isinstance(reason, str) else False
    return {"required": required, "finish_reason": reason,
            "status": "not_applicable" if not required else "observed" if known else "unknown",
            "truncated": reason == "length" if known and required else None}


def observation_termination(turns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep draft/editor evidence distinct, including multi-turn unknowns."""
    stages = []
    for index, turn in enumerate(turns):
        metadata = turn.get("metadata") or {}
        editor = metadata.get("answer_verification") or turn.get("editor") or {}
        draft_required = not bool(metadata.get("generation_bypass"))
        stages.append({"turn_index": index, "stage": "reference" if turn.get("execution_kind") == "ungoverned_reference" else "draft",
                       **generation_termination(turn.get("generation_stats"), required=draft_required)})
        editor_stats = turn.get("editor_generation_stats") or editor.get("generation_stats")
        # Triggering a review is not proof that an editor model ran.
        verification_unknown = (turn.get("verification_observation") or {}).get("status") == "unknown_after_draft_return"
        editor_required = verification_unknown or editor_stats is not None or editor.get("editor_output") is not None or editor.get("rewrite_accepted") is True or "editor_error" in (editor.get("rejection_reasons") or [])
        stages.append({"turn_index": index, "stage": "editor",
                       **generation_termination(editor_stats, required=editor_required),
                       **({"attempt_observation": "unknown"} if verification_unknown else {})})
    required = [stage for stage in stages if stage["required"]]
    truncated = True if any(stage["truncated"] is True for stage in required) else None if not required or any(stage["status"] == "unknown" for stage in required) else False
    return {"schema_version": "open_agronomy_agent.generation_termination.v1",
            "stages": stages, "status": "not_applicable" if stages and not required else "unknown" if not required or any(stage["status"] == "unknown" for stage in required) else "observed",
            "truncated": truncated, "finish_reason": "length" if truncated is True else "stop" if truncated is False else None}


def _checks(
    case: Mapping[str, Any],
    turns: list[dict[str, Any]],
    arm: Any,
    alias_receipt: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []

    def check(identifier: str, passed: bool, detail: Any) -> None:
        checks.append({"id": identifier, "passed": bool(passed), "detail": detail})

    check(
        "field_aliases_unambiguous",
        not alias_receipt["conflicts"],
        alias_receipt["conflicts"],
    )
    completed = [turn for turn in turns if turn["status"] == "completed"]
    for index, turn in enumerate(turns):
        prefix = f"turn_{index + 1}"
        if turn["status"] != "completed":
            check(f"{prefix}.execution_completed", False, turn.get("error"))
            continue
        saved = turn["persisted_turn"]
        check(
            f"{prefix}.persisted_answer",
            saved is not None and saved.get("answer") == turn["answer"],
            {"turn_id": turn["turn_id"]},
        )
        if turn["execution_kind"] != "production":
            check(
                f"{prefix}.reference_has_no_product_topology",
                not turn["stage_receipts"],
                turn["execution_kind"],
            )
            continue
        if turn.get("generation_stats") and turn.get(
            "model_revision_observation", {}
        ).get("configured"):
            check(
                f"{prefix}.model_revision_verified",
                turn["model_revision_observation"]["verified"],
                turn["model_revision_observation"],
            )
        if case.get("_requested_backend") != "mock":
            check(
                f"{prefix}.real_backend_and_editor_available",
                turn["model_execution"]["backend_available"],
                turn["generation_origin"],
            )
            if turn["model_execution"]["disposition"] == "model_generated":
                check(
                    f"{prefix}.real_generation_observed",
                    turn["model_execution_eligible"],
                    turn["model_execution"],
                )
        receipts = {row["stage_id"]: row for row in turn["stage_receipts"]}
        check(
            f"{prefix}.ordered_stages",
            list(receipts) == list(EXECUTION_STAGE_IDS),
            list(receipts),
        )
        for flag, stage, outputs in (
            (
                arm.document_retrieval_enabled,
                "document_retrieval",
                turn["source_receipts"],
            ),
            (arm.graph_retrieval_enabled, "graph_retrieval", turn["graph_receipts"]),
            (arm.typed_tools_enabled, "tool_execution", turn["tool_results"]),
        ):
            if not flag:
                check(
                    f"{prefix}.{stage}_disabled",
                    receipts[stage]["state"] == "disabled_by_arm" and not outputs,
                    receipts[stage]["state"],
                )
        if not arm.field_context_enabled:
            field_receipt = receipts["typed_field_context"]
            compiled = turn["metadata"].get("field_context_compiler") or {}
            check(
                f"{prefix}.typed_field_context_disabled",
                field_receipt["state"] == "disabled_by_arm"
                and field_receipt["evidence"].get("field_context_present") is False
                and not compiled.get("field")
                and not compiled.get("map_context")
                and not compiled.get("live_context"),
                {
                    "state": field_receipt["state"],
                    "field_context_present": field_receipt["evidence"].get(
                        "field_context_present"
                    ),
                },
            )
        if turn["tool_results"]:
            expected = receipts["tool_execution"]["evidence"]
            check(
                f"{prefix}.tool_results_bound",
                stable_sha256(turn["tool_results"]) == expected["results_sha256"],
                {"result_ids": expected["result_ids"]},
            )
            check(
                f"{prefix}.tool_payloads_bound",
                all(
                    row.get("payload_sha256") == stable_sha256(row.get("payload"))
                    for row in turn["tool_results"]
                ),
                [row.get("result_id") for row in turn["tool_results"]],
            )
            if (
                turn["metadata"].get("generation_path") == "deterministic_tool_result"
                and len(turn["tool_results"]) == 1
            ):
                payload_answer = (
                    turn["tool_results"][0].get("payload", {}).get("answer")
                )
                check(
                    f"{prefix}.tool_answer_used",
                    payload_answer == turn["draft"],
                    {
                        "result_id": turn["tool_results"][0].get("result_id"),
                        "draft_sha256": stable_sha256(turn["draft"]),
                    },
                )
        check(
            f"{prefix}.private_overlays_absent",
            int(turn["metadata"].get("workspace_doc_count") or 0) == 0,
            turn["metadata"].get("workspace_doc_count", 0),
        )
    assertions = case.get("assertions", {})
    if not isinstance(assertions, Mapping):
        raise ValueError("assertions must be a mapping")
    latest = completed[-1] if completed else {}
    metadata = latest.get("metadata") or {}
    receipts = {row["stage_id"]: row for row in latest.get("stage_receipts", [])}
    for key, expected in assertions.items():
        observed: Any = None
        supported = latest.get("execution_kind") == "production"
        if key == "stage_states" and supported:
            observed = {
                stage: receipts.get(stage, {}).get("state") for stage in expected
            }
            passed = observed == expected
        elif key == "tool_status" and supported:
            observed = (metadata.get("tool_plan") or {}).get("status")
            passed = observed == expected
        elif key == "expected_operations" and supported:
            observed = [
                row.get("operation")
                for row in (metadata.get("tool_plan") or {}).get("invocations", [])
            ]
            passed = set(expected).issubset(observed)
        elif key == "field_values" and supported:
            field = (metadata.get("field_context_compiler") or {}).get("field") or {}
            observed = {name: field.get(name) for name in expected}
            passed = observed == expected
        elif key == "history_resolution" and supported:
            observed = (metadata.get("conversation_resolution") or {}).get("status")
            passed = observed == expected
        elif (
            key in {"expected_source_ids", "forbidden_source_ids", "require_no_sources"}
            and supported
        ):
            observed = sorted(
                {
                    str(row.get("source_id") or row.get("doc_id") or "")
                    for row in latest.get("source_receipts", [])
                }
            )
            passed = (
                set(expected).issubset(observed)
                if key == "expected_source_ids"
                else (
                    not set(expected).intersection(observed)
                    if key == "forbidden_source_ids"
                    else (not observed) == expected
                )
            )
        elif key == "generation_origin" and supported:
            observed = (
                (receipts.get("fallback_origin") or {})
                .get("evidence", {})
                .get("origin_class")
            )
            passed = observed == expected
        elif key == "fault_expected":
            observed = any(
                row.get("status") == "failed" for row in case.get("_backend_calls", [])
            )
            passed = observed == expected
        elif key == "recovery_expected":
            calls = case.get("_backend_calls", [])
            observed = any(row.get("status") == "completed" for row in calls) and any(
                row.get("status") == "failed" for row in calls
            )
            passed = observed == expected
        else:
            unknown.append(
                {
                    "id": key,
                    "detail": "semantic review or unsupported assertion; no automatic semantic judgment",
                    "expected": expected,
                }
            )
            if key != "semantic_assertions":
                check(
                    key,
                    False,
                    "unsupported required mechanical assertion or unavailable production observations",
                )
            continue
        check(key, passed, {"expected": expected, "observed": observed})
    if case.get("review_required"):
        unknown.append(
            {
                "id": "semantic_review",
                "detail": "independent domain review required; mechanical checks do not establish answer validity",
            }
        )
    if case.get("scoring"):
        unknown.append(
            {
                "id": "answer_scoring",
                "detail": "answer scoring belongs to the independent release scorer",
                "contract": deepcopy(case["scoring"]),
            }
        )
    return checks, unknown


def execute_product_case(
    case: Mapping[str, Any],
    *,
    model_config: Path,
    rag_config: Path,
    arm_id: str = "production_full",
    backend: str = "mock",
    max_tokens: int = 640,
    output_dir: Path,
    trial_id: str = "trial-001",
) -> dict[str, Any]:
    """Execute one isolated case/trial, retaining completed and failed turns.

    ``output_dir`` owns a new case-arm-trial subdirectory. Existing cells are
    rejected, never overwritten. ``mlx`` uses the product's configured model
    adapter (including an explicitly configured HTTP transport for GPU runs).
    Synthetic faults are permitted only for declared mock fault cases.
    """
    started = time.monotonic()
    result: dict[str, Any] = {
        "schema_version": EXECUTOR_SCHEMA_VERSION,
        "status": "failed",
        "case_id": str(case.get("case_id") or ""),
        "scenario_family": str(case.get("scenario_family") or ""),
        "lane": case.get("lane"),
        "arm_id": arm_id,
        "trial_id": trial_id,
        "backend": backend,
        "turns": [],
        "checks": [],
        "unknown": [],
        "claim_eligible": False,
        "model_execution_eligible": False,
    }
    store = None
    cell_dir = None
    pending_control_flow: BaseException | None = None
    try:
        arm = execution_arm(arm_id)
        if backend not in {"mock", "mlx"}:
            raise ValueError("backend must be mock or mlx")
        if (
            not result["case_id"]
            or not result["scenario_family"]
            or result["lane"] not in {"harness", "conversation", "agronomy"}
        ):
            raise ValueError(
                "case_id, scenario_family and harness/conversation/agronomy lane are required"
            )
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        selected_assertions, assertion_scope = _selected_assertions(case, arm_id)
        result["assertion_scope"] = assertion_scope
        if not isinstance(case.get("review_required"), bool):
            raise ValueError("review_required must be an explicit bool")
        questions = _questions(case)
        field = case.get("field_context", {})
        if not isinstance(field, Mapping):
            raise ValueError("field_context must be a mapping")
        compiled, aliases = compile_case_field_context(field)
        fault = case.get("synthetic_fault")
        if fault is not None:
            if (
                backend != "mock"
                or result["scenario_family"] != "backend_faults"
                or not isinstance(fault, Mapping)
                or fault.get("kind") != "backend_unavailable"
                or type(fault.get("fail_calls")) is not int
                or fault["fail_calls"] <= 0
            ):
                raise ValueError(
                    "synthetic_fault requires a mock backend_faults case and positive backend_unavailable fail_calls"
                )
        slug = re.sub(
            r"[^A-Za-z0-9_.-]", "_", f"{result['case_id']}--{arm_id}--{trial_id}"
        )
        cell_dir = Path(output_dir) / (
            slug + "--" + stable_sha256([result["case_id"], arm_id, trial_id])[:10]
        )
        cell_dir.mkdir(parents=True, exist_ok=False)
        result["artifact_dir"] = str(cell_dir.resolve())
        result["case_sha256"] = stable_sha256(case)
        result["config_identity"] = {
            name: {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in (("model", Path(model_config)), ("rag", Path(rag_config)))
        }
        result["draft_checkpoint_sources"] = {
            name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for name, path in (("executor", __file__), ("service", chat_service.__file__))
        }
        result["field_alias_receipt"] = aliases
        result["arm_configuration"] = arm.to_dict()
        result["execution_kind"] = (
            "ungoverned_reference"
            if arm_id in {"raw_model", "kernel_only"}
            else "production"
        )
        store = TraceStore(cell_dir / "trace.sqlite3")
        session = store.create_session(result["case_id"], {}, {})
        session_id = session["session_id"]
        result["session_id"] = session_id
        config = load_model_config(model_config)
        model_id = (
            "mock"
            if backend == "mock"
            else str(config.get("serving_model_id") or config["model_id"])
        )
        revision = str(config.get("model_revision") or "") or None
        transport = (
            "mock"
            if backend == "mock"
            else os.getenv("AGRONOMY_AGENT_MODEL_BACKEND", "mlx").strip().lower()
        )
        snapshot = None
        if backend == "mlx" and transport in {"mlx", "native", "local"}:
            snapshot = resolve_local_model_snapshot(model_id, revision=revision)
        result["execution_metadata"] = {
            "requested_backend": backend,
            "transport": transport,
            "configured_model_id": model_id,
            "configured_model_revision": revision if backend != "mock" else None,
            "resolved_snapshot": str(snapshot) if snapshot else None,
            "resolved_model_revision": snapshot.name if snapshot else None,
            "synthetic": backend == "mock",
        }
        settings = build_settings(
            db_path=cell_dir / "trace.sqlite3",
            artifact_root=cell_dir / "artifacts",
            model_config_path=str(model_config),
            default_rag_config=str(rag_config),
            network_mode="offline",
        )
        generator = _RecordedMock(fault) if backend == "mock" else None
        history: list[dict[str, str]] = []
        for turn_index, question in enumerate(questions, 1):
            turn_started = time.monotonic()
            profiler = TraceProfiler()
            profiler.set_thread_id(session_id)
            checkpoint = _DraftCheckpoint(cell_dir / f"turn-{turn_index}-completed-draft.json", {
                "case_id": result["case_id"], "case_sha256": result["case_sha256"],
                "arm_id": arm_id, "trial_id": trial_id, "turn_index": turn_index,
                "config_identity": result["config_identity"],
                "source_files": result["draft_checkpoint_sources"],
            })
            try:
                if result["execution_kind"] == "ungoverned_reference":
                    if generator is None:
                        generator = chat_service._build_mlx_generator(
                            model_id, config, str(model_config)
                        )
                        generator.max_tokens = max_tokens
                    turn = _reference_turn(
                        question,
                        arm_id=arm_id,
                        generator=generator,
                        store=store,
                        session_id=session_id,
                        history=history,
                        evaluation_draft_hook=checkpoint,
                    )
                else:
                    request = AgentExecutionRequest(
                        store=store,
                        settings=settings,
                        session_id=session_id,
                        message=question,
                        mode="agronomic_rag",
                        model_id=model_id,
                        rag_config=str(rag_config),
                        max_tokens=max_tokens,
                        trace_options={
                            "store_prompt_messages": True,
                            "store_retrieved_text": True,
                        },
                        session_context=(
                            {"field_context": compiled} if compiled else None
                        ),
                        generation_backend=generator,
                        profiler=profiler,
                        execution_class="product_turn",
                        **arm.request_controls(),
                    )
                    turn = _production_turn(question, request, evaluation_draft_hook=checkpoint)
                retained_draft = checkpoint.read()
                metadata = turn.get("metadata") or {}
                bypassed = any(metadata.get(name) for name in (
                    "generation_bypass", "generation_fallback", "generation_unavailable"
                ))
                if not bypassed and retained_draft is None:
                    raise ValueError("completed provider return lacks its draft checkpoint")
                if retained_draft is not None and retained_draft["draft_sha256"] != stable_sha256(
                    turn["answer"] if result["execution_kind"] == "ungoverned_reference" else turn["draft"]
                ):
                    raise ValueError("completed draft checkpoint disagrees with returned draft")
                turn["draft_checkpoint"] = checkpoint.receipt()
                profiler.set_turn_id(turn["turn_id"])
                identity = turn.get("model_identity") or {}
                resolved_revision = (identity.get("runtime") or {}).get(
                    "model_revision"
                ) or (snapshot.name if snapshot else None)
                identity_verified = (
                    backend != "mock"
                    and identity.get("status")
                    in {"verified_runtime_receipt", "verified_direct_loader"}
                    and revision is not None
                    and resolved_revision == revision
                )
                turn["model_revision_observation"] = {
                    "configured": revision if backend != "mock" else None,
                    "resolved": resolved_revision,
                    "verified": identity_verified,
                }
                turn["model_execution_eligible"] = (
                    identity_verified
                    and bool(turn.get("generation_stats"))
                    and not (turn.get("metadata") or {}).get("generation_bypass")
                    and not (turn.get("metadata") or {}).get("generation_fallback")
                )
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    pending_control_flow = exc
                try:
                    persistence = {"session_turn_count": store.count_session_turns(session_id)}
                except Exception as count_error:
                    persistence = {"session_turn_count": None, "status": "unknown",
                                   "error": _observed_error(count_error)}
                turn = {
                    "status": "interrupted" if pending_control_flow is not None else "failed",
                    "execution_kind": result["execution_kind"],
                    "question": question,
                    "error": _observed_error(exc),
                    "stage_receipts": [],
                    "answer": None,
                    "model_execution_eligible": False,
                    "elapsed_seconds": time.monotonic() - turn_started,
                    "persistence_observation": persistence,
                    "receipt_boundary": "exception interrupted execution; no complete production topology is asserted",
                }
                try:
                    retained_draft = checkpoint.read()
                    turn["draft_checkpoint"] = checkpoint.receipt()
                    if retained_draft is not None:
                        observation = retained_draft["observation"]
                        turn.update(draft=observation["draft"], final=None,
                                    prompt_messages=deepcopy(observation["prompt_messages"]),
                                    generation_stats=deepcopy(observation["generation_stats"]),
                                    model_identity=deepcopy(observation["model_identity"]))
                        if result["execution_kind"] == "production" and arm.verifier_enabled and (config.get("answer_verification") or {}).get("enabled"):
                            turn["verification_observation"] = {"status": "unknown_after_draft_return", "attempted": None}
                except Exception as checkpoint_error:
                    turn["draft_checkpoint"] = {"status": "unverified", "path": str(checkpoint.path),
                                                "error": _observed_error(checkpoint_error)}
            turn["profiler_spans"] = profiler.span_records()
            turn["editor_generation_stats"] = deepcopy(
                ((turn.get("metadata") or {}).get("answer_verification") or {}).get(
                    "generation_stats"
                )
            )
            turn["verification_generation_stats"] = deepcopy(
                turn["editor_generation_stats"]
            )
            turn["elapsed_ms"] = round(turn["elapsed_seconds"] * 1000, 3)
            origin_receipt = next(
                (
                    row
                    for row in turn.get("stage_receipts", [])
                    if row["stage_id"] == "fallback_origin"
                ),
                {},
            )
            turn["generation_origin"] = (origin_receipt.get("evidence") or {}).get(
                "origin_class"
            ) or (
                "ungoverned_reference"
                if turn["status"] == "completed" and turn.get("execution_kind") == "ungoverned_reference"
                else "execution_failed"
            )
            metadata = turn.get("metadata") or {}
            editor_failed = "editor_error" in (
                (metadata.get("answer_verification") or {}).get("rejection_reasons")
                or []
            )
            backend_available = (
                turn["status"] == "completed"
                and not metadata.get("generation_fallback")
                and not metadata.get("generation_unavailable")
                and not editor_failed
            )
            disposition = (
                "backend_fallback_or_unavailable"
                if not backend_available
                else (
                    "deterministic_bypass"
                    if metadata.get("generation_bypass")
                    else (
                        "model_generated" if turn.get("generation_stats") else "unknown"
                    )
                )
            )
            turn["model_execution"] = {
                "disposition": disposition,
                "model_generation_eligible": turn["model_execution_eligible"],
                "model_execution_eligible": turn["model_execution_eligible"],
                "product_quality_eligible": backend != "mock"
                and backend_available
                and result["execution_kind"] == "production"
                and (turn.get("model_revision_observation") or {}).get("verified")
                is True,
                "backend_available": bool(backend_available),
                "synthetic": backend == "mock",
                "generation_stats_present": bool(turn.get("generation_stats")),
                "identity": deepcopy(turn.get("model_identity")),
            }
            turn["termination"] = observation_termination([turn])
            turn["time_to_first_token_ms"] = (turn.get("generation_stats") or {}).get(
                "time_to_first_token_ms"
            )
            turn["peak_memory_bytes"] = None
            if backend == "mlx" and transport in {"mlx", "native", "local"}:
                try:
                    mx = sys.modules.get("mlx.core")
                    if mx is not None:
                        turn["peak_memory_bytes"] = mx.get_peak_memory()
                        turn["peak_memory_scope"] = (
                            "process_cumulative_since_last_external_reset"
                        )
                except (AttributeError, RuntimeError):
                    pass
            result["turns"].append(turn)
            if pending_control_flow is not None or (
                checkpoint.attempted and turn.get("draft_checkpoint", {}).get("status") != "retained"
            ):
                break
        calls = (
            deepcopy(generator.calls) if isinstance(generator, _RecordedMock) else []
        )
        result["backend_calls"] = calls
        exposure = {"schema_version": "open_agronomy_agent.task_exposure.v1", "arm_id": arm_id,
                    "scope": "inputs delivered to reference generator or execute_agent_request; field consumption and final prompt are separate stage/recipe observations",
                    "worker_case_sha256": digest(worker_case(case)),
                    "requests": [deepcopy(turn["task_request"]) for turn in result["turns"] if "task_request" in turn],
                    "compiled_field_context_sha256": digest(compiled), "field_alias_receipt": aliases}
        exposure["receipt_sha256"] = digest(exposure)
        result["task_exposure"] = exposure
        result["checks"], result["unknown"] = _checks(
            {
                **case,
                "assertions": selected_assertions,
                "_backend_calls": calls,
                "_requested_backend": backend,
            },
            result["turns"],
            arm,
            aliases,
        )
        result["status"] = (
            "interrupted" if pending_control_flow is not None else (
                "completed" if all(turn["status"] == "completed" for turn in result["turns"])
                else "failed"
            )
        )
        result["model_execution_eligible"] = any(
            turn["model_execution_eligible"] for turn in result["turns"]
        )
        result["termination"] = observation_termination(result["turns"])
        result["finish_reason"] = result["termination"]["finish_reason"]
        result["truncated"] = result["termination"]["truncated"]
    except BaseException as exc:
        if not isinstance(exc, Exception):
            pending_control_flow = exc
        result["status"] = "interrupted" if pending_control_flow is not None else "failed"
        result["error"] = _observed_error(exc)
        result["checks"].append(
            {"id": "cell_execution", "passed": False, "detail": result["error"]}
        )
    finally:
        if store is not None:
            try:
                store._conn.close()
            except BaseException as exc:
                result["close_error"] = _observed_error(exc)
                result["status"] = "interrupted" if pending_control_flow is not None else "failed"
                result["checks"].append({"id": "cell_store_close", "passed": False})
                if not isinstance(exc, Exception) and pending_control_flow is None:
                    pending_control_flow = exc
                    result["status"] = "interrupted"
    result["failed_checks"] = [
        row for row in result["checks"] if row["passed"] is False
    ]
    result["elapsed_seconds"] = time.monotonic() - started
    result["result_sha256"] = stable_sha256(result)
    if cell_dir is not None and cell_dir.is_dir() and "artifact_dir" in result:
        try:
            (cell_dir / "result.json").write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        except BaseException as closeout_error:
            if pending_control_flow is None:
                raise
            # Disk failure cannot replace an already pending cancellation/exit.
            # Retain bounded evidence on that original exception when its own
            # result file is unwritable; never fall back to a foreign path.
            bounded = _observed_error(closeout_error)
            try:
                pending_control_flow.evaluation_closeout_error = bounded
                pending_control_flow.add_note("evaluation_closeout_error=" + json.dumps(bounded, ensure_ascii=False, separators=(",", ":")))
            except BaseException:
                pass
    if pending_control_flow is not None:
        raise pending_control_flow
    return result


__all__ = [
    "execute_product_case",
    "compile_case_field_context",
    "SyntheticBackendUnavailable",
    "EXECUTOR_SCHEMA_VERSION",
]
