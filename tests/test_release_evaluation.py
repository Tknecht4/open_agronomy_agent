from copy import deepcopy
import json

import pytest

from agronomy_agent.release_evaluation import (
    DEFAULT_REGISTRY,
    ROOT,
    build_plan,
    checked_path,
    digest,
    load_registry,
    normalize_case,
    worker_case,
    write_new_json,
)


def test_complete_profiles_share_cohort_and_cells():
    registry = load_registry()
    baseline = build_plan(registry, profile="baseline", run_id="before")
    release = build_plan(registry, profile="release", run_id="after")
    assert baseline["cohort_sha256"] == release["cohort_sha256"]
    assert baseline["matrix"] == release["matrix"]
    assert baseline["counts"]["observations"] == 2 * baseline["counts"]["cases"]
    assert baseline["counts"]["lanes"]["agronomy"] == 256
    assert len(baseline["auxiliary_inputs"]) > 100
    admission_queue = (
        "data/manifests/provincial_applied_guidance_admission_queue_20260724.json"
    )
    assert (admission_queue in baseline["auxiliary_inputs"]) == (
        ROOT / admission_queue
    ).is_file()
    assert "data/seed/agronomy_knowledge_graph.json" in baseline["auxiliary_inputs"]
    assert any("us_nrcs/shards" in key for key in baseline["auxiliary_inputs"])


@pytest.mark.parametrize("profile", ["ci", "baseline", "release"])
def test_case_limit_never_makes_complete_profile(profile):
    with pytest.raises(ValueError, match="smoke"):
        build_plan(load_registry(), profile=profile, limit=1)


def test_smoke_limit_remains_explicitly_claim_ineligible():
    plan = build_plan(load_registry(), profile="smoke", limit=1)
    assert plan["counts"]["cases"] == 2
    assert plan["claim_eligible"] is False
    assert any(
        suite["selected_cases"] < suite["total_cases"] for suite in plan["suites"]
    )


def test_ci_is_harness_only_and_synthetic_faults_are_declared():
    plan = build_plan(load_registry(), profile="ci")
    assert plan["counts"]["lanes"] == {"harness": 30, "conversation": 6}
    assert all(cell["backend"] == "mock" for cell in plan["matrix"])
    assert set(plan["required_components"]) == {
        "instrument",
        "capability",
        "retrieval",
        "field_data",
        "product_contracts",
        "performance",
    }


def test_product_worker_never_receives_controller_gold():
    case = {
        "case_id": "a",
        "question": "What is needed?",
        "reference_answer": "SECRET",
        "semantic_rubric": "SECRET",
        "reference_numeric": 120,
        "reference_unit": "L/ha",
        "scoring": {"method": "numeric_tolerance"},
        "assertions": {"stage_states": {"draft_generation": "complete"}},
    }
    result = worker_case(case)
    assert set(result) == {"case_id", "question", "assertions"}
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update(claim_eligible=True),
        lambda row: row["required_components"].append("retrieval"),
        lambda row: row["profiles"]["baseline"].update(trials=1),
        lambda row: row["profiles"]["release"].update(trials=3),
        lambda row: row["profiles"]["baseline"].update(backend="mock"),
        lambda row: row["comparison_policy"].update(maximum_latency_p95_ratio=0),
        lambda row: row["retrieval_policy"].update(
            minimum_negative_control_compliance_rate=True
        ),
        lambda row: row["retrieval_policy"].clear(),
        lambda row: row["domain_policy"].update(required_review_coverage=float("nan")),
        lambda row: row.update(seed=True),
        lambda row: row["suites"][0].update(path="../secret.jsonl"),
    ],
)
def test_invalid_registry_is_not_a_pass(tmp_path, mutation):
    row = deepcopy(load_registry())
    mutation(row)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        load_registry(path)


def test_case_id_change_changes_cell_identity_without_gold_transport():
    suite = {"id": "suite", "format": "scenario", "exposure": "exposed_development"}
    row = {
        "case_id": "one",
        "scenario_family": "family",
        "lane": "agronomy",
        "question": "Q",
        "review_required": True,
    }
    a = normalize_case(row, suite)
    b = normalize_case({**row, "question": "Different"}, suite)
    assert a["case_sha256"] != b["case_sha256"]
    assert a["scenario_family"] == b["scenario_family"]


def test_legacy_metadata_does_not_claim_independent_scenarios():
    case = normalize_case(
        {"eval_id": "old", "question": "Q", "task_family": "fertility"},
        {"id": "old", "format": "legacy_domain", "exposure": "exposed_development"},
    )
    assert "not_independent" in case["family_origin"]
    assert case["review_required"] is True


def test_exclusive_json_and_no_nonfinite_or_escaped_inputs(tmp_path):
    path = tmp_path / "immutable.json"
    write_new_json(path, {"a": 1})
    with pytest.raises(FileExistsError):
        write_new_json(path, {"a": 2})
    with pytest.raises(ValueError):
        digest({"unknown": float("nan")})
    with pytest.raises(ValueError):
        checked_path(ROOT, str((tmp_path / "secret").resolve()))
