from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from agronomy_agent.agent import MLXGenerator
from agronomy_agent.codex_app_server import (
    BENCHMARK_EGRESS_AUTHORIZED_PAYLOAD_CLASSES,
    BENCHMARK_EGRESS_AUTHORIZATION_SCHEMA,
    BENCHMARK_EGRESS_FORBIDDEN_PAYLOAD_CLASSES,
    BENCHMARK_EGRESS_PAYLOAD_CLASSES_BY_PHASE_AND_ARM,
)
from agronomy_agent.evals import (
    allocate_run_directory,
    build_observation_replication_receipt,
    build_parser,
    effective_sampling_config,
    exclusive_run_lock,
    load_partial_outputs,
    run_eval,
)
from scripts.run_open_agronomy_benchmark import _eval_command
from scripts.run_open_agronomy_benchmark import _load_egress_authorization
from scripts.run_open_agronomy_benchmark import _validate_external_execution_boundary
from scripts.run_open_agronomy_benchmark import _write_invocation
from scripts.run_codex_semantic_answer_judge import AppServerJudgeRunner, validate_judge_transport
from scripts.run_local_mlx_semantic_answer_judge import LocalMLXRunner
from scripts.build_benchmark_cost_ledger import build_ledger
from scripts.build_full_system_benchmark_database import build_database


_SUITE_CASE_CONTRACT_SHA256 = "c" * 64
_EGRESS_ARTIFACT_CONTRACT_SHA256 = "d" * 64
_STATIC_PROMPT_CONTRACT_SHA256 = "e" * 64


class _Tokenizer:
    def apply_chat_template(
        self,
        messages: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
        enable_thinking: bool,
    ) -> str:
        del add_generation_prompt, enable_thinking
        assert tokenize is False
        return messages[-1]["content"]


def _install_fake_mlx(monkeypatch: pytest.MonkeyPatch) -> tuple[list[int], list[tuple[int | None, int | None]]]:
    seed_calls: list[int] = []
    generation_windows: list[tuple[int | None, int | None]] = []
    state: dict[str, int | None] = {"seed": None}

    class FakeRandom:
        @staticmethod
        def seed(value: int) -> None:
            state["seed"] = value
            seed_calls.append(value)

    core = types.ModuleType("mlx.core")
    core.random = FakeRandom()  # type: ignore[attr-defined]
    mlx = types.ModuleType("mlx")
    mlx.core = core  # type: ignore[attr-defined]
    sample_utils = types.ModuleType("mlx_lm.sample_utils")
    sample_utils.make_sampler = lambda **kwargs: (lambda logits: logits)  # type: ignore[attr-defined]
    mlx_lm = types.ModuleType("mlx_lm")

    def generate(*args: Any, **kwargs: Any) -> str:
        del args, kwargs
        started_seed = state["seed"]
        time.sleep(0.01)
        finished_seed = state["seed"]
        generation_windows.append((started_seed, finished_seed))
        return f"sample-from-{started_seed}"

    mlx_lm.generate = generate  # type: ignore[attr-defined]
    mlx_lm.stream_generate = lambda *args, **kwargs: iter(())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx", mlx)
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    monkeypatch.setitem(sys.modules, "mlx_lm", mlx_lm)
    monkeypatch.setitem(sys.modules, "mlx_lm.sample_utils", sample_utils)
    return seed_calls, generation_windows


def _fake_generator(seed: int) -> MLXGenerator:
    generator = MLXGenerator(
        "fixture/model",
        seed=seed,
        temperature=0.8,
        top_p=0.85,
        top_k=20,
        use_stream_generate=False,
    )
    generator._model = object()
    generator._tokenizer = _Tokenizer()
    return generator


def _write_eval_inputs(tmp_path: Path, *, rows: int = 2) -> tuple[Path, Path]:
    suite = tmp_path / "suite.jsonl"
    suite.write_text(
        "".join(
            json.dumps(
                {
                    "eval_id": f"case-{index}",
                    "task_family": "replication",
                    "question": f"What should be checked for case {index}?",
                    "required_patterns": [],
                    "forbidden_patterns": [],
                }
            )
            + "\n"
            for index in range(rows)
        ),
        encoding="utf-8",
    )
    config = tmp_path / "model.yaml"
    config.write_text(
        "model_id: fixture/model\nmax_tokens: 32\ntemperature: 0.0\ntop_p: 0.9\ntop_k: 0\nseed: 42\n",
        encoding="utf-8",
    )
    return suite, config


def _write_egress_authorization(
    tmp_path: Path,
    **overrides: Any,
) -> tuple[Path, str, str]:
    now = dt.datetime.now(dt.UTC)
    benchmark_id = "fixture-benchmark"
    suite_sha256 = "a" * 64
    payload: dict[str, Any] = {
        "schema_version": BENCHMARK_EGRESS_AUTHORIZATION_SCHEMA,
        "authorization_decision": "authorized",
        "benchmark_id": benchmark_id,
        "benchmark_suite_sha256": suite_sha256,
        "recipient_backend": "codex_app_server_chatgpt_auth",
        "model_id": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "model_config_sha256": "b" * 64,
        "suite_case_contract_sha256": _SUITE_CASE_CONTRACT_SHA256,
        "egress_artifact_contract_sha256": _EGRESS_ARTIFACT_CONTRACT_SHA256,
        "static_prompt_contract_sha256": _STATIC_PROMPT_CONTRACT_SHA256,
        "authorization_source": "human-review-receipt-20260813",
        "authorized_by_key_id": "benchmark-authority-key-7",
        "authorized_at": (now - dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "authorized_payload_classes": list(BENCHMARK_EGRESS_AUTHORIZED_PAYLOAD_CLASSES),
        "excluded_payload_classes": list(BENCHMARK_EGRESS_FORBIDDEN_PAYLOAD_CLASSES),
        "payload_classes_by_phase_and_arm": {
            phase: {arm: list(classes) for arm, classes in arms.items()}
            for phase, arms in BENCHMARK_EGRESS_PAYLOAD_CLASSES_BY_PHASE_AND_ARM.items()
        },
    }
    payload.update(overrides)
    path = tmp_path / "egress-authorization.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, benchmark_id, suite_sha256


def _mock_args(
    suite: Path,
    config: Path,
    output_dir: Path,
    *,
    resume: Path | None = None,
    generation_seed: int = 101,
    trial_id: str = "trial-003",
) -> argparse.Namespace:
    values = [
        "--mode",
        "baseline",
        "--suite",
        str(suite),
        "--output-dir",
        str(output_dir),
        "--model-config",
        str(config),
        "--trial-id",
        trial_id,
        "--generation-seed",
        str(generation_seed),
        "--verification-seed",
        "1101",
        "--case-order-seed",
        "909",
        "--judge-seed",
        "707",
        "--capture-context-packets",
        "--mock",
    ]
    if resume is not None:
        values.extend(["--resume-run-dir", str(resume)])
    return build_parser().parse_args(values)


def test_mlx_same_seed_replays_and_different_seed_is_applied_inside_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_calls, windows = _install_fake_mlx(monkeypatch)
    messages = [{"role": "user", "content": "Question"}]
    first = _fake_generator(17)
    second = _fake_generator(29)

    assert first._generate_on_mlx_thread(messages) == "sample-from-17"
    assert first._generate_on_mlx_thread(messages) == "sample-from-17"
    assert second._generate_on_mlx_thread(messages) == "sample-from-29"

    assert seed_calls == [17, 17, 29]
    assert windows == [(17, 17), (17, 17), (29, 29)]
    receipt = second.last_generation_stats["seed_application"]
    assert receipt["status"] == "applied"
    assert receipt["applied_seed"] == 29
    assert receipt["application_point"] == "serialized_generation_lock_before_sampler"
    assert receipt["sampler"] == {
        "factory": "mlx_lm.sample_utils.make_sampler",
        "temperature": 0.8,
        "top_p": 0.85,
        "top_k": 20,
        "sampling_mode": "stochastic",
    }


def test_mlx_seed_and_generation_remain_atomic_under_concurrent_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, windows = _install_fake_mlx(monkeypatch)
    messages = [{"role": "user", "content": "Question"}]
    first = _fake_generator(3)
    second = _fake_generator(5)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outputs = list(
            executor.map(
                lambda generator: generator._generate_on_mlx_thread(messages),
                (first, second),
            )
        )

    assert outputs == ["sample-from-3", "sample-from-5"]
    assert windows == [(3, 3), (5, 5)]


def test_local_judge_shared_cache_is_bound_to_seed_and_sampler(tmp_path: Path) -> None:
    cache_dir = tmp_path / "judge-cache"

    def invoke(seed: int, name: str, *, forbid_generation: bool = False) -> LocalMLXRunner:
        runner = LocalMLXRunner(
            model_id="fixture/judge",
            model_revision="revision-one",
            max_tokens=32,
            seed=seed,
            shared_cache_dir=cache_dir,
        )
        if forbid_generation:
            runner.generator.generate = lambda messages: pytest.fail(  # type: ignore[method-assign]
                f"seed-bound cache unexpectedly missed for {messages!r}"
            )
        else:
            runner.generator.generate = lambda messages: json.dumps(  # type: ignore[method-assign]
                {"judgments": [], "message_count": len(messages)}
            )
        result_path = tmp_path / f"{name}.json"
        runner(
            prompt="Judge this frozen batch.",
            schema_path=tmp_path / "schema.json",
            result_path=result_path,
            model="fixture/judge",
            reasoning_effort="local_deterministic",
            cwd=tmp_path,
        )
        return runner

    seed_11 = invoke(11, "seed-11")
    seed_12 = invoke(12, "seed-12")
    seed_11_replay = invoke(11, "seed-11-replay", forbid_generation=True)

    assert seed_11.shared_cache_writes == 1
    assert seed_12.shared_cache_writes == 1
    assert seed_11_replay.shared_cache_hits == 1
    assert len(list(cache_dir.glob("*.json"))) == 2


def test_sampling_cli_overrides_are_explicit_and_do_not_mutate_config() -> None:
    args = build_parser().parse_args(
        [
            "--mode",
            "baseline",
            "--generation-seed",
            "19",
            "--verification-seed",
            "23",
            "--temperature",
            "0.7",
            "--top-p",
            "0.8",
            "--top-k",
            "40",
        ]
    )
    config = {"max_tokens": 64, "temperature": 0.0, "top_p": 0.9, "top_k": 0, "seed": 42}

    resolved = effective_sampling_config(args, config)

    assert resolved == {
        "max_tokens": 64,
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 40,
        "generation_seed": 19,
        "generation_seed_source": "cli_override",
        "verification_seed": 23,
        "verification_seed_source": "cli_override",
    }
    assert config["seed"] == 42


def test_deterministic_path_receipts_do_not_claim_model_sampling() -> None:
    receipt = build_observation_replication_receipt(
        eval_id="calc-1",
        sample_index=1,
        run_execution_id="run_one",
        run_identity_sha256="a" * 64,
        matched_key="b" * 64,
        replication_contract={
            "trial_id": "trial-1",
            "generation_seed": 42,
            "verification_seed": 142,
            "judge_seed": 242,
            "case_order": {"case_order_seed": 342},
        },
        process_identity={"process_execution_id": "proc_one"},
        cache_identity={"cache_epoch_id": "cache_one"},
        model_backend="mlx_local",
        metadata={"generation_path": "deterministic_tool_result"},
    )

    assert receipt["execution_kind"] == "deterministic_bypass"
    assert receipt["seed_application"]["status"] == "not_applied_generation_bypassed"
    assert receipt["seed_application"]["applied_seed"] is None
    assert (
        receipt["verification_seed_application"]["status"]
        == "not_applied_verification_bypassed"
    )
    assert receipt["verification_seed_application"]["applied_seed"] is None


def test_resume_preserves_run_identity_and_cannot_duplicate_completed_sample(tmp_path: Path) -> None:
    suite, config = _write_eval_inputs(tmp_path)
    output_root = tmp_path / "runs"
    assert run_eval(_mock_args(suite, config, output_root)) == 0
    run_dir = next(output_root.iterdir())
    initial_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    partial_rows = load_partial_outputs(run_dir / "outputs.partial.jsonl")
    (run_dir / "outputs.partial.jsonl").write_text(
        json.dumps(partial_rows[0]) + "\n",
        encoding="utf-8",
    )

    assert run_eval(_mock_args(suite, config, output_root, resume=run_dir)) == 0

    resumed_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    outputs = load_partial_outputs(run_dir / "outputs.jsonl")
    assert resumed_manifest["run_identity_sha256"] == initial_manifest["run_identity_sha256"]
    assert resumed_manifest["run_execution_id"] == initial_manifest["run_execution_id"]
    assert resumed_manifest["invocation_count"] == 2
    assert len(outputs) == 2
    assert len({row["observation_id"] for row in outputs}) == 2
    assert len({row["sample_index"] for row in outputs}) == 2
    assert len({row["replication"]["process_identity"]["process_execution_id"] for row in outputs}) == 2


def test_resume_rejects_a_changed_generation_seed(tmp_path: Path) -> None:
    suite, config = _write_eval_inputs(tmp_path, rows=1)
    output_root = tmp_path / "runs"
    assert run_eval(_mock_args(suite, config, output_root)) == 0
    run_dir = next(output_root.iterdir())

    with pytest.raises(ValueError, match="generation_config|replication_contract"):
        run_eval(
            _mock_args(
                suite,
                config,
                output_root,
                resume=run_dir,
                generation_seed=102,
            )
        )


def test_partial_loader_rejects_duplicate_observation_ids(tmp_path: Path) -> None:
    partial = tmp_path / "partial.jsonl"
    row = {"eval_id": "one", "observation_id": "obs-one"}
    partial.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate observation IDs"):
        load_partial_outputs(partial)


def test_run_directory_allocation_and_lock_are_concurrency_safe(tmp_path: Path) -> None:
    def allocate(index: int) -> Path:
        return allocate_run_directory(
            tmp_path,
            mode="baseline",
            trial_id="trial-1",
            run_execution_id=f"run_{index:032x}",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        paths = list(executor.map(allocate, range(8)))
    assert len(set(paths)) == 8
    with exclusive_run_lock(paths[0]):
        with pytest.raises(RuntimeError, match="already active"):
            with exclusive_run_lock(paths[0]):
                pass


def test_canonical_benchmark_launcher_threads_replication_and_sampling_options(tmp_path: Path) -> None:
    args = argparse.Namespace(
        mock=False,
        max_samples=None,
        model_base_url=None,
        request_model_id="default_model",
        codex_app_server=False,
        reasoning_effort="high",
        model_identity_receipt=None,
        egress_authorization=None,
        private_knowledge_policy="disabled",
        trial_id="trial-4",
        process_isolation_policy="fresh_process_per_run",
        cache_policy="no_prompt_cache",
        generation_seed=13,
        verification_seed=17,
        case_order_seed=19,
        judge_seed=23,
        temperature=0.6,
        top_p=0.75,
        top_k=30,
    )
    command = _eval_command(
        args=args,
        contract={
            "benchmark_id": "fixture-benchmark",
            "suite_path": "suite.jsonl",
            "max_tokens": 100,
            "rubric": "pattern",
            "answer_profile": "benchmark",
            "evaluation_partition": "internal",
            "rag_config": "rag.yaml",
        },
        model_config=tmp_path / "model.yaml",
        model_id="fixture/model",
        mode="baseline",
        output_dir=tmp_path / "runs",
    )

    rendered = " ".join(command)
    for expected in (
        "--trial-id trial-4",
        "--generation-seed 13",
        "--verification-seed 17",
        "--case-order-seed 19",
        "--judge-seed 23",
        "--temperature 0.6",
        "--top-p 0.75",
        "--top-k 30",
        "--process-isolation-policy fresh_process_per_run",
        "--cache-policy no_prompt_cache",
        "--private-knowledge-policy disabled",
    ):
        assert expected in rendered


def test_canonical_launcher_threads_codex_egress_identity_and_private_policy(
    tmp_path: Path,
) -> None:
    authorization = tmp_path / "egress.json"
    args = argparse.Namespace(
        mock=False,
        max_samples=None,
        model_base_url=None,
        request_model_id="default_model",
        codex_app_server=True,
        reasoning_effort="high",
        model_identity_receipt=None,
        egress_authorization=authorization,
        private_knowledge_policy="disabled",
        trial_id="trial-4",
        process_isolation_policy="fresh_process_per_run",
        cache_policy="no_prompt_cache",
        generation_seed=None,
        verification_seed=None,
        case_order_seed=None,
        judge_seed=None,
        temperature=None,
        top_p=None,
        top_k=None,
    )

    command = _eval_command(
        args=args,
        contract={
            "benchmark_id": "fixture-benchmark",
            "suite_path": "suite.jsonl",
            "max_tokens": 100,
            "rubric": "pattern",
            "answer_profile": "benchmark",
            "evaluation_partition": "internal",
            "rag_config": "rag.yaml",
        },
        model_config=tmp_path / "model.yaml",
        model_id="gpt-5.6-luna",
        mode="baseline",
        output_dir=tmp_path / "runs",
    )

    assert command[command.index("--egress-authorization") + 1] == str(authorization)
    assert command[command.index("--benchmark-id") + 1] == "fixture-benchmark"
    assert command[command.index("--private-knowledge-policy") + 1] == "disabled"
    assert command[command.index("--rag-config") + 1] == "rag.yaml"


def test_runner_rejects_codex_judge_and_private_overlay_egress() -> None:
    base = {
        "judge": False,
        "judge_backend": "mlx_local",
        "codex_app_server": True,
        "private_knowledge_policy": "disabled",
    }
    _validate_external_execution_boundary(argparse.Namespace(**base))

    with pytest.raises(ValueError, match="semantic judging is forbidden"):
        _validate_external_execution_boundary(
            argparse.Namespace(
                **{
                    **base,
                    "judge": True,
                    "judge_backend": "codex_app_server",
                }
            )
        )
    with pytest.raises(ValueError, match="private-knowledge-policy disabled"):
        _validate_external_execution_boundary(
            argparse.Namespace(**{**base, "private_knowledge_policy": "as_configured"})
        )

    with pytest.raises(ValueError, match="disabled by the selected benchmark contract"):
        _validate_external_execution_boundary(
            argparse.Namespace(**{**base, "judge": True}),
            contract={"judge": {"execution_allowed": False}},
        )
    _validate_external_execution_boundary(
        argparse.Namespace(**{**base, "judge": True}),
        contract={"judge": {"execution_allowed": True}},
    )


def test_standalone_app_server_judge_requires_a_future_dedicated_authorization() -> None:
    for transport in ("app-server", "exec"):
        with pytest.raises(ValueError, match="no dedicated judge-egress authorization"):
            validate_judge_transport(argparse.Namespace(transport=transport))
    with pytest.raises(RuntimeError, match="dedicated judge-egress authorization"):
        AppServerJudgeRunner()


def test_two_trials_remain_distinct_in_database_views_and_invocation_receipts(
    tmp_path: Path,
) -> None:
    suite, config = _write_eval_inputs(tmp_path, rows=2)
    experiment = tmp_path / "experiment"
    arm_root = experiment / "runs" / "fixture" / "baseline"
    assert run_eval(
        _mock_args(
            suite,
            config,
            arm_root,
            generation_seed=101,
            trial_id="trial-001",
        )
    ) == 0
    assert run_eval(
        _mock_args(
            suite,
            config,
            arm_root,
            generation_seed=202,
            trial_id="trial-002",
        )
    ) == 0

    report = build_database(experiment, experiment / "benchmark.sqlite3")
    assert report["run_count"] == 2
    assert report["response_count"] == 4
    connection = sqlite3.connect(experiment / "benchmark.sqlite3")
    try:
        assert connection.execute(
            "SELECT trial_id, generation_seed FROM benchmark_run ORDER BY trial_id"
        ).fetchall() == [("trial-001", 101), ("trial-002", 202)]
        assert connection.execute(
            "SELECT trial_id, response_count FROM model_arm_summary ORDER BY trial_id"
        ).fetchall() == [("trial-001", 2), ("trial-002", 2)]
        assert connection.execute(
            "SELECT COUNT(DISTINCT observation_id) FROM response"
        ).fetchone()[0] == 4
    finally:
        connection.close()

    base_invocation = {
        "benchmark_id": "fixture-benchmark",
        "model_id": "fixture/model",
        "model_revision": "revision",
    }
    _write_invocation(
        experiment,
        "fixture",
        {
            **base_invocation,
            "replication_contract": {"trial_id": "trial-001", "generation_seed": 101},
        },
    )
    _write_invocation(
        experiment,
        "fixture",
        {
            **base_invocation,
            "replication_contract": {"trial_id": "trial-002", "generation_seed": 202},
        },
    )
    assert sorted(path.name for path in (experiment / "invocations").glob("*.json")) == [
        "fixture__trial-001.json",
        "fixture__trial-002.json",
    ]
    latest_before_rejection = (experiment / "benchmark_invocation.json").read_text(
        encoding="utf-8"
    )
    with pytest.raises(ValueError, match="trial invocation identity changed"):
        _write_invocation(
            experiment,
            "fixture",
            {
                **base_invocation,
                "replication_contract": {
                    "trial_id": "trial-002",
                    "generation_seed": 999,
                },
            },
        )
    assert (
        experiment / "benchmark_invocation.json"
    ).read_text(encoding="utf-8") == latest_before_rejection


def test_cost_ledger_does_not_collapse_a_replayed_provider_receipt_across_trials(
    tmp_path: Path,
) -> None:
    experiment = tmp_path / "experiment"
    shared_receipt = {
        "requested_model": "gpt-5.6-luna",
        "selected_model": "gpt-5.6-luna",
        "turn_id": "provider-turn-replayed",
        "thread_id": "thread-one",
        "token_usage": {
            "last": {
                "inputTokens": 100,
                "cachedInputTokens": 0,
                "cacheWriteInputTokens": 0,
                "outputTokens": 20,
                "reasoningOutputTokens": 5,
                "totalTokens": 120,
            }
        },
    }
    for index, trial_id in enumerate(("trial-001", "trial-002"), start=1):
        run_dir = experiment / "runs" / "fixture" / "baseline" / f"run-{index}"
        run_dir.mkdir(parents=True)
        row = {
            "eval_id": "case-1",
            "trial_id": trial_id,
            "run_execution_id": f"run-{index}",
            "observation_id": f"obs-{index}",
            "metadata": {"generation_stats": {"app_server_receipt": shared_receipt}},
        }
        (run_dir / "outputs.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    manifest = build_ledger(
        experiment,
        experiment / "cost.sqlite3",
        experiment / "cost.json",
    )

    assert manifest["totals"]["calls"] == 2
    connection = sqlite3.connect(experiment / "cost.sqlite3")
    try:
        assert connection.execute(
            "SELECT trial_id, observation_id FROM usage_entry ORDER BY trial_id"
        ).fetchall() == [("trial-001", "obs-1"), ("trial-002", "obs-2")]
    finally:
        connection.close()


def test_completed_trial_receipt_cannot_be_silently_reused_or_overwritten(
    tmp_path: Path,
) -> None:
    experiment = tmp_path / "experiment"
    invocation = {
        "benchmark_id": "fixture-benchmark",
        "model_id": "fixture/model",
        "model_revision": "revision",
        "replication_contract": {"trial_id": "trial-001", "generation_seed": 101},
    }
    completed = {**invocation, "status": "execution_complete"}
    _write_invocation(experiment, "fixture", completed)
    durable_path = experiment / "invocations" / "fixture__trial-001.json"
    completed_bytes = durable_path.read_bytes()

    with pytest.raises(ValueError, match="trial invocation is already complete"):
        _write_invocation(experiment, "fixture", invocation)
    assert durable_path.read_bytes() == completed_bytes
    assert (experiment / "benchmark_invocation.json").read_bytes() == completed_bytes

    _write_invocation(
        experiment,
        "fixture",
        invocation,
        allow_completed_reuse=True,
    )
    assert durable_path.read_bytes() == completed_bytes
    assert json.loads(
        (experiment / "benchmark_invocation.json").read_text(encoding="utf-8")
    ).get("status") is None


def test_egress_authorization_v4_requires_exact_current_human_authority(
    tmp_path: Path,
) -> None:
    path, benchmark_id, suite_sha256 = _write_egress_authorization(tmp_path)

    receipt = _load_egress_authorization(
        path,
        benchmark_id=benchmark_id,
        benchmark_suite_sha256=suite_sha256,
        recipient_backend="codex_app_server_chatgpt_auth",
        model_id="gpt-5.6-luna",
        reasoning_effort="high",
        model_config_sha256="b" * 64,
        suite_case_contract_sha256=_SUITE_CASE_CONTRACT_SHA256,
        egress_artifact_contract_sha256=_EGRESS_ARTIFACT_CONTRACT_SHA256,
        static_prompt_contract_sha256=_STATIC_PROMPT_CONTRACT_SHA256,
    )

    assert receipt["authorization_decision"] == "authorized"
    assert receipt["authorization_source"] == "human-review-receipt-20260813"
    assert receipt["authorized_by_key_id"] == "benchmark-authority-key-7"
    assert receipt["schema_version"] == BENCHMARK_EGRESS_AUTHORIZATION_SCHEMA
    assert receipt["authorized_payload_classes"] == list(
        BENCHMARK_EGRESS_AUTHORIZED_PAYLOAD_CLASSES
    )
    assert receipt["excluded_payload_classes"] == list(
        BENCHMARK_EGRESS_FORBIDDEN_PAYLOAD_CLASSES
    )
    assert "path" not in receipt
    assert receipt["sha256"]


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        (
            {"schema_version": "open_agronomy_agent.benchmark_egress_authorization.v1"},
            "invalid benchmark egress authorization schema",
        ),
        (
            {"authorization_decision": "template_not_authorized"},
            "not authorized",
        ),
        (
            {"authorization_source": "REPLACE-WITH-AUTHORIZATION-SOURCE"},
            "missing non-placeholder provenance",
        ),
        (
            {"authorized_by_key_id": "example-authorizer"},
            "missing non-placeholder provenance",
        ),
        (
            {
                "authorized_at": "2026-08-13T00:00:00Z",
                "expires_at": "2026-08-13T00:01:00Z",
            },
            "expired or has an invalid interval",
        ),
        (
            {"authorized_at": "2026-08-13T00:00:00-06:00"},
            "authorized_at must be UTC",
        ),
        (
            {"authorized_payload_classes": []},
            "payload classes do not match the runtime contract",
        ),
        (
            {"authorized_payload_classes": "benchmark_questions"},
            "payload classes do not match the runtime contract",
        ),
        (
            {"excluded_payload_classes": ["farmer_records", ""]},
            "excluded classes do not match the runtime contract",
        ),
        (
            {"payload_classes_by_phase_and_arm": {}},
            "phase/arm payload map does not match runtime",
        ),
    ],
)
def test_egress_authorization_v4_fails_closed(
    tmp_path: Path,
    overrides: dict[str, Any],
    expected_error: str,
) -> None:
    path, benchmark_id, suite_sha256 = _write_egress_authorization(tmp_path, **overrides)

    with pytest.raises(ValueError, match=expected_error):
        _load_egress_authorization(
            path,
            benchmark_id=benchmark_id,
            benchmark_suite_sha256=suite_sha256,
            recipient_backend="codex_app_server_chatgpt_auth",
            model_id="gpt-5.6-luna",
            reasoning_effort="high",
            model_config_sha256="b" * 64,
            suite_case_contract_sha256=_SUITE_CASE_CONTRACT_SHA256,
            egress_artifact_contract_sha256=_EGRESS_ARTIFACT_CONTRACT_SHA256,
            static_prompt_contract_sha256=_STATIC_PROMPT_CONTRACT_SHA256,
        )
