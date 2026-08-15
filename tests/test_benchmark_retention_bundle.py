from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_benchmark_retention_bundle import (
    OUTER_COMPLETION_RECEIPT,
    PUBLIC_MATERIAL_ERROR_CODES,
    _csv_bytes,
    build_retention_bundle,
    sha256_file,
    verify_retention_bundle,
)
from scripts.build_full_system_benchmark_database import DDL


def _database(path, *, ddl: str = DDL) -> None:  # noqa: ANN001
    connection = sqlite3.connect(path)
    connection.executescript(ddl)
    connection.execute(
        "INSERT INTO model VALUES (?, ?, ?, ?, ?)",
        ("model-1", "candidate/model", "rev-1", "model.yaml", "a" * 64),
    )
    question = "What is one plus one?"
    connection.execute(
        "INSERT INTO benchmark_case VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "case-1",
            1,
            "benign_calculation",
            question,
            hashlib.sha256(question.encode()).hexdigest(),
            "{}",
            "{}",
            json.dumps({"benchmark_lane": "benign_answerability", "metric_role": "objective"}),
        ),
    )
    connection.execute(
        """
        INSERT INTO benchmark_run(
            run_id, model_key, mode, system_variant, outputs_path, outputs_sha256,
            summary_path, summary_sha256, row_count, context_packet_capture,
            is_canonical, run_identity_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("run-1", "model-1", "agronomic_rag", "full_system", "outputs.jsonl", "c" * 64, "summary.json", "d" * 64, 1, 1, 1, "{}"),
    )
    answer = "2"
    context_block = "private context"
    connection.execute(
        """
        INSERT INTO response(
            response_id, run_id, eval_id, ordinal, output, output_sha256,
            elapsed_seconds, exact_messages_json, context_block, context_block_sha256,
            field_context_json, score_json, metadata_json, route_json,
            verification_json, generation_stats_json, generation_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "response-1",
            "run-1",
            "case-1",
            1,
            answer,
            hashlib.sha256(answer.encode()).hexdigest(),
            0.1,
            '[{"role":"user","content":"private prompt"}]',
            context_block,
            hashlib.sha256(context_block.encode()).hexdigest(),
            "{}",
            '{"accuracy":100,"parse_valid":true}',
            "{}",
            "{}",
            '{"triggered":true,"intervention_action":"preserve_draft"}',
            '{"prompt_tokens":10,"generation_tokens":1}',
            "candidate_generation",
        ),
    )
    connection.execute(
        """
        INSERT INTO semantic_judgment VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "response-1",
            "judge/model",
            "judge-rev",
            "cross_model",
            "test",
            "valid",
            "pass",
            "high",
            95.0,
            json.dumps(
                {
                    "agronomic_accuracy": 4,
                    "decision_relevance": 4,
                    "completeness_actionability": 4,
                    "calibration_safety": 3,
                    "crop_region_source_fit": 4,
                }
            ),
            '["minor_calibration"]',
            "private rationale",
            0,
            "{}",
            '{"private":"judge output"}',
        ),
    )
    connection.commit()
    connection.close()


def test_content_addressed_retention_bundle_keeps_private_database_and_safe_dimensions(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    experiment = tmp_path / "experiment"
    judge_dir = experiment / "runs/model/full/semantic_judge/batches"
    judge_dir.mkdir(parents=True)
    (judge_dir / "batch_0001.prompt.txt").write_text("exact private judge prompt", encoding="utf-8")
    (judge_dir / "batch_0001.receipt.json").write_text('{"ok":true}\n', encoding="utf-8")

    report = build_retention_bundle(
        database=database,
        bundle_root=tmp_path / "retained",
        experiment_dir=experiment,
        implementation_commit="f" * 40,
    )

    bundle = tmp_path / "retained" / report["bundle_id"]
    assert report["status"] == "verified"
    assert sha256_file(bundle / "private/full_system_benchmark.sqlite3") == sha256_file(database)
    assert (bundle / "private/experiment/runs/model/full/semantic_judge/batches/batch_0001.prompt.txt").is_file()
    public_text = (bundle / "public_safe/response_measurements.csv").read_text(encoding="utf-8")
    assert "private prompt" not in public_text
    assert "private context" not in public_text
    assert "private rationale" not in public_text
    row = next(csv.DictReader(public_text.splitlines()))
    assert row["agronomic_accuracy"] == "4.0"
    assert row["answer_origin"] == "preserved_draft"
    assert row["private_response_record_link_sha256"]
    assert row["private_judgment_record_link_sha256"]
    assert row["question_link_sha256"]
    assert row["context_link_sha256"]
    assert json.loads(row["material_error_codes_json"]) == ["calibration_error"]
    assert (bundle / "private/retention_contract/build_benchmark_retention_bundle.py").is_file()
    assert (bundle / "private/retention_contract/benchmark_retention_bundle_v1.schema.json").is_file()
    assert verify_retention_bundle(bundle)["canonical_response_count"] == 1


def test_retention_verification_fails_if_canonical_database_is_removed(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    report = build_retention_bundle(database=database, bundle_root=tmp_path / "retained")
    bundle = tmp_path / "retained" / report["bundle_id"]
    (bundle / "private/full_system_benchmark.sqlite3").unlink()

    with pytest.raises(ValueError, match="missing:private/full_system_benchmark.sqlite3"):
        verify_retention_bundle(bundle)


def test_public_safe_error_export_never_copies_arbitrary_judge_text(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    connection = sqlite3.connect(database)
    canary = '=HYPERLINK("https://example.invalid","PRIVATE ANSWER SNIPPET")'
    connection.execute(
        "UPDATE semantic_judgment SET material_errors_json = ?",
        (json.dumps([canary, "missing current label authority"]),),
    )
    connection.commit()
    connection.close()

    report = build_retention_bundle(database=database, bundle_root=tmp_path / "retained")
    bundle = tmp_path / "retained" / report["bundle_id"]
    public_text = (bundle / "public_safe/response_measurements.csv").read_text(encoding="utf-8")
    row = next(csv.DictReader(public_text.splitlines()))
    codes = set(json.loads(row["material_error_codes_json"]))

    assert "PRIVATE ANSWER SNIPPET" not in public_text
    assert "HYPERLINK" not in public_text
    assert codes <= PUBLIC_MATERIAL_ERROR_CODES
    assert codes == {"missing_authority", "unclassified_material_error"}


def test_public_safe_projection_pseudonymizes_untrusted_metadata_and_low_entropy_content(
    tmp_path,
) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE model SET model_id = ?, model_revision = ?",
        ("PRIVATE_METADATA_CANARY", "PRIVATE_REVISION_CANARY"),
    )
    connection.execute(
        "UPDATE benchmark_case SET eval_metadata_json = ?",
        (json.dumps({"benchmark_lane": "PRIVATE_PROMPT_CANARY", "metric_role": "PRIVATE_ROLE"}),),
    )
    connection.commit()
    connection.close()

    report = build_retention_bundle(database=database, bundle_root=tmp_path / "retained")
    bundle = tmp_path / "retained" / report["bundle_id"]
    public_text = (bundle / "public_safe/response_measurements.csv").read_text(encoding="utf-8")
    row = next(csv.DictReader(public_text.splitlines()))

    for canary in (
        "PRIVATE_METADATA_CANARY",
        "PRIVATE_REVISION_CANARY",
        "PRIVATE_PROMPT_CANARY",
        "PRIVATE_ROLE",
        hashlib.sha256(b"2").hexdigest(),
    ):
        assert canary not in public_text
    assert row["model_id"].startswith("private_link_")
    assert row["model_revision"].startswith("private_link_")
    assert row["benchmark_lane"] == "unclassified"
    assert row["metric_role"] == "unclassified"


@pytest.mark.parametrize(
    ("statement", "parameters", "expected"),
    [
        (
            "UPDATE semantic_judgment SET semantic_score = ?",
            ("PRIVATE_SEMANTIC_TEXT_CANARY",),
            "semantic_score",
        ),
        (
            "UPDATE semantic_judgment SET dimensions_json = ?",
            (json.dumps({"agronomic_accuracy": "PRIVATE_DIMENSION_CANARY"}),),
            "dimensions.agronomic_accuracy",
        ),
        (
            "UPDATE response SET score_json = ?",
            (json.dumps({"accuracy": "PRIVATE_SCORE_CANARY", "parse_valid": True}),),
            "score.accuracy",
        ),
        (
            "UPDATE response SET score_json = ?",
            (json.dumps({"accuracy": 100, "parse_valid": "PRIVATE_BOOL_CANARY"}),),
            "score.parse_valid",
        ),
        (
            "UPDATE response SET generation_stats_json = ?",
            (json.dumps({"prompt_tokens": "PRIVATE_TOKEN_CANARY", "generation_tokens": 1}),),
            "generation.prompt_tokens",
        ),
        (
            "UPDATE response SET elapsed_seconds = ?",
            ("PRIVATE_TIMING_CANARY",),
            "elapsed_seconds",
        ),
        (
            "UPDATE response SET verification_json = ?",
            (json.dumps({"triggered": "PRIVATE_BOOLEAN_CANARY"}),),
            "verification.triggered",
        ),
    ],
)
def test_public_projection_rejects_non_typed_measurement_values(
    tmp_path,
    statement: str,
    parameters: tuple,
    expected: str,
) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    connection = sqlite3.connect(database)
    connection.execute(statement, parameters)
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match=expected):
        build_retention_bundle(database=database, bundle_root=tmp_path / "retained")


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("UPDATE response SET output_sha256 = '" + "0" * 64 + "'", "output stored sha256"),
        (
            "UPDATE response SET context_block_sha256 = '" + "0" * 64 + "'",
            "context_block stored sha256",
        ),
        (
            "UPDATE benchmark_case SET question_sha256 = '" + "0" * 64 + "'",
            "question stored sha256",
        ),
    ],
)
def test_retention_recomputes_private_content_hashes_before_linking_public_rows(
    tmp_path,
    statement: str,
    expected: str,
) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    connection = sqlite3.connect(database)
    connection.execute(statement)
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match=expected):
        build_retention_bundle(database=database, bundle_root=tmp_path / "retained")


def test_retention_rejects_weakened_semantic_judgment_schema(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    weakened = DDL.replace("judgment_json TEXT NOT NULL", "judgment_json TEXT")
    _database(database, ddl=weakened)
    connection = sqlite3.connect(database)
    connection.execute("UPDATE semantic_judgment SET judgment_json = NULL")
    connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="canonical linkage schema"):
        build_retention_bundle(database=database, bundle_root=tmp_path / "retained")


@pytest.mark.parametrize(
    "dangerous_value",
    [
        '=HYPERLINK("https://example.invalid","PRIVATE")',
        "+1+1",
        "-2+3",
        "@SUM(1,1)",
        "\t=1+1",
        "\r=1+1",
        "  =1+1",
        "\v=1+1",
        "\f=1+1",
        "\u00a0=1+1",
        "\ufeff=1+1",
    ],
)
def test_public_safe_csv_neutralizes_formula_cells_in_every_string_column(
    tmp_path,
    dangerous_value: str,
) -> None:
    rows = [{"identity": dangerous_value, "category": dangerous_value}]
    row = next(csv.DictReader(io.StringIO(_csv_bytes(rows).decode("utf-8"), newline="")))

    assert row["identity"] == "'" + dangerous_value
    assert row["category"] == "'" + dangerous_value


def test_outer_completion_receipt_is_not_a_self_referential_bundle_input(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    terminal = experiment / "benchmark_invocation.json"
    terminal.write_text('{"status":"execution_complete"}\n', encoding="utf-8")
    (experiment / OUTER_COMPLETION_RECEIPT).write_text("old outer receipt", encoding="utf-8")

    report = build_retention_bundle(
        database=database,
        bundle_root=tmp_path / "retained",
        experiment_dir=experiment,
    )
    bundle = tmp_path / "retained" / report["bundle_id"]
    retained_terminal = bundle / "private/experiment/benchmark_invocation.json"

    assert retained_terminal.read_bytes() == terminal.read_bytes()
    assert not (bundle / f"private/experiment/{OUTER_COMPLETION_RECEIPT}").exists()


def test_transient_run_lock_drift_does_not_change_retention_identity(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    experiment = tmp_path / "experiment"
    run_dir = experiment / "runs/model/full"
    run_dir.mkdir(parents=True)
    terminal = run_dir / "summary.json"
    terminal.write_text('{"status":"complete"}\n', encoding="utf-8")
    lock = run_dir / ".eval_run.lock"
    lock.write_text("worker=one\n", encoding="utf-8")

    first = build_retention_bundle(
        database=database,
        bundle_root=tmp_path / "retained",
        experiment_dir=experiment,
    )
    bundle = tmp_path / "retained" / first["bundle_id"]
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))

    lock.write_text("worker=two-with-a-different-size\n", encoding="utf-8")
    second = build_retention_bundle(
        database=database,
        bundle_root=tmp_path / "retained",
        experiment_dir=experiment,
    )

    assert second["bundle_id"] == first["bundle_id"]
    assert (
        bundle / "private/experiment/runs/model/full/summary.json"
    ).read_bytes() == terminal.read_bytes()
    assert not (bundle / "private/experiment/runs/model/full/.eval_run.lock").exists()
    assert all(
        not entry["path"].endswith("/.eval_run.lock")
        for entry in manifest["private_artifacts"]
    )


def test_retention_verifies_legitimate_zero_byte_experiment_artifact(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    empty_artifact = experiment / "empty.marker"
    empty_artifact.touch()

    report = build_retention_bundle(
        database=database,
        bundle_root=tmp_path / "retained",
        experiment_dir=experiment,
    )
    bundle = tmp_path / "retained" / report["bundle_id"]
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    retained = bundle / "private/experiment/empty.marker"
    entry = next(
        item
        for item in manifest["private_artifacts"]
        if item["path"] == "private/experiment/empty.marker"
    )

    assert report["status"] == "verified"
    assert retained.is_file()
    assert retained.stat().st_size == 0
    assert entry["bytes"] == 0
    assert entry["sha256"] == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize(
    "link_kind",
    ["experiment_root", "descendant_file", "descendant_directory"],
)
def test_retention_rejects_symlink_experiment_entries_without_creating_bundle(
    tmp_path,
    link_kind: str,
) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    real_experiment = tmp_path / "real-experiment"
    real_experiment.mkdir()
    experiment = real_experiment
    if link_kind == "experiment_root":
        experiment = tmp_path / "experiment-link"
        experiment.symlink_to(real_experiment, target_is_directory=True)
    elif link_kind == "descendant_file":
        target = tmp_path / "outside.txt"
        target.write_text("outside", encoding="utf-8")
        (experiment / "linked-file.txt").symlink_to(target)
    else:
        target = tmp_path / "outside-directory"
        target.mkdir()
        (target / "outside.txt").write_text("outside", encoding="utf-8")
        (experiment / "linked-directory").symlink_to(target, target_is_directory=True)
    bundle_root = tmp_path / "retained"

    with pytest.raises(ValueError, match="symlink"):
        build_retention_bundle(
            database=database,
            bundle_root=bundle_root,
            experiment_dir=experiment,
        )

    assert not bundle_root.exists()


def test_copy_drift_fails_before_atomic_bundle_publication(tmp_path, monkeypatch) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    artifact = experiment / "terminal.json"
    artifact.write_text('{"status":"complete"}\n', encoding="utf-8")
    bundle_root = tmp_path / "retained"
    real_copy2 = shutil.copy2
    drift_injected = False

    def copy_with_source_drift(source, destination):  # noqa: ANN001, ANN202
        nonlocal drift_injected
        if Path(source) == artifact.resolve() and not drift_injected:
            artifact.write_text(
                '{"status":"mutated-after-inventory"}\n',
                encoding="utf-8",
            )
            drift_injected = True
        return real_copy2(source, destination)

    monkeypatch.setattr(
        "scripts.build_benchmark_retention_bundle.shutil.copy2",
        copy_with_source_drift,
    )

    with pytest.raises(
        ValueError,
        match="size:private/experiment/terminal.json",
    ):
        build_retention_bundle(
            database=database,
            bundle_root=bundle_root,
            experiment_dir=experiment,
        )

    assert drift_injected is True
    assert bundle_root.is_dir()
    assert list(bundle_root.iterdir()) == []


def test_verifier_recomputes_content_address_identity_and_public_transform(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    report = build_retention_bundle(database=database, bundle_root=tmp_path / "retained")
    bundle = tmp_path / "retained" / report["bundle_id"]
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["identity"]["public_transform"]["policy_version"].endswith("projection.v3")
    assert manifest["identity"]["public_transform"]["builder_sha256"]
    assert manifest["identity"]["public_transform"]["rows_sha256"]
    manifest["identity"]["public_transform"]["rows_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="identity_payload"):
        verify_retention_bundle(bundle)


def test_privacy_boundary_is_schema_bound_and_cannot_be_rewritten(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    report = build_retention_bundle(database=database, bundle_root=tmp_path / "retained")
    bundle = tmp_path / "retained" / report["bundle_id"]
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["privacy_boundary"] = "All artifacts may be published."
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="privacy_boundary"):
        verify_retention_bundle(bundle)


def test_retained_builder_and_schema_can_verify_bundle_in_place(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    report = build_retention_bundle(database=database, bundle_root=tmp_path / "retained")
    bundle = tmp_path / "retained" / report["bundle_id"]
    retained_builder = bundle / "private/retention_contract/build_benchmark_retention_bundle.py"

    completed = subprocess.run(
        [sys.executable, str(retained_builder), "--verify", str(bundle)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "verified"


def test_verifier_recomputes_database_snapshot_instead_of_trusting_manifest(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    report = build_retention_bundle(database=database, bundle_root=tmp_path / "retained")
    bundle = tmp_path / "retained" / report["bundle_id"]
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database"]["counts"]["response"] = 999
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="database_snapshot"):
        verify_retention_bundle(bundle)


def test_verifier_regenerates_public_derivative_from_retained_database(tmp_path) -> None:
    database = tmp_path / "full_system_benchmark.sqlite3"
    _database(database)
    report = build_retention_bundle(database=database, bundle_root=tmp_path / "retained")
    bundle = tmp_path / "retained" / report["bundle_id"]
    public_csv = bundle / "public_safe/response_measurements.csv"
    manifest_path = bundle / "manifest.json"
    public_csv.write_text(public_csv.read_text(encoding="utf-8").replace("95.0", "5.0"), encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    public_entry = manifest["public_safe_artifacts"][0]
    public_entry["sha256"] = sha256_file(public_csv)
    public_entry["bytes"] = public_csv.stat().st_size
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="public_safe_regeneration"):
        verify_retention_bundle(bundle)
