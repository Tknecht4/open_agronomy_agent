#!/usr/bin/env python3
"""Build a price-versioned token and API-equivalent cost ledger for a benchmark."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRICING_INDEX = ROOT / "configs/openai_pricing/gpt-5.6-luna_standard_20260808.json"


DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS pricing_index (
    pricing_index_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    service_tier TEXT NOT NULL,
    currency TEXT NOT NULL,
    unit_tokens INTEGER NOT NULL,
    uncached_input_rate REAL NOT NULL,
    cached_input_rate REAL NOT NULL,
    cache_write_input_rate REAL NOT NULL,
    output_rate REAL NOT NULL,
    effective_observed_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    billing_scope TEXT NOT NULL,
    pricing_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_entry (
    call_id TEXT PRIMARY KEY,
    pricing_index_id TEXT NOT NULL REFERENCES pricing_index(pricing_index_id),
    usage_role TEXT NOT NULL CHECK(usage_role IN ('candidate', 'judge')),
    artifact_path TEXT NOT NULL,
    model_key TEXT,
    mode TEXT,
    trial_id TEXT,
    run_execution_id TEXT,
    observation_id TEXT,
    eval_id TEXT,
    judge_role TEXT,
    requested_model TEXT NOT NULL,
    selected_model TEXT,
    requested_reasoning_effort TEXT,
    thread_id TEXT,
    turn_id TEXT,
    input_tokens INTEGER NOT NULL,
    uncached_input_tokens INTEGER NOT NULL,
    cached_input_tokens INTEGER NOT NULL,
    cache_write_input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    reasoning_output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    uncached_input_cost_usd REAL NOT NULL,
    cached_input_cost_usd REAL NOT NULL,
    cache_write_input_cost_usd REAL NOT NULL,
    output_cost_usd REAL NOT NULL,
    api_equivalent_cost_usd REAL NOT NULL,
    actual_billed_cost_usd REAL,
    elapsed_ms REAL,
    reroute_count INTEGER NOT NULL,
    receipt_sha256 TEXT NOT NULL,
    receipt_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_model_mode ON usage_entry(model_key, mode, usage_role);
CREATE INDEX IF NOT EXISTS idx_usage_trial ON usage_entry(model_key, trial_id, mode, usage_role);
CREATE INDEX IF NOT EXISTS idx_usage_judge_role ON usage_entry(judge_role, usage_role);
"""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            yield payload


def _source_run_identity(path: Path, experiment_dir: Path) -> dict[str, Any]:
    for parent in path.parents:
        if parent == experiment_dir.parent:
            break
        manifest_path = parent / "run_manifest.json"
        if manifest_path.is_file():
            return _load_object(manifest_path)
        if parent == experiment_dir:
            break
    return {}


def _usage(receipt: dict[str, Any]) -> dict[str, int]:
    token_usage = receipt.get("token_usage") or {}
    last = token_usage.get("last") or {}
    values = {
        "input_tokens": int(last.get("inputTokens") or 0),
        "cached_input_tokens": int(last.get("cachedInputTokens") or 0),
        "cache_write_input_tokens": int(last.get("cacheWriteInputTokens") or 0),
        "output_tokens": int(last.get("outputTokens") or 0),
        "reasoning_output_tokens": int(last.get("reasoningOutputTokens") or 0),
        "total_tokens": int(last.get("totalTokens") or 0),
    }
    values["uncached_input_tokens"] = max(
        0,
        values["input_tokens"]
        - values["cached_input_tokens"]
        - values["cache_write_input_tokens"],
    )
    return values


def _costs(usage: dict[str, int], pricing: dict[str, Any]) -> dict[str, float]:
    rates = pricing["rates"]
    unit = float(pricing["unit_tokens"])
    components = {
        "uncached_input_cost_usd": usage["uncached_input_tokens"] * float(rates["uncached_input"]) / unit,
        "cached_input_cost_usd": usage["cached_input_tokens"] * float(rates["cached_input"]) / unit,
        "cache_write_input_cost_usd": usage["cache_write_input_tokens"]
        * float(rates["cache_write_input"])
        / unit,
        "output_cost_usd": usage["output_tokens"] * float(rates["output"]) / unit,
    }
    components["api_equivalent_cost_usd"] = sum(components.values())
    return components


def _candidate_entries(experiment_dir: Path) -> Iterable[dict[str, Any]]:
    for outputs_path in sorted(experiment_dir.glob("runs/*/*/*/outputs.jsonl")):
        parts = outputs_path.relative_to(experiment_dir).parts
        model_key = parts[1]
        mode = parts[2]
        for row in _read_jsonl(outputs_path):
            stats = (row.get("metadata") or {}).get("generation_stats") or {}
            receipt = stats.get("app_server_receipt")
            if isinstance(receipt, dict):
                yield {
                    "usage_role": "candidate",
                    "artifact_path": _display_path(outputs_path),
                    "model_key": model_key,
                    "mode": mode,
                    "trial_id": row.get("trial_id"),
                    "run_execution_id": row.get("run_execution_id"),
                    "observation_id": row.get("observation_id"),
                    "eval_id": str(row.get("eval_id") or "") or None,
                    "judge_role": None,
                    "receipt": receipt,
                }
            verification_stats = (row.get("metadata") or {}).get("verification_generation_stats") or {}
            verification_receipt = verification_stats.get("app_server_receipt")
            if isinstance(verification_receipt, dict):
                yield {
                    "usage_role": "judge",
                    "artifact_path": _display_path(outputs_path),
                    "model_key": model_key,
                    "mode": mode,
                    "trial_id": row.get("trial_id"),
                    "run_execution_id": row.get("run_execution_id"),
                    "observation_id": row.get("observation_id"),
                    "eval_id": str(row.get("eval_id") or "") or None,
                    "judge_role": "answer_verifier",
                    "receipt": verification_receipt,
                }


def _judge_entries(experiment_dir: Path) -> Iterable[dict[str, Any]]:
    for receipt_path in sorted(experiment_dir.glob("runs/*/*/*/semantic_judge*/*/*.receipt.json")):
        parts = receipt_path.relative_to(experiment_dir).parts
        model_key = parts[1]
        mode = parts[2]
        judge_dir = parts[4]
        attempt_class = parts[5]
        summary_path = receipt_path.parents[1] / "summary.json"
        summary = _load_object(summary_path) if summary_path.is_file() else {}
        run_identity = _source_run_identity(receipt_path, experiment_dir)
        replication = run_identity.get("replication_contract") or {}
        judge_role = str(summary.get("judge_role") or judge_dir.removeprefix("semantic_judge_"))
        yield {
            "usage_role": "judge",
            "artifact_path": _display_path(receipt_path),
            "model_key": model_key,
            "mode": mode,
            "trial_id": replication.get("trial_id"),
            "run_execution_id": run_identity.get("run_execution_id"),
            "observation_id": None,
            "eval_id": None,
            "judge_role": f"{judge_role}::failed_attempt" if attempt_class == "failed_attempts" else judge_role,
            "receipt": _load_object(receipt_path),
        }


def build_ledger(
    experiment_dir: Path,
    database_path: Path,
    manifest_path: Path,
    pricing_index_path: Path = DEFAULT_PRICING_INDEX,
) -> dict[str, Any]:
    experiment_dir = experiment_dir.resolve()
    pricing_index_path = pricing_index_path.resolve()
    pricing = _load_object(pricing_index_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    existing_usage_columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(usage_entry)")
    }
    for column in ("trial_id", "run_execution_id", "observation_id"):
        if existing_usage_columns and column not in existing_usage_columns:
            connection.execute(f"ALTER TABLE usage_entry ADD COLUMN {column} TEXT")
    connection.executescript(DDL)
    rates = pricing["rates"]
    connection.execute(
        """
        INSERT OR REPLACE INTO pricing_index(
            pricing_index_id, provider, model, service_tier, currency, unit_tokens,
            uncached_input_rate, cached_input_rate, cache_write_input_rate, output_rate,
            effective_observed_at, source_url, source_sha256, billing_scope, pricing_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pricing["pricing_index_id"],
            pricing["provider"],
            pricing["model"],
            pricing["service_tier"],
            pricing["currency"],
            int(pricing["unit_tokens"]),
            float(rates["uncached_input"]),
            float(rates["cached_input"]),
            float(rates["cache_write_input"]),
            float(rates["output"]),
            pricing["effective_observed_at"],
            pricing["source_url"],
            _sha256_path(pricing_index_path),
            pricing["billing_scope"],
            _canonical(pricing),
        ),
    )
    entries = list(_candidate_entries(experiment_dir)) + list(_judge_entries(experiment_dir))
    for entry in entries:
        receipt = entry["receipt"]
        requested_model = str(receipt.get("requested_model") or "")
        if requested_model != pricing["model"]:
            raise ValueError(
                f"receipt model {requested_model!r} has no matching pricing index {pricing['model']!r}: "
                f"{entry['artifact_path']}"
            )
        usage = _usage(receipt)
        costs = _costs(usage, pricing)
        source_call_id = str(
            receipt.get("turn_id") or _sha256_bytes(_canonical(receipt).encode("utf-8"))
        )
        # A cached/replayed provider receipt can legitimately appear in more
        # than one trial artifact.  Keep each use distinct without losing the
        # provider's original turn_id in its dedicated column.
        call_id = _sha256_bytes(
            _canonical(
                {
                    "source_call_id": source_call_id,
                    "artifact_path": entry["artifact_path"],
                    "usage_role": entry["usage_role"],
                    "observation_id": entry.get("observation_id"),
                    "judge_role": entry.get("judge_role"),
                }
            ).encode("utf-8")
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO usage_entry(
                call_id, pricing_index_id, usage_role, artifact_path, model_key, mode,
                trial_id, run_execution_id, observation_id, eval_id, judge_role,
                requested_model, selected_model,
                requested_reasoning_effort, thread_id, turn_id, input_tokens,
                uncached_input_tokens, cached_input_tokens, cache_write_input_tokens,
                output_tokens, reasoning_output_tokens, total_tokens,
                uncached_input_cost_usd, cached_input_cost_usd,
                cache_write_input_cost_usd, output_cost_usd, api_equivalent_cost_usd,
                actual_billed_cost_usd, elapsed_ms, reroute_count, receipt_sha256, receipt_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                call_id,
                pricing["pricing_index_id"],
                entry["usage_role"],
                entry["artifact_path"],
                entry["model_key"],
                entry["mode"],
                entry.get("trial_id"),
                entry.get("run_execution_id"),
                entry.get("observation_id"),
                entry["eval_id"],
                entry["judge_role"],
                requested_model,
                receipt.get("selected_model"),
                receipt.get("requested_turn_reasoning_effort"),
                receipt.get("thread_id"),
                receipt.get("turn_id"),
                usage["input_tokens"],
                usage["uncached_input_tokens"],
                usage["cached_input_tokens"],
                usage["cache_write_input_tokens"],
                usage["output_tokens"],
                usage["reasoning_output_tokens"],
                usage["total_tokens"],
                costs["uncached_input_cost_usd"],
                costs["cached_input_cost_usd"],
                costs["cache_write_input_cost_usd"],
                costs["output_cost_usd"],
                costs["api_equivalent_cost_usd"],
                None,
                receipt.get("elapsed_ms"),
                len(receipt.get("reroutes") or []),
                _sha256_bytes(_canonical(receipt).encode("utf-8")),
                _canonical(receipt),
            ),
        )
    connection.commit()
    connection.row_factory = sqlite3.Row
    totals = dict(
        connection.execute(
            """
            SELECT
                COUNT(*) AS calls,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                COALESCE(SUM(cache_write_input_tokens), 0) AS cache_write_input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(reasoning_output_tokens), 0) AS reasoning_output_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(api_equivalent_cost_usd), 0) AS api_equivalent_cost_usd
            FROM usage_entry
            """
        ).fetchone()
    )
    grouped: dict[str, Any] = defaultdict(dict)
    for row in connection.execute(
        """
        SELECT model_key, trial_id, mode, usage_role, judge_role, COUNT(*) AS calls,
               SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
               SUM(total_tokens) AS total_tokens,
               SUM(api_equivalent_cost_usd) AS api_equivalent_cost_usd
        FROM usage_entry
        GROUP BY model_key, trial_id, mode, usage_role, judge_role
        ORDER BY model_key, trial_id, mode, usage_role, judge_role
        """
    ):
        key = "::".join(str(value or "none") for value in row[:5])
        grouped[key] = dict(row)
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    connection.close()
    manifest = {
        "schema_version": "open_agronomy_agent.benchmark_cost_ledger.v2",
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "experiment_dir": str(experiment_dir),
        "pricing_index": pricing,
        "pricing_index_path": str(pricing_index_path),
        "pricing_index_sha256": _sha256_path(pricing_index_path),
        "billing_interpretation": (
            "API-equivalent estimate from the official standard token schedule; "
            "actual ChatGPT-authenticated App Server billing is not observed."
        ),
        "totals": totals,
        "groups": dict(grouped),
        "database": str(database_path),
        "database_sha256": _sha256_path(database_path),
        "integrity_check": integrity,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pricing-index", type=Path, default=DEFAULT_PRICING_INDEX)
    args = parser.parse_args()
    experiment = args.experiment_dir.resolve()
    manifest = build_ledger(
        experiment,
        (args.database or experiment / "cost_ledger.sqlite3").resolve(),
        (args.manifest or experiment / "cost_ledger_manifest.json").resolve(),
        args.pricing_index,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["integrity_check"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
