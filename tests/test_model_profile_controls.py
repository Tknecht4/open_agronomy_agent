from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from agronomy_agent.agent import generate_answer, load_model_config
from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings


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
