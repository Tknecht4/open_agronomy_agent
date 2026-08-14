from __future__ import annotations

from copy import deepcopy

import pytest

from agronomy_agent.benchmark_rehearsal import (
    ObservedSystemBenchmarkAdapter,
    PRODUCTION_FULL_COMPONENTS,
    PRODUCTION_FULL_CONFIGURATION_ID,
    RETRIEVAL_COMPONENT_CONFIGURATIONS,
)
from agronomy_agent.execution_core import (
    AgentExecutionRequest,
    AgentExecutionResult,
    EXECUTION_STAGE_IDS,
    EXECUTION_STAGE_TOPOLOGY_VERSION,
    build_execution_stage_receipts,
    stable_sha256,
)
from agronomy_agent.server.services.chat_service import execute_agent_request, run_turn
from agronomy_agent.server.settings import build_settings
from agronomy_agent.server.storage.db import TraceStore


QUESTION = "Convert a fertilizer rate of 100 lb/ac to kg/ha."
RETRIEVAL_QUESTION = "How does soybean iron deficiency chlorosis relate to soil pH?"


def _runtime(tmp_path, name: str):  # noqa: ANN001, ANN202
    database_path = tmp_path / f"{name}.sqlite3"
    store = TraceStore(database_path)
    session = store.create_session(name, {}, {})
    settings = build_settings(
        db_path=database_path,
        artifact_root=tmp_path / f"{name}_artifacts",
        model_config_path="configs/model_gemma4_e2b_interface_v2.yaml",
        default_rag_config="configs/rag_final_mvp.yaml",
        network_mode="offline",
    )
    return store, session, settings


def _nonclaim_request(
    tmp_path,  # noqa: ANN001
    name: str = "adapter",
    *,
    question: str = QUESTION,
    model_id: str = "mock",
    document_retrieval_enabled: bool = True,
    graph_retrieval_enabled: bool = True,
) -> AgentExecutionRequest:
    store, session, settings = _runtime(tmp_path, name)
    return AgentExecutionRequest(
        store=store,
        settings=settings,
        session_id=session["session_id"],
        message=question,
        mode="agronomic_rag",
        model_id=model_id,
        rag_config="configs/rag_final_mvp.yaml",
        max_tokens=100,
        trace_options={
            "store_prompt_messages": False,
            "store_retrieved_text": False,
        },
        execution_class="observed_system_execution_nonclaim",
        document_retrieval_enabled=document_retrieval_enabled,
        graph_retrieval_enabled=graph_retrieval_enabled,
    )


def test_cockpit_and_nonclaim_adapter_share_the_production_stage_receipts(tmp_path) -> None:  # noqa: ANN001
    product_store, product_session, settings = _runtime(tmp_path, "product")
    product_payload = run_turn(
        store=product_store,
        settings=settings,
        session_id=product_session["session_id"],
        message=QUESTION,
        mode="agronomic_rag",
        model_id="mock",
        rag_config="configs/rag_final_mvp.yaml",
        max_tokens=100,
        trace_options={
            "store_prompt_messages": False,
            "store_retrieved_text": False,
        },
    )
    adapter_result = ObservedSystemBenchmarkAdapter().execute(
        _nonclaim_request(tmp_path)
    )

    product_trace = product_payload["turn"]["trace"]
    adapter_trace = adapter_result.execution.turn["trace"]
    product_receipts = product_trace["metadata"]["execution_stage_receipts"]
    adapter_receipts = adapter_trace["metadata"]["execution_stage_receipts"]

    assert product_payload["turn"]["answer"] == adapter_result.execution.answer
    assert product_receipts == adapter_receipts
    assert [receipt["stage_id"] for receipt in product_receipts] == list(
        EXECUTION_STAGE_IDS
    )
    assert product_trace["metadata"]["execution_class"] == "product_turn"
    assert adapter_trace["metadata"]["execution_class"] == (
        "observed_system_execution_nonclaim"
    )
    assert adapter_result.claim_eligible is False
    assert adapter_result.result_class == "observed_system_execution_nonclaim"


def test_nonclaim_adapter_retains_all_answer_stages_and_persistence(tmp_path) -> None:  # noqa: ANN001
    result = ObservedSystemBenchmarkAdapter().execute(
        _nonclaim_request(tmp_path, "retained")
    )
    record = result.to_dict()

    assert record["claim_eligible"] is False
    assert record["component_configuration"]["configuration_id"] == (
        PRODUCTION_FULL_CONFIGURATION_ID
    )
    assert record["component_configuration"]["components"] == PRODUCTION_FULL_COMPONENTS
    assert record["execution"]["answer_stages"]["final"]["text"] == (
        record["execution"]["answer"]
    )
    assert record["execution"]["persistence_receipt"]["stored"] is True
    assert record["execution"]["turn"]["metadata"]["generated_with"] == (
        "observed_system_execution_nonclaim"
    )


def test_nonclaim_adapter_rejects_components_that_do_not_match_named_arm(tmp_path) -> None:  # noqa: ANN001
    components = dict(PRODUCTION_FULL_COMPONENTS)
    components["graph_retrieval"] = False

    with pytest.raises(ValueError, match="does not match the named retrieval"):
        ObservedSystemBenchmarkAdapter().execute(
            _nonclaim_request(tmp_path, "ablation"),
            components=components,
        )


@pytest.mark.parametrize(
    ("configuration_id", "document_enabled", "graph_enabled"),
    [
        ("retrieval_neither", False, False),
        ("retrieval_document_only", True, False),
        ("retrieval_graph_only", False, True),
        ("retrieval_both", True, True),
    ],
)
def test_nonclaim_adapter_executes_the_four_receipted_retrieval_arms(
    tmp_path,  # noqa: ANN001
    configuration_id: str,
    document_enabled: bool,
    graph_enabled: bool,
) -> None:
    result = ObservedSystemBenchmarkAdapter().execute(
        _nonclaim_request(
            tmp_path,
            configuration_id,
            question=RETRIEVAL_QUESTION,
            document_retrieval_enabled=document_enabled,
            graph_retrieval_enabled=graph_enabled,
        ),
        component_configuration_id=configuration_id,
    )
    record = result.to_dict()
    receipts = {
        row["stage_id"]: row for row in record["execution"]["stage_receipts"]
    }
    document_outputs = record["execution"]["turn"]["trace"]["retrieved_docs"]
    graph_outputs = record["execution"]["turn"]["trace"]["graph_hits"]

    assert record["component_configuration"] == {
        "configuration_id": configuration_id,
        "components": RETRIEVAL_COMPONENT_CONFIGURATIONS[configuration_id],
    }
    assert bool(document_outputs) is document_enabled
    assert bool(graph_outputs) is graph_enabled
    assert receipts["document_retrieval"]["state"] == (
        "completed" if document_enabled else "disabled_by_arm"
    )
    assert receipts["graph_retrieval"]["state"] == (
        "completed" if graph_enabled else "disabled_by_arm"
    )
    assert receipts["document_retrieval"]["evidence"]["document_ids"] == [
        row["doc_id"] for row in document_outputs
    ]
    assert receipts["graph_retrieval"]["evidence"]["graph_node_ids"] == [
        row["node_id"] for row in graph_outputs
    ]


@pytest.mark.parametrize(
    ("configuration_id", "document_enabled", "graph_enabled"),
    [
        ("retrieval_neither", False, False),
        ("retrieval_document_only", True, False),
        ("retrieval_graph_only", False, True),
        ("retrieval_both", True, True),
    ],
)
def test_retrieval_adapter_matches_direct_shared_core_execution(
    tmp_path,  # noqa: ANN001
    configuration_id: str,
    document_enabled: bool,
    graph_enabled: bool,
) -> None:
    direct = execute_agent_request(
        _nonclaim_request(
            tmp_path,
            f"direct_{configuration_id}",
            question=RETRIEVAL_QUESTION,
            document_retrieval_enabled=document_enabled,
            graph_retrieval_enabled=graph_enabled,
        )
    )
    adapted = ObservedSystemBenchmarkAdapter().execute(
        _nonclaim_request(
            tmp_path,
            f"adapted_{configuration_id}",
            question=RETRIEVAL_QUESTION,
            document_retrieval_enabled=document_enabled,
            graph_retrieval_enabled=graph_enabled,
        ),
        component_configuration_id=configuration_id,
    ).execution

    assert adapted.answer == direct.answer
    assert adapted.answer_stages == direct.answer_stages
    assert adapted.stage_receipts == direct.stage_receipts


def test_nonclaim_adapter_keeps_non_retrieval_toggles_unsupported(tmp_path) -> None:  # noqa: ANN001
    components = dict(RETRIEVAL_COMPONENT_CONFIGURATIONS["retrieval_both"])
    components["tool_execution"] = False

    with pytest.raises(ValueError, match="non-retrieval component toggles: tool_execution"):
        ObservedSystemBenchmarkAdapter().execute(
            _nonclaim_request(tmp_path, "unsupported_stage"),
            component_configuration_id="retrieval_both",
            components=components,
        )


def test_disabled_retrieval_trace_contamination_is_rejected(tmp_path) -> None:  # noqa: ANN001
    request = _nonclaim_request(
        tmp_path,
        "disabled_contamination",
        question=RETRIEVAL_QUESTION,
        document_retrieval_enabled=False,
        graph_retrieval_enabled=False,
    )
    execution = ObservedSystemBenchmarkAdapter().execute(
        request,
        component_configuration_id="retrieval_neither",
    ).execution
    payload = deepcopy(execution.to_run_turn_payload())
    payload["turn"]["trace"]["retrieved_docs"].append({"doc_id": "stale-doc"})

    with pytest.raises(ValueError, match="trace/receipt output count mismatch"):
        AgentExecutionResult.from_run_turn_payload(request, payload)

    disguised_as_workspace = deepcopy(execution.to_run_turn_payload())
    disguised_as_workspace["turn"]["trace"]["retrieved_docs"].append(
        {"doc_id": "stale-workspace-doc"}
    )
    disguised_as_workspace["turn"]["trace"]["metadata"][
        "workspace_doc_count"
    ] = 1
    with pytest.raises(ValueError, match="workspace document trace/receipt count mismatch"):
        AgentExecutionResult.from_run_turn_payload(request, disguised_as_workspace)


def test_execution_result_fails_closed_on_missing_or_tampered_stage_receipts(tmp_path) -> None:  # noqa: ANN001
    request = _nonclaim_request(tmp_path, "tamper")
    execution = ObservedSystemBenchmarkAdapter().execute(request).execution
    payload = execution.to_run_turn_payload()

    missing = deepcopy(payload)
    missing["turn"]["trace"]["metadata"]["execution_stage_receipts"].pop()
    with pytest.raises(ValueError, match="receipt count mismatch"):
        AgentExecutionResult.from_run_turn_payload(request, missing)

    tampered = deepcopy(payload)
    tampered["turn"]["trace"]["metadata"]["execution_stage_receipts"][0][
        "evidence"
    ]["risk_level"] = "tampered"
    with pytest.raises(ValueError, match="evidence hash mismatch"):
        AgentExecutionResult.from_run_turn_payload(request, tampered)


def test_stage_builder_rejects_missing_unknown_and_reordered_topology(tmp_path) -> None:  # noqa: ANN001
    execution = ObservedSystemBenchmarkAdapter().execute(
        _nonclaim_request(tmp_path, "stage_topology_adversarial")
    ).execution
    observations = {
        str(receipt["stage_id"]): {
            "state": receipt["state"],
            "evidence": deepcopy(receipt["evidence"]),
        }
        for receipt in execution.stage_receipts
    }

    missing = dict(observations)
    missing.pop("fallback_origin")
    with pytest.raises(ValueError, match=r"missing=\['fallback_origin'\]"):
        build_execution_stage_receipts(missing)

    unknown = dict(observations)
    unknown["unknown_answer_stage"] = deepcopy(observations["fallback_origin"])
    with pytest.raises(ValueError, match=r"unknown=\['unknown_answer_stage'\]"):
        build_execution_stage_receipts(unknown)

    reordered = dict(reversed(list(observations.items())))
    with pytest.raises(ValueError, match="execution stage topology mismatch"):
        build_execution_stage_receipts(reordered)


def test_stage_builder_rejects_semantically_empty_evidence_even_if_mapping_exists(
    tmp_path,  # noqa: ANN001
) -> None:
    execution = ObservedSystemBenchmarkAdapter().execute(
        _nonclaim_request(tmp_path, "stage_evidence_adversarial")
    ).execution
    observations = {
        str(receipt["stage_id"]): {
            "state": receipt["state"],
            "evidence": deepcopy(receipt["evidence"]),
        }
        for receipt in execution.stage_receipts
    }
    observations["evidence_selection_packing"]["evidence"] = {}

    with pytest.raises(
        ValueError,
        match="evidence_selection_packing evidence is missing required keys",
    ):
        build_execution_stage_receipts(observations)

    contradictory = {
        str(receipt["stage_id"]): {
            "state": receipt["state"],
            "evidence": deepcopy(receipt["evidence"]),
        }
        for receipt in execution.stage_receipts
    }
    contradictory["safety_normalization"]["evidence"]["input_sha256"] = "0" * 64
    with pytest.raises(
        ValueError,
        match="execution stage hash continuity mismatch: verification_to_safety",
    ):
        build_execution_stage_receipts(contradictory)


def test_observed_adapter_capabilities_bind_exact_shared_stage_contract() -> None:
    capabilities = ObservedSystemBenchmarkAdapter().harness_capabilities()

    assert capabilities["stage_topology_version"] == EXECUTION_STAGE_TOPOLOGY_VERSION
    assert capabilities["stage_topology"] == list(EXECUTION_STAGE_IDS)
    assert list(PRODUCTION_FULL_COMPONENTS) == list(EXECUTION_STAGE_IDS)


class _FakeGenerator:
    model_id = "fake-local-model"
    last_generation_stats = None

    def generate(self, messages):  # noqa: ANN001, ANN201
        del messages
        return "Model draft that requires verifier intervention."


class _DraftAssessment:
    reasons = ("unsupported_named_condition",)


class _VerificationOutcome:
    def __init__(
        self,
        *,
        answer: str,
        rewrite_accepted: bool,
        fallback_applied: bool,
    ) -> None:
        self.answer = answer
        self.triggered = True
        self.rewrite_accepted = rewrite_accepted
        self.fallback_applied = fallback_applied
        self.draft_assessment = _DraftAssessment()

    def as_record(self) -> dict[str, object]:
        return {
            "selection_policy": "hard_safety_then_specificity_v2",
            "intervention_action": (
                "accept_rewrite"
                if self.rewrite_accepted
                else "fallback_or_degraded"
            ),
            "triggered": True,
            "rewrite_accepted": self.rewrite_accepted,
            "fallback_applied": self.fallback_applied,
            "rejection_reasons": (
                [] if self.rewrite_accepted else ["deterministic_test_fallback"]
            ),
            "replacement_audit": {
                "schema_version": "open_agronomy_agent.verifier_replacement_audit.v1",
                "failed_rule_ids": ["test.rule"],
            },
        }


def _install_fake_model_and_verifier(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rewrite_accepted: bool,
    fallback_applied: bool,
    answer: str,
) -> None:
    monkeypatch.setattr(
        "agronomy_agent.server.services.chat_service._build_mlx_generator",
        lambda *args, **kwargs: _FakeGenerator(),
    )
    monkeypatch.setattr(
        "agronomy_agent.server.services.chat_service.verify_answer",
        lambda *args, **kwargs: _VerificationOutcome(
            answer=answer,
            rewrite_accepted=rewrite_accepted,
            fallback_applied=fallback_applied,
        ),
    )


def test_verifier_fallback_origin_is_content_linked_and_adapter_equivalent(
    tmp_path,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_model_and_verifier(
        monkeypatch,
        rewrite_accepted=False,
        fallback_applied=True,
        answer="Conservative deterministic verifier fallback.",
    )
    direct = execute_agent_request(
        _nonclaim_request(
            tmp_path,
            "verifier_fallback_direct",
            question=RETRIEVAL_QUESTION,
            model_id="fake-local-model",
        )
    )
    adapted = ObservedSystemBenchmarkAdapter().execute(
        _nonclaim_request(
            tmp_path,
            "verifier_fallback_adapter",
            question=RETRIEVAL_QUESTION,
            model_id="fake-local-model",
        )
    ).execution

    assert adapted.answer == direct.answer
    assert adapted.answer_stages == direct.answer_stages
    assert adapted.stage_receipts == direct.stage_receipts
    receipts = {row["stage_id"]: row for row in adapted.stage_receipts}
    verification = receipts["verification"]
    origin = receipts["fallback_origin"]["evidence"]
    assert verification["state"] == "executed"
    assert origin["origin_class"] == "verifier_conservative_fallback"
    assert origin["fallback_used"] is True
    assert origin["verification_action"] == "conservative_fallback"
    assert origin["verification_fallback_applied"] is True
    assert origin["rewrite_accepted"] is False
    assert origin["replacement_used"] is True
    assert origin["draft_sha256"] == adapted.answer_stages["draft"]["sha256"]
    assert origin["post_verification_sha256"] == (
        adapted.answer_stages["post_verification"]["sha256"]
    )
    assert origin["verification_receipt_sha256"] == (
        verification["evidence"]["adjudication_sha256"]
    )
    assert origin["origin_sha256"] == stable_sha256(origin["origin_record"])


def test_accepted_verifier_editor_rewrite_is_not_classified_as_fallback(
    tmp_path,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_model_and_verifier(
        monkeypatch,
        rewrite_accepted=True,
        fallback_applied=False,
        answer="Accepted evidence-editor rewrite.",
    )
    execution = ObservedSystemBenchmarkAdapter().execute(
        _nonclaim_request(
            tmp_path,
            "verifier_editor_rewrite",
            question=RETRIEVAL_QUESTION,
            model_id="fake-local-model",
        )
    ).execution
    origin = next(
        row["evidence"]
        for row in execution.stage_receipts
        if row["stage_id"] == "fallback_origin"
    )

    assert origin["origin_class"] == "verifier_editor_rewrite"
    assert origin["verification_action"] == "accepted_editor_rewrite"
    assert origin["rewrite_accepted"] is True
    assert origin["replacement_used"] is True
    assert origin["fallback_used"] is False


def test_forged_editor_origin_cannot_hide_persisted_verifier_fallback(
    tmp_path,  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_model_and_verifier(
        monkeypatch,
        rewrite_accepted=False,
        fallback_applied=True,
        answer="Conservative deterministic verifier fallback.",
    )
    request = _nonclaim_request(
        tmp_path,
        "verifier_origin_tamper",
        question=RETRIEVAL_QUESTION,
        model_id="fake-local-model",
    )
    execution = ObservedSystemBenchmarkAdapter().execute(request).execution
    payload = deepcopy(execution.to_run_turn_payload())
    receipts = payload["turn"]["trace"]["metadata"]["execution_stage_receipts"]
    origin_receipt = next(
        row for row in receipts if row["stage_id"] == "fallback_origin"
    )
    evidence = origin_receipt["evidence"]
    evidence.update(
        {
            "origin_class": "verifier_editor_rewrite",
            "fallback_used": False,
            "fallback_kind": None,
            "verification_action": "accepted_editor_rewrite",
            "verification_fallback_applied": False,
            "rewrite_accepted": True,
        }
    )
    evidence["origin_record"].update(
        {
            "origin_class": "verifier_editor_rewrite",
            "fallback_used": False,
            "fallback_kind": None,
            "verification_action": "accepted_editor_rewrite",
            "verification_fallback_applied": False,
            "rewrite_accepted": True,
        }
    )
    evidence["origin_sha256"] = stable_sha256(evidence["origin_record"])
    origin_receipt["evidence_sha256"] = stable_sha256(evidence)
    origin_receipt["receipt_sha256"] = stable_sha256(
        {
            key: value
            for key, value in origin_receipt.items()
            if key != "receipt_sha256"
        }
    )

    with pytest.raises(
        ValueError,
        match="fallback_origin does not match persisted verification: verification_action",
    ):
        AgentExecutionResult.from_run_turn_payload(request, payload)


def test_execution_request_rejects_unknown_modes_before_side_effects(tmp_path) -> None:  # noqa: ANN001
    store, session, settings = _runtime(tmp_path, "bad_mode")
    with pytest.raises(ValueError, match="unsupported production execution mode"):
        AgentExecutionRequest(
            store=store,
            settings=settings,
            session_id=session["session_id"],
            message=QUESTION,
            mode="raw_model",
            model_id="mock",
            rag_config="configs/rag_final_mvp.yaml",
            max_tokens=100,
            execution_class="observed_system_execution_nonclaim",
        )
