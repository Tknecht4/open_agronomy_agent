#!/usr/bin/env python3
"""Rehearse pinned study-source imports through offline HTTP, in a NEW database.

The script checks deterministic binding only. Expected diagnostics are calculated
outside the runtime requests; they are never added to retrieval or training.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import os
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from agronomy_agent.execution_core import EXECUTION_STAGE_IDS
from agronomy_agent.field_source_preparation import PINS, RAW_DIRECTORY
from agronomy_agent.server.app import create_app
from agronomy_agent.server.settings import build_settings

OWNER = {"X-Agronomy-User-Email": "local-demo@open-agronomy.local"}
OUTSIDER = {"X-Agronomy-User-Email": "source-outsider@example.test"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked(response, status=200):
    if response.status_code != status:
        raise AssertionError(f"HTTP {response.status_code}, expected {status}: {response.text[:1000]}")
    return response.json()


def independent_stats(values: list[str]) -> dict:
    numeric, missing, invalid = [], 0, 0
    for value in values:
        if not value.strip():
            missing += 1
            continue
        try:
            number = float(value)
        except ValueError:
            invalid += 1
            continue
        if not math.isfinite(number):
            invalid += 1
        else:
            numeric.append(number)
    return {"numeric_count": len(numeric), "missing_count": missing, "invalid_count": invalid,
            "mean": math.fsum(numeric)/len(numeric) if numeric else None, "row_count": len(values)}



def verify_answer_binding(question: str, turn: dict, oracle: dict, source_sha: str, database: Path, turn_id: str) -> dict:
    """Validate HTTP, structured and persisted answers against one registered result."""
    trace = turn["trace"]
    metadata = trace.get("metadata", {})
    invocations = [t for t in trace.get("tool_invocations", []) if t.get("tool_id") == "field_table_query"]
    planned = [t for t in invocations if t.get("status") == "planned"]
    executed = [t for t in invocations if t.get("status") == "success" and t.get("result_id")]
    checks = {"one_planned_and_executed": len(planned) == len(executed) == 1}
    if not checks["one_planned_and_executed"]:
        return {"status": "failed", "checks": checks}
    result, plan = executed[0], planned[0]
    payload = result.get("payload", {})
    query = payload.get("query_receipt", {})
    answer = payload.get("answer")
    structured = trace.get("structured_answer", {})
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as conn:
        saved = conn.execute("SELECT user_message, answer, trace FROM turns WHERE id=?", (turn_id,)).fetchone()
    saved_trace = json.loads(saved[2]) if saved else {}
    saved_structured = saved_trace.get("structured_answer", {})
    checks.update({
        "generation_path": metadata.get("generation_path") == "deterministic_tool_result",
        "registered_result": result["result_id"] in metadata.get("tool_result_ids", []),
        "invocation_link": result.get("invocation_id") == plan.get("invocation_id"),
        "question_binding": plan.get("question_sha256") == sha(question.encode()),
        "answer_nonempty": isinstance(answer, str) and bool(answer.strip()),
        "http_answer_binding": turn.get("answer") == answer,
        "structured_answer_binding": structured.get("answer") == answer,
        "structured_markdown_binding": structured.get("public_answer_markdown") == answer,
        "persisted_question_binding": bool(saved) and saved[0] == question,
        "persisted_answer_binding": bool(saved) and saved[1] == answer,
        "persisted_structured_answer_binding": saved_structured.get("answer") == answer,
        "persisted_structured_markdown_binding": saved_structured.get("public_answer_markdown") == answer,
        "source_binding": query.get("source_sha256") == source_sha,
    })
    for key in ("operation", "column", "value", "unit", "selected_row_count", "numeric_count", "missing_count", "invalid_count", "selected_rows_sha256", "mapping_sha256", "member_sha256", "evidence_role", "value_scope"):
        checks["oracle_" + key] = query.get(key) == oracle.get(key)
    failed = [name for name, passed in checks.items() if not passed]
    return {"status": "failed" if failed else "verified", "failed_checks": failed, "checks": checks, "result_id": result["result_id"], "invocation_id": result.get("invocation_id"), "payload_answer_sha256": sha(answer.encode()) if isinstance(answer, str) else None, "http_answer_sha256": sha(turn.get("answer", "").encode())}


def _jobs(raw: Path, prepared: Path) -> list[dict]:
    import openpyxl
    bean_path = "ca-borealis-bean-ayd-field/AYD_Field_Data_4environments_YRKPP.tab"
    data = (raw / bean_path).read_bytes()
    if sha(data) != PINS[bean_path]:
        raise ValueError("original bean SHA mismatch")
    book = openpyxl.load_workbook(io.BytesIO(data), data_only=False, read_only=True)
    try:
        sheet = book["Sheet1"]
        rows = list(sheet.values)
        original = [dict(zip(rows[0], row)) for row in rows[1:] if row[1]]
    finally:
        book.close()
    jobs = []
    for environment in sorted({row["Location"] for row in original}):
        plot = str(next(row["Plot"] for row in original if row["Location"] == environment and isinstance(row["YD"], (int, float)) and row["YD"] != -9999))
        chosen = [row for row in original if row["Location"] == environment and str(row["Plot"]) == plot]
        mapping = {"filters": {"Location": environment, "Plot": plot}, "record_key": ["Year", "Location", "Plot"],
            "source": {"title": f"Reinprecht and Pauls AYD bean: {environment}, plot {plot}", "url": "https://doi.org/10.5683/SP3/FD81LR", "license": "CC-BY-4.0", "citation": f"Original XLSX bytes SHA256={sha(data)}; study plot only, no farm independence or geometry. YD source-adjusted to 18% moisture."},
            "columns": [{"column": "YD", "label": "Seed yield", "unit": "kg/ha", "role": "measurement", "aggregation": "mean", "evidence_role": "observation", "value_scope": "record"}, {"column": "Cultivar", "label": "Cultivar", "unit": None, "role": "identifier", "aggregation": "none", "evidence_role": "observation", "value_scope": "record"}]}
        jobs.append({"label": f"Research bean {environment} plot {plot}", "source_kind": "original_xlsx", "filename": "AYD_Field_Data_4environments_YRKPP.xlsx", "content": data, "mapping": mapping, "column": "YD", "chat_column": "YD", "stats": independent_stats([str(r["YD"]) for r in chosen]), "raw_sha256": sha(data)})
    index = json.loads((prepared / "index.json").read_text())
    selections = [("bean", "ERS15", "source_yd", "source_yd"), ("onion-grower", "Davis_Onion | 2024 | SGS_Lab", "source_nitrogen", "source_nitrogen"), ("onion-grower", "Davis_Onion | 2024 | Picketa_LENS", "source_nitrogen", None), ("onion-trial-yield", "2024", "source_jumbo_bulb_weight_kg", "source_jumbo_bulb_weight_kg"), ("soybean", "1", "source_actual_yield_kg_ha", "source_crop_moisture_content")]
    for source, unit, column, chat_column in selections:
        group = next(g for g in index["groups"] if g["source_id"] == source and g["study_unit"] == unit)
        data = (prepared / group["csv"]).read_bytes()
        mapping_bytes = (prepared / group["mapping"]).read_bytes()
        if sha(data) != group["csv_sha256"] or sha(mapping_bytes) != group["mapping_sha256"]:
            raise ValueError("prepared artifact SHA mismatch")
        mapping = json.loads(mapping_bytes)
        # Explicit rehearsal review selects the queried measurements. Retain raw
        # CSV/manifest identity; bounded chat snapshots must have a complete index.
        if len(mapping["columns"]) > 16:
            mapping["columns"] = [c for c in mapping["columns"] if c["role"] != "measurement" or c["column"] in {column, chat_column}]
        rows = list(csv.DictReader(io.StringIO(data.decode())))
        if not rows or any(r["study_unit"] != unit or group["raw_sha256"] not in r["source_row"] for r in rows):
            raise ValueError("prepared source lineage mismatch")
        jobs.append({"label": f"Research {source} {unit}", "source_kind": "prepared_csv", "filename": group["csv"], "content": data, "mapping": mapping, "column": column, "chat_column": chat_column, "stats": independent_stats([r[column] for r in rows]), "chat_stats": independent_stats([r[chat_column] for r in rows]) if chat_column else None, "raw_sha256": group["raw_sha256"], "manifest_sha256": group["manifest_sha256"]})
    return jobs


def rehearse(raw: Path, prepared: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("rehearsal output exists; no overwrites")
    jobs = _jobs(raw, prepared)
    output.mkdir(parents=True, exist_ok=False)
    # Process-local only: the operator's runtime and existing databases are untouched.
    os.environ["AGRONOMY_AGENT_PRIVATE_KNOWLEDGE"] = "disabled"
    os.environ.pop("AGRONOMY_AGENT_PRIVATE_KNOWLEDGE_MANIFEST", None)
    settings = build_settings(db_path=output / "demo.sqlite3", artifact_root=output / "artifacts", network_mode="offline", allow_model_id_override=True)
    receipt = {"status": "running", "claim": "deterministic source binding only", "network_mode": "offline", "model_id": "mock", "private_knowledge": "disabled", "groups": [], "expected_refusals": [], "source_index_sha256": sha((prepared / "index.json").read_bytes())}
    try:
        with TestClient(create_app(settings)) as client:
            for ordinal, job in enumerate(jobs):
                field = checked(client.post("/api/demo/fields", headers=OWNER, json={"name": job["label"], "field": {"crop": "bean" if "bean" in job["label"] and "soybean" not in job["label"] else "soybean" if "soybean" in job["label"] else "onion", "region": "Research source study unit; geometry unknown"}, "geometry": {"kind": "none"}}), 201)["field"]
                field_id = field["field_context_id"]
                path = f"/api/demo/fields/{field_id}/data"
                preview = checked(client.post(path+"/preview", headers=OWNER, json={"filename": job["filename"], "base64_content": base64.b64encode(job["content"]).decode()}), 201)
                import_id = preview["import_id"]
                if ordinal == 0:
                    unsafe = {**job["mapping"], "filters": {"Location": job["mapping"]["filters"]["Location"]}}
                    rejection = client.post(f"{path}/{import_id}/commit", headers=OWNER, json={"mapping": unsafe})
                    checked(rejection, 422)
                    if "Plot" not in rejection.text:
                        raise AssertionError("expected nested plot scope guard")
                    receipt["expected_refusals"].append({"kind": "location_without_plot_scope", "status": 422, "detail": rejection.json()})
                committed = checked(client.post(f"{path}/{import_id}/commit", headers=OWNER, json={"mapping": job["mapping"]}))["import"]
                if committed["source_sha256"] != sha(job["content"]):
                    raise AssertionError("source identity changed")
                count = checked(client.post(f"{path}/{import_id}/query", headers=OWNER, json={"operation": "count"}))
                mean = checked(client.post(f"{path}/{import_id}/query", headers=OWNER, json={"operation": "mean", "column": job["column"]}))
                expected = job["stats"]
                assert count["value"] == expected["row_count"]
                for key in ("numeric_count", "missing_count", "invalid_count"):
                    assert mean[key] == expected[key], (key, mean[key], expected[key])
                assert math.isclose(mean["value"], expected["mean"], rel_tol=1e-12, abs_tol=1e-12)
                session = checked(client.post("/api/sessions", headers=OWNER, json={"title": job["label"], "tags": ["source_rehearsal", "not_agronomic_validation"], "consent": {"local_trace_capture": True, "training_export_allowed": False, "research_export_allowed": False}, "context": {"field_context_id": field_id}}))
                session_id = session["session_id"]
                question = f"What is the mean {job['chat_column']} in my uploaded data?" if job["chat_column"] else "How many records in my uploaded data?"
                body = {"message": question, "mode": "agronomic_rag", "model_id": "mock", "max_tokens": 80, "session_context": {"field_context_id": field_id}, "trace_options": {"store_prompt_messages": False, "store_retrieved_text": False}}
                response = checked(client.post(f"/api/sessions/{session_id}/turns", headers=OWNER, json=body))
                trace = response["turn"]["trace"]
                metadata = trace["metadata"]
                stages = metadata["execution_stage_receipts"]
                assert [s["stage_id"] for s in stages] == list(EXECUTION_STAGE_IDS)
                assert metadata["generation_path"] == "deterministic_tool_result", metadata.get("generation_path")
                tools = trace["tool_invocations"]
                query = next(t["payload"]["query_receipt"] for t in tools if t["tool_id"] == "field_table_query" and "payload" in t)
                assert query["source_sha256"] == committed["source_sha256"]
                chat_expected = (job.get("chat_stats") or expected)["mean"] if job["chat_column"] else expected["row_count"]
                assert math.isclose(query["value"], chat_expected, rel_tol=1e-12, abs_tol=1e-12)
                chat_oracle = checked(client.post(f"{path}/{import_id}/query", headers=OWNER, json={"operation": "mean", "column": job["chat_column"]})) if job["chat_column"] else count
                binding = verify_answer_binding(question, response["turn"], chat_oracle, committed["source_sha256"], settings.db_path, response["turn_id"])
                if binding["status"] != "verified":
                    receipt["answer_binding_failure"] = {"label": job["label"], "turn_id": response["turn_id"], **binding}
                    raise AssertionError(f"complete answer binding failed: {binding['failed_checks']}")
                denials = {}
                for name, response_denied in {
                    "list": client.get(path, headers=OUTSIDER),
                    "query": client.post(f"{path}/{import_id}/query", headers=OUTSIDER, json={"operation": "count"}),
                    "session_turn": client.post(f"/api/sessions/{session_id}/turns", headers=OUTSIDER, json=body),
                }.items():
                    checked(response_denied, 404 if name == "session_turn" else 403)
                    denials[name] = response_denied.status_code
                group_receipt = {"label": job["label"], "field_id": field_id, "import_id": import_id, "session_id": session_id, "turn_id": response["turn_id"], "source_kind": job["source_kind"], "raw_sha256": job["raw_sha256"], "source_sha256": committed["source_sha256"], "mapping_sha256": committed["mapping_sha256"], "geometry": "none", "row_count": count["value"], "independent_stats": expected, "mean_receipt": mean, "question": question, "answer_binding": binding, "query_receipt": query, "execution_stage_receipts": stages, "generation_path": metadata["generation_path"], "unauthorized_workspace": denials, "evidence_roles": sorted({c["evidence_role"] for c in job["mapping"]["columns"]})}
                if not job["chat_column"]:
                    blocked = checked(client.post(f"/api/sessions/{session_id}/turns", headers=OWNER, json={**body, "message": f"What is the mean {job['column']} in my uploaded data?"}))
                    blocked_meta = blocked["turn"]["trace"]["metadata"]
                    assert blocked_meta["generation_path"] == "deterministic_tool_clarification"
                    group_receipt["model_output_mean_hold"] = {"turn_id": blocked["turn_id"], "generation_path": blocked_meta["generation_path"], "answer": blocked["turn"]["answer"]}
                receipt["groups"].append(group_receipt)
        with sqlite3.connect(settings.db_path) as conn:
            conn.row_factory = sqlite3.Row
            blobs = [dict(r) for r in conn.execute("SELECT source_sha256, raw_size, encoded_size, codec FROM field_data_source_blobs ORDER BY source_sha256")]
            imported = [dict(r) for r in conn.execute("SELECT source_sha256, source_storage, length(source_bytes) AS inline_size FROM field_data_imports")]
            receipt["storage"] = {"blob_count": len(blobs), "import_count": len(imported), "blobs": blobs, "unique_raw_bytes": sum(b["raw_size"] for b in blobs), "compressed_bytes": sum(b["encoded_size"] for b in blobs), "unshared_raw_bytes": sum(len(j["content"]) for j in jobs), "inline_bytes": sum(r["inline_size"] for r in imported), "source_storage": sorted({r["source_storage"] for r in imported})}
            assert len(blobs) == 6 and len(imported) == 9
            bean_sha = jobs[0]["raw_sha256"]
            assert sum(r["source_sha256"] == bean_sha for r in imported) == 4
            assert sum(b["source_sha256"] == bean_sha for b in blobs) == 1
        receipt["original_inputs_unchanged"] = all(sha((raw / path).read_bytes()) == pin for path, pin in PINS.items())
        assert receipt["original_inputs_unchanged"]
        receipt["status"] = "verified_complete_answer_and_source_binding"
    except Exception as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--raw-root", type=Path, default=root / RAW_DIRECTORY)
    parser.add_argument("--prepared-root", type=Path, default=root / "outputs/field-source-preparation-20260927")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    receipt = rehearse(args.raw_root.resolve(), args.prepared_root.resolve(), args.output_dir.resolve())
    print(json.dumps({"status": receipt["status"], "imports": len(receipt["groups"]), "storage": receipt["storage"]}, indent=2))


if __name__ == "__main__":
    main()
