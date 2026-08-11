from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FRONTEND_DIST = ROOT / "frontend/dist"
REPORT_VERSION = "phase6.frontend_bundle_budget.v1"


@dataclass(frozen=True)
class BundleBudget:
    budget_id: str
    label: str
    glob: str
    max_bytes: int
    required: bool = True
    html_reference_required: bool = False


# The July lineage/privacy repair adds field-scoped history, explicit network
# state, and the data-use surface. Field-record transfer and private local
# references have separate lazy capability budgets so their costs cannot
# disappear into the main map/agent ceiling. The Quebec offline terrain
# availability control and Canadian knowledge-coverage contract are likewise
# isolated. The July 26 official-source disclosure adds sanitized, collapsed
# acquisition leads only to the lazy Sources route: the measured route change
# is 1,518 raw JS bytes and leaves the map-first entry chunk unchanged. Its
# explicit route ceiling and the aggregate ceiling increase together so that
# the capability cannot disappear into unrelated bundle growth.
# Privacy/About copy is also lazy because it is not required for the map-first
# cold path; its explicit ceiling does not increase the aggregate JS budget.
# Raw byte ceilings are measured capability baselines; gzip remains reported by
# Vite.
BUNDLE_BUDGETS = (
    BundleBudget("open_agronomy_app_js", "Open Agronomy app JavaScript", "assets/index-*.js", 258_000, html_reference_required=True),
    BundleBudget("benchmarks_route_js", "Benchmarks route JavaScript", "assets/BenchmarksRoute-*.js", 75_000),
    BundleBudget("leaflet_field_map_js", "Leaflet field map JavaScript", "assets/LeafletFieldMap-*.js", 165_000),
    BundleBudget("field_sync_panel_js", "Field record transfer JavaScript", "assets/FieldSyncPanel-*.js", 8_000),
    BundleBudget("private_knowledge_panel_js", "Private local references JavaScript", "assets/PrivateKnowledgePanel-*.js", 2_500),
    BundleBudget("offline_terrain_context_panel_js", "Offline terrain context JavaScript", "assets/OfflineTerrainContextPanel-*.js", 3_000),
    BundleBudget("canadian_knowledge_coverage_panel_js", "Canadian knowledge coverage JavaScript", "assets/CanadianKnowledgeCoveragePanel-*.js", 4_500),
    BundleBudget("open_agronomy_info_pages_js", "Privacy and About JavaScript", "assets/OpenAgronomyInfoPages-*.js", 5_000),
    BundleBudget("open_agronomy_app_css", "Open Agronomy app CSS", "assets/index-*.css", 50_000, html_reference_required=True),
    BundleBudget("benchmarks_route_css", "Benchmarks route CSS", "assets/BenchmarksRoute-*.css", 24_000),
    BundleBudget("leaflet_field_map_css", "Leaflet field map CSS", "assets/LeafletFieldMap-*.css", 18_500),
    BundleBudget("private_knowledge_panel_css", "Private local references CSS", "assets/PrivateKnowledgePanel-*.css", 1_600),
    BundleBudget("canadian_knowledge_coverage_panel_css", "Canadian knowledge coverage CSS", "assets/CanadianKnowledgeCoveragePanel-*.css", 3_200),
)
EXPECTED_BUNDLE_BUDGET_IDS = tuple(budget.budget_id for budget in BUNDLE_BUDGETS)
TOTAL_JS_BUDGET_BYTES = 496_500


def validate_phase6_frontend_bundle_budget(*, dist_dir: Path = DEFAULT_FRONTEND_DIST) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    assets = _collect_assets(dist_dir, failures)
    budget_rows: list[dict[str, Any]] = []
    budgeted_asset_paths: set[str] = set()

    for budget in BUNDLE_BUDGETS:
        matches = sorted(dist_dir.glob(budget.glob))
        if budget.required and not matches:
            failures.append({"budget_id": budget.budget_id, "reason": f"missing required build asset matching {budget.glob}"})
        if len(matches) > 1:
            failures.append({"budget_id": budget.budget_id, "reason": f"expected one route chunk, found {len(matches)} matches"})

        total_bytes = sum(path.stat().st_size for path in matches if path.exists())
        over_budget = total_bytes > budget.max_bytes
        if over_budget:
            failures.append(
                {
                    "budget_id": budget.budget_id,
                    "reason": f"{total_bytes} bytes exceeds budget {budget.max_bytes}",
                }
            )
        budget_rows.append(
            {
                "budget_id": budget.budget_id,
                "label": budget.label,
                "glob": budget.glob,
                "max_bytes": budget.max_bytes,
                "actual_bytes": total_bytes,
                "asset_paths": [_display_path(path) for path in matches],
                "over_budget": over_budget,
                "html_reference_required": budget.html_reference_required,
            }
        )
        budgeted_asset_paths.update(_display_path(path) for path in matches)

    js_assets = [asset for asset in assets if asset["path"].endswith(".js")]
    total_js_bytes = sum(int(asset["bytes"]) for asset in js_assets)
    if total_js_bytes > TOTAL_JS_BUDGET_BYTES:
        failures.append(
            {
                "budget_id": "total_js",
                "reason": f"{total_js_bytes} bytes exceeds total JS budget {TOTAL_JS_BUDGET_BYTES}",
            }
        )

    unbudgeted_assets = sorted(asset["path"] for asset in assets if asset["path"] not in budgeted_asset_paths)
    for asset_path in unbudgeted_assets:
        failures.append({"budget_id": "unbudgeted_asset", "reason": f"unbudgeted JS/CSS asset present: {asset_path}"})

    html_reference_missing: list[str] = []
    index_html = dist_dir / "index.html"
    if not index_html.exists():
        failures.append({"budget_id": "index_html", "reason": "frontend/dist/index.html is missing"})
    else:
        html = index_html.read_text(encoding="utf-8")
        for row in budget_rows:
            for asset_path in row["asset_paths"]:
                asset_ref = asset_path.removeprefix("frontend/dist/")
                if asset_ref.endswith((".js", ".css")) and asset_ref not in html and row["html_reference_required"]:
                    html_reference_missing.append(asset_path)
                    failures.append({"budget_id": row["budget_id"], "reason": f"index.html does not reference {asset_ref}"})

    budget_ids = tuple(row["budget_id"] for row in budget_rows)
    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "dist_dir": _display_path(dist_dir),
        "route_budget_count": len(BUNDLE_BUDGETS),
        "expected_budget_ids": list(EXPECTED_BUNDLE_BUDGET_IDS),
        "budget_ids": list(budget_ids),
        "budget_manifest_exact": budget_ids == EXPECTED_BUNDLE_BUDGET_IDS,
        "total_js_budget_bytes": TOTAL_JS_BUDGET_BYTES,
        "total_js_bytes": total_js_bytes,
        "assets": assets,
        "asset_count": len(assets),
        "budgeted_asset_count": len(budgeted_asset_paths),
        "unbudgeted_assets": unbudgeted_assets,
        "html_reference_missing": html_reference_missing,
        "budgets": budget_rows,
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_frontend_bundle_budget_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _collect_assets(dist_dir: Path, failures: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not dist_dir.exists():
        failures.append({"budget_id": "dist_dir", "reason": f"{_display_path(dist_dir)} does not exist"})
        return []
    assets: list[dict[str, Any]] = []
    for path in sorted(dist_dir.glob("assets/*")):
        if path.is_file() and path.suffix in {".js", ".css"}:
            assets.append({"path": _display_path(path), "bytes": path.stat().st_size})
    if not assets:
        failures.append({"budget_id": "assets", "reason": "no JS/CSS assets found in frontend/dist/assets"})
    return assets


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
