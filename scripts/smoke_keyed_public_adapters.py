#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.parse
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agronomy_agent import local_tools
from agronomy_agent.paths import repo_path


SMOKE_SCHEMA_VERSION = "open_agronomy_agent.keyed_public_adapter_smoke.v1"
DEFAULT_OUTPUT = "outputs/tool_smoke/keyed_public_adapters_latest.json"
FIXTURE_NASS_KEY = "fixture-nass-key"
FIXTURE_OPENET_KEY = "fixture-openet-key"

SMOKE_CASES: tuple[dict[str, str], ...] = (
    {
        "case_id": "nass_quickstats_missing_key",
        "provider": "USDA NASS Quick Stats",
        "mode": "missing_key",
    },
    {
        "case_id": "nass_quickstats_fixture_success",
        "provider": "USDA NASS Quick Stats",
        "mode": "fixture_success",
    },
    {
        "case_id": "openet_missing_key",
        "provider": "OpenET",
        "mode": "missing_key",
    },
    {
        "case_id": "openet_fixture_success",
        "provider": "OpenET",
        "mode": "fixture_success",
    },
)


def run_smoke(
    *,
    live: bool = False,
    output: str | Path = DEFAULT_OUTPUT,
    timeout: int = 12,
    cache_dir: str | Path = "outputs/tool_cache/keyed_public_smoke",
) -> dict[str, Any]:
    output_path = repo_path(str(output))
    opener = None if live else _offline_urlopen
    with _patched_urlopen(opener):
        cases = [_run_case(case, live=live, timeout=timeout, cache_dir=str(cache_dir)) for case in SMOKE_CASES]
    failures = [failure for case in cases for failure in case["failures"]]
    report = {
        "schema_version": SMOKE_SCHEMA_VERSION,
        "mode": "live" if live else "offline_fixture",
        "providers": ["USDA NASS Quick Stats", "OpenET"],
        "case_count": len(cases),
        "passed": not failures,
        "failures": failures,
        "cases": cases,
        "boundary": (
            "This smoke check verifies key-gated adapter credential handling, normalization, and source-card readiness. "
            "It does not verify field-specific yield prediction, irrigation scheduling, water-right accounting, or "
            "provider coverage for every crop and region."
        ),
    }
    _assert_no_fixture_secrets(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _run_case(case: dict[str, str], *, live: bool, timeout: int, cache_dir: str) -> dict[str, Any]:
    case_cache_dir = str(repo_path(cache_dir) / case["case_id"])
    env_context = _env_for_case(case, live=live)
    with env_context:
        payload = _call_case(case, timeout=timeout, cache_dir=case_cache_dir)
    failures = _case_failures(case, payload, live=live)
    return {
        "case_id": case["case_id"],
        "provider": case["provider"],
        "credential_state": _credential_state(case, live=live),
        "tool": payload.get("tool"),
        "status": payload.get("status"),
        "record_count": payload.get("record_count"),
        "source": payload.get("source"),
        "required_env_vars": payload.get("required_env_vars") or [],
        "summary": _case_summary(payload),
        "boundary": payload.get("boundary"),
        "result": "pass" if not failures else "fail",
        "failures": failures,
    }


def _call_case(case: dict[str, str], *, timeout: int, cache_dir: str) -> dict[str, Any]:
    if case["provider"] == "USDA NASS Quick Stats":
        return local_tools.nass_quickstats_crop_stats(
            "corn",
            "IA",
            statistic_categories=local_tools.DEFAULT_QUICKSTATS_CATEGORIES,
            year_ge=2022,
            cache_dir=cache_dir,
            snapshot_path=str(repo_path(cache_dir) / "intentionally_absent_snapshot.jsonl"),
            timeout=timeout,
        )
    return local_tools.openet_point_timeseries(
        36.73,
        -119.79,
        "2024-04-01",
        "2024-05-31",
        cache_dir=cache_dir,
        timeout=timeout,
    )


def _case_failures(case: dict[str, str], payload: dict[str, Any], *, live: bool) -> list[str]:
    failures: list[str] = []
    case_id = case["case_id"]
    provider = case["provider"]
    if provider == "USDA NASS Quick Stats":
        failures.extend(_quickstats_failures(case, payload, live=live))
    if provider == "OpenET":
        failures.extend(_openet_failures(case, payload, live=live))
    serialized = json.dumps(payload)
    for secret in (FIXTURE_NASS_KEY, FIXTURE_OPENET_KEY):
        if secret in serialized:
            failures.append(f"{case_id}: fixture credential leaked into payload")
    return failures


def _quickstats_failures(case: dict[str, str], payload: dict[str, Any], *, live: bool) -> list[str]:
    failures: list[str] = []
    case_id = case["case_id"]
    if payload.get("tool") != "nass_quickstats_crop_stats":
        failures.append(f"{case_id}: wrong tool name")
    if payload.get("source") != local_tools.NASS_QUICKSTATS_API_URL:
        failures.append(f"{case_id}: wrong source")
    if case["mode"] == "missing_key":
        if payload.get("status") != "not_configured":
            failures.append(f"{case_id}: expected not_configured without an API key")
        if "AGRONOMY_AGENT_NASS_QUICKSTATS_API_KEY" not in (payload.get("required_env_vars") or []):
            failures.append(f"{case_id}: missing required env var names")
        if int(payload.get("record_count") or 0) != 0:
            failures.append(f"{case_id}: missing-key path should not return records")
        if "field-specific yield prediction" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing regional-statistics boundary")
        return failures

    if payload.get("status") == "not_configured" and live:
        failures.append(f"{case_id}: live Quick Stats credential is not configured")
        return failures
    if payload.get("status") != "available":
        failures.append(f"{case_id}: expected available fixture rows")
    if int(payload.get("record_count") or 0) < 3:
        failures.append(f"{case_id}: expected yield, acreage, and production rows")
    latest = payload.get("latest_by_statistic") or {}
    for statistic in local_tools.DEFAULT_QUICKSTATS_CATEGORIES:
        if statistic not in latest:
            failures.append(f"{case_id}: missing latest {statistic} row")
    if (latest.get("YIELD") or {}).get("value_numeric") != 201.0 and not live:
        failures.append(f"{case_id}: fixture yield value was not normalized")
    if "field-specific yield guarantee" not in str(payload.get("boundary") or ""):
        failures.append(f"{case_id}: missing non-field-specific boundary")
    return failures


def _openet_failures(case: dict[str, str], payload: dict[str, Any], *, live: bool) -> list[str]:
    failures: list[str] = []
    case_id = case["case_id"]
    if payload.get("tool") != "openet_point_timeseries":
        failures.append(f"{case_id}: wrong tool name")
    if payload.get("source") != local_tools.OPENET_RASTER_TIMESERIES_POINT_URL:
        failures.append(f"{case_id}: wrong source")
    if case["mode"] == "missing_key":
        if payload.get("status") != "not_configured":
            failures.append(f"{case_id}: expected not_configured without an API key")
        if "AGRONOMY_AGENT_OPENET_API_KEY" not in (payload.get("required_env_vars") or []):
            failures.append(f"{case_id}: missing required env var names")
        if int(payload.get("record_count") or 0) != 0:
            failures.append(f"{case_id}: missing-key path should not return records")
        if "irrigation prescription" not in str(payload.get("boundary") or ""):
            failures.append(f"{case_id}: missing irrigation-boundary language")
        return failures

    if payload.get("status") == "not_configured" and live:
        failures.append(f"{case_id}: live OpenET credential is not configured")
        return failures
    if payload.get("status") != "available":
        failures.append(f"{case_id}: expected available fixture rows")
    if int(payload.get("record_count") or 0) < 2:
        failures.append(f"{case_id}: expected at least two ET periods")
    summary = payload.get("timeseries_summary") or {}
    if summary.get("sum") != 259.0 and not live:
        failures.append(f"{case_id}: fixture ET sum was not normalized")
    if "irrigation prescription" not in str(payload.get("boundary") or ""):
        failures.append(f"{case_id}: missing irrigation-boundary language")
    return failures


def _case_summary(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("tool") == "nass_quickstats_crop_stats":
        return {
            "crop": payload.get("crop"),
            "state_alpha": payload.get("state_alpha"),
            "year_ge": payload.get("year_ge"),
            "statistic_categories": payload.get("statistic_categories") or [],
            "latest_by_statistic": payload.get("latest_by_statistic") or {},
        }
    if payload.get("tool") == "openet_point_timeseries":
        return {
            "start": payload.get("start"),
            "end": payload.get("end"),
            "interval": payload.get("interval"),
            "model": payload.get("model"),
            "variable": payload.get("variable"),
            "units": payload.get("units"),
            "timeseries_summary": payload.get("timeseries_summary") or {},
        }
    return {}


def _credential_state(case: dict[str, str], *, live: bool) -> str:
    if case["mode"] == "missing_key":
        return "cleared_for_missing_key_check"
    return "live_environment" if live else "offline_fixture_key"


@contextmanager
def _env_for_case(case: dict[str, str], *, live: bool):
    if case["provider"] == "USDA NASS Quick Stats":
        env_vars = local_tools.NASS_QUICKSTATS_ENV_VARS
        updates = {} if live or case["mode"] == "missing_key" else {env_vars[0]: FIXTURE_NASS_KEY}
    else:
        env_vars = local_tools.OPENET_ENV_VARS
        updates = {} if live or case["mode"] == "missing_key" else {env_vars[0]: FIXTURE_OPENET_KEY}
    if live and case["mode"] != "missing_key":
        yield
        return
    with _patched_env(clear=env_vars, updates=updates):
        yield


@contextmanager
def _patched_env(*, clear: Iterable[str], updates: dict[str, str]):
    original = {key: os.environ.get(key) for key in clear}
    for key in clear:
        os.environ.pop(key, None)
    os.environ.update(updates)
    try:
        yield
    finally:
        for key in updates:
            os.environ.pop(key, None)
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _patched_urlopen(opener: Callable[..., Any] | None):
    if opener is None:
        yield
        return
    original = local_tools.urllib.request.urlopen
    local_tools.urllib.request.urlopen = opener
    try:
        yield
    finally:
        local_tools.urllib.request.urlopen = original


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _offline_urlopen(request: Any, timeout: int = 12) -> _FakeResponse:  # noqa: ARG001
    url = str(getattr(request, "full_url", request))
    if url.startswith(local_tools.NASS_QUICKSTATS_API_URL):
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        statistic = (query.get("statisticcat_desc") or ["YIELD"])[0]
        return _FakeResponse(_quickstats_fixture(statistic))
    if url == local_tools.OPENET_RASTER_TIMESERIES_POINT_URL:
        return _FakeResponse(
            {
                "data": [
                    {"date": "2024-04-01", "et": 112.4, "units": "mm"},
                    {"date": "2024-05-01", "et": 146.6, "units": "mm"},
                ]
            }
        )
    raise RuntimeError(f"unexpected offline smoke URL: {url}")


def _quickstats_fixture(statistic: str) -> dict[str, list[dict[str, str]]]:
    statistic = statistic.upper()
    values = {
        "YIELD": {
            "short_desc": "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE",
            "unit_desc": "BU / ACRE",
            "Value": "201.0",
        },
        "AREA HARVESTED": {
            "short_desc": "CORN, GRAIN - ACRES HARVESTED",
            "unit_desc": "ACRES",
            "Value": "12,300,000",
        },
        "PRODUCTION": {
            "short_desc": "CORN, GRAIN - PRODUCTION, MEASURED IN BU",
            "unit_desc": "BU",
            "Value": "2,472,300,000",
        },
    }
    row = values.get(statistic, values["YIELD"])
    return {
        "data": [
            {
                "year": "2024",
                "statisticcat_desc": statistic,
                "agg_level_desc": "STATE",
                "state_alpha": "IA",
                "source_desc": "SURVEY",
                "reference_period_desc": "YEAR",
                **row,
            }
        ]
    }


def _assert_no_fixture_secrets(report: dict[str, Any]) -> None:
    serialized = json.dumps(report)
    leaked = [secret for secret in (FIXTURE_NASS_KEY, FIXTURE_OPENET_KEY) if secret in serialized]
    if leaked:
        raise AssertionError("fixture credential leaked into smoke report")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test key-gated public adapters and missing-credential states.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--cache-dir", default="outputs/tool_cache/keyed_public_smoke")
    parser.add_argument("--live", action="store_true", help="Call live provider APIs with configured credentials.")
    args = parser.parse_args()
    report = run_smoke(live=args.live, output=args.output, timeout=args.timeout, cache_dir=args.cache_dir)
    print(json.dumps({"output": str(repo_path(args.output)), "passed": report["passed"], "failures": report["failures"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
