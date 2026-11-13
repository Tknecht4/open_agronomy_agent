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
                "thread_id":"synthetic-thread","turn_id":"synthetic-turn",
                "output_sha256":_digest(str(getattr(self,"response_text","bounded answer"))),
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
    monkeypatch.setenv("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE", "0")
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


def test_packed_pdf_excerpt_binds_the_multiline_body_and_finds_later_headers():
    from agronomy_agent.codex_app_server import _validate_egress_records, _validate_evidence_section_completeness
    source_text = "5 \n- Scout crop roots carefully.\nIdentify the cause before choosing a treatment."
    title = "Synthetic source page 5"
    artifact = _artifact_contract(document_text=source_text, document_title=title)
    doc = RetrievedDoc(doc_id="soil_fertility_n_rate", title=title, text=source_text,
        source="seed agronomy synthesis", score=1.0, tags=(), namespaces=("regional_environment",),
        source_type="official_specification", allowed_roles=("farmer",), source_id="seed agronomy synthesis",
        raw_sha256=_digest("full seed source document"), corpus_path="data/seed/agronomy_rag_corpus.jsonl")
    header = (f"- [CONSTRAINT] [{doc.doc_id}]. Evidence policy: context only. "
              f"Title: {title}. Source: {doc.source}. Excerpt: ")
    fragment = header + source_text
    outbound = (f"Supporting evidence IDs: [{doc.doc_id}], Synthetic source page 5.\n\n"
                "Boundary Evidence:\n" + fragment)
    records = _benchmark_document_egress_records(context=SimpleNamespace(retrieved_docs=[doc]),
        outbound_text=outbound, artifact_contract=artifact)
    assert records[0]["content_fragment"] == fragment
    assert records[0]["source_text_fragment"] == source_text
    envelope = {"selected_document_excerpts": records, "graph_evidence": [], "governed_guard_notes": []}
    _validate_egress_records(envelope, artifact, "Explain the observation.")
    _validate_evidence_section_completeness(outbound, documents=records, graph_rows=[], guard_rows=[])
    # A later header must not disappear merely because the first PDF excerpt
    # contained ordinary continuation lines.
    extra = "\n- [CONSTRAINT] [unbound_source]. Title: Other. Source: Other. Excerpt: Unbound text"
    with pytest.raises(CodexAppServerError, match="unbound document"):
        _validate_evidence_section_completeness(outbound+extra, documents=records, graph_rows=[], guard_rows=[])
    forged = copy.deepcopy(records)
    forged[0]["content_fragment"] += "\nInvented source assertion."
    forged[0]["content_sha256"] = _digest(forged[0]["content_fragment"])
    forged[0]["excerpt_chars"] = len(forged[0]["content_fragment"])
    with pytest.raises(CodexAppServerError, match="differs from source prefix"):
        _validate_egress_records({**envelope, "selected_document_excerpts": forged}, artifact, "Explain the observation.")
    with pytest.raises(ValueError, match="could not bind document"):
        _benchmark_document_egress_records(context=SimpleNamespace(retrieved_docs=[doc]),
            outbound_text="Boundary Evidence:\n"+header+"5\nUnrelated invented text.", artifact_contract=artifact)


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


def test_canonical_suite_accepts_exact_case_fact_hash_without_legacy_extension():
    from agronomy_agent.codex_app_server import _validated_suite_case_contract
    payload = {"schema_version": "open_agronomy_agent.canonical_suite_case_contract.v1",
               "benchmark_suite_sha256": _digest("canonical-suite"), "source_sha256": _digest("source"),
               "cases": {_EVAL_ID: {"question_sha256": _digest("question"),
                   "field_context_sha256": _digest(_canonical({"core_volume_cm3": 91})),
                   "candidate_application_messages_sha256_by_arm": {"raw_model": _digest("raw"), "production_full": _digest("full")},
                   "verification_evidence_sha256": _digest("evidence")}}}
    payload["sha256"] = _digest(_canonical(payload))
    assert _validated_suite_case_contract(payload, benchmark_suite_sha256=payload["benchmark_suite_sha256"]) == payload


def test_canonical_missing_thread_selection_is_not_requested_model():
    client = object.__new__(CodexAppServerClient)
    client.expected_model="gpt-6-luna"; client.expected_reasoning_effort="medium"
    client.cwd="/owned/empty"; client.allowed_instruction_sources=(); client._pending_notifications=[]
    client.fail_on_reroute=True; client.catalog_model={};client.protocol_identity={}
    def request(method,params):
        assert method == "thread/start", "missing selection must stop before turn/start"
        return {"thread":{"id":"thread-1","ephemeral":True},"cwd":client.cwd,
                "approvalPolicy":"never","sandbox":{"type":"readOnly","networkAccess":False},
                "runtimeWorkspaceRoots":[],"instructionSources":[]}
    client._request=request
    with pytest.raises(CodexAppServerError,match="selection|model"):
        client.generate(user_text="question",base_instructions="")


def _canonical_generator(tmp_path, *, question="What should I check?", messages=None, facts=None,
                         phase="candidate_generation", arm="production_full", config_sha=None,
                         evidence=None, max_tokens=640, model_id="gpt-6-luna", config_path=None, artifact=None):
    import agronomy_agent.codex_app_server as module
    tmp_path.mkdir(parents=True,exist_ok=True)
    if config_path is None:
        config_path=tmp_path/"effective-model.yaml"
        config_path.write_text(json.dumps({"model_id":model_id,"model_revision":None,"reasoning_effort":"medium","max_tokens":640,
            "answer_verification":{"enabled":True,"model_id":model_id,"reasoning_effort":"medium","max_tokens":220}}))
    config_sha=config_sha or hashlib.sha256(config_path.read_bytes()).hexdigest()
    messages=messages or [{"role":"system","content":"Synthetic system"},{"role":"user","content":question}]
    suite={"schema_version":module.CANONICAL_SUITE_SCHEMA,"benchmark_suite_sha256":_digest("canonical suite"),
           "source_sha256":_digest("synthetic source"),"cases":{_EVAL_ID:{
           "question_sha256":_digest(question),"field_context_sha256":_digest(_canonical(facts or {})),
           "candidate_application_messages_sha256_by_arm":{"raw_model":_digest(_canonical([{"role":"user","content":question}])),
                                                            "production_full":_digest(_canonical(messages))},
           "verification_evidence_sha256":_digest(question if evidence is None else evidence)}}}
    suite["sha256"]=_digest(_canonical(suite));artifact=_artifact_contract() if artifact is None else artifact;static=build_benchmark_static_prompt_contract()
    grant,bid,_=_write_authorization(tmp_path,suite_case_contract_sha256=suite["sha256"],
        egress_artifact_contract_sha256=artifact["sha256"],static_prompt_contract_sha256=static["sha256"])
    authority=json.loads(grant.read_text());authority.update(schema_version=module.CANONICAL_EGRESS_AUTHORIZATION_SCHEMA,benchmark_suite_sha256=suite["benchmark_suite_sha256"],
        model_id=model_id,reasoning_effort="medium",model_config_sha256=config_sha,authorized_payload_classes=list(module.CANONICAL_PAYLOAD_CLASSES),
        payload_classes_by_phase_and_arm=module.CANONICAL_PAYLOAD_MAP)
    grant.write_text(json.dumps(authority))
    return CodexAppServerGenerator(model_id=model_id,reasoning_effort="medium",benchmark_id=bid,benchmark_suite_sha256=suite["benchmark_suite_sha256"],
        model_config_sha256=config_sha,model_config_path=config_path,egress_authorization=grant,egress_phase=phase,benchmark_arm=arm,
        suite_case_contract=suite,egress_artifact_contract=artifact,static_prompt_contract=static,max_tokens=max_tokens)


@pytest.mark.parametrize("change",["field","question","messages","unknown","artifact","overlay","legacy","typed"])
def test_canonical_egress_rejects_changed_or_unclassified_payload_before_client(tmp_path,change):
    from agronomy_agent.agent import _build_benchmark_egress_envelope
    generator=_canonical_generator(tmp_path)
    messages=[{"role":"system","content":"Synthetic system"},{"role":"user","content":"What should I check?"}]
    envelope=_build_benchmark_egress_envelope(generator=generator,messages=messages,eval_id=_EVAL_ID,
        question="What should I check?",field_context={},context=None,resources=None)
    if change=="field":envelope["field_context"]={"unreviewed":91}
    if change=="question":envelope["question_fragment"]="Altered question"
    if change=="messages":messages[1]["content"]+=" changed"
    if change=="unknown":envelope["unclassified"]="private"
    if change=="artifact":envelope["egress_artifact_contract_sha256"]="0"*64
    if change=="overlay":envelope["private_knowledge_overlay_loaded"]=True
    if change=="legacy":generator.egress_authorization["schema_version"]=BENCHMARK_EGRESS_AUTHORIZATION_SCHEMA
    if change=="typed":envelope["payload_classes"].append("typed_tool_results")
    with pytest.raises((ValueError,CodexAppServerError)):
        generator.generate_with_egress(messages,envelope)
    assert generator._client is None


@pytest.mark.parametrize("change",["arm","phase","model","config","cap","facts","effort"])
def test_canonical_factory_product_is_case_config_arm_and_phase_bound(tmp_path,change):
    from agronomy_agent.codex_app_server import validate_canonical_backend
    generator=_canonical_generator(tmp_path)
    expected=dict(eval_id=_EVAL_ID,question="What should I check?",field_context={},arm="production_full",
        phase="candidate_generation",model_id="gpt-6-luna",model_config_sha256=generator.egress_authorization["model_config_sha256"],max_tokens=640,reasoning_effort="medium")
    validate_canonical_backend(generator,**expected)
    key={"arm":"arm","phase":"phase","model":"model_id","config":"model_config_sha256","cap":"max_tokens","facts":"field_context","effort":"reasoning_effort"}[change]
    expected[key]=641 if change=="cap" else {"different":True} if change=="facts" else "different"
    with pytest.raises(ValueError,match="mismatch"):validate_canonical_backend(generator,**expected)
    assert generator._client is None


@pytest.mark.parametrize("editor_override",[None,"medium"])
def test_canonical_editor_requested_effort_matches_phase_config_before_client(tmp_path,editor_override):
    from agronomy_agent.codex_app_server import validate_canonical_backend
    config=tmp_path/"phase.yaml"
    stage={"model_id":"gpt-6-luna","max_tokens":220}
    if editor_override is not None:stage["reasoning_effort"]=editor_override
    config.write_text(json.dumps({"model_id":"gpt-6-luna","reasoning_effort":"medium","max_tokens":640,"answer_verification":stage}))
    generator=_canonical_generator(tmp_path,phase="verification",max_tokens=220,config_path=config)
    expected=dict(eval_id=_EVAL_ID,question="What should I check?",field_context={},arm="production_full",phase="verification",
        model_id="gpt-6-luna",model_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),max_tokens=220,
        reasoning_effort=stage.get("reasoning_effort") or "medium")
    validate_canonical_backend(generator,**expected)
    generator.reasoning_effort="high";generator.egress_authorization["reasoning_effort"]="high"
    with pytest.raises(ValueError,match="mismatch"):validate_canonical_backend(generator,**expected)
    assert generator._client is None


def test_canonical_shared_provenance_checks_even_with_unchanged_message_hash(tmp_path):
    from agronomy_agent.codex_app_server import _validate_egress_records
    envelope={"selected_document_excerpts":[_document("- [soil_fertility_n_rate] Synthetic source")],"graph_evidence":[],"governed_guard_notes":[]}
    for key,value in (("policy_rights_status","private"),("runtime_eligibility","excluded"),("document_row_sha256","0"*64)):
        altered=copy.deepcopy(envelope);altered["selected_document_excerpts"][0][key]=value
        with pytest.raises(CodexAppServerError):_validate_egress_records(altered,_artifact_contract(),"question")


def _protocol_client(events, *, selected="gpt-6-luna", check=None):
    client=object.__new__(CodexAppServerClient);client.expected_model="gpt-6-luna";client.expected_reasoning_effort="medium"
    client.cwd="/owned/empty";client.allowed_instruction_sources=();client._pending_notifications=[]
    client.fail_on_reroute=True;client.catalog_model={};client.protocol_identity={};client.before_dispatch=check
    client._event_bytes=0;client._reader_error=None
    def request(method,params):
        if method=="thread/start":return {"thread":{"id":"thread-1","ephemeral":True},"model":selected,"cwd":client.cwd,
            "approvalPolicy":"never","sandbox":{"type":"readOnly","networkAccess":False},"runtimeWorkspaceRoots":[],"instructionSources":[]}
        return {"threadId":"thread-1","turn":{"id":"turn-1"}}
    client._request=request;iterator=iter(events);client._read_message=lambda:next(iterator)
    return client


def _terminal_events():
    return [{"method":"item/completed","params":{"threadId":"thread-1","turnId":"turn-1","item":{"id":"item-1","type":"agentMessage","text":"synthetic answer"}}},
            {"method":"thread/tokenUsage/updated","params":{"threadId":"thread-1","turnId":"turn-1","tokenUsage":{"last":{"inputTokens":10,"outputTokens":4}}}},
            {"method":"turn/completed","params":{"threadId":"thread-1","turn":{"id":"turn-1","status":"completed"}}}]


@pytest.mark.parametrize("change",["item","usage","terminal","missing_selection","reroute","request","duplicate"])
def test_canonical_protocol_rejects_foreign_or_missing_attribution(change):
    events=_terminal_events();client=_protocol_client(events)
    if change in {"item","usage"}:events[{"item":0,"usage":1}[change]]["params"]["turnId"]="foreign"
    if change=="terminal":events[2]["params"]["threadId"]="foreign"
    if change=="missing_selection":client=_protocol_client(events,selected=None)
    if change=="reroute":events.insert(0,{"method":"model/rerouted","params":{"threadId":"thread-1","turnId":"turn-1"}})
    if change=="request":events.insert(0,{"id":77,"method":"tool/request","params":{}})
    if change=="duplicate":events.insert(1,copy.deepcopy(events[0]))
    with pytest.raises(CodexAppServerError):client.generate(user_text="question",base_instructions="")


def test_canonical_protocol_completion_keeps_cap_effort_revision_and_eos_unknown():
    client=_protocol_client(_terminal_events())
    result=client.generate(user_text="question",base_instructions="")
    assert result.receipt["selected_model"]=="gpt-6-luna"
    assert result.receipt["finish_reason"] is None and result.receipt["hard_output_cap_supported"] is False
    assert result.receipt["effective_turn_reasoning_effort_observed"] is False
    with pytest.raises(CodexAppServerError,match="single-turn"):client.generate(user_text="again",base_instructions="")


@pytest.mark.parametrize("change", [None, "missing_start", "foreign_thread", "foreign_turn", "duplicate_start", "foreign_terminal"])
def test_current_turn_response_requires_observed_thread_binding(change):
    # The current generated TurnStartResponse has only a turn; attribution is
    # independently observed in turn/started and turn/completed notifications.
    start = {"method": "turn/started", "params": {"threadId": "thread-1", "turn": {"id": "turn-1"}}}
    events = [start, *_terminal_events()]
    if change == "missing_start": events.pop(0)
    if change == "foreign_thread": start["params"]["threadId"] = "foreign"
    if change == "foreign_turn": start["params"]["turn"]["id"] = "foreign"
    if change == "duplicate_start": events.insert(1, copy.deepcopy(start))
    if change == "foreign_terminal": events[-1]["params"]["threadId"] = "foreign"
    client = _protocol_client(events)
    request = client._request
    def current_request(method, params):
        value = request(method, params)
        if method == "turn/start": value.pop("threadId")
        return value
    client._request = current_request
    if change:
        with pytest.raises(CodexAppServerError): client.generate(user_text="question", base_instructions="")
    else:
        result = client.generate(user_text="question", base_instructions="")
        assert result.receipt["thread_binding_evidence"] == {
            "turn_start_response": False, "turn_started_notification": True, "completed_notification": True}


@pytest.mark.parametrize("change", [None, "thread", "cwd", "model", "effort", "network", "approval", "profile", "missing", "missing_profile"])
def test_settings_notifications_must_preserve_controlled_transport(change):
    settings = {"cwd": "/owned/empty", "model": "gpt-6-luna", "effort": "medium",
                "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                "activePermissionProfile": None}
    event = {"method": "thread/settings/updated", "params": {"threadId": "thread-1", "threadSettings": settings}}
    if change == "thread": event["params"]["threadId"] = "foreign"
    if change in {"cwd", "model", "effort"}: settings[change] = "foreign"
    if change == "network": settings["sandboxPolicy"]["networkAccess"] = True
    if change == "approval": settings["approvalPolicy"] = "on-request"
    if change == "profile": settings["activePermissionProfile"] = {"name": "other"}
    if change == "missing": settings.pop("model")
    if change == "missing_profile": settings.pop("activePermissionProfile")
    client = _protocol_client([event, *_terminal_events()])
    if change:
        with pytest.raises(CodexAppServerError, match="controlled transport"): client.generate(user_text="question", base_instructions="")
    else:
        assert client.generate(user_text="question", base_instructions="").text == "synthetic answer"


@pytest.mark.parametrize("change", [None, "foreign_thread", "unknown_warning", "remote_enabled"])
def test_only_expected_isolation_warning_and_disabled_remote_state_are_admitted(change):
    warning = {"method": "warning", "params": {"threadId": "thread-1", "message":
        "Failed to read global AGENTS.md instructions from `/synthetic/config/AGENTS.md`: Operation not permitted (os error 1)"}}
    remote = {"method": "remoteControl/status/changed", "params": {"status": "disabled", "environmentId": None}}
    if change == "foreign_thread": warning["params"]["threadId"] = "foreign"
    if change == "unknown_warning": warning["params"]["message"] = "Unreviewed transport condition"
    if change == "remote_enabled": remote["params"]["status"] = "enabled"
    client = _protocol_client([warning, remote, *_terminal_events()])
    if change:
        with pytest.raises(CodexAppServerError): client.generate(user_text="question", base_instructions="")
    else:
        result = client.generate(user_text="question", base_instructions="")
        assert result.receipt["transport_warning_classifications"] == ["global_instruction_read_denied"]


def test_explicit_disabled_code_mode_warning_is_retained_without_enabling_tools():
    event = {"method": "warning", "params": {"threadId": "thread-1", "message":
        "Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; "
        "enable `features.code_mode_host` and install `codex-code-mode-host`."}}
    result = _protocol_client([event, *_terminal_events()]).generate(user_text="question", base_instructions="")
    assert result.receipt["transport_warning_classifications"] == ["code_mode_host_disabled"]
    assert result.receipt["transport_policy"] == "text_only_no_tools_v1"


@pytest.mark.parametrize("mode", ["chatgpt", "apikey", None])
def test_account_notifications_cannot_change_the_declared_auth_transport(mode):
    event = {"method": "account/updated", "params": {"authMode": mode, "planType": None}}
    client = _protocol_client([event, *_terminal_events()])
    if mode != "chatgpt":
        with pytest.raises(CodexAppServerError, match="authentication state"): client.generate(user_text="question", base_instructions="")
    else:
        assert client.generate(user_text="question", base_instructions="").text == "synthetic answer"


@pytest.mark.parametrize("foreign", [False, True])
def test_moderation_metadata_remains_attributed_observation_not_answer_authority(foreign):
    event = {"method": "turn/moderationMetadata", "params": {"threadId": "thread-1",
        "turnId": "foreign" if foreign else "turn-1", "metadata": {"synthetic_observation": True}}}
    client = _protocol_client([event, *_terminal_events()])
    if foreign:
        with pytest.raises(CodexAppServerError, match="binding mismatch"): client.generate(user_text="question", base_instructions="")
    else:
        result = client.generate(user_text="question", base_instructions="")
        assert result.receipt["moderation_metadata"] == [event["params"]]
        assert result.receipt["moderation_metadata_scope"].startswith("provider_observation_only")


def test_sparse_account_quota_observation_does_not_become_turn_attribution():
    event = {"method": "account/rateLimits/updated", "params": {"rateLimits": {"primary": None}}}
    result = _protocol_client([event, *_terminal_events()]).generate(user_text="question", base_instructions="")
    assert result.receipt["account_rate_limit_observations"] == [event["params"]]
    assert result.receipt["effective_turn_reasoning_effort_observed"] is False


@pytest.mark.parametrize("stream_answer", [False, True])
def test_terminal_fallback_cannot_hide_a_forbidden_tool_item(stream_answer):
    events = _terminal_events()
    events[-1]["params"]["turn"]["items"] = [
        {"id": "item-1", "type": "agentMessage", "text": "synthetic answer"},
        {"id": "tool-1", "type": "commandExecution"}]
    if not stream_answer: events.pop(0)
    with pytest.raises(CodexAppServerError, match="forbidden.*terminal items"):
        _protocol_client(events).generate(user_text="question", base_instructions="")


@pytest.mark.parametrize("stage",["thread/start","turn/start"])
def test_canonical_fresh_authority_check_occurs_at_both_egress_boundaries(stage):
    calls=[]
    def check(method):
        calls.append(method)
        if method==stage:raise CodexAppServerError("expired")
    client=_protocol_client(_terminal_events(),check=check)
    with pytest.raises(CodexAppServerError,match="expired"):client.generate(user_text="question",base_instructions="")
    assert calls==(["thread/start"] if stage=="thread/start" else ["thread/start","turn/start"])


def test_canonical_bounded_reader_refuses_oversized_frame_before_queue_allocation():
    import io,queue,threading
    client=object.__new__(CodexAppServerClient)
    class Pipe:
        def __init__(self):self.sizes=[]
        def readline(self,size):self.sizes.append(size);return b"x"*size
    pipe=Pipe();client._process=SimpleNamespace(stdout=pipe);client._reader_error=None
    client._stdout_queue=queue.Queue(maxsize=1);client._queued_bytes=0;client._buffer_lock=threading.Lock()
    client._read_stdout()
    assert pipe.sizes==[client.MAX_FRAME_BYTES+1] and client._reader_error
    assert client._queued_bytes==0


def test_canonical_absolute_deadline_and_event_aggregate_are_finite(monkeypatch):
    import agronomy_agent.codex_app_server as module
    client=object.__new__(CodexAppServerClient);client._deadline=10
    monkeypatch.setattr(module,"perf_counter",lambda:11)
    with pytest.raises(CodexAppServerError,match="deadline"):client._remaining()
    client._event_bytes=client.MAX_EVENT_BYTES
    with pytest.raises(CodexAppServerError,match="bound"):client._retain_event([],{"method":"x"})


def test_canonical_owned_process_close_kills_waits_and_never_claims_remote_cancel(monkeypatch):
    import agronomy_agent.codex_app_server as module
    calls=[]
    class Process:
        pid=123;stdin=None;returncode=None
        def poll(self):return self.returncode
        def terminate(self):calls.append("term")
        def kill(self):calls.append("kill")
        def wait(self,timeout):
            calls.append("wait")
            if len(calls)==2:raise module.subprocess.TimeoutExpired("fake",timeout)
            self.returncode=-9
    client=object.__new__(CodexAppServerClient);client._closed=False;client._process=Process();client._temporary_cwd=None
    def kill(pid,sig):
        assert pid==123
        if sig==0:raise ProcessLookupError
        calls.append("term" if sig==module.signal.SIGTERM else "kill")
    monkeypatch.setattr(module.os,"killpg",kill)
    receipt=client.close()
    assert calls==["term","wait","kill","wait"]
    assert receipt["local_returncode"]==-9 and receipt["owned_group_absent"] is None and receipt["remote_cancellation_confirmed"] is None


@pytest.mark.parametrize("after_ack",[False,True])
def test_canonical_failed_attempt_keeps_known_acknowledgements_not_stale_stats(tmp_path,monkeypatch,after_ack):
    import agronomy_agent.codex_app_server as module
    from agronomy_agent.agent import _build_benchmark_egress_envelope
    class FailedClient(_FakeClient):
        def generate(self,**kwargs):
            error=CodexAppServerError("synthetic failure")
            error.provider_attempt={"state":"turn_acknowledged" if after_ack else "pre_dispatch",
                "thread_id":"thread" if after_ack else None,"turn_id":"turn" if after_ack else None,
                "turn_acknowledged":after_ack,"submitted":after_ack}
            raise error
    monkeypatch.setattr(module,"CodexAppServerClient",FailedClient)
    generator=_canonical_generator(tmp_path)
    generator.last_generation_stats={"generation_tokens":999,"stale":True}
    messages=[{"role":"system","content":"Synthetic system"},{"role":"user","content":"What should I check?"}]
    envelope=_build_benchmark_egress_envelope(generator=generator,messages=messages,eval_id=_EVAL_ID,
        question="What should I check?",field_context={},context=None,resources=None)
    with pytest.raises(CodexAppServerError) as caught:generator.generate_with_egress(messages,envelope)
    attempt=caught.value.provider_attempt
    assert attempt["phase"]=="candidate_generation" and attempt["eval_id"]==_EVAL_ID and attempt["attempt_id"]==1
    assert attempt["turn_acknowledged"] is after_ack and attempt["turn_id"]==("turn" if after_ack else None)
    assert generator.last_generation_stats is None


@pytest.mark.parametrize("change",["doc","graph","guard","missing","rights","eligibility"])
def test_canonical_direct_egress_shares_membership_and_completeness_validation(tmp_path,change):
    from agronomy_agent.agent import _build_benchmark_egress_envelope
    question="What should I check?"
    doc="- "+_DOC_SOURCE_TEXT;graph="- "+_GRAPH_SOURCE_TEXT
    messages=[{"role":"system","content":"Synthetic system"},
              {"role":"user","content":question+"\nRetrieved agronomy context:\n"+doc+"\n\nKnowledge graph hits:\n"+graph}]
    generator=_canonical_generator(tmp_path,messages=messages)
    envelope=_build_benchmark_egress_envelope(generator=generator,messages=messages,eval_id=_EVAL_ID,
        question=question,field_context={},context=None,resources=None)
    envelope.update(selected_document_excerpts=[_document(doc)],graph_evidence=[_graph(graph)],
        payload_classes=["project_owned_frozen_benchmark_questions","benchmark_system_and_answer_contract_prompts",
                         "selected_public_release_runtime_document_source_excerpts","public_release_runtime_graph_evidence"])
    if change=="doc":envelope["selected_document_excerpts"][0]["document_row_sha256"]="0"*64
    if change=="graph":envelope["graph_evidence"][0]["node_row_sha256"]="0"*64
    if change=="guard":envelope["governed_guard_notes"]=[{"name":"forged_guard"}]
    if change=="missing":envelope["selected_document_excerpts"]=[]
    if change=="rights":envelope["selected_document_excerpts"][0]["policy_rights_status"]="private"
    if change=="eligibility":envelope["selected_document_excerpts"][0]["runtime_eligibility"]="excluded"
    with pytest.raises(CodexAppServerError):generator.generate_with_egress(messages,envelope)
    assert generator._client is None


@pytest.mark.parametrize("change",["doc","graph","guard","missing_doc","missing_graph","missing_guard","rights","eligibility"])
def test_canonical_entry_accepts_admitted_records_sanitizes_and_rejects_mutation_before_call(tmp_path,monkeypatch,change):
    from agronomy_agent.agent import _build_benchmark_egress_envelope,_benchmark_guard_note_egress_records
    from agronomy_agent.tools.registry import run_tools
    class CurrentClient(_FakeClient):
        def generate(self,**kwargs):
            result=super().generate(**kwargs);result.receipt["selected_model"]="gpt-6-luna";return result
    monkeypatch.setattr("agronomy_agent.codex_app_server.CodexAppServerClient",CurrentClient)
    question="What soil structure should I check?"
    note=run_tools(question,("soil_structure_guard",))[0]
    doc="- "+_DOC_SOURCE_TEXT;graph="- "+_GRAPH_SOURCE_TEXT;guard="- "+note.name+": "+note.text
    messages=[{"role":"system","content":"Synthetic system"},{"role":"user","content":
        question+"\nRetrieved agronomy context:\n"+doc+"\n\nKnowledge graph hits:\n"+graph+"\n\n"+guard}]
    generator=_canonical_generator(tmp_path,question=question,messages=messages)
    envelope=_build_benchmark_egress_envelope(generator=generator,messages=messages,eval_id=_EVAL_ID,
        question=question,field_context={},context=None,resources=None)
    envelope.update(selected_document_excerpts=[_document(doc)],graph_evidence=[_graph(graph)],
        governed_guard_notes=_benchmark_guard_note_egress_records(context=SimpleNamespace(tool_notes=[note]),outbound_text=messages[1]["content"]),
        payload_classes=["project_owned_frozen_benchmark_questions","benchmark_system_and_answer_contract_prompts",
                         "selected_public_release_runtime_document_source_excerpts","public_release_runtime_graph_evidence"])
    assert generator.generate_with_egress(messages,envelope)=="bounded answer"
    receipt=generator.last_generation_stats["benchmark_egress_receipt"]
    assert all(receipt[key] for key in ("selected_document_excerpts","graph_evidence","governed_guard_notes"))
    assert all(text not in _canonical(receipt) for text in (question,_DOC_SOURCE_TEXT,_GRAPH_SOURCE_TEXT,note.text))
    assert len(generator._client.calls)==1
    altered=copy.deepcopy(envelope)
    if change=="doc":altered["selected_document_excerpts"][0]["document_row_sha256"]="0"*64
    if change=="graph":altered["graph_evidence"][0]["node_row_sha256"]="0"*64
    if change=="guard":altered["governed_guard_notes"][0]["text"]="forged"
    if change.startswith("missing_"):altered[{"missing_doc":"selected_document_excerpts","missing_graph":"graph_evidence","missing_guard":"governed_guard_notes"}[change]]=[]
    if change=="rights":altered["selected_document_excerpts"][0]["policy_rights_status"]="private"
    if change=="eligibility":altered["selected_document_excerpts"][0]["runtime_eligibility"]="excluded"
    with pytest.raises(CodexAppServerError):generator.generate_with_egress(messages,altered)
    assert len(generator._client.calls)==1


def test_canonical_effective_config_drift_rechecked_before_lazy_client(tmp_path):
    generator=_canonical_generator(tmp_path)
    generator._model_config_path.write_text("changed")
    with pytest.raises(CodexAppServerError,match="config"):
        generator._ensure_client()
    assert generator._client is None


@pytest.mark.parametrize("bad_id",[True,1.0,False,"1"])
def test_canonical_response_id_requires_exact_integer_type(bad_id):
    client=object.__new__(CodexAppServerClient);client._next_id=0;client._pending_notifications=[]
    client._send=lambda payload:None
    client._read_message=lambda:{"id":bad_id,"result":{}}
    with pytest.raises(CodexAppServerError,match="binding"):client._request("initialize",{})


@pytest.mark.parametrize("bad_id",[True,77,1.0])
@pytest.mark.parametrize("phase",["thread","turn"])
def test_canonical_thread_and_turn_ids_must_be_returned_strings(bad_id,phase):
    client=_protocol_client(_terminal_events());original=client._request
    def request(method,params):
        result=original(method,params)
        if method==phase+"/start":result[phase]["id"]=bad_id
        return result
    client._request=request
    with pytest.raises(CodexAppServerError,match="id"):client.generate(user_text="question",base_instructions="")


@pytest.mark.parametrize("text",[None,True,7,{"text":"coerced"}])
def test_canonical_nonstring_output_is_not_coerced(text):
    events=_terminal_events();events[0]["params"]["item"]["text"]=text
    with pytest.raises(CodexAppServerError,match="string"):_protocol_client(events).generate(user_text="question",base_instructions="")


@pytest.mark.parametrize("text",["  exact raw output\n",""])
def test_canonical_raw_output_whitespace_and_empty_return_are_preserved(text):
    events=_terminal_events();events[0]["params"]["item"]["text"]=text
    result=_protocol_client(events).generate(user_text="question",base_instructions="")
    assert result.text==text and result.receipt["output_sha256"]==_digest(text)
    assert result.receipt["output_composition"]=="one_exact_raw_agent_message"


@pytest.fixture(scope="module")
def render_public_artifact():
    return build_benchmark_egress_artifact_contract()


def _render_bound_fixture(tmp_path, base, *, kind="guard", delivery="body_prefix", copies=1,
                          omitted_occurrences=0, phase="candidate_generation"):
    from agronomy_agent import agent
    from agronomy_agent import benchmark_render_provenance as render
    from agronomy_agent.tools.registry import run_tools
    question="Explain why a local observation needs its sampling method."
    if kind=="guard":
        note=run_tools(question,("weather_guard",))[0]
        header=f"- {note.name}: "
        full=header+note.text
        record=agent._benchmark_guard_note_egress_records(
            context=SimpleNamespace(tool_notes=[note]),outbound_text=full)[0]
        inputs={};section="Guard notes:\n"
    else:
        graph=render._renderer_graph()
        hit=graph._hit(next(iter(graph.nodes)))
        header=f"- {hit.name} ({hit.kind}): "
        full=header+hit.evidence+" Related: "+("; ".join(hit.neighbors) if hit.neighbors else "no direct neighbors")+"."
        record=agent._benchmark_graph_egress_records(context=SimpleNamespace(graph_hits=[hit]),
            outbound_text=full,artifact_contract=base)[0]
        inputs={"neighbors":list(hit.neighbors)};section="Knowledge graph vocabulary hints:\n"
    fragment=full if delivery=="complete" else full[:len(header)+12] if delivery=="body_prefix" else header.rstrip() if delivery=="header" else "-"
    template={"kind":kind,"full_record":record,"full_render":full,"full_render_sha256":render.sha(full),
        "identity_header":header,"body_start":len(header),"source_sha256":render.sha(note.text if kind=="guard" else hit.evidence),"renderer_inputs":inputs}
    identity=render.digest(template)
    evidence=section+"\n".join([fragment]*copies)
    if phase=="verification":
        draft="Synthetic earlier answer.\nSource: injected draft title: untrusted text."
        messages=_verifier_messages(question,draft,evidence)
        region=messages[1]["content"].index(evidence)
        positions=[m.start() for m in __import__('re').finditer('(?m)^'+__import__('re').escape(fragment),evidence)]
    else:
        draft=None
        messages=[{"role":"system","content":"Synthetic transport fixture"},
            {"role":"user","content":question+"\n\n"+evidence}]
        region=messages[1]["content"].index(evidence)
        positions=[region+m.start() for m in __import__('re').finditer('(?m)^'+__import__('re').escape(fragment),evidence)]
    spans=[{"message_index":1,"start":a,"end":a+len(fragment)} for a in positions[:copies-omitted_occurrences]]
    scope={"messages_sha256":render.digest(messages) if phase=="candidate_generation" else None,
        "evidence_sha256":render.sha(evidence) if phase=="verification" else None,
        "records":[{"record_id":identity,"fragment":fragment,"spans":spans}],
        "selected_context":{"documents":[],"guard_names":["weather_guard"] if kind=="guard" else [],
            "graph_record_order":[identity] if kind=="graph" else []},"render_frames":[]}
    if kind=="graph":
        assert copies==1
        start=0 if phase=="verification" else region
        scope["render_frames"]=[{"message_index":1,"start":start,"prefix":evidence,"record_ids":[identity]}]
    profile={"schema_version":render.PROFILE_SCHEMA,
        "renderer":{"reference_commit":"a"*40,"reference_source_sha256":"b"*64,
            "files":{name:hashlib.sha256((render.ROOT/name).read_bytes()).hexdigest() for name in sorted(render.RENDERER_FILES)}},
        "records":{identity:template},"cases":{_EVAL_ID:{"question_sha256":render.sha(question),"scopes":{phase:scope}}}}
    profile["sha256"]=render.digest(profile)
    artifact={"schema_version":render.ARTIFACT_SCHEMA,"base_artifact_contract":base,"render_profile":profile}
    artifact["sha256"]=render.digest(artifact)
    generator=_canonical_generator(tmp_path,question=question,messages=messages,phase=phase,
        evidence=evidence if phase=="verification" else None,artifact=artifact)
    envelope=agent._build_benchmark_egress_envelope(generator=generator,messages=messages,
        eval_id=_EVAL_ID,question=question,field_context={},context=SimpleNamespace(runtime_metadata={}),
        resources=SimpleNamespace(private_knowledge_overlay=None),
        **({"candidate_draft":draft,"verifier_evidence_text":evidence,
            "candidate_generation_output_sha256":render.sha(draft)} if draft else {}))
    if draft:generator.bind_candidate_generation_output(eval_id=_EVAL_ID,output_sha256=render.sha(draft))
    return generator,envelope,messages


def _validate_render_fixture(generator,envelope,messages):
    from agronomy_agent.codex_app_server import _validate_outbound_envelope
    return _validate_outbound_envelope(envelope,authorization=generator.egress_authorization,
        artifact_contract=generator.expected_artifact_contract,suite_case_contract=generator.expected_suite_case_contract,
        static_prompt_contract=generator.expected_static_prompt_contract,
        expected_candidate_output_sha256=generator._candidate_output_bindings.get(_EVAL_ID),
        expected_phase=generator.egress_phase,expected_arm=generator.benchmark_arm,messages=messages)


@pytest.mark.parametrize("kind,delivery,body_chars,complete_identity",[
    ("guard","body_prefix",12,True),("guard","header",0,False),
    ("graph","body_prefix",12,True),("graph","bare",0,False)])
def test_render_bound_actual_prefix_preserves_messages_and_reports_only_delivered_body(
        tmp_path,render_public_artifact,kind,delivery,body_chars,complete_identity):
    gen,envelope,messages=_render_bound_fixture(tmp_path,render_public_artifact,kind=kind,delivery=delivery)
    result=_validate_render_fixture(gen,envelope,messages)
    assert result['instructions']==messages[0]['content']
    assert result['user_text']==messages[1]['content']
    key='governed_guard_notes' if kind=='guard' else 'graph_evidence'
    record=result['sanitized_envelope'][key][0];provenance=record['render_provenance']
    assert provenance['delivered_source_chars']==body_chars
    assert provenance['metadata_only'] is (body_chars==0)
    assert provenance['identity_header_complete'] is complete_identity
    assert provenance['source_body_complete'] is False
    assert all(k not in record for k in ('text','outbound_fragment','node_evidence_text','node_evidence_fragment','evidence_fragment'))
    if not complete_identity:assert provenance['identity_binding'].startswith('controller_inferred_')


def test_render_bound_duplicate_header_without_second_span_rejects_before_provider(tmp_path,render_public_artifact,monkeypatch):
    gen,envelope,messages=_render_bound_fixture(tmp_path,render_public_artifact,copies=2,omitted_occurrences=1)
    monkeypatch.setattr(gen,'_ensure_client',lambda:pytest.fail('provider constructed'))
    with pytest.raises(CodexAppServerError,match='unbound guard'):
        gen.generate_with_egress(messages,envelope)


def test_render_bound_occurrence_weighted_delivery_limit(tmp_path,render_public_artifact,monkeypatch):
    import agronomy_agent.codex_app_server as module
    gen,envelope,messages=_render_bound_fixture(tmp_path,render_public_artifact,copies=3,delivery='complete')
    length=len(envelope['governed_guard_notes'][0]['outbound_fragment'])
    monkeypatch.setattr(module,'_MAX_GUARD_NOTE_CHARS',length*2)
    monkeypatch.setattr(gen,'_ensure_client',lambda:pytest.fail('provider constructed'))
    with pytest.raises(CodexAppServerError,match='actual source delivery exceeds'):
        gen.generate_with_egress(messages,envelope)


@pytest.mark.parametrize('change',['missing_frame','changed_order','forged_neighbors','ambiguous_guard','renderer_drift'])
def test_render_bound_rehashed_profile_rejects_unproved_identity(tmp_path,render_public_artifact,change):
    from agronomy_agent import benchmark_render_provenance as render
    from agronomy_agent.codex_app_server import _validated_artifact_contract
    kind='guard' if change=='ambiguous_guard' else 'graph'
    gen,_,_=_render_bound_fixture(tmp_path,render_public_artifact,kind=kind,delivery='bare' if kind=='graph' else 'header')
    artifact=copy.deepcopy(gen.expected_artifact_contract);profile=artifact['render_profile']
    scope=profile['cases'][_EVAL_ID]['scopes']['candidate_generation']
    if change=='missing_frame':scope['render_frames']=[]
    elif change=='changed_order':scope['selected_context']['graph_record_order']=[]
    elif change=='forged_neighbors':
        identity=next(iter(profile['records']));template=profile['records'].pop(identity)
        template['renderer_inputs']['neighbors']=['fabricated public relation']
        new=render.digest(template);profile['records'][new]=template
        scope['records'][0]['record_id']=new;scope['selected_context']['graph_record_order']=[new];scope['render_frames'][0]['record_ids']=[new]
    elif change=='ambiguous_guard':
        # Rehash a bare header prefix against two selected original guards.
        item=scope['records'][0];item['fragment']='- ';item['spans'][0]['end']=item['spans'][0]['start']+2
        scope['selected_context']['guard_names']=['weather_guard','soil_structure_guard']
    else:profile['renderer']['files']['configs/context_policy_v1.yaml']='0'*64
    profile.pop('sha256');profile['sha256']=render.digest(profile)
    artifact.pop('sha256');artifact['sha256']=render.digest(artifact)
    with pytest.raises(ValueError):_validated_artifact_contract(artifact)


def test_render_bound_editor_draft_cannot_supply_an_evidence_occurrence(tmp_path,render_public_artifact):
    gen,envelope,messages=_render_bound_fixture(tmp_path,render_public_artifact,phase='verification')
    result=_validate_render_fixture(gen,envelope,messages)
    assert result['user_text']==messages[1]['content']
    assert len(result['sanitized_envelope']['governed_guard_notes'])==1
    span=envelope['governed_guard_notes'][0]['render_provenance']['spans'][0]
    assert span['end']<messages[1]['content'].index('UNTRUSTED CANDIDATE-DRAFT')


def test_render_bound_contract_cannot_downgrade_to_v1_envelope(tmp_path,render_public_artifact):
    import agronomy_agent.codex_app_server as module
    gen,envelope,messages=_render_bound_fixture(tmp_path,render_public_artifact)
    envelope['schema_version']=module.CANONICAL_ENVELOPE_SCHEMA
    with pytest.raises(CodexAppServerError,match='authority versions differ'):
        _validate_render_fixture(gen,envelope,messages)


@pytest.mark.parametrize('phase',['candidate_generation','verification'])
def test_render_bound_declared_graph_frame_must_exist_in_actual_message(tmp_path,render_public_artifact,phase):
    from agronomy_agent import benchmark_render_provenance as render
    gen,envelope,messages=_render_bound_fixture(tmp_path,render_public_artifact,kind='graph',delivery='bare',phase=phase)
    profile=copy.deepcopy(gen.expected_artifact_contract['render_profile'])
    scope=profile['cases'][_EVAL_ID]['scopes'][phase]
    header='Knowledge graph vocabulary hints:'
    replacement='Unrelated synthetic section'.ljust(len(header))
    changed=copy.deepcopy(messages)
    changed[1]['content']=changed[1]['content'].replace(header,replacement,1)
    evidence=envelope.get('verifier_evidence_text')
    if phase=='verification':
        evidence=evidence.replace(header,replacement,1)
        scope['evidence_sha256']=render.sha(evidence)
    else:scope['messages_sha256']=render.digest(changed)
    profile.pop('sha256');profile['sha256']=render.digest(profile)
    # Declared source/order/offset proof alone is valid; actual frame is absent.
    render.checked_profile(profile,base_artifact_contract=render_public_artifact)
    with pytest.raises(ValueError,match='actual original render frame differs'):
        render.build_records(profile,eval_id=_EVAL_ID,phase=phase,arm='production_full',
            messages=changed,question=envelope['question_fragment'],verifier_evidence_text=evidence)
