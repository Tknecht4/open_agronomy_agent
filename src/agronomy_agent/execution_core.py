"""Typed receipts for the production answer-execution path.

This module deliberately does not implement a second agent.  The server owns
the production orchestration; it records the observations defined here and
returns an :class:`AgentExecutionResult`.  Benchmark rehearsals consume that
same result, so they cannot manufacture answers from case expectations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from agronomy_agent.server.settings import ServerSettings
    from agronomy_agent.server.storage.db import TraceStore


EXECUTION_REQUEST_SCHEMA_VERSION = "open_agronomy_agent.execution_request.v2"
EXECUTION_RESULT_SCHEMA_VERSION = "open_agronomy_agent.execution_result.v1"
EXECUTION_STAGE_RECEIPT_SCHEMA_VERSION = (
    "open_agronomy_agent.execution_stage_receipt.v1"
)
EXECUTION_STAGE_TOPOLOGY_VERSION = "open_agronomy_agent.production_stage_topology.v3"

SUPPORTED_EXECUTION_CLASSES = frozenset(
    {"product_turn", "observed_system_execution_nonclaim"}
)
SUPPORTED_MODES = frozenset({"baseline", "agronomic_rag", "mock"})
STAGE_STATES = frozenset(
    {
        "executed",
        "bypassed",
        "not_applicable",
        "failed",
        # Retrieval stages use a more precise arm-aware state vocabulary.  The
        # generic states remain valid for every other production stage.
        "completed",
        "completed_no_result",
        "disabled_by_arm",
    }
)
RETRIEVAL_COMPONENT_STATES = frozenset(
    {"completed", "completed_no_result", "disabled_by_arm"}
)

# This order is part of the observed-system contract.  A new, removed, or
# reordered answer-affecting stage requires an explicit topology-version
# decision instead of being silently ignored by the benchmark adapter.
EXECUTION_STAGE_SPECS: tuple[tuple[str, bool], ...] = (
    ("routing", True),
    ("typed_field_context", True),
    ("public_adapter_selection", True),
    ("document_retrieval", True),
    ("graph_retrieval", True),
    ("evidence_selection_packing", True),
    ("tool_planning", True),
    ("tool_execution", True),
    ("prompt_construction", True),
    ("pre_generation_answerability_risk_intervention", True),
    ("deterministic_bypass", True),
    ("draft_generation", True),
    ("verification", True),
    ("safety_normalization", True),
    ("high_consequence_policy", True),
    ("structured_rendering", True),
    ("fallback_origin", True),
)
EXECUTION_STAGE_IDS = tuple(stage_id for stage_id, _ in EXECUTION_STAGE_SPECS)
_ANSWER_AFFECTING_BY_STAGE = dict(EXECUTION_STAGE_SPECS)

# A stage receipt is useful only when it proves more than presence in a list.
# Every stage therefore carries a human-readable decision reason plus at least
# one content-addressed observation specific to that boundary.  Empty generic
# evidence mappings cannot satisfy this contract, even when their outer receipt
# hash has been recomputed.
EXECUTION_STAGE_REQUIRED_EVIDENCE_KEYS: dict[str, tuple[str, ...]] = {
    "routing": ("reason", "question_type", "risk_level", "route_sha256"),
    "typed_field_context": (
        "reason",
        "compiler_receipt_sha256",
        "field_context_present",
    ),
    "public_adapter_selection": (
        "reason",
        "record_count",
        "records_sha256",
        "status_counts_sha256",
    ),
    "document_retrieval": (
        "reason",
        "enabled",
        "executed",
        "document_count",
        "document_ids_sha256",
        "workspace_document_count",
        "workspace_document_ids_sha256",
    ),
    "graph_retrieval": (
        "reason",
        "enabled",
        "executed",
        "graph_hit_count",
        "graph_node_ids_sha256",
    ),
    "evidence_selection_packing": (
        "reason",
        "context_present",
        "source_grounded",
        "selection_sha256",
    ),
    "tool_planning": (
        "reason",
        "plan_status",
        "tool_plan_sha256",
        "invocation_ids_sha256",
    ),
    "tool_execution": (
        "reason",
        "result_count",
        "result_ids_sha256",
        "results_sha256",
    ),
    "prompt_construction": (
        "reason",
        "message_count",
        "messages_sha256",
        "raw_messages_retained",
    ),
    "pre_generation_answerability_risk_intervention": (
        "reason",
        "decision_sha256",
        "intervention_receipt_sha256",
    ),
    "deterministic_bypass": (
        "reason",
        "bypass_selected",
        "decision_sha256",
    ),
    "draft_generation": (
        "reason",
        "generation_path",
        "model_call_executed",
        "draft_sha256",
    ),
    "verification": (
        "reason",
        "configured",
        "executed",
        "draft_sha256",
        "post_verification_sha256",
        "adjudication_sha256",
    ),
    "safety_normalization": (
        "reason",
        "changed_answer",
        "input_sha256",
        "output_sha256",
    ),
    "high_consequence_policy": (
        "reason",
        "policy_status",
        "boundary_changed_answer",
        "input_sha256",
        "output_sha256",
        "policy_sha256",
    ),
    "structured_rendering": (
        "reason",
        "input_sha256",
        "renderer_sha256",
        "final_sha256",
    ),
    "fallback_origin": (
        "reason",
        "origin_class",
        "fallback_used",
        "verification_action",
        "verification_triggered",
        "verification_fallback_applied",
        "rewrite_accepted",
        "replacement_used",
        "draft_sha256",
        "post_verification_sha256",
        "final_sha256",
        "verification_receipt_sha256",
        "origin_record",
        "origin_sha256",
    ),
}

EXECUTION_STAGE_EVIDENCE_DIGEST_KEYS: dict[str, tuple[str, ...]] = {
    stage_id: tuple(key for key in keys if key.endswith("_sha256"))
    for stage_id, keys in EXECUTION_STAGE_REQUIRED_EVIDENCE_KEYS.items()
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def classify_verification_origin(
    verification_record: Mapping[str, Any] | None,
    *,
    draft_sha256: str,
    post_verification_sha256: str,
) -> dict[str, Any]:
    """Classify the verifier's contribution without conflating two outcomes.

    An accepted editor rewrite is a model-editor selection, not a fallback.
    A verifier fallback is a conservative deterministic/degraded selection.
    ``replacement_used`` is separately content-derived because either selection
    can theoretically produce text identical to the draft.
    """

    record = dict(verification_record or {})
    fallback_applied = record.get("fallback_applied") is True
    rewrite_accepted = record.get("rewrite_accepted") is True
    triggered = record.get("triggered") is True
    if fallback_applied and rewrite_accepted:
        raise ValueError(
            "answer verification cannot accept an editor rewrite and apply fallback"
        )
    replacement_used = draft_sha256 != post_verification_sha256
    if str(record.get("schema_version") or "").startswith(
        "open_agronomy_agent.typed_capability_validation."
    ):
        action = "typed_capability_validation"
    elif fallback_applied:
        action = "conservative_fallback"
    elif rewrite_accepted:
        action = "accepted_editor_rewrite"
    elif triggered:
        action = "reviewed_draft_preserved"
    elif record:
        action = "not_triggered"
    else:
        action = "not_recorded"
    if action in {
        "typed_capability_validation",
        "reviewed_draft_preserved",
        "not_triggered",
        "not_recorded",
    } and replacement_used:
        raise ValueError(
            f"verification action {action!r} contradicts changed post-verification text"
        )
    return {
        "verification_action": action,
        "verification_triggered": triggered,
        "verification_fallback_applied": fallback_applied,
        "rewrite_accepted": rewrite_accepted,
        "replacement_used": replacement_used,
    }


def _validate_stage_evidence(stage_id: str, evidence: Mapping[str, Any]) -> None:
    required_keys = EXECUTION_STAGE_REQUIRED_EVIDENCE_KEYS[stage_id]
    missing = [key for key in required_keys if key not in evidence]
    if missing:
        raise ValueError(
            f"stage {stage_id} evidence is missing required keys: {missing}"
        )
    reason = evidence.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"stage {stage_id} evidence reason must be nonempty")
    for key in EXECUTION_STAGE_EVIDENCE_DIGEST_KEYS[stage_id]:
        digest = evidence.get(key)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(
                f"stage {stage_id} evidence {key} must be a lowercase sha256 digest"
            )


def _validate_stage_semantics(receipts: list[dict[str, Any]]) -> None:
    by_id = {str(receipt["stage_id"]): receipt for receipt in receipts}

    def evidence(stage_id: str) -> Mapping[str, Any]:
        return by_id[stage_id]["evidence"]

    if not str(evidence("routing").get("question_type") or "").strip():
        raise ValueError("routing evidence has no question type")

    document = evidence("document_retrieval")
    document_ids = document.get("document_ids")
    if not isinstance(document_ids, list) or document.get("document_count") != len(
        document_ids
    ):
        raise ValueError("document_retrieval evidence count does not match its IDs")
    graph = evidence("graph_retrieval")
    graph_ids = graph.get("graph_node_ids")
    if not isinstance(graph_ids, list) or graph.get("graph_hit_count") != len(
        graph_ids
    ):
        raise ValueError("graph_retrieval evidence count does not match its IDs")

    tool_execution = evidence("tool_execution")
    result_ids = tool_execution.get("result_ids")
    if not isinstance(result_ids, list) or tool_execution.get("result_count") != len(
        result_ids
    ):
        raise ValueError("tool_execution evidence count does not match its IDs")
    if int(evidence("prompt_construction").get("message_count") or 0) <= 0:
        raise ValueError("prompt_construction evidence has no messages")

    deterministic_bypass = by_id["deterministic_bypass"]
    bypass_selected = deterministic_bypass["evidence"].get("bypass_selected")
    if not isinstance(bypass_selected, bool):
        raise ValueError("deterministic_bypass evidence must record a bool decision")
    expected_bypass_state = "executed" if bypass_selected else "not_applicable"
    if deterministic_bypass.get("state") != expected_bypass_state:
        raise ValueError("deterministic_bypass state contradicts its decision evidence")
    draft_generation = by_id["draft_generation"]
    if bypass_selected and draft_generation.get("state") != "bypassed":
        raise ValueError("selected deterministic bypass did not bypass draft generation")
    if bypass_selected and draft_generation["evidence"].get("model_call_executed") is not False:
        raise ValueError("selected deterministic bypass claims a model call")

    verification = evidence("verification")
    safety = evidence("safety_normalization")
    high_consequence = evidence("high_consequence_policy")
    rendering = evidence("structured_rendering")
    fallback_origin = evidence("fallback_origin")
    continuity = (
        (
            draft_generation["evidence"].get("draft_sha256"),
            verification.get("draft_sha256"),
            "draft_generation_to_verification",
        ),
        (
            verification.get("post_verification_sha256"),
            safety.get("input_sha256"),
            "verification_to_safety",
        ),
        (
            safety.get("output_sha256"),
            high_consequence.get("input_sha256"),
            "safety_to_high_consequence",
        ),
        (
            high_consequence.get("output_sha256"),
            rendering.get("input_sha256"),
            "high_consequence_to_rendering",
        ),
        (
            draft_generation["evidence"].get("draft_sha256"),
            fallback_origin.get("draft_sha256"),
            "draft_generation_to_origin",
        ),
        (
            verification.get("post_verification_sha256"),
            fallback_origin.get("post_verification_sha256"),
            "verification_to_origin",
        ),
        (
            rendering.get("final_sha256"),
            fallback_origin.get("final_sha256"),
            "rendering_to_origin",
        ),
    )
    for upstream, downstream, boundary in continuity:
        if upstream != downstream:
            raise ValueError(f"execution stage hash continuity mismatch: {boundary}")

    origin_record = fallback_origin.get("origin_record")
    if not isinstance(origin_record, Mapping):
        raise ValueError("fallback_origin evidence has no origin record")
    if fallback_origin.get("origin_sha256") != stable_sha256(dict(origin_record)):
        raise ValueError("fallback_origin evidence does not address its origin record")
    fallback_used = fallback_origin.get("fallback_used")
    if not isinstance(fallback_used, bool):
        raise ValueError("fallback_origin evidence must record fallback use as a bool")
    if fallback_used != bool(origin_record.get("fallback_used")):
        raise ValueError("fallback_origin use flag contradicts its origin record")
    if (
        fallback_origin.get("verification_receipt_sha256")
        != verification.get("adjudication_sha256")
    ):
        raise ValueError("fallback_origin is not linked to the verification receipt")
    replacement_used = fallback_origin.get("replacement_used")
    expected_replacement = (
        fallback_origin.get("draft_sha256")
        != fallback_origin.get("post_verification_sha256")
    )
    if not isinstance(replacement_used, bool) or replacement_used != expected_replacement:
        raise ValueError("fallback_origin replacement flag contradicts answer hashes")
    for key in (
        "origin_class",
        "verification_action",
        "verification_triggered",
        "verification_fallback_applied",
        "rewrite_accepted",
        "replacement_used",
        "verification_receipt_sha256",
    ):
        if fallback_origin.get(key) != origin_record.get(key):
            raise ValueError(
                f"fallback_origin evidence contradicts its origin record: {key}"
            )
    verification_action = fallback_origin.get("verification_action")
    verification_fallback_applied = fallback_origin.get(
        "verification_fallback_applied"
    )
    rewrite_accepted = fallback_origin.get("rewrite_accepted")
    origin_class = fallback_origin.get("origin_class")
    if verification_fallback_applied is True:
        if (
            verification_action != "conservative_fallback"
            or rewrite_accepted is not False
            or fallback_used is not True
            or origin_class != "verifier_conservative_fallback"
        ):
            raise ValueError("verifier fallback origin semantics are contradictory")
    elif rewrite_accepted is True:
        if (
            verification_action != "accepted_editor_rewrite"
            or fallback_used is not False
            or origin_class != "verifier_editor_rewrite"
        ):
            raise ValueError("accepted editor rewrite is incorrectly classified")
    elif origin_class in {
        "verifier_conservative_fallback",
        "verifier_editor_rewrite",
    }:
        raise ValueError("verifier origin class has no matching verifier action")


@dataclass(frozen=True)
class AgentExecutionRequest:
    """Complete input to one production-core execution.

    ``execution_class`` records why the shared path was invoked; it does not
    alter answer behavior.  The non-claim class is reserved for benchmark
    adapter rehearsals and cannot be promoted to a performance result.
    """

    store: "TraceStore"
    settings: "ServerSettings"
    session_id: str
    message: str
    mode: str
    model_id: str | None
    rag_config: str
    max_tokens: int
    trace_options: Mapping[str, Any] = field(default_factory=dict)
    session_context: Mapping[str, Any] | None = None
    parent_turn_id: str | None = None
    profiler: Any | None = None
    execution_class: str = "product_turn"
    document_retrieval_enabled: bool = True
    graph_retrieval_enabled: bool = True
    schema_version: str = EXECUTION_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_REQUEST_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported execution request schema: {self.schema_version}"
            )
        if self.execution_class not in SUPPORTED_EXECUTION_CLASSES:
            raise ValueError(f"unsupported execution class: {self.execution_class}")
        if self.mode not in SUPPORTED_MODES:
            raise ValueError(f"unsupported production execution mode: {self.mode}")
        if not self.session_id.strip():
            raise ValueError("session_id is required")
        if not self.message.strip():
            raise ValueError("message is required")
        if not self.rag_config.strip():
            raise ValueError("rag_config is required")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be greater than 0")
        if not isinstance(self.document_retrieval_enabled, bool):
            raise TypeError("document_retrieval_enabled must be a bool")
        if not isinstance(self.graph_retrieval_enabled, bool):
            raise TypeError("graph_retrieval_enabled must be a bool")
        if self.mode != "agronomic_rag" and (
            not self.document_retrieval_enabled or not self.graph_retrieval_enabled
        ):
            raise ValueError(
                "retrieval component arms are supported only in agronomic_rag mode"
            )

    @property
    def retrieval_controls(self) -> dict[str, bool]:
        return {
            "document_retrieval_enabled": self.document_retrieval_enabled,
            "graph_retrieval_enabled": self.graph_retrieval_enabled,
        }


def build_execution_stage_receipts(
    observations: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Validate and content-address one complete production stage topology."""

    observed_ids = tuple(observations)
    if observed_ids != EXECUTION_STAGE_IDS:
        missing = [stage_id for stage_id in EXECUTION_STAGE_IDS if stage_id not in observations]
        unknown = [stage_id for stage_id in observations if stage_id not in EXECUTION_STAGE_IDS]
        raise ValueError(
            "execution stage topology mismatch: "
            f"expected={list(EXECUTION_STAGE_IDS)} observed={list(observed_ids)} "
            f"missing={missing} unknown={unknown}"
        )

    receipts: list[dict[str, Any]] = []
    for position, stage_id in enumerate(EXECUTION_STAGE_IDS):
        observation = observations[stage_id]
        state = str(observation.get("state") or "")
        if state not in STAGE_STATES:
            raise ValueError(
                f"stage {stage_id} has unsupported or missing state: {state!r}"
            )
        evidence = observation.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError(f"stage {stage_id} must provide mapping evidence")
        evidence_record = dict(evidence)
        _validate_stage_evidence(stage_id, evidence_record)
        base = {
            "schema_version": EXECUTION_STAGE_RECEIPT_SCHEMA_VERSION,
            "topology_version": EXECUTION_STAGE_TOPOLOGY_VERSION,
            "position": position,
            "stage_id": stage_id,
            "answer_affecting": _ANSWER_AFFECTING_BY_STAGE[stage_id],
            "state": state,
            "evidence": evidence_record,
            "evidence_sha256": stable_sha256(evidence_record),
        }
        receipts.append({**base, "receipt_sha256": stable_sha256(base)})
    _validate_stage_semantics(receipts)
    return tuple(receipts)


def validate_execution_stage_receipts(
    receipts: Any,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(receipts, list):
        raise ValueError("execution stage receipts must be a list")
    if len(receipts) != len(EXECUTION_STAGE_IDS):
        raise ValueError(
            "execution stage receipt count mismatch: "
            f"expected={len(EXECUTION_STAGE_IDS)} observed={len(receipts)}"
        )

    validated: list[dict[str, Any]] = []
    for position, expected_stage_id in enumerate(EXECUTION_STAGE_IDS):
        receipt = receipts[position]
        if not isinstance(receipt, Mapping):
            raise ValueError(f"stage receipt at position {position} must be a mapping")
        record = dict(receipt)
        if record.get("schema_version") != EXECUTION_STAGE_RECEIPT_SCHEMA_VERSION:
            raise ValueError(f"stage {expected_stage_id} has an unsupported receipt schema")
        if record.get("topology_version") != EXECUTION_STAGE_TOPOLOGY_VERSION:
            raise ValueError(f"stage {expected_stage_id} has an unsupported topology version")
        if record.get("position") != position:
            raise ValueError(f"stage {expected_stage_id} has a mismatched position")
        if record.get("stage_id") != expected_stage_id:
            raise ValueError(
                f"execution stage mismatch at {position}: "
                f"expected={expected_stage_id} observed={record.get('stage_id')}"
            )
        if record.get("answer_affecting") is not _ANSWER_AFFECTING_BY_STAGE[
            expected_stage_id
        ]:
            raise ValueError(f"stage {expected_stage_id} has a mismatched effect class")
        if record.get("state") not in STAGE_STATES:
            raise ValueError(f"stage {expected_stage_id} has an invalid state")
        evidence = record.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError(f"stage {expected_stage_id} has invalid evidence")
        _validate_stage_evidence(expected_stage_id, evidence)
        if record.get("evidence_sha256") != stable_sha256(dict(evidence)):
            raise ValueError(f"stage {expected_stage_id} evidence hash mismatch")
        base = {key: value for key, value in record.items() if key != "receipt_sha256"}
        if record.get("receipt_sha256") != stable_sha256(base):
            raise ValueError(f"stage {expected_stage_id} receipt hash mismatch")
        validated.append(record)
    _validate_stage_semantics(validated)
    return tuple(validated)


def validate_retrieval_receipts_for_request(
    request: AgentExecutionRequest,
    receipts: tuple[dict[str, Any], ...],
    *,
    trace: Mapping[str, Any],
) -> None:
    """Reject cross-arm output or receipt contamination before accepting a run.

    A disabled component is required to have both a ``disabled_by_arm`` stage
    receipt and an empty component-specific trace output.  This validation is
    intentionally independent of the context cache implementation so a stale,
    tampered, or incorrectly keyed cache entry cannot become a valid rehearsal.
    """

    receipt_by_id = {str(receipt.get("stage_id") or ""): receipt for receipt in receipts}
    trace_metadata = trace.get("metadata")
    if not isinstance(trace_metadata, Mapping):
        raise ValueError("execution trace metadata is missing")
    workspace_document_count = int(trace_metadata.get("workspace_doc_count") or 0)
    retrieved_docs = trace.get("retrieved_docs")
    if not isinstance(retrieved_docs, list):
        raise ValueError("document_retrieval trace output must be a list")
    if workspace_document_count < 0 or workspace_document_count > len(retrieved_docs):
        raise ValueError("workspace document count is incompatible with retrieval trace")
    document_receipt = next(
        (
            receipt
            for receipt in receipts
            if receipt.get("stage_id") == "document_retrieval"
        ),
        None,
    )
    document_evidence = (
        document_receipt.get("evidence")
        if isinstance(document_receipt, Mapping)
        else None
    )
    if not isinstance(document_evidence, Mapping):
        raise ValueError("document_retrieval stage evidence is missing")
    if document_evidence.get("workspace_document_count") != workspace_document_count:
        raise ValueError("workspace document trace/receipt count mismatch")
    if not request.document_retrieval_enabled and workspace_document_count:
        raise ValueError("document-disabled request contains workspace output contamination")

    components = (
        (
            "document_retrieval",
            request.document_retrieval_enabled,
            retrieved_docs[workspace_document_count:],
            "document_count",
        ),
        (
            "graph_retrieval",
            request.graph_retrieval_enabled,
            trace.get("graph_hits"),
            "graph_hit_count",
        ),
    )
    for stage_id, enabled, raw_outputs, count_key in components:
        if not isinstance(raw_outputs, list):
            raise ValueError(f"{stage_id} trace output must be a list")
        receipt = receipt_by_id.get(stage_id)
        if not isinstance(receipt, Mapping):
            raise ValueError(f"{stage_id} stage receipt is missing")
        evidence = receipt.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError(f"{stage_id} stage evidence is missing")

        state = str(receipt.get("state") or "")
        observed_count = len(raw_outputs)
        receipted_count = evidence.get(count_key)
        if not isinstance(receipted_count, int) or receipted_count != observed_count:
            raise ValueError(
                f"{stage_id} trace/receipt output count mismatch: "
                f"trace={observed_count} receipt={receipted_count!r}"
            )

        if request.mode != "agronomic_rag":
            continue

        # Baseline and deterministic product bypasses remain not-applicable;
        # retrieval-arm invariants apply when a component was explicitly
        # disabled or when an arm-aware governed context was built.
        arm_aware = "enabled" in evidence or state in RETRIEVAL_COMPONENT_STATES
        if not enabled:
            if state != "disabled_by_arm":
                raise ValueError(
                    f"{stage_id} disabled request has incompatible state: {state!r}"
                )
            if observed_count:
                raise ValueError(f"{stage_id} disabled request contains output contamination")
            if evidence.get("enabled") is not False or evidence.get("executed") is not False:
                raise ValueError(f"{stage_id} disabled receipt does not prove non-execution")
        elif arm_aware:
            if state == "not_applicable" and not observed_count:
                if evidence.get("executed") is not False:
                    raise ValueError(
                        f"{stage_id} bypass receipt does not prove non-execution"
                    )
                continue
            expected_state = "completed" if observed_count else "completed_no_result"
            if state != expected_state:
                raise ValueError(
                    f"{stage_id} enabled request has incompatible state: "
                    f"expected={expected_state} observed={state!r}"
                )
            if evidence.get("enabled") is not True or evidence.get("executed") is not True:
                raise ValueError(f"{stage_id} enabled receipt does not prove execution")


def validate_fallback_origin_for_trace(
    receipts: tuple[dict[str, Any], ...],
    *,
    trace: Mapping[str, Any],
    answer_stages: Mapping[str, Any],
) -> None:
    """Bind origin classification to the persisted verifier observation."""

    metadata = trace.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("execution trace metadata is missing")
    raw_verification = metadata.get("answer_verification")
    if raw_verification is not None and not isinstance(raw_verification, Mapping):
        raise ValueError("answer-verification trace record is invalid")
    verification_record = dict(raw_verification or {})
    classification = classify_verification_origin(
        verification_record,
        draft_sha256=str((answer_stages.get("draft") or {}).get("sha256") or ""),
        post_verification_sha256=str(
            (answer_stages.get("post_verification") or {}).get("sha256") or ""
        ),
    )
    origin_receipt = next(
        (receipt for receipt in receipts if receipt.get("stage_id") == "fallback_origin"),
        None,
    )
    if not isinstance(origin_receipt, Mapping):
        raise ValueError("fallback_origin stage receipt is missing")
    origin_evidence = origin_receipt.get("evidence")
    if not isinstance(origin_evidence, Mapping):
        raise ValueError("fallback_origin stage evidence is missing")
    for key, expected in classification.items():
        if origin_evidence.get(key) != expected:
            raise ValueError(
                f"fallback_origin does not match persisted verification: {key}"
            )
    if origin_evidence.get("verification_receipt_sha256") != stable_sha256(
        verification_record
    ):
        raise ValueError(
            "fallback_origin verification hash does not match persisted verification"
        )


def validate_answer_stages(answer_stages: Any, *, final_answer: str) -> dict[str, Any]:
    if not isinstance(answer_stages, Mapping):
        raise ValueError("answer stages are missing")
    record = dict(answer_stages)
    if record.get("schema_version") != "open_agronomy_agent.answer_stages.v1":
        raise ValueError("unsupported answer-stage schema")
    for stage_id in ("draft", "post_verification", "final"):
        stage = record.get(stage_id)
        if not isinstance(stage, Mapping):
            raise ValueError(f"answer stage {stage_id} is missing")
        text = stage.get("text")
        if not isinstance(text, str):
            raise ValueError(f"answer stage {stage_id} text is missing")
        if stage.get("sha256") != text_sha256(text):
            raise ValueError(f"answer stage {stage_id} hash mismatch")
    if record["final"]["text"] != final_answer:
        raise ValueError("final answer does not match the final answer stage")
    return record


@dataclass(frozen=True)
class AgentExecutionResult:
    """Validated result from the shared production execution core."""

    execution_class: str
    turn_id: str
    parent_turn_id: str | None
    answer: str
    answer_stages: Mapping[str, Any]
    stage_receipts: tuple[Mapping[str, Any], ...]
    persistence_receipt: Mapping[str, Any]
    turn: Mapping[str, Any]
    schema_version: str = EXECUTION_RESULT_SCHEMA_VERSION

    @classmethod
    def from_run_turn_payload(
        cls,
        request: AgentExecutionRequest,
        payload: Mapping[str, Any],
    ) -> "AgentExecutionResult":
        turn_id = payload.get("turn_id")
        turn = payload.get("turn")
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("production execution did not return a turn_id")
        if not isinstance(turn, Mapping):
            raise ValueError("production execution did not return a persisted turn")
        if turn.get("turn_id") != turn_id:
            raise ValueError("persisted turn identity mismatch")
        answer = turn.get("answer")
        if not isinstance(answer, str):
            raise ValueError("persisted turn answer is missing")
        trace = turn.get("trace")
        if not isinstance(trace, Mapping):
            raise ValueError("persisted execution trace is missing")
        metadata = trace.get("metadata")
        if not isinstance(metadata, Mapping):
            raise ValueError("persisted execution trace metadata is missing")
        if metadata.get("execution_class") != request.execution_class:
            raise ValueError("persisted execution class mismatch")
        answer_stages = validate_answer_stages(
            metadata.get("answer_stages"),
            final_answer=answer,
        )
        stage_receipts = validate_execution_stage_receipts(
            metadata.get("execution_stage_receipts")
        )
        receipt_by_id = {
            str(receipt["stage_id"]): receipt for receipt in stage_receipts
        }
        if (
            receipt_by_id["draft_generation"]["evidence"]["draft_sha256"]
            != answer_stages["draft"]["sha256"]
        ):
            raise ValueError("draft-generation receipt does not match answer stages")
        if (
            receipt_by_id["verification"]["evidence"][
                "post_verification_sha256"
            ]
            != answer_stages["post_verification"]["sha256"]
        ):
            raise ValueError("verification receipt does not match answer stages")
        if (
            receipt_by_id["structured_rendering"]["evidence"]["final_sha256"]
            != answer_stages["final"]["sha256"]
        ):
            raise ValueError("structured-rendering receipt does not match answer stages")
        validate_retrieval_receipts_for_request(
            request,
            stage_receipts,
            trace=trace,
        )
        validate_fallback_origin_for_trace(
            stage_receipts,
            trace=trace,
            answer_stages=answer_stages,
        )
        persistence_evidence = {
            "stored": True,
            "turn_id": turn_id,
            "session_id": request.session_id,
        }
        persistence_receipt = {
            "schema_version": "open_agronomy_agent.persistence_receipt.v1",
            **persistence_evidence,
            "receipt_sha256": stable_sha256(persistence_evidence),
        }
        return cls(
            execution_class=request.execution_class,
            turn_id=turn_id,
            parent_turn_id=payload.get("parent_turn_id"),
            answer=answer,
            answer_stages=answer_stages,
            stage_receipts=stage_receipts,
            persistence_receipt=persistence_receipt,
            turn=dict(turn),
        )

    def to_run_turn_payload(self) -> dict[str, Any]:
        """Preserve the historical server response shape."""

        return {
            "turn_id": self.turn_id,
            "parent_turn_id": self.parent_turn_id,
            "turn": dict(self.turn),
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "execution_class": self.execution_class,
            "turn_id": self.turn_id,
            "parent_turn_id": self.parent_turn_id,
            "answer": self.answer,
            "answer_stages": dict(self.answer_stages),
            "stage_receipts": [dict(receipt) for receipt in self.stage_receipts],
            "persistence_receipt": dict(self.persistence_receipt),
            "turn": dict(self.turn),
        }


__all__ = [
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "EXECUTION_REQUEST_SCHEMA_VERSION",
    "EXECUTION_RESULT_SCHEMA_VERSION",
    "EXECUTION_STAGE_IDS",
    "EXECUTION_STAGE_REQUIRED_EVIDENCE_KEYS",
    "EXECUTION_STAGE_RECEIPT_SCHEMA_VERSION",
    "EXECUTION_STAGE_SPECS",
    "EXECUTION_STAGE_TOPOLOGY_VERSION",
    "RETRIEVAL_COMPONENT_STATES",
    "build_execution_stage_receipts",
    "classify_verification_origin",
    "stable_sha256",
    "validate_answer_stages",
    "validate_execution_stage_receipts",
    "validate_fallback_origin_for_trace",
    "validate_retrieval_receipts_for_request",
]
