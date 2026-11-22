from copy import deepcopy
import hashlib
import json

import pytest

from agronomy_agent.release_evaluation import (
    DEFAULT_REGISTRY,
    FINAL_REGISTRY,
    ROOT,
    build_plan,
    checked_path,
    digest,
    load_registry,
    normalize_case,
    worker_case,
    write_new_json,
    bind_controller_inputs,
    read_controller_inputs,
    task_input_contract,
    validate_task_exposure,
    read_stop_policy,
    bind_stop_policy,
)


def test_final_catalog_accounts_for_prepared_and_retained_inputs():
    entries = json.loads(FINAL_REGISTRY.read_text())["entries"]
    root = ROOT / "data/eval"
    declared = {entry["path"] for entry in entries if entry["path"].startswith("data/eval/")}
    assert declared == {path.relative_to(ROOT).as_posix() for path in root.rglob("*.jsonl")}
    by_id = {entry["id"]: entry for entry in entries}
    assert {key: by_id[key]["rows"] for key in (
        "release_harness_v1", "successor_development", "scientific_reference",
        "cca_repaired_reference", "refusal_crop_scope_regressions",
        "open_agronomy_external_agroqa_v1", "agrillm_external", "v3_canadian_regional",
    )} == {
        "release_harness_v1": 36, "successor_development": 256, "scientific_reference": 240,
        "cca_repaired_reference": 28, "refusal_crop_scope_regressions": 48,
        "open_agronomy_external_agroqa_v1": 256, "agrillm_external": 800,
        "v3_canadian_regional": 72,
    }


def test_final_scorer_identity_binds_coverage_implementation(monkeypatch):
    import agronomy_agent.release_evaluation as evaluation

    registry = load_registry()
    registry["final_inventory"] = [
        {**suite, "sha256": evaluation.file_digest(ROOT / suite["path"])}
        for suite in registry["suites"]
    ]
    before = build_plan(registry, profile="baseline")
    original_digest = evaluation.file_digest
    monkeypatch.setattr(evaluation, "file_digest", lambda path: (
        "f" * 64 if path == ROOT / evaluation.FINAL_SCORER_FILE else original_digest(path)
    ))
    after = build_plan(registry, profile="baseline")
    assert before["cohort_sha256"] == after["cohort_sha256"]
    assert before["scorer_sha256"] != after["scorer_sha256"]


def test_copied_or_narrowed_catalog_cannot_impersonate_the_final_suite(tmp_path):
    copy = tmp_path / "alternate.json"
    copy.write_bytes(FINAL_REGISTRY.read_bytes())
    with pytest.raises(ValueError, match="canonical catalog path"):
        load_registry(copy)


@pytest.mark.parametrize("change, error", [
    ("new_input", "lack a catalog entry"),
    ("missing", "missing or escaped registry input"),
    ("truncated", "row count changed"),
    ("different_copy", "source copy differs"),
    ("changed_retained_bytes", "input hash changed"),
])
def test_final_catalog_blocks_scope_or_identity_drift(tmp_path, change, error):
    from agronomy_agent.final_evaluation import FINAL_SUITE_ID, final_registry

    rows = [{"eval_id": "case", "question": "What is the record date?", "reference_answer": "Use the record."}]
    content = json.dumps(rows[0]) + "\n"
    paths = {
        "inputs": "data/eval/prepared.jsonl",
        "copy": "data/eval/prepared_source.jsonl",
        "retained": "outputs/frozen.jsonl",
    }
    for name, path in paths.items():
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    base_registry = tmp_path / DEFAULT_REGISTRY.relative_to(ROOT)
    base_registry.parent.mkdir()
    base_registry.write_bytes(DEFAULT_REGISTRY.read_bytes())
    catalog = {
        "suite_id": FINAL_SUITE_ID,
        "whole_run_timeout_seconds": 1000,
        "entries": [
            {"id": "inputs", "path": paths["inputs"], "rows": 1, "execution": "prepared_question"},
            {"id": "copy", "path": paths["copy"], "rows": 1, "execution": "source_copy", "covered_by": "inputs"},
            {"id": "retained", "path": paths["retained"], "rows": 1, "execution": "prepared_question",
             "sha256": hashlib.sha256(content.encode()).hexdigest()},
        ],
    }
    registry = final_registry(catalog, root=tmp_path)
    assert [suite["id"] for suite in registry["suites"]] == ["inputs", "retained"]
    case = normalize_case(rows[0], registry["suites"][0])
    assert case["case_sha256"] == digest(rows[0])
    assert worker_case(case)["question"] == rows[0]["question"]
    assert "reference_answer" not in worker_case(case)
    with pytest.raises(ValueError, match="requires baseline or release"):
        build_plan(registry, root=tmp_path, profile="smoke")
    with pytest.raises(ValueError, match="case limits"):
        build_plan(registry, root=tmp_path, profile="baseline", limit=1)
    if change == "new_input":
        (tmp_path / "data/eval/new.jsonl").write_text(content)
    elif change == "missing":
        (tmp_path / paths["retained"]).unlink()
    elif change == "truncated":
        (tmp_path / paths["inputs"]).write_text("")
    elif change == "different_copy":
        (tmp_path / paths["copy"]).write_text(content.replace("record date", "sample date"))
    else:
        (tmp_path / paths["retained"]).write_text(content + "\n")
    with pytest.raises(ValueError, match=error):
        final_registry(catalog, root=tmp_path)


@pytest.mark.parametrize("override", [{"extra": True}, {"finalization_reserve_seconds": 10},
    {"finalization_reserve_seconds": True}, {"file_hardcap_bytes": False},
    {"minimum_free_bytes": 0}, {"require_termination": "yes"},
    {"retention_budget_bytes": 1024}])
def test_order3_stop_policy_refuses_invalid_contract_before_binding(tmp_path, override):
    value = {"schema_version": "open_agronomy_agent.bounded_stop_policy.v1",
             "finalization_reserve_seconds": 15, "retention_budget_bytes": 4096,
             "finalization_reserve_bytes": 1024, "minimum_free_bytes": 1,
             "file_hardcap_bytes": 1024, "require_model_identity": True,
             "require_termination": True, **override}
    path = tmp_path / "stop.json"; path.write_text(json.dumps(value))
    with pytest.raises(ValueError): read_stop_policy(path)


def test_order3_stop_policy_has_exact_bytes_and_finite_reserve(tmp_path):
    value = {"schema_version": "open_agronomy_agent.bounded_stop_policy.v1",
             "finalization_reserve_seconds": 15, "retention_budget_bytes": 4096,
             "finalization_reserve_bytes": 1024, "minimum_free_bytes": 1,
             "file_hardcap_bytes": 1024, "require_model_identity": True,
             "require_termination": True}
    path = tmp_path / "stop.json"; path.write_text(json.dumps(value))
    item = read_stop_policy(path)
    bound = bind_stop_policy({}, item, 30)
    assert bound["bounded_stop_policy"]["sha256"] == __import__('hashlib').sha256(path.read_bytes()).hexdigest()
    assert bound["bounded_stop_policy"]["bytes"] == len(path.read_bytes())
    with pytest.raises(ValueError, match="whole run budget"): bind_stop_policy({}, item, 15)


def _controller_packet(tmp_path):
    from test_release_eval_model_metrics import packet
    from agronomy_agent.release_eval_model_metrics import rubric_digest
    plan, rows, rubrics, reviews, policy = packet()
    for index, case in enumerate(plan["cases"]):
        raw = {"case_id": case["case_id"], "scenario_family": "synthetic_arithmetic", "lane": "harness",
               "question": 'Add the supplied toy counts.\nSupplied facts: {"a":2,"b":3}',
               "field_context": {"a": 2, "b": 3}, "assertions": {}, "review_required": True}
        case.update(raw, case_sha256=digest(raw), suite_id="qa")
        rubric = rubrics[index]
        rubric["case_sha256"] = case["case_sha256"]
        rubric["criteria"][0]["description"] = "CONTROLLER_ONLY synthetic rubric"
        rubric["rubric_sha256"] = rubric_digest(rubric)
        for cell, row, review in zip(plan["matrix"][index * 2:index * 2 + 2], rows[index * 2:index * 2 + 2], reviews[index * 2:index * 2 + 2]):
            cell.update(case_sha256=case["case_sha256"], backend="mock")
            row.update(case_sha256=case["case_sha256"])
            review.update(case_sha256=case["case_sha256"], rubric_sha256=rubric["rubric_sha256"])
    plan["model"] = {"id": "fixture_model", "revision": "fixture_revision"}
    rubric_path, policy_path = tmp_path / "rubrics.jsonl", tmp_path / "policy.json"
    rubric_path.write_text("".join(json.dumps(r) + "\n" for r in rubrics))
    policy_path.write_text(json.dumps(policy))
    inputs = read_controller_inputs(rubrics_path=rubric_path, policy_path=policy_path)
    plan = bind_controller_inputs(plan, inputs, "synthetic-explicit-cohort-v1")
    for row in rows:
        case = next(case for case in plan["cases"] if case["case_id"] == row["case_id"])
        row.update(task_exposure=_task_exposure(case, row["arm_id"]),
                   task_input_sha256=task_input_contract(case)["task_input_sha256"],
                   comparison_cohort="synthetic-explicit-cohort-v1")
    return plan, rows, rubrics, reviews, policy, inputs


def _task_exposure(case, arm):
    from agronomy_agent.release_eval_executor import compile_case_field_context
    contract = task_input_contract(case)
    compiled, aliases = compile_case_field_context(contract["field_context"])
    requests = []
    for question in contract["requests"]:
        item = {"message": question, "field_context_delivered": compiled}
        if arm in {"raw_model", "kernel_only"}:
            item.update(field_context_delivered=None,
                        prompt_messages=([{"role": "system", "content": "Synthetic kernel recipe"}] if arm == "kernel_only" else []) + [{"role": "user", "content": question}])
        requests.append(item)
    receipt = {"schema_version": "open_agronomy_agent.task_exposure.v1", "arm_id": arm,
               "worker_case_sha256": digest(worker_case(case)), "requests": requests,
               "compiled_field_context_sha256": digest(compiled), "field_alias_receipt": aliases}
    receipt["receipt_sha256"] = digest(receipt)
    return receipt


def test_controller_freeze_raw_and_canonical_identity_and_gold_isolation(tmp_path):
    plan, rows, rubrics, reviews, policy, inputs = _controller_packet(tmp_path)
    assert plan["controller_inputs"]["files"]["policy"]["canonical_sha256"] == digest(policy)
    assert plan["model_scoring_policy_sha256"] == digest(policy)
    assert plan["controller_inputs"]["files"]["policy"]["sha256"] != digest(policy)
    assert all("CONTROLLER_ONLY" not in json.dumps(worker_case(case)) for case in plan["cases"])
    for row in rows:
        case = next(case for case in plan["cases"] if case["case_id"] == row["case_id"])
        assert validate_task_exposure(case, row["arm_id"], row["task_exposure"])["task_input_sha256"] == row["task_input_sha256"]


@pytest.mark.parametrize("question,context,matched", [
    ('Toy task', {}, True), ('Toy task.\nSupplied facts: {"a":1}', {"a": 1}, True),
    ('Toy task', {"a": 1}, False), ('Toy task.\nSupplied facts: {"a":true}', {"a": 1}, False),
    ('Toy task.\nSupplied facts: {"a":1}', {"a": 1, "b": 2}, False),
    ('Toy task. Example: "{\\"a\\":1}"', {"a": 1}, False),
    ('Toy task.\nSupplied facts: {"a":1,"a":1}', {"a": 1}, False),
    ('Toy task.\nSupplied facts: {"a":NaN}', {"a": 1}, False),
])
def test_shared_task_requires_exact_typed_whole_inline_facts(question, context, matched):
    result = task_input_contract({"question": question, "field_context": context})
    assert (result["task_input_sha256"] is not None) is matched


def test_multiturn_and_conflicting_aliases_are_unmatched():
    assert task_input_contract({"turns": ["Toy first", "Toy next"]})["task_input_sha256"] is None
    context = {"province": True, "jurisdiction": 1}
    question = "Toy question.\nSupplied facts: " + json.dumps(context)
    assert task_input_contract({"question": question, "field_context": context})["status"] == "unknown_alias_conflict"
    with pytest.raises(ValueError, match="user turns"):
        task_input_contract({"turns": [{"role": "assistant", "content": "Toy"}]})


def test_trailing_example_is_not_declared_supplied_facts():
    case = {"question": 'Do NOT use this example: {"area_ha":2}', "field_context": {"area_ha": 2}}
    assert task_input_contract(case)["task_input_sha256"] is None


@pytest.mark.parametrize("target", ["compiled", "alias_input", "alias_mapping"])
def test_false_compiler_or_alias_receipt_pins_refuse(tmp_path, target):
    plan, rows, *_ = _controller_packet(tmp_path)
    receipt = deepcopy(rows[0]["task_exposure"])
    if target == "compiled": receipt["compiled_field_context_sha256"] = "f" * 64
    if target == "alias_input": receipt["field_alias_receipt"]["input_sha256"] = "f" * 64
    if target == "alias_mapping": receipt["field_alias_receipt"]["aliases_applied"] = {"fake": "alias"}
    receipt["receipt_sha256"] = digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    with pytest.raises(ValueError, match="compiler/alias"):
        validate_task_exposure(plan["cases"][0], "raw_model", receipt)


@pytest.mark.parametrize("case", [
    {"question": "Toy", "field_context": {"nested": {"reference_answer": "CONTROLLER_ONLY"}}},
    {"question": 'Toy {"nested":{"semantic_rubric":"CONTROLLER_ONLY"}}'},
])
def test_nested_controller_gold_refuses_worker_projection(case):
    with pytest.raises(ValueError, match="controller gold"):
        worker_case(case)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '[]'])
def test_controller_reader_refuses_invalid_json(tmp_path, raw):
    path = tmp_path / "policy.json"; path.write_text(raw)
    with pytest.raises(ValueError):
        read_controller_inputs(policy_path=path)


def test_controller_reader_refuses_symlink_and_oversize(tmp_path, monkeypatch):
    import agronomy_agent.release_evaluation as protocol
    path = tmp_path / "policy.json"; path.write_text('{"toy":true}')
    link = tmp_path / "link.json"; link.symlink_to(path)
    with pytest.raises(ValueError, match="regular file"):
        read_controller_inputs(policy_path=link)
    monkeypatch.setattr(protocol, "CONTROLLER_INPUT_LIMIT", 2)
    with pytest.raises(ValueError, match="bounded"):
        read_controller_inputs(policy_path=path)


@pytest.mark.parametrize("mutation", ["question", "context", "arm", "worker_hash"])
def test_actual_exposure_changes_refuse_even_same_outer_case(tmp_path, mutation):
    plan, rows, *_ = _controller_packet(tmp_path)
    row = rows[1]; case = plan["cases"][0]; receipt = deepcopy(row["task_exposure"])
    if mutation == "question": receipt["requests"][0]["message"] = "Changed toy input"
    if mutation == "context": receipt["requests"][0]["field_context_delivered"]["a"] = 99
    if mutation == "arm": receipt["arm_id"] = "raw_model"
    if mutation == "worker_hash": receipt["worker_case_sha256"] = "a" * 64
    receipt["receipt_sha256"] = digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    with pytest.raises(ValueError):
        validate_task_exposure(case, "production_full", receipt)
    assert validate_task_exposure(case, "production_full", None)["task_input_sha256"] is None


def test_mock_reference_records_actual_task_delivery_without_controller_gold(tmp_path):
    from agronomy_agent.release_eval_executor import execute_product_case
    raw = {"case_id": "toy-actual-request", "scenario_family": "synthetic_arithmetic", "lane": "harness",
           "question": 'Explain toy counts.\nSupplied facts: {"a":2,"b":3}', "field_context": {"a": 2, "b": 3},
           "assertions": {}, "review_required": True}
    result = execute_product_case(raw, model_config=ROOT / "configs/model.yaml", rag_config=ROOT / "configs/rag.yaml",
                                  arm_id="raw_model", backend="mock", output_dir=tmp_path / "actual-reference")
    assert result["status"] == "completed", result.get("error")
    delivered = result["task_exposure"]["requests"][0]
    assert delivered["message"] == raw["question"]
    assert delivered["prompt_messages"] == [{"role": "user", "content": raw["question"]}]
    assert delivered["field_context_delivered"] is None
    assert validate_task_exposure(raw, "raw_model", result["task_exposure"])["task_input_sha256"] == task_input_contract(raw)["task_input_sha256"]


def test_complete_profiles_share_cohort_and_cells():
    registry = load_registry()
    baseline = build_plan(registry, profile="baseline", run_id="before")
    release = build_plan(registry, profile="release", run_id="after")
    assert baseline["cohort_sha256"] == release["cohort_sha256"]
    assert baseline["matrix"] == release["matrix"]
    assert baseline["counts"]["observations"] == 2 * baseline["counts"]["cases"]
    assert baseline["counts"]["lanes"]["agronomy"] == 256
    assert len(baseline["auxiliary_inputs"]) > 100
    assert "data/manifests/canada_agronomy_sources.json" in baseline["auxiliary_inputs"]
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


def test_isolated_canadian_boundary_requires_the_bound_runtime_registry(tmp_path):
    from agronomy_agent.canada_sources import build_canadian_coverage_boundary
    from agronomy_agent.release_evaluation import file_digest

    name = "data/manifests/canada_agronomy_sources.json"
    source = ROOT / name
    plan = build_plan(load_registry(), profile="ci")
    assert plan["auxiliary_inputs"][name] == file_digest(source)
    isolated = tmp_path / name
    with pytest.raises(FileNotFoundError):
        build_canadian_coverage_boundary("Saskatchewan", [], manifest_path=isolated)
    isolated.parent.mkdir(parents=True)
    isolated.write_bytes(source.read_bytes())
    boundary = build_canadian_coverage_boundary(
        "Saskatchewan", [], manifest_path=isolated
    )
    assert boundary.jurisdiction == "Saskatchewan"
    assert boundary.requires_prompt_boundary is True
    assert boundary.registered_source_ids


@pytest.mark.parametrize("filename", [
    "requirements-release-evaluation-colab.txt", "requirements-phase4-ci.txt",
])
def test_source_identity_binds_relocated_dependencies_and_rejects_stale_capsule(
    tmp_path, monkeypatch, filename,
):
    from types import SimpleNamespace
    from agronomy_agent import release_evaluation as evaluation

    monkeypatch.setattr(evaluation.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout=""))
    for name in ("requirements-release-evaluation-colab.txt", "requirements-phase4-ci.txt"):
        path = tmp_path / "requirements" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("pytest==1.0\n")
    original = evaluation.source_identity(tmp_path)
    assert set(original["files"]) == {
        "requirements/requirements-release-evaluation-colab.txt",
        "requirements/requirements-phase4-ci.txt",
    }
    # Old receipts stay immutable; the source capsule must reject new input bytes.
    capsule = tmp_path / "EVALUATION_SOURCE.json"
    capsule.write_text(json.dumps({"commit": "historical", "source_sha256": original["source_sha256"]}))
    before = capsule.read_bytes()
    assert evaluation.source_identity(tmp_path)["commit"] == "historical"
    (tmp_path / "requirements" / filename).write_text("pytest==2.0\n")
    with pytest.raises(ValueError, match="capsule does not match source bytes"):
        evaluation.source_identity(tmp_path)
    assert capsule.read_bytes() == before
