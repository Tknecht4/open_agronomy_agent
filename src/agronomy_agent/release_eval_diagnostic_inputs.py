"""Read the sealed six-cell closeout as a diagnostic analysis projection.

Only known, pinned direct children of the closeout directory are read. References
to archives, source checkouts, SQLite databases and earlier receipts remain
metadata; this adapter neither follows them nor requalifies their contents.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


_MAX_FILE_BYTES = 2 * 1024 * 1024
_SEAL = "closure-seal-v1.json"
_FILES = frozenset({
    "actual-answers-v1.json", "collection-observations-v1.json",
    "delayed-account.json", "final-retained-inspection-v1.json",
    "native-execution-file-seal-v1.json", "original-luna-file-seal-v1.json",
    "paired-answer-analysis-v1.md", "paired-answer-findings-v1.json",
    "retained-grounding-readout-v1.json", "root-final-handoff-v1.json",
    "terminal-accounting-v1.json",
})
_SCHEMAS = {
    "actual-answers-v1.json": "open_agronomy_agent.actual_six_cell_answer_readout.v1",
    "collection-observations-v1.json": "open_agronomy_agent.six_cell_completed_observations.v1",
    "final-retained-inspection-v1.json": "open_agronomy_agent.six_cell_final_retained_inspection.v1",
    "paired-answer-findings-v1.json": "open_agronomy_agent.six_cell_paired_answer_interpretation.v1",
    "retained-grounding-readout-v1.json": "open_agronomy_agent.six_cell_retained_grounding_readout.v1",
    "root-final-handoff-v1.json": "open_agronomy_agent.six_cell_final_evidence_handoff.v1",
    "terminal-accounting-v1.json": "open_agronomy_agent.six_cell_terminal_reconciled_accounting.v1",
}
_MODELS = {
    "gemma_e2b": ("mlx-community/gemma-4-e2b-it-4bit", "238767527555cb75a05732a84dff5d6ba0dd6809"),
    "gemma_e4b": ("mlx-community/gemma-4-e4b-it-4bit", "475b9088d29754a3379866cf5aeb6b41acd313c2"),
    "luna_medium": ("gpt-6-luna", None),
}
_ARMS = {"raw_model", "production_full"}


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(f"six-cell closeout: {reason}")


def _digest(value: Any) -> str:
    # Exact release_evaluation.digest serialization, without importing runners.
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _sha(value: Any, name: str) -> str:
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None, name)
    return value


def _json(raw: bytes, name: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            _require(key not in result, f"duplicate JSON key in {name}")
            result[key] = value
        return result

    def nonfinite(value: str) -> None:
        raise ValueError(f"six-cell closeout: nonfinite JSON in {name}: {value}")

    value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs,
                       parse_constant=nonfinite)
    _require(isinstance(value, dict), f"object required in {name}")
    try:
        json.dumps(value, allow_nan=False)
    except ValueError as error:
        raise ValueError(f"six-cell closeout: nonfinite JSON in {name}") from error
    return value


def _directory(directory: Path) -> Path:
    root = Path(directory).absolute()
    _require(not any(p.is_symlink() for p in (root, *root.parents)), "linked directory")
    _require(root.is_dir(), "missing directory")
    return root


def _read(root: Path, name: str) -> bytes:
    _require(name in _FILES or name == _SEAL, "unknown closeout file")
    _require(not any(p.is_symlink() for p in (root, *root.parents)), "linked directory")
    directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory_fd)
        except OSError as error:
            raise ValueError(f"six-cell closeout: missing or linked file: {name}") from error
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            _require(stat.S_ISREG(before.st_mode), f"regular file required: {name}")
            _require(0 <= before.st_size <= _MAX_FILE_BYTES, f"file byte cap: {name}")
            raw = handle.read(before.st_size + 1)
            after = os.fstat(handle.fileno())
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
            _require(len(raw) == before.st_size and identity(before) == identity(after)
                     == identity(current), f"file changed while reading: {name}")
            return raw
    finally:
        os.close(directory_fd)


def _pin_name(root: Path, value: Any) -> str:
    _require(isinstance(value, str) and bool(value), "invalid pin path")
    path = Path(value)
    _require(".." not in path.parts, "escaped pin path")
    candidate = path if path.is_absolute() else root / path
    _require(candidate.parent == root and candidate.name in _FILES, "escaped or unknown pin path")
    return candidate.name


def _records(value: Any, name: str, count: int) -> list[dict[str, Any]]:
    _require(isinstance(value, list) and len(value) == count
             and all(isinstance(item, dict) for item in value), name)
    return value


def _indexed(rows: list[dict[str, Any]], name: str) -> dict[str, dict[str, Any]]:
    result = {}
    cells = set()
    for row in rows:
        observation = _sha(row.get("observation_id"), f"{name} observation identity")
        _require(observation not in result, f"duplicate {name} observation")
        backend, arm = row.get("backend_id"), row.get("arm_id")
        _require(isinstance(backend, str) and isinstance(arm, str)
                 and backend in _MODELS and arm in _ARMS, f"{name} backend or arm")
        _require((backend, arm) not in cells, f"duplicate {name} model/arm")
        cells.add((backend, arm))
        result[observation] = row
    _require(cells == {(backend, arm) for backend in _MODELS for arm in _ARMS},
             f"incomplete {name} model/arm matrix")
    return result


def read_six_cell_closeout(directory: Path) -> dict[str, Any]:
    """Validate local closure pins and return six existing diagnostic observations.

    Raises ValueError for missing, altered, escaped or inconsistent records.
    No external evidence is read, and no correctness labels are constructed.
    """
    root = _directory(directory)
    seal_raw = _read(root, _SEAL)
    seal = _json(seal_raw, _SEAL)
    _require(seal.get("schema") == "open_agronomy_agent.six_cell_final_closure.v1", "closure schema")
    _require(seal.get("root") == str(root), "closure directory binding")
    pins = _records(seal.get("files"), "closure file list", len(_FILES))
    _require(type(seal.get("file_count")) is int and seal["file_count"] == len(_FILES), "closure file count")
    contents: dict[str, bytes] = {}
    descriptors = {}
    for pin in pins:
        name = _pin_name(root, pin.get("path"))
        _require(name not in contents, "duplicate closure file")
        size = pin.get("bytes")
        _require(type(size) is int and 0 <= size <= _MAX_FILE_BYTES, f"pin byte cap: {name}")
        expected = _sha(pin.get("sha256"), f"pin hash: {name}")
        raw = _read(root, name)
        _require(len(raw) == size and hashlib.sha256(raw).hexdigest() == expected,
                 f"pin mismatch: {name}")
        contents[name] = raw
        descriptors[name] = {"bytes": size, "sha256": expected}
    _require(set(contents) == _FILES, "incomplete closure")
    _require(type(seal.get("total_bytes")) is int
             and seal["total_bytes"] == sum(len(raw) for raw in contents.values()), "closure byte total")
    documents = {}
    for name, schema in _SCHEMAS.items():
        document = _json(contents[name], name)
        _require(document.get("schema") == schema, f"schema mismatch: {name}")
        documents[name] = document

    answers = documents["actual-answers-v1.json"]
    collection = documents["collection-observations-v1.json"]
    handoff = documents["root-final-handoff-v1.json"]
    grounding = documents["retained-grounding-readout-v1.json"]
    inspection = documents["final-retained-inspection-v1.json"]
    case_id, question = answers.get("case_id"), answers.get("question")
    _require(isinstance(case_id, str) and bool(case_id) and isinstance(question, str)
             and bool(question), "case identity or question")
    _require(collection.get("case_id") == case_id and answers.get("same_safe_case_all_six") is True,
             "case identity join")
    expected_counts = {"observations_completed": 6, "exposed_cases": 1,
                       "semantic_expert_labels": 0, "trials_per_model_arm": 1,
                       "native_weight_eligible_observations": 4,
                       "catalog_response_observed_remote_observations_native_weight_ineligible": 2}
    _require(all(type(collection.get(key)) is int and collection[key] == value
                 for key, value in expected_counts.items()), "collection scope or counts")
    _require(collection.get("full_suite_executed") is False
             and collection.get("current_JLens_executed") is False, "collection claim scope")
    hc = handoff.get("collection")
    _require(isinstance(hc, dict) and hc.get("exposed_case_id") == case_id, "handoff case join")
    for key, value in {"actual_completed_observations": 6, "cases": 1,
                       "independent_semantic_labels": 0, "trials_per_model_arm": 1,
                       "native_weight_eligible_observations": 4,
                       "remote_catalog_response_observed_native_weight_ineligible": 2}.items():
        _require(type(hc.get(key)) is int and hc[key] == value, "handoff scope or counts")
    _require(hc.get("all_claim_and_domain_flags_false") is True
             and hc.get("full_suite_executed") is False and hc.get("current_JLens_executed") is False,
             "handoff claim scope")
    model_pairs = hc.get("models")
    _require(isinstance(model_pairs, list) and len(model_pairs) == 3
             and all(isinstance(pair, list) and len(pair) == 2
                     and all(isinstance(value, str) for value in pair) for pair in model_pairs)
             and {tuple(pair) for pair in model_pairs} == {
                 (model, revision if revision is not None else "unobserved remote revision")
                 for model, revision in _MODELS.values()}, "handoff model join")
    source = handoff.get("source")
    _require(isinstance(source, dict), "source binding")
    _sha(source.get("source_sha256"), "source hash")
    _require(isinstance(source.get("head"), str)
             and re.fullmatch(r"[0-9a-f]{40}", source["head"]) is not None, "source head")
    _require(inspection.get("source_head") == source["head"]
             and inspection.get("source_sha256") == source["source_sha256"], "inspection source join")

    rows = _indexed(_records(collection.get("entries"), "six observations required", 6), "collection")
    texts = _indexed(_records(answers.get("answers"), "six answers required", 6), "answers")
    _require(set(rows) == set(texts), "answer observation join")
    case_hashes = {_sha(row.get("case_sha256"), "case hash") for row in rows.values()}
    task_hashes = {_sha(row.get("case_input_sha256"), "task input hash") for row in rows.values()}
    _require(len(case_hashes) == len(task_hashes) == 1, "case/task input hash join")
    case_sha256 = next(iter(case_hashes))
    full_grounding = {}
    for entry in _records(grounding.get("entries"), "three full grounding records required", 3):
        backend = entry.get("backend_id")
        _require(isinstance(backend, str) and backend in _MODELS and backend not in full_grounding
                 and entry.get("arm_id") == "production_full", "grounding model/arm join")
        _require(type(entry.get("source_grounded")) is bool
                 and type(entry.get("draft_final_equal")) is bool
                 and type(entry.get("verification_triggered")) is bool
                 and isinstance(entry.get("verification_action"), str)
                 and isinstance(entry.get("retrieved_doc_ids"), list)
                 and all(isinstance(value, str) for value in entry["retrieved_doc_ids"]), "grounding fields")
        full_grounding[backend] = entry
    helpers = {}
    for entry in _records(handoff.get("Luna_original_receipts"), "two original Luna receipts required", 2):
        _require(isinstance(entry.get("arm"), str), "original helper arm")
        arm = {"raw-model": "raw_model", "production-full": "production_full"}.get(entry.get("arm"))
        _require(arm in _ARMS and arm not in helpers and entry.get("original_status") == "failed",
                 "original helper failure join")
        _require(isinstance(entry.get("original_receipt"), dict), "original helper reference")
        helpers[arm] = entry

    observations, matrix = [], []
    for observation_id, row in rows.items():
        answer_row = texts[observation_id]
        _require(all(answer_row.get(key) == row[key] for key in ("arm_id", "backend_id")),
                 "answer model/arm join")
        model_id, revision = _MODELS[row["backend_id"]]
        _require(row.get("model_id") == model_id and row.get("model_revision") == revision, "model metadata join")
        for value in (row, answer_row):
            for key, expected in {"case_id": case_id, "case_sha256": case_sha256,
                                  "trial_id": "trial-001", "model_id": model_id,
                                  "model_revision": revision}.items():
                _require(key not in value or value[key] == expected, f"optional {key} metadata join")
        _require(row.get("status") == answer_row.get("row_status") == "completed"
                 and type(row.get("worker_exit_code")) is int and row["worker_exit_code"] == 0,
                 "completed observation join")
        _require(type(row.get("model_execution_eligible")) is bool
                 and row["model_execution_eligible"] == (row["backend_id"] != "luna_medium")
                 and answer_row.get("native_weight_model_execution_eligible") is row["model_execution_eligible"],
                 "native eligibility join")
        _require(row.get("claim_eligible") is False and row.get("domain_eligible") is False
                 and "domain_quality" in row and row["domain_quality"] is None, "unqualified domain flags")
        answer = answer_row.get("answer")
        _require(isinstance(answer, str) and bool(answer), "answer text")
        utf8_hash = hashlib.sha256(answer.encode("utf-8")).hexdigest()
        _require(answer_row.get("answer_utf8_sha256") == row.get("answer_utf8_sha256") == utf8_hash,
                 "answer UTF-8 hash join")
        ledger_hash = _digest(answer)
        for value in (row, answer_row):
            if "ledger_answer_identity_sha256" in value:
                _require(value["ledger_answer_identity_sha256"] == ledger_hash, "ledger string hash join")
        _require(answer_row.get("elapsed_seconds") == row.get("elapsed_seconds"), "elapsed time join")
        _require(type(row.get("elapsed_seconds")) in {int, float} and row["elapsed_seconds"] >= 0,
                 "elapsed time value")
        unknown = row.get("unknown", [])
        _require(isinstance(unknown, list) and all(isinstance(item, dict) for item in unknown), "unknown records")
        cell = {"observation_id": observation_id, "suite_id": "six_cell_diagnostic",
                "case_id": case_id, "case_sha256": case_sha256,
                "arm_id": row["arm_id"], "trial_id": "trial-001",
                "backend_id": row["backend_id"], "model_id": model_id, "model_revision": revision}
        normalized = {**deepcopy(row), **cell, "answer": answer, "answer_sha256": ledger_hash,
                      "task_input_sha256": row["case_input_sha256"], "comparison_cohort": None,
                      "identity_status": row.get("identity_status"), "unknown": deepcopy(row.get("unknown", []))}
        if row["arm_id"] == "production_full":
            normalized["retained_grounding"] = deepcopy(full_grounding[row["backend_id"]])
        if row["backend_id"] == "luna_medium":
            _require(row.get("identity_status") == "catalog_verified_response_observed", "remote identity status")
            _require(row.get("original_helper_receipt_status") == helpers[row["arm_id"]]["original_status"],
                     "remote helper status join")
            normalized["original_helper_receipt"] = deepcopy(helpers[row["arm_id"]]["original_receipt"])
        observations.append(normalized)
        matrix.append(cell)

    limitations = handoff.get("remaining_limits")
    _require(isinstance(limitations, list) and all(isinstance(item, str) for item in limitations),
             "evidence limitations")
    limitations = deepcopy(limitations) + [
        "Projection validates local closeout pins and joins only; external archives, SQLite and source bytes are not reread.",
        "No correctness reviews are supplied; analyst interpretations are not expert labels.",
        "The closeout lists field-context keys, not their values; original task-input hashes are preserved.",
    ]
    plan = {"schema_version": "open_agronomy_agent.diagnostic_projection.v1",
            "cases": [{"suite_id": "six_cell_diagnostic", "case_id": case_id,
                       "case_sha256": case_sha256, "question": question,
                       "scenario_family": "official_source_answer_boundary", "lane": "agronomy",
                       "exposure": "exposed_development"}],
            "matrix": matrix, "source": deepcopy(source), "comparison_cohort": None,
            "full_suite_executed": False, "current_JLens_executed": False,
            "historical_JLens_scope": collection.get("historical_bounded_CUDA_JLens"),
            "evidence_bindings": {"closure_sha256": hashlib.sha256(seal_raw).hexdigest(),
                                  "local_files": descriptors}}
    return {"plan": plan, "observations": observations, "reviews": [],
            "comparison_cohort": None, "evidence_limitations": limitations}
