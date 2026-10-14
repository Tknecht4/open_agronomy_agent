"""Offline, descriptive model outcomes under a supplied project analysis policy.

This does not replace historical lexical scores or the release regression gate.
Unknown labels never become successes. Tool correctness is a separate system
dimension; outcome contrasts require identical criteria and declared cohorts.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import statistics
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

SCHEMA = "open_agronomy_agent.model_metrics.v1"
POLICY_SCHEMA = "open_agronomy_agent.model_scoring_policy.v1"
OUTCOME_DIMENSIONS = ("usefulness", "restraint", "numeric_unit_accuracy", "evidence_support", "applicability")
DIMENSIONS = OUTCOME_DIMENSIONS + ("tool_correctness",)
REVIEW_TYPES = {"human_agronomist", "human_domain_reviewer", "automated_triage", "synthetic_fixture", "deterministic_oracle"}
FAILED = {"failed", "error", "timeout", "timed_out", "interrupted"}
HEX = re.compile(r"[0-9a-f]{64}\Z")
CONDITION_FIELDS = ("model_config_sha256", "source_sha256", "runtime_config_sha256", "arm_recipe_sha256")


def canonical_bytes(value: Any) -> bytes:
    """Same JSON serialization as release_evaluation.digest; no NaN/Infinity."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def rubric_digest(rubric: Mapping[str, Any]) -> str:
    return canonical_digest({key: value for key, value in rubric.items() if key != "rubric_sha256"})


def _number(value: Any, *, score: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("expected a finite numeric value")
    if score and not 0 <= value <= 1:
        raise ValueError("criterion score must be in [0,1]")
    return float(value)


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected a nonempty identifier")
    return value


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError("expected lowercase SHA256")
    return value


def _condition(value: Any) -> dict[str, str | None]:
    if value is None:
        return {key: None for key in CONDITION_FIELDS}
    if not isinstance(value, dict) or set(value) - set(CONDITION_FIELDS):
        raise ValueError("analysis condition must contain declared SHA256 bindings only")
    return {key: _sha(value[key]) if value.get(key) is not None else None for key in CONDITION_FIELDS}


def termination_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    """Validate recorded flags and scoped stages without inventing a terminal."""
    def fields(value: Mapping[str, Any]) -> bool | None:
        reason, flag = value.get("finish_reason"), value.get("truncated")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("finish reason must be provider text or null")
        if flag is not None and not isinstance(flag, bool):
            raise ValueError("truncated must be boolean or null")
        known = reason == "length" if reason in ("stop", "length") else None
        if known is not None and flag is not None and known != flag:
            raise ValueError("contradictory terminal evidence")
        return known if known is not None else flag

    recorded = fields(row)
    termination = row.get("termination")
    if termination is None:
        return {"truncated": recorded, "status": "unknown" if recorded is None else "observed"}
    if not isinstance(termination, Mapping) or termination.get("schema_version") != "open_agronomy_agent.generation_termination.v1":
        raise ValueError("unsupported termination evidence")
    stages = termination.get("stages")
    if not isinstance(stages, list):
        raise ValueError("termination stages must be a list")
    seen = set()
    required = []
    for stage in stages:
        if not isinstance(stage, Mapping) or type(stage.get("required")) is not bool or type(stage.get("turn_index")) is not int or stage["turn_index"] < 0 or stage.get("stage") not in {"draft", "reference", "editor"}:
            raise ValueError("invalid termination stage")
        key = (stage["turn_index"], stage["stage"])
        if key in seen:
            raise ValueError("duplicate termination stage")
        seen.add(key)
        fields(stage)
        reason = stage.get("finish_reason")
        known = reason in ("stop", "length")
        expected_status = "not_applicable" if not stage["required"] else "observed" if known else "unknown"
        expected_flag = reason == "length" if known and stage["required"] else None
        if stage.get("status") != expected_status or stage.get("truncated") != expected_flag:
            raise ValueError("contradictory terminal stage")
        if stage["required"]:
            required.append(stage)
    expected_status = "not_applicable" if stages and not required else "unknown" if not required or any(s["status"] == "unknown" for s in required) else "observed"
    expected_flag = True if any(s["truncated"] is True for s in required) else None if expected_status in {"unknown", "not_applicable"} else False
    expected_reason = "length" if expected_flag is True else "stop" if expected_flag is False else None
    if (termination.get("status"), termination.get("truncated"), termination.get("finish_reason")) != (expected_status, expected_flag, expected_reason):
        raise ValueError("contradictory terminal aggregate")
    if recorded is not None and expected_flag is not None and recorded != expected_flag:
        raise ValueError("contradictory recorded and derived terminal evidence")
    return {"truncated": recorded if recorded is not None else expected_flag,
            "status": "observed" if expected_status == "not_applicable" and recorded is not None else expected_status}


def _weights(value: Any, allowed: set[str]) -> dict[str, float]:
    if not isinstance(value, dict) or not value or set(value) - allowed:
        raise ValueError("unknown or empty weight dimensions/domains")
    weights = {_text(key): _number(weight) for key, weight in value.items()}
    if any(weight <= 0 for weight in weights.values()):
        raise ValueError("weights must be positive")
    total = sum(weights.values())
    if not math.isfinite(total):
        raise ValueError("weight sum must be finite")
    return {key: weight / total for key, weight in weights.items()}


def validate_policy(policy: Mapping[str, Any], domains: set[str]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("unsupported supplied policy version")
    if policy.get("missingness") != "unknown_fixed_denominator" or policy.get("failed_outcome") != "zero":
        raise ValueError("policy must declare unknown fixed denominators and failed outcome zero")
    if policy.get("truncated_outcome") not in {"retain_labels", "zero"}:
        raise ValueError("explicit truncation policy required")
    if policy.get("weight_authority") != "project_choice":
        raise ValueError("weights must be an explicit project choice")
    normalized = dict(policy)
    normalized["domain_weights"] = _weights(policy.get("domain_weights"), domains)
    if set(normalized["domain_weights"]) != domains:
        raise ValueError("policy must cover every planned domain")
    normalized["dimension_weights"] = _weights(policy.get("dimension_weights"), set(OUTCOME_DIMENSIONS))
    profiles = []
    seen = set()
    for profile in policy.get("sensitivity_profiles", []):
        name = _text(profile.get("profile_id"))
        if name in seen:
            raise ValueError("duplicate sensitivity profile")
        seen.add(name)
        dw = _weights(profile.get("domain_weights"), domains)
        mw = _weights(profile.get("dimension_weights"), set(OUTCOME_DIMENSIONS))
        if set(dw) != domains or set(mw) != set(normalized["dimension_weights"]):
            raise ValueError("sensitivity must preserve domain and dimension coverage")
        profiles.append({"profile_id": name, "domain_weights": dw, "dimension_weights": mw})
    normalized["sensitivity_profiles"] = profiles
    return normalized


def _rubrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for source in rows:
        row = dict(source)
        case = _text(row.get("case_id"))
        if case in result or _sha(row.get("rubric_sha256")) != rubric_digest(row):
            raise ValueError("duplicate case rubric or rubric hash mismatch")
        _sha(row.get("case_sha256"))
        _text(row.get("domain_id")); _text(row.get("cluster_id"))
        if row.get("answerability") not in {"answerable", "partially_answerable", "insufficient_information"}:
            raise ValueError("invalid answerability")
        _text(row.get("review_status"))
        criteria = {}
        for criterion in row.get("criteria", []):
            cid = _text(criterion.get("criterion_id"))
            if cid in criteria or criterion.get("dimension") not in DIMENSIONS:
                raise ValueError("duplicate criterion or unknown dimension")
            condition = criterion.get("applicability_condition", "arm_only")
            if condition not in {"arm_only", "requested_outcome_in_all_arms", "actual_assessable_tool_attempt"}:
                raise ValueError("unsupported applicability condition")
            if condition == "actual_assessable_tool_attempt" and criterion["dimension"] != "tool_correctness":
                raise ValueError("conditional applicability is restricted to tool correctness")
            _text(criterion.get("description"))
            if _number(criterion.get("weight")) <= 0:
                raise ValueError("criterion weight must be positive")
            arms = criterion.get("applicable_arms")
            if not isinstance(arms, list) or not arms or len(set(arms)) != len(arms):
                raise ValueError("explicit unique applicable arms required")
            for arm in arms:
                _text(arm)
            criteria[cid] = dict(criterion)
        if not criteria:
            raise ValueError("rubric needs criteria")
        if not math.isfinite(sum(spec["weight"] for spec in criteria.values())):
            raise ValueError("criterion weight sum must be finite")
        fatal = row.get("fatal_conditions")
        if not isinstance(fatal, list) or len(set(fatal)) != len(fatal):
            raise ValueError("fatal condition IDs must be a unique list")
        for fid in fatal:
            _text(fid)
        row["criteria_by_id"] = criteria
        result[case] = row
    return result


def bind_fixture_review(observation: Mapping[str, Any], rubric: Mapping[str, Any], fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize a QA fixture as an explicitly synthetic, hash-bound review."""
    if fixture.get("synthetic_fixture") is not True:
        raise ValueError("fixture must be marked synthetic")
    if fixture.get("case_id") != observation.get("case_id") or fixture.get("arm_id") != observation.get("arm_id"):
        raise ValueError("fixture cell mismatch")
    if rubric.get("case_sha256") != observation.get("case_sha256"):
        raise ValueError("fixture rubric case mismatch")
    for key, expected in (("case_sha256", observation.get("case_sha256")), ("answer_sha256", observation.get("answer_sha256")),
                          ("rubric_sha256", rubric.get("rubric_sha256")), ("status", observation.get("status"))):
        if key in fixture and fixture[key] != expected:
            raise ValueError("fixture supplied binding mismatch: " + key)
    if canonical_digest(fixture.get("answer")) != observation.get("answer_sha256"):
        raise ValueError("fixture answer mismatch")
    applicability = {}
    trace = fixture.get("trace_expectations", {})
    if not isinstance(trace, dict):
        raise ValueError("fixture trace expectations must be a mapping")
    attempted, execution = trace.get("attempted"), trace.get("execution_correctness")
    if attempted is not None and not isinstance(attempted, bool):
        raise ValueError("fixture attempted must be boolean or unknown")
    if execution is not None and not isinstance(execution, bool):
        _number(execution, score=True)
    if attempted is False and execution is not None:
        raise ValueError("no-attempt fixture cannot declare execution correctness")
    for spec in rubric.get("criteria", []):
        if spec.get("dimension") == "tool_correctness" and spec.get("applicability_condition") == "actual_assessable_tool_attempt":
            applicability[spec["criterion_id"]] = False if attempted is False else True if attempted is True and execution is not None else None
    return {"observation_id": observation["observation_id"], "case_sha256": observation["case_sha256"],
            "answer_sha256": observation["answer_sha256"], "rubric_sha256": rubric["rubric_sha256"],
            "reviewer_id": "synthetic:" + _text(fixture.get("fixture_id")), "reviewer_type": "synthetic_fixture",
            "criterion_scores": fixture.get("criterion_scores", {}), "fatal_failures": fixture.get("fatal_failures", []),
            "fatal_review_complete": fixture.get("fatal_review_complete", False), "criterion_applicability": applicability}


def score_numeric_oracle(answer: str, oracle: Mapping[str, Any]) -> dict[str, Any]:
    """Reuse the historical explicit-unit scalar scorer; never extract vectors.

    Decimal declarations are retained; scoring uses the existing finite-float
    implementation. Unit/basis equivalence must be declared by the controller.
    """
    for key in ("case_id", "criterion_id", "quantity_id", "unit"):
        _text(oracle.get(key))
    if "value_decimal" not in oracle or "absolute_tolerance_decimal" not in oracle:
        raise ValueError("explicit oracle value and absolute tolerance required")
    values = []
    for key in ("value_decimal", "absolute_tolerance_decimal", "relative_tolerance_decimal"):
        raw = oracle.get(key, "0")
        if not isinstance(raw, str):
            raise ValueError("oracle quantities must be Decimal strings")
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError("invalid oracle decimal") from exc
        if not value.is_finite() or (key != "value_decimal" and value < 0):
            raise ValueError("nonfinite or negative oracle tolerance")
        values.append(value)
    expected, absolute, relative = values
    tolerance = max(absolute, abs(expected) * relative)
    reference_float, tolerance_float = float(expected), float(tolerance)
    if not math.isfinite(reference_float) or not math.isfinite(tolerance_float):
        raise ValueError("oracle outside scalar float range")
    if expected != 0 and reference_float == 0 or tolerance != 0 and tolerance_float == 0:
        raise ValueError("oracle underflows scalar float range")
    from agronomy_agent.evals import score_item_numeric
    result = score_item_numeric(answer, {"reference_numeric": reference_float, "reference_unit": oracle["unit"],
                                         "absolute_tolerance": tolerance_float})
    return {"score": result["score"] / 100, "oracle_sha256": canonical_digest(oracle),
            "scalar_scorer": "evals.score_item_numeric", "measurement": result, "promotion_eligible": False}


def _interval(values: Sequence[tuple[str, float]]) -> dict[str, Any]:
    from agronomy_agent.release_eval_analysis import _cluster_interval
    result = _cluster_interval(values)
    if result["clusters_n"] < 2:
        result["lower_95"] = result["upper_95"] = None
    result["scope"] = "observed_equal_cluster_description; not domain-weighted population inference"
    return result


def _performance(row: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve supplied scopes; missing phases/dtype are unknown, never zero."""
    fields = ("elapsed_seconds", "load_seconds", "first_response_seconds", "ttft_seconds", "prefill_seconds",
              "post_first_decode_seconds", "harness_seconds", "retrieval_seconds", "transport_seconds",
              "compile_seconds", "input_tokens", "output_tokens", "decode_tokens_per_second")
    source = row.get("performance", {})
    if not isinstance(source, dict) or set(source) - set(fields):
        raise ValueError("performance must contain declared scalar stage metrics only")
    result = {field: source.get(field) for field in fields}
    for field, alias in (("elapsed_seconds", "elapsed_seconds"), ("input_tokens", "prompt_tokens"), ("output_tokens", "generation_tokens")):
        if result[field] is None:
            result[field] = row.get(alias)
    for field, value in result.items():
        if value is not None and _number(value) < 0:
            raise ValueError("negative performance metric")
        if field in {"input_tokens", "output_tokens"} and value is not None and type(value) is not int:
            raise ValueError("token counts must be integers")
    return result


def _cell_value(cell: Mapping[str, Any], policy: Mapping[str, Any]) -> float | None:
    if cell["penalty_zero"]:
        return 0.0
    if policy["truncated_outcome"] == "zero" and cell["termination_status"] == "unknown":
        return None
    dimensions = cell["dimensions"]
    if all(dimensions.get(dim) is not None for dim in policy["dimension_weights"]):
        return sum(dimensions[dim] * weight for dim, weight in policy["dimension_weights"].items())
    return None


def _aggregate(cells: Sequence[dict[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    domains: dict[str, dict[str, list[float | None]]] = defaultdict(lambda: defaultdict(list))
    for cell in cells:
        value = _cell_value(cell, policy)
        domains[cell["domain_id"]][cell["cluster_id"]].append(value)
    summary = {}; lower = upper = 0.0; complete = True
    observed = []
    for domain, weight in policy["domain_weights"].items():
        clusters = domains.get(domain, {})
        known = []
        lo = hi = 0.0
        for cluster, values in clusters.items():
            labels = [value for value in values if value is not None]
            lo += sum(labels) / len(values)
            hi += (sum(labels) + len(values) - len(labels)) / len(values)
            if len(labels) == len(values):
                mean = statistics.mean(labels)
                known.append(mean); observed.append((canonical_digest([domain, cluster]), mean))
        n = len(clusters)
        full = bool(n) and len(known) == n
        complete &= full
        lower += weight * (lo / n if n else 0)
        upper += weight * (hi / n if n else 1)
        summary[domain] = {"planned_clusters": n, "complete_clusters": len(known),
                           "observed_complete_cluster_mean": statistics.mean(known) if known else None}
    return {"score": lower if complete else None, "fixed_denominator_bounds": [lower, upper],
            "coverage_status": "complete" if complete else "partial_unknown", "domains": summary,
            "observed_equal_cluster_interval": _interval(observed)}


def score_model_matrix(plan: Mapping[str, Any], observations: Sequence[Mapping[str, Any]], *,
                       rubrics: Sequence[Mapping[str, Any]], reviews: Sequence[Mapping[str, Any]] = (),
                       policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return descriptive, fixed-denominator scores; never release authority.

    plan.cases carry case_id/case_sha256. plan.matrix carries observation_id,
    case_id/case_sha256/suite_id/arm_id/trial_id/model_id/model_revision/backend_id.
    Observations and reviews join only through these original hash identities.
    A comparison_cohort and task_input_sha256 must be explicitly recorded on
    observations for contrasts; missing cohort disables comparisons.
    """
    frozen = plan.get("controller_inputs")
    binding_status = "legacy_posthoc_unfrozen"
    if frozen is not None:
        if not isinstance(frozen, Mapping) or frozen.get("schema_version") != "open_agronomy_agent.controller_inputs.v1" or not isinstance(frozen.get("files"), dict):
            raise ValueError("unsupported controller input freeze")
        for name, value in (("rubrics", list(rubrics)), ("policy", policy)):
            expected = frozen["files"].get(name)
            if expected is not None:
                _sha(expected.get("sha256")); _sha(expected.get("canonical_sha256"))
                if value is not None and (name != "rubrics" or value) and canonical_digest(value) != expected["canonical_sha256"]:
                    raise ValueError("scoring controller canonical input changed")
        binding_status = "prospective_canonical_inputs_bound" if policy is not None and rubrics and all(name in frozen["files"] for name in ("rubrics", "policy")) else "partial_unknown"
    cases = {}; matrix = {}; observed = {}; review_map = {}; logical_cells = set()
    rubric_map = _rubrics(rubrics)
    for case in plan.get("cases", []):
        cid = _text(case.get("case_id"))
        if cid in cases:
            raise ValueError("duplicate planned case")
        _sha(case.get("case_sha256")); cases[cid] = case
    for cid, rubric in rubric_map.items():
        if cid not in cases or rubric["case_sha256"] != cases[cid]["case_sha256"]:
            raise ValueError("rubric planned case hash mismatch")
    for item in plan.get("matrix", []):
        oid = _text(item.get("observation_id")); cid = _text(item.get("case_id"))
        if oid in matrix or cid not in cases or item.get("case_sha256") != cases[cid]["case_sha256"]:
            raise ValueError("duplicate cell or planned case hash mismatch")
        for key in ("suite_id", "arm_id", "trial_id", "model_id", "backend_id"):
            _text(item.get(key))
        if item.get("model_revision") is not None:
            _text(item["model_revision"])
        condition = _condition(item.get("analysis_condition"))
        planned_condition = _condition(item.get("planned_analysis_condition"))
        logical = tuple(item.get(key) for key in ("model_id", "model_revision", "backend_id", "arm_id", "suite_id", "case_id", "trial_id")) + (canonical_digest(condition), canonical_digest(planned_condition))
        if logical in logical_cells:
            raise ValueError("duplicate logical model/arm/case/trial cell")
        logical_cells.add(logical)
        matrix[oid] = item
    if not matrix or set(rubric_map) - set(cases):
        raise ValueError("nonempty planned matrix and known rubrics required")
    for row in observations:
        canonical_bytes(row)
        termination_evidence(row)
        if row.get("status") not in FAILED | {"completed", "blocked", "skipped", "cancelled", "not_started"}:
            raise ValueError("unknown observation status")
        oid = row.get("observation_id"); item = matrix.get(oid)
        if oid in observed or item is None:
            raise ValueError("duplicate or unplanned observation")
        for key in ("case_id", "case_sha256", "suite_id", "arm_id", "trial_id", "model_id", "model_revision", "backend_id"):
            if row.get(key) != item.get(key):
                raise ValueError("observation plan identity mismatch: " + key)
        if row.get("answer_sha256") is not None:
            _sha(row["answer_sha256"])
        if "answer" in row and canonical_digest(row["answer"]) != row.get("answer_sha256"):
            raise ValueError("answer hash mismatch")
        if row.get("status") == "completed" and row.get("answer_sha256") is None:
            raise ValueError("completed observation requires answer hash")
        if row.get("task_input_sha256") is not None:
            _sha(row["task_input_sha256"])
        if row.get("comparison_cohort") is not None:
            _text(row["comparison_cohort"])
        if frozen is not None:
            from agronomy_agent.release_evaluation import validate_task_exposure
            binding = validate_task_exposure(cases[item["case_id"]], item["arm_id"], row.get("task_exposure"))
            if row.get("task_input_sha256") is not None and (row["task_input_sha256"] != binding["task_input_sha256"] or row["task_input_sha256"] != item.get("task_input_sha256")):
                raise ValueError("scoring task input differs from actual exposure")
            if row.get("comparison_cohort") is not None and (binding["task_input_sha256"] is None or row["comparison_cohort"] != plan.get("comparison_cohort")):
                raise ValueError("scoring cohort differs from prospective declaration")
        if _condition(row.get("analysis_condition")) != _condition(item.get("analysis_condition")):
            raise ValueError("observation planned analysis condition mismatch")
        observed[oid] = row
    for review in reviews:
        oid = review.get("observation_id"); row = observed.get(oid)
        rubric = rubric_map.get(row["case_id"]) if row else None
        if oid in review_map or row is None or rubric is None or row.get("status") != "completed":
            raise ValueError("duplicate, unknown or noncompleted review cell")
        for key in ("case_sha256", "answer_sha256"):
            if review.get(key) != row.get(key):
                raise ValueError("review hash mismatch")
        if review.get("rubric_sha256") != rubric["rubric_sha256"]:
            raise ValueError("review rubric mismatch")
        _text(review.get("reviewer_id"))
        if review.get("reviewer_type") not in REVIEW_TYPES:
            raise ValueError("unknown review type")
        scores = review.get("criterion_scores", {})
        if not isinstance(scores, dict) or set(scores) - set(rubric["criteria_by_id"]):
            raise ValueError("unknown review criterion")
        for cid, value in scores.items():
            if value is not None and row["arm_id"] not in rubric["criteria_by_id"][cid]["applicable_arms"]:
                raise ValueError("score supplied for inapplicable criterion")
            if value is not None:
                _number(value, score=True)
        applicability = review.get("criterion_applicability", {})
        if not isinstance(applicability, dict):
            raise ValueError("criterion applicability must be a mapping")
        for cid, flag in applicability.items():
            spec = rubric["criteria_by_id"].get(cid, {})
            if spec.get("dimension") != "tool_correctness" or spec.get("applicability_condition") != "actual_assessable_tool_attempt":
                raise ValueError("only declared conditional tool criteria accept applicability labels")
            if flag is not None and not isinstance(flag, bool):
                raise ValueError("conditional applicability must be bool or null")
            if flag is not True and scores.get(cid) is not None:
                raise ValueError("nonapplicable or unknown tool attempt cannot receive a score")
        for cid, spec in rubric["criteria_by_id"].items():
            if spec.get("applicability_condition") == "actual_assessable_tool_attempt" and scores.get(cid) is not None and applicability.get(cid) is not True:
                raise ValueError("conditional tool score requires assessable-attempt applicability")
        fatal = review.get("fatal_failures", [])
        if not isinstance(fatal, list) or len(set(fatal)) != len(fatal) or set(fatal) - set(rubric["fatal_conditions"]):
            raise ValueError("unknown or duplicate fatal condition")
        if not isinstance(review.get("fatal_review_complete", False), bool):
            raise ValueError("fatal review completeness must be boolean")
        review_map[oid] = review
    missing_rubrics = set(cases) - set(rubric_map)
    domains = {row["domain_id"] for row in rubric_map.values()}
    if policy is not None and missing_rubrics:
        declared = policy.get("domain_weights")
        if not isinstance(declared, dict) or not domains.issubset(declared):
            raise ValueError("supplied policy omits known rubric domains")
        # Missing case bindings prohibit aggregates, but a structurally valid
        # supplied policy can still be reported as blocked/partial evidence.
        domains = set(declared)
    normalized = validate_policy(policy, domains) if policy is not None else None
    policy_bound = policy is not None and plan.get("model_scoring_policy_sha256") == canonical_digest(policy)
    groups = defaultdict(list); cells = []
    for oid, item in matrix.items():
        row = observed.get(oid, {}); rubric = rubric_map.get(item["case_id"]); review = review_map.get(oid, {})
        mask = {}; dimensions = {}; scores = review.get("criterion_scores", {})
        for dim in DIMENSIONS:
            applicable = {cid: spec for cid, spec in (rubric or {}).get("criteria_by_id", {}).items()
                          if spec["dimension"] == dim and item["arm_id"] in spec["applicable_arms"]
                          and review.get("criterion_applicability", {}).get(cid) is not False}
            mask[dim] = sorted(applicable)
            dimensions[dim] = (sum(scores[cid] * spec["weight"] for cid, spec in applicable.items()) /
                               sum(spec["weight"] for spec in applicable.values())) if applicable and all(scores.get(cid) is not None for cid in applicable) else None
        status = row.get("status", "missing")
        terminal = termination_evidence(row)
        truncated = terminal["truncated"]
        condition = _condition(item.get("analysis_condition"))
        cell = {**{key: item.get(key) for key in ("observation_id", "case_id", "suite_id", "trial_id", "arm_id", "model_id", "model_revision", "backend_id")},
                "analysis_condition": condition, "analysis_condition_sha256": canonical_digest(condition),
                "planned_analysis_condition": item.get("planned_analysis_condition"),
                "observed_model_identity": row.get("observed_model_identity"),
                "runtime_input_binding_status": row.get("runtime_input_binding_status", "unknown"),
                "unknown_condition_fields": [key for key, value in condition.items() if value is None],
                "domain_id": rubric["domain_id"] if rubric else "unknown", "cluster_id": rubric["cluster_id"] if rubric else item["case_id"],
                "status": status, "truncated": truncated, "termination_status": terminal["status"], "termination": row.get("termination"), "dimensions": dimensions, "criterion_mask": mask,
                "criterion_applicability": review.get("criterion_applicability", {}),
                "dimension_status": {dim: "unknown_rubric" if rubric is None else "not_applicable" if not mask[dim]
                                     else "unknown_labels" if dimensions[dim] is None else "observed" for dim in DIMENSIONS},
                "fatal_failures": review.get("fatal_failures", []),
                "safety_unknown": rubric is None or bool(rubric["fatal_conditions"]) and review.get("fatal_review_complete") is not True,
                "review_type": review.get("reviewer_type"), "task_input_sha256": row.get("task_input_sha256"),
                "comparison_cohort": row.get("comparison_cohort"),
                "penalty_zero": normalized is not None and (status in FAILED or truncated is True and normalized["truncated_outcome"] == "zero"),
                "source_observed_metrics": _performance(row), "metrics_scope": row.get("performance_scope", "source_observed_row_only; phase scopes unknown"),
                "tokens_scope": row.get("tokens_scope", "unknown"), "identity_status": row.get("identity_status", "unknown"),
                "model_execution_eligible": row.get("model_execution_eligible"), "original_unknowns": row.get("unknown", []),
                "original_helper_receipt_status": row.get("original_helper_receipt_status"),
                "original_claim_eligible": row.get("claim_eligible"), "original_domain_eligible": row.get("domain_eligible")}
        cells.append(cell)
        group_key = (item["model_id"], item.get("model_revision"), item["backend_id"], item["arm_id"], cell["analysis_condition_sha256"])
        if "planned_analysis_condition" in item:
            group_key += (canonical_digest(item["planned_analysis_condition"]),)
        groups[group_key].append(cell)
    group_reports = []
    for key, values in groups.items():
        eligible = normalized is not None and not missing_rubrics
        primary = _aggregate(values, normalized) if eligible else None
        group_reports.append({"model_id": key[0], "model_revision": key[1], "backend_id": key[2], "arm_id": key[3],
                              "analysis_condition": values[0]["analysis_condition"], "analysis_condition_sha256": key[4],
                              "planned_analysis_condition": values[0]["planned_analysis_condition"],
                              "unknown_condition_fields": values[0]["unknown_condition_fields"],
                              "planned": len(values), "observed": sum(v["status"] != "missing" for v in values),
                              "failed": sum(v["status"] in FAILED for v in values), "missing": sum(v["status"] == "missing" for v in values),
                              "completed": sum(v["status"] == "completed" for v in values), "truncated": sum(v["truncated"] is True for v in values), "termination_unknown": sum(v["termination_status"] == "unknown" for v in values), "termination_not_applicable": sum(v["termination_status"] == "not_applicable" for v in values),
                              "fatal_failures_n": sum(len(v["fatal_failures"]) for v in values), "safety_unknown_n": sum(v["safety_unknown"] for v in values),
                              "primary": primary, "sensitivity": [{"profile_id": p["profile_id"], **_aggregate(values, {**normalized, **p})}
                                                                      for p in normalized["sensitivity_profiles"]] if eligible else []})
    pairs = []
    for (left_key, left), (right_key, right) in itertools.combinations(groups.items(), 2):
        lookup = {(v["suite_id"], v["case_id"], v["trial_id"]): v for v in right}
        left_keys = {(v["suite_id"], v["case_id"], v["trial_id"]) for v in left}
        deltas = []; incompatible = unmatched = unscored = identity_incomplete = source_mismatch = 0
        for a in left:
            b = lookup.get((a["suite_id"], a["case_id"], a["trial_id"]))
            if b is None:
                unmatched += 1; continue
            dims = list(normalized["dimension_weights"]) if normalized else list(OUTCOME_DIMENSIONS)
            complete_identity = not a["unknown_condition_fields"] and not b["unknown_condition_fields"]
            source_compatible = a["analysis_condition"]["source_sha256"] == b["analysis_condition"]["source_sha256"]
            if not complete_identity:
                identity_incomplete += 1
            elif not source_compatible:
                source_mismatch += 1
            same = (complete_identity and source_compatible and (frozen is None or binding_status == "prospective_canonical_inputs_bound")
                    and a["comparison_cohort"] is not None and a["comparison_cohort"] == b["comparison_cohort"]
                    and a["task_input_sha256"] is not None and a["task_input_sha256"] == b["task_input_sha256"]
                    and all(a["criterion_mask"][dim] == b["criterion_mask"][dim] for dim in dims))
            if not same:
                incompatible += 1; continue
            if normalized:
                av, bv = _cell_value(a, normalized), _cell_value(b, normalized)
                if av is not None and bv is not None:
                    deltas.append((canonical_digest([a["domain_id"], a["cluster_id"]]), bv - av))
                else:
                    unscored += 1
            else:
                unscored += 1
        pairs.append({"left": list(left_key), "right": list(right_key), "paired_scored_n": len(deltas),
                      "left_analysis_condition": left[0]["analysis_condition"], "right_analysis_condition": right[0]["analysis_condition"],
                      "condition_differences": [key for key in CONDITION_FIELDS if left[0]["analysis_condition"][key] != right[0]["analysis_condition"][key]],
                      "identity_incomplete_n": identity_incomplete, "source_mismatch_n": source_mismatch,
                      "incomparable_n": incompatible, "unmatched_left_n": unmatched,
                      "unmatched_right_n": len(set(lookup) - left_keys), "unscored_compatible_n": unscored,
                      "interval": _interval(deltas),
                      "ranking_authorized": False})
    return {"schema_version": SCHEMA, "status": "blocked_missing_policy" if normalized is None else "partial_unknown" if missing_rubrics or any(g["primary"]["score"] is None for g in group_reports) or frozen is not None and binding_status != "prospective_canonical_inputs_bound" else "descriptive_complete",
            "policy_sha256": canonical_digest(policy) if policy else None, "policy_bound_to_plan": policy_bound,
            "policy_preregistration_verified": False,
            "controller_binding_status": binding_status,
            "weight_authority": "project_choice" if policy else None, "missing_rubric_case_ids": sorted(missing_rubrics),
            "planned_n": len(matrix), "observed_n": len(observed), "reviewed_n": len(review_map),
            "groups": group_reports, "cells": cells, "contrasts": pairs, "promotion_allowed": False,
            "limitations": ["Exposed descriptive development data; no independent competence or release claim.",
                            "Unknown labels retain fixed denominators; tool correctness is separate from outcome composites.",
                            "Weights are supplied project choices; synthetic/triage/oracle records are not expert certification.",
                            "Timing scopes, precision, service identity and output lengths require separate comparability checks."]}
