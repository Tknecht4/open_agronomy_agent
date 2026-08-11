from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.local_inference_preview.v1"
LAUNCH_GATE_ID = "local_inference_boundary"
DEFAULT_MATRIX = ROOT / "plans/agronomy_agent_phase6_pre_demo_launch_packet/phase6_webgpu_client_inference_decision_matrix.csv"
DEFAULT_LAUNCH_MATRIX = ROOT / "docs/phase6_launch_gate_matrix.yaml"
DEFAULT_LOCAL_PREVIEW = ROOT / "frontend/src/localPreview.ts"
DEFAULT_LOCAL_PREVIEW_TEST = ROOT / "frontend/src/localPreview.test.ts"
DEFAULT_HOSTED_PLATFORM = ROOT / "frontend/src/HostedPlatform.tsx"
DEFAULT_PACKAGE_JSON = ROOT / "frontend/package.json"
DEFAULT_DOC = ROOT / "docs/phase6_local_inference_preview.md"
REQUIRED_MATRIX_EVIDENCE = (
    "docs/phase6_local_inference_preview.md",
    "scripts/validate_phase6_local_inference_preview.py",
    "tests/test_phase6_local_inference_preview.py",
    "outputs/phase6_local_inference_preview_latest.json",
    "frontend/src/localPreview.ts",
    "frontend/src/localPreview.test.ts",
    "frontend/src/App.test.tsx",
)

EXPECTED_MATRIX: dict[str, dict[str, str]] = {
    "canonical agronomy answer": {
        "task_id": "canonical_agronomy_answer",
        "risk": "medium/high/regulated",
        "candidate_runtime": "server 4-bit harness",
        "allowed_phase6": "yes",
        "default": "yes",
        "notes": "Retains full trace/eval/guardrail path.",
        "output_label": "server_harness_required",
    },
    "local summarization of user notes": {
        "task_id": "local_note_summarization",
        "risk": "low",
        "candidate_runtime": "Transformers.js or Chrome built-in AI",
        "allowed_phase6": "yes behind flag",
        "default": "no",
        "notes": "Useful privacy/cost experiment; do not treat as final advice.",
        "output_label": "local_draft_allowed",
    },
    "rewrite report section": {
        "task_id": "report_section_rewrite",
        "risk": "low",
        "candidate_runtime": "WebLLM or built-in Writer/Rewriter API",
        "allowed_phase6": "yes behind flag",
        "default": "no",
        "notes": "Clearly label local draft.",
        "output_label": "local_draft_allowed",
    },
    "image embedding / similarity search": {
        "task_id": "image_embedding_similarity",
        "risk": "low/medium",
        "candidate_runtime": "Transformers.js/OpenCLIP-style model",
        "allowed_phase6": "research only",
        "default": "no",
        "notes": "May help VLM-RAG, but calibration required.",
        "output_label": "research_only",
    },
    "regulated product/label answer": {
        "task_id": "regulated_product_label_answer",
        "risk": "regulated",
        "candidate_runtime": "server harness only",
        "allowed_phase6": "yes",
        "default": "yes",
        "notes": "Never local-only in Phase 6.",
        "output_label": "server_harness_required",
    },
    "field-specific diagnostic answer": {
        "task_id": "field_specific_diagnostic_answer",
        "risk": "medium",
        "candidate_runtime": "server harness only",
        "allowed_phase6": "yes",
        "default": "yes",
        "notes": "Local preprocessing okay, final answer server.",
        "output_label": "local_preprocess_allowed",
    },
    "offline toy demo": {
        "task_id": "offline_toy_demo",
        "risk": "low",
        "candidate_runtime": "WebLLM small model",
        "allowed_phase6": "optional",
        "default": "no",
        "notes": "Use synthetic data and visible limitations.",
        "output_label": "local_draft_allowed",
    },
    "private field notes preprocessing": {
        "task_id": "private_field_notes_preprocessing",
        "risk": "low",
        "candidate_runtime": "client worker + optional local model",
        "allowed_phase6": "yes behind consent",
        "default": "no",
        "notes": "Never silently upload or cache raw notes.",
        "output_label": "local_preprocess_allowed",
    },
}

FORBIDDEN_MODEL_PACKAGES = {
    "@huggingface/transformers",
    "@mlc-ai/web-llm",
    "webllm",
    "onnxruntime-web",
}


def validate_phase6_local_inference_preview(
    *,
    matrix_csv: Path = DEFAULT_MATRIX,
    launch_matrix_path: Path = DEFAULT_LAUNCH_MATRIX,
    local_preview_ts: Path = DEFAULT_LOCAL_PREVIEW,
    local_preview_test: Path = DEFAULT_LOCAL_PREVIEW_TEST,
    hosted_platform_tsx: Path = DEFAULT_HOSTED_PLATFORM,
    package_json: Path = DEFAULT_PACKAGE_JSON,
    doc_path: Path = DEFAULT_DOC,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    matrix_rows = _load_matrix(matrix_csv, failures)
    launch_matrix = _load_yaml(launch_matrix_path, "launch_gate_matrix", failures)
    local_preview_text = _read_text(local_preview_ts, "local_preview_ts", failures)
    local_preview_test_text = _read_text(local_preview_test, "local_preview_test", failures)
    hosted_text = _read_text(hosted_platform_tsx, "hosted_platform", failures)
    package_payload = _load_json(package_json, "package_json", failures)
    doc_text = _read_text(doc_path, "docs", failures)

    task_names = {row.get("task", "") for row in matrix_rows}
    gate = _launch_gate(launch_matrix)
    _expect(gate is not None, "launch_gate_matrix", "launch matrix must track local_inference_boundary", failures)
    if gate is not None:
        _expect(gate.get("status") == "complete", "launch_gate_matrix", "local inference launch gate must remain complete", failures)
        evidence = {str(item) for item in gate.get("evidence") or []}
        for required in REQUIRED_MATRIX_EVIDENCE:
            _expect(required in evidence, "launch_gate_matrix", f"local inference gate evidence must include {required}", failures)
            if not required.startswith("outputs/"):
                _expect((ROOT / required).exists(), "launch_gate_matrix", f"local inference gate evidence path missing: {required}", failures)

    _expect(task_names == set(EXPECTED_MATRIX), "matrix", f"matrix tasks must exactly match packet launch set: {sorted(task_names)}", failures)
    _expect(len(matrix_rows) == len(EXPECTED_MATRIX), "matrix", "matrix row count must remain 8", failures)

    for task, expected in EXPECTED_MATRIX.items():
        row = next((item for item in matrix_rows if item.get("task") == task), None)
        if row is None:
            continue
        for field in ("risk", "candidate_runtime", "allowed_phase6", "default", "notes"):
            _expect(
                str(row.get(field) or "").strip() == expected[field],
                "matrix",
                f"{task} {field} drifted from packet value",
                failures,
            )
        _expect(f"{expected['task_id']}:" in local_preview_text, "local_preview_ts", f"frontend matrix missing task id {expected['task_id']}", failures)
        _expect(expected["candidate_runtime"] in local_preview_text, "local_preview_ts", f"frontend matrix missing runtime for {expected['task_id']}", failures)
        _expect(expected["notes"] in local_preview_text, "local_preview_ts", f"frontend matrix missing notes for {expected['task_id']}", failures)

    _expect(
        "VITE_ENABLE_WEBGPU_PREVIEW === 'true'" in local_preview_text,
        "local_preview_ts",
        "local preview must remain behind explicit feature flag",
        failures,
    )
    _expect(
        "No local model download is allowed until feature flag, user consent, and explicit model-download confirmation are all true." in local_preview_text,
        "local_preview_ts",
        "no-download guarantee text must remain explicit",
        failures,
    )
    _expect(
        "downloadAllowed = localDraftAllowed && downloadConsent" in local_preview_text,
        "local_preview_ts",
        "downloads must require local draft eligibility and explicit download consent",
        failures,
    )
    _expect(
        "trainingCandidateAllowed = localDraftAllowed && consentGranted && syncedAndReviewed" in local_preview_text,
        "local_preview_ts",
        "local drafts must require consent and sync review before training candidacy",
        failures,
    )
    _expect(
        "canonicalAnswerPath: 'server_harness'" in local_preview_text,
        "local_preview_ts",
        "canonical answer path must remain server_harness",
        failures,
    )
    _expect(
        "No browser model download" in local_preview_test_text and "keeps all local model downloads blocked by default" in local_preview_test_text,
        "local_preview_test",
        "frontend tests must cover no-download default behavior",
        failures,
    )
    _expect(
        "model_download_notice" in hosted_text and "webgpu_probe_completed" in hosted_text,
        "hosted_platform",
        "hosted platform must emit local-preview notice/probe telemetry",
        failures,
    )
    _expect(
        "No Transformers.js or WebLLM package is imported" in doc_text and "No browser model download or cache write" in doc_text,
        "docs",
        "local inference doc must preserve no-import/no-download boundary",
        failures,
    )

    dependencies = {
        **(package_payload.get("dependencies") if isinstance(package_payload.get("dependencies"), dict) else {}),
        **(package_payload.get("devDependencies") if isinstance(package_payload.get("devDependencies"), dict) else {}),
    }
    forbidden_dependencies = sorted(set(dependencies) & FORBIDDEN_MODEL_PACKAGES)
    for package in forbidden_dependencies:
        failures.append({"section": "package_json", "reason": f"real local model package dependency is not allowed before research signoff: {package}"})

    forbidden_imports = _forbidden_imports(local_preview_text, hosted_text)
    for package in forbidden_imports:
        failures.append({"section": "frontend_imports", "reason": f"real local model package import is not allowed before research signoff: {package}"})

    default_enabled_task_ids = sorted(EXPECTED_MATRIX[row["task"]]["task_id"] for row in matrix_rows if row.get("default") == "yes" and row.get("task") in EXPECTED_MATRIX)
    server_required_task_ids = sorted(
        expected["task_id"]
        for expected in EXPECTED_MATRIX.values()
        if expected["candidate_runtime"] in {"server 4-bit harness", "server harness only"}
    )
    download_eligible_task_ids = sorted(
        expected["task_id"]
        for expected in EXPECTED_MATRIX.values()
        if expected["output_label"] == "local_draft_allowed"
    )
    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "launch_gate_complete": gate is not None and gate.get("status") == "complete",
        "matrix_task_count": len(matrix_rows),
        "expected_task_count": len(EXPECTED_MATRIX),
        "default_enabled_task_ids": default_enabled_task_ids,
        "server_harness_required_task_ids": server_required_task_ids,
        "download_eligible_task_ids": download_eligible_task_ids,
        "feature_flag_required": "VITE_ENABLE_WEBGPU_PREVIEW === 'true'" in local_preview_text,
        "explicit_download_consent_required": "downloadAllowed = localDraftAllowed && downloadConsent" in local_preview_text,
        "canonical_answer_path": "server_harness",
        "no_download_boundary": not forbidden_dependencies and not forbidden_imports,
        "forbidden_dependencies": forbidden_dependencies,
        "forbidden_imports": forbidden_imports,
        "human_research_signoff_required": True,
        "human_research_signoff_reason": "Automated source checks cannot approve real browser model downloads, cache controls, or local answer generation.",
        "evidence": {
            "matrix_csv": _display_path(matrix_csv),
            "launch_gate_matrix": _display_path(launch_matrix_path),
            "local_preview_ts": _display_path(local_preview_ts),
            "local_preview_test": _display_path(local_preview_test),
            "hosted_platform": _display_path(hosted_platform_tsx),
            "package_json": _display_path(package_json),
            "docs": _display_path(doc_path),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def _launch_gate(matrix: dict[str, Any]) -> dict[str, Any] | None:
    for row in matrix.get("launch_gates") or []:
        if isinstance(row, dict) and row.get("id") == LAUNCH_GATE_ID:
            return row
    return None


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_matrix(path: Path, failures: list[dict[str, str]]) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [{str(key): str(value).strip() for key, value in row.items()} for row in csv.DictReader(handle)]
    except Exception as exc:
        failures.append({"section": "matrix", "reason": f"could not read {_display_path(path)}: {exc}"})
        return []
    required_fields = {"task", "risk", "candidate_runtime", "allowed_phase6", "default", "notes"}
    for row in rows:
        missing = sorted(required_fields - set(row))
        if missing:
            failures.append({"section": "matrix", "reason": f"matrix row missing fields: {missing}"})
    return rows


def _load_yaml(path: Path, section: str, failures: list[dict[str, str]]) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return {}
    if not isinstance(payload, dict):
        failures.append({"section": section, "reason": f"{_display_path(path)} must contain a YAML mapping"})
        return {}
    return payload


def _read_text(path: Path, section: str, failures: list[dict[str, str]]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return ""


def _load_json(path: Path, section: str, failures: list[dict[str, str]]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return {}
    if not isinstance(payload, dict):
        failures.append({"section": section, "reason": f"{_display_path(path)} must contain a JSON object"})
        return {}
    return payload


def _forbidden_imports(*texts: str) -> list[str]:
    imports: set[str] = set()
    pattern = re.compile(r"\b(?:import|from)\s+(?:[^'\"]+\s+from\s+)?['\"]([^'\"]+)['\"]")
    for text in texts:
        for match in pattern.finditer(text):
            package = match.group(1)
            if package in FORBIDDEN_MODEL_PACKAGES:
                imports.add(package)
    return sorted(imports)


def _expect(condition: bool, section: str, reason: str, failures: list[dict[str, str]]) -> None:
    if not condition:
        failures.append({"section": section, "reason": reason})


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
