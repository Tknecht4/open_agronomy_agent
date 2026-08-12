import json
import os
import re
from pathlib import Path

import pytest

from agronomy_agent.agent import AgentContext, format_answer_for_output_contract, generate_answer
from agronomy_agent.agent import OpenAICompatibleGenerator
from agronomy_agent.agno_runtime.local_index import RetrievedDoc
from agronomy_agent.evidence_handshake import EvidenceHandshake
from agronomy_agent.router import QueryRoute
from agronomy_agent.evals import (
    DEFAULT_RAG_CONFIG,
    aggregate,
    answer_profile_environment,
    build_parser,
    build_eval_generators,
    build_eval_field_context,
    build_implementation_identity,
    build_rag_artifact_identity,
    contains,
    enrich_eval_metadata_with_expected_source_trace,
    eval_question,
    forbidden_contains,
    load_partial_outputs,
    run_eval,
    parse_multiple_choice_answer,
    score_item,
    score_item_agribench_proxy,
    score_item_multiple_choice,
    score_item_numeric,
    score_item_reference_answer,
    validate_eval_item,
    validate_resume_identity,
    validate_resume_prefix,
)


def test_eval_field_context_normalizes_legacy_canadian_aliases() -> None:
    context = build_eval_field_context(
        {
            "eval_id": "legacy-context",
            "field_context": {"province": "Manitoba", "crop": "canola"},
        }
    )

    assert context["province_state"] == "Manitoba"
    assert context["crop_current"] == "canola"


def test_numeric_agronomic_calculation_requires_value_and_unit_contract() -> None:
    item = {
        "reference_numeric": 120.0,
        "reference_unit": "L/ha",
        "unit_aliases": ["L ha-1"],
        "absolute_tolerance": 1.0,
    }

    score = score_item_numeric("The calibrated output is 120 L/ha.", item)

    assert score["score"] == 100.0
    assert score["parsed_value"] == 120.0
    assert score["metric_role"] == "objective_agronomic_calculation_accuracy"


def test_eval_run_writes_hash_bound_identity_manifest(tmp_path: Path) -> None:
    suite = tmp_path / "suite.jsonl"
    suite.write_text(
        json.dumps(
            {
                "eval_id": "identity-1",
                "task_family": "identity",
                "question": "What field evidence is needed?",
                "required_patterns": [],
                "forbidden_patterns": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    model_config = tmp_path / "model.yaml"
    model_config.write_text("model_id: mock\nmax_tokens: 32\n", encoding="utf-8")
    output_dir = tmp_path / "runs"
    args = build_parser().parse_args(
        [
            "--mode",
            "baseline",
            "--suite",
            str(suite),
            "--output-dir",
            str(output_dir),
            "--model-config",
            str(model_config),
            "--mock",
        ]
    )

    assert run_eval(args) == 0

    run_dir = next(output_dir.iterdir())
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    output = json.loads((run_dir / "outputs.jsonl").read_text(encoding="utf-8"))
    assert len(manifest["suite_sha256"]) == 64
    assert len(manifest["model_config_sha256"]) == 64
    assert len(manifest["runner_sha256"]) == 64
    assert len(manifest["command_sha256"]) == 64
    assert len(manifest["outputs_sha256"]) == 64
    assert output["run_identity_sha256"] == manifest["run_identity_sha256"]
    assert summary["outputs_sha256"] == manifest["outputs_sha256"]


def test_eval_cli_defaults_to_submission_rag_configuration() -> None:
    args = build_parser().parse_args(["--mode", "agronomic_rag"])

    assert DEFAULT_RAG_CONFIG == "configs/rag_final_mvp.yaml"
    assert args.rag_config == DEFAULT_RAG_CONFIG


def test_rag_artifact_identity_binds_corpus_graph_and_policy_bytes(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    graph = tmp_path / "graph.json"
    policy = tmp_path / "policy.json"
    corpus.write_text('{"doc_id":"one"}\n', encoding="utf-8")
    graph.write_text('{"nodes":[]}\n', encoding="utf-8")
    policy.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.runtime_corpus_policy.v1",
                "default_eligibility": "quarantined",
                "corpora": [
                    {
                        "path": str(corpus),
                        "runtime_eligibility": "context_only",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class Resources:
        rag_config = {
            "retrieval": {
                "corpus_paths": [str(corpus)],
                "graph_paths": [str(graph)],
                "corpus_policy_manifest": str(policy),
            }
        }

    records = build_rag_artifact_identity(Resources())

    assert [record["kind"] for record in records] == ["corpus", "graph", "corpus_policy"]
    assert all(len(record["sha256"]) == 64 for record in records)
    assert all(record["size"] > 0 for record in records)


def test_rag_artifact_identity_excludes_quarantined_missing_corpora(tmp_path: Path) -> None:
    admitted = tmp_path / "admitted.jsonl"
    quarantined = tmp_path / "not-redistributed.jsonl"
    graph = tmp_path / "graph.json"
    policy = tmp_path / "policy.json"
    admitted.write_text('{"doc_id":"one"}\n', encoding="utf-8")
    graph.write_text('{"nodes":[]}\n', encoding="utf-8")
    policy.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.runtime_corpus_policy.v1",
                "default_eligibility": "quarantined",
                "corpora": [
                    {
                        "path": str(admitted),
                        "runtime_eligibility": "context_only",
                    },
                    {
                        "path": str(quarantined),
                        "runtime_eligibility": "quarantined",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    class Resources:
        rag_config = {
            "retrieval": {
                "corpus_paths": [str(admitted), str(quarantined)],
                "graph_paths": [str(graph)],
                "corpus_policy_manifest": str(policy),
            }
        }

    records = build_rag_artifact_identity(Resources())

    assert [record["path"] for record in records] == [
        str(admitted),
        str(graph),
        str(policy),
    ]


def test_rag_artifact_identity_rejects_missing_admitted_corpus(tmp_path: Path) -> None:
    admitted = tmp_path / "missing-admitted.jsonl"
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "schema_version": "open_agronomy_agent.runtime_corpus_policy.v1",
                "default_eligibility": "quarantined",
                "corpora": [
                    {
                        "path": str(admitted),
                        "runtime_eligibility": "context_only",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class Resources:
        rag_config = {
            "retrieval": {
                "corpus_paths": [str(admitted)],
                "corpus_policy_manifest": str(policy),
            }
        }

    with pytest.raises(FileNotFoundError, match="configured RAG corpus artifact is missing"):
        build_rag_artifact_identity(Resources())


def test_implementation_identity_binds_the_agent_source_tree() -> None:
    identity = build_implementation_identity()

    assert identity["scope"] == ["src/agronomy_agent/**/*.py", "scripts/run_eval.py"]
    assert identity["file_count"] > 20
    assert len(identity["sha256"]) == 64


def test_eval_can_use_the_same_openai_compatible_host_as_the_container() -> None:
    args = build_parser().parse_args(
        [
            "--mode",
            "agronomic_rag",
            "--model",
            "mlx-community/gemma-4-e2b-it-4bit",
            "--model-base-url",
            "http://127.0.0.1:8081/v1",
            "--request-model-id",
            "default_model",
            "--max-tokens",
            "512",
        ]
    )
    model_cfg = {
        "temperature": 0.0,
        "top_p": 0.9,
        "top_k": 0,
        "answer_verification": {"enabled": True, "max_tokens": 180},
    }

    generator, verifier, model_id, backend, request_model_id = build_eval_generators(args, model_cfg)

    assert isinstance(generator, OpenAICompatibleGenerator)
    assert isinstance(verifier, OpenAICompatibleGenerator)
    assert generator.endpoint == "http://127.0.0.1:8081/v1/chat/completions"
    assert generator.max_tokens == 512
    assert verifier.max_tokens == 180
    assert model_id == "mlx-community/gemma-4-e2b-it-4bit"
    assert backend == "openai_compatible_http"
    assert request_model_id == "default_model"


def test_eval_can_use_chatgpt_authenticated_codex_app_server(monkeypatch) -> None:
    created: list[dict[str, object]] = []

    class FakeAppServerGenerator:
        def __init__(self, **kwargs: object) -> None:
            created.append(dict(kwargs))

    monkeypatch.setattr("agronomy_agent.evals.CodexAppServerGenerator", FakeAppServerGenerator)
    args = build_parser().parse_args(
        [
            "--mode",
            "baseline",
            "--model",
            "gpt-5.6-luna",
            "--codex-app-server",
            "--reasoning-effort",
            "high",
        ]
    )
    model_cfg = {"answer_verification": {"enabled": False}}

    generator, verifier, model_id, backend, request_model_id = build_eval_generators(args, model_cfg)

    assert isinstance(generator, FakeAppServerGenerator)
    assert verifier is None
    assert created == [
        {
            "model_id": "gpt-5.6-luna",
            "reasoning_effort": "high",
            "timeout_seconds": 360.0,
        }
    ]
    assert model_id == "gpt-5.6-luna"
    assert backend == "codex_app_server_chatgpt_auth"
    assert request_model_id == "gpt-5.6-luna"


def test_raw_model_arm_has_no_kernel_and_preserves_unformatted_output() -> None:
    class RawGenerator:
        model_id = "fixture/raw"
        model_identity = {}
        last_generation_stats = {}

        def generate(self, messages):
            assert messages == [{"role": "user", "content": "Should I spray?"}]
            return "  RAW answer without the public answer contract  "

    output, metadata = generate_answer(
        "Should I spray?",
        "raw_model",
        RawGenerator(),
        capture_context_packet=True,
    )

    assert output == "RAW answer without the public answer contract"
    assert metadata["agent_kernel"] == {
        "active": False,
        "version": None,
        "system_prompt_sha256": None,
    }
    assert metadata["benchmark_generation_input"]["messages"] == [
        {"role": "user", "content": "Should I spray?"}
    ]


def test_eval_rejects_two_remote_model_backends() -> None:
    args = build_parser().parse_args(
        [
            "--mode",
            "baseline",
            "--model",
            "gpt-5.6-luna",
            "--codex-app-server",
            "--model-base-url",
            "http://127.0.0.1:8081/v1",
        ]
    )

    try:
        build_eval_generators(args, {"answer_verification": {"enabled": False}})
    except ValueError as exc:
        assert "mutually exclusive" in str(exc)
    else:
        raise AssertionError("expected conflicting backends to fail closed")


def test_eval_can_pin_a_different_local_verifier_revision() -> None:
    args = build_parser().parse_args(
        [
            "--mode",
            "agronomic_rag",
            "--model",
            "mlx-community/gemma-3-270m-it-4bit",
        ]
    )
    model_cfg = {
        "model_revision": "gemma-revision",
        "answer_verification": {
            "enabled": True,
            "model_id": "mlx-community/Qwen3.5-2B-OptiQ-4bit",
            "model_revision": "qwen-revision",
            "max_tokens": 240,
        },
    }

    generator, verifier, _, backend, _ = build_eval_generators(args, model_cfg)

    assert backend == "mlx_local"
    assert generator.model_revision == "gemma-revision"
    assert verifier.model_id == "mlx-community/Qwen3.5-2B-OptiQ-4bit"
    assert verifier.model_revision == "qwen-revision"
    assert verifier.max_tokens == 240


def test_generate_answer_preserves_backend_generation_telemetry() -> None:
    class Generator:
        last_generation_stats = {
            "backend": "openai_compatible_http",
            "generation_tokens": 42,
            "prompt_tokens": 200,
        }

        def generate(self, messages):
            return "Check the crop and field evidence before making the decision."

    _, metadata = generate_answer(
        "What should I check?",
        "baseline",
        Generator(),
        verification_enabled=False,
    )

    assert metadata["generation_stats"] == {
        "backend": "openai_compatible_http",
        "generation_tokens": 42,
        "prompt_tokens": 200,
    }


def test_generate_answer_context_packet_capture_is_explicit_and_local_only() -> None:
    class Generator:
        def generate(self, messages):
            return "Compare representative field observations before deciding."

    _, default_metadata = generate_answer(
        "What should I compare?",
        "baseline",
        Generator(),
        verification_enabled=False,
    )
    _, captured_metadata = generate_answer(
        "What should I compare?",
        "baseline",
        Generator(),
        verification_enabled=False,
        capture_context_packet=True,
    )

    assert "benchmark_generation_input" not in default_metadata
    packet = captured_metadata["benchmark_generation_input"]
    assert packet["distribution_scope"] == "machine_local_benchmark_only"
    assert packet["messages"][1] == {"role": "user", "content": "What should I compare?"}
    assert packet["context_block"] is None
    assert packet["retrieved_documents"] == []


def test_eval_parser_requires_opt_in_for_private_context_packet_capture() -> None:
    default_args = build_parser().parse_args(["--mode", "baseline"])
    capture_args = build_parser().parse_args(
        ["--mode", "agronomic_rag", "--capture-context-packets"]
    )

    assert default_args.capture_context_packets is False
    assert capture_args.capture_context_packets is True


def test_generate_answer_does_not_reuse_stale_verifier_telemetry_when_no_editor_call(monkeypatch) -> None:
    class Generator:
        last_generation_stats = {"generation_tokens": 40}

        def generate(self, messages):
            return "The evidence supports a concise answer."

    class Verifier:
        last_generation_stats = {"generation_tokens": 999, "elapsed_ms": 9999}

    class VerificationResult:
        answer = "The evidence supports a concise answer."
        editor_output = None

        def as_record(self):
            return {"triggered": False, "rewrite_accepted": False}

    monkeypatch.setattr(
        "agronomy_agent.agent.build_messages",
        lambda *args, **kwargs: ([{"role": "user", "content": "Question"}], None),
    )
    monkeypatch.setattr("agronomy_agent.agent.verify_answer", lambda *args, **kwargs: VerificationResult())

    _, metadata = generate_answer(
        "What does the evidence support?",
        "agronomic_rag",
        Generator(),
        verifier=Verifier(),
        verification_enabled=True,
    )

    assert metadata["answer_verification"]["triggered"] is False
    assert "verification_generation_stats" not in metadata


def test_benchmark_contract_is_bounded_and_rejects_checklist_scaffolding() -> None:
    from agronomy_agent.evals import BENCHMARK_ANSWER_OUTPUT_CONTRACT, BENCHMARK_SYSTEM_PROMPT

    assert "no more than 170 words" in BENCHMARK_ANSWER_OUTPUT_CONTRACT
    assert "exactly 2 brief paragraphs" in BENCHMARK_ANSWER_OUTPUT_CONTRACT
    assert "Do not use headings" in BENCHMARK_ANSWER_OUTPUT_CONTRACT
    assert "generic checklist" in BENCHMARK_ANSWER_OUTPUT_CONTRACT
    assert "do not paraphrase a formula into different arithmetic" in BENCHMARK_SYSTEM_PROMPT
    assert "complete value sequence" in BENCHMARK_ANSWER_OUTPUT_CONTRACT


def test_forbidden_patterns_allow_negated_advice() -> None:
    assert not forbidden_contains("Price alone is not enough to justify a fungicide pass.", "price alone")
    assert not forbidden_contains("A fungicide pass cannot be justified by price alone.", "price alone")
    assert not forbidden_contains("It is impossible to recommend a product or rate without the current label.", r"\brate\b")
    assert forbidden_contains("Spray because price alone justifies it.", "price alone")


def test_multiturn_eval_question_flattens_history() -> None:
    item = {
        "eval_id": "multi",
        "task_family": "regional_soil_weather",
        "turns": [
            {"role": "user", "content": "We are in Red River Valley spring wheat."},
            {"role": "assistant", "content": "What soil and weather issue is most relevant?"},
            {"role": "user", "content": "Heavy clay, saturated soil, rain tomorrow. Can we spray?"},
        ],
        "required_patterns": ["wind|rain"],
        "forbidden_patterns": [],
    }

    prompt = eval_question(item)

    assert "Conversation history" in prompt
    assert "Heavy clay" in prompt
    assert "Can we spray?" in prompt


def test_validate_eval_item_rejects_missing_patterns() -> None:
    bad = {"eval_id": "bad", "task_family": "x", "question": "What now?"}

    try:
        validate_eval_item(bad, source="inline")
    except ValueError as exc:
        assert "required_patterns" in str(exc)
    else:
        raise AssertionError("validate_eval_item should reject incomplete eval rows")


def test_score_item_exposes_missing_patterns() -> None:
    item = {
        "eval_id": "score",
        "task_family": "x",
        "question": "What now?",
        "required_patterns": ["soil test", "yield goal"],
        "ask_for_patterns": [],
        "forbidden_patterns": [],
    }

    score = score_item("Ask for a soil test.", item)

    assert score["required_hits"] == ["soil test"]
    assert score["missing_required_patterns"] == ["yield goal"]


def test_required_pattern_aliases_count_semantic_agronomy_equivalents() -> None:
    assert contains("The lime source lists calcium carbonate equivalent and fineness.", "CCE|ECCE|neutralizing value")
    assert contains("The problem is diagnosed from symptom location and soil tests.", "deficiency symptoms|diagnosis")
    assert contains("Bray and Olsen cannot be assumed interchangeable.", "do not convert|not interchangeable")
    assert contains("Verify the exact growth stage before treating.", "crop stage")
    assert contains("Measure root depth with a probe.", "rooting depth")
    assert contains("Check soil moisture readings and rainfall outlook.", "water use|stored soil moisture")
    assert contains("Review the previous herbicide program and survivors.", "field history|previous program")
    assert contains("Use NASS as a regional reference, not a field prediction.", "regional prior|benchmark|context")
    assert contains("Request field records, yield maps, and grower records.", "field yield records")
    assert contains("Measure saturated-paste soil EC and irrigation-water EC.", "soil test")
    assert contains("Measure saturated-paste soil EC and irrigation-water EC.", "irrigation water|water test")
    assert contains("Expected yield benefit must exceed crop-value and application-cost risk.", "yield potential|economics|ROI")
    assert contains("Check wind speed and direction near sensitive fields.", "wind direction")
    assert contains("Check wind speed and direction near sensitive fields.", "sensitive crop|downwind")
    assert contains("Validate the yield-response curve with check strips.", "expected response")


def test_agribench_proxy_score_reports_four_metrics() -> None:
    item = {
        "eval_id": "proxy",
        "task_family": "regional_nutrient_management",
        "question": "What should I check before changing nitrogen?",
        "crop": "corn",
        "required_patterns": ["soil test", "yield goal", "weather"],
        "ask_for_patterns": ["soil test"],
        "forbidden_patterns": ["guarantee"],
        "expected_tools": ["fertility_guard"],
    }
    output = "For corn, check the soil test, yield goal, recent weather, and nitrogen credits before changing the rate."

    score = score_item_agribench_proxy(output, item, {"tool_notes": ["fertility_guard"]})

    assert score["rubric"] == "agribench_proxy"
    assert score["proxy_valid"] is True
    assert score["promotion_eligible"] is False
    assert score["accuracy"] == 100.0
    assert score["relevance"] >= 90.0
    assert score["completeness"] == 100.0
    assert 0.0 <= score["conciseness"] <= 100.0


def test_agribench_proxy_is_undefined_without_a_lexical_contract() -> None:
    item = {
        "eval_id": "semantic_only",
        "task_family": "soil_sampling",
        "question": "How should the field be sampled?",
        "required_patterns": [],
        "ask_for_patterns": [],
        "forbidden_patterns": [],
    }
    score = score_item_agribench_proxy("Keep contrasting landscape positions separate.", item, {})
    assert score["proxy_valid"] is False
    assert score["score"] is None
    assert score["answer_quality_score"] is None

    summary = aggregate(
        [{"task_family": "soil_sampling", "score": score, "eval_metadata": {}}],
        mode="agronomic_rag",
        model_id="mock",
    )
    assert summary["mean_score"] is None
    assert summary["scored_samples"] == 0
    assert summary["unscored_samples"] == 1


def test_agribench_proxy_tool_credit_requires_trace_not_answer_vocabulary() -> None:
    item = {
        "eval_id": "proxy_field",
        "task_family": "regional_soil_water",
        "question": "What diagnostic steps fit traffic compaction?",
        "crop": "corn",
        "required_patterns": ["traffic pattern", "penetrometer|soil pit|probe", "soil moisture"],
        "ask_for_patterns": ["depth"],
        "forbidden_patterns": [],
        "expected_tools": ["field_data_guard"],
    }
    output = (
        "For corn, verify the traffic pattern, soil moisture, and depth of restriction with a probe, "
        "penetrometer, or soil pit before choosing controlled traffic."
    )

    score = score_item_agribench_proxy(output, item, {"tool_notes": []})

    assert score["completeness"] == 90.0
    assert score["tool_trace_audit"]["missing_local_guards"] == ["field_data_guard"]
    assert score["tool_trace_audit"]["answer_text_used_as_execution_evidence"] is False


def test_agribench_proxy_tool_credit_is_not_free_without_evidence() -> None:
    item = {
        "eval_id": "proxy_label",
        "task_family": "regional_product_stewardship",
        "question": "Can I spray?",
        "crop": "soybean",
        "required_patterns": ["soybean"],
        "ask_for_patterns": [],
        "forbidden_patterns": [],
        "expected_tools": ["label_guard"],
    }
    output = "For soybean, wait until the field is ready."

    score = score_item_agribench_proxy(output, item, {"tool_notes": []})

    assert score["completeness"] == 90.0


def test_eval_item_round_trips_json() -> None:
    item = {
        "eval_id": "json",
        "task_family": "x",
        "question": "What now?",
        "required_patterns": ["soil test"],
        "ask_for_patterns": [],
        "forbidden_patterns": [],
    }

    validate_eval_item(json.loads(json.dumps(item)), source="roundtrip")


def test_resume_prefix_round_trips_partial_outputs(tmp_path) -> None:
    suite = [
        {
            "eval_id": "one",
            "task_family": "x",
            "question": "What now?",
            "required_patterns": [],
            "forbidden_patterns": [],
        }
    ]
    row = {
        "eval_id": "one",
        "question": "What now?",
        "mode": "agronomic_rag",
        "model_id": "test-model",
        "answer_profile": "public",
    }
    partial = tmp_path / "outputs.partial.jsonl"
    partial.write_text(json.dumps(row) + "\n", encoding="utf-8")

    outputs = load_partial_outputs(partial)
    validate_resume_prefix(
        outputs,
        suite,
        mode="agronomic_rag",
        model_id="test-model",
        answer_profile="public",
    )

    assert outputs == [row]


def test_resume_prefix_rejects_a_different_suite() -> None:
    suite = [
        {
            "eval_id": "expected",
            "task_family": "x",
            "question": "What now?",
            "required_patterns": [],
            "forbidden_patterns": [],
        }
    ]
    outputs = [
        {
            "eval_id": "different",
            "question": "What now?",
            "mode": "agronomic_rag",
            "model_id": "test-model",
            "answer_profile": "public",
        }
    ]

    with pytest.raises(ValueError, match="does not match"):
        validate_resume_prefix(
            outputs,
            suite,
            mode="agronomic_rag",
            model_id="test-model",
            answer_profile="public",
        )


def test_resume_prefix_rejects_a_different_rag_configuration() -> None:
    suite = [
        {
            "eval_id": "one",
            "task_family": "x",
            "question": "What now?",
            "required_patterns": [],
            "forbidden_patterns": [],
        }
    ]
    outputs = [
        {
            "eval_id": "one",
            "question": "What now?",
            "mode": "agronomic_rag",
            "model_id": "test-model",
            "answer_profile": "public",
            "rag_config": "configs/rag.yaml",
        }
    ]

    with pytest.raises(ValueError, match="rag_config"):
        validate_resume_prefix(
            outputs,
            suite,
            mode="agronomic_rag",
            model_id="test-model",
            answer_profile="public",
            rag_config="configs/rag_final_mvp.yaml",
        )


def test_resume_identity_allows_only_command_digest_to_change(tmp_path) -> None:
    identity = {
        "suite_sha256": "suite",
        "model_config_sha256": "model",
        "implementation": {"sha256": "implementation"},
        "command_sha256": "first-command",
    }
    receipt = tmp_path / "resumable_run_identity.json"
    receipt.write_text(
        json.dumps({key: value for key, value in identity.items() if key != "command_sha256"}),
        encoding="utf-8",
    )

    validate_resume_identity(receipt, {**identity, "command_sha256": "resume-command"})


def test_resume_identity_rejects_changed_implementation(tmp_path) -> None:
    receipt = tmp_path / "resumable_run_identity.json"
    receipt.write_text(
        json.dumps(
            {
                "suite_sha256": "suite",
                "model_config_sha256": "model",
                "implementation": {"sha256": "old"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="implementation"):
        validate_resume_identity(
            receipt,
            {
                "suite_sha256": "suite",
                "model_config_sha256": "model",
                "implementation": {"sha256": "new"},
                "command_sha256": "resume-command",
            },
        )


def test_aggregate_reports_hardness_and_turn_type() -> None:
    rows = [
        {
            "task_family": "nutrient",
            "score": {"score": 100.0, "missing_required_patterns": []},
            "eval_metadata": {"hardness_bucket": "easy", "difficulty": "easy", "is_multi_turn": False, "expected_tools": []},
        },
        {
            "task_family": "nutrient",
            "score": {"score": 50.0, "missing_required_patterns": ["soil test"]},
            "eval_metadata": {"hardness_bucket": "expert", "difficulty": "expert", "is_multi_turn": True, "expected_tools": ["fertility_guard"]},
        },
    ]

    summary = aggregate(rows, mode="agronomic_rag", model_id="mock")

    assert summary["by_hardness"]["easy"]["mean_score"] == 100.0
    assert summary["by_hardness"]["expert"]["flagged_missing_required"] == 1
    assert summary["by_turn_type"]["multi_turn"]["mean_score"] == 50.0
    assert summary["by_expected_tool_count"]["1"]["samples"] == 1


def test_eval_metadata_records_expected_public_adapters_without_pretending_they_ran() -> None:
    item = {
        "eval_id": "stress_map",
        "task_family": "public_field_boundary",
        "question": "What should I check from this uploaded boundary?",
        "required_patterns": ["boundary"],
        "forbidden_patterns": [],
        "expected_tools": ["field_data_guard"],
        "expected_public_adapters": ["nrcs_soil_survey_geometry", "cropland_data_layer"],
        "public_source_lane": "map_geometry_quality_control",
        "scenario_type": "uploaded_geometry_quality_control",
    }

    metadata = enrich_eval_metadata_with_expected_source_trace({"tool_notes": []}, item)

    assert metadata["expected_public_adapters"] == ["nrcs_soil_survey_geometry", "cropland_data_layer"]
    assert metadata["tool_notes"] == []
    assert "field_data_guard" in metadata["route_tool_notes"]
    assert "missing_expected_tools" not in metadata
    assert metadata["tool_trace_refresh"]["source"] == "current_router_and_local_guard_registry"
    records = metadata["public_adapter_results"]
    assert {record["name"] for record in records} == {"nrcs_soil_survey_geometry", "cropland_data_layer"}
    assert {record["payload"]["status"] for record in records} == {"not_run_in_eval"}
    assert "not provider results" in metadata["source_trace_boundary"]
    assert "field point or boundary payload" in records[0]["payload"]["summary"]["not_run_reason"]


def test_eval_trace_refresh_uses_the_same_refined_route_as_generation() -> None:
    item = {
        "eval_id": "pest_with_incidental_fertility_context",
        "task_family": "pests",
        "question": (
            "Corn has manure history and tile drainage. For the reported pest pressure, should this field be treated? "
            "Give the scouting, pest-identification, economic-threshold, beneficial-insect, and current product-label evidence needed before acting."
        ),
        "required_patterns": [],
        "forbidden_patterns": [],
    }

    metadata = enrich_eval_metadata_with_expected_source_trace({"tool_notes": []}, item)

    assert metadata["route"]["question_type"] == "plant_health"
    assert metadata["route"]["required_tools"] == (
        "field_data_guard",
        "label_guard",
        "pesticide_safety_guard",
    )
    assert "fertility_guard" not in metadata["route_tool_notes"]
    assert "nutrient_4r_guard" not in metadata["route_tool_notes"]


def test_answer_profile_environment_switches_benchmark_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGRONOMY_AGENT_SYSTEM_PROMPT", "custom")
    monkeypatch.setenv("AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT", "custom contract")
    monkeypatch.setenv("AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION", "0")

    with answer_profile_environment("benchmark"):
        assert os.environ["AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION"] == "1"
        assert "agronomy benchmark" in os.environ["AGRONOMY_AGENT_SYSTEM_PROMPT"]
        assert "exactly 2 brief paragraphs" in os.environ["AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT"]
        assert "Do not use headings" in os.environ["AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT"]
        assert "termination timing and method" not in os.environ["AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT"]
        assert "avoid additional P or do not apply P" not in os.environ["AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT"]

    assert os.environ["AGRONOMY_AGENT_SYSTEM_PROMPT"] == "custom"
    assert os.environ["AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT"] == "custom contract"
    assert os.environ["AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION"] == "0"

    with answer_profile_environment("multiple_choice"):
        assert os.environ["AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION"] == "1"
        assert "multiple-choice" in os.environ["AGRONOMY_AGENT_SYSTEM_PROMPT"]
        assert os.environ["AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT"].startswith("Return exactly one Roman numeral")
        assert os.environ["AGRONOMY_AGENT_OBJECTIVE_RESPONSE_MODE"] == "multiple_choice"

    with answer_profile_environment("public"):
        assert "AGRONOMY_AGENT_SYSTEM_PROMPT" not in os.environ
        assert "AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT" not in os.environ
        assert "AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION" not in os.environ
        assert "AGRONOMY_AGENT_OBJECTIVE_RESPONSE_MODE" not in os.environ

    with answer_profile_environment("production"):
        assert "AGRONOMY_AGENT_SYSTEM_PROMPT" not in os.environ
        assert "AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT" not in os.environ
        assert "AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION" not in os.environ

    assert os.environ["AGRONOMY_AGENT_SYSTEM_PROMPT"] == "custom"
    assert os.environ["AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT"] == "custom contract"
    assert os.environ["AGRONOMY_AGENT_DISABLE_ANSWER_NORMALIZATION"] == "0"
    assert "AGRONOMY_AGENT_OBJECTIVE_RESPONSE_MODE" not in os.environ


def test_multiple_choice_profile_isolates_objective_output_from_advisory_postprocessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Generator:
        def generate(self, messages):
            return "III"

    def unexpected(*args, **kwargs):
        raise AssertionError("advisory hold, verifier, safety, and disclosure must not rewrite objective output")

    monkeypatch.setattr(
        "agronomy_agent.agent.build_messages",
        lambda *args, **kwargs: ([{"role": "system", "content": "Choose."}, {"role": "user", "content": "MCQ"}], None),
    )
    monkeypatch.setattr("agronomy_agent.agent._non_decisive_evidence_hold", unexpected)
    monkeypatch.setattr("agronomy_agent.agent.verify_answer", unexpected)
    monkeypatch.setattr("agronomy_agent.agent.enforce_answer_safety_postconditions", unexpected)
    monkeypatch.setattr("agronomy_agent.agent.apply_canadian_coverage_disclosure", unexpected)

    with answer_profile_environment("multiple_choice"):
        answer, metadata = generate_answer(
            "Which option is best?",
            "agronomic_rag",
            Generator(),
            verification_enabled=True,
        )

    assert answer == "III"
    assert metadata["objective_response_mode"] == "multiple_choice"
    assert metadata["objective_context_policy"] == {
        "candidate_context_used": False,
        "rejection_reason": "no_decision_grade_primary_evidence",
    }
    assert "answer_verification" not in metadata
    assert "evidence_sufficiency_gate" not in metadata


def test_rag_rejects_weak_candidate_from_generation_but_keeps_it_in_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rejected_text = "Wheat midge threshold content that does not fit this potato question."
    candidate = RetrievedDoc(
        doc_id="wrong_crop",
        title="Wrong-crop candidate",
        text=rejected_text,
        source="fixture",
        score=2.0,
        tags=("wheat",),
        namespaces=("plant_health",),
        source_type="applied_guidance",
        allowed_roles=("grower",),
        crops=("wheat",),
    )
    route = QueryRoute(
        question_type="plant_health",
        risk_level="low",
        namespaces=("plant_health",),
        required_tools=("field_data_guard",),
        answer_style="plain",
        audience="farmer",
        query_expansion=("diagnostic sample",),
        guidance="Keep a differential diagnosis until representative field evidence supports one cause.",
        knowledge_bucket="farmer_knowledge",
        knowledge_domains=("crop_management",),
    )
    handshake = EvidenceHandshake(
        decision="plant_health_diagnostic",
        preserve_entities=("potato",),
        required_entities=(),
        primary_doc_id=None,
        primary_title=None,
        supporting_doc_ids=(candidate.doc_id,),
        decisive_terms=(),
        primary_query_coverage=0.0,
        primary_relevance_score=0.0,
        evidence_roles=((candidate.doc_id, "supporting", "insufficient_fit"),),
    )
    context = AgentContext(
        retrieved_docs=[candidate],
        graph_hits=[],
        tool_notes=[],
        route=route,
        coverage_checklist=(),
        evidence_handshake=handshake,
    )

    class CapturingGenerator:
        messages: list[dict[str, str]] = []

        def generate(self, messages: list[dict[str, str]]) -> str:
            self.messages = messages
            return "The symptoms do not confirm late blight. Check representative plants and tubers before treatment."

    generator = CapturingGenerator()
    monkeypatch.setattr(
        "agronomy_agent.agent.build_messages",
        lambda *args, **kwargs: (
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": rejected_text},
            ],
            context,
        ),
    )

    answer, metadata = generate_answer(
        "Are collapsing potato tops enough to call late blight?",
        "agronomic_rag",
        generator,
        field_context={"crop_current": "potato", "province_state": "Alberta"},
        verification_enabled=False,
        capture_context_packet=True,
    )

    generation_input = generator.messages[-1]["content"]
    assert rejected_text not in generation_input
    assert "crop_current: potato" in generation_input
    assert "province_state: Alberta" in generation_input
    assert metadata["context_admission"] == {
        "candidate_retrieval_present": True,
        "candidate_retrieval_admitted": False,
        "policy": "kernel_and_field_context_only",
        "rejection_reason": "no_decision_grade_primary_evidence",
    }
    packet = metadata["benchmark_generation_input"]
    assert packet["context_block"] in generation_input
    assert packet["retrieved_documents"][0]["doc_id"] == "wrong_crop"
    assert "late blight" in answer.lower()


@pytest.mark.parametrize(
    ("output", "expected"),
    [("III", "III"), ("(IV). option text", "IV"), ("Answer: II", "II"), ("VI", "VI"), ("I think II", None), ("I, II, III, or IV", None), ("explanation only", None)],
)
def test_multiple_choice_parser_is_deterministic(output: str, expected: str | None) -> None:
    assert parse_multiple_choice_answer(output) == expected


def test_multiple_choice_score_is_objective_and_judge_free() -> None:
    item = {"eval_id": "mcq", "reference_answer": "III", "required_patterns": ["III"]}
    correct = score_item_multiple_choice("(III). Correct option", item)
    wrong = score_item_multiple_choice("II", item)
    assert correct["score"] == 100.0
    assert correct["exact_match"] is True
    assert wrong["score"] == 0.0
    assert wrong["exact_match"] is False
    assert correct["metric_role"] == "objective_multiple_choice_accuracy"


def test_reference_answer_score_is_transparent_non_promotional_overlap() -> None:
    item = {"eval_id": "reference", "reference_answer": "Mulch the soil to reduce erosion."}
    close = score_item_reference_answer("Mulch soil to reduce erosion.", item)
    unrelated = score_item_reference_answer("Scout the field before deciding.", item)

    assert close["reference_token_f1"] == 1.0
    assert close["score"] == 100.0
    assert unrelated["score"] == 0.0
    assert close["promotion_eligible"] is False
    assert "not a semantic-correctness" in close["score_note"]

def test_benchmark_profile_cannot_disable_unsupported_prescription_postcondition() -> None:
    class UnsafeGenerator:
        def generate(self, messages):
            return "Apply irrigation immediately from the regional index value."

    question = (
        "The AAFC Crop Stress Index is 80 for a Saskatchewan canola field. Use that value alone to prescribe "
        "the exact irrigation depth and timing without checking the crop, soil profile, rooting depth, rainfall, "
        "equipment, or field observations."
    )

    with answer_profile_environment("benchmark"):
        answer, metadata = generate_answer(
            question,
            "baseline",
            UnsafeGenerator(),
            verification_enabled=False,
        )

    assert answer.startswith("No.")
    assert "cannot support an exact irrigation depth or timing" in answer
    assert metadata["answer_safety_normalized"] is True


def test_benchmark_output_contract_splits_existing_content_into_two_paragraphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = "The first sentence gives the decision. The second explains why. The third gives the next action."
    with answer_profile_environment("benchmark"):
        formatted = format_answer_for_output_contract(answer)

    assert len(formatted.split("\n\n")) == 2
    assert " ".join(formatted.split()) == " ".join(answer.split())


def test_benchmark_output_contract_merges_postprocessing_disclosure_into_second_paragraph() -> None:
    answer = "Direct answer.\n\nPractical explanation.\n\nJurisdiction disclosure added after verification."

    with answer_profile_environment("benchmark"):
        formatted = format_answer_for_output_contract(answer)

    assert formatted.split("\n\n") == [
        "Direct answer.",
        "Practical explanation. Jurisdiction disclosure added after verification.",
    ]


def test_benchmark_output_contract_enforces_word_budget_at_sentence_boundary() -> None:
    first = " ".join(["decision"] * 90) + "."
    second = " ".join(["evidence"] * 70) + ". " + " ".join(["disclosure"] * 35) + "."

    with answer_profile_environment("benchmark"):
        formatted = format_answer_for_output_contract(first + "\n\n" + second)

    assert len(re.findall(r"\b\w+\b", formatted)) <= 170
    assert len(formatted.split("\n\n")) == 2
    assert formatted.endswith(".")


def test_public_output_contract_does_not_force_paragraph_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGRONOMY_AGENT_ANSWER_OUTPUT_CONTRACT", raising=False)
    answer = "The first sentence gives the decision. The second explains why."

    assert format_answer_for_output_contract(answer) == answer
