from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from agronomy_agent.paths import REPO_ROOT, repo_path


OPEN_AGRONOMY_BENCHMARK_MANIFEST = repo_path("data/eval/open_agronomy_canadian_performance_v1_manifest.json")
OPEN_AGRONOMY_BENCHMARK_CONTRACT = repo_path("configs/open_agronomy_canadian_performance_v1.json")
OPEN_AGRONOMY_BENCHMARK_DATABASE = repo_path(
    "outputs/open_agronomy_canadian_performance_v1/full_system_benchmark.sqlite3"
)
OPEN_AGRONOMY_EXTERNAL_MANIFEST = repo_path("data/eval/open_agronomy_external_agroqa_v1_manifest.json")
OPEN_AGRONOMY_EXTERNAL_CONTRACT = repo_path("configs/open_agronomy_external_agroqa_v1.json")
OPEN_AGRONOMY_EXTERNAL_DATABASE = repo_path(
    "outputs/open_agronomy_external_agroqa_v1_three_model_20260809/full_system_benchmark.sqlite3"
)
OPEN_AGRONOMY_SEPARATION_MANIFEST = repo_path(
    "data/eval/open_agronomy_canadian_external_agroqa_separation_manifest.json"
)


DEFAULT_AIAGRIBENCH_PROXY_ROOTS = (
    repo_path("outputs/evals/aiagribench_proxy_iter17_full_live_precision_economics_cleanup"),
    repo_path("outputs/evals/aiagribench_proxy_iter16b_rescore_precision_economics_concise"),
    repo_path("outputs/evals/aiagribench_proxy_iter15_full_live_final_floor_cleanup"),
    repo_path("outputs/evals/aiagribench_proxy_iter14_rescore_final_floor_cleanup"),
    repo_path("outputs/evals/aiagribench_proxy_iter13_full_live_after_spray_drift_cleanup"),
    repo_path("outputs/evals/aiagribench_proxy_iter12_rescore_spray_drift_cleanup"),
    repo_path("outputs/evals/aiagribench_proxy_iter11_full_live_post_sub95_repairs"),
    repo_path("outputs/evals/aiagribench_proxy_iter10_full_rescore_sub95_repairs"),
    repo_path("outputs/evals/aiagribench_proxy_submission_freeze_final_live"),
)


def open_agronomy_benchmark_summary() -> dict[str, Any]:
    """Return the stable canonical benchmark contract, never a legacy proxy score."""

    if not OPEN_AGRONOMY_BENCHMARK_MANIFEST.is_file() or not OPEN_AGRONOMY_BENCHMARK_CONTRACT.is_file():
        return {
            "available": False,
            "benchmark_id": "open_agronomy_canadian_performance_v1",
            "message": "Canonical benchmark contract is unavailable.",
        }
    manifest = json.loads(OPEN_AGRONOMY_BENCHMARK_MANIFEST.read_text(encoding="utf-8"))
    contract = json.loads(OPEN_AGRONOMY_BENCHMARK_CONTRACT.read_text(encoding="utf-8"))
    external_manifest = (
        json.loads(OPEN_AGRONOMY_EXTERNAL_MANIFEST.read_text(encoding="utf-8"))
        if OPEN_AGRONOMY_EXTERNAL_MANIFEST.is_file()
        else None
    )
    separation = (
        json.loads(OPEN_AGRONOMY_SEPARATION_MANIFEST.read_text(encoding="utf-8"))
        if OPEN_AGRONOMY_SEPARATION_MANIFEST.is_file()
        else None
    )
    return {
        "available": True,
        "benchmark_id": manifest["benchmark_id"],
        "status": manifest["status"],
        "rows": manifest["rows"],
        "lane_counts": manifest["lane_counts"],
        "unique_questions": manifest["unique_questions"],
        "exact_duplicate_questions": manifest["exact_duplicate_questions"],
        "traceable_real_user_questions": manifest["traceable_real_user_questions"],
        "claim_eligible": False,
        "suite_sha256": manifest["suite_sha256"],
        "default_modes": contract["default_modes"],
        "primary_comparison": contract["primary_comparison"],
        "evaluation_policy": manifest["evaluation_policy"],
        "database_available": OPEN_AGRONOMY_BENCHMARK_DATABASE.is_file(),
        "database_path": str(OPEN_AGRONOMY_BENCHMARK_DATABASE.relative_to(REPO_ROOT)),
        "canonical_command": ".venv/bin/python scripts/run_open_agronomy_benchmark.py --model-config MODEL_CONFIG --model-key MODEL_KEY",
        "external_diagnostic": {
            "available": external_manifest is not None,
            "benchmark_id": external_manifest.get("benchmark_id") if external_manifest else None,
            "rows": external_manifest.get("rows") if external_manifest else None,
            "suite_sha256": external_manifest.get("suite_sha256") if external_manifest else None,
            "database_available": OPEN_AGRONOMY_EXTERNAL_DATABASE.is_file(),
            "separation_status": separation.get("status") if separation else "missing",
            "exact_overlap": separation.get("question_overlap", {}).get("exact_match_count") if separation else None,
            "near_overlap": separation.get("question_overlap", {}).get("near_duplicate_count") if separation else None,
            "claim_eligible": False,
            "geographic_scope": "Ugandan farmer questions; external transfer diagnostic only",
            "canonical_command": ".venv/bin/python scripts/run_open_agronomy_benchmark.py --evaluation-set external --model-config MODEL_CONFIG --model-key MODEL_KEY",
            "use_policy": (
                "Finalist-only external transfer diagnostic. Published answers are not independently revalidated; "
                "never tune and retest on the same frozen version."
            ),
        },
        "quarantined_historical_benchmarks": [
            {
                "benchmark_id": "open_agronomy_public_verification_v3",
                "status": "quarantined_upstream_answer_key_defects_20260809",
                "claim_eligible": False,
            }
        ],
        "message": (
            "Project-owned Canadian development benchmark plus a separately frozen, source-disjoint "
            "non-Canadian transfer diagnostic. Neither is independent agronomist validation."
        ),
    }
PUBLIC_DOMAIN_COVERAGE_MANIFEST = repo_path("data/eval/public_domain_coverage_manifest.json")
PUBLIC_DOMAIN_COVERAGE_SUITE = repo_path("data/eval/public_domain_coverage_eval.jsonl")
PUBLIC_DOMAIN_DEEP_COVERAGE_MANIFEST = repo_path("data/eval/public_domain_deep_coverage_manifest.json")
PUBLIC_DOMAIN_DEEP_COVERAGE_SUITE = repo_path("data/eval/public_domain_deep_coverage_eval.jsonl")
PUBLIC_DOMAIN_DEEP_COVERAGE_SMOKE_MANIFEST = repo_path("data/eval/public_domain_deep_coverage_smoke_manifest.json")
PUBLIC_DOMAIN_DEEP_COVERAGE_SMOKE_SUITE = repo_path("data/eval/public_domain_deep_coverage_smoke_eval.jsonl")
PUBLIC_DOMAIN_DEEP_COVERAGE_BUILDER = repo_path("scripts/build_public_domain_deep_coverage_suite.py")
PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_JSON = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/public_domain_deep_coverage_smoke_readiness.json"
)
PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_MARKDOWN = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/public_domain_deep_coverage_smoke_readiness.md"
)
PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_BUILDER = repo_path("scripts/build_public_domain_deep_smoke_readiness.py")
PUBLIC_DOMAIN_DEEP_SMOKE_GPU_ATTEMPT_JSON = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/public_domain_deep_coverage_smoke_gpu_attempt_latest.json"
)
PUBLIC_DOMAIN_DEEP_SMOKE_GPU_ATTEMPT_MARKDOWN = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/public_domain_deep_coverage_smoke_gpu_attempt_latest.md"
)
PUBLIC_DEMO_REHEARSAL_MANIFEST = repo_path("data/eval/public_demo_rehearsal_manifest.json")
PUBLIC_DEMO_REHEARSAL_SUITE = repo_path("data/eval/public_demo_rehearsal_prompts.jsonl")
PUBLIC_DEMO_REHEARSAL_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/public_demo_rehearsal_packet.md")
PUBLIC_CLAIM_STRESS_FOCUS_MANIFEST = repo_path("data/eval/public_claim_stress_focus_manifest.json")
PUBLIC_CLAIM_STRESS_FOCUS_SUITE = repo_path("data/eval/public_claim_stress_focus_eval.jsonl")
PUBLIC_CLAIM_STRESS_FOCUS_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/public_claim_stress_focus_packet.md")
PUBLIC_CLAIM_ADAPTER_CONTEXT_PACKET = repo_path("docs/open_agronomy_agent_whitepaper_20260709/public_claim_adapter_context_packet.json")
PUBLIC_CLAIM_ADAPTER_CONTEXT_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/public_claim_adapter_context_packet.md")
PUBLIC_SHADOW_HELDOUT_MANIFEST = repo_path("data/eval/public_shadow_heldout_manifest.json")
PUBLIC_SHADOW_HELDOUT_SUITE = repo_path("data/eval/public_shadow_heldout_eval.jsonl")
PUBLIC_SHADOW_HELDOUT_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/heldout_public_shadow_packet.md")
PUBLIC_SHADOW_HELDOUT_RUNNER = repo_path("scripts/run_heldout_public_shadow_eval.py")
PUBLIC_SHADOW_HELDOUT_ANALYZER = repo_path("scripts/analyze_heldout_public_shadow_eval.py")
HELDOUT_GAP_REVIEW_JSON = repo_path("docs/open_agronomy_agent_whitepaper_20260709/heldout_public_shadow_gap_review.json")
HELDOUT_GAP_REVIEW_CSV = repo_path("docs/open_agronomy_agent_whitepaper_20260709/heldout_public_shadow_gap_review.csv")
HELDOUT_GAP_REVIEW_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/heldout_public_shadow_gap_review.md")
HELDOUT_GAP_REVIEW_BUILDER = repo_path("scripts/build_heldout_gap_review_packet.py")
HUMAN_REVIEW_QUEUE_JSONL = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_queue.jsonl")
HUMAN_REVIEW_QUEUE_MANIFEST = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_queue_manifest.json")
HUMAN_REVIEW_QUEUE_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_queue.md")
HUMAN_REVIEW_QUICKSTART = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_quickstart.md")
HUMAN_USER_TEST_SCRIPT = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_user_test_script.md")
HUMAN_SMOKE_PREFLIGHT_JSON = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_smoke_preflight.json")
HUMAN_SMOKE_PREFLIGHT_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_smoke_preflight.md")
HUMAN_SMOKE_PREFLIGHT_RUNNER = repo_path("scripts/run_human_smoke_preflight.py")
HUMAN_REVIEW_OUTCOME_SCHEMA = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_outcome_schema.json")
HUMAN_REVIEW_OUTCOME_TEMPLATE = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_outcomes_template.csv")
HUMAN_REVIEW_OUTCOME_SUMMARY = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_outcome_summary.json")
HUMAN_REVIEW_OUTCOME_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_outcome_summary.md")
HUMAN_REVIEW_BATCH_INGEST_LATEST = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_batch_ingest_latest.json")
HUMAN_REVIEW_BATCH_PREFLIGHT_LATEST = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_batch_preflight_latest.json")
HUMAN_REVIEW_BATCH_PREFLIGHT_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_batch_preflight_latest.md")
HUMAN_REVIEW_BATCH_INGEST_HELPER = repo_path("scripts/ingest_human_review_batch.py")
HUMAN_REVIEW_BATCH_PREFLIGHT_HELPER = repo_path("scripts/preflight_human_review_batch.py")
HUMAN_REVIEW_BATCHES_MANIFEST = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_batches_manifest.json")
HUMAN_REVIEW_BATCHES_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_batches.md")
HUMAN_REVIEW_BATCH_QUICKSTART_SMOKE = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_batch_quickstart_smoke.csv")
HUMAN_REVIEW_BATCH_PUBLIC_DEMO_P0 = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_batch_public_demo_p0.csv")
HUMAN_REVIEW_BATCH_QUALITY_SAMPLE = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_batch_quality_claim_sample.csv")
HUMAN_REVIEW_BATCH_SOURCE_CARD_SAMPLE = repo_path("docs/open_agronomy_agent_whitepaper_20260709/human_review_batch_source_card_p2_sample.csv")
HUMAN_REVIEW_BATCH_MERGE_HELPER = repo_path("scripts/merge_human_review_batch_outcomes.py")
LIVE_SOURCE_QA_PACKET_JSON = repo_path("docs/open_agronomy_agent_whitepaper_20260709/live_source_qa_packet.json")
LIVE_SOURCE_QA_PACKET_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/live_source_qa_packet.md")
LIVE_SOURCE_QA_PACKET_BUILDER = repo_path("scripts/build_live_source_qa_packet.py")
MOBILE_APP_QA_PACKET_JSON = repo_path("docs/open_agronomy_agent_whitepaper_20260709/mobile_app_qa_packet.json")
MOBILE_APP_QA_PACKET_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/mobile_app_qa_packet.md")
MOBILE_APP_QA_PACKET_BUILDER = repo_path("scripts/build_mobile_app_qa_packet.py")
PUBLIC_DEMO_ARTIFACT_BUNDLE_MANIFEST_JSON = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/public_demo_artifact_bundle_manifest.json"
)
PUBLIC_DEMO_ARTIFACT_BUNDLE_MANIFEST_MARKDOWN = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/public_demo_artifact_bundle_manifest.md"
)
PUBLIC_DEMO_ARTIFACT_BUNDLE_BUILDER = repo_path("scripts/build_public_demo_artifact_bundle.py")
PUBLIC_DEMO_ACCEPTANCE_CHECKLIST_JSON = repo_path("docs/open_agronomy_agent_whitepaper_20260709/public_demo_acceptance_checklist.json")
PUBLIC_DEMO_ACCEPTANCE_CHECKLIST_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/public_demo_acceptance_checklist.md")
PUBLIC_DEMO_ACCEPTANCE_CHECKLIST_BUILDER = repo_path("scripts/build_public_demo_acceptance_checklist.py")
SUBMISSION_ANSWER_HYGIENE_AUDIT_JSON = repo_path("docs/open_agronomy_agent_whitepaper_20260709/submission_answer_hygiene_audit.json")
SUBMISSION_ANSWER_HYGIENE_AUDIT_MARKDOWN = repo_path("docs/open_agronomy_agent_whitepaper_20260709/submission_answer_hygiene_audit.md")
SUBMISSION_ANSWER_HYGIENE_HIGH_RISK_CSV = repo_path("docs/open_agronomy_agent_whitepaper_20260709/submission_answer_hygiene_high_risk_review.csv")
SUBMISSION_ANSWER_HYGIENE_AUDIT_RUNNER = repo_path("scripts/audit_submission_answer_hygiene.py")
REPORT_VISUAL_QA_CURRENT_PASS = repo_path("docs/open_agronomy_agent_whitepaper_20260709/visual_qa/visual_qa_current_pass.md")
REPORT_VISUAL_QA_MANIFEST = repo_path("docs/open_agronomy_agent_whitepaper_20260709/visual_qa/visual_qa_manifest.json")
REPORT_VISUAL_QA_INSPECTION_PACKET = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/visual_qa/visual_qa_inspection_packet.md"
)
REPORT_VISUAL_QA_INSPECTION_PACKET_JSON = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/visual_qa/visual_qa_inspection_packet.json"
)
REPORT_VISUAL_QA_INSPECTION_PACKET_BUILDER = repo_path("scripts/build_visual_qa_inspection_packet.py")
REPORT_VISUAL_QA_SVG_PREVIEWS_DIR = repo_path("docs/open_agronomy_agent_whitepaper_20260709/visual_qa/svg_previews")
REPORT_VISUAL_QA_SVG_CONTACT_SHEET = repo_path("docs/open_agronomy_agent_whitepaper_20260709/visual_qa/svg_preview_contact_sheet.png")
REPORT_VISUAL_QA_PDF_CONTACT_SHEET = repo_path("docs/open_agronomy_agent_whitepaper_20260709/visual_qa/pdf_contact_sheet.png")
AGENTIC_GAP_MATRIX_DIR = repo_path("outputs/evals/agentic_gap_matrix")
AIAGRIBENCH_SUBMISSION_RUNNER = repo_path("scripts/run_aiagribench_submission.py")
AIAGRIBENCH_LEADERBOARD_REQUEST_PACKET_JSON = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/aiagribench_leaderboard_request_packet.json"
)
AIAGRIBENCH_LEADERBOARD_REQUEST_PACKET_MARKDOWN = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/aiagribench_leaderboard_request_packet.md"
)
AIAGRIBENCH_LEADERBOARD_REQUEST_PACKET_BUILDER = repo_path("scripts/build_aiagribench_leaderboard_request_packet.py")
AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_JSON = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/aiagribench_submission_dry_run_packet.json"
)
AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_MARKDOWN = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/aiagribench_submission_dry_run_packet.md"
)
AIAGRIBENCH_SUBMISSION_DRY_RUN_SUBMIT_SAFE_SAMPLE = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/aiagribench_submission_dry_run_submit_safe_sample.json"
)
AIAGRIBENCH_SUBMISSION_DRY_RUN_PROMPT_BOUNDARY_PREFLIGHT = repo_path(
    "docs/open_agronomy_agent_whitepaper_20260709/aiagribench_submission_dry_run_prompt_boundary_preflight.json"
)
AIAGRIBENCH_SUBMISSION_DRY_RUN_QUESTIONS = repo_path("data/eval/aiagribench_submission_dry_run_questions.json")
AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_BUILDER = repo_path("scripts/build_aiagribench_submission_dry_run_packet.py")
DEFAULT_MODEL_CONFIG = repo_path("configs/model.yaml")
DEFAULT_RAG_CONFIG = repo_path("configs/rag_final_mvp.yaml")
DEFAULT_PUBLIC_DOMAIN_FULL_ROOTS = (
    repo_path("outputs/evals/public_domain_coverage_full_live_1056_current_rescore_contract_repairs_final"),
    repo_path("outputs/evals/public_domain_coverage_full_live_1056_current_rescore_contract_repairs"),
)
DEFAULT_PUBLIC_DOMAIN_SMOKE_ROOTS = (
    repo_path("outputs/evals/public_domain_coverage_smoke_live_1056_expanded_rescore_contract_repairs"),
    repo_path("outputs/evals/public_domain_coverage_smoke_live_1056_expanded"),
)
DEFAULT_PUBLIC_CLAIM_STRESS_FOCUS_ROOTS = (
    repo_path("outputs/evals/public_claim_stress_focus_full_live_20260710_submission_hygiene_rescore"),
    repo_path("outputs/evals/public_claim_stress_focus_full_live_20260710_boundary_contract_rescore"),
    repo_path("outputs/evals/public_claim_stress_focus_full_live_20260710_current_rescore"),
    repo_path("outputs/evals/public_claim_stress_focus_full_live"),
)
DEFAULT_PUBLIC_SHADOW_HELDOUT_ROOTS = (repo_path("outputs/evals/public_shadow_heldout"),)
DIRECT_SEMANTIC_REVIEW_JSONL = repo_path("docs/general_agent_semantic_control_v5_direct_review_20260715.jsonl")
DIRECT_SEMANTIC_REVIEW_MARKDOWN = repo_path("docs/general_agent_semantic_control_v5_direct_review_20260715.md")
DIRECT_SEMANTIC_REVIEW_RUN = repo_path(
    "outputs/evals/general_agent_semantic_control_v5_240/agronomic_rag_20260715T031940Z"
)
BROAD_SEMANTIC_REVIEW_DIR = repo_path("outputs/evals/expert_review_807_blinded_semantic_20260718")
BROAD_SEMANTIC_REVIEW_JSONL = BROAD_SEMANTIC_REVIEW_DIR / "judgments.jsonl"
BROAD_SEMANTIC_REVIEW_MARKDOWN = BROAD_SEMANTIC_REVIEW_DIR / "summary.md"
CANADIAN_SEMANTIC_REVIEW_ROOT = repo_path("outputs/evals/canadian_semantic_reserve_v1_qwen2b")

BENCHMARK_ARTIFACT_DOWNLOADS: dict[str, dict[str, Any]] = {
    "direct-semantic-review-jsonl": {
        "path": DIRECT_SEMANTIC_REVIEW_JSONL,
        "filename": "open-agronomy-agent-direct-semantic-review.jsonl",
        "media_type": "application/x-ndjson",
        "kind": "semantic_answer_review",
    },
    "direct-semantic-review-markdown": {
        "path": DIRECT_SEMANTIC_REVIEW_MARKDOWN,
        "filename": "open-agronomy-agent-direct-semantic-review.md",
        "media_type": "text/markdown",
        "kind": "semantic_answer_review",
    },
    "public-domain-deep-coverage-manifest": {
        "path": PUBLIC_DOMAIN_DEEP_COVERAGE_MANIFEST,
        "filename": "open-agronomy-agent-public-domain-deep-coverage-manifest.json",
        "media_type": "application/json",
        "kind": "public_shadow_suite",
    },
    "public-domain-deep-coverage-suite": {
        "path": PUBLIC_DOMAIN_DEEP_COVERAGE_SUITE,
        "filename": "open-agronomy-agent-public-domain-deep-coverage.jsonl",
        "media_type": "application/x-ndjson",
        "kind": "public_shadow_suite",
    },
    "public-domain-deep-coverage-smoke-manifest": {
        "path": PUBLIC_DOMAIN_DEEP_COVERAGE_SMOKE_MANIFEST,
        "filename": "open-agronomy-agent-public-domain-deep-coverage-smoke-manifest.json",
        "media_type": "application/json",
        "kind": "public_shadow_suite",
    },
    "public-domain-deep-coverage-smoke-suite": {
        "path": PUBLIC_DOMAIN_DEEP_COVERAGE_SMOKE_SUITE,
        "filename": "open-agronomy-agent-public-domain-deep-coverage-smoke.jsonl",
        "media_type": "application/x-ndjson",
        "kind": "public_shadow_suite",
    },
    "public-domain-deep-coverage-builder": {
        "path": PUBLIC_DOMAIN_DEEP_COVERAGE_BUILDER,
        "filename": "open-agronomy-agent-build-public-domain-deep-coverage-suite.py",
        "media_type": "text/x-python",
        "kind": "public_shadow_suite",
    },
    "public-domain-deep-coverage-smoke-readiness": {
        "path": PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_JSON,
        "filename": "open-agronomy-agent-public-domain-deep-smoke-readiness.json",
        "media_type": "application/json",
        "kind": "public_shadow_suite",
    },
    "public-domain-deep-coverage-smoke-readiness-markdown": {
        "path": PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_MARKDOWN,
        "filename": "open-agronomy-agent-public-domain-deep-smoke-readiness.md",
        "media_type": "text/markdown",
        "kind": "public_shadow_suite",
    },
    "public-domain-deep-coverage-smoke-readiness-builder": {
        "path": PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_BUILDER,
        "filename": "open-agronomy-agent-build-public-domain-deep-smoke-readiness.py",
        "media_type": "text/x-python",
        "kind": "public_shadow_suite",
    },
    "public-domain-deep-coverage-smoke-gpu-attempt": {
        "path": PUBLIC_DOMAIN_DEEP_SMOKE_GPU_ATTEMPT_JSON,
        "filename": "open-agronomy-agent-public-domain-deep-smoke-gpu-attempt.json",
        "media_type": "application/json",
        "kind": "public_shadow_suite",
    },
    "public-domain-deep-coverage-smoke-gpu-attempt-markdown": {
        "path": PUBLIC_DOMAIN_DEEP_SMOKE_GPU_ATTEMPT_MARKDOWN,
        "filename": "open-agronomy-agent-public-domain-deep-smoke-gpu-attempt.md",
        "media_type": "text/markdown",
        "kind": "public_shadow_suite",
    },
    "public-demo-rehearsal-manifest": {
        "path": PUBLIC_DEMO_REHEARSAL_MANIFEST,
        "filename": "open-agronomy-agent-public-demo-rehearsal-manifest.json",
        "media_type": "application/json",
        "kind": "human_review_suite",
    },
    "public-demo-rehearsal-prompts": {
        "path": PUBLIC_DEMO_REHEARSAL_SUITE,
        "filename": "open-agronomy-agent-public-demo-rehearsal-prompts.jsonl",
        "media_type": "application/x-ndjson",
        "kind": "human_review_suite",
    },
    "public-demo-rehearsal-packet": {
        "path": PUBLIC_DEMO_REHEARSAL_MARKDOWN,
        "filename": "open-agronomy-agent-public-demo-rehearsal-packet.md",
        "media_type": "text/markdown",
        "kind": "human_review_suite",
    },
    "human-review-queue-jsonl": {
        "path": HUMAN_REVIEW_QUEUE_JSONL,
        "filename": "open-agronomy-agent-human-review-queue.jsonl",
        "media_type": "application/x-ndjson",
        "kind": "human_review_queue",
    },
    "human-review-queue-manifest": {
        "path": HUMAN_REVIEW_QUEUE_MANIFEST,
        "filename": "open-agronomy-agent-human-review-queue-manifest.json",
        "media_type": "application/json",
        "kind": "human_review_queue",
    },
    "human-review-queue-markdown": {
        "path": HUMAN_REVIEW_QUEUE_MARKDOWN,
        "filename": "open-agronomy-agent-human-review-queue.md",
        "media_type": "text/markdown",
        "kind": "human_review_queue",
    },
    "heldout-gap-review-json": {
        "path": HELDOUT_GAP_REVIEW_JSON,
        "filename": "open-agronomy-agent-heldout-gap-review.json",
        "media_type": "application/json",
        "kind": "heldout_gap_review",
    },
    "heldout-gap-review-csv": {
        "path": HELDOUT_GAP_REVIEW_CSV,
        "filename": "open-agronomy-agent-heldout-gap-review.csv",
        "media_type": "text/csv",
        "kind": "heldout_gap_review",
    },
    "heldout-gap-review-markdown": {
        "path": HELDOUT_GAP_REVIEW_MARKDOWN,
        "filename": "open-agronomy-agent-heldout-gap-review.md",
        "media_type": "text/markdown",
        "kind": "heldout_gap_review",
    },
    "human-review-quickstart": {
        "path": HUMAN_REVIEW_QUICKSTART,
        "filename": "open-agronomy-agent-human-review-quickstart.md",
        "media_type": "text/markdown",
        "kind": "human_review_queue",
    },
    "human-user-test-script": {
        "path": HUMAN_USER_TEST_SCRIPT,
        "filename": "open-agronomy-agent-human-user-test-script.md",
        "media_type": "text/markdown",
        "kind": "human_review_queue",
    },
    "human-smoke-preflight": {
        "path": HUMAN_SMOKE_PREFLIGHT_JSON,
        "filename": "open-agronomy-agent-human-smoke-preflight.json",
        "media_type": "application/json",
        "kind": "human_review_queue",
    },
    "human-smoke-preflight-markdown": {
        "path": HUMAN_SMOKE_PREFLIGHT_MARKDOWN,
        "filename": "open-agronomy-agent-human-smoke-preflight.md",
        "media_type": "text/markdown",
        "kind": "human_review_queue",
    },
    "human-review-batches-manifest": {
        "path": HUMAN_REVIEW_BATCHES_MANIFEST,
        "filename": "open-agronomy-agent-human-review-batches-manifest.json",
        "media_type": "application/json",
        "kind": "human_review_batches",
    },
    "human-review-batch-quickstart-smoke": {
        "path": HUMAN_REVIEW_BATCH_QUICKSTART_SMOKE,
        "filename": "open-agronomy-agent-human-review-batch-quickstart-smoke.csv",
        "media_type": "text/csv",
        "kind": "human_review_batches",
    },
    "human-review-batch-public-demo-p0": {
        "path": HUMAN_REVIEW_BATCH_PUBLIC_DEMO_P0,
        "filename": "open-agronomy-agent-human-review-batch-public-demo-p0.csv",
        "media_type": "text/csv",
        "kind": "human_review_batches",
    },
    "human-review-batch-quality-sample": {
        "path": HUMAN_REVIEW_BATCH_QUALITY_SAMPLE,
        "filename": "open-agronomy-agent-human-review-batch-quality-sample.csv",
        "media_type": "text/csv",
        "kind": "human_review_batches",
    },
    "human-review-batch-source-card-sample": {
        "path": HUMAN_REVIEW_BATCH_SOURCE_CARD_SAMPLE,
        "filename": "open-agronomy-agent-human-review-batch-source-card-sample.csv",
        "media_type": "text/csv",
        "kind": "human_review_batches",
    },
    "human-review-outcome-schema": {
        "path": HUMAN_REVIEW_OUTCOME_SCHEMA,
        "filename": "open-agronomy-agent-human-review-outcome-schema.json",
        "media_type": "application/json",
        "kind": "human_review_outcomes",
    },
    "human-review-outcomes-template": {
        "path": HUMAN_REVIEW_OUTCOME_TEMPLATE,
        "filename": "open-agronomy-agent-human-review-outcomes-template.csv",
        "media_type": "text/csv",
        "kind": "human_review_outcomes",
    },
    "human-review-outcome-summary": {
        "path": HUMAN_REVIEW_OUTCOME_SUMMARY,
        "filename": "open-agronomy-agent-human-review-outcome-summary.json",
        "media_type": "application/json",
        "kind": "human_review_outcomes",
    },
    "human-review-outcome-markdown": {
        "path": HUMAN_REVIEW_OUTCOME_MARKDOWN,
        "filename": "open-agronomy-agent-human-review-outcome-summary.md",
        "media_type": "text/markdown",
        "kind": "human_review_outcomes",
    },
    "human-review-batch-ingest-latest": {
        "path": HUMAN_REVIEW_BATCH_INGEST_LATEST,
        "filename": "open-agronomy-agent-human-review-batch-ingest-latest.json",
        "media_type": "application/json",
        "kind": "human_review_outcomes",
    },
    "human-review-batch-preflight-latest": {
        "path": HUMAN_REVIEW_BATCH_PREFLIGHT_LATEST,
        "filename": "open-agronomy-agent-human-review-batch-preflight-latest.json",
        "media_type": "application/json",
        "kind": "human_review_outcomes",
    },
    "human-review-batch-preflight-markdown": {
        "path": HUMAN_REVIEW_BATCH_PREFLIGHT_MARKDOWN,
        "filename": "open-agronomy-agent-human-review-batch-preflight-latest.md",
        "media_type": "text/markdown",
        "kind": "human_review_outcomes",
    },
    "human-review-batch-ingest-helper": {
        "path": HUMAN_REVIEW_BATCH_INGEST_HELPER,
        "filename": "open-agronomy-agent-human-review-batch-ingest.py",
        "media_type": "text/x-python",
        "kind": "human_review_outcomes",
    },
    "human-review-batch-preflight-helper": {
        "path": HUMAN_REVIEW_BATCH_PREFLIGHT_HELPER,
        "filename": "open-agronomy-agent-human-review-batch-preflight.py",
        "media_type": "text/x-python",
        "kind": "human_review_outcomes",
    },
    "public-demo-acceptance-checklist": {
        "path": PUBLIC_DEMO_ACCEPTANCE_CHECKLIST_MARKDOWN,
        "filename": "open-agronomy-agent-public-demo-acceptance-checklist.md",
        "media_type": "text/markdown",
        "kind": "human_review_outcomes",
    },
    "public-demo-acceptance-checklist-json": {
        "path": PUBLIC_DEMO_ACCEPTANCE_CHECKLIST_JSON,
        "filename": "open-agronomy-agent-public-demo-acceptance-checklist.json",
        "media_type": "application/json",
        "kind": "human_review_outcomes",
    },
    "live-source-qa-packet": {
        "path": LIVE_SOURCE_QA_PACKET_MARKDOWN,
        "filename": "open-agronomy-agent-live-source-qa-packet.md",
        "media_type": "text/markdown",
        "kind": "human_review_queue",
    },
    "live-source-qa-packet-json": {
        "path": LIVE_SOURCE_QA_PACKET_JSON,
        "filename": "open-agronomy-agent-live-source-qa-packet.json",
        "media_type": "application/json",
        "kind": "human_review_queue",
    },
    "live-source-qa-packet-builder": {
        "path": LIVE_SOURCE_QA_PACKET_BUILDER,
        "filename": "open-agronomy-agent-build-live-source-qa-packet.py",
        "media_type": "text/x-python",
        "kind": "human_review_queue",
    },
    "mobile-app-qa-packet": {
        "path": MOBILE_APP_QA_PACKET_MARKDOWN,
        "filename": "open-agronomy-agent-mobile-app-qa-packet.md",
        "media_type": "text/markdown",
        "kind": "human_review_queue",
    },
    "mobile-app-qa-packet-json": {
        "path": MOBILE_APP_QA_PACKET_JSON,
        "filename": "open-agronomy-agent-mobile-app-qa-packet.json",
        "media_type": "application/json",
        "kind": "human_review_queue",
    },
    "mobile-app-qa-packet-builder": {
        "path": MOBILE_APP_QA_PACKET_BUILDER,
        "filename": "open-agronomy-agent-build-mobile-app-qa-packet.py",
        "media_type": "text/x-python",
        "kind": "human_review_queue",
    },
    "public-demo-artifact-bundle-manifest": {
        "path": PUBLIC_DEMO_ARTIFACT_BUNDLE_MANIFEST_MARKDOWN,
        "filename": "open-agronomy-agent-public-demo-artifact-bundle-manifest.md",
        "media_type": "text/markdown",
        "kind": "public_demo_artifact_bundle",
    },
    "public-demo-artifact-bundle-manifest-json": {
        "path": PUBLIC_DEMO_ARTIFACT_BUNDLE_MANIFEST_JSON,
        "filename": "open-agronomy-agent-public-demo-artifact-bundle-manifest.json",
        "media_type": "application/json",
        "kind": "public_demo_artifact_bundle",
    },
    "public-demo-artifact-bundle-builder": {
        "path": PUBLIC_DEMO_ARTIFACT_BUNDLE_BUILDER,
        "filename": "open-agronomy-agent-build-public-demo-artifact-bundle.py",
        "media_type": "text/x-python",
        "kind": "public_demo_artifact_bundle",
    },
    "submission-answer-hygiene-audit": {
        "path": SUBMISSION_ANSWER_HYGIENE_AUDIT_JSON,
        "filename": "open-agronomy-agent-submission-answer-hygiene-audit.json",
        "media_type": "application/json",
        "kind": "submission_answer_hygiene",
    },
    "submission-answer-hygiene-markdown": {
        "path": SUBMISSION_ANSWER_HYGIENE_AUDIT_MARKDOWN,
        "filename": "open-agronomy-agent-submission-answer-hygiene-audit.md",
        "media_type": "text/markdown",
        "kind": "submission_answer_hygiene",
    },
    "submission-answer-hygiene-high-risk-csv": {
        "path": SUBMISSION_ANSWER_HYGIENE_HIGH_RISK_CSV,
        "filename": "open-agronomy-agent-submission-answer-hygiene-high-risk-review.csv",
        "media_type": "text/csv",
        "kind": "submission_answer_hygiene",
    },
    "aiagribench-leaderboard-request-packet": {
        "path": AIAGRIBENCH_LEADERBOARD_REQUEST_PACKET_MARKDOWN,
        "filename": "open-agronomy-agent-aiagribench-leaderboard-request-packet.md",
        "media_type": "text/markdown",
        "kind": "aiagribench_submission",
    },
    "aiagribench-leaderboard-request-packet-json": {
        "path": AIAGRIBENCH_LEADERBOARD_REQUEST_PACKET_JSON,
        "filename": "open-agronomy-agent-aiagribench-leaderboard-request-packet.json",
        "media_type": "application/json",
        "kind": "aiagribench_submission",
    },
    "aiagribench-submission-dry-run-packet": {
        "path": AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_MARKDOWN,
        "filename": "open-agronomy-agent-aiagribench-submission-dry-run-packet.md",
        "media_type": "text/markdown",
        "kind": "aiagribench_submission",
    },
    "aiagribench-submission-dry-run-packet-json": {
        "path": AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_JSON,
        "filename": "open-agronomy-agent-aiagribench-submission-dry-run-packet.json",
        "media_type": "application/json",
        "kind": "aiagribench_submission",
    },
    "aiagribench-submission-dry-run-submit-safe-sample": {
        "path": AIAGRIBENCH_SUBMISSION_DRY_RUN_SUBMIT_SAFE_SAMPLE,
        "filename": "open-agronomy-agent-aiagribench-submission-dry-run-submit-safe-sample.json",
        "media_type": "application/json",
        "kind": "aiagribench_submission",
    },
    "aiagribench-submission-dry-run-prompt-boundary-preflight": {
        "path": AIAGRIBENCH_SUBMISSION_DRY_RUN_PROMPT_BOUNDARY_PREFLIGHT,
        "filename": "open-agronomy-agent-aiagribench-submission-dry-run-prompt-boundary-preflight.json",
        "media_type": "application/json",
        "kind": "aiagribench_submission",
    },
    "visual-qa-current-pass": {
        "path": REPORT_VISUAL_QA_CURRENT_PASS,
        "filename": "open-agronomy-agent-report-visual-qa-current-pass.md",
        "media_type": "text/markdown",
        "kind": "report_visual_qa",
    },
    "visual-qa-manifest": {
        "path": REPORT_VISUAL_QA_MANIFEST,
        "filename": "open-agronomy-agent-report-visual-qa-manifest.json",
        "media_type": "application/json",
        "kind": "report_visual_qa",
    },
    "visual-qa-inspection-packet": {
        "path": REPORT_VISUAL_QA_INSPECTION_PACKET,
        "filename": "open-agronomy-agent-report-visual-qa-inspection-packet.md",
        "media_type": "text/markdown",
        "kind": "report_visual_qa",
    },
    "visual-qa-inspection-packet-json": {
        "path": REPORT_VISUAL_QA_INSPECTION_PACKET_JSON,
        "filename": "open-agronomy-agent-report-visual-qa-inspection-packet.json",
        "media_type": "application/json",
        "kind": "report_visual_qa",
    },
    "visual-qa-inspection-packet-builder": {
        "path": REPORT_VISUAL_QA_INSPECTION_PACKET_BUILDER,
        "filename": "open-agronomy-agent-build-visual-qa-inspection-packet.py",
        "media_type": "text/x-python",
        "kind": "report_visual_qa",
    },
}


def benchmark_artifact_download(artifact_id: str) -> dict[str, Any]:
    spec = BENCHMARK_ARTIFACT_DOWNLOADS.get(artifact_id)
    if spec is None:
        raise KeyError(artifact_id)

    path = repo_path(spec["path"]).resolve()
    repo_root = REPO_ROOT.resolve()
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"benchmark artifact is outside the repository: {artifact_id}") from exc
    if not path.is_file():
        raise FileNotFoundError(path)

    artifact = _artifact_entry(artifact_id.replace("-", "_"), path, kind=str(spec["kind"]))
    artifact["download_id"] = artifact_id
    return {
        "artifact_id": artifact_id,
        "path": path,
        "filename": str(spec["filename"]),
        "media_type": str(spec["media_type"]),
        "artifact": artifact,
        "boundary": (
            "Allowlisted public-demo, human-review, answer-hygiene, AI AgriBench dry-run, or report-QA artifact; official AI AgriBench "
            "question text, traces, and internal submission audit files are not exposed through this endpoint."
        ),
    }


def latest_aiagribench_proxy_summary(root: Path | None = None) -> dict[str, Any]:
    roots = (root,) if root is not None else DEFAULT_AIAGRIBENCH_PROXY_ROOTS
    summary_paths = sorted(_summary_paths(roots), key=lambda path: path.stat().st_mtime, reverse=True)
    if not summary_paths:
        base_label = str(root) if root is not None else ", ".join(str(path) for path in DEFAULT_AIAGRIBENCH_PROXY_ROOTS)
        return {
            "available": False,
            "suite": "AI AgriBench proxy",
            "message": f"No generated proxy summaries found under {base_label}",
            "official_leaderboard_score": None,
            "public_coverage": _public_coverage_summary(),
            "public_deep_coverage": _public_deep_coverage_summary(),
            "public_full_gap": _public_full_gap_summary(),
            "public_smoke_gap": _public_smoke_gap_summary(),
            "public_claim_stress_focus": _public_claim_stress_focus_gap_summary(),
            "public_demo_rehearsal": _public_demo_rehearsal_summary(),
            "public_claim_adapter_context": _public_claim_adapter_context_summary(),
            "public_shadow_heldout": _public_shadow_heldout_summary(),
            "public_shadow_heldout_result": _public_shadow_heldout_result_summary(),
            "heldout_gap_review": _heldout_gap_review_summary(),
            "agentic_gap_matrix": _agentic_gap_matrix_summary(),
            "human_review_queue": _human_review_queue_summary(),
            "human_review_batches": human_review_batches_summary(),
            "human_smoke_preflight": _human_smoke_preflight_summary(),
            "human_review_outcomes": human_review_outcome_summary(),
            "submission_answer_hygiene": _submission_answer_hygiene_summary(),
            "aiagribench_submission_dry_run": _aiagribench_submission_dry_run_summary(),
            "report_visual_qa": _report_visual_qa_summary(),
            "direct_semantic_review": _direct_semantic_review_summary(),
            "canadian_semantic_review": _canadian_semantic_review_summary(),
        }

    summary_path = summary_paths[0]
    run_dir = summary_path.parent
    summary = _read_json(summary_path)
    rows = _read_output_rows(run_dir / "outputs.jsonl")

    family_floors = sorted(
        (
            {
                "family": family,
                "samples": int(payload.get("samples") or 0),
                "mean_score": payload.get("mean_score"),
                "min_score": payload.get("min_score"),
                "max_score": payload.get("max_score"),
                "flagged_missing_required": int(payload.get("flagged_missing_required") or 0),
            }
            for family, payload in (summary.get("by_family") or {}).items()
            if isinstance(payload, dict)
        ),
        key=lambda item: (float(item["mean_score"] or 0), item["family"]),
    )

    scores = [_row_score(row) for row in rows]
    elapsed = [float(row.get("elapsed_seconds")) for row in rows if _is_number(row.get("elapsed_seconds"))]
    missing_flags = sum(
        int((payload or {}).get("flagged_missing_required") or 0)
        for payload in (summary.get("by_family") or {}).values()
        if isinstance(payload, dict)
    )

    return {
        "available": True,
        "suite": "AI AgriBench proxy",
        "run_id": run_dir.name,
        "artifact_dir": str(run_dir),
        "created_at": summary.get("created_at"),
        "mode": summary.get("mode"),
        "model_id": summary.get("model_id"),
        "answer_profile": summary.get("answer_profile"),
        "source_run_dir": summary.get("source_run_dir"),
        "rubric": summary.get("rubric"),
        "normalized_rows": summary.get("normalized_rows"),
        "improved_rows": summary.get("improved_rows"),
        "regressed_rows": summary.get("regressed_rows"),
        "samples": summary.get("samples"),
        "mean_score": summary.get("mean_score"),
        "metrics": summary.get("metric_means") or {},
        "missing_required_flags": missing_flags,
        "under90_rows": sum(1 for score in scores if score < 90),
        "average_seconds": round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
        "max_seconds": round(max(elapsed), 2) if elapsed else None,
        "family_floors": family_floors,
        "lowest_rows": [_summarize_row(row) for row in sorted(rows, key=_row_score)[:8]],
        "official_leaderboard_score": None,
        "public_coverage": _public_coverage_summary(),
        "public_deep_coverage": _public_deep_coverage_summary(),
        "public_full_gap": _public_full_gap_summary(),
        "public_smoke_gap": _public_smoke_gap_summary(),
        "public_claim_stress_focus": _public_claim_stress_focus_gap_summary(),
        "public_demo_rehearsal": _public_demo_rehearsal_summary(),
        "public_claim_adapter_context": _public_claim_adapter_context_summary(),
        "public_shadow_heldout": _public_shadow_heldout_summary(),
        "public_shadow_heldout_result": _public_shadow_heldout_result_summary(),
        "heldout_gap_review": _heldout_gap_review_summary(),
        "agentic_gap_matrix": _agentic_gap_matrix_summary(),
        "human_review_queue": _human_review_queue_summary(),
        "human_review_batches": human_review_batches_summary(),
        "human_smoke_preflight": _human_smoke_preflight_summary(),
        "human_review_outcomes": human_review_outcome_summary(),
        "submission_answer_hygiene": _submission_answer_hygiene_summary(),
        "aiagribench_submission_dry_run": _aiagribench_submission_dry_run_summary(),
        "report_visual_qa": _report_visual_qa_summary(),
        "direct_semantic_review": _direct_semantic_review_summary(),
        "canadian_semantic_review": _canadian_semantic_review_summary(),
        "score_warning": summary.get("score_warning")
        or "Local deterministic proxy rubric; not an official AI AgriBench leaderboard score.",
    }


def aiagribench_submission_freeze_manifest(
    *,
    model_config_path: Path | None = None,
    rag_config_path: Path | None = None,
    benchmark_root: Path | None = None,
) -> dict[str, Any]:
    model_config_path = model_config_path or DEFAULT_MODEL_CONFIG
    rag_config_path = rag_config_path or DEFAULT_RAG_CONFIG
    model_config = _read_mapping_file(model_config_path)
    rag_config = _read_mapping_file(rag_config_path)
    retrieval = rag_config.get("retrieval") if isinstance(rag_config.get("retrieval"), dict) else {}
    corpus_paths = _configured_paths(
        retrieval.get("corpus_paths") or [retrieval.get("corpus_path") or "data/seed/agronomy_rag_corpus.jsonl"]
    )
    graph_paths = _configured_paths(retrieval.get("graph_paths") or [])
    proxy_summary = latest_aiagribench_proxy_summary(benchmark_root)
    public_full_gap = _public_full_gap_summary()
    public_smoke_gap = _public_smoke_gap_summary()
    public_claim_stress_focus = _public_claim_stress_focus_gap_summary()
    public_coverage = _public_coverage_summary()
    public_deep_coverage = _public_deep_coverage_summary()
    public_demo_rehearsal = _public_demo_rehearsal_summary()
    public_shadow_heldout = _public_shadow_heldout_summary()
    public_shadow_heldout_result = _public_shadow_heldout_result_summary()
    heldout_gap_review = _heldout_gap_review_summary()
    human_review_queue = _human_review_queue_summary()
    human_review_batches = human_review_batches_summary()
    human_smoke_preflight = _human_smoke_preflight_summary()
    human_review_outcomes = human_review_outcome_summary()
    submission_answer_hygiene = _submission_answer_hygiene_summary()
    aiagribench_submission_dry_run = _aiagribench_submission_dry_run_summary()
    report_visual_qa = _report_visual_qa_summary()
    direct_semantic_review = _direct_semantic_review_summary()
    latest_artifacts = _latest_proxy_artifacts(proxy_summary)
    public_artifacts = [
        _artifact_entry("public_coverage_manifest", PUBLIC_DOMAIN_COVERAGE_MANIFEST, kind="public_shadow_suite"),
        _artifact_entry("public_coverage_suite", PUBLIC_DOMAIN_COVERAGE_SUITE, kind="public_shadow_suite"),
        _artifact_entry("public_deep_coverage_manifest", PUBLIC_DOMAIN_DEEP_COVERAGE_MANIFEST, kind="public_shadow_suite"),
        _artifact_entry("public_deep_coverage_suite", PUBLIC_DOMAIN_DEEP_COVERAGE_SUITE, kind="public_shadow_suite"),
        _artifact_entry(
            "public_deep_coverage_smoke_manifest",
            PUBLIC_DOMAIN_DEEP_COVERAGE_SMOKE_MANIFEST,
            kind="public_shadow_suite",
        ),
        _artifact_entry("public_deep_coverage_smoke_suite", PUBLIC_DOMAIN_DEEP_COVERAGE_SMOKE_SUITE, kind="public_shadow_suite"),
        _artifact_entry("public_deep_coverage_builder", PUBLIC_DOMAIN_DEEP_COVERAGE_BUILDER, kind="public_shadow_suite"),
        _artifact_entry(
            "public_deep_smoke_readiness",
            PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_JSON,
            kind="public_shadow_suite",
        ),
        _artifact_entry(
            "public_deep_smoke_readiness_markdown",
            PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_MARKDOWN,
            kind="public_shadow_suite",
        ),
        _artifact_entry(
            "public_deep_smoke_readiness_builder",
            PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_BUILDER,
            kind="public_shadow_suite",
        ),
        _artifact_entry(
            "public_deep_smoke_gpu_attempt",
            PUBLIC_DOMAIN_DEEP_SMOKE_GPU_ATTEMPT_JSON,
            kind="public_shadow_suite",
        ),
        _artifact_entry(
            "public_deep_smoke_gpu_attempt_markdown",
            PUBLIC_DOMAIN_DEEP_SMOKE_GPU_ATTEMPT_MARKDOWN,
            kind="public_shadow_suite",
        ),
        _artifact_entry("public_demo_rehearsal_manifest", PUBLIC_DEMO_REHEARSAL_MANIFEST, kind="human_review_suite"),
        _artifact_entry("public_demo_rehearsal_prompts", PUBLIC_DEMO_REHEARSAL_SUITE, kind="human_review_suite"),
        _artifact_entry("public_demo_rehearsal_packet", PUBLIC_DEMO_REHEARSAL_MARKDOWN, kind="human_review_suite"),
        _artifact_entry("public_claim_stress_focus_manifest", PUBLIC_CLAIM_STRESS_FOCUS_MANIFEST, kind="public_shadow_suite"),
        _artifact_entry("public_claim_stress_focus_suite", PUBLIC_CLAIM_STRESS_FOCUS_SUITE, kind="public_shadow_suite"),
        _artifact_entry("public_claim_stress_focus_packet", PUBLIC_CLAIM_STRESS_FOCUS_MARKDOWN, kind="public_shadow_suite"),
        _artifact_entry("public_shadow_heldout_manifest", PUBLIC_SHADOW_HELDOUT_MANIFEST, kind="heldout_shadow_suite"),
        _artifact_entry("public_shadow_heldout_suite", PUBLIC_SHADOW_HELDOUT_SUITE, kind="heldout_shadow_suite"),
        _artifact_entry("public_shadow_heldout_packet", PUBLIC_SHADOW_HELDOUT_MARKDOWN, kind="heldout_shadow_suite"),
        _artifact_entry("public_shadow_heldout_runner", PUBLIC_SHADOW_HELDOUT_RUNNER, kind="heldout_shadow_runner"),
        _artifact_entry("public_shadow_heldout_analyzer", PUBLIC_SHADOW_HELDOUT_ANALYZER, kind="heldout_shadow_runner"),
        _artifact_entry("heldout_gap_review_json", HELDOUT_GAP_REVIEW_JSON, kind="heldout_gap_review"),
        _artifact_entry("heldout_gap_review_csv", HELDOUT_GAP_REVIEW_CSV, kind="heldout_gap_review"),
        _artifact_entry("heldout_gap_review_markdown", HELDOUT_GAP_REVIEW_MARKDOWN, kind="heldout_gap_review"),
        _artifact_entry("heldout_gap_review_builder", HELDOUT_GAP_REVIEW_BUILDER, kind="heldout_gap_review"),
        _artifact_entry("agentic_gap_matrix_summary", AGENTIC_GAP_MATRIX_DIR / "summary.json", kind="agentic_gap_matrix"),
        _artifact_entry("agentic_gap_matrix_jsonl", AGENTIC_GAP_MATRIX_DIR / "agentic_gap_matrix.jsonl", kind="agentic_gap_matrix"),
        _artifact_entry("human_review_queue_jsonl", HUMAN_REVIEW_QUEUE_JSONL, kind="human_review_queue"),
        _artifact_entry("human_review_queue_manifest", HUMAN_REVIEW_QUEUE_MANIFEST, kind="human_review_queue"),
        _artifact_entry("human_review_queue_markdown", HUMAN_REVIEW_QUEUE_MARKDOWN, kind="human_review_queue"),
        _artifact_entry("human_review_quickstart", HUMAN_REVIEW_QUICKSTART, kind="human_review_queue"),
        _artifact_entry("human_user_test_script", HUMAN_USER_TEST_SCRIPT, kind="human_review_queue"),
        _artifact_entry("human_smoke_preflight_json", HUMAN_SMOKE_PREFLIGHT_JSON, kind="human_review_queue"),
        _artifact_entry("human_smoke_preflight_markdown", HUMAN_SMOKE_PREFLIGHT_MARKDOWN, kind="human_review_queue"),
        _artifact_entry("human_smoke_preflight_runner", HUMAN_SMOKE_PREFLIGHT_RUNNER, kind="human_review_queue"),
        _artifact_entry("mobile_app_qa_packet_json", MOBILE_APP_QA_PACKET_JSON, kind="human_review_queue"),
        _artifact_entry("mobile_app_qa_packet_markdown", MOBILE_APP_QA_PACKET_MARKDOWN, kind="human_review_queue"),
        _artifact_entry("mobile_app_qa_packet_builder", MOBILE_APP_QA_PACKET_BUILDER, kind="human_review_queue"),
        _artifact_entry(
            "public_demo_artifact_bundle_manifest_json",
            PUBLIC_DEMO_ARTIFACT_BUNDLE_MANIFEST_JSON,
            kind="public_demo_artifact_bundle",
        ),
        _artifact_entry(
            "public_demo_artifact_bundle_manifest_markdown",
            PUBLIC_DEMO_ARTIFACT_BUNDLE_MANIFEST_MARKDOWN,
            kind="public_demo_artifact_bundle",
        ),
        _artifact_entry(
            "public_demo_artifact_bundle_builder",
            PUBLIC_DEMO_ARTIFACT_BUNDLE_BUILDER,
            kind="public_demo_artifact_bundle",
        ),
        _artifact_entry("human_review_batches_manifest", HUMAN_REVIEW_BATCHES_MANIFEST, kind="human_review_batches"),
        _artifact_entry("human_review_batches_markdown", HUMAN_REVIEW_BATCHES_MARKDOWN, kind="human_review_batches"),
        _artifact_entry("human_review_batch_quickstart_smoke", HUMAN_REVIEW_BATCH_QUICKSTART_SMOKE, kind="human_review_batches"),
        _artifact_entry("human_review_batch_public_demo_p0", HUMAN_REVIEW_BATCH_PUBLIC_DEMO_P0, kind="human_review_batches"),
        _artifact_entry("human_review_batch_quality_sample", HUMAN_REVIEW_BATCH_QUALITY_SAMPLE, kind="human_review_batches"),
        _artifact_entry("human_review_batch_source_card_sample", HUMAN_REVIEW_BATCH_SOURCE_CARD_SAMPLE, kind="human_review_batches"),
        _artifact_entry("human_review_outcome_schema", HUMAN_REVIEW_OUTCOME_SCHEMA, kind="human_review_outcomes"),
        _artifact_entry("human_review_outcomes_template", HUMAN_REVIEW_OUTCOME_TEMPLATE, kind="human_review_outcomes"),
        _artifact_entry("human_review_outcome_summary", HUMAN_REVIEW_OUTCOME_SUMMARY, kind="human_review_outcomes"),
        _artifact_entry("human_review_outcome_markdown", HUMAN_REVIEW_OUTCOME_MARKDOWN, kind="human_review_outcomes"),
        _artifact_entry("human_review_batch_ingest_latest", HUMAN_REVIEW_BATCH_INGEST_LATEST, kind="human_review_outcomes"),
        _artifact_entry("human_review_batch_preflight_latest", HUMAN_REVIEW_BATCH_PREFLIGHT_LATEST, kind="human_review_outcomes"),
        _artifact_entry("human_review_batch_preflight_markdown", HUMAN_REVIEW_BATCH_PREFLIGHT_MARKDOWN, kind="human_review_outcomes"),
        _artifact_entry("human_review_batch_merge_helper", HUMAN_REVIEW_BATCH_MERGE_HELPER, kind="human_review_outcomes"),
        _artifact_entry("human_review_batch_ingest_helper", HUMAN_REVIEW_BATCH_INGEST_HELPER, kind="human_review_outcomes"),
        _artifact_entry("human_review_batch_preflight_helper", HUMAN_REVIEW_BATCH_PREFLIGHT_HELPER, kind="human_review_outcomes"),
        _artifact_entry("public_demo_acceptance_checklist_json", PUBLIC_DEMO_ACCEPTANCE_CHECKLIST_JSON, kind="human_review_outcomes"),
        _artifact_entry(
            "public_demo_acceptance_checklist_markdown",
            PUBLIC_DEMO_ACCEPTANCE_CHECKLIST_MARKDOWN,
            kind="human_review_outcomes",
        ),
        _artifact_entry(
            "public_demo_acceptance_checklist_builder",
            PUBLIC_DEMO_ACCEPTANCE_CHECKLIST_BUILDER,
            kind="human_review_outcomes",
        ),
        _artifact_entry("submission_answer_hygiene_audit_json", SUBMISSION_ANSWER_HYGIENE_AUDIT_JSON, kind="submission_answer_hygiene"),
        _artifact_entry("submission_answer_hygiene_audit_markdown", SUBMISSION_ANSWER_HYGIENE_AUDIT_MARKDOWN, kind="submission_answer_hygiene"),
        _artifact_entry("submission_answer_hygiene_high_risk_csv", SUBMISSION_ANSWER_HYGIENE_HIGH_RISK_CSV, kind="submission_answer_hygiene"),
        _artifact_entry("submission_answer_hygiene_audit_runner", SUBMISSION_ANSWER_HYGIENE_AUDIT_RUNNER, kind="submission_answer_hygiene"),
        _artifact_entry("aiagribench_leaderboard_request_packet_json", AIAGRIBENCH_LEADERBOARD_REQUEST_PACKET_JSON, kind="aiagribench_submission"),
        _artifact_entry(
            "aiagribench_leaderboard_request_packet_markdown",
            AIAGRIBENCH_LEADERBOARD_REQUEST_PACKET_MARKDOWN,
            kind="aiagribench_submission",
        ),
        _artifact_entry(
            "aiagribench_leaderboard_request_packet_builder",
            AIAGRIBENCH_LEADERBOARD_REQUEST_PACKET_BUILDER,
            kind="aiagribench_submission",
        ),
        _artifact_entry("aiagribench_submission_dry_run_packet_json", AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_JSON, kind="aiagribench_submission"),
        _artifact_entry(
            "aiagribench_submission_dry_run_packet_markdown",
            AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_MARKDOWN,
            kind="aiagribench_submission",
        ),
        _artifact_entry(
            "aiagribench_submission_dry_run_submit_safe_sample",
            AIAGRIBENCH_SUBMISSION_DRY_RUN_SUBMIT_SAFE_SAMPLE,
            kind="aiagribench_submission",
        ),
        _artifact_entry(
            "aiagribench_submission_dry_run_prompt_boundary_preflight",
            AIAGRIBENCH_SUBMISSION_DRY_RUN_PROMPT_BOUNDARY_PREFLIGHT,
            kind="aiagribench_submission",
        ),
        _artifact_entry("aiagribench_submission_dry_run_questions", AIAGRIBENCH_SUBMISSION_DRY_RUN_QUESTIONS, kind="aiagribench_submission"),
        _artifact_entry(
            "aiagribench_submission_dry_run_packet_builder",
            AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_BUILDER,
            kind="aiagribench_submission",
        ),
        _artifact_entry("report_visual_qa_current_pass", REPORT_VISUAL_QA_CURRENT_PASS, kind="report_visual_qa"),
        _artifact_entry("report_visual_qa_manifest", REPORT_VISUAL_QA_MANIFEST, kind="report_visual_qa"),
        _artifact_entry(
            "direct_semantic_review_jsonl",
            DIRECT_SEMANTIC_REVIEW_JSONL,
            kind="semantic_answer_review",
        ),
        _artifact_entry(
            "direct_semantic_review_markdown",
            DIRECT_SEMANTIC_REVIEW_MARKDOWN,
            kind="semantic_answer_review",
        ),
    ]
    if public_full_gap.get("report_path"):
        public_artifacts.append(_artifact_entry("public_full_gap_report", public_full_gap["report_path"], kind="public_shadow_result"))
    if public_full_gap.get("markdown_report_path"):
        public_artifacts.append(
            _artifact_entry("public_full_gap_markdown", public_full_gap["markdown_report_path"], kind="public_shadow_result")
        )
    if public_smoke_gap.get("report_path"):
        public_artifacts.append(_artifact_entry("public_smoke_gap_report", public_smoke_gap["report_path"], kind="public_shadow_result"))
    if public_smoke_gap.get("markdown_report_path"):
        public_artifacts.append(
            _artifact_entry("public_smoke_gap_markdown", public_smoke_gap["markdown_report_path"], kind="public_shadow_result")
        )
    if public_claim_stress_focus.get("report_path"):
        public_artifacts.append(
            _artifact_entry("public_claim_stress_focus_report", public_claim_stress_focus["report_path"], kind="public_shadow_result")
        )
    if public_claim_stress_focus.get("markdown_report_path"):
        public_artifacts.append(
            _artifact_entry(
                "public_claim_stress_focus_markdown",
                public_claim_stress_focus["markdown_report_path"],
                kind="public_shadow_result",
            )
        )
    if public_shadow_heldout_result.get("report_path"):
        public_artifacts.append(
            _artifact_entry("public_shadow_heldout_result", public_shadow_heldout_result["report_path"], kind="heldout_shadow_result")
        )
    if public_shadow_heldout_result.get("markdown_report_path"):
        public_artifacts.append(
            _artifact_entry(
                "public_shadow_heldout_markdown",
                public_shadow_heldout_result["markdown_report_path"],
                kind="heldout_shadow_result",
            )
        )

    corpus_entries = [_artifact_entry(f"corpus_{index:02d}", path, kind="rag_corpus") for index, path in enumerate(corpus_paths, start=1)]
    graph_entries = [_artifact_entry(f"graph_{index:02d}", path, kind="knowledge_graph") for index, path in enumerate(graph_paths, start=1)]
    config_artifacts = [
        _artifact_entry("model_config", model_config_path, kind="config"),
        _artifact_entry("rag_config", rag_config_path, kind="config"),
        _artifact_entry("submission_runner", AIAGRIBENCH_SUBMISSION_RUNNER, kind="runner"),
    ]

    all_corpus_present = all(entry.get("exists") for entry in corpus_entries)
    all_graphs_present = all(entry.get("exists") for entry in graph_entries)
    proxy_clean = bool(
        proxy_summary.get("available")
        and int(proxy_summary.get("under90_rows") or 0) == 0
        and int(proxy_summary.get("missing_required_flags") or 0) == 0
    )
    full_shadow_clean = bool(
        public_full_gap.get("available")
        and public_full_gap.get("is_current_to_manifest")
        and int(public_full_gap.get("under90_rows") or 0) == 0
        and int(public_full_gap.get("flagged_missing_required") or 0) == 0
    )
    smoke_shadow_clean = bool(
        public_smoke_gap.get("available")
        and int(public_smoke_gap.get("under90_rows") or 0) == 0
        and int(public_smoke_gap.get("flagged_missing_required") or 0) == 0
    )
    claim_stress_focus_clean = bool(
        public_claim_stress_focus.get("available")
        and public_claim_stress_focus.get("is_current_to_manifest")
        and int(public_claim_stress_focus.get("under90_rows") or 0) == 0
        and int(public_claim_stress_focus.get("flagged_missing_required") or 0) == 0
    )
    git = _git_head_snapshot()
    command = (
        "PYTHONPATH=src python scripts/run_aiagribench_submission.py "
        "--questions <official_aiagribench_questions.csv> "
        "--output-dir outputs/aiagribench_submission "
        "--mode agronomic_rag "
        "--model-config configs/model.yaml "
        "--rag-config configs/rag_final_mvp.yaml "
        "--answer-profile benchmark "
        f"--max-tokens {int(model_config.get('max_tokens') or 480)}"
    )
    heldout_quality_evidence = bool(public_shadow_heldout_result.get("is_quality_evidence"))
    heldout_result_kind = str(public_shadow_heldout_result.get("result_kind") or "missing")
    heldout_review_detail = (
        f"{public_shadow_heldout_result.get('samples') or 0}/{public_shadow_heldout.get('row_count') or 0} "
        "held-out public rows have a generated result. "
    )
    if heldout_quality_evidence:
        heldout_review_detail += (
            "Latest result is full_agentic transfer evidence; keep failures in human review until logged. "
            f"The held-out gap review packet covers {heldout_gap_review.get('row_count') or 0} weak rows "
            f"from {heldout_gap_review.get('csv_path') or 'heldout_public_shadow_gap_review.csv'}."
        )
    elif public_shadow_heldout_result.get("available"):
        heldout_review_detail += (
            f"Latest result kind is {heldout_result_kind}, which does not satisfy full_agentic quality evidence. "
            "Keep rows outside RAG/KG ingestion and gap-repair loops until batch review is complete."
        )
    else:
        heldout_review_detail += "Keep rows outside RAG/KG ingestion and gap-repair loops until batch review is complete."

    return {
        "schema_version": "open_agronomy_agent.aiagribench_freeze_manifest.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "target": "AI AgriBench official question-file rehearsal and submission",
        "status": "local_readiness_packet",
        "official_leaderboard_score": None,
        "score_warning": "Local proxy and public shadow numbers are not official AI AgriBench leaderboard results.",
        "git": git,
        "runner": {
            "path": _repo_relative(AIAGRIBENCH_SUBMISSION_RUNNER),
            "command_template": command,
            "official_response_file": "outputs/aiagribench_submission/aiagribench_submission_<run_id>.json",
            "submit_safe_files": [
                {
                    "path": "outputs/aiagribench_submission/aiagribench_submission_<run_id>.json",
                    "allowed_keys": ["qna_id", "answer"],
                    "contains_question_text": False,
                    "contains_trace_or_retrieval": False,
                    "review_before_send": True,
                }
            ],
            "audit_response_files": [
                "outputs/aiagribench_submission/aiagribench_responses_<run_id>.jsonl",
                "outputs/aiagribench_submission/aiagribench_responses_<run_id>.csv",
            ],
            "preflight_file": "outputs/aiagribench_submission/aiagribench_submission_preflight_<run_id>.json",
            "preflight_minimum_protocol_checks": [
                "duplicate_ids",
                "generated_qna_id_ids",
                "empty_answer_ids",
                "official_payload.submit_safe",
            ],
            "preflight_quality_warning_checks": [
                "short_answer_ids",
                "one_paragraph_answer_ids",
                "too_many_paragraph_answer_ids",
                "long_answer_ids",
                "citation_marker_answer_ids",
                "tool_trace_leakage_answer_ids",
                "checklist_style_answer_ids",
                "answer_scaffold_leakage_answer_ids",
                "generic_disclaimer_answer_ids",
                "evasive_answer_ids",
                "unsafe_certainty_answer_ids",
                "placeholder_answer_ids",
            ],
            "preflight_submission_ready_field": "submission_ready_without_manual_exception",
            "internal_trace_file": "outputs/aiagribench_submission/aiagribench_traces_<run_id>.jsonl",
            "internal_only_files": [
                {
                    "path": "outputs/aiagribench_submission/aiagribench_responses_<run_id>.jsonl",
                    "reason": "Contains official question text for internal audit.",
                },
                {
                    "path": "outputs/aiagribench_submission/aiagribench_responses_<run_id>.csv",
                    "reason": "Contains official question text for spreadsheet review.",
                },
                {
                    "path": "outputs/aiagribench_submission/aiagribench_traces_<run_id>.jsonl",
                    "reason": "Contains source rows, generation metadata, route/retrieval/tool traces, and timing.",
                },
                {
                    "path": "outputs/aiagribench_submission/aiagribench_submission_preflight_<run_id>.json",
                    "reason": "Contains run QA metadata and belongs in the internal audit packet.",
                },
            ],
            "submission_boundary": (
                "Submit the official JSON answer file with qna_id and answer only unless organizers request another "
                "format; keep question text, source rows, and trace files internal unless provenance is explicitly requested."
            ),
        },
        "model": {
            "model_id": model_config.get("model_id"),
            "serving_model_id": model_config.get("serving_model_id"),
            "assistant_model_id": model_config.get("assistant_model_id"),
            "max_tokens": int(model_config.get("max_tokens") or 480),
            "serving_max_tokens": model_config.get("serving_max_tokens"),
            "assistant_max_tokens": model_config.get("assistant_max_tokens"),
            "temperature": model_config.get("temperature"),
            "top_p": model_config.get("top_p"),
            "top_k": model_config.get("top_k"),
            "seed": model_config.get("seed"),
            "use_stream_generate": model_config.get("use_stream_generate"),
            "draft_model_id": model_config.get("draft_model_id"),
            "num_draft_tokens": model_config.get("num_draft_tokens"),
            "answer_profile": "benchmark",
        },
        "rag": {
            "config_path": _repo_relative(rag_config_path),
            "retrieval_top_k": retrieval.get("top_k"),
            "retrieval_min_score": retrieval.get("min_score"),
            "configured_corpus_paths": len(corpus_entries),
            "configured_graph_paths": len(graph_entries),
            "agent_runtime": (rag_config.get("agent_runtime") or {}).get("mode")
            if isinstance(rag_config.get("agent_runtime"), dict)
            else None,
            "agno_enabled": bool((rag_config.get("agent_runtime") or {}).get("agno_enabled"))
            if isinstance(rag_config.get("agent_runtime"), dict)
            else False,
        },
        "local_evidence": {
            "direct_semantic_review": {
                "available": direct_semantic_review.get("available"),
                "rows": direct_semantic_review.get("rows"),
                "semantic_mean": direct_semantic_review.get("semantic_mean"),
                "answer_disposition": direct_semantic_review.get("answer_disposition"),
                "generation_paths": direct_semantic_review.get("generation_paths"),
                "source_proxy_mean": direct_semantic_review.get("source_proxy_mean"),
                "human_agronomist_signoff": direct_semantic_review.get("human_agronomist_signoff"),
                "official_ai_agribench": False,
                "score_warning": direct_semantic_review.get("score_warning"),
            },
            "proxy": {
                "available": proxy_summary.get("available"),
                "run_id": proxy_summary.get("run_id"),
                "samples": proxy_summary.get("samples"),
                "mean_score": proxy_summary.get("mean_score"),
                "under90_rows": proxy_summary.get("under90_rows"),
                "missing_required_flags": proxy_summary.get("missing_required_flags"),
            },
            "public_coverage": {
                "available": public_coverage.get("available"),
                "total_items": public_coverage.get("total_items"),
                "core_items": public_coverage.get("core_items"),
                "expansion_items": public_coverage.get("expansion_items"),
                "official_ai_agribench": False,
            },
            "public_deep_coverage": {
                "available": public_deep_coverage.get("available"),
                "total_items": public_deep_coverage.get("total_items"),
                "base_total_items": public_deep_coverage.get("base_total_items"),
                "deep_added_items": public_deep_coverage.get("deep_added_items"),
                "deep_scenario_templates": public_deep_coverage.get("deep_scenario_templates"),
                "scored": public_deep_coverage.get("scored"),
                "official_ai_agribench": False,
                "smoke_readiness": {
                    "status": (public_deep_coverage.get("smoke_readiness") or {}).get("status"),
                    "suite_rows": (public_deep_coverage.get("smoke_readiness") or {}).get("suite_rows"),
                    "scored_answer_quality": (public_deep_coverage.get("smoke_readiness") or {}).get(
                        "scored_answer_quality"
                    ),
                    "mean_required_support_rate": (public_deep_coverage.get("smoke_readiness") or {}).get(
                        "mean_required_support_rate"
                    ),
                    "blockers": (public_deep_coverage.get("smoke_readiness") or {}).get("blockers") or [],
                },
            },
            "public_full_gap": {
                "available": public_full_gap.get("available"),
                "is_current_to_manifest": public_full_gap.get("is_current_to_manifest"),
                "samples": public_full_gap.get("samples"),
                "mean_score": public_full_gap.get("mean_score"),
                "under90_rows": public_full_gap.get("under90_rows"),
                "flagged_missing_required": public_full_gap.get("flagged_missing_required"),
            },
            "public_smoke_gap": {
                "available": public_smoke_gap.get("available"),
                "samples": public_smoke_gap.get("samples"),
                "mean_score": public_smoke_gap.get("mean_score"),
                "under90_rows": public_smoke_gap.get("under90_rows"),
                "flagged_missing_required": public_smoke_gap.get("flagged_missing_required"),
            },
            "public_claim_stress_focus": {
                "available": public_claim_stress_focus.get("available"),
                "is_current_to_manifest": public_claim_stress_focus.get("is_current_to_manifest"),
                "samples": public_claim_stress_focus.get("samples"),
                "mean_score": public_claim_stress_focus.get("mean_score"),
                "under90_rows": public_claim_stress_focus.get("under90_rows"),
                "flagged_missing_required": public_claim_stress_focus.get("flagged_missing_required"),
                "demo_quality_mean": public_claim_stress_focus.get("demo_quality_mean"),
                "demo_quality_under82_rows": public_claim_stress_focus.get("demo_quality_under82_rows"),
                "quality_risk_row_count": public_claim_stress_focus.get("quality_risk_row_count"),
                "high_proxy_quality_risk_count": public_claim_stress_focus.get("high_proxy_quality_risk_count"),
                "official_ai_agribench": False,
            },
            "public_demo_rehearsal": {
                "available": public_demo_rehearsal.get("available"),
                "prompt_count": public_demo_rehearsal.get("prompt_count"),
                "context_count": public_demo_rehearsal.get("context_count"),
                "adapter_lane_count": public_demo_rehearsal.get("adapter_lane_count"),
                "official_ai_agribench": False,
            },
            "public_shadow_heldout": {
                "available": public_shadow_heldout.get("available"),
                "row_count": public_shadow_heldout.get("row_count"),
                "context_count": public_shadow_heldout.get("context_count"),
                "topic_category_count": public_shadow_heldout.get("topic_category_count"),
                "excluded_from_gap_repair": (public_shadow_heldout.get("heldout_policy") or {}).get("excluded_from_gap_repair"),
                "official_ai_agribench": False,
            },
            "public_shadow_heldout_result": {
                "available": public_shadow_heldout_result.get("available"),
                "run_mode": public_shadow_heldout_result.get("run_mode"),
                "model_id": public_shadow_heldout_result.get("model_id"),
                "answer_profile": public_shadow_heldout_result.get("answer_profile"),
                "result_kind": public_shadow_heldout_result.get("result_kind"),
                "is_quality_evidence": public_shadow_heldout_result.get("is_quality_evidence"),
                "mock": public_shadow_heldout_result.get("mock"),
                "is_complete_to_manifest": public_shadow_heldout_result.get("is_complete_to_manifest"),
                "samples": public_shadow_heldout_result.get("samples"),
                "mean_score": public_shadow_heldout_result.get("mean_score"),
                "under90_rows": public_shadow_heldout_result.get("under90_rows"),
                "flagged_missing_required": public_shadow_heldout_result.get("flagged_missing_required"),
                "official_ai_agribench": False,
            },
            "heldout_gap_review": {
                "available": heldout_gap_review.get("available"),
                "row_count": heldout_gap_review.get("row_count"),
                "selected_mean_score": heldout_gap_review.get("selected_mean_score"),
                "selected_under90_rows": heldout_gap_review.get("selected_under90_rows"),
                "selected_missing_required_rows": heldout_gap_review.get("selected_missing_required_rows"),
                "csv_path": heldout_gap_review.get("csv_path"),
                "official_ai_agribench": False,
            },
            "human_review_queue": {
                "available": human_review_queue.get("available"),
                "queue_item_count": human_review_queue.get("queue_item_count"),
                "p0_items": (human_review_queue.get("by_priority") or {}).get("P0", 0),
                "p1_items": (human_review_queue.get("by_priority") or {}).get("P1", 0),
                "p2_items": (human_review_queue.get("by_priority") or {}).get("P2", 0),
                "official_ai_agribench": False,
            },
            "human_review_batches": {
                "available": human_review_batches.get("available"),
                "batch_count": human_review_batches.get("batch_count"),
                "p0_public_demo_rows": human_review_batches.get("p0_public_demo_rows"),
                "quality_sample_plus_p0_rows": human_review_batches.get("quality_sample_plus_p0_rows"),
                "quality_claim_review_floor": human_review_batches.get("quality_claim_review_floor"),
                "official_ai_agribench": False,
            },
            "human_smoke_preflight": {
                "available": human_smoke_preflight.get("available"),
                "preflight_passed": human_smoke_preflight.get("preflight_passed"),
                "row_count": human_smoke_preflight.get("row_count"),
                "passed_row_count": human_smoke_preflight.get("passed_row_count"),
                "error_count": human_smoke_preflight.get("error_count"),
                "warning_count": human_smoke_preflight.get("warning_count"),
                "human_review_replacement": human_smoke_preflight.get("human_review_replacement"),
                "official_ai_agribench": False,
            },
            "human_review_outcomes": {
                "available": human_review_outcomes.get("available"),
                "reviewed_count": human_review_outcomes.get("reviewed_count"),
                "unreviewed_count": human_review_outcomes.get("unreviewed_count"),
                "review_record_issue_count": human_review_outcomes.get("review_record_issue_count"),
                "blocking_issue_count": human_review_outcomes.get("blocking_issue_count"),
                "public_demo_gate": (human_review_outcomes.get("public_demo_gate") or {}).get("status"),
                "quality_claim_gate": (human_review_outcomes.get("quality_claim_gate") or {}).get("status"),
                "official_ai_agribench": False,
            },
            "submission_answer_hygiene": {
                "available": submission_answer_hygiene.get("available"),
                "row_count": submission_answer_hygiene.get("row_count"),
                "quality_warning_count": submission_answer_hygiene.get("quality_warning_count"),
                "quality_warning_rate": submission_answer_hygiene.get("quality_warning_rate"),
                "high_risk_warning_count": submission_answer_hygiene.get("high_risk_warning_count"),
                "high_risk_warning_rate": submission_answer_hygiene.get("high_risk_warning_rate"),
                "current_high_risk_warning_count": submission_answer_hygiene.get("current_high_risk_warning_count"),
                "current_high_risk_warning_rate": submission_answer_hygiene.get("current_high_risk_warning_rate"),
                "stale_high_risk_warning_count": submission_answer_hygiene.get("stale_high_risk_warning_count"),
                "stale_high_risk_warning_rate": submission_answer_hygiene.get("stale_high_risk_warning_rate"),
                "current_high_risk_artifacts": submission_answer_hygiene.get("current_high_risk_artifacts"),
                "stale_high_risk_artifacts": submission_answer_hygiene.get("stale_high_risk_artifacts"),
                "format_warning_count": submission_answer_hygiene.get("format_warning_count"),
                "format_warning_rate": submission_answer_hygiene.get("format_warning_rate"),
                "official_ai_agribench": False,
            },
            "aiagribench_submission_dry_run": {
                "available": aiagribench_submission_dry_run.get("available"),
                "row_count": aiagribench_submission_dry_run.get("row_count"),
                "dry_run_kind": aiagribench_submission_dry_run.get("dry_run_kind"),
                "mock": aiagribench_submission_dry_run.get("mock"),
                "official_payload_submit_safe": aiagribench_submission_dry_run.get("official_payload_submit_safe"),
                "minimum_protocol_passed": aiagribench_submission_dry_run.get("minimum_protocol_passed"),
                "quality_warning_passed": aiagribench_submission_dry_run.get("quality_warning_passed"),
                "submission_ready_without_manual_exception": aiagribench_submission_dry_run.get(
                    "submission_ready_without_manual_exception"
                ),
                "submit_safe_sample_path": aiagribench_submission_dry_run.get("submit_safe_sample_path"),
                "prompt_boundary_preflight_path": aiagribench_submission_dry_run.get("prompt_boundary_preflight_path"),
                "prompt_boundary_passed": aiagribench_submission_dry_run.get("prompt_boundary_passed"),
                "prompt_boundary_hit_count": aiagribench_submission_dry_run.get("prompt_boundary_hit_count"),
                "prompt_boundary_report_excludes_question_text": aiagribench_submission_dry_run.get(
                    "prompt_boundary_report_excludes_question_text"
                ),
                "official_ai_agribench": False,
            },
            "report_visual_qa": {
                "available": report_visual_qa.get("available"),
                "current_pass_path": report_visual_qa.get("current_pass_path"),
                "manifest_path": report_visual_qa.get("manifest_path"),
                "svg_preview_count": report_visual_qa.get("svg_preview_count"),
                "svg_contact_sheet_exists": report_visual_qa.get("svg_contact_sheet_exists"),
                "svg_contact_sheet_path": report_visual_qa.get("svg_contact_sheet_path"),
                "strict_svg_validation": report_visual_qa.get("strict_svg_validation"),
                "report_package_validation": report_visual_qa.get("report_package_validation"),
                "visual_gate_svg_html_current": report_visual_qa.get("visual_gate_svg_html_current"),
                "pdf_render_attempted": report_visual_qa.get("pdf_render_attempted"),
                "pdf_render_status": report_visual_qa.get("pdf_render_status"),
                "pdf_contact_sheet_exists": report_visual_qa.get("pdf_contact_sheet_exists"),
                "pdf_rerender_required": report_visual_qa.get("pdf_rerender_required"),
                "pdf_rerender_blocked_this_environment": report_visual_qa.get("pdf_rerender_blocked_this_environment"),
                "official_ai_agribench": False,
            },
        },
        "artifacts": [*config_artifacts, *latest_artifacts, *public_artifacts],
        "corpora": corpus_entries,
        "graphs": graph_entries,
        "checklist": [
            _check_item(
                "frozen_git_commit",
                "Freeze git commit",
                "pass" if git.get("commit") else "needs_review",
                git.get("commit") or "No git commit could be read from .git/HEAD.",
            ),
            _check_item(
                "model_config_hash",
                "Hash model configuration",
                "pass" if config_artifacts[0].get("sha256") else "fail",
                config_artifacts[0].get("sha256") or "Model configuration is missing.",
            ),
            _check_item(
                "rag_config_hash",
                "Hash RAG configuration",
                "pass" if config_artifacts[1].get("sha256") else "fail",
                config_artifacts[1].get("sha256") or "RAG configuration is missing.",
            ),
            _check_item(
                "corpus_inventory_present",
                "Verify configured corpora",
                "pass" if all_corpus_present else "fail",
                f"{sum(1 for entry in corpus_entries if entry.get('exists'))}/{len(corpus_entries)} configured corpora are present.",
            ),
            _check_item(
                "graph_inventory_present",
                "Verify configured graphs",
                "pass" if all_graphs_present else "fail",
                f"{sum(1 for entry in graph_entries if entry.get('exists'))}/{len(graph_entries)} configured graphs are present.",
            ),
            _check_item(
                "local_proxy_clean",
                "Clean 416-row local proxy",
                "pass" if proxy_clean else "needs_review",
                f"{proxy_summary.get('samples') or 0} rows; {proxy_summary.get('under90_rows') or 0} under-90; "
                f"{proxy_summary.get('missing_required_flags') or 0} missing-required flags.",
            ),
            _check_item(
                "direct_semantic_review",
                "Review answer quality semantically",
                "pass"
                if direct_semantic_review.get("available")
                and not (direct_semantic_review.get("answer_disposition") or {}).get("revise")
                and not (direct_semantic_review.get("answer_disposition") or {}).get("fail")
                else "needs_review",
                f"{direct_semantic_review.get('rows') or 0} repaired development rows at "
                f"{direct_semantic_review.get('semantic_mean') or 'n/a'} mean; "
                f"generation paths={direct_semantic_review.get('generation_paths') or {}}. "
                "This is direct AI desk review, not certified agronomist signoff or a held-out production estimate.",
            ),
            _check_item(
                "public_shadow_clean",
                "Clean current public shadow screen",
                "pass" if full_shadow_clean else "needs_review",
                f"{public_full_gap.get('samples') or 0}/{public_coverage.get('total_items') or 0} rows; "
                f"{public_full_gap.get('under90_rows') or 0} under-90; "
                f"{public_full_gap.get('flagged_missing_required') or 0} missing-required flags. "
                f"Current smoke: {public_smoke_gap.get('samples') or 0} rows at {public_smoke_gap.get('mean_score') or 'n/a'} mean, "
                f"{public_smoke_gap.get('under90_rows') or 0} under-90, "
                f"{public_smoke_gap.get('flagged_missing_required') or 0} missing-required flags"
                f"{' (clean)' if smoke_shadow_clean else ''}. Run the full current coverage suite when these counts do not match.",
            ),
            _check_item(
                "public_claim_stress_focus_clean",
                "Clean 80-row public claim-stress focus suite",
                "pass" if claim_stress_focus_clean else "needs_review",
                f"{public_claim_stress_focus.get('samples') or 0}/"
                f"{public_claim_stress_focus.get('coverage_total_items') or 0} rows; "
                f"{public_claim_stress_focus.get('mean_score') or 'n/a'} mean; "
                f"{public_claim_stress_focus.get('under90_rows') or 0} under-90; "
                f"{public_claim_stress_focus.get('flagged_missing_required') or 0} missing-required flags.",
            ),
            _check_item(
                "official_questions_pending",
                "Request official question file",
                "pending",
                "The official AI AgriBench question file is external and should not be added to tracked corpora.",
            ),
            _check_item(
                "official_response_protocol",
                "Use minimal qna_id/answer JSON response",
                "manual",
                "The runner writes aiagribench_submission_<run_id>.json with qna_id and answer only; review preflight warnings before sending.",
            ),
            _check_item(
                "public_submission_dry_run",
                "Run public no-edit submission dry run",
                "pass"
                if aiagribench_submission_dry_run.get("available")
                and aiagribench_submission_dry_run.get("minimum_protocol_passed")
                and aiagribench_submission_dry_run.get("official_payload_submit_safe")
                and aiagribench_submission_dry_run.get("prompt_boundary_passed")
                else "needs_review",
                (
                    f"{aiagribench_submission_dry_run.get('row_count') or 0} public surrogate rows; "
                    f"submit-safe={aiagribench_submission_dry_run.get('official_payload_submit_safe')}; "
                    f"prompt-boundary passed={aiagribench_submission_dry_run.get('prompt_boundary_passed')}; "
                    f"prompt-boundary hits={aiagribench_submission_dry_run.get('prompt_boundary_hit_count') or 0}; "
                    f"quality warnings pass={aiagribench_submission_dry_run.get('quality_warning_passed')}. "
                    "This proves runner/payload shape only; it is not official AI AgriBench quality evidence."
                ),
            ),
            _check_item(
                "private_prompt_boundary",
                "Keep official prompts out of training and public artifacts",
                "manual",
                "Run the official file only through the submission runner; do not copy hidden questions into docs, RAG, KG, eval suites, or screenshots.",
            ),
            _check_item(
                "conciseness_review",
                "Review 2-4 paragraph benchmark style",
                "manual",
                "Use the preflight file and sampled human review to catch one-paragraph, overlong, source-citation-heavy, UI-scaffold, generic-disclaimer, evasive, or unsafe-certainty answers before submission. "
                f"The local submission hygiene audit currently flags {submission_answer_hygiene.get('high_risk_warning_count') or 0} high-risk warning rows across {submission_answer_hygiene.get('row_count') or 0} audited local/public answers; "
                f"{submission_answer_hygiene.get('current_high_risk_warning_count') or 0} are current/post-remediation rows and {submission_answer_hygiene.get('stale_high_risk_warning_count') or 0} are stale rows from artifacts generated before the answer-safety cleanup; "
                f"start with {submission_answer_hygiene.get('high_risk_review_csv') or 'submission_answer_hygiene_high_risk_review.csv'}.",
            ),
            _check_item(
                "human_review_packet",
                "Human review before leaderboard claim",
                "manual" if human_review_queue.get("available") or public_demo_rehearsal.get("available") else "needs_review",
                (
                    f"Use the {human_review_queue.get('queue_item_count') or 0}-item human review queue when available; "
                    f"it includes {public_demo_rehearsal.get('prompt_count') or 0} public-demo rehearsal prompts across "
                    f"{public_demo_rehearsal.get('context_count') or 0} contexts. Start with the "
                    f"{human_review_batches.get('p0_public_demo_rows') or 0}-row P0 batch and "
                    f"{human_review_batches.get('quality_sample_plus_p0_rows') or 0} P0-plus-quality-sample rows "
                    "before making any public quality claim."
                ),
            ),
            _check_item(
                "heldout_public_shadow_review",
                "Run held-out public shadow review",
                "manual" if heldout_quality_evidence else "needs_review",
                heldout_review_detail,
            ),
            _check_item(
                "human_review_outcomes_logged",
                "Record human review outcomes",
                "manual" if int(human_review_outcomes.get("reviewed_count") or 0) > 0 else "needs_review",
                (
                    f"{human_review_outcomes.get('reviewed_count') or 0}/"
                    f"{human_review_outcomes.get('queue_item_count') or 0} queue rows have outcome records; "
                    f"{human_review_outcomes.get('review_record_issue_count') or 0} review record issues; "
                    f"public demo gate is {(human_review_outcomes.get('public_demo_gate') or {}).get('status') or 'unknown'}."
                ),
            ),
            _check_item(
                "report_visual_qa_pdf_rerender",
                "Rerender final PDF visual QA",
                "pass"
                if report_visual_qa.get("available") and not report_visual_qa.get("pdf_rerender_required")
                else ("manual" if report_visual_qa.get("available") else "needs_review"),
                (
                    f"{report_visual_qa.get('svg_preview_count') or 0} refreshed SVG previews are tracked in the current pass; "
                    f"svg contact sheet exists={bool(report_visual_qa.get('svg_contact_sheet_exists'))}; "
                    f"visual manifest reports pdf_render_status={report_visual_qa.get('pdf_render_status') or 'unknown'}. "
                    + (
                        "The PDF and PDF contact sheet still need a Chrome renderer rerun before the report PDF is shared publicly."
                        if report_visual_qa.get("pdf_rerender_required")
                        else "The PDF/contact-sheet render is current for public sharing."
                    )
                ),
            ),
        ],
        "data_boundaries": [
            "This manifest identifies local configs, corpora, graphs, and local eval artifacts only.",
            "The expanded public-domain suite is a shadow coverage screen, not official AI AgriBench.",
            "The deep public-domain coverage suite is a candidate next-run artifact; it is not a scored result until generated answers exist for that exact manifest.",
            "The held-out public shadow suite is for transfer review after freeze and should not be used for RAG repair loops.",
            "Held-out mock, partial, baseline, or metadata-unknown runs do not satisfy the full_agentic quality-evidence gate.",
            "The held-out gap review packet ranks weak transfer rows for human review only; it must not become prompt, training, RAG/KG, regex, or deterministic repair data.",
            "The human review queue is an assignment packet for public-demo, held-out transfer, and proxy-gap review; it is not a scored benchmark.",
            "The human review batch files are reviewer workflow slices and do not contain official hidden benchmark prompts.",
            "The human review outcome template is for local reviewer notes and must not contain official hidden benchmark prompts.",
            "The submission answer hygiene audit is a local style/leakage screen over public/proxy answer artifacts, not an official AI AgriBench score.",
            "The AI AgriBench submission dry run uses public surrogate questions and mock answers to prove payload shape; it is not official AI AgriBench quality evidence.",
            "The report visual-QA current pass validates refreshed HTML/SVG assets; PDF and contact-sheet artifacts must be rerendered before public PDF sharing.",
            "The full public shadow result is current only when its sample count matches the coverage manifest total.",
            "Official questions remain confidential input data and should stay outside tracked repositories and retrieval stores.",
            "The official submission file should contain qna_id and answer only unless organizers request trace provenance.",
        ],
    }


def _public_coverage_summary(path: Path = PUBLIC_DOMAIN_COVERAGE_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(path)
    if not manifest:
        return {
            "available": False,
            "suite": "Public-domain coverage screen",
            "message": f"No public-domain coverage manifest found at {path}",
            "official_ai_agribench": False,
        }
    domain_counts = manifest.get("domain_counts") if isinstance(manifest.get("domain_counts"), dict) else {}
    source_lanes = manifest.get("public_source_lanes") if isinstance(manifest.get("public_source_lanes"), dict) else {}
    aiagribench_categories = (
        manifest.get("aiagribench_topic_category_counts")
        if isinstance(manifest.get("aiagribench_topic_category_counts"), dict)
        else {}
    )
    return {
        "available": True,
        "suite": "Public-domain coverage screen",
        "suite_path": manifest.get("suite"),
        "manifest_path": str(path),
        "core_items": manifest.get("core_items"),
        "expansion_items": manifest.get("expansion_items"),
        "total_items": manifest.get("total_items"),
        "official_ai_agribench": bool(manifest.get("official_ai_agribench")),
        "domain_counts": domain_counts,
        "source_lane_counts": source_lanes,
        "aiagribench_topic_category_counts": aiagribench_categories,
        "contexts": manifest.get("contexts") or [],
        "source_boundaries": manifest.get("source_boundaries") or [],
        "score_warning": "Expanded public-domain coverage screen; not official AI AgriBench questions or score.",
    }


def _direct_semantic_review_summary(
    path: Path | None = None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    if path is None:
        path = BROAD_SEMANTIC_REVIEW_JSONL if BROAD_SEMANTIC_REVIEW_JSONL.is_file() else DIRECT_SEMANTIC_REVIEW_JSONL
    if run_dir is None:
        run_dir = BROAD_SEMANTIC_REVIEW_DIR if path == BROAD_SEMANTIC_REVIEW_JSONL else DIRECT_SEMANTIC_REVIEW_RUN
    rows = _read_jsonl_dicts(path)
    if not rows:
        return {
            "available": False,
            "suite": "Direct semantic answer review",
            "message": f"No direct semantic review found at {path}",
            "official_ai_agribench": False,
        }

    dispositions: dict[str, int] = {}
    generation_paths: dict[str, int] = {}
    dimension_values: dict[str, list[float]] = {}
    semantic_scores: list[float] = []
    for row in rows:
        disposition = str(row.get("answer_disposition") or "unknown")
        dispositions[disposition] = dispositions.get(disposition, 0) + 1
        generation_path = str(row.get("generation_path") or "unknown")
        generation_paths[generation_path] = generation_paths.get(generation_path, 0) + 1
        if _is_number(row.get("semantic_score_0_to_100")):
            semantic_scores.append(float(row["semantic_score_0_to_100"]))
        for name, value in (row.get("dimensions") or {}).items():
            if _is_number(value):
                dimension_values.setdefault(str(name), []).append(float(value) / 4 * 100)

    run_summary = _read_json(run_dir / "summary.json")
    run_rows = _read_output_rows(run_dir / "outputs.jsonl")
    elapsed = [float(row["elapsed_seconds"]) for row in run_rows if _is_number(row.get("elapsed_seconds"))]
    broad_review = path == BROAD_SEMANTIC_REVIEW_JSONL
    markdown_path = BROAD_SEMANTIC_REVIEW_MARKDOWN if broad_review else DIRECT_SEMANTIC_REVIEW_MARKDOWN
    lowest_rows = sorted(
        (
            {
                "eval_id": row.get("review_id"),
                "score": row.get("semantic_score_0_to_100"),
                "disposition": row.get("answer_disposition"),
                "crop": (row.get("eval_metadata") or {}).get("crop"),
                "jurisdiction": (row.get("eval_metadata") or {}).get("jurisdiction"),
                "material_errors": row.get("material_errors") or [],
            }
            for row in rows
            if _is_number(row.get("semantic_score_0_to_100"))
        ),
        key=lambda row: float(row.get("score") or 0),
    )[:6]
    return {
        "available": True,
        "suite": "Broad blinded semantic answer review" if broad_review else "Direct semantic answer review",
        "review_path": str(path),
        "markdown_path": str(markdown_path),
        "run_dir": str(run_dir),
        "rows": len(rows),
        "semantic_mean": round(sum(semantic_scores) / len(semantic_scores), 2) if semantic_scores else None,
        "answer_disposition": dispositions,
        "generation_paths": generation_paths,
        "dimensions_0_to_100": {
            name: round(sum(values) / len(values), 2)
            for name, values in sorted(dimension_values.items())
            if values
        },
        "source_proxy_mean": run_summary.get("proxy_score_mean", run_summary.get("mean_score")),
        "proxy_semantic_pearson": run_summary.get("proxy_semantic_pearson"),
        "mean_latency_seconds": round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
        "needs_source_validation": sum(bool(row.get("needs_source_validation")) for row in rows),
        "generation_path_quality": run_summary.get("by_generation_path") or {},
        "by_source": run_summary.get("by_source") or {},
        "by_question_disposition": run_summary.get("by_question_disposition") or {},
        "by_task_family": run_summary.get("by_task_family") or {},
        "by_crop": run_summary.get("by_crop") or {},
        "by_jurisdiction": run_summary.get("by_jurisdiction") or {},
        "lowest_rows": lowest_rows,
        "source_row_count": run_summary.get("source_row_count"),
        "skipped_without_answer": run_summary.get("skipped_without_answer"),
        "primary_quality_signal": "blinded_semantic_answer_judgment",
        "deterministic_signal_role": "diagnostic_only",
        "composite_score": None,
        "official_ai_agribench": False,
        "human_agronomist_signoff": False,
        "score_warning": (
            "Blinded row-level AI semantic review of a failure-enriched review queue. Use source strata and the "
            "held-out subset for diagnosis; the aggregate is not an overall production estimate, certified "
            "agronomist signoff, or an official AI AgriBench score."
            if broad_review
            else "Direct AI semantic review of a repaired development suite; primary local answer-quality evidence, "
            "but not a held-out production estimate, certified agronomist signoff, or official AI AgriBench score."
        ),
    }


def _canadian_semantic_review_summary(root: Path = CANADIAN_SEMANTIC_REVIEW_ROOT) -> dict[str, Any]:
    summary_paths = sorted(
        root.glob("*/codex_semantic_judge/summary.json"),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    if not summary_paths:
        return {
            "available": False,
            "suite": "Canadian semantic reserve",
            "message": f"No Canadian semantic review found under {root}",
            "official_ai_agribench": False,
        }

    summary_path = summary_paths[0]
    judge_dir = summary_path.parent
    run_dir = judge_dir.parent
    summary = _read_json(summary_path)
    judgments = _read_jsonl_dicts(judge_dir / "judgments.jsonl")
    run_rows = _read_output_rows(run_dir / "outputs.jsonl")
    elapsed = [float(row["elapsed_seconds"]) for row in run_rows if _is_number(row.get("elapsed_seconds"))]
    lowest_rows = sorted(
        (
            {
                "eval_id": row.get("review_id"),
                "score": row.get("semantic_score_0_to_100"),
                "disposition": row.get("answer_disposition"),
                "crop": (row.get("eval_metadata") or {}).get("crop"),
                "jurisdiction": (row.get("eval_metadata") or {}).get("jurisdiction"),
                "material_errors": row.get("material_errors") or [],
            }
            for row in judgments
        ),
        key=lambda row: float(row.get("score") or 0),
    )[:6]
    return {
        "available": True,
        "suite": "Canadian semantic reserve",
        "review_path": str(judge_dir / "judgments.jsonl"),
        "markdown_path": str(judge_dir / "summary.md"),
        "run_dir": str(run_dir),
        "rows": summary.get("row_count"),
        "semantic_mean": summary.get("semantic_score_mean"),
        "answer_disposition": summary.get("answer_disposition") or {},
        "generation_paths": {
            path: int(payload.get("rows") or 0)
            for path, payload in (summary.get("by_generation_path") or {}).items()
            if isinstance(payload, dict)
        },
        "generation_path_quality": summary.get("by_generation_path") or {},
        "dimensions_0_to_100": summary.get("dimensions_0_to_100") or {},
        "source_proxy_mean": summary.get("proxy_score_mean"),
        "proxy_semantic_pearson": summary.get("proxy_semantic_pearson"),
        "mean_latency_seconds": round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
        "needs_source_validation": summary.get("needs_source_validation"),
        "by_task_family": summary.get("by_task_family") or {},
        "by_crop": summary.get("by_crop") or {},
        "by_jurisdiction": summary.get("by_jurisdiction") or {},
        "lowest_rows": lowest_rows,
        "primary_quality_signal": summary.get("primary_quality_signal"),
        "deterministic_signal_role": summary.get("deterministic_signal_role"),
        "composite_score": summary.get("composite_score"),
        "official_ai_agribench": False,
        "human_agronomist_signoff": False,
        "score_warning": (
            "Blinded AI semantic review of a frozen Canadian reserve; primary local answer-quality evidence, "
            "not certified agronomist signoff or an official AI AgriBench score."
        ),
    }


def _public_deep_coverage_summary(path: Path = PUBLIC_DOMAIN_DEEP_COVERAGE_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(path)
    if not manifest:
        return {
            "available": False,
            "suite": "Deep public-domain coverage candidate",
            "message": f"No deep public-domain coverage manifest found at {path}",
            "official_ai_agribench": False,
            "scored": False,
        }
    smoke_readiness = _public_deep_smoke_readiness_summary()
    domain_counts = manifest.get("domain_counts") if isinstance(manifest.get("domain_counts"), dict) else {}
    deep_domain_counts = manifest.get("deep_domain_counts") if isinstance(manifest.get("deep_domain_counts"), dict) else {}
    source_lanes = manifest.get("public_source_lanes") if isinstance(manifest.get("public_source_lanes"), dict) else {}
    deep_source_lanes = manifest.get("deep_public_source_lanes") if isinstance(manifest.get("deep_public_source_lanes"), dict) else {}
    aiagribench_categories = (
        manifest.get("aiagribench_topic_category_counts")
        if isinstance(manifest.get("aiagribench_topic_category_counts"), dict)
        else {}
    )
    return {
        "available": True,
        "suite": "Deep public-domain coverage candidate",
        "suite_path": manifest.get("suite"),
        "manifest_path": str(path),
        "schema_version": manifest.get("schema_version"),
        "base_total_items": manifest.get("base_total_items"),
        "base_core_items": manifest.get("base_core_items"),
        "base_expansion_items": manifest.get("base_expansion_items"),
        "deep_context_extension_items": manifest.get("deep_context_extension_items"),
        "deep_scenario_items": manifest.get("deep_scenario_items"),
        "deep_added_items": manifest.get("deep_added_items"),
        "total_items": manifest.get("total_items"),
        "deep_scenario_templates": manifest.get("deep_scenario_templates"),
        "total_scenario_templates": manifest.get("total_scenario_templates"),
        "deep_contexts_per_scenario": manifest.get("deep_contexts_per_scenario"),
        "official_ai_agribench": bool(manifest.get("official_ai_agribench")),
        "scored": bool(manifest.get("scored")),
        "domain_counts": domain_counts,
        "deep_domain_counts": deep_domain_counts,
        "source_lane_counts": source_lanes,
        "deep_source_lane_counts": deep_source_lanes,
        "aiagribench_topic_category_counts": aiagribench_categories,
        "new_guard_tool_counts": manifest.get("new_guard_tool_counts") or {},
        "expected_public_adapter_counts": manifest.get("expected_public_adapter_counts") or {},
        "coverage_axes": manifest.get("coverage_axes") or [],
        "smoke_readiness": smoke_readiness,
        "source_boundaries": manifest.get("source_boundaries") or [],
        "score_warning": (
            "Unscored deep public-domain coverage candidate; deep-smoke readiness reports retrieval/tool context "
            "only until a completed generation run exists. Not official AI AgriBench questions or score."
        ),
    }


def _public_deep_smoke_readiness_summary(path: Path = PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_JSON) -> dict[str, Any]:
    payload = _read_json(path)
    if not payload:
        return {
            "available": False,
            "suite": "Public-domain deep coverage smoke readiness",
            "official_ai_agribench": False,
            "scored_answer_quality": False,
            "message": f"No deep-smoke readiness packet found at {path}",
        }
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    generation = payload.get("generation") if isinstance(payload.get("generation"), dict) else {}
    latest_attempt = generation.get("latest_attempt") if isinstance(generation.get("latest_attempt"), dict) else {}
    return {
        "available": True,
        "suite": "Public-domain deep coverage smoke readiness",
        "path": str(path),
        "markdown_path": str(PUBLIC_DOMAIN_DEEP_SMOKE_READINESS_MARKDOWN),
        "status": payload.get("status"),
        "suite_rows": payload.get("suite_rows"),
        "official_ai_agribench": bool(payload.get("official_ai_agribench")),
        "scored_answer_quality": bool(payload.get("scored_answer_quality")),
        "quality_claim_ready": bool(payload.get("quality_claim_ready")),
        "mean_required_support_rate": diagnostics.get("mean_required_support_rate"),
        "mean_source_diversity": diagnostics.get("mean_source_diversity"),
        "retrieval_context_ready": bool(diagnostics.get("retrieval_context_ready")),
        "latest_completed_generation": generation.get("latest_completed_run"),
        "latest_incomplete_generation": generation.get("latest_incomplete_run"),
        "latest_gpu_attempt": latest_attempt if latest_attempt.get("available") else None,
        "blockers": payload.get("blockers") or [],
        "low_domains": (diagnostics.get("low_domains") or [])[:6],
        "low_source_lanes": (diagnostics.get("low_source_lanes") or [])[:6],
        "under_routed_tools": [
            row
            for row in diagnostics.get("tool_route_recall") or []
            if float(row.get("route_recall") or 0.0) < 0.75
        ][:6],
        "run_command": generation.get("run_command"),
        "score_warning": "Deep smoke readiness is local diagnostic context, not a scored answer-quality claim.",
    }


def _public_demo_rehearsal_summary(path: Path = PUBLIC_DEMO_REHEARSAL_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(path)
    if not manifest:
        return {
            "available": False,
            "suite": "Public-demo human rehearsal prompts",
            "message": f"No public-demo rehearsal manifest found at {path}",
            "official_ai_agribench": False,
        }
    return {
        "available": True,
        "suite": "Public-demo human rehearsal prompts",
        "suite_path": manifest.get("suite"),
        "manifest_path": str(path),
        "markdown_path": manifest.get("markdown_packet") or str(PUBLIC_DEMO_REHEARSAL_MARKDOWN),
        "schema_version": manifest.get("schema_version"),
        "prompt_count": manifest.get("prompt_count"),
        "context_count": manifest.get("context_count"),
        "adapter_lane_count": manifest.get("adapter_lane_count"),
        "contexts": manifest.get("contexts") or {},
        "adapter_counts": manifest.get("adapter_counts") or {},
        "workflow_counts": manifest.get("workflow_counts") or {},
        "public_source_lanes": manifest.get("public_source_lanes") or {},
        "regional_matrix_artifact": manifest.get("regional_matrix_artifact"),
        "source_boundaries": manifest.get("source_boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Human public-demo rehearsal prompts; not official AI AgriBench questions or score.",
    }


def _public_claim_adapter_context_summary(path: Path = PUBLIC_CLAIM_ADAPTER_CONTEXT_PACKET) -> dict[str, Any]:
    packet = _read_json(path)
    if not packet:
        return {
            "available": False,
            "suite": "Public claim-stress adapter-context packet",
            "message": f"No public claim adapter-context packet found at {path}",
            "official_ai_agribench": False,
        }
    return {
        "available": True,
        "suite": "Public claim-stress adapter-context packet",
        "packet_path": str(path),
        "markdown_path": str(PUBLIC_CLAIM_ADAPTER_CONTEXT_MARKDOWN),
        "schema_version": packet.get("schema_version"),
        "mode": packet.get("mode"),
        "row_count": packet.get("row_count"),
        "adapter_mention_count": packet.get("adapter_mention_count"),
        "offline_fixture_pass_count": packet.get("offline_fixture_pass_count"),
        "not_executable_count": packet.get("not_executable_count"),
        "canada_source_lane_planned_count": packet.get("canada_source_lane_planned_count"),
        "canada_source_lane_needed_count": packet.get("canada_source_lane_needed_count"),
        "fully_executable_row_count": packet.get("fully_executable_row_count"),
        "partially_executable_row_count": packet.get("partially_executable_row_count"),
        "unsupported_row_count": packet.get("unsupported_row_count"),
        "status_counts": packet.get("status_counts") or {},
        "adapter_status_counts": packet.get("adapter_status_counts") or {},
        "boundaries": packet.get("boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Adapter-context packet maps representative fixture coverage; it is not live provider uptime or an official benchmark score.",
    }


def _public_shadow_heldout_summary(path: Path = PUBLIC_SHADOW_HELDOUT_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(path)
    if not manifest:
        return {
            "available": False,
            "suite": "Held-out public shadow set",
            "message": f"No held-out public shadow manifest found at {path}",
            "official_ai_agribench": False,
        }
    return {
        "available": True,
        "suite": "Held-out public shadow set",
        "suite_path": manifest.get("suite"),
        "manifest_path": str(path),
        "markdown_path": manifest.get("markdown_packet") or str(PUBLIC_SHADOW_HELDOUT_MARKDOWN),
        "schema_version": manifest.get("schema_version"),
        "row_count": manifest.get("row_count"),
        "context_count": manifest.get("context_count"),
        "topic_category_count": manifest.get("topic_category_count"),
        "domain_count": manifest.get("domain_count"),
        "source_lane_count": manifest.get("source_lane_count"),
        "source_family_count": manifest.get("source_family_count"),
        "contexts": manifest.get("contexts") or {},
        "domain_counts": manifest.get("domain_counts") or {},
        "aiagribench_topic_category_counts": manifest.get("aiagribench_topic_category_counts") or {},
        "public_source_lanes": manifest.get("public_source_lanes") or {},
        "source_family_counts": manifest.get("source_family_counts") or {},
        "expected_tool_counts": manifest.get("expected_tool_counts") or {},
        "heldout_policy": manifest.get("heldout_policy") or {},
        "source_boundaries": manifest.get("source_boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Held-out public-domain shadow set for transfer review; not official AI AgriBench questions or score.",
    }


def public_shadow_heldout_packet(
    *,
    manifest_path: Path = PUBLIC_SHADOW_HELDOUT_MANIFEST,
    suite_path: Path = PUBLIC_SHADOW_HELDOUT_SUITE,
    limit: int | None = None,
) -> dict[str, Any]:
    summary = _public_shadow_heldout_summary(manifest_path)
    if not summary.get("available"):
        return {
            **summary,
            "rows": [],
            "row_count_returned": 0,
        }
    rows = _read_jsonl_dicts(suite_path)
    if limit is not None:
        limit = max(0, min(int(limit), 200))
        rows = rows[:limit]
    return {
        **summary,
        "suite_path": str(suite_path),
        "row_count_returned": len(rows),
        "rows": rows,
        "boundary": (
            "Held-out public shadow rows are for post-freeze transfer review and claim calibration. "
            "They are not official AI AgriBench questions, scored leaderboard rows, training data, or RAG repair targets."
        ),
    }


def public_demo_rehearsal_packet(
    *,
    manifest_path: Path = PUBLIC_DEMO_REHEARSAL_MANIFEST,
    suite_path: Path = PUBLIC_DEMO_REHEARSAL_SUITE,
    limit: int | None = None,
) -> dict[str, Any]:
    summary = _public_demo_rehearsal_summary(manifest_path)
    if not summary.get("available"):
        return {
            **summary,
            "prompts": [],
            "prompt_count_returned": 0,
        }
    prompts = _read_jsonl_dicts(suite_path)
    if limit is not None:
        limit = max(0, min(int(limit), 200))
        prompts = prompts[:limit]
    return {
        **summary,
        "suite_path": str(suite_path),
        "prompt_count_returned": len(prompts),
        "prompts": prompts,
        "boundary": (
            "Public-demo rehearsal prompts are for human app testing and source-card review. "
            "They are not official AI AgriBench questions, scored benchmark rows, or training data."
        ),
    }


def human_review_queue_packet(
    *,
    manifest_path: Path = HUMAN_REVIEW_QUEUE_MANIFEST,
    queue_path: Path = HUMAN_REVIEW_QUEUE_JSONL,
    limit: int | None = None,
) -> dict[str, Any]:
    summary = _human_review_queue_summary(manifest_path)
    if not summary.get("available"):
        return {
            **summary,
            "items": [],
            "item_count_returned": 0,
        }
    items = _read_jsonl_dicts(queue_path)
    if limit is not None:
        limit = max(0, min(int(limit), 200))
        items = items[:limit]
    return {
        **summary,
        "queue_path": str(queue_path),
        "item_count_returned": len(items),
        "items": items,
        "boundary": (
            "Human review queue items are assignments for app testing, held-out transfer review, and proxy-gap triage. "
            "They are not official AI AgriBench questions, scored benchmark rows, training data, or automatic repair targets."
        ),
    }


def human_review_outcome_summary(path: Path = HUMAN_REVIEW_OUTCOME_SUMMARY) -> dict[str, Any]:
    summary = _read_json(path)
    latest_ingest = _read_json(HUMAN_REVIEW_BATCH_INGEST_LATEST)
    latest_preflight = _read_json(HUMAN_REVIEW_BATCH_PREFLIGHT_LATEST)
    if not summary:
        return {
            "available": False,
            "suite": "Human review outcomes",
            "message": f"No human review outcome summary found at {path}",
            "official_ai_agribench": False,
        }
    return {
        "available": True,
        "suite": "Human review outcomes",
        "summary_path": str(path),
        "schema_path": str(HUMAN_REVIEW_OUTCOME_SCHEMA),
        "template_path": str(HUMAN_REVIEW_OUTCOME_TEMPLATE),
        "markdown_path": str(HUMAN_REVIEW_OUTCOME_MARKDOWN),
        "schema_version": summary.get("schema_version"),
        "queue_item_count": summary.get("queue_item_count"),
        "outcome_row_count": summary.get("outcome_row_count"),
        "reviewed_count": summary.get("reviewed_count"),
        "unreviewed_count": summary.get("unreviewed_count"),
        "status_counts": summary.get("status_counts") or {},
        "severity_counts": summary.get("severity_counts") or {},
        "priority_counts": summary.get("priority_counts") or {},
        "reviewed_by_priority": summary.get("reviewed_by_priority") or {},
        "p0_total": summary.get("p0_total"),
        "p0_reviewed": summary.get("p0_reviewed"),
        "p0_unreviewed": summary.get("p0_unreviewed"),
        "review_record_issue_count": summary.get("review_record_issue_count"),
        "p0_review_record_issue_count": summary.get("p0_review_record_issue_count"),
        "review_record_issues": summary.get("review_record_issues") or [],
        "blocking_issue_count": summary.get("blocking_issue_count"),
        "release_blocking_count": summary.get("release_blocking_count"),
        "demo_blocking_count": summary.get("demo_blocking_count"),
        "public_demo_gate": summary.get("public_demo_gate") or {},
        "quality_claim_gate": summary.get("quality_claim_gate") or {},
        "review_batch_count": summary.get("review_batch_count"),
        "review_batches": summary.get("review_batches") or [],
        "latest_ingest": _compact_human_review_ingest(latest_ingest),
        "latest_preflight": _compact_human_review_preflight(latest_preflight),
        "next_actions": summary.get("next_actions") or [],
        "top_blockers": summary.get("top_blockers") or [],
        "source_boundaries": summary.get("source_boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Human review outcomes are local app-testing records; not official AI AgriBench results.",
    }


def _compact_human_review_ingest(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return None
    merge = payload.get("merge") if isinstance(payload.get("merge"), dict) else {}
    human_review = payload.get("human_review") if isinstance(payload.get("human_review"), dict) else {}
    readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
    return {
        "path": _repo_relative(HUMAN_REVIEW_BATCH_INGEST_LATEST),
        "schema_version": payload.get("schema_version"),
        "generated_at": payload.get("generated_at"),
        "batch_csvs": payload.get("batch_csvs") or [],
        "incoming_rows": merge.get("incoming_rows"),
        "incoming_reviewed_rows": merge.get("incoming_reviewed_rows"),
        "merged_rows": merge.get("merged_rows"),
        "skipped_unreviewed_rows": merge.get("skipped_unreviewed_rows"),
        "skipped_existing_reviewed_rows": merge.get("skipped_existing_reviewed_rows"),
        "reviewed_count": human_review.get("reviewed_count"),
        "public_demo_gate": human_review.get("public_demo_gate"),
        "quality_claim_gate": human_review.get("quality_claim_gate"),
        "readiness_automated_gate_passed": readiness.get("automated_gate_passed"),
        "readiness_public_demo_ready": readiness.get("public_demo_ready"),
    }


def _compact_human_review_preflight(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload:
        return None
    merge = payload.get("merge") if isinstance(payload.get("merge"), dict) else {}
    human_review = payload.get("projected_human_review") if isinstance(payload.get("projected_human_review"), dict) else {}
    return {
        "path": _repo_relative(HUMAN_REVIEW_BATCH_PREFLIGHT_LATEST),
        "markdown_path": _repo_relative(HUMAN_REVIEW_BATCH_PREFLIGHT_MARKDOWN),
        "schema_version": payload.get("schema_version"),
        "generated_at": payload.get("generated_at"),
        "status": payload.get("status"),
        "ready_to_ingest": payload.get("ready_to_ingest"),
        "batch_csvs": payload.get("batch_csvs") or [],
        "incoming_rows": merge.get("incoming_rows"),
        "incoming_reviewed_rows": merge.get("incoming_reviewed_rows"),
        "merged_rows": merge.get("merged_rows"),
        "skipped_unreviewed_rows": merge.get("skipped_unreviewed_rows"),
        "skipped_existing_reviewed_rows": merge.get("skipped_existing_reviewed_rows"),
        "reviewed_count_after_merge": human_review.get("reviewed_count"),
        "review_record_issue_count_after_merge": human_review.get("review_record_issue_count"),
        "public_demo_gate_after_merge": human_review.get("public_demo_gate"),
        "quality_claim_gate_after_merge": human_review.get("quality_claim_gate"),
        "warning_count": len(payload.get("warnings") or []),
        "error_count": len(payload.get("errors") or []),
    }


def _submission_answer_hygiene_summary(path: Path = SUBMISSION_ANSWER_HYGIENE_AUDIT_JSON) -> dict[str, Any]:
    audit = _read_json(path)
    if not audit:
        return {
            "available": False,
            "suite": "Submission answer hygiene audit",
            "message": f"No submission answer hygiene audit found at {path}",
            "official_ai_agribench": False,
        }
    return {
        "available": True,
        "suite": "Submission answer hygiene audit",
        "audit_path": str(path),
        "markdown_path": str(SUBMISSION_ANSWER_HYGIENE_AUDIT_MARKDOWN),
        "high_risk_csv_path": str(SUBMISSION_ANSWER_HYGIENE_HIGH_RISK_CSV),
        "schema_version": audit.get("schema_version"),
        "artifact_count": audit.get("artifact_count"),
        "row_count": audit.get("row_count"),
        "quality_warning_count": audit.get("quality_warning_count"),
        "quality_warning_rate": audit.get("quality_warning_rate"),
        "high_risk_warning_count": audit.get("high_risk_warning_count"),
        "high_risk_warning_rate": audit.get("high_risk_warning_rate"),
        "current_high_risk_warning_count": audit.get("current_high_risk_warning_count"),
        "current_high_risk_warning_rate": audit.get("current_high_risk_warning_rate"),
        "stale_high_risk_warning_count": audit.get("stale_high_risk_warning_count"),
        "stale_high_risk_warning_rate": audit.get("stale_high_risk_warning_rate"),
        "current_high_risk_artifacts": audit.get("current_high_risk_artifacts") or [],
        "stale_high_risk_artifacts": audit.get("stale_high_risk_artifacts") or [],
        "high_risk_review_row_count": audit.get("high_risk_review_row_count"),
        "high_risk_review_csv": audit.get("high_risk_review_csv"),
        "high_risk_review_rows": audit.get("high_risk_review_rows") or [],
        "format_warning_count": audit.get("format_warning_count"),
        "format_warning_rate": audit.get("format_warning_rate"),
        "quality_warning_fields": audit.get("quality_warning_fields") or [],
        "high_risk_warning_fields": audit.get("high_risk_warning_fields") or [],
        "artifacts": audit.get("artifacts") or [],
        "next_actions": audit.get("next_actions") or [],
        "official_ai_agribench": False,
        "score_warning": "Local official-style answer hygiene screen; not an official AI AgriBench score.",
    }


def _aiagribench_submission_dry_run_summary(path: Path = AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_JSON) -> dict[str, Any]:
    packet = _read_json(path)
    if not packet:
        return {
            "available": False,
            "suite": "AI AgriBench submission dry run",
            "message": f"No AI AgriBench submission dry-run packet found at {path}",
            "packet_path": str(path),
            "markdown_path": str(AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_MARKDOWN),
            "submit_safe_sample_path": str(AIAGRIBENCH_SUBMISSION_DRY_RUN_SUBMIT_SAFE_SAMPLE),
            "prompt_boundary_preflight_path": str(AIAGRIBENCH_SUBMISSION_DRY_RUN_PROMPT_BOUNDARY_PREFLIGHT),
            "official_ai_agribench": False,
        }
    gates = packet.get("gates") if isinstance(packet.get("gates"), dict) else {}
    preflight = packet.get("preflight") if isinstance(packet.get("preflight"), dict) else {}
    submit_safe_payload = packet.get("submit_safe_payload") if isinstance(packet.get("submit_safe_payload"), dict) else {}
    official_like_input = packet.get("official_like_input") if isinstance(packet.get("official_like_input"), dict) else {}
    prompt_boundary = packet.get("prompt_boundary") if isinstance(packet.get("prompt_boundary"), dict) else {}
    return {
        "available": True,
        "suite": "AI AgriBench submission dry run",
        "packet_path": str(path),
        "markdown_path": str(AIAGRIBENCH_SUBMISSION_DRY_RUN_PACKET_MARKDOWN),
        "submit_safe_sample_path": str(AIAGRIBENCH_SUBMISSION_DRY_RUN_SUBMIT_SAFE_SAMPLE),
        "prompt_boundary_preflight_path": str(AIAGRIBENCH_SUBMISSION_DRY_RUN_PROMPT_BOUNDARY_PREFLIGHT),
        "question_fixture_path": str(AIAGRIBENCH_SUBMISSION_DRY_RUN_QUESTIONS),
        "schema_version": packet.get("schema_version"),
        "generated_at": packet.get("generated_at"),
        "dry_run_kind": packet.get("dry_run_kind"),
        "row_count": packet.get("row_count"),
        "mock": bool(packet.get("mock")),
        "mode": packet.get("mode"),
        "answer_profile": packet.get("answer_profile"),
        "runner_manifest": packet.get("runner_manifest"),
        "official_like_input_has_official_questions": official_like_input.get("contains_official_questions"),
        "submit_safe_sample_row_count": submit_safe_payload.get("row_count"),
        "submit_safe_allowed_keys": submit_safe_payload.get("allowed_keys") or [],
        "submit_safe_contains_question_text": submit_safe_payload.get("contains_question_text"),
        "prompt_boundary_passed": prompt_boundary.get("passed"),
        "prompt_boundary_hit_count": prompt_boundary.get("hit_count"),
        "prompt_boundary_report_excludes_question_text": prompt_boundary.get("question_text_in_report") is False,
        "official_payload_submit_safe": preflight.get("official_payload_submit_safe"),
        "minimum_protocol_passed": gates.get("minimum_protocol_passed"),
        "quality_warning_passed": gates.get("quality_warning_passed"),
        "submission_ready_without_manual_exception": gates.get("submission_ready_without_manual_exception"),
        "quality_warning_count": preflight.get("quality_warning_count"),
        "quality_warning_counts": preflight.get("quality_warning_counts") or {},
        "next_actions": packet.get("next_actions") or [],
        "boundaries": packet.get("boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Public surrogate mock dry run; not official AI AgriBench and not answer-quality evidence.",
    }


def _report_visual_qa_summary(path: Path = REPORT_VISUAL_QA_CURRENT_PASS) -> dict[str, Any]:
    visual_qa_path = repo_path(path)
    manifest_path = repo_path(REPORT_VISUAL_QA_MANIFEST)
    manifest = _read_json(manifest_path)
    previews_dir = repo_path(REPORT_VISUAL_QA_SVG_PREVIEWS_DIR)
    preview_count_from_manifest = ((manifest.get("svg_previews") or {}).get("preview_count") if manifest else None)
    svg_preview_count = (
        int(preview_count_from_manifest)
        if isinstance(preview_count_from_manifest, int)
        else len(list(previews_dir.glob("*.png")))
        if previews_dir.is_dir()
        else 0
    )
    svg_contact_sheet = repo_path(REPORT_VISUAL_QA_SVG_CONTACT_SHEET)
    pdf_contact_sheet = repo_path(REPORT_VISUAL_QA_PDF_CONTACT_SHEET)
    pdf_render = manifest.get("pdf_render") if isinstance(manifest.get("pdf_render"), dict) else {}
    visual_gate = manifest.get("visual_gate") if isinstance(manifest.get("visual_gate"), dict) else {}
    validation = manifest.get("report_package_validation") if isinstance(manifest.get("report_package_validation"), dict) else {}
    try:
        note = visual_qa_path.read_text(encoding="utf-8")
    except OSError:
        note = ""
    note_available = bool(note)
    manifest_available = bool(manifest)
    pdf_required = visual_gate.get("pdf_rerender_required") if isinstance(visual_gate.get("pdf_rerender_required"), bool) else True
    package_passed = validation.get("gate_passed")
    report_package_validation = None
    if package_passed is True:
        report_package_validation = (
            f"pass, {validation.get('error_count') or 0} errors, "
            f"{validation.get('warning_count') or 0} warnings, {validation.get('info_count') or 0} info"
        )
    elif "Report package validation: pass, zero errors, zero warnings, zero findings" in note:
        report_package_validation = "pass, zero errors, zero warnings, zero findings"
    if not note_available and not manifest_available:
        return {
            "available": False,
            "suite": "Report visual QA",
            "message": f"No report visual-QA current-pass note or manifest found at {visual_qa_path}",
            "current_pass_path": _repo_relative(visual_qa_path),
            "manifest_path": _repo_relative(manifest_path),
            "svg_preview_count": svg_preview_count,
            "svg_contact_sheet_path": _repo_relative(svg_contact_sheet),
            "svg_contact_sheet_exists": svg_contact_sheet.is_file(),
            "pdf_contact_sheet_path": _repo_relative(pdf_contact_sheet),
            "pdf_contact_sheet_exists": pdf_contact_sheet.is_file(),
            "pdf_render_attempted": False,
            "pdf_render_status": "missing",
            "pdf_rerender_required": True,
            "pdf_rerender_blocked_this_environment": False,
            "official_ai_agribench": False,
        }

    return {
        "available": True,
        "suite": "Report visual QA",
        "current_pass_path": _repo_relative(visual_qa_path),
        "manifest_path": _repo_relative(manifest_path),
        "manifest_available": manifest_available,
        "manifest_generated_at": manifest.get("generated_at"),
        "manifest_mode": manifest.get("mode"),
        "svg_preview_dir": _repo_relative(previews_dir),
        "svg_preview_count": svg_preview_count,
        "svg_contact_sheet_path": _repo_relative(svg_contact_sheet),
        "svg_contact_sheet_exists": svg_contact_sheet.is_file(),
        "strict_svg_validation": "8 SVGs, zero errors, zero warnings"
        if "Strict SVG validation: 8 SVGs, zero errors, zero warnings" in note
        else None,
        "report_package_validation": report_package_validation,
        "project_state_validation": "pass, all 8 checklist items pass"
        if "Project state validation: pass, all 8 checklist items pass" in note
        else None,
        "visual_gate_svg_html_current": visual_gate.get("svg_html_current"),
        "pdf_render_attempted": pdf_render.get("attempted"),
        "pdf_render_status": pdf_render.get("status") or ("unknown" if manifest_available else "not_tracked"),
        "pdf_render_error": pdf_render.get("error"),
        "pdf_contact_sheet_path": _repo_relative(pdf_contact_sheet),
        "pdf_contact_sheet_exists": pdf_contact_sheet.is_file(),
        "pdf_rerender_required": pdf_required,
        "pdf_rerender_blocked_this_environment": bool(pdf_render.get("blocked_this_environment") or "SIGABRT" in note),
        "next_action": (
            "Rerun PYTHONPATH=src:. python docs/open_agronomy_agent_whitepaper_20260709/scripts/render_report.py "
            "in an environment where Chrome can print, then re-open visual_qa/pdf_contact_sheet.png before sharing the PDF."
        ),
        "boundary": (
            "Current SVG previews and HTML report are refreshed; the PDF/contact-sheet render remains a manual gate "
            "before public PDF sharing."
        ),
        "official_ai_agribench": False,
        "score_warning": "Report visual QA is publication-readiness evidence, not an official AI AgriBench score.",
    }


def _public_shadow_heldout_result_summary(root: Path | None = None) -> dict[str, Any]:
    roots = (root,) if root is not None else DEFAULT_PUBLIC_SHADOW_HELDOUT_ROOTS
    report_paths = sorted(_heldout_gap_report_paths(roots), key=lambda path: path.stat().st_mtime, reverse=True)
    if not report_paths:
        base_label = str(root) if root is not None else ", ".join(str(path) for path in DEFAULT_PUBLIC_SHADOW_HELDOUT_ROOTS)
        return {
            "available": False,
            "suite": "Held-out public shadow result",
            "message": f"No generated held-out public shadow reports found under {base_label}",
            "result_kind": "missing",
            "is_quality_evidence": False,
            "mock": False,
            "official_ai_agribench": False,
        }

    report_path = report_paths[0]
    report = _read_json(report_path)
    by_domain = report.get("by_coverage_domain") if isinstance(report.get("by_coverage_domain"), dict) else {}
    by_lane = report.get("by_public_source_lane") if isinstance(report.get("by_public_source_lane"), dict) else {}
    by_topic = (
        report.get("by_aiagribench_topic_category")
        if isinstance(report.get("by_aiagribench_topic_category"), dict)
        else {}
    )
    evidence = _heldout_result_evidence_metadata(report_path, report)
    return {
        "available": True,
        "suite": "Held-out public shadow result",
        "run_dir": report.get("run_dir") or str(report_path.parent),
        "report_path": str(report_path),
        "markdown_report_path": str(report_path.with_suffix(".md")),
        "suite_path": report.get("suite"),
        "manifest_path": report.get("manifest_path"),
        "scope": report.get("scope"),
        "run_mode": evidence["run_mode"],
        "model_id": evidence["model_id"],
        "answer_profile": evidence["answer_profile"],
        "result_kind": evidence["result_kind"],
        "is_quality_evidence": evidence["is_quality_evidence"],
        "mock": evidence["mock"],
        "samples": report.get("samples"),
        "suite_items": report.get("suite_items"),
        "manifest_row_count": report.get("manifest_row_count"),
        "is_complete_to_manifest": bool(report.get("is_complete_to_manifest")),
        "missing_manifest_rows": report.get("missing_manifest_rows"),
        "mean_score": report.get("mean_score"),
        "metric_means": report.get("metric_means") or {},
        "under90_rows": report.get("under90_rows"),
        "flagged_missing_required": report.get("flagged_missing_required"),
        "low_domains": _lowest_group_rows(by_domain, label_key="domain"),
        "low_source_lanes": _lowest_group_rows(by_lane, label_key="source_lane"),
        "low_topics": _lowest_group_rows(by_topic, label_key="topic"),
        "lowest_rows": (report.get("lowest_rows") or [])[:8],
        "heldout_policy": report.get("heldout_policy") or {},
        "source_boundaries": report.get("source_boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Held-out public shadow result; not official AI AgriBench and not a repair-loop target.",
    }


def _heldout_gap_review_summary(path: Path = HELDOUT_GAP_REVIEW_JSON) -> dict[str, Any]:
    packet = _read_json(path)
    if not packet:
        return {
            "available": False,
            "suite": "Held-out gap review packet",
            "message": f"No held-out gap review packet found at {path}",
            "json_path": str(path),
            "csv_path": str(HELDOUT_GAP_REVIEW_CSV),
            "markdown_path": str(HELDOUT_GAP_REVIEW_MARKDOWN),
            "official_ai_agribench": False,
        }
    return {
        "available": True,
        "suite": "Held-out gap review packet",
        "json_path": str(path),
        "csv_path": str(HELDOUT_GAP_REVIEW_CSV),
        "markdown_path": str(HELDOUT_GAP_REVIEW_MARKDOWN),
        "schema_version": packet.get("schema_version"),
        "generated_at": packet.get("generated_at"),
        "run_dir": packet.get("run_dir"),
        "report_path": packet.get("report_path"),
        "run_mode": packet.get("run_mode"),
        "model_id": packet.get("model_id"),
        "answer_profile": packet.get("answer_profile"),
        "result_kind": packet.get("result_kind"),
        "is_quality_evidence": packet.get("is_quality_evidence"),
        "row_count": packet.get("row_count"),
        "source_samples": packet.get("source_samples"),
        "source_mean_score": packet.get("source_mean_score"),
        "source_under90_rows": packet.get("source_under90_rows"),
        "source_flagged_missing_required": packet.get("source_flagged_missing_required"),
        "selected_mean_score": packet.get("selected_mean_score"),
        "selected_under90_rows": packet.get("selected_under90_rows"),
        "selected_missing_required_rows": packet.get("selected_missing_required_rows"),
        "by_topic": packet.get("by_topic") or {},
        "by_coverage_domain": packet.get("by_coverage_domain") or {},
        "by_public_source_lane": packet.get("by_public_source_lane") or {},
        "top_missing_required_patterns": packet.get("top_missing_required_patterns") or [],
        "quality_risk_note": packet.get("quality_risk_note"),
        "review_policy": packet.get("review_policy") or [],
        "source_boundaries": packet.get("source_boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Held-out gap review packet; not official AI AgriBench and not a repair-loop target.",
    }


def _heldout_result_evidence_metadata(report_path: Path, report: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(str(report.get("run_dir") or report_path.parent))
    run_manifest = _read_json(run_dir / "heldout_run_manifest.json")
    summary = _read_json(run_dir / "summary.json")
    run_mode = report.get("run_mode") or summary.get("mode") or run_manifest.get("mode")
    model_id = report.get("model_id") or summary.get("model_id") or run_manifest.get("model")
    answer_profile = report.get("answer_profile") or summary.get("answer_profile") or run_manifest.get("answer_profile")
    samples = _int_or_zero(report.get("samples"))
    manifest_row_count = _int_or_zero(report.get("manifest_row_count"))
    complete = bool(report.get("is_complete_to_manifest")) and manifest_row_count > 0 and samples == manifest_row_count
    mock = bool(report.get("mock") is True or run_manifest.get("mock") is True or str(model_id or "").lower() == "mock")
    result_kind = str(report.get("result_kind") or "").strip()
    if not result_kind:
        if mock:
            result_kind = "mock_contract"
        elif not complete:
            result_kind = "partial_live"
        elif not run_mode or not model_id:
            result_kind = "unknown_complete"
        elif run_mode != "agronomic_rag":
            result_kind = "baseline_full"
        else:
            result_kind = "full_agentic"
    reported_quality = report.get("is_quality_evidence")
    is_quality_evidence = bool(reported_quality) if isinstance(reported_quality, bool) else result_kind == "full_agentic"
    is_quality_evidence = bool(is_quality_evidence and result_kind == "full_agentic" and complete and not mock)
    return {
        "run_mode": run_mode,
        "model_id": model_id,
        "answer_profile": answer_profile,
        "result_kind": result_kind,
        "is_quality_evidence": is_quality_evidence,
        "mock": mock,
    }


def _public_full_gap_summary(root: Path | None = None) -> dict[str, Any]:
    return _public_gap_summary(
        root=root,
        default_roots=DEFAULT_PUBLIC_DOMAIN_FULL_ROOTS,
        suite_name="Public-domain full coverage gap screen",
        missing_label="public-domain full coverage gap reports",
        score_warning="Full expanded public-domain coverage screen; not an official AI AgriBench score.",
    )


def _public_smoke_gap_summary(root: Path | None = None) -> dict[str, Any]:
    return _public_gap_summary(
        root=root,
        default_roots=DEFAULT_PUBLIC_DOMAIN_SMOKE_ROOTS,
        suite_name="Public-domain smoke gap screen",
        missing_label="public-domain smoke gap reports",
        score_warning="Current public-domain smoke gap screen; not the full coverage manifest and not an official AI AgriBench score.",
    )


def _public_claim_stress_focus_gap_summary(root: Path | None = None) -> dict[str, Any]:
    return _public_gap_summary(
        root=root,
        default_roots=DEFAULT_PUBLIC_CLAIM_STRESS_FOCUS_ROOTS,
        suite_name="Public claim-stress focus gap screen",
        missing_label="public claim-stress focus gap reports",
        score_warning="Stress-only public claim-boundary screen; not an official AI AgriBench score.",
        current_manifest_path=PUBLIC_CLAIM_STRESS_FOCUS_MANIFEST,
    )


def _agentic_gap_matrix_summary(root: Path | None = None) -> dict[str, Any]:
    matrix_dir = root or AGENTIC_GAP_MATRIX_DIR
    summary_path = matrix_dir / "summary.json"
    summary = _read_json(summary_path)
    if not summary:
        return {
            "available": False,
            "suite": "Agentic gap matrix",
            "message": f"No agentic gap matrix summary found at {summary_path}",
            "official_ai_agribench": False,
        }
    return {
        "available": True,
        "suite": "Agentic gap matrix",
        "summary_path": str(summary_path),
        "matrix_path": str(matrix_dir / "agentic_gap_matrix.jsonl"),
        "markdown_path": str(matrix_dir / "agentic_gap_matrix.md"),
        "schema_version": summary.get("schema_version"),
        "rows": summary.get("rows"),
        "core_rows": summary.get("core_rows"),
        "public_expansion_rows": summary.get("public_expansion_rows"),
        "raw_under90_rows": summary.get("raw_under90_rows"),
        "current_under90_rows": summary.get("current_under90_rows"),
        "raw_missing_required_rows": summary.get("raw_missing_required_rows"),
        "current_missing_required_rows": summary.get("current_missing_required_rows"),
        "repaired_contract_gaps": summary.get("repaired_contract_gaps"),
        "open_failures": summary.get("open_failures"),
        "low_floor_human_review_rows": summary.get("low_floor_human_review_rows"),
        "tool_integration_review_rows": summary.get("tool_integration_review_rows"),
        "status_counts": summary.get("status_counts") or {},
        "action_priority_counts": summary.get("action_priority_counts") or {},
        "gap_type_counts": summary.get("gap_type_counts") or {},
        "source_requirement_counts": summary.get("source_requirement_counts") or {},
        "live_adapter_review_rows": summary.get("live_adapter_review_rows"),
        "planned_source_lane_review_rows": summary.get("planned_source_lane_review_rows"),
        "source_gap_backlog_rows": summary.get("source_gap_backlog_rows"),
        "top_raw_missing_required_patterns": summary.get("top_raw_missing_required_patterns") or [],
        "lowest_current_rows": (summary.get("lowest_current_rows") or [])[:8],
        "highest_raw_to_current_repairs": (summary.get("highest_raw_to_current_repairs") or [])[:8],
        "source_boundaries": summary.get("source_boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Agentic gap matrix is local proxy/shadow diagnostics; not an official AI AgriBench result.",
    }


def _human_review_queue_summary(path: Path = HUMAN_REVIEW_QUEUE_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(path)
    if not manifest:
        return {
            "available": False,
            "suite": "Human review queue",
            "message": f"No human review queue manifest found at {path}",
            "official_ai_agribench": False,
        }
    return {
        "available": True,
        "suite": "Human review queue",
        "manifest_path": str(path),
        "queue_path": manifest.get("queue_path") or str(HUMAN_REVIEW_QUEUE_JSONL),
        "markdown_path": manifest.get("markdown_path") or str(HUMAN_REVIEW_QUEUE_MARKDOWN),
        "schema_version": manifest.get("schema_version"),
        "queue_item_count": manifest.get("queue_item_count"),
        "source_counts": manifest.get("source_counts") or {},
        "by_source": manifest.get("by_source") or {},
        "by_priority": manifest.get("by_priority") or {},
        "by_review_type": manifest.get("by_review_type") or {},
        "top_coverage_domains": manifest.get("top_coverage_domains") or [],
        "top_public_source_lanes": manifest.get("top_public_source_lanes") or [],
        "review_policy": manifest.get("review_policy") or [],
        "source_boundaries": manifest.get("source_boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Human review assignment queue; not an official AI AgriBench result or scored benchmark report.",
    }


def human_review_batches_summary(path: Path = HUMAN_REVIEW_BATCHES_MANIFEST) -> dict[str, Any]:
    manifest = _read_json(path)
    if not manifest:
        return {
            "available": False,
            "suite": "Human review batches",
            "message": f"No human review batches manifest found at {path}",
            "official_ai_agribench": False,
        }
    batches = manifest.get("batches") if isinstance(manifest.get("batches"), list) else []
    return {
        "available": True,
        "suite": "Human review batches",
        "manifest_path": str(path),
        "markdown_path": str(HUMAN_REVIEW_BATCHES_MARKDOWN),
        "schema_version": manifest.get("schema_version"),
        "queue_path": manifest.get("queue_path") or str(HUMAN_REVIEW_QUEUE_JSONL),
        "queue_item_count": manifest.get("queue_item_count"),
        "quality_claim_review_floor": manifest.get("quality_claim_review_floor"),
        "p0_public_demo_rows": manifest.get("p0_public_demo_rows"),
        "p1_available_rows": manifest.get("p1_available_rows"),
        "p2_available_rows": manifest.get("p2_available_rows"),
        "quality_sample_plus_p0_rows": manifest.get("quality_sample_plus_p0_rows"),
        "batch_count": len(batches),
        "batches": [
            {
                "batch_id": batch.get("batch_id"),
                "label": batch.get("label"),
                "purpose": batch.get("purpose"),
                "review_goal": batch.get("review_goal"),
                "csv_path": batch.get("csv_path"),
                "absolute_path": batch.get("absolute_path"),
                "row_count": batch.get("row_count"),
                "by_priority": batch.get("by_priority") or {},
                "by_review_type": batch.get("by_review_type") or {},
                "by_source": batch.get("by_source") or {},
            }
            for batch in batches
            if isinstance(batch, dict)
        ],
        "source_boundaries": manifest.get("source_boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": "Human review batches are local app-testing assignments; not official AI AgriBench results.",
    }


def _human_smoke_preflight_summary(path: Path = HUMAN_SMOKE_PREFLIGHT_JSON) -> dict[str, Any]:
    payload = _read_json(path)
    if not payload:
        return {
            "available": False,
            "suite": "Human smoke preflight",
            "message": f"No human smoke preflight found at {path}",
            "official_ai_agribench": False,
            "human_review_replacement": False,
        }
    return {
        "available": True,
        "suite": "Human smoke preflight",
        "json_path": str(path),
        "markdown_path": str(HUMAN_SMOKE_PREFLIGHT_MARKDOWN),
        "runner_path": str(HUMAN_SMOKE_PREFLIGHT_RUNNER),
        "schema_version": payload.get("schema_version"),
        "mode": payload.get("mode"),
        "generated_at": payload.get("generated_at"),
        "row_count": payload.get("row_count"),
        "passed_row_count": payload.get("passed_row_count"),
        "error_count": payload.get("error_count"),
        "warning_count": payload.get("warning_count"),
        "preflight_passed": bool(payload.get("preflight_passed")),
        "official_ai_agribench": False,
        "human_review_replacement": bool(payload.get("human_review_replacement")),
        "boundary": payload.get("boundary"),
        "score_warning": "Human smoke preflight is an offline app-routing contract check; not human review and not an official AI AgriBench result.",
    }


def _public_gap_summary(
    *,
    root: Path | None,
    default_roots: tuple[Path, ...],
    suite_name: str,
    missing_label: str,
    score_warning: str,
    current_manifest_path: Path | None = None,
) -> dict[str, Any]:
    roots = (root,) if root is not None else default_roots
    report_paths = sorted(_gap_report_paths(roots), key=lambda path: path.stat().st_mtime, reverse=True)
    if not report_paths:
        base_label = str(root) if root is not None else ", ".join(str(path) for path in default_roots)
        return {
            "available": False,
            "suite": suite_name,
            "message": f"No generated {missing_label} found under {base_label}",
            "official_ai_agribench": False,
        }

    report_path = report_paths[0]
    report = _read_json(report_path)
    current_manifest = _read_json(current_manifest_path) if current_manifest_path is not None else {}
    if current_manifest:
        coverage_total = int(current_manifest.get("total_items") or 0)
    else:
        coverage = _public_coverage_summary()
        coverage_total = int(coverage.get("total_items") or 0)
    samples = int(report.get("samples") or 0)
    by_domain = report.get("by_coverage_domain") if isinstance(report.get("by_coverage_domain"), dict) else {}
    low_domains = sorted(
        (
            {
                "domain": domain,
                "samples": int(payload.get("samples") or 0),
                "mean_score": payload.get("mean_score"),
                "min_score": payload.get("min_score"),
                "flagged_missing_required": int(payload.get("flagged_missing_required") or 0),
                "common_missing_required": payload.get("common_missing_required") or [],
            }
            for domain, payload in by_domain.items()
            if isinstance(payload, dict)
        ),
        key=lambda item: (float(item["mean_score"] or 0), item["domain"]),
    )
    by_lane = report.get("by_public_source_lane") if isinstance(report.get("by_public_source_lane"), dict) else {}
    low_source_lanes = sorted(
        (
            {
                "source_lane": lane,
                "samples": int(payload.get("samples") or 0),
                "mean_score": payload.get("mean_score"),
                "min_score": payload.get("min_score"),
                "flagged_missing_required": int(payload.get("flagged_missing_required") or 0),
                "common_missing_required": payload.get("common_missing_required") or [],
            }
            for lane, payload in by_lane.items()
            if isinstance(payload, dict)
        ),
        key=lambda item: (float(item["mean_score"] or 0), item["source_lane"]),
    )
    return {
        "available": True,
        "suite": suite_name,
        "run_dir": report.get("run_dir") or str(report_path.parent),
        "report_path": str(report_path),
        "markdown_report_path": str(report_path.with_suffix(".md")),
        "suite_path": report.get("suite"),
        "current_manifest_path": str(current_manifest_path) if current_manifest_path is not None else str(PUBLIC_DOMAIN_COVERAGE_MANIFEST),
        "scope": report.get("scope"),
        "suite_items": report.get("suite_items"),
        "core_items": report.get("core_items"),
        "expansion_items": report.get("expansion_items"),
        "samples": report.get("samples"),
        "coverage_total_items": coverage_total or None,
        "is_current_to_manifest": bool(coverage_total and samples == coverage_total),
        "missing_manifest_rows": max(coverage_total - samples, 0) if coverage_total else None,
        "mean_score": report.get("mean_score"),
        "metric_means": report.get("metric_means") or {},
        "under90_rows": report.get("under90_rows"),
        "flagged_missing_required": report.get("flagged_missing_required"),
        "demo_quality_mean": report.get("demo_quality_mean"),
        "demo_quality_under82_rows": report.get("demo_quality_under82_rows"),
        "quality_risk_row_count": report.get("quality_risk_row_count"),
        "high_proxy_quality_risk_count": report.get("high_proxy_quality_risk_count"),
        "common_quality_flags": report.get("common_quality_flags") or [],
        "low_domains": low_domains[:8],
        "low_source_lanes": low_source_lanes[:8],
        "source_boundaries": report.get("source_boundaries") or [],
        "official_ai_agribench": False,
        "score_warning": score_warning,
    }


def _summary_paths(roots: tuple[Path, ...]) -> list[Path]:
    paths: list[Path] = []
    for base in roots:
        if (base / "summary.json").exists():
            paths.append(base / "summary.json")
        paths.extend(base.glob("*/summary.json"))
    return paths


def _gap_report_paths(roots: tuple[Path, ...]) -> list[Path]:
    paths: list[Path] = []
    for base in roots:
        if (base / "gap_report.json").exists():
            paths.append(base / "gap_report.json")
        paths.extend(base.glob("*/gap_report.json"))
    return paths


def _heldout_gap_report_paths(roots: tuple[Path, ...]) -> list[Path]:
    paths: list[Path] = []
    for base in roots:
        if (base / "heldout_gap_report.json").exists():
            paths.append(base / "heldout_gap_report.json")
        paths.extend(base.glob("*/heldout_gap_report.json"))
    return paths


def _lowest_group_rows(groups: dict[str, Any], *, label_key: str) -> list[dict[str, Any]]:
    rows = []
    for name, payload in groups.items():
        if not isinstance(payload, dict):
            continue
        rows.append(
            {
                label_key: name,
                "samples": int(payload.get("samples") or 0),
                "mean_score": payload.get("mean_score"),
                "min_score": payload.get("min_score"),
                "flagged_missing_required": int(payload.get("flagged_missing_required") or 0),
                "common_missing_required": payload.get("common_missing_required") or [],
            }
        )
    return sorted(rows, key=lambda item: (float(item["mean_score"] or 0), str(item[label_key])))[:8]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _read_output_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _read_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _row_score(row: dict[str, Any]) -> float:
    score = row.get("score")
    if isinstance(score, dict) and _is_number(score.get("score")):
        return float(score["score"])
    if _is_number(score):
        return float(score)
    return 0.0


def _summarize_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("eval_metadata") if isinstance(row.get("eval_metadata"), dict) else {}
    return {
        "eval_id": row.get("eval_id"),
        "score": _row_score(row),
        "task_family": row.get("task_family"),
        "crop": metadata.get("crop"),
        "region": metadata.get("region"),
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _int_or_zero(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _read_mapping_file(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(repo_path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _configured_paths(value: Any) -> list[Path]:
    if isinstance(value, (str, Path)):
        raw_paths = [value]
    elif isinstance(value, list):
        raw_paths = value
    else:
        raw_paths = []
    paths: list[Path] = []
    for raw in raw_paths:
        if raw in (None, ""):
            continue
        paths.append(repo_path(str(raw)))
    return paths


def _artifact_entry(label: str, path_value: str | Path, *, kind: str) -> dict[str, Any]:
    path = repo_path(path_value)
    exists = path.exists() and path.is_file()
    entry: dict[str, Any] = {
        "label": label,
        "kind": kind,
        "path": _repo_relative(path),
        "exists": exists,
    }
    if not exists:
        return entry
    stat = path.stat()
    entry["bytes"] = stat.st_size
    entry["sha256"] = _sha256(path)
    if path.suffix.lower() in {".jsonl", ".ndjson", ".csv"}:
        entry["line_count"] = _line_count(path)
    return entry


def _latest_proxy_artifacts(proxy_summary: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_dir = proxy_summary.get("artifact_dir")
    if not artifact_dir:
        return []
    run_dir = repo_path(str(artifact_dir))
    return [
        _artifact_entry("latest_proxy_summary", run_dir / "summary.json", kind="local_proxy_result"),
        _artifact_entry("latest_proxy_outputs", run_dir / "outputs.jsonl", kind="local_proxy_result"),
    ]


def _check_item(item_id: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {"id": item_id, "label": label, "status": status, "detail": detail}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def _repo_relative(path: str | Path) -> str:
    resolved = repo_path(path).resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def _git_head_snapshot() -> dict[str, Any]:
    git_dir = _git_dir()
    if not git_dir:
        return {"available": False, "commit": None, "ref": None, "dirty_state": "not_computed"}
    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return {"available": False, "commit": None, "ref": None, "dirty_state": "not_computed"}
    ref: str | None = None
    commit: str | None = None
    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        ref_path = git_dir / ref
        try:
            commit = ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            commit = _packed_ref(git_dir, ref)
    elif head:
        commit = head
    return {
        "available": bool(commit),
        "commit": commit,
        "short_commit": commit[:12] if commit else None,
        "ref": ref,
        "dirty_state": "not_computed",
        "dirty_state_note": "The local API reads .git/HEAD without shelling out; run git status before final freeze.",
    }


def _git_dir() -> Path | None:
    dot_git = repo_path(".git")
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        try:
            text = dot_git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if text.startswith("gitdir:"):
            raw = text.split(":", 1)[1].strip()
            path = Path(raw)
            return path if path.is_absolute() else REPO_ROOT / path
    return None


def _packed_ref(git_dir: Path, ref: str) -> str | None:
    packed = git_dir / "packed-refs"
    try:
        lines = packed.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line or line.startswith("#") or line.startswith("^"):
            continue
        parts = line.split()
        if len(parts) == 2 and parts[1] == ref:
            return parts[0]
    return None
