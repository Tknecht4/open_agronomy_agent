from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agronomy_agent.agent import (
    _benchmark_document_egress_records,
    benchmark_rendered_field_context_fragment,
    build_benchmark_egress_artifact_contract,
    build_benchmark_candidate_application_messages,
    generate_answer,
    load_agent_resources,
)
from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.codex_app_server import (
    AppServerResult,
    BENCHMARK_EGRESS_ARTIFACT_CONTRACT_SCHEMA,
    BENCHMARK_EGRESS_AUTHORIZATION_SCHEMA,
    BENCHMARK_EGRESS_AUTHORIZED_PAYLOAD_CLASSES,
    BENCHMARK_EGRESS_ENVELOPE_SCHEMA,
    BENCHMARK_EGRESS_FORBIDDEN_PAYLOAD_CLASSES,
    BENCHMARK_EGRESS_PAYLOAD_CLASSES_BY_PHASE_AND_ARM,
    BENCHMARK_EGRESS_SUITE_CASE_CONTRACT_SCHEMA,
    BENCHMARK_EGRESS_STATIC_PROMPT_CONTRACT_SCHEMA,
    DEFAULT_APP_SERVER_COMMAND,
    CodexAppServerError,
    CodexAppServerClient,
    CodexAppServerGenerator,
    TEXT_ONLY_BENCHMARK_CONTROL,
    build_benchmark_static_prompt_contract,
    load_benchmark_egress_authorization,
)
from agronomy_agent.context_packer import format_user_field_context
from agronomy_agent.answer_verifier import build_evidence_editor_messages


_EVAL_ID = "fixture-eval"
_MODEL_CONFIG_SHA256 = hashlib.sha256(b"model-config").hexdigest()
_DOC_SOURCE_TEXT = "Nitrogen recommendations depend on a current soil test."
_GRAPH_SOURCE_TEXT = "Graph evidence."


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_map() -> dict[str, dict[str, list[str]]]:
    return {
        phase: {arm: list(classes) for arm, classes in arms.items()}
        for phase, arms in BENCHMARK_EGRESS_PAYLOAD_CLASSES_BY_PHASE_AND_ARM.items()
    }


def _write_authorization(
    tmp_path: Path,
    *,
    suite_case_contract_sha256: str,
    egress_artifact_contract_sha256: str,
    static_prompt_contract_sha256: str,
    **overrides: Any,
) -> tuple[Path, str, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC)
    benchmark_id = "fixture-benchmark"
    suite_sha256 = _digest("suite")
    payload = {
        "schema_version": BENCHMARK_EGRESS_AUTHORIZATION_SCHEMA,
        "authorization_decision": "authorized",
        "benchmark_id": benchmark_id,
        "benchmark_suite_sha256": suite_sha256,
        "suite_case_contract_sha256": suite_case_contract_sha256,
        "egress_artifact_contract_sha256": egress_artifact_contract_sha256,
        "static_prompt_contract_sha256": static_prompt_contract_sha256,
        "recipient_backend": "codex_app_server_chatgpt_auth",
        "model_id": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "model_config_sha256": _MODEL_CONFIG_SHA256,
        "authorization_source": "human-release-authority-20260814",
        "authorized_by_key_id": "benchmark-authority-key-7",
        "authorized_at": (now - dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        "authorized_payload_classes": list(BENCHMARK_EGRESS_AUTHORIZED_PAYLOAD_CLASSES),
        "excluded_payload_classes": list(BENCHMARK_EGRESS_FORBIDDEN_PAYLOAD_CLASSES),
        "payload_classes_by_phase_and_arm": _payload_map(),
    }
    payload.update(overrides)
    path = tmp_path / "egress.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, benchmark_id, suite_sha256


def _artifact_contract(
    *,
    document_text: str = _DOC_SOURCE_TEXT,
    document_title: str = "Nitrogen rate guidance",
) -> dict[str, Any]:
    document_identity = {
        "doc_id": "soil_fertility_n_rate",
        "source_id": "seed agronomy synthesis",
        "source_document_sha256": _digest("full seed source document"),
        "source_text_sha256": _digest(document_text),
    }
    document_identity_sha256 = _digest(_canonical(document_identity))
    node_identity = {
        "node_id": "nitrogen_node",
        "name": "nitrogen",
        "kind": "concept",
        "evidence_sha256": _digest(_GRAPH_SOURCE_TEXT),
    }
    node_identity_sha256 = _digest(_canonical(node_identity))
    payload = {
        "schema_version": BENCHMARK_EGRESS_ARTIFACT_CONTRACT_SCHEMA,
        "public_repository_manifest_sha256": _digest("public-manifest"),
        "runtime_policy_sha256": _digest("runtime-policy"),
        "rag_config_sha256": _digest("rag-config"),
        "corpus_bundle_sha256": _digest("corpus-bundle"),
        "allowed_corpora": {
            _digest("data/seed/agronomy_rag_corpus.jsonl"): {
                "artifact_sha256": _digest("seed-corpus-bytes"),
                "policy_entry_sha256": _digest("seed-policy-entry"),
                "public_manifest_match_sha256": _digest("seed-public-manifest-entry"),
                "policy_rights_status": "project_authored",
                "runtime_eligibility": "context_only",
                "allowed_documents": {
                    document_identity_sha256: {
                        **document_identity,
                        "title": document_title,
                        "source": "seed agronomy synthesis",
                        "row_sha256": _digest("seed-document-row"),
                    }
                },
            }
        },
        "allowed_graphs": {
            _digest("seed-graph-bytes"): {
                "graph_id": "open_agronomy.curated_seed",
                "version": "1.0.0",
                "source_sha256": _digest("Open Agronomy Agent curated seed graph"),
                "license": "Apache-2.0",
                "public_manifest_match_sha256": _digest("seed-graph-public-manifest-entry"),
                "allowed_nodes": {
                    node_identity_sha256: {
                        **node_identity,
                        "node_row_sha256": _digest("seed-graph-node-row"),
                    }
                },
            }
        },
    }
    payload["sha256"] = _digest(_canonical(payload))
    return payload


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, **_: Any) -> None:
        self.protocol_identity = {"fixture": True}
        self.catalog_model = {"id": "gpt-5.6-luna"}
        self.calls: list[dict[str, Any]] = []
        self.instances.append(self)

    def generate(
        self,
        *,
        user_text: str,
        base_instructions: str,
        output_schema: dict[str, Any] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AppServerResult:
        self.calls.append(
            {
                "user_text": user_text,
                "base_instructions": base_instructions,
                "output_schema": output_schema,
                "metadata": metadata,
            }
        )
        controlled = (
            f"{TEXT_ONLY_BENCHMARK_CONTROL}\n\n{base_instructions.strip()}"
            if base_instructions.strip()
            else TEXT_ONLY_BENCHMARK_CONTROL
        )
        return AppServerResult(
            text=str(getattr(self, "response_text", "bounded answer")),
            receipt={
                "selected_model": "gpt-5.6-luna",
                "input_sha256": _digest(user_text),
                "base_instructions_sha256": _digest(controlled),
                "token_usage": {"last": {"inputTokens": 10, "outputTokens": 4}},
                "elapsed_ms": 1.25,
            },
        )

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.instances.clear()
    monkeypatch.setattr("agronomy_agent.codex_app_server.CodexAppServerClient", _FakeClient)


def _generator(
    tmp_path: Path,
    *,
    phase: str = "candidate_generation",
    arm: str = "agronomic_rag",
    artifact_contract: dict[str, Any] | None = None,
    question: str = "What should I check?",
    field_values: dict[str, Any] | None = None,
    messages: list[dict[str, str]] | None = None,
    rag_resources: Any | None = None,
) -> CodexAppServerGenerator:
    artifact = artifact_contract or _artifact_contract()
    static_prompt = build_benchmark_static_prompt_contract()
    suite_sha256 = _digest("suite")
    if messages is None and phase == "candidate_generation":
        messages = build_benchmark_candidate_application_messages(
            question,
            arm,
            resources=rag_resources if arm == "agronomic_rag" else None,
            field_context=field_values,
        )
    suite_case_contract = _suite_case_contract(
        suite_sha256,
        question=question,
        field_values=field_values,
        arm=arm,
        messages=messages,
    )
    authorization, benchmark_id, _ = _write_authorization(
        tmp_path,
        suite_case_contract_sha256=suite_case_contract["sha256"],
        egress_artifact_contract_sha256=artifact["sha256"],
        static_prompt_contract_sha256=static_prompt["sha256"],
    )
    return CodexAppServerGenerator(
        model_id="gpt-5.6-luna",
        egress_authorization=authorization,
        benchmark_id=benchmark_id,
        benchmark_suite_sha256=suite_sha256,
        model_config_sha256=_MODEL_CONFIG_SHA256,
        egress_phase=phase,
        benchmark_arm=arm,
        egress_artifact_contract=artifact,
        suite_case_contract=suite_case_contract,
        static_prompt_contract=static_prompt,
    )


def _suite_case_contract(
    suite_sha256: str,
    *,
    question: str,
    field_values: dict[str, Any] | None = None,
    arm: str = "agronomic_rag",
    messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    values = dict(field_values or {})
    default_messages = [{"role": "user", "content": question}]
    message_hashes = {
        value: _digest(_canonical(default_messages))
        for value in ("raw_model", "baseline", "kernel_field_context", "agronomic_rag")
    }
    if messages is not None:
        message_hashes[arm] = _digest(_canonical(messages))
    rendered_field_hashes = {
        value: None
        for value in ("raw_model", "baseline", "kernel_field_context", "agronomic_rag")
    }
    if messages is not None:
        rendered = benchmark_rendered_field_context_fragment(messages)
        rendered_field_hashes[arm] = _digest(rendered) if rendered else None
    payload: dict[str, Any] = {
        "schema_version": BENCHMARK_EGRESS_SUITE_CASE_CONTRACT_SCHEMA,
        "benchmark_suite_sha256": suite_sha256,
        "cases": {
            _EVAL_ID: {
                "question_sha256": _digest(question),
                "safe_field_context_present": bool(values),
                "safe_field_context_sha256": _digest(_canonical(values)) if values else None,
                "rendered_field_context_sha256_by_arm": rendered_field_hashes,
                "candidate_application_messages_sha256_by_arm": message_hashes,
            }
        },
    }
    payload["sha256"] = _digest(_canonical(payload))
    return payload


def _document(fragment: str) -> dict[str, Any]:
    contract = _artifact_contract()
    path_sha = _digest("data/seed/agronomy_rag_corpus.jsonl")
    expected = contract["allowed_corpora"][path_sha]
    identity = {
        "doc_id": "soil_fertility_n_rate",
        "source_id": "seed agronomy synthesis",
        "source_document_sha256": _digest("full seed source document"),
        "source_text_sha256": _digest(_DOC_SOURCE_TEXT),
    }
    identity_sha256 = _digest(_canonical(identity))
    member = expected["allowed_documents"][identity_sha256]
    return {
        "doc_id": "soil_fertility_n_rate",
        "source_id": "seed agronomy synthesis",
        "title": member["title"],
        "source": member["source"],
        "document_identity_sha256": identity_sha256,
        "document_row_sha256": member["row_sha256"],
        "source_text": _DOC_SOURCE_TEXT,
        "source_text_sha256": _digest(_DOC_SOURCE_TEXT),
        "source_text_fragment": _DOC_SOURCE_TEXT,
        "source_text_fragment_sha256": _digest(_DOC_SOURCE_TEXT),
        "content_fragment": fragment,
        "content_sha256": _digest(fragment),
        "source_document_sha256": _digest("full seed source document"),
        "corpus_artifact_sha256": expected["artifact_sha256"],
        "corpus_path_sha256": path_sha,
        "policy_entry_sha256": expected["policy_entry_sha256"],
        "public_manifest_match_sha256": expected["public_manifest_match_sha256"],
        "policy_rights_status": expected["policy_rights_status"],
        "runtime_eligibility": expected["runtime_eligibility"],
        "excerpt_chars": len(fragment),
    }


def _graph(fragment: str) -> dict[str, Any]:
    graph_sha = _digest("seed-graph-bytes")
    expected = _artifact_contract()["allowed_graphs"][graph_sha]
    identity = {
        "node_id": "nitrogen_node",
        "name": "nitrogen",
        "kind": "concept",
        "evidence_sha256": _digest(_GRAPH_SOURCE_TEXT),
    }
    identity_sha256 = _digest(_canonical(identity))
    member = expected["allowed_nodes"][identity_sha256]
    return {
        "graph_id": expected["graph_id"],
        "graph_version": expected["version"],
        "graph_sha256": graph_sha,
        "source_sha256": expected["source_sha256"],
        "license": expected["license"],
        "public_manifest_match_sha256": expected["public_manifest_match_sha256"],
        "node_id": identity["node_id"],
        "node_name": identity["name"],
        "node_kind": identity["kind"],
        "node_identity_sha256": identity_sha256,
        "node_row_sha256": member["node_row_sha256"],
        "node_evidence_text": _GRAPH_SOURCE_TEXT,
        "node_evidence_text_sha256": _digest(_GRAPH_SOURCE_TEXT),
        "node_evidence_fragment": _GRAPH_SOURCE_TEXT,
        "node_evidence_fragment_sha256": _digest(_GRAPH_SOURCE_TEXT),
        "evidence_fragment": fragment,
        "evidence_sha256": _digest(fragment),
    }


def _tool(fragment: str) -> dict[str, Any]:
    question = "What should I check?"
    invocation_seed = {
        "planner_version": "open_agronomy_agent.tool_planner.v1",
        "tool_id": "agronomic_calculator",
        "tool_version": "agronomic_calculator_v1",
        "operation": "unit_conversion",
        "inputs": {"value": 1.0},
        "question_sha256": _digest(question),
    }


def _verifier_messages(
    question: str = "What should I check?",
    draft: str = "Earlier draft claimed a fixed rate.",
    evidence: str | None = None,
) -> list[dict[str, str]]:
    return build_evidence_editor_messages(
        draft=draft,
        question=question,
        question_type="general",
        evidence_text=evidence or question,
        failed_claims=(draft,),
        forbidden_terms=(),
        missing_intent_facets=(),
        missing_evidence_terms=(),
        max_words=max(60, min(160, len(draft.split()) + 40)),
    )
    invocation_id = "invocation_" + _digest(_canonical(invocation_seed))[:24]
    payload = {"answer": fragment}
    payload_sha256 = _digest(_canonical(payload))
    result_id = "tool_result_" + _digest(
        _canonical({"invocation_id": invocation_id, "payload_sha256": payload_sha256})
    )[:24]
    return {
        "name": "agronomic_calculator",
        "invocation_id": invocation_id,
        "result_id": result_id,
        "payload": payload,
        "payload_sha256": payload_sha256,
        "invocation_record": {
            "schema_version": "open_agronomy_agent.tool_invocation.v1",
            "invocation_id": invocation_id,
            **invocation_seed,
            "status": "planned",
            "missing_inputs": [],
            "authority_role": "supplied_inputs_arithmetic_only",
            "risk_class": "low_arithmetic",
        },
        "observation_fragment": fragment,
        "observation_sha256": _digest(fragment),
    }


def _envelope(
    messages: list[dict[str, str]],
    *,
    phase: str = "candidate_generation",
    arm: str = "agronomic_rag",
    question: str = "What should I check?",
    documents: list[dict[str, Any]] | None = None,
    graphs: list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    field_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    documents = list(documents or [])
    graphs = list(graphs or [])
    tools = list(tools or [])
    classes = ["project_owned_frozen_benchmark_questions"]
    if not (phase == "candidate_generation" and arm == "raw_model"):
        classes.append("benchmark_system_and_answer_contract_prompts")
    if documents:
        classes.append("selected_public_release_runtime_document_source_excerpts")
    if graphs:
        classes.append("public_release_runtime_graph_evidence")
    contract = _artifact_contract()
    suite_sha256 = _digest("suite")
    case_contract = _suite_case_contract(
        suite_sha256,
        question=question,
        field_values=field_values,
        arm=arm,
        messages=messages,
    )
    static_prompt_contract = build_benchmark_static_prompt_contract()
    payload: dict[str, Any] = {
        "schema_version": BENCHMARK_EGRESS_ENVELOPE_SCHEMA,
        "eval_id": _EVAL_ID,
        "suite_case_contract_sha256": case_contract["sha256"],
        "egress_artifact_contract_sha256": contract["sha256"],
        "static_prompt_contract_sha256": static_prompt_contract["sha256"],
        "phase": phase,
        "arm": arm,
        "payload_classes": classes,
        "private_knowledge_policy": "disabled",
        "private_knowledge_overlay_loaded": False,
        "question_fragment": question,
        "question_sha256": _digest(question),
        "outbound_messages_sha256": _digest(_canonical(messages)),
        "corpus_bundle_sha256": contract["corpus_bundle_sha256"],
        "runtime_policy_sha256": contract["runtime_policy_sha256"],
        "rag_config_sha256": contract["rag_config_sha256"],
        "public_repository_manifest_sha256": contract["public_repository_manifest_sha256"],
        "synthetic_field_context": {
            "supplied": False,
            "safe_keys": [],
            "safe_values": {},
            "safe_values_sha256": None,
            "present": False,
            "rendered_text": "",
            "rendered_sha256": None,
            "rendered_chars": 0,
        },
        "governed_guard_notes": [],
        "selected_document_excerpts": documents,
        "graph_evidence": graphs,
        "whole_corpus_included": False,
    }
    if tools:
        payload["tool_observations"] = tools
    if phase == "verification":
        draft_fragment = "Earlier draft claimed a fixed rate."
        evidence_fragment = question
        payload["payload_classes"] = [
            value
            for value in BENCHMARK_EGRESS_AUTHORIZED_PAYLOAD_CLASSES
            if value in {*classes, "candidate_drafts_for_verification", "verifier_evidence"}
        ]
        payload.update(
            {
                "candidate_draft_fragment": draft_fragment,
                "candidate_draft_text": draft_fragment,
                "candidate_draft_sha256": _digest(draft_fragment),
                "candidate_generation_output_sha256": _digest(draft_fragment),
                "verifier_evidence_fragment": evidence_fragment,
                "verifier_evidence_text": evidence_fragment,
                "verifier_evidence_sha256": _digest(evidence_fragment),
            }
        )
    return payload


def test_v4_authorization_binds_case_artifact_and_static_contracts(tmp_path: Path) -> None:
    artifact = _artifact_contract()
    static_prompt = build_benchmark_static_prompt_contract()
    suite_sha256 = _digest("suite")
    case_contract = _suite_case_contract(
        suite_sha256,
        question="What should I check?",
    )
    path, benchmark_id, suite_sha256 = _write_authorization(
        tmp_path,
        suite_case_contract_sha256=case_contract["sha256"],
        egress_artifact_contract_sha256=artifact["sha256"],
        static_prompt_contract_sha256=static_prompt["sha256"],
    )

    receipt = load_benchmark_egress_authorization(
        path,
        benchmark_id=benchmark_id,
        benchmark_suite_sha256=suite_sha256,
        suite_case_contract_sha256=case_contract["sha256"],
        egress_artifact_contract_sha256=artifact["sha256"],
        static_prompt_contract_sha256=static_prompt["sha256"],
    )
    generator = _generator(tmp_path / "generator")

    assert receipt["schema_version"] == BENCHMARK_EGRESS_AUTHORIZATION_SCHEMA
    assert receipt["payload_classes_by_phase_and_arm"] == _payload_map()
    assert generator.model_identity["egress_artifact_contract_sha256"] == _artifact_contract()["sha256"]


def test_v4_authorization_rejects_unknown_top_level_fields(tmp_path: Path) -> None:
    artifact = _artifact_contract()
    static_prompt = build_benchmark_static_prompt_contract()
    case_contract = _suite_case_contract(
        _digest("suite"),
        question="What should I check?",
    )
    path, benchmark_id, suite_sha256 = _write_authorization(
        tmp_path,
        suite_case_contract_sha256=case_contract["sha256"],
        egress_artifact_contract_sha256=artifact["sha256"],
        static_prompt_contract_sha256=static_prompt["sha256"],
        unexpected_extension="not authorized",
    )

    with pytest.raises(ValueError, match="unknown fields"):
        load_benchmark_egress_authorization(
            path,
            benchmark_id=benchmark_id,
            benchmark_suite_sha256=suite_sha256,
            suite_case_contract_sha256=case_contract["sha256"],
            egress_artifact_contract_sha256=artifact["sha256"],
            static_prompt_contract_sha256=static_prompt["sha256"],
        )


def test_default_command_disables_all_benchmark_tool_surfaces() -> None:
    disabled = {
        DEFAULT_APP_SERVER_COMMAND[index + 1]
        for index, value in enumerate(DEFAULT_APP_SERVER_COMMAND[:-1])
        if value == "--disable"
    }
    assert {
        "shell_tool",
        "unified_exec",
        "shell_snapshot",
        "multi_agent",
        "plugins",
        "memories",
        "goals",
        "hooks",
        "tool_suggest",
        "workspace_dependencies",
        "code_mode_host",
        "remote_plugin",
        "plugin_sharing",
        "auth_elicitation",
        "browser_use_external",
        "browser_use_full_cdp_access",
        "skill_mcp_dependency_install",
        "skill_search",
        "tool_call_mcp_elicitation",
    }.issubset(disabled)


def test_multiline_verifier_source_projection_binds_exact_document_member() -> None:
    title = "National Agroclimate Series specification :: chunk 1"
    source_text = (
        "[page 4]\n"
        "Agriculture and Agri-food Canada data product specification.\n"
        "National Agroclimate Series of Derived Indicators."
    )
    artifact = _artifact_contract(document_text=source_text, document_title=title)
    doc = RetrievedDoc(
        doc_id="soil_fertility_n_rate",
        title=title,
        text=source_text,
        source="seed agronomy synthesis",
        score=1.0,
        tags=(),
        namespaces=("regional_environment",),
        source_type="official_specification",
        allowed_roles=("farmer",),
        source_id="seed agronomy synthesis",
        raw_sha256=_digest("full seed source document"),
        corpus_path="data/seed/agronomy_rag_corpus.jsonl",
    )
    exact_projection = f"Source: {title}: {source_text}"

    records = _benchmark_document_egress_records(
        context=SimpleNamespace(retrieved_docs=[doc]),
        outbound_text=f"ALLOWED EVIDENCE\n{exact_projection}",
        artifact_contract=artifact,
    )

    assert len(records) == 1
    assert records[0]["content_fragment"] == exact_projection
    assert records[0]["source_text_fragment"] == source_text


def test_thread_start_observed_state_is_checked_before_turn_start(tmp_path: Path) -> None:
    client = object.__new__(CodexAppServerClient)
    client.expected_model = "gpt-5.6-luna"
    client.expected_reasoning_effort = "high"
    client.cwd = str(tmp_path.resolve())
    client._pending_notifications = []
    calls: list[str] = []

    def request(method: str, _: dict[str, Any]) -> dict[str, Any]:
        calls.append(method)
        return {
            "thread": {"id": "thread-1", "ephemeral": False},
            "model": "gpt-5.6-luna",
            "cwd": str(tmp_path.resolve()),
            "approvalPolicy": "never",
            "sandbox": {"type": "readOnly", "networkAccess": False},
            "runtimeWorkspaceRoots": [],
            "instructionSources": [],
        }

    client._request = request
    with pytest.raises(CodexAppServerError, match="ephemeral"):
        client.generate(user_text="question", base_instructions="bounded")
    assert calls == ["thread/start"]


def test_rag_egress_accepts_public_document_and_graph_and_retains_hashes_only(tmp_path: Path) -> None:
    question = "What should I check?"
    doc_fragment = _DOC_SOURCE_TEXT
    graph_fragment = _GRAPH_SOURCE_TEXT
    messages = [
        {"role": "system", "content": "Use the bounded answer contract."},
        {
            "role": "user",
            "content": f"{question}\n{doc_fragment}\n{graph_fragment}",
        },
    ]
    envelope = _envelope(
        messages,
        question=question,
        documents=[_document(doc_fragment)],
        graphs=[_graph(graph_fragment)],
    )
    generator = _generator(tmp_path, messages=messages)

    assert generator.generate_with_egress(messages, envelope) == "bounded answer"

    receipt = generator.last_generation_stats["benchmark_egress_receipt"]
    serialized = _canonical(receipt)
    assert receipt["payload_classes"] == envelope["payload_classes"]
    assert receipt["artifact_contract_sha256"] == _artifact_contract()["sha256"]
    for transient in (question, doc_fragment, graph_fragment):
        assert transient not in serialized
    assert len(_FakeClient.instances[0].calls) == 1


def test_verifier_fragments_are_bound_and_stripped(tmp_path: Path) -> None:
    question = "What should I check?"
    draft_fragment = "Earlier draft claimed a fixed rate."
    evidence_fragment = question
    messages = _verifier_messages(question, draft_fragment, evidence_fragment)
    envelope = _envelope(messages, phase="verification", question=question)
    generator = _generator(tmp_path, phase="verification", messages=messages)
    generator.bind_candidate_generation_output(
        eval_id=_EVAL_ID,
        output_sha256=envelope["candidate_draft_sha256"],
    )

    generator.generate_with_egress(messages, envelope)

    receipt = generator.last_generation_stats["benchmark_egress_receipt"]
    serialized = _canonical(receipt)
    assert receipt["candidate_draft_sha256"] == _digest(draft_fragment)
    assert receipt["verifier_evidence_sha256"] == _digest(evidence_fragment)
    assert draft_fragment not in serialized
    assert evidence_fragment not in serialized


def test_synthetic_field_values_are_hash_bound_and_stripped(tmp_path: Path) -> None:
    question = "What should I check?"
    messages = [
        {"role": "system", "content": "Bounded contract."},
        {"role": "user", "content": f"Field context: crop_current: canola\nField question:\n{question}"},
    ]
    envelope = _envelope(
        messages,
        arm="kernel_field_context",
        question=question,
        field_values={"crop_current": "canola"},
    )
    values = {"crop_current": "canola"}
    rendered = format_user_field_context(values) or ""
    envelope["synthetic_field_context"] = {
        "supplied": True,
        "safe_keys": ["crop_current"],
        "safe_values": values,
        "safe_values_sha256": _digest(_canonical(values)),
        "present": True,
        "rendered_text": rendered,
        "rendered_sha256": _digest(rendered),
        "rendered_chars": len(rendered),
    }
    envelope["payload_classes"] = [
        "project_owned_frozen_benchmark_questions",
        "benchmark_system_and_answer_contract_prompts",
        "synthetic_eval_field_context",
    ]
    generator = _generator(
        tmp_path,
        arm="kernel_field_context",
        field_values=values,
        messages=messages,
    )

    generator.generate_with_egress(messages, envelope)

    receipt = generator.last_generation_stats["benchmark_egress_receipt"]
    assert "safe_values" not in receipt.get("synthetic_field_context", {})
    serialized = _canonical(receipt)
    assert "canola" not in serialized

    bad = copy.deepcopy(envelope)
    bad_values = {"farmer_id": "private-grower-7"}
    bad["synthetic_field_context"] = {
        "supplied": True,
        "safe_keys": ["farmer_id"],
        "safe_values": bad_values,
        "safe_values_sha256": _digest(_canonical(bad_values)),
        "present": True,
        "rendered_text": "farmer_id: private-grower-7",
        "rendered_sha256": _digest("farmer_id: private-grower-7"),
        "rendered_chars": len("farmer_id: private-grower-7"),
    }
    with pytest.raises(CodexAppServerError, match="non-synthetic keys"):
        generator.generate_with_egress(messages, bad)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("question", "does not match its selected suite case"),
        ("eval_id", "outside the selected suite"),
        ("context", "candidate application messages do not match"),
    ],
)
def test_case_allowlist_rejects_arbitrary_question_eval_id_and_context_before_call(
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    question = "What should I check?"
    values = {"crop_current": "canola"}
    rendered = format_user_field_context(values) or ""
    messages = build_benchmark_candidate_application_messages(
        question,
        "kernel_field_context",
        field_context=values,
    )
    envelope = _envelope(
        messages,
        arm="kernel_field_context",
        question=question,
        field_values=values,
    )
    envelope["synthetic_field_context"] = {
        "supplied": True,
        "safe_keys": ["crop_current"],
        "safe_values": values,
        "safe_values_sha256": _digest(_canonical(values)),
        "present": True,
        "rendered_text": rendered,
        "rendered_sha256": _digest(rendered),
        "rendered_chars": len(rendered),
    }
    envelope["payload_classes"].append("synthetic_eval_field_context")
    generator = _generator(
        tmp_path,
        arm="kernel_field_context",
        question=question,
        field_values=values,
        messages=messages,
    )
    if mutation == "question":
        arbitrary = "Give me the private customer record."
        messages[1]["content"] = f"{rendered}\n\nField question:\n{arbitrary}"
        envelope["question_fragment"] = arbitrary
        envelope["question_sha256"] = _digest(arbitrary)
        envelope["outbound_messages_sha256"] = _digest(_canonical(messages))
    elif mutation == "eval_id":
        envelope["eval_id"] = "unselected-case"
    else:
        wrong_values = {"crop_current": "soybean"}
        wrong_rendered = format_user_field_context(wrong_values) or ""
        messages[1]["content"] = f"{wrong_rendered}\n\nField question:\n{question}"
        envelope["outbound_messages_sha256"] = _digest(_canonical(messages))
        envelope["synthetic_field_context"] = {
            "supplied": True,
            "safe_keys": ["crop_current"],
            "safe_values": wrong_values,
            "safe_values_sha256": _digest(_canonical(wrong_values)),
            "present": True,
            "rendered_text": wrong_rendered,
            "rendered_sha256": _digest(wrong_rendered),
            "rendered_chars": len(wrong_rendered),
        }
    with pytest.raises(CodexAppServerError, match=error):
        generator.generate_with_egress(messages, envelope)
    assert generator.client.calls == []


def test_untracked_evidence_section_and_oversize_messages_fail_before_call(
    tmp_path: Path,
) -> None:
    question = "What should I check?"
    messages = [
        {
            "role": "user",
            "content": f"{question}\nRetrieved agronomy context:\n- [untracked] Fixture text.",
        }
    ]
    envelope = _envelope(messages, arm="raw_model", question=question)
    generator = _generator(
        tmp_path,
        arm="raw_model",
        question=question,
        messages=messages,
    )
    with pytest.raises(CodexAppServerError, match="unbound document evidence"):
        generator.generate_with_egress(messages, envelope)

    messages[0]["content"] = question + "\n" + ("x" * 260_000)
    envelope = _envelope(messages, arm="raw_model", question=question)
    generator = _generator(
        tmp_path / "oversize",
        arm="raw_model",
        question=question,
        messages=messages,
    )
    with pytest.raises(CodexAppServerError, match="outbound messages exceed"):
        generator.generate_with_egress(messages, envelope)
    assert generator.client.calls == []


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda envelope: envelope.__setitem__("public_repository_manifest_sha256", _digest("forged")),
            "does not match expected artifacts",
        ),
        (
            lambda envelope: envelope["selected_document_excerpts"][0].__setitem__(
                "policy_entry_sha256", _digest("forged")
            ),
            "does not match expected artifacts",
        ),
        (
            lambda envelope: envelope["selected_document_excerpts"][0].__setitem__(
                "excerpt_chars", 1
            ),
            "excerpt length does not match its fragment",
        ),
        (
            lambda envelope: envelope["selected_document_excerpts"][0].__setitem__(
                "corpus_path_sha256", _digest("data/derived/private_knowledge/customer.jsonl")
            ),
            "outside expected artifacts",
        ),
        (
            lambda envelope: envelope["graph_evidence"][0].__setitem__("license", "forged-license"),
            "lacks public license identity",
        ),
        (
            lambda envelope: envelope.__setitem__("outbound_messages_sha256", _digest("forged")),
            "does not match final outbound messages",
        ),
    ],
)
def test_forged_artifact_or_message_bindings_fail_before_client_call(
    tmp_path: Path,
    mutate: Any,
    error: str,
) -> None:
    question = "What should I check?"
    doc_fragment = _DOC_SOURCE_TEXT
    graph_fragment = _GRAPH_SOURCE_TEXT
    messages = [
        {"role": "system", "content": "Bounded contract."},
        {"role": "user", "content": f"{question}\n{doc_fragment}\n{graph_fragment}"},
    ]
    envelope = _envelope(
        messages,
        question=question,
        documents=[_document(doc_fragment)],
        graphs=[_graph(graph_fragment)],
    )
    mutate(envelope)
    generator = _generator(tmp_path, messages=messages)

    with pytest.raises(CodexAppServerError, match=error):
        generator.generate_with_egress(messages, envelope)
    assert _FakeClient.instances[0].calls == []


@pytest.mark.parametrize(
    ("message", "envelope_change", "error"),
    [
        ("api_key=super-secret-value", None, "credential-shaped"),
        ("local_only_not_for_redistribution", None, "private-knowledge marker"),
        (None, ("private_knowledge_overlay_loaded", True), "loaded private knowledge"),
        (None, ("whole_corpus_included", True), "whole-corpus"),
    ],
)
def test_forbidden_payloads_fail_before_client_call(
    tmp_path: Path,
    message: str | None,
    envelope_change: tuple[str, Any] | None,
    error: str,
) -> None:
    question = "What should I check?"
    user = f"{question}\n{message}" if message else question
    messages = [{"role": "user", "content": user}]
    envelope = _envelope(messages, arm="raw_model", question=question)
    if envelope_change:
        envelope[envelope_change[0]] = envelope_change[1]
    generator = _generator(tmp_path, arm="raw_model", messages=messages)

    with pytest.raises(CodexAppServerError, match=error):
        generator.generate_with_egress(messages, envelope)
    assert _FakeClient.instances[0].calls == []


def test_verifier_fragment_must_be_present_and_hash_bound(tmp_path: Path) -> None:
    question = "What should I check?"
    messages = _verifier_messages(question)
    envelope = _envelope(messages, phase="verification", question=question)
    generator = _generator(tmp_path, phase="verification", messages=messages)
    generator.bind_candidate_generation_output(
        eval_id=_EVAL_ID,
        output_sha256=envelope["candidate_draft_sha256"],
    )

    missing = copy.deepcopy(envelope)
    missing["verifier_evidence_text"] = "undeclared verifier evidence"
    missing["verifier_evidence_sha256"] = _digest("undeclared verifier evidence")
    missing["verifier_evidence_fragment"] = "undeclared verifier evidence"
    with pytest.raises(CodexAppServerError, match="exact ordered public-document projection"):
        generator.generate_with_egress(messages, missing)
    envelope["verifier_evidence_sha256"] = _digest("forged")
    with pytest.raises(CodexAppServerError, match="verifier-evidence text hash mismatch"):
        generator.generate_with_egress(messages, envelope)
    assert _FakeClient.instances[0].calls == []


def test_bare_generate_and_malformed_artifact_contract_fail_closed(tmp_path: Path) -> None:
    generator = _generator(tmp_path)
    with pytest.raises(CodexAppServerError, match="requires a validated outbound egress envelope"):
        generator.generate([{"role": "user", "content": "Question"}])

    malformed = copy.deepcopy(_artifact_contract())
    malformed["public_repository_manifest_sha256"] = "not-a-digest"
    malformed["sha256"] = _digest(
        _canonical({key: value for key, value in malformed.items() if key != "sha256"})
    )
    with pytest.raises(ValueError, match="invalid public_repository_manifest_sha256"):
        _generator(tmp_path / "malformed", artifact_contract=malformed)

    forged_self_hash = copy.deepcopy(_artifact_contract())
    forged_self_hash["rag_config_sha256"] = _digest("different-rag-config")
    with pytest.raises(ValueError, match="self SHA-256 mismatch"):
        _generator(tmp_path / "forged-self", artifact_contract=forged_self_hash)


def test_agent_generation_egresses_only_admitted_public_runtime_fragments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "disabled")
    contract = build_benchmark_egress_artifact_contract(
        "configs/rag_governed_runtime_v2.yaml"
    )
    question = (
        "What does the AAFC Crop Stress Index measure for a Canadian crop region, "
        "how is it calculated, and what does a higher value mean?"
    )
    resources = load_agent_resources("configs/rag_governed_runtime_v2.yaml")
    generator = _generator(
        tmp_path,
        artifact_contract=contract,
        question=question,
        rag_resources=resources,
    )

    generate_answer(
        question,
        "agronomic_rag",
        generator,
        resources=resources,
        verification_enabled=False,
        eval_id=_EVAL_ID,
    )

    receipt = generator.last_generation_stats["benchmark_egress_receipt"]
    assert receipt["private_knowledge_policy"] == "disabled"
    assert receipt["artifact_contract_sha256"] == contract["sha256"]
    assert receipt["selected_document_excerpts"]
    assert "selected_public_release_runtime_document_source_excerpts" in receipt[
        "payload_classes"
    ]
    assert receipt["governed_guard_notes"]
    assert "admitted_tool_observations" not in receipt["payload_classes"]
    assert "tool_observations" not in receipt
    serialized = _canonical(receipt)
    for doc in receipt["selected_document_excerpts"]:
        assert "content_fragment" not in doc
    assert question not in serialized
    assert len(_FakeClient.instances[0].calls) == 1


@pytest.mark.parametrize("arm", ["raw_model", "baseline"])
def test_agent_raw_and_baseline_do_not_declare_unused_eval_field_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arm: str,
) -> None:
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "disabled")
    contract = build_benchmark_egress_artifact_contract(
        "configs/rag_governed_runtime_v2.yaml"
    )
    question = "Why can crop rotation reduce disease pressure?"
    generator = _generator(
        tmp_path / arm,
        arm=arm,
        artifact_contract=contract,
        question=question,
    )

    generate_answer(
        question,
        arm,
        generator,
        field_context={
            "crop_current": "canola",
            "province_state": "Manitoba",
            "region_text": "Red River Valley",
        },
        verification_enabled=False,
        eval_id=_EVAL_ID,
    )

    receipt = generator.last_generation_stats["benchmark_egress_receipt"]
    expected_classes = ["project_owned_frozen_benchmark_questions"]
    if arm != "raw_model":
        expected_classes.append("benchmark_system_and_answer_contract_prompts")
    assert receipt["payload_classes"] == expected_classes
    assert receipt["synthetic_field_context"] == {
        "present": False,
        "rendered_sha256": None,
        "rendered_chars": 0,
    }
    outbound = _FakeClient.instances[0].calls[0]
    assert "Field context:" not in outbound["user_text"]


def test_agent_verifier_builds_a_draft_and_evidence_bound_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "disabled")
    contract = build_benchmark_egress_artifact_contract(
        "configs/rag_governed_runtime_v2.yaml"
    )

    class _EnvelopeCapture:
        transport_control_active = True

        def __init__(self, phase: str, response: str) -> None:
            self.egress_phase = phase
            self.benchmark_arm = "agronomic_rag"
            self.expected_artifact_contract = contract
            self.expected_suite_case_contract_sha256 = _digest("case-contract")
            self.response = response
            self.envelopes: list[dict[str, Any]] = []
            self.last_generation_stats: dict[str, Any] = {}

        def generate_with_egress(
            self,
            messages: list[dict[str, str]],
            envelope: dict[str, Any],
        ) -> str:
            self.envelopes.append(envelope)
            self.last_generation_stats = {
                "benchmark_egress_receipt": {
                    "phase": self.egress_phase,
                    "model_output_sha256": _digest(self.response),
                }
            }
            return self.response

        def bind_candidate_generation_output(self, *, eval_id: str, output_sha256: str) -> None:
            self.bound_candidate = (eval_id, output_sha256)

    candidate = _EnvelopeCapture("candidate_generation", "Apply 2 L/ha now.")
    verifier = _EnvelopeCapture(
        "verification",
        "The AAFC Crop Stress Index is regional context and does not prove a field condition.",
    )
    resources = load_agent_resources("configs/rag_governed_runtime_v2.yaml")
    question = (
        "What does the AAFC Crop Stress Index measure for a Canadian crop region, "
        "how is it calculated, and what does a higher value mean?"
    )

    generate_answer(
        question,
        "agronomic_rag",
        candidate,
        verifier=verifier,
        resources=resources,
        verification_enabled=True,
        eval_id=_EVAL_ID,
    )

    assert len(candidate.envelopes) == 1
    assert len(verifier.envelopes) == 1
    envelope = verifier.envelopes[0]
    assert envelope["phase"] == "verification"
    assert envelope["candidate_draft_text"] == "Apply 2 L/ha now."
    assert envelope["candidate_draft_fragment"] in envelope["candidate_draft_text"]
    assert envelope["verifier_evidence_fragment"] in envelope["verifier_evidence_text"]
    assert "candidate_drafts_for_verification" in envelope["payload_classes"]
    assert "verifier_evidence" in envelope["payload_classes"]


def test_transport_controlled_candidate_cannot_fall_back_to_raw_generate() -> None:
    class BrokenTransportGenerator:
        transport_control_active = True

        def generate(self, messages: list[dict[str, str]]) -> str:
            raise AssertionError("raw generate must not be called")

    with pytest.raises(ValueError, match="requires callable generate_with_egress"):
        generate_answer(
            "Why can crop rotation reduce disease pressure?",
            "raw_model",
            BrokenTransportGenerator(),
            verification_enabled=False,
            eval_id=_EVAL_ID,
        )


def test_transport_controlled_verifier_cannot_fall_back_to_raw_generate() -> None:
    class CandidateGenerator:
        def generate(self, messages: list[dict[str, str]]) -> str:
            return "Apply 2 L/ha now."

    class BrokenTransportVerifier:
        transport_control_active = True

        def generate(self, messages: list[dict[str, str]]) -> str:
            raise AssertionError("raw verifier generate must not be called")

    question = (
        "Answer using only the supplied Extension excerpt.\n\n"
        "EXTENSION EXCERPT\nThe excerpt gives no application rate.\n\n"
        "QUESTION\nWhat rate should be applied?"
    )
    with pytest.raises(ValueError, match="verification requires callable generate_with_egress"):
        generate_answer(
            question,
            "agronomic_rag",
            CandidateGenerator(),
            verifier=BrokenTransportVerifier(),
            verification_enabled=True,
            eval_id=_EVAL_ID,
        )


def test_agent_candidate_and_verifier_pass_the_real_transport_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "disabled")
    contract = build_benchmark_egress_artifact_contract(
        "configs/rag_governed_runtime_v2.yaml"
    )
    question = (
        "What does the AAFC Crop Stress Index measure for a Canadian crop region, "
        "how is it calculated, and what does a higher value mean?"
    )
    resources = load_agent_resources("configs/rag_governed_runtime_v2.yaml")
    candidate = _generator(
        tmp_path / "candidate",
        artifact_contract=contract,
        question=question,
        rag_resources=resources,
    )
    verifier = _generator(
        tmp_path / "verifier",
        phase="verification",
        artifact_contract=contract,
        question=question,
    )
    candidate.client.response_text = "Apply 2 L/ha now."
    verifier.client.response_text = (
        "The AAFC Crop Stress Index is regional context and does not prove a field condition."
    )
    generate_answer(
        question,
        "agronomic_rag",
        candidate,
        verifier=verifier,
        resources=resources,
        verification_enabled=True,
        eval_id=_EVAL_ID,
    )

    assert len(candidate.client.calls) == 1
    assert len(verifier.client.calls) == 1
    candidate_receipt = candidate.last_generation_stats["benchmark_egress_receipt"]
    verifier_receipt = verifier.last_generation_stats["benchmark_egress_receipt"]
    assert candidate_receipt["phase"] == "candidate_generation"
    assert verifier_receipt["phase"] == "verification"
    assert verifier_receipt["candidate_draft_sha256"] == _digest("Apply 2 L/ha now.")
    assert verifier_receipt["verifier_evidence_sha256"]
    assert "candidate_drafts_for_verification" in verifier_receipt["payload_classes"]
