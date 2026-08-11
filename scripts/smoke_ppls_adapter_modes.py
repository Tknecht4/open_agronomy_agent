#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.parse
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agronomy_agent import local_tools
from agronomy_agent.paths import repo_path


SMOKE_SCHEMA_VERSION = "open_agronomy_agent.ppls_adapter_smoke.v1"
DEFAULT_OUTPUT = "outputs/tool_smoke/ppls_adapter_modes_latest.json"

SMOKE_CASES: tuple[dict[str, str], ...] = (
    {"case_id": "ingredient_candidate_disambiguation", "kind": "ingredient_name", "value": "glyphosate"},
    {"case_id": "product_name_candidate", "kind": "product_name", "value": "Example Herbicide"},
    {"case_id": "exact_registration_number", "kind": "epa_reg_no", "value": "123-45"},
    {"case_id": "no_records", "kind": "product_name", "value": "zz-no-record-demo"},
)


def run_smoke(
    *,
    live: bool = False,
    output: str | Path = DEFAULT_OUTPUT,
    timeout: int = 12,
    cache_dir: str | Path = "outputs/tool_cache/ppls_smoke",
) -> dict[str, Any]:
    output_path = repo_path(str(output))
    opener = None if live else _offline_urlopen
    with _patched_urlopen(opener):
        cases = [_run_case(case, timeout=timeout, cache_dir=str(cache_dir)) for case in SMOKE_CASES]
    failures = [failure for case in cases for failure in case["failures"]]
    report = {
        "schema_version": SMOKE_SCHEMA_VERSION,
        "mode": "live" if live else "offline_fixture",
        "provider": "EPA PPLS",
        "case_count": len(cases),
        "passed": not failures,
        "failures": failures,
        "cases": cases,
        "boundary": (
            "This smoke check verifies PPLS adapter routing, normalization, and source-card readiness. "
            "It does not verify legal label interpretation, local product approval, or rate advice."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def _run_case(case: dict[str, str], *, timeout: int, cache_dir: str) -> dict[str, Any]:
    kind = case["kind"]
    value = case["value"]
    payload = local_tools.epa_ppls_product_search(**{kind: value}, cache_dir=cache_dir, timeout=timeout)
    top_candidate = payload.get("top_candidate") or {}
    label_link_count = len(top_candidate.get("label_pdf_urls") or [])
    failures = _case_failures(case, payload)
    return {
        "case_id": case["case_id"],
        "search_kind": payload.get("search_kind"),
        "search_value": payload.get("search_value"),
        "result_count": payload.get("result_count"),
        "current_product_count": payload.get("current_product_count"),
        "inactive_product_count": payload.get("inactive_product_count"),
        "unknown_status_product_count": payload.get("unknown_status_product_count"),
        "needs_product_disambiguation": payload.get("needs_product_disambiguation"),
        "top_candidate": top_candidate,
        "label_link_count": label_link_count,
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "source": payload.get("source"),
        "boundary": payload.get("boundary"),
    }


def _case_failures(case: dict[str, str], payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if payload.get("tool") != "epa_ppls_product_search":
        failures.append(f"{case['case_id']}: wrong tool name")
    if payload.get("search_kind") != case["kind"]:
        failures.append(f"{case['case_id']}: wrong search kind {payload.get('search_kind')}")
    if str(payload.get("search_value")) != case["value"]:
        failures.append(f"{case['case_id']}: wrong search value {payload.get('search_value')}")
    if case["case_id"] == "ingredient_candidate_disambiguation":
        if int(payload.get("current_product_count") or 0) < 1:
            failures.append("ingredient search should expose at least one current-status candidate")
        if int(payload.get("inactive_product_count") or 0) < 1:
            failures.append("ingredient search should expose inactive/cancelled candidates distinctly")
        if payload.get("needs_product_disambiguation") is not True:
            failures.append("ingredient search should require exact product/reg-number disambiguation")
    if case["case_id"] == "exact_registration_number":
        if payload.get("needs_product_disambiguation") is not False:
            failures.append("exact registration-number fixture should not require candidate disambiguation")
        if (payload.get("top_candidate") or {}).get("epa_reg_no") != case["value"]:
            failures.append("exact registration-number fixture should preserve top candidate reg number")
    if case["case_id"] == "no_records":
        if int(payload.get("result_count") or 0) != 0:
            failures.append("no-record fixture should return zero results")
        if payload.get("top_candidate"):
            failures.append("no-record fixture should not expose a top candidate")
    if "legal label interpretation" not in str(payload.get("boundary") or ""):
        failures.append(f"{case['case_id']}: missing label-interpretation boundary")
    return failures


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
    decoded = urllib.parse.unquote(url)
    if "zz-no-record-demo" in decoded:
        return _FakeResponse({"items": []})
    if "searchWithRegNo" in decoded:
        return _FakeResponse({"items": [_active_product("123-45", "Example Herbicide")]})
    if "searchWithProductName" in decoded:
        return _FakeResponse({"items": [_active_product("123-45", "Example Herbicide")]})
    return _FakeResponse(
        {
            "items": [
                _cancelled_product("999-00", "Old Example Herbicide"),
                _active_product("123-45", "Example Herbicide"),
            ]
        }
    )


def _active_product(reg_no: str, name: str) -> dict[str, str]:
    return {
        "eparegnumber": reg_no,
        "productname": name,
        "registrationstatus": "Active",
        "productstatusdate": "July 1, 2026",
        "ingredientname": "Glyphosate",
        "PDFFILES": f"https://example.test/labels/{reg_no}.pdf",
    }


def _cancelled_product(reg_no: str, name: str) -> dict[str, str]:
    return {
        "eparegnumber": reg_no,
        "productname": name,
        "registrationstatus": "Cancelled",
        "productstatusdate": "January 1, 2020",
        "ingredientname": "Glyphosate",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test EPA PPLS adapter search modes and normalization.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--cache-dir", default="outputs/tool_cache/ppls_smoke")
    parser.add_argument("--live", action="store_true", help="Call the live EPA PPLS API instead of offline fixtures.")
    args = parser.parse_args()
    report = run_smoke(live=args.live, output=args.output, timeout=args.timeout, cache_dir=args.cache_dir)
    print(json.dumps({"output": str(repo_path(args.output)), "passed": report["passed"], "failures": report["failures"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
