"""Exposed development pilot over source-pinned, dependent field-data slices.

This module is offline maintainer tooling. Nothing imports it from the product
path. Gold cases are read only by the benchmark runner, after the runtime input
and private field store have been constructed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import platform
import sys
import tempfile
from collections import defaultdict
from importlib import metadata as package_metadata
from pathlib import Path
from typing import Any

from agronomy_agent.server.storage.db import TraceStore
from agronomy_agent.server.storage.field_data_store import commit_import, preview_import, query_import

SCHEMA = "field_data_pilot.v1"
SOURCE_DEFS = {
    "akron": {
        "filename": "akron_modeling_data.csv",
        "sha256": "a1599b9c523f4ed44efd9b7f0c3ba6baf9f263f7c274415c77b4eb81d623f38b",
        "url": "https://agdatacommons.nal.usda.gov/articles/dataset/Data_from_Topographic_position_index_predicts_within-field_yield_variation_in_a_dryland_cereal_production_system/28914434",
        "download_url": "https://ndownloader.figshare.com/files/54132527",
        "title": "Topographic position index predicts within-field yield variation in a dryland cereal production system",
        "license": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "attribution": "USDA Ag Data Commons / Poss et al., record 28914434",
        "columns": ["field", "year", "crop", "easting_UTM13N", "northing_UTM13N", "yield_kg_ha"],
        "dependency_group": "Akron research site; multiple management units and seasons",
    },
    "nitrate": {
        "filename": "corn_stalk_nitrate.csv",
        "sha256": "5186e2ee41a6dfe975edcef44e6b10633e05dfde3dd2da4b3bb276e994a62513",
        "url": "https://agdatacommons.nal.usda.gov/articles/dataset/Data_from_Late-season_corn_stalk_nitrate_measurements_across_the_US_Midwest_from_2006_to_2018/24668283",
        "download_url": "https://ndownloader.figshare.com/files/44532422",
        "title": "Late-season corn stalk nitrate measurements across the US Midwest from 2006 to 2018",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Laurent et al., USDA Ag Data Commons, DOI 10.15482/USDA.ADC/1527976",
        "columns": ["Field_ID", "Sample_number", "Year", "Previous_crop", "N_fertilizer_form", "Total_N_rate_kgha", "Stalk_nitrate_CSNT", "County_centroid_latitude", "County_centroid_longitude"],
        "dependency_group": "Midwest survey; farm independence is not established",
    },
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_rows(path: Path, expected_sha: str) -> list[tuple[int, dict[str, str]]]:
    raw = path.read_bytes()
    if sha256(raw) != expected_sha:
        raise ValueError(f"source checksum mismatch: {path.name}")
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as stream:
        reader = csv.DictReader(stream)
        return [(number, row) for number, row in enumerate(reader, start=2)]


def _fixture_bytes(columns: list[str], rows: list[tuple[int, dict[str, str]]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for _, row in rows:
        writer.writerow({name: row[name] for name in columns})
    return stream.getvalue().encode("utf-8")


def _mapping(group: str, source: dict[str, Any]) -> dict[str, Any]:
    if group == "akron":
        specs = [
            ("field", "identifier", None, "none", "field_season"),
            ("year", "identifier", None, "none", "field_season"),
            ("crop", "context", None, "unique", "field_season"),
            ("easting_UTM13N", "context", "m", "none", "record"),
            ("northing_UTM13N", "context", "m", "none", "record"),
            ("yield_kg_ha", "measurement", "kg/ha", "mean", "record"),
        ]
    else:
        specs = [
            ("Field_ID", "identifier", None, "none", "field_season"),
            ("Sample_number", "identifier", None, "none", "record"),
            ("Year", "identifier", None, "none", "field_season"),
            ("Previous_crop", "context", None, "none", "field_season"),
            ("N_fertilizer_form", "context", None, "none", "field_season"),
            ("Total_N_rate_kgha", "measurement", "kg/ha", "unique", "field_season"),
            ("Stalk_nitrate_CSNT", "measurement", "ppm", "mean", "record"),
            ("County_centroid_latitude", "context", None, "none", "unknown"),
            ("County_centroid_longitude", "context", None, "none", "unknown"),
        ]
    return {
        "filters": {}, "record_key": [] if group == "akron" else ["Sample_number"],
            "columns": [{"column": name, "label": name, "unit": unit, "role": role,
                     "aggregation": aggregation, "evidence_role": "observation", "value_scope": value_scope}
                    for name, role, unit, aggregation, value_scope in specs],
        "source": {"title": source["title"], "url": source["url"],
                   "license": source["license"], "citation": source["attribution"]},
    }


def _case(bundle: dict[str, Any], suffix: str, question: str, query: dict[str, Any],
          expected: dict[str, Any], *, score_layer: str = "query") -> dict[str, Any]:
    return {"id": f"{bundle['id']}-{suffix}", "bundle_id": bundle["id"],
            "source_group": bundle["source_group"], "question": question,
            "query": query, "expected": expected, "score_layer": score_layer,
            "exposure": "exposed_development", "agronomic_review": "not_performed"}


def build_pilot(source_root: Path, output_root: Path) -> dict[str, Any]:
    """Rebuild fixed 24-bundle/96-case development inputs from SHA-pinned raw CSVs."""
    source_root, output_root = Path(source_root), Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("output root must be empty; preserve existing evidence")
    raw = {key: _source_rows(source_root / value["filename"], value["sha256"])
           for key, value in SOURCE_DEFS.items()}
    akron_groups: dict[tuple[str, str], list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for number, row in raw["akron"]:
        akron_groups[(row["field"], row["year"])].append((number, row))
    nitrate_groups: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for number, row in raw["nitrate"]:
        nitrate_groups[row["Field_ID"]].append((number, row))
    # Include the inspected seed first, then select stable distinct units. A
    # bundle is a field-season/sample unit, never an independent farm claim.
    akron_keys = [("S2", "2022")] + [key for key in sorted(akron_groups)
                                     if key != ("S2", "2022") and len(akron_groups[key]) >= 3][:11]
    nitrate_keys = ["GSS2010OHMM015"] + [key for key in sorted(nitrate_groups)
                                         if key != "GSS2010OHMM015" and len(nitrate_groups[key]) == 3][:11]
    if len(akron_keys) != 12 or len(nitrate_keys) != 12:
        raise ValueError("source has too few eligible field units")
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "fixtures").mkdir()
    bundles: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    for group, keys, grouped in (("akron", akron_keys, akron_groups),
                                 ("nitrate", nitrate_keys, nitrate_groups)):
        source = SOURCE_DEFS[group]
        for index, key in enumerate(keys, start=1):
            rows = grouped[key]
            bundle_id = f"{group}-{index:02d}"
            fixture = _fixture_bytes(source["columns"], rows)
            fixture_rel = f"fixtures/{bundle_id}.csv"
            (output_root / fixture_rel).write_bytes(fixture)
            bundle = {
                "id": bundle_id, "source_group": group, "source_unit": list(key) if isinstance(key, tuple) else key,
                "dependency_group": source["dependency_group"], "independent_farm_verified": False,
                "source_filename": source["filename"], "source_sha256": source["sha256"],
                "source_url": source["url"], "download_url": source["download_url"],
                "license": source["license"], "license_url": source["license_url"],
                "attribution": source["attribution"],
                "derivation": "Exact source cell strings projected to listed columns and selected by source unit; rows retain source order. CSV bytes reserialized as UTF-8 with LF endings; no cell values synthesized or normalized.",
                "source_csv_records_with_header_1": [number for number, _ in rows],
                "source_row_lineage": [
                    {"fixture_csv_record_with_header_1": position,
                     "source_csv_record_with_header_1": number}
                    for position, (number, _) in enumerate(rows, start=2)
                ],
                "fixture_path": fixture_rel, "fixture_sha256": sha256(fixture),
                "fixture_bytes": len(fixture), "row_count": len(rows),
                "mapping": _mapping(group, source),
                "geometry_status": "no reviewed polygon; UTM sample points are not a field boundary" if group == "akron" else "no reviewed polygon; county centroid is not a field boundary",
            }
            bundle["mapping"]["filters"] = ({"field": key[0], "year": key[1]}
                                             if group == "akron" else {"Field_ID": key})
            bundles.append(bundle)
            cases.append(_case(bundle, "count", "How many records in my uploaded data?",
                               {"operation": "count"}, {"kind": "value", "value": len(rows)}))
            if group == "akron":
                values = [float(row["yield_kg_ha"]) for _, row in rows]
                cases.append(_case(bundle, "yield-mean", "What is the mean yield_kg_ha in my uploaded data?",
                                   {"operation": "mean", "column": "yield_kg_ha"},
                                   {"kind": "number", "value": sum(values) / len(values), "tolerance": 1e-8,
                                    "numeric_count": len(values)}))
                crops = sorted({row["crop"] for _, row in rows if row["crop"].strip()})
                cases.append(_case(bundle, "crop-unique", "List unique crop in my uploaded data",
                                   {"operation": "unique", "column": "crop"}, {"kind": "value", "value": crops}))
                cases.append(_case(bundle, "area-yield-state", "What is the area-weighted field yield in my uploaded data?",
                                   {"operation": "mean", "column": "area_weighted_field_yield_kg_ha"},
                                   {"kind": "missing_column", "column": "area_weighted_field_yield_kg_ha"},
                                   score_layer="query_only"))
            else:
                values = [float(row["Stalk_nitrate_CSNT"]) for _, row in rows
                          if row["Stalk_nitrate_CSNT"].strip() and row["Stalk_nitrate_CSNT"] != "NA"]
                cases.append(_case(bundle, "nitrate-mean", "What is the mean Stalk_nitrate_CSNT in my uploaded data?",
                                   {"operation": "mean", "column": "Stalk_nitrate_CSNT"},
                                   {"kind": "number", "value": sum(values) / len(values) if values else None,
                                    "tolerance": 1e-8, "numeric_count": len(values)}))
                rates = sorted({row["Total_N_rate_kgha"] for _, row in rows if row["Total_N_rate_kgha"].strip()})
                cases.append(_case(bundle, "rate-unique", "List unique Total_N_rate_kgha in my uploaded data",
                                   {"operation": "unique", "column": "Total_N_rate_kgha"},
                                   {"kind": "value", "value": rates}))
                cases.append(_case(bundle, "yield-state", "What is the measured yield in my uploaded data?",
                                   {"operation": "mean", "column": "yield_kg_ha"},
                                   {"kind": "missing_column", "column": "yield_kg_ha"}, score_layer="query_only"))
    gold_bytes = b"".join(canonical_bytes(case) + b"\n" for case in cases)
    (output_root / "gold_cases.jsonl").write_bytes(gold_bytes)
    manifest = {
        "schema_version": SCHEMA, "status": "exposed_development_not_agronomic_validation",
        "bundle_count": len(bundles), "case_count": len(cases),
        "source_group_counts": {"akron": 12, "nitrate": 12},
        "source_locator_convention": "1-based logical CSV record including header; quoted newlines do not increment a record number",
        "case_score_scope": "deterministic query receipts; product answers retained separately, no agronomic scoring",
        "independence": "Akron bundles share one research site; nitrate IDs may share farms; no independent-farm count is claimed.",
        "rights": "Source-specific CC0 and CC BY terms remain binding; projection and attribution recorded per bundle.",
        "demo_use": "Explicitly select a fixture CSV for private preview/review/commit. Do not load gold_cases.jsonl into the product.",
        "gold_cases_path": "gold_cases.jsonl", "gold_cases_sha256": sha256(gold_bytes),
        "bundles": bundles,
    }
    (output_root / "manifest.json").write_bytes(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True).encode() + b"\n")
    return manifest


def load_pilot(pilot_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pilot_root = Path(pilot_root)
    manifest = json.loads((pilot_root / "manifest.json").read_text())
    if manifest.get("schema_version") != SCHEMA:
        raise ValueError("unexpected pilot schema")
    gold = (pilot_root / manifest["gold_cases_path"]).read_bytes()
    if sha256(gold) != manifest["gold_cases_sha256"]:
        raise ValueError("gold case checksum mismatch")
    cases = [json.loads(line) for line in gold.splitlines() if line]
    if len(cases) != manifest["case_count"]:
        raise ValueError("case count mismatch")
    for bundle in manifest["bundles"]:
        fixture = (pilot_root / bundle["fixture_path"]).read_bytes()
        if sha256(fixture) != bundle["fixture_sha256"] or len(fixture) != bundle["fixture_bytes"]:
            raise ValueError(f"fixture checksum mismatch: {bundle['id']}")
    return manifest, cases


def _judge_query(expected: dict[str, Any], result: dict[str, Any] | None, error: Exception | None) -> str:
    kind = expected["kind"]
    if kind == "missing_column":
        return "pass" if isinstance(error, ValueError) and "mapped query column required" in str(error) else "fail"
    if error or result is None:
        return "fail"
    if kind == "value":
        return "pass" if result.get("value") == expected["value"] else "fail"
    if kind == "number":
        value = result.get("value")
        target = expected["value"]
        number_ok = value is None and target is None or (
            isinstance(value, (int, float)) and isinstance(target, (int, float))
            and abs(value - target) <= expected["tolerance"])
        return "pass" if number_ok and result.get("numeric_count") == expected["numeric_count"] else "fail"
    raise ValueError("unknown expected kind")


def _judge_product_contract(case: dict[str, Any], oracle: dict[str, Any] | None,
                            answer: str, trace: dict[str, Any],
                            source_sha256: str) -> dict[str, Any]:
    """Score only exact registered table-result binding, outside the runtime."""
    if case["score_layer"] != "query":
        return {"status": "unscored_semantic", "reason": "No reviewed product-answer rubric for this state question."}
    if oracle is None:
        return {"status": "fail", "reason": "Reviewed query oracle did not complete."}
    metadata = trace.get("metadata", {})
    invocations = [entry for entry in trace.get("tool_invocations", [])
                   if isinstance(entry, dict) and entry.get("tool_id") == "field_table_query"]
    planned = [entry for entry in invocations if entry.get("status") == "planned"]
    executed = [entry for entry in invocations if entry.get("status") == "success" and entry.get("result_id")]
    if len(planned) != 1 or len(executed) != 1:
        return {"status": "fail", "reason": "Expected exactly one planned and one executed field_table_query."}
    result = executed[0]
    payload = result.get("payload", {})
    receipt = payload.get("query_receipt", {})
    result_id = result["result_id"]
    contract = {
        "generation_path": metadata.get("generation_path") == "deterministic_tool_result",
        "registered_result": result_id in metadata.get("tool_result_ids", []),
        "invocation_link": result.get("invocation_id") == planned[0].get("invocation_id"),
        "question_binding": planned[0].get("question_sha256") == sha256(case["question"].encode()),
        "answer_binding": answer == payload.get("answer"),
        "source_binding": receipt.get("source_sha256") == source_sha256,
        "oracle_value": _judge_query(case["expected"], receipt, None) == "pass",
    }
    for key in ("operation", "column", "value", "unit", "selected_row_count", "numeric_count",
                "missing_count", "invalid_count", "selected_rows_sha256", "mapping_sha256",
                "member_sha256", "evidence_role", "value_scope"):
        contract[f"oracle_{key}"] = receipt.get(key) == oracle.get(key)
    failed = [name for name, passed in contract.items() if not passed]
    return {"status": "fail" if failed else "pass", "failed_checks": failed,
            "result_id": result_id, "invocation_id": result.get("invocation_id"),
            "receipt_sha256": receipt.get("receipt_sha256")}


_SUPPLEMENTAL_CODE_FILES = (
    "scripts/build_field_data_pilot.py", "scripts/run_field_data_benchmark.py",
    "configs/model.yaml", "configs/rag.yaml", "configs/runtime_profiles.json",
)


def _code_hashes() -> dict[str, str]:
    repo = Path(__file__).resolve().parents[2]
    package_files = sorted((repo / "src/agronomy_agent").rglob("*.py"))
    names = [path.relative_to(repo).as_posix() for path in package_files]
    names.extend(_SUPPLEMENTAL_CODE_FILES)
    return {name: sha256((repo / name).read_bytes()) for name in names}


def _environment_receipt() -> dict[str, Any]:
    packages = ("fastapi", "pydantic", "numpy", "openpyxl", "PyYAML", "agno", "mlx")
    versions = {}
    for name in packages:
        try:
            versions[name] = package_metadata.version(name)
        except package_metadata.PackageNotFoundError:
            versions[name] = None
    return {"python": sys.version, "system": platform.system(),
            "machine": platform.machine(), "installed_package_versions": versions}


def run_pilot(pilot_root: Path, output_dir: Path, *, limit: int | None = None,
              product: bool = True) -> dict[str, Any]:
    """Run isolated field imports; retain every attempted case and product trace."""
    manifest, cases = load_pilot(pilot_root)
    code_hashes_start = _code_hashes()
    environment_start = _environment_receipt()
    manifest_sha256 = sha256((Path(pilot_root) / "manifest.json").read_bytes())
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    selected = cases[:limit] if limit is not None else cases
    output_dir = Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("output directory must be empty; preserve earlier runs")
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_by_id = {bundle["id"]: bundle for bundle in manifest["bundles"]}
    result_path = output_dir / "cases.jsonl"
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    task_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    product_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    contract_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    failed_case_count = 0
    with result_path.open("w", encoding="utf-8") as writer:
        for case in selected:
            bundle = bundle_by_id[case["bundle_id"]]
            record: dict[str, Any] = {
                "case_id": case["id"], "bundle_id": bundle["id"],
                "source_group": bundle["source_group"], "source_sha256": bundle["source_sha256"],
                "source_csv_records_with_header_1": bundle["source_csv_records_with_header_1"],
                "fixture_sha256": bundle["fixture_sha256"], "question": case["question"],
                "question_sha256": sha256(case["question"].encode()),
                "query": case["query"], "score_layer": case["score_layer"],
                "task_type": case["id"].removeprefix(bundle["id"] + "-"),
                "raw_layer": {"status": "not_run", "fixture_sha256": bundle["fixture_sha256"]},
                "query_layer": {"status": "not_run"}, "production_layer": {"status": "not_run"},
            }
            try:
                with tempfile.TemporaryDirectory(prefix="field-data-case-") as temp:
                    temp_path = Path(temp)
                    store = TraceStore(temp_path / "state.sqlite3")
                    field = store.create_phase4_field_context(
                        workspace={"id": f"workspace-{case['id']}", "organization_id": "benchmark"},
                        created_by_user_id="benchmark", payload={"display_name": bundle["id"], "region_text": "United States"})
                    fixture = (Path(pilot_root) / bundle["fixture_path"]).read_bytes()
                    if sha256(fixture) != bundle["fixture_sha256"]:
                        record["raw_layer"]["status"] = "failed_checksum"
                        raise ValueError("fixture checksum changed during run")
                    record["raw_layer"]["status"] = "verified"
                    preview = preview_import(store, field, "benchmark", Path(bundle["fixture_path"]).name, fixture)
                    committed = commit_import(store, field, preview["import_id"], bundle["mapping"])["import"]
                    record["raw_layer"].update({"preview_row_count": preview["profile"]["row_count"],
                                                 "field_id": field["id"],
                                                 "import_id": committed["import_id"],
                                                 "mapping_sha256": committed["mapping_sha256"]})
                    query_receipt = None
                    query_error = None
                    try:
                        query_receipt = query_import(store, field["id"], committed["import_id"], case["query"])
                    except Exception as exc:  # retain a failure or expected block per case
                        query_error = exc
                    record["query_layer"] = {
                        "status": _judge_query(case["expected"], query_receipt, query_error),
                        "expected": case["expected"],
                        "receipt": query_receipt, "error_type": type(query_error).__name__ if query_error else None,
                        "error": str(query_error) if query_error else None,
                    }
                    if product:
                        from agronomy_agent.execution_core import AgentExecutionRequest
                        from agronomy_agent.server.services.chat_service import execute_agent_request
                        from agronomy_agent.server.settings import build_settings

                        settings = build_settings(db_path=temp_path / "state.sqlite3",
                                                  artifact_root=temp_path / "artifacts",
                                                  model_config_path="configs/model.yaml",
                                                  default_rag_config="configs/rag.yaml", network_mode="offline")
                        session = store.create_session(case["id"], {}, {})
                        request = AgentExecutionRequest(
                            store=store, settings=settings, session_id=session["session_id"],
                            message=case["question"], mode="agronomic_rag", model_id="mock",
                            rag_config="configs/rag.yaml", max_tokens=128,
                            trace_options={"store_prompt_messages": False, "store_retrieved_text": False},
                            session_context={"field_context": {"field_context_id": field["id"]},
                                             "field_context_id": field["id"],
                                             "field_access_authorized": True,
                                             "field_access_workspace_id": field["workspace_id"]},
                            execution_class="observed_system_execution_nonclaim",
                            document_retrieval_enabled=False, graph_retrieval_enabled=False)
                        try:
                            execution = execute_agent_request(request)
                            trace = execution.turn.get("trace", {})
                            metadata = trace.get("metadata", {})
                            record["production_layer"] = {
                                "status": "observed_unscored", "turn_id": execution.turn_id,
                                "session_id": session["session_id"],
                                "request_sha256": sha256(canonical_bytes({
                                    "message": request.message, "mode": request.mode,
                                    "model_id": request.model_id, "rag_config": request.rag_config,
                                    "field_id": field["id"], "session_id": request.session_id,
                                    "execution_class": request.execution_class,
                                })),
                                "answer": execution.answer, "answer_sha256": sha256(execution.answer.encode()),
                                "stage_receipts": execution.stage_receipts,
                                "fingerprints": execution.fingerprints,
                                "tool_results": metadata.get("tool_results"),
                                "generation_path": metadata.get("generation_path"),
                                "trace": trace,
                                "trace_sha256": sha256(canonical_bytes(trace)),
                                "contract_score": _judge_product_contract(
                                    case, query_receipt, execution.answer, trace, committed["source_sha256"]),
                            }
                        except Exception as exc:
                            record["production_layer"] = {"status": "failed", "error_type": type(exc).__name__,
                                                          "error": str(exc)}
                    store._conn.close()
            except Exception as exc:
                record["case_failure"] = {"error_type": type(exc).__name__, "error": str(exc)}
                if record["query_layer"]["status"] == "not_run":
                    record["query_layer"]["status"] = "failed_before_query"
            counts[bundle["source_group"]][record["query_layer"]["status"]] += 1
            task_counts[bundle["source_group"]][record["task_type"]] += 1
            product_counts[bundle["source_group"]][record["production_layer"]["status"]] += 1
            contract_status = record["production_layer"].get("contract_score", {}).get("status", "not_run")
            contract_counts[bundle["source_group"]][contract_status] += 1
            if (record.get("case_failure") or record["query_layer"]["status"] != "pass"
                    or record["production_layer"]["status"] == "failed" or contract_status == "fail"):
                failed_case_count += 1
            writer.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            writer.flush()
    results = result_path.read_bytes()
    summary = {
        "schema_version": "field_data_pilot_run.v1", "case_count": len(selected),
        "source_group_case_counts": {group: dict(statuses) for group, statuses in sorted(counts.items())},
        "source_group_task_counts": {group: dict(tasks) for group, tasks in sorted(task_counts.items())},
        "source_group_product_counts": {group: dict(statuses) for group, statuses in sorted(product_counts.items())},
        "source_group_product_contract_counts": {group: dict(statuses) for group, statuses in sorted(contract_counts.items())},
        "failed_case_count": failed_case_count,
        "source_group_bundle_counts": manifest["source_group_counts"],
        "cases_sha256": sha256(results), "manifest_sha256": manifest_sha256,
        "gold_cases_sha256": manifest["gold_cases_sha256"],
        "code_sha256_start": code_hashes_start, "code_sha256_end": _code_hashes(),
        "environment_start": environment_start, "environment_end": _environment_receipt(),
        "product_mode": "offline_mock_generator" if product else "not_run",
        "claim": "Exposed development table/query and exact deterministic product binding only; semantic cases unscored; no independent farm or agronomic competence claim.",
    }
    summary["runtime_code_stable"] = (summary["code_sha256_start"] == summary["code_sha256_end"]
                                      and summary["environment_start"] == summary["environment_end"])
    (output_dir / "summary.json").write_bytes(json.dumps(summary, indent=2, sort_keys=True).encode() + b"\n")
    return summary
