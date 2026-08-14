from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
import pytest
import yaml

from agronomy_agent.agent import generate_answer, load_model_config, resolve_local_model_snapshot
from agronomy_agent.offline_readiness import build_offline_readiness
from agronomy_agent.runtime_profiles import DEFAULT_MODEL_CONFIG
from agronomy_agent.server.app import _demo_model_policy, create_app
from agronomy_agent.server.services.model_adaptation_service import model_adaptation_readiness
from agronomy_agent.server.services.model_decision_service import (
    CONFERENCE_MODEL_CONFIG_PATH,
    conference_model_decision,
)
from agronomy_agent.server.services.chat_service import _build_mlx_generator
from agronomy_agent.server.settings import build_settings
from agronomy_agent.training.postprocess_sft import build_parser as build_sft_parser
from scripts.download_model import (
    build_parser as build_download_parser,
    resolve_download_request,
)


class _StaticGenerator:
    def generate(self, messages: list[dict[str, str]]) -> str:
        return "The supplied source does not support an exact rate."


def test_generate_answer_can_explicitly_disable_self_verification(monkeypatch: Any) -> None:
    def unexpected_verify(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("answer verification should be disabled")

    monkeypatch.setattr("agronomy_agent.agent.verify_answer", unexpected_verify)

    answer, metadata = generate_answer(
        "Using only the supplied source, can an exact rate be recommended?",
        "agronomic_rag",
        _StaticGenerator(),
        verification_enabled=False,
    )

    assert answer == "The supplied source does not support an exact rate."
    assert "answer_verification" not in metadata


def test_gemma_profile_is_selectable_by_server_settings(tmp_path: Any) -> None:
    config_path = "configs/model_gemma4_e2b.yaml"
    config = load_model_config(config_path)
    settings = build_settings(
        db_path=tmp_path / "profile.sqlite3",
        artifact_root=tmp_path / "artifacts",
        model_config_path=config_path,
    )

    assert settings.model_config_path == config_path
    assert settings.default_model_id == "mlx-community/gemma-4-e2b-it-4bit"
    assert config["serving_label"] == "Gemma 4 E2B · Canadian verified"
    assert config["serving_max_tokens"] == 480
    assert config["answer_verification"] == {
        "enabled": True,
        "mode": "conference_selective",
        "model_id": "mlx-community/gemma-4-e2b-it-4bit",
        "max_tokens": 220,
        "max_evidence_chars": 9000,
    }

    profiles = {
        profile["id"]: profile
        for profile in TestClient(create_app(settings)).get("/api/configs").json()["model_profiles"]
    }
    gemma = profiles["mlx-community/gemma-4-e2b-it-4bit"]
    assert gemma["label"] == "Gemma 4 E2B · Canadian verified"
    assert gemma["role"] == "conference"
    assert gemma["max_tokens"] == 480


def test_repaired_gemma4_profile_is_versioned_without_mutating_preregistered_profile() -> None:
    historical = load_model_config("configs/model_gemma4_e2b.yaml")
    repaired = load_model_config("configs/model_gemma4_e2b_interface_v1.yaml")

    assert historical["answer_verification"]["mode"] == "conference_selective"
    assert repaired["model_id"] == historical["model_id"]
    assert repaired["model_revision"] == historical["model_revision"]
    assert repaired["answer_verification"]["mode"] == "model_agnostic_selective_v2"
    assert repaired["serving_quality_gate"] == "open_agronomy_system_interface_v1"
    assert repaired["intervention_profile"] == "balanced"


def test_conference_release_profile_matches_frozen_gemma4_benchmark_answer_controls() -> None:
    release = load_model_config("configs/model_gemma4_e2b_interface_v1.yaml")
    benchmark = load_model_config("configs/benchmark_models/gemma4_e2b.yaml")

    answer_controls = (
        "model_id",
        "model_revision",
        "max_tokens",
        "temperature",
        "top_p",
        "top_k",
        "seed",
        "intervention_profile",
    )
    assert {key: release.get(key) for key in answer_controls} == {
        key: benchmark.get(key) for key in answer_controls
    }
    verifier_controls = ("enabled", "mode", "model_id", "max_tokens", "max_evidence_chars")
    assert {
        key: release["answer_verification"].get(key) for key in verifier_controls
    } == {
        key: benchmark["answer_verification"].get(key) for key in verifier_controls
    }
    assert release["answer_verification"]["model_revision"] == release["model_revision"]


def test_gemma_270m_bounded_profile_is_single_model_and_revision_pinned() -> None:
    config = load_model_config("configs/model_gemma3_270m_bounded.yaml")

    assert config["model_id"] == "mlx-community/gemma-3-270m-it-4bit"
    assert config["assistant_model_id"] == config["model_id"]
    assert config["vlm_model_id"] is None
    assert config["model_revision"] == "ff1143e3a10547c9f2129e94ca37059b096b23f4"
    assert config["answer_verification"]["mode"] == "model_agnostic_selective_v2"
    assert config["answer_verification"]["model_id"] == config["model_id"]
    assert config["answer_verification"]["model_revision"] == config["model_revision"]
    assert config["intervention_profile"] == "constrained"


def test_pre_demo_profile_pins_every_selectable_local_model() -> None:
    config = load_model_config(DEFAULT_MODEL_CONFIG)

    assert config["model_revision"]
    assert config["assistant_model_revision"]
    assert config["serving_quality_gate"] == "open_agronomy_system_interface_v2"


def test_live_readiness_and_model_decision_defaults_use_release_profile(tmp_path: Any) -> None:
    assert CONFERENCE_MODEL_CONFIG_PATH == DEFAULT_MODEL_CONFIG

    offline = build_offline_readiness(
        root=tmp_path,
        runtime_manifest_path=tmp_path / "missing-runtime-manifest.json",
        hub_cache=tmp_path / "missing-hub-cache",
    )
    model_check = next(row for row in offline["checks"] if row["id"] == "model_snapshot")
    assert DEFAULT_MODEL_CONFIG in model_check["detail"]

    conference = conference_model_decision()
    adaptation = model_adaptation_readiness()
    if conference.get("available"):
        assert conference["active_runtime_configuration"]["config_path"] == DEFAULT_MODEL_CONFIG
    if adaptation.get("available"):
        assert (
            adaptation["conference_answer_model"]["active_runtime_configuration"]["config_path"]
            == DEFAULT_MODEL_CONFIG
        )


def test_bare_model_download_resolves_the_pinned_release_profile() -> None:
    model_id, revision = resolve_download_request(build_download_parser().parse_args([]))
    release = load_model_config(DEFAULT_MODEL_CONFIG)

    assert model_id == release["serving_model_id"]
    assert revision == release["model_revision"]


def test_server_model_identity_fails_closed_when_profile_has_no_model_id(tmp_path: Any) -> None:
    invalid_profile = tmp_path / "invalid-model.yaml"
    invalid_profile.write_text(yaml.safe_dump({"max_tokens": 64}), encoding="utf-8")
    settings = build_settings(
        db_path=tmp_path / "fail-closed.sqlite3",
        artifact_root=tmp_path / "artifacts",
        model_config_path=str(invalid_profile),
    )

    with pytest.raises(ValueError, match="does not define a serving model ID"):
        _ = settings.default_model_id


def test_demo_policy_names_the_active_release_model() -> None:
    active_model = load_model_config(DEFAULT_MODEL_CONFIG)["serving_model_id"]
    policy = _demo_model_policy(active_model)

    assert active_model in policy
    assert "Qwen3.5-2B" not in policy


def test_sft_postprocessor_requires_an_explicit_task_model() -> None:
    parser = build_sft_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--input-dir", "input", "--output-dir", "output"])
    args = parser.parse_args(
        [
            "--input-dir",
            "input",
            "--output-dir",
            "output",
            "--model",
            "mlx-community/training-target",
        ]
    )
    assert args.model == "mlx-community/training-target"


def test_generator_receives_revision_for_selected_profile(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    class CapturingGenerator:
        def __init__(self, model_id: str, **kwargs: Any) -> None:
            calls.append({"model_id": model_id, **kwargs})

    monkeypatch.setattr("agronomy_agent.server.services.chat_service.MLXGenerator", CapturingGenerator)
    config = {
        "model_id": "serving/model",
        "serving_model_id": "serving/model",
        "model_revision": "serving-revision",
        "assistant_model_id": "assistant/model",
        "assistant_model_revision": "assistant-revision",
    }

    _build_mlx_generator("serving/model", config)
    _build_mlx_generator("assistant/model", config)

    assert calls[0]["model_revision"] == "serving-revision"
    assert calls[1]["model_revision"] == "assistant-revision"


def test_local_snapshot_resolution_fails_closed_without_downloading(monkeypatch: Any) -> None:
    observed: dict[str, Any] = {}

    def unavailable_snapshot_download(**kwargs: Any) -> str:
        observed.update(kwargs)
        raise FileNotFoundError("not cached")

    monkeypatch.setattr("huggingface_hub.snapshot_download", unavailable_snapshot_download)

    try:
        resolve_local_model_snapshot("example/missing-model", revision="immutable-revision")
    except RuntimeError as exc:
        assert "No automatic download was attempted" in str(exc)
    else:
        raise AssertionError("missing local model should fail closed")
    assert observed["local_files_only"] is True
    assert observed["revision"] == "immutable-revision"
