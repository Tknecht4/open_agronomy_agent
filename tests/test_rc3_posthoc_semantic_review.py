from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_rc3_posthoc_semantic_review.py"


def _module():
    spec = importlib.util.spec_from_file_location("rc3_posthoc_semantic_review", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packet(root: Path, *, model: str, trial: str, base) -> None:
    directory = root / model / trial / "review_packets" / model
    directory.mkdir(parents=True)
    rows = []
    identity = []
    packet_offset = int(hashlib.sha256(f"{model}|{trial}".encode()).hexdigest()[:10], 16)
    for index in range(180):
        review_id = f"agr_{packet_offset + index:020x}"[-24:]
        rows.append({
            "review_id": review_id,
            "question": f"Question {index}?",
            "answer": f"Answer {index}.",
            "crop": "wheat",
            "jurisdiction": "Alberta",
            "task_family": "soils",
            "non_exhaustive_reference_points": ["Use a soil test."],
            "known_material_error_hypotheses": [],
            "critical_evidence": [],
            "safe_boundary": None,
            "reference_boundary": "non-exhaustive",
        })
        identity.append({"review_id": review_id, "source_label": "model_only", "eval_id": f"case-{index}", "answer_sha256": "a" * 64})
    phase = directory / "phase_b_reference_assisted.jsonl"
    phase.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    ids = directory / "private_identity_map.jsonl"
    ids.write_text("".join(json.dumps(row) + "\n" for row in identity), encoding="utf-8")
    (directory / "manifest.json").write_text(json.dumps({
        "schema_version": "open_agronomy_agent.agronomist_answer_review_packet.v1",
        "rows": 180,
        "phase_b": {"path": phase.name, "sha256": _sha(phase)},
        "identity_map": {"path": ids.name, "sha256": _sha(ids)},
    }), encoding="utf-8")


def test_prepare_builds_complete_opaque_selection(tmp_path: Path) -> None:
    module = _module()
    experiment = tmp_path / "experiment"
    for model in ("gemma3", "gemma4", "luna"):
        for trial in ("trial-001", "trial-002", "trial-003"):
            _packet(experiment, model=model, trial=trial, base=module)
    records, selection = module.prepare(experiment, tmp_path / "review")
    assert len(records) == 1620
    assert selection["row_count"] == 1620
    assert len(selection["records"]) == 1620
    assert selection["sha256"] == module._sha_text(module._canonical({key: value for key, value in selection.items() if key != "sha256"}))
    assert (tmp_path / "review" / "private_blinded_inputs.jsonl").is_file()


def test_authorization_rejects_wrong_selection_or_payload_taxonomy(tmp_path: Path) -> None:
    module = _module()
    selection = {"sha256": "a" * 64}
    payload = {
        "schema_version": module.AUTH_SCHEMA,
        "authorization_decision": "authorized",
        "authorization_source": "user",
        "authorized_by_key_id": "owner",
        "authorized_at": "2026-08-15T00:00:00Z",
        "expires_at": "2026-08-16T00:00:00Z",
        "recipient_backend": "codex_app_server_chatgpt_auth",
        "model_id": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "selection_manifest_sha256": "b" * 64,
        "judge_prompt_sha256": module._sha_text(module.BASE.judge_instructions("semantic_answer_quality")),
        "judge_output_schema_sha256": module._sha_text(module._canonical(module.BASE.judge_schema())),
        "authorized_payload_classes": list(module.PAYLOAD_CLASSES),
        "excluded_payload_classes": list(module.FORBIDDEN_CLASSES),
        "instruction_sources": [module.INSTRUCTION_SOURCE_TOKEN],
        "instruction_sources_sha256": "0" * 64,
        "claim_eligible": False,
    }
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="selection identity"):
        module.validate_authorization(path, selection)


def test_authorized_runner_keeps_app_server_clients_thread_local(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    created = []

    class FakeClient:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def close(self):
            return None

    monkeypatch.setattr(module, "CodexAppServerClient", FakeClient)
    runner = module.AuthorizedLunaRunner(
        authorization={"instruction_sources": [module.INSTRUCTION_SOURCE_TOKEN]},
        selection={},
        timeout_seconds=1,
    )
    assert runner._client() is runner._client()
    assert len(created) == 1
    assert created[0]["allowed_instruction_sources"] == (str((Path.home() / ".codex" / "AGENTS.md").resolve()),)


def test_truncated_opaque_review_id_is_repaired_only_when_unique() -> None:
    module = _module()
    expected = "sem_fe5750d6ff9d4d090214"
    payload = {"judgments": [{"review_id": "sem_5750d6ff9d4d090214"}]}
    text = "Blinded records:\n" + json.dumps([{"review_id": expected}])
    normalized = module.AuthorizedLunaRunner._normalize_review_ids(payload, text)
    assert payload["judgments"][0]["review_id"] == expected
    assert normalized == [{"received": "sem_5750d6ff9d4d090214", "canonical": expected}]
    ambiguous = {"judgments": [{"review_id": "sem_aaaaaaaaaaaaaaaa"}]}
    text = "Blinded records:\n" + json.dumps([{"review_id": "sem_00aaaaaaaaaaaaaaaa"}, {"review_id": "sem_11aaaaaaaaaaaaaaaa"}])
    assert module.AuthorizedLunaRunner._normalize_review_ids(ambiguous, text) == []
