#!/usr/bin/env python3
"""Run a separately authorized, post-hoc blinded semantic review for RC3.

This is deliberately not part of the frozen RC3 generation identity.  It
materializes only the existing two-arm primary-lane review packets, binds every
outbound Luna request to a hash of that selection and the fixed rubric/schema,
and writes a successor evidence directory.  The original experiment tree is
read-only input.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import threading
from pathlib import Path
from typing import Any, Iterable

from agronomy_agent.codex_app_server import CodexAppServerClient, DEFAULT_APP_SERVER_COMMAND


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts" / "run_codex_semantic_answer_judge.py"
DEFAULT_EXPERIMENT = ROOT / "outputs" / "open_agronomy_canadian_performance_v1_runtime_v2_rc3"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "open_agronomy_canadian_performance_v1_runtime_v2_rc3_posthoc_semantic_review"
AUTH_SCHEMA = "open_agronomy_agent.rc3_posthoc_semantic_judge_egress_authorization.v1"
SELECTION_SCHEMA = "open_agronomy_agent.rc3_posthoc_semantic_judge_selection.v1"
RECEIPT_SCHEMA = "open_agronomy_agent.rc3_posthoc_semantic_judge_receipt.v1"
PAYLOAD_CLASSES = (
    "project_owned_frozen_benchmark_questions",
    "candidate_answers",
    "benchmark_reference_and_rubric_for_judging",
)
FORBIDDEN_CLASSES = (
    "farmer_records",
    "private_field_history",
    "credentials",
    "local_knowledge_corpus_files",
)
INSTRUCTION_SOURCE_TOKEN = "user_global_agents_md"


def _authorized_instruction_source_paths(tokens: Sequence[str]) -> tuple[str, ...]:
    """Resolve public authorization tokens without serializing a home path."""

    if tuple(tokens) != (INSTRUCTION_SOURCE_TOKEN,):
        raise ValueError("judge authorization instruction source differs from the approved user-level governance token")
    return (str((Path.home() / ".codex" / "AGENTS.md").resolve()),)


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("semantic_judge_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load semantic judge base: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_base()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"expected object rows: {path}")
    return rows


def _relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        # Fixtures and controlled recovery copies can live outside the checkout.
        # Their absolute path is retained only in the private selection manifest.
        return str(resolved)


def _packet_records(experiment: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for manifest_path in sorted(experiment.glob("*/trial-*/review_packets/*/manifest.json")):
        manifest = _read_json(manifest_path)
        if manifest.get("schema_version") != "open_agronomy_agent.agronomist_answer_review_packet.v1":
            raise ValueError(f"unexpected review packet schema: {manifest_path}")
        if manifest.get("rows") != 180:
            raise ValueError(f"RC3 review packet must contain 180 rows: {manifest_path}")
        phase_b = manifest.get("phase_b") or {}
        phase_b_path = manifest_path.parent / str(phase_b.get("path") or "")
        if not phase_b_path.is_file() or _sha_path(phase_b_path) != phase_b.get("sha256"):
            raise ValueError(f"review packet phase B receipt mismatch: {manifest_path}")
        identity = manifest.get("identity_map") or {}
        identity_path = manifest_path.parent / str(identity.get("path") or "")
        if not identity_path.is_file() or _sha_path(identity_path) != identity.get("sha256"):
            raise ValueError(f"review packet identity receipt mismatch: {manifest_path}")
        trial = manifest_path.parents[2].name
        model_key = manifest_path.parents[3].name
        phase_b_rows = _read_jsonl(phase_b_path)
        identity_rows = {str(row.get("review_id") or ""): row for row in _read_jsonl(identity_path)}
        if len(phase_b_rows) != 180 or set(identity_rows) != {str(row.get("review_id") or "") for row in phase_b_rows}:
            raise ValueError(f"review packet identity mapping is incomplete: {manifest_path}")
        for row in phase_b_rows:
            review_id = str(row.get("review_id") or "")
            if not re.fullmatch(r"agr_[0-9a-f]{20}", review_id):
                raise ValueError(f"invalid opaque review ID: {review_id!r}")
            semantic_reference = {
                "expert_reference_points": list(row.get("non_exhaustive_reference_points") or []),
                "material_errors": list(row.get("known_material_error_hypotheses") or []),
                "critical_evidence": list(row.get("critical_evidence") or []),
                "safe_boundary": row.get("safe_boundary"),
                "reference_boundary": row.get("reference_boundary"),
            }
            # RC3 packets intentionally restart their opaque IDs per trial.
            # Derive a fresh opaque ID for this cross-trial companion without
            # exposing the model/arm label to the judge prompt.
            posthoc_review_id = "sem_" + _sha_text(
                f"{model_key}|{trial}|{review_id}"
            )[:20]
            records.append(
                {
                    "review_id": posthoc_review_id,
                    "question": str(row.get("question") or ""),
                    "answer": str(row.get("answer") or ""),
                    "task_family": str(row.get("task_family") or ""),
                    "eval_metadata": {
                        "crop": row.get("crop"),
                        "jurisdiction": row.get("jurisdiction"),
                    },
                    "semantic_reference": semantic_reference,
                    # Not included in the blinded prompt; retained only in the
                    # local selection and judgment artifacts for aggregation.
                    "selection_provenance": {
                        "model_key": model_key,
                        "trial_id": trial,
                        "packet_review_id": review_id,
                        "source_label": identity_rows[review_id].get("source_label"),
                        "eval_id": identity_rows[review_id].get("eval_id"),
                        "answer_sha256": identity_rows[review_id].get("answer_sha256"),
                        "packet_manifest": _relative(manifest_path),
                    },
                }
            )
    if len(records) != 1_620:
        raise ValueError(f"expected 1,620 packet rows, found {len(records)}")
    review_ids = [str(row["review_id"]) for row in records]
    if len(review_ids) != len(set(review_ids)):
        raise ValueError("opaque review IDs collide across RC3 packets")
    return records


def _selection_manifest(experiment: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    packets: dict[str, str] = {}
    for row in records:
        path = str((row.get("selection_provenance") or {}).get("packet_manifest") or "")
        if path:
            packets[path] = _sha_path(ROOT / path)
    identity_rows = [
        {
            "review_id": row["review_id"],
            "question_sha256": _sha_text(str(row["question"])),
            "answer_sha256": _sha_text(str(row["answer"])),
            "semantic_reference_sha256": _sha_text(_canonical(row["semantic_reference"])),
            "source": row["selection_provenance"],
        }
        for row in records
    ]
    payload: dict[str, Any] = {
        "schema_version": SELECTION_SCHEMA,
        "status": "prepared_for_authorized_posthoc_blinded_semantic_review",
        "source_experiment": _relative(experiment),
        "source_experiment_sha256": _sha_text(_relative(experiment)),
        "selection": "all nine immutable RC3 two-arm primary-lane review packets",
        "row_count": len(records),
        "packet_manifest_sha256": dict(sorted(packets.items())),
        "records": identity_rows,
        "payload_classes": list(PAYLOAD_CLASSES),
        "excluded_payload_classes": list(FORBIDDEN_CLASSES),
        "claim_eligible": False,
        "boundary": "Post-hoc automated semantic triage only; original RC3 generation remains judge-free and immutable.",
    }
    payload["sha256"] = _sha_text(_canonical(payload))
    return payload


def prepare(experiment: Path, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records = _packet_records(experiment)
    selection = _selection_manifest(experiment, records)
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = output_dir / "private_blinded_inputs.jsonl"
    inputs.write_text("".join(_canonical(row) + "\n" for row in records), encoding="utf-8")
    (output_dir / "selection_manifest.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    request = {
        "schema_version": AUTH_SCHEMA,
        "authorization_decision": "awaiting_human_authorization",
        "selection_manifest_sha256": selection["sha256"],
        "judge_prompt_sha256": _sha_text(BASE.judge_instructions("semantic_answer_quality")),
        "judge_output_schema_sha256": _sha_text(_canonical(BASE.judge_schema())),
        "recipient_backend": "codex_app_server_chatgpt_auth",
        "model_id": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "authorized_payload_classes": list(PAYLOAD_CLASSES),
        "excluded_payload_classes": list(FORBIDDEN_CLASSES),
        "row_count": len(records),
    }
    (output_dir / "authorization_request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    return records, selection


def _parse_time(value: object) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("authorization timestamps require timezone")
    return parsed.astimezone(dt.UTC)


def validate_authorization(path: Path, selection: dict[str, Any]) -> dict[str, Any]:
    auth = _read_json(path)
    required = {
        "schema_version", "authorization_decision", "authorization_source", "authorized_by_key_id",
        "authorized_at", "expires_at", "recipient_backend", "model_id", "reasoning_effort",
        "selection_manifest_sha256", "judge_prompt_sha256", "judge_output_schema_sha256",
        "authorized_payload_classes", "excluded_payload_classes", "instruction_sources",
        "instruction_sources_sha256", "claim_eligible",
    }
    missing = sorted(required - set(auth))
    if missing:
        raise ValueError(f"judge authorization lacks fields: {missing}")
    if auth["schema_version"] != AUTH_SCHEMA or auth["authorization_decision"] != "authorized":
        raise ValueError("judge authorization is not an authorized post-hoc RC3 receipt")
    if auth["recipient_backend"] != "codex_app_server_chatgpt_auth" or auth["model_id"] != "gpt-5.6-luna" or auth["reasoning_effort"] != "high":
        raise ValueError("judge authorization recipient identity differs from the approved Luna High judge")
    if auth["selection_manifest_sha256"] != selection["sha256"]:
        raise ValueError("judge authorization selection identity mismatch")
    if auth["judge_prompt_sha256"] != _sha_text(BASE.judge_instructions("semantic_answer_quality")):
        raise ValueError("judge authorization prompt identity mismatch")
    if auth["judge_output_schema_sha256"] != _sha_text(_canonical(BASE.judge_schema())):
        raise ValueError("judge authorization schema identity mismatch")
    if tuple(auth["authorized_payload_classes"]) != PAYLOAD_CLASSES or tuple(auth["excluded_payload_classes"]) != FORBIDDEN_CLASSES:
        raise ValueError("judge authorization payload taxonomy differs from the approved post-hoc boundary")
    resolved_sources = _authorized_instruction_source_paths([str(value) for value in auth["instruction_sources"]])
    source_path = Path(resolved_sources[0])
    if not source_path.is_file() or auth["instruction_sources_sha256"] != _sha_path(source_path):
        raise ValueError("judge authorization instruction-source identity mismatch")
    if auth["claim_eligible"] is not False:
        raise ValueError("automated post-hoc judge authorization must remain non-claim")
    now = dt.datetime.now(dt.UTC)
    if not (_parse_time(auth["authorized_at"]) <= now < _parse_time(auth["expires_at"])):
        raise ValueError("judge authorization is outside its UTC validity interval")
    auth["sha256"] = _sha_text(_canonical({key: value for key, value in auth.items() if key != "sha256"}))
    return auth


class AuthorizedLunaRunner:
    def __init__(self, *, authorization: dict[str, Any], selection: dict[str, Any], timeout_seconds: float) -> None:
        self.authorization = authorization
        self.selection = selection
        self.timeout_seconds = timeout_seconds
        self._local = threading.local()
        self._clients: list[CodexAppServerClient] = []
        self._clients_lock = threading.Lock()

    def _client(self) -> CodexAppServerClient:
        client = getattr(self._local, "client", None)
        if client is not None:
            return client
        client = CodexAppServerClient(
            command=DEFAULT_APP_SERVER_COMMAND,
            # Let the hardened client create and own a fresh empty directory.
            cwd=None,
            timeout_seconds=self.timeout_seconds,
            expected_model="gpt-5.6-luna",
            expected_reasoning_effort="high",
            collect_protocol_identity=True,
            allowed_instruction_sources=_authorized_instruction_source_paths(
                [str(value) for value in self.authorization["instruction_sources"]]
            ),
        )
        self._local.client = client
        with self._clients_lock:
            self._clients.append(client)
        return client

    def __call__(self, *, prompt: str, schema_path: Path, result_path: Path, model: str, reasoning_effort: str, cwd: Path) -> dict[str, Any]:
        del cwd
        if model != self.authorization["model_id"] or reasoning_effort != self.authorization["reasoning_effort"]:
            raise ValueError("judge invocation recipient differs from authorization")
        instructions = BASE.judge_instructions("semantic_answer_quality")
        prefix = instructions + "\n"
        if not prompt.startswith(prefix):
            raise ValueError("judge runner received a non-canonical blinded prompt")
        user_text = prompt[len(prefix):]
        result = self._client().generate(
            user_text=user_text,
            base_instructions=instructions,
            output_schema=json.loads(schema_path.read_text(encoding="utf-8")),
            metadata={"application": "open-agronomy-rc3-posthoc-review", "role": "semantic-judge"},
        )
        payload = json.loads(result.text)
        normalizations = self._normalize_review_ids(payload, user_text)
        receipt = dict(result.receipt)
        receipt["posthoc_semantic_judge_egress"] = {
            "schema_version": RECEIPT_SCHEMA,
            "authorization_sha256": self.authorization["sha256"],
            "selection_manifest_sha256": self.selection["sha256"],
            "payload_classes": list(PAYLOAD_CLASSES),
            "excluded_payload_classes": list(FORBIDDEN_CLASSES),
            "judge_prompt_sha256": self.authorization["judge_prompt_sha256"],
            "judge_output_schema_sha256": self.authorization["judge_output_schema_sha256"],
            "instruction_sources_sha256": self.authorization["instruction_sources_sha256"],
            "input_sha256": _sha_text(user_text),
            "review_id_normalizations": normalizations,
        }
        # Keep the original model payload beside the canonical normalized file
        # whenever an opaque-ID copy repair was necessary.
        if normalizations:
            result_path.with_suffix(".raw_model.json").write_text(result.text + "\n", encoding="utf-8")
        result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        result_path.with_suffix(".receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return payload

    @staticmethod
    def _normalize_review_ids(payload: Any, user_text: str) -> list[dict[str, str]]:
        """Repair only an unambiguous truncated opaque ID copied by the judge.

        This never repairs judgment content or accepts a collision: an emitted ID
        must be a suffix of exactly one requested opaque ID, at least 16 hex
        characters long, and retain the ``sem_`` namespace.
        """
        if not isinstance(payload, dict) or not isinstance(payload.get("judgments"), list):
            return []
        marker = "Blinded records:\n"
        if marker not in user_text:
            raise ValueError("judge prompt lacks its canonical blinded-record section")
        rows = json.loads(user_text.split(marker, 1)[1])
        expected = {str(row.get("review_id") or "") for row in rows if isinstance(row, dict)}
        normalizations: list[dict[str, str]] = []
        for judgment in payload["judgments"]:
            if not isinstance(judgment, dict):
                continue
            received = str(judgment.get("review_id") or "")
            if received in expected:
                continue
            if not re.fullmatch(r"sem_[0-9a-f]{16,20}", received):
                continue
            suffix = received.removeprefix("sem_")
            matches = sorted(value for value in expected if value.removeprefix("sem_").endswith(suffix))
            if len(matches) == 1:
                judgment["review_id"] = matches[0]
                normalizations.append({"received": received, "canonical": matches[0]})
        return normalizations

    def close(self) -> None:
        for client in self._clients:
            client.close()
        self._clients.clear()


def _write_public_summary(output_dir: Path, judgments: Iterable[dict[str, Any]], authorization: dict[str, Any], selection: dict[str, Any]) -> None:
    rows = list(judgments)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        provenance = row.get("selection_provenance") or {}
        key = "|".join(str(provenance.get(name) or "") for name in ("model_key", "trial_id", "source_label"))
        groups.setdefault(key, []).append(row)
    summaries = []
    for key, group in sorted(groups.items()):
        model_key, trial_id, source_label = key.split("|", 2)
        dispositions: dict[str, int] = {}
        for row in group:
            value = str(row.get("answer_disposition") or "")
            dispositions[value] = dispositions.get(value, 0) + 1
        summaries.append({
            "model_key": model_key,
            "trial_id": trial_id,
            "source_label": source_label,
            "rows": len(group),
            "semantic_score_mean": round(sum(float(row["semantic_score_0_to_100"]) for row in group) / len(group), 4),
            "pass": dispositions.get("pass", 0),
            "revise": dispositions.get("revise", 0),
            "fail": dispositions.get("fail", 0),
        })
    payload = {
        "schema_version": "open_agronomy_agent.rc3_posthoc_semantic_review_summary.v1",
        "status": "complete_uncalibrated_blinded_ai_triage_nonclaim",
        "claim_eligible": False,
        "source_generation": "frozen_rc3_unchanged",
        "review_rows": len(rows),
        "selection_manifest_sha256": selection["sha256"],
        "authorization_sha256": authorization["sha256"],
        "judge": {"backend": "codex_app_server_chatgpt_auth", "model_id": "gpt-5.6-luna", "reasoning_effort": "high"},
        "results": summaries,
        "boundary": "Blinded automated semantic triage of saved RC3 primary-lane answers. No calibration against independent agronomist labels, no human adjudication, and no promotion authority.",
    }
    (output_dir / "public_safe_summary.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=360.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1 or args.workers < 1:
        raise SystemExit("--batch-size and --workers must be at least one")
    records, selection = prepare(args.experiment.resolve(), args.output_dir.resolve())
    if args.prepare_only:
        print(json.dumps({"status": "prepared", "rows": len(records), "selection_manifest_sha256": selection["sha256"]}, indent=2))
        return 0
    if args.authorization is None:
        raise SystemExit("--authorization is required before any Luna semantic-review request")
    authorization = validate_authorization(args.authorization.resolve(), selection)
    inputs = args.output_dir / "private_blinded_inputs.jsonl"
    runner = AuthorizedLunaRunner(authorization=authorization, selection=selection, timeout_seconds=args.timeout_seconds)
    try:
        summary = BASE.run(
            outputs_path=inputs,
            output_dir=args.output_dir / "semantic_answer_quality",
            batch_size=args.batch_size,
            model="gpt-5.6-luna",
            reasoning_effort="high",
            limit=args.limit,
            overwrite=args.overwrite,
            workers=args.workers,
            runner=runner,
            judge_backend="codex_app_server_authorized_posthoc",
            judge_role="semantic_answer_quality",
        )
    finally:
        runner.close()
    judgments = _read_jsonl(args.output_dir / "semantic_answer_quality" / "judgments.jsonl")
    for row in judgments:
        source = next((record for record in records if record["review_id"] == row.get("review_id")), None)
        if source is None:
            raise ValueError("judgment review ID is outside selected immutable packet rows")
        row["selection_provenance"] = source["selection_provenance"]
    (args.output_dir / "semantic_answer_quality" / "judgments.jsonl").write_text(
        "".join(_canonical(row) + "\n" for row in judgments), encoding="utf-8"
    )
    summary.update({"authorization_sha256": authorization["sha256"], "selection_manifest_sha256": selection["sha256"], "claim_eligible": False})
    (args.output_dir / "semantic_answer_quality" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _write_public_summary(args.output_dir, judgments, authorization, selection)
    print(json.dumps({"status": "complete", "rows": len(judgments), "selection_manifest_sha256": selection["sha256"], "authorization_sha256": authorization["sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
