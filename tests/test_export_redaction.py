from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from agronomy_agent.server.services.export_service import _sanitize_export_value, build_export_bundle


CANARIES = {
    "session_title": "CANARY_SESSION_TITLE_5bb361",
    "session_context": "CANARY_PRIVATE_FARM_CONTEXT_c2536f",
    "user_message": "CANARY_USER_QUESTION_f4ca7c",
    "answer": "CANARY_PUBLIC_ANSWER_6dcb90",
    "draft": "CANARY_DRAFT_STAGE_8f014a",
    "post_verification": "CANARY_POST_VERIFY_STAGE_e0138a",
    "final": "CANARY_FINAL_STAGE_e51c02",
    "verification_draft": "CANARY_VERIFIER_DRAFT_545d21",
    "verification_evidence": "CANARY_VERIFIER_EVIDENCE_460a74",
    "prompt": "CANARY_SYSTEM_PROMPT_a36436",
    "retrieved_snippet": "CANARY_RETRIEVED_SNIPPET_2ae13d",
    "evidence_claim": "CANARY_EVIDENCE_CLAIM_a3f4b2",
    "evidence_source": "CANARY_EVIDENCE_SOURCE_SNIPPET_c269d8",
    "tool_input": "CANARY_TOOL_INPUT_5abfd1",
    "tool_result": "CANARY_TOOL_RESULT_f07a3a",
    "graph_evidence": "CANARY_GRAPH_EVIDENCE_9c8f07",
    "nested_metadata": "CANARY_DEEP_METADATA_10c99c",
    "suffix_id": "private.id+canary@example.invalid",
    "suffix_status": "private.status+canary@example.invalid",
    "suffix_role": "private.role+canary@example.invalid",
    "known_user_id": "CANARY_PRIVATE_FARMER_001",
    "known_status": "CANARY_PRIVATE_FARMER_001",
    "known_source_id": "private/farm/CANARY001",
    "event": "CANARY_EVENT_PAYLOAD_548069",
    "data_source": "CANARY_PRIVATE_SOURCE_PATH_6f05d8",
    "feedback": "CANARY_HUMAN_CORRECTION_e95bd9",
    "reflection": "CANARY_REFLECTION_RULE_d982c0",
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _marker(value: str) -> str:
    return f"[redacted:{_sha(value)}]"


def _fixture_records(*, training_export_allowed: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    turn = {
        "turn_id": "turn_001",
        "session_id": "session_001",
        "user_message": CANARIES["user_message"],
        "answer": CANARIES["answer"],
        "answer_status": "approved",
        "created_at": "2026-08-13T12:00:00+00:00",
        "system_state": {
            "mode": "agronomic_rag",
            "model_id": "model_local_001",
            "prompt_version": "prompt_v1",
            "latency_ms": 42,
        },
        "trace": {
            "route": {
                "question_type": "field_decision",
                "risk_level": "medium",
                "namespaces": ["soil", "crop"],
                "required_tools": ["agronomic_calculator_v1"],
            },
            "coverage_checklist": [CANARIES["evidence_claim"]],
            "retrieved_docs": [
                {
                    "doc_id": "doc_001",
                    "source_id": "source_001",
                    "score": 0.91,
                    "snippet": CANARIES["retrieved_snippet"],
                }
            ],
            "graph_hits": [
                {
                    "node_id": "node_001",
                    "rank": 1,
                    "score": 0.88,
                    "evidence": CANARIES["graph_evidence"],
                    "metadata": {"private_note": CANARIES["nested_metadata"]},
                }
            ],
            "tool_invocations": [
                {
                    "invocation_id": "invocation_001",
                    "tool_id": "agronomic_calculator_v1",
                    "tool_version": "agronomic_calculator_v1",
                    "operation": "convert_rate",
                    "status": "succeeded",
                    "inputs": {"crop_name": CANARIES["tool_input"], "rate_kg_ha": 55.5},
                    "result": {
                        "result_id": "result_001",
                        "status": "validated",
                        "value": 49.5,
                        "text": CANARIES["tool_result"],
                    },
                }
            ],
            "prompt_messages": [
                {"role": "system", "content": CANARIES["prompt"]},
                {"role": "user", "content": CANARIES["user_message"]},
            ],
            "metadata": {
                "answer_stages": {
                    "schema_version": "open_agronomy_agent.answer_stages.v1",
                    "draft": {"text": CANARIES["draft"], "sha256": _sha(CANARIES["draft"])},
                    "post_verification": {
                        "text": CANARIES["post_verification"],
                        "sha256": _sha(CANARIES["post_verification"]),
                    },
                    "final": {"text": CANARIES["final"], "sha256": _sha(CANARIES["final"])},
                },
                "answer_verification": {
                    "schema_version": "open_agronomy_agent.answer_verification.v1",
                    "status": "validated",
                    "triggered": True,
                    "confidence": 0.93,
                    "result_ids": ["result_001"],
                    "draft_answer": CANARIES["verification_draft"],
                    "evidence": CANARIES["verification_evidence"],
                },
                "evidence_fabric": {
                    "schema_version": "open_agronomy_agent.evidence_fabric.v1",
                    "status": "captured",
                    "record_sha256": "a" * 64,
                    "evidence_packet": {
                        "packet_id": "packet_001",
                        "claims": [
                            {"claim_id": "claim_001", "claim": CANARIES["evidence_claim"], "confidence": 0.82}
                        ],
                        "sources": [
                            {"source_id": "source_001", "snippet": CANARIES["evidence_source"], "rank": 1}
                        ],
                    },
                },
                "tool_results": [
                    {
                        "result_id": "result_001",
                        "status": "validated",
                        "value": 49.5,
                        "text": CANARIES["tool_result"],
                    }
                ],
                "extension_metadata": {
                    "level_one": {
                        "level_two": {
                            "private_note": CANARIES["nested_metadata"],
                            "private_note_id": CANARIES["suffix_id"],
                            "private_status": CANARIES["suffix_status"],
                            "private_role": CANARIES["suffix_role"],
                        }
                    },
                    "malformed_structural_fields": {
                        "id": CANARIES["suffix_id"],
                        "status": CANARIES["suffix_status"],
                        "role": CANARIES["suffix_role"],
                    },
                    "disguised_known_keys": {
                        "user_id": CANARIES["known_user_id"],
                        "status": CANARIES["known_status"],
                        "source_id": CANARIES["known_source_id"],
                    },
                },
            },
        },
        "objectives": {"safety": 1.0, "correctness": 0.75},
        "prompt_messages": [{"role": "system", "content": CANARIES["prompt"]}],
        "metadata": {"private_note": CANARIES["nested_metadata"], "receipt_sha256": "b" * 64},
        "feedback": {
            "rating": 4,
            "accepted": True,
            "human_correction": CANARIES["feedback"],
            "failure_tags": ["too_vague"],
        },
        "reflection": {
            "review_status": "candidate",
            "affected_component": "answer_policy",
            "proposed_rule": CANARIES["reflection"],
            "evidence": [CANARIES["verification_evidence"]],
        },
    }
    session = {
        "session_id": "session_001",
        "title": CANARIES["session_title"],
        "created_at": "2026-08-13T12:00:00+00:00",
        "updated_at": "2026-08-13T12:01:00+00:00",
        "user_pseudonym": "private-user",
        "tags": ["private-tag"],
        "consent": {"training_export_allowed": training_export_allowed},
        "context": {
            "farm_id": "farm_001",
            "region": CANARIES["session_context"],
            "crop": "confidential-crop",
        },
        "turns": [{"turn_id": "turn_001"}],
    }
    return session, turn


class _Store:
    def __init__(self, turn: dict[str, Any]) -> None:
        self.turn = turn

    def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        return deepcopy(self.turn) if turn_id == self.turn["turn_id"] else None

    def list_events(self, session_id: str) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "session_id": session_id,
                "turn_id": self.turn["turn_id"],
                "event_name": "answer.completed",
                "payload": {"private_note": CANARIES["event"], "latency_ms": 42},
                "created_at": "2026-08-13T12:01:00+00:00",
            }
        ]

    def list_data_sources(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": "source_001",
                "source_type": "file",
                "path": CANARIES["data_source"],
                "checksum": "c" * 64,
            }
        ]


def _all_export_text(export_dir: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(export_dir.iterdir()) if path.is_file())


def test_snippets_hashed_recursively_hashes_content_in_every_export_artifact(tmp_path: Path) -> None:
    session, turn = _fixture_records()
    manifest, _ = build_export_bundle(
        session,
        _Store(turn),
        tmp_path,
        export_id="exp_snippets_hashed",
        redaction_mode="snippets_hashed",
    )

    export_dir = tmp_path / "exp_snippets_hashed"
    exported_text = _all_export_text(export_dir)
    for location, canary in CANARIES.items():
        assert canary not in exported_text, f"{location} canary leaked"
        assert _sha(canary) in exported_text, f"{location} canary was not replaced by a stable hash"

    exported_session = json.loads((export_dir / "session.json").read_text(encoding="utf-8"))
    exported_turn = exported_session["turns"][0]
    trace = exported_turn["trace"]
    assert exported_session["session_id"] == "session_001"
    assert exported_turn["turn_id"] == "turn_001"
    assert exported_session["created_at"] == "2026-08-13T12:00:00+00:00"
    assert exported_turn["created_at"] == "2026-08-13T12:00:00+00:00"
    assert exported_turn["user_message"] == _marker(CANARIES["user_message"])
    assert exported_turn["answer"] == _marker(CANARIES["answer"])
    assert trace["prompt_messages"][0] == {"role": "system", "content": _marker(CANARIES["prompt"])}
    assert trace["graph_hits"][0]["node_id"] == "node_001"
    assert trace["graph_hits"][0]["score"] == 0.88
    assert trace["graph_hits"][0]["evidence"] == _marker(CANARIES["graph_evidence"])
    tool = trace["tool_invocations"][0]
    assert tool["invocation_id"] == "invocation_001"
    assert tool["inputs"]["rate_kg_ha"] == 55.5
    assert tool["inputs"]["crop_name"] == _marker(CANARIES["tool_input"])
    stages = trace["metadata"]["answer_stages"]
    assert stages["draft"]["text"] == _marker(CANARIES["draft"])
    assert stages["draft"]["sha256"] == _sha(CANARIES["draft"])
    verification = trace["metadata"]["answer_verification"]
    assert verification["status"] == "validated"
    assert verification["confidence"] == 0.93
    assert verification["result_ids"] == ["result_001"]
    private_extension = trace["metadata"]["extension_metadata"]["level_one"]["level_two"]
    assert private_extension == {
        "private_note": _marker(CANARIES["nested_metadata"]),
        "private_note_id": _marker(CANARIES["suffix_id"]),
        "private_status": _marker(CANARIES["suffix_status"]),
        "private_role": _marker(CANARIES["suffix_role"]),
    }
    assert trace["metadata"]["extension_metadata"]["malformed_structural_fields"] == {
        "id": _marker(CANARIES["suffix_id"]),
        "status": _marker(CANARIES["suffix_status"]),
        "role": _marker(CANARIES["suffix_role"]),
    }
    assert trace["metadata"]["extension_metadata"]["disguised_known_keys"] == {
        "user_id": _marker(CANARIES["known_user_id"]),
        "status": _marker(CANARIES["known_status"]),
        "source_id": _marker(CANARIES["known_source_id"]),
    }
    assert trace["prompt_messages"][0]["role"] == "system"
    assert trace["tool_invocations"][0]["status"] == "succeeded"
    assert manifest["contains_personal_data"] is True
    assert manifest["contains_farm_identifiable_data"] is True
    assert manifest["contains_private_attachment_text"] is True


def test_training_safe_omits_content_but_retains_structural_metadata_everywhere(tmp_path: Path) -> None:
    session, turn = _fixture_records(training_export_allowed=True)
    manifest, _ = build_export_bundle(
        session,
        _Store(turn),
        tmp_path,
        export_id="exp_training_safe",
        redaction_mode="training_safe",
    )

    export_dir = tmp_path / "exp_training_safe"
    exported_text = _all_export_text(export_dir)
    for location, canary in CANARIES.items():
        assert canary not in exported_text, f"{location} canary leaked"

    exported_session = json.loads((export_dir / "session.json").read_text(encoding="utf-8"))
    exported_turn = exported_session["turns"][0]
    trace = exported_turn["trace"]
    assert exported_session["session_id"] == "session_001"
    assert exported_turn["turn_id"] == "turn_001"
    assert exported_session["created_at"] == "2026-08-13T12:00:00+00:00"
    assert exported_turn["created_at"] == "2026-08-13T12:00:00+00:00"
    assert exported_turn["user_message"] == "[training-safe]"
    assert exported_turn["answer"] == "[training-safe]"
    assert trace["prompt_messages"] == [{"role": "system"}, {"role": "user"}]
    assert trace["graph_hits"][0] == {
        "node_id": "node_001",
        "rank": 1,
        "score": 0.88,
        "metadata": {},
    }
    tool = trace["tool_invocations"][0]
    assert tool["invocation_id"] == "invocation_001"
    assert tool["tool_id"] == "agronomic_calculator_v1"
    assert tool["status"] == "succeeded"
    assert tool["inputs"] == {}
    assert tool["result"] == {"result_id": "result_001", "status": "validated"}
    stages = trace["metadata"]["answer_stages"]
    assert stages["draft"] == {"sha256": _sha(CANARIES["draft"])}
    assert stages["post_verification"] == {"sha256": _sha(CANARIES["post_verification"])}
    assert stages["final"] == {"sha256": _sha(CANARIES["final"])}
    verification = trace["metadata"]["answer_verification"]
    assert verification == {
        "schema_version": "open_agronomy_agent.answer_verification.v1",
        "status": "validated",
        "triggered": True,
        "confidence": 0.93,
        "result_ids": ["result_001"],
    }
    packet = trace["metadata"]["evidence_fabric"]["evidence_packet"]
    assert packet["claims"] == [{"claim_id": "claim_001", "confidence": 0.82}]
    assert packet["sources"] == [{"source_id": "source_001", "rank": 1}]
    assert trace["metadata"]["extension_metadata"] == {
        "level_one": {"level_two": {}},
        "malformed_structural_fields": {},
        "disguised_known_keys": {},
    }
    assert trace["prompt_messages"][0]["role"] == "system"
    assert trace["tool_invocations"][0]["status"] == "succeeded"
    assert manifest["training_eligible"] is True
    assert manifest["training_exclusion_reason"] is None
    assert manifest["contains_personal_data"] is True
    assert manifest["contains_farm_identifiable_data"] is True
    assert manifest["contains_private_attachment_text"] is True


def test_training_safe_manifest_does_not_claim_eligibility_without_consent(tmp_path: Path) -> None:
    session, turn = _fixture_records(training_export_allowed=False)
    manifest, _ = build_export_bundle(
        session,
        _Store(turn),
        tmp_path,
        export_id="exp_training_without_consent",
        redaction_mode="training_safe",
        include_artifacts=False,
    )

    assert manifest["training_eligible"] is False
    assert manifest["training_exclusion_reason"] == "training export requires training_safe redaction and consent"


def test_unknown_subtree_cannot_regain_trust_by_reusing_known_field_names() -> None:
    payload = {
        "extension_metadata": {
            "user_id": CANARIES["known_user_id"],
            "status": CANARIES["known_status"],
            "source_id": CANARIES["known_source_id"],
        }
    }

    hashed = _sanitize_export_value(payload, "snippets_hashed")
    assert hashed == {
        "extension_metadata": {
            "user_id": _marker(CANARIES["known_user_id"]),
            "status": _marker(CANARIES["known_status"]),
            "source_id": _marker(CANARIES["known_source_id"]),
        }
    }
    assert _sanitize_export_value(payload, "training_safe") == {
        "extension_metadata": {}
    }
