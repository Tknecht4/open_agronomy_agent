import { useEffect, useMemo, useState } from 'react'
import { apiGet } from './api'
import './BenchmarksRoute.css'

const LOCAL_NOT_OFFICIAL = 'Local diagnostic; not official AI AgriBench.'
const WHITEPAPER_DIR = 'docs/open_agronomy_agent_whitepaper_20260709'
type CanonicalBenchmarkSummary = {
  available: boolean
  benchmark_id?: string
  status?: string
  rows?: number
  lane_counts?: Record<string, number>
  unique_questions?: number
  exact_duplicate_questions?: number
  traceable_real_user_questions?: number
  claim_eligible?: boolean
  database_available?: boolean
  external_diagnostic?: {
    available?: boolean
    benchmark_id?: string
    rows?: number
    database_available?: boolean
    separation_status?: string
    exact_overlap?: number
    near_overlap?: number
    use_policy?: string
    claim_eligible?: boolean
    geographic_scope?: string
  }
  message?: string
}
type BenchmarkFamilyFloor = {
  family: string
  samples: number
  mean_score: number
  min_score: number
  max_score: number
  flagged_missing_required: number
}

type BenchmarkLowestRow = {
  eval_id: string
  score: number
  task_family: string
  crop?: string
  region?: string
}

type DirectSemanticReviewSummary = {
  available: boolean
  suite?: string
  review_path?: string
  markdown_path?: string
  run_dir?: string
  rows?: number
  semantic_mean?: number
  answer_disposition?: Record<string, number>
  generation_paths?: Record<string, number>
  dimensions_0_to_100?: Record<string, number>
  source_proxy_mean?: number
  mean_latency_seconds?: number
  needs_source_validation?: number
  official_ai_agribench?: boolean
  human_agronomist_signoff?: boolean
  score_warning?: string
  proxy_semantic_pearson?: number | null
  generation_path_quality?: Record<string, { rows?: number; semantic_score_mean?: number; answer_disposition?: Record<string, number> }>
  by_source?: Record<string, { rows?: number; semantic_score_mean?: number; answer_disposition?: Record<string, number> }>
  by_question_disposition?: Record<string, { rows?: number; semantic_score_mean?: number; answer_disposition?: Record<string, number> }>
  by_task_family?: Record<string, { rows?: number; semantic_score_mean?: number; answer_disposition?: Record<string, number> }>
  by_crop?: Record<string, { rows?: number; semantic_score_mean?: number; answer_disposition?: Record<string, number> }>
  by_jurisdiction?: Record<string, { rows?: number; semantic_score_mean?: number; answer_disposition?: Record<string, number> }>
  source_row_count?: number
  skipped_without_answer?: number
  lowest_rows?: Array<{
    eval_id?: string
    score?: number
    disposition?: string
    crop?: string
    jurisdiction?: string
    material_errors?: string[]
  }>
}

type PublicCoverageSummary = {
  available: boolean
  suite?: string
  suite_path?: string
  manifest_path?: string
  core_items?: number
  expansion_items?: number
  total_items?: number
  official_ai_agribench?: boolean
  domain_counts?: Record<string, number>
  source_lane_counts?: Record<string, number>
  aiagribench_topic_category_counts?: Record<string, number>
  source_boundaries?: string[]
  score_warning?: string
}

type PublicDeepCoverageSummary = PublicCoverageSummary & {
  base_total_items?: number
  base_core_items?: number
  base_expansion_items?: number
  deep_context_extension_items?: number
  deep_scenario_items?: number
  deep_added_items?: number
  deep_scenario_templates?: number
  total_scenario_templates?: number
  deep_contexts_per_scenario?: number
  scored?: boolean
  deep_domain_counts?: Record<string, number>
  deep_source_lane_counts?: Record<string, number>
  new_guard_tool_counts?: Record<string, number>
  expected_public_adapter_counts?: Record<string, number>
  coverage_axes?: string[]
  smoke_readiness?: PublicDeepSmokeReadinessSummary
}

type PublicDeepSmokeReadinessGroup = {
  domain?: string
  lane?: string
  items?: number
  mean_required_support_rate?: number
  mean_source_diversity?: number
  rows_missing_expected_tool_notes?: number
}

type PublicDeepSmokeReadinessTool = {
  tool?: string
  expected_rows?: number
  routed_rows?: number
  route_recall?: number
}

type PublicDeepSmokeGpuAttempt = {
  available?: boolean
  path?: string
  markdown_path?: string
  generated_at?: string
  status?: string
  stage?: string
  returncode?: number | null
  blocker?: string | null
  next_action?: string | null
}

type PublicDeepSmokeReadinessSummary = {
  available?: boolean
  status?: string
  path?: string
  markdown_path?: string
  suite_rows?: number
  scored_answer_quality?: boolean
  quality_claim_ready?: boolean
  mean_required_support_rate?: number
  mean_source_diversity?: number
  retrieval_context_ready?: boolean
  latest_completed_generation?: string | null
  latest_incomplete_generation?: string | null
  latest_gpu_attempt?: PublicDeepSmokeGpuAttempt | null
  blockers?: string[]
  low_domains?: PublicDeepSmokeReadinessGroup[]
  low_source_lanes?: PublicDeepSmokeReadinessGroup[]
  under_routed_tools?: PublicDeepSmokeReadinessTool[]
  run_command?: string
  score_warning?: string
}

type PublicSmokeDomain = {
  domain: string
  samples: number
  mean_score?: number
  min_score?: number
  flagged_missing_required?: number
  common_missing_required?: Array<[string, number]>
}

type PublicSmokeLane = {
  source_lane: string
  samples: number
  mean_score?: number
  min_score?: number
  flagged_missing_required?: number
  common_missing_required?: Array<[string, number]>
}

type PublicSmokeGapSummary = {
  available: boolean
  suite?: string
  run_dir?: string
  report_path?: string
  markdown_report_path?: string
  suite_path?: string
  scope?: string
  suite_items?: number
  core_items?: number
  expansion_items?: number
  samples?: number
  coverage_total_items?: number
  is_current_to_manifest?: boolean
  missing_manifest_rows?: number
  mean_score?: number
  under90_rows?: number
  flagged_missing_required?: number
  demo_quality_mean?: number
  demo_quality_under82_rows?: number
  quality_risk_row_count?: number
  high_proxy_quality_risk_count?: number
  common_quality_flags?: Array<[string, number]>
  low_domains?: PublicSmokeDomain[]
  low_source_lanes?: PublicSmokeLane[]
  source_boundaries?: string[]
  score_warning?: string
}

type AgenticGapMatrixRow = {
  eval_id: string
  scope?: string
  coverage_domain?: string
  public_source_lane?: string
  scenario_type?: string
  raw_score?: number
  current_score?: number
  score_delta?: number
  gap_status?: string
  action_priority?: string
  recommended_action?: string
}

type AgenticGapMatrixSummary = {
  available: boolean
  suite?: string
  summary_path?: string
  matrix_path?: string
  markdown_path?: string
  rows?: number
  raw_under90_rows?: number
  current_under90_rows?: number
  repaired_contract_gaps?: number
  open_failures?: number
  low_floor_human_review_rows?: number
  tool_integration_review_rows?: number
  live_adapter_review_rows?: number
  planned_source_lane_review_rows?: number
  source_gap_backlog_rows?: number
  source_requirement_counts?: Record<string, number>
  lowest_current_rows?: AgenticGapMatrixRow[]
  highest_raw_to_current_repairs?: AgenticGapMatrixRow[]
  score_warning?: string
}

type PublicDemoRehearsalSummary = {
  available: boolean
  suite?: string
  suite_path?: string
  manifest_path?: string
  markdown_path?: string
  prompt_count?: number
  context_count?: number
  adapter_lane_count?: number
  contexts?: Record<string, number>
  public_source_lanes?: Record<string, number>
  official_ai_agribench?: boolean
  source_boundaries?: string[]
  score_warning?: string
}

type PublicDemoRehearsalPrompt = {
  prompt_id: string
  context_id?: string
  context_label?: string
  workflow?: string
  public_source_lane?: string
  source_lane_label?: string
  question: string
  expected_public_adapters?: string[]
  expected_visible_evidence?: string[]
  release_blocking_failure?: string
}

type PublicDemoRehearsalPacket = PublicDemoRehearsalSummary & {
  prompt_count_returned: number
  prompts: PublicDemoRehearsalPrompt[]
  boundary?: string
}

type PublicShadowHeldoutSummary = {
  available: boolean
  suite?: string
  row_count?: number
  context_count?: number
  topic_category_count?: number
  source_lane_count?: number
  score_warning?: string
}

type PublicShadowHeldoutResultSummary = PublicSmokeGapSummary & {
  manifest_row_count?: number
  is_complete_to_manifest?: boolean
}

type HeldoutGapReviewSummary = {
  available: boolean
  suite?: string
  json_path?: string
  csv_path?: string
  markdown_path?: string
  row_count?: number
  source_samples?: number
  source_mean_score?: number
  source_under90_rows?: number
  source_flagged_missing_required?: number
  selected_mean_score?: number
  selected_under90_rows?: number
  selected_missing_required_rows?: number
  by_topic?: Record<string, number>
  by_coverage_domain?: Record<string, number>
  by_public_source_lane?: Record<string, number>
  top_missing_required_patterns?: Array<[string, number]>
  quality_risk_note?: string
  score_warning?: string
}

type HumanReviewQueueSummary = {
  available: boolean
  suite?: string
  manifest_path?: string
  queue_path?: string
  markdown_path?: string
  queue_item_count?: number
  by_priority?: Record<string, number>
  score_warning?: string
}

type HumanReviewQueueItem = {
  review_id: string
  source?: string
  priority?: string
  review_type?: string
  context_label?: string
  question?: string
  coverage_domain?: string
  public_source_lane?: string
  expected_public_adapters?: string[]
  expected_visible_evidence?: string[]
  release_blocking_failure?: string
  human_review_focus?: string
  no_repair_loop?: boolean
}

type HumanReviewQueuePacket = HumanReviewQueueSummary & {
  item_count_returned: number
  items: HumanReviewQueueItem[]
  boundary?: string
  source_boundaries?: string[]
}

type HumanReviewOutcomeBatch = {
  batch_id?: string
  label?: string
  csv_path?: string
  row_count?: number
  reviewed_count?: number
  blocking_issue_count?: number
  record_issue_count?: number
  status?: string
}

type HumanReviewBlocker = {
  review_id?: string
  priority?: string
  result_status?: string
  severity?: string
  issue_summary?: string
  followup_owner?: string
}

type HumanReviewRecordIssue = {
  review_id?: string
  priority?: string
  issue_type?: string
  detail?: string
}

type HumanReviewLatestIngest = {
  path?: string
  generated_at?: string
  incoming_rows?: number
  incoming_reviewed_rows?: number
  merged_rows?: number
  skipped_unreviewed_rows?: number
  reviewed_count?: number
  public_demo_gate?: string
  quality_claim_gate?: string
  readiness_automated_gate_passed?: boolean
  readiness_public_demo_ready?: boolean
}

type HumanReviewLatestPreflight = {
  path?: string
  markdown_path?: string
  generated_at?: string
  status?: string
  ready_to_ingest?: boolean
  incoming_rows?: number
  incoming_reviewed_rows?: number
  merged_rows?: number
  skipped_unreviewed_rows?: number
  skipped_existing_reviewed_rows?: number
  reviewed_count_after_merge?: number
  review_record_issue_count_after_merge?: number
  public_demo_gate_after_merge?: string
  quality_claim_gate_after_merge?: string
  warning_count?: number
  error_count?: number
}

type HumanReviewOutcomeSummary = {
  available: boolean
  suite?: string
  summary_path?: string
  template_path?: string
  markdown_path?: string
  queue_item_count?: number
  outcome_row_count?: number
  reviewed_count?: number
  p0_total?: number
  p0_reviewed?: number
  review_record_issue_count?: number
  p0_review_record_issue_count?: number
  review_record_issues?: HumanReviewRecordIssue[]
  blocking_issue_count?: number
  public_demo_gate?: { status?: string; requirement?: string }
  quality_claim_gate?: { status?: string; requirement?: string }
  review_batch_count?: number
  review_batches?: HumanReviewOutcomeBatch[]
  latest_ingest?: HumanReviewLatestIngest | null
  latest_preflight?: HumanReviewLatestPreflight | null
  next_actions?: string[]
  top_blockers?: HumanReviewBlocker[]
  score_warning?: string
}

type SubmissionAnswerHygieneSummary = {
  available?: boolean
  suite?: string
  row_count?: number
  quality_warning_count?: number
  quality_warning_rate?: number
  high_risk_warning_count?: number
  high_risk_warning_rate?: number
  current_high_risk_warning_count?: number
  current_high_risk_warning_rate?: number
  stale_high_risk_warning_count?: number
  stale_high_risk_warning_rate?: number
  current_high_risk_artifacts?: string[]
  stale_high_risk_artifacts?: string[]
  high_risk_review_row_count?: number
  high_risk_review_csv?: string
  format_warning_count?: number
  format_warning_rate?: number
  next_actions?: string[]
  score_warning?: string
}

type AiAgribenchSubmissionDryRunSummary = {
  available?: boolean
  suite?: string
  row_count?: number
  dry_run_kind?: string
  mock?: boolean
  mode?: string
  answer_profile?: string
  official_payload_submit_safe?: boolean
  minimum_protocol_passed?: boolean
  quality_warning_passed?: boolean
  submission_ready_without_manual_exception?: boolean
  quality_warning_count?: number
  submit_safe_sample_path?: string
  score_warning?: string
}

type ReportVisualQaSummary = {
  available?: boolean
  suite?: string
  current_pass_path?: string
  manifest_path?: string
  manifest_available?: boolean
  manifest_generated_at?: string
  manifest_mode?: string
  svg_preview_dir?: string
  svg_preview_count?: number
  strict_svg_validation?: string | null
  report_package_validation?: string | null
  project_state_validation?: string | null
  visual_gate_svg_html_current?: boolean
  pdf_render_attempted?: boolean
  pdf_render_status?: string
  pdf_render_error?: string | null
  pdf_contact_sheet_path?: string
  pdf_contact_sheet_exists?: boolean
  pdf_rerender_required?: boolean
  pdf_rerender_blocked_this_environment?: boolean
  next_action?: string
  boundary?: string
  score_warning?: string
}

type AcceptanceCurrentStatus = {
  automated_gate_passed?: boolean
  public_demo_ready?: boolean
  quality_claim_ready?: boolean
  aiagribench_rehearsal_ready_once_official_questions_arrive?: boolean
  aiagribench_submission_ready?: boolean
  automated_blocker_ids?: string[]
  open_gate_ids?: string[]
}

type AcceptanceGateSummary = {
  status?: string
  blocking_gate_ids?: string[]
  detail?: string
}

type AcceptanceReviewStep = {
  order?: number
  label?: string
  batch_id?: string
  row_count?: number
  reviewed_count?: number
  artifact?: string
  pass_rule?: string
}

type AcceptanceVisualQaPlan = {
  svg_html_current?: boolean
  pdf_current?: boolean
  pdf_rerender_required?: boolean
  pdf_render_status?: string
  reviewer_action?: string
}

type PublicDemoAcceptanceChecklist = {
  schema_version?: string
  current_status?: AcceptanceCurrentStatus
  go_no_go?: {
    public_demo?: AcceptanceGateSummary
    quality_claim?: AcceptanceGateSummary
    aiagribench_submission?: AcceptanceGateSummary
  }
  review_plan?: AcceptanceReviewStep[]
  visual_qa_plan?: AcceptanceVisualQaPlan
  commands?: Record<string, string>
}

type LiveSourceQaPacket = {
  schema_version?: string
  demo_go_no_go?: {
    status?: string
    offline_smoke_gate?: string
    credential_gate?: string
    monitor_lane_gate?: string
    open_blockers?: string[]
  }
  readiness_summary?: {
    adapter_count?: number
    ready_count?: number
    needs_key_count?: number
    monitor_count?: number
    smoke_check_count?: number
    smoke_passed_count?: number
    smoke_failed_count?: number
    smoke_missing_count?: number
  }
  credential_blockers?: Array<{ id?: string; label?: string; required_env_vars?: string[] }>
  monitor_only_lanes?: Array<{ id?: string; label?: string }>
  live_candidate_adapters?: Array<{ id?: string; label?: string }>
  source_card_lanes?: Array<{ id?: string; label?: string }>
  regional_matrix?: {
    context_count?: number
    adapter_case_count?: number
  }
}

type FreezeChecklistItem = {
  id: string
  label: string
  status: 'pass' | 'pending' | 'manual' | 'needs_review' | 'fail' | string
  detail: string
}

type FreezeArtifact = {
  label: string
  kind: string
  path: string
  exists: boolean
  bytes?: number
  sha256?: string
  line_count?: number
}

type FreezeManifest = {
  schema_version: string
  generated_at?: string
  target?: string
  status?: string
  score_warning?: string
  git?: {
    short_commit?: string | null
    commit?: string | null
    ref?: string | null
  }
  runner?: {
    path?: string
    command_template?: string
    official_response_file?: string
    audit_response_files?: string[]
    preflight_file?: string
    internal_trace_file?: string
    submission_boundary?: string
  }
  model?: {
    model_id?: string
    max_tokens?: number
    serving_max_tokens?: number
    assistant_model_id?: string
    assistant_max_tokens?: number
    temperature?: number
    answer_profile?: string
  }
  rag?: {
    config_path?: string
    retrieval_top_k?: number
    retrieval_min_score?: number
    configured_corpus_paths?: number
    configured_graph_paths?: number
    agent_runtime?: string
    agno_enabled?: boolean
  }
  artifacts?: FreezeArtifact[]
  corpora?: FreezeArtifact[]
  graphs?: FreezeArtifact[]
  checklist?: FreezeChecklistItem[]
}

type BenchmarkSummary = {
  available: boolean
  suite: string
  run_id?: string
  mode?: string
  model_id?: string
  answer_profile?: string
  samples?: number
  mean_score?: number
  metrics?: Record<string, number>
  missing_required_flags?: number
  under90_rows?: number
  average_seconds?: number
  max_seconds?: number
  family_floors?: BenchmarkFamilyFloor[]
  lowest_rows?: BenchmarkLowestRow[]
  direct_semantic_review?: DirectSemanticReviewSummary
  canadian_semantic_review?: DirectSemanticReviewSummary
  public_coverage?: PublicCoverageSummary
  public_deep_coverage?: PublicDeepCoverageSummary
  public_full_gap?: PublicSmokeGapSummary
  public_smoke_gap?: PublicSmokeGapSummary
  public_claim_stress_focus?: PublicSmokeGapSummary
  public_demo_rehearsal?: PublicDemoRehearsalSummary
  public_shadow_heldout?: PublicShadowHeldoutSummary
  public_shadow_heldout_result?: PublicShadowHeldoutResultSummary
  heldout_gap_review?: HeldoutGapReviewSummary
  agentic_gap_matrix?: AgenticGapMatrixSummary
  human_review_queue?: HumanReviewQueueSummary
  human_review_outcomes?: HumanReviewOutcomeSummary
  submission_answer_hygiene?: SubmissionAnswerHygieneSummary
  aiagribench_submission_dry_run?: AiAgribenchSubmissionDryRunSummary
  report_visual_qa?: ReportVisualQaSummary
  score_warning?: string
  message?: string
}

type BenchmarkEvidenceRow = {
  suite: string
  samples: number | 'n/a'
  reference: string
  current: string
  note: string
}

type ModelAdaptationReadiness = {
  available: boolean
  status: string
  message?: string
  new_global_lora_authorized?: boolean
  hardware_feasibility?: {
    status?: string
    gemma3_270m_observed_peak_memory_gb?: number
    gemma4_e2b_smoke_observed_peak_memory_gb?: number
  }
  conference_answer_model?: {
    model_id?: string
    revision?: string
    active_identity_matches_decision?: boolean
    selection_evidence?: {
      complete_system_paired_rows?: number
      qwen_minus_gemma_semantic_delta?: number
      independent_agronomist_signoff?: boolean
    }
  }
  experiments?: Array<{
    id?: string
    status?: string
    strict_json_rate?: number
    safety_critical_omission_rows?: number
    document_disjoint_balanced_delta?: number
    critical_regression_rows?: number
  }>
  blockers?: Array<{
    id?: string
    status?: string
    reason?: string
  }>
  next_experiment?: {
    authorized_scope?: string
    stop_rule?: string
  }
  boundary?: string
}

const fallbackBenchmarkSummary: BenchmarkSummary = {
  available: false,
  suite: 'Benchmark data unavailable',
  score_warning: 'The live benchmark API is unavailable; no bundled score snapshot is shown.',
}

const fallbackCanonicalBenchmark: CanonicalBenchmarkSummary = {
  available: false,
  benchmark_id: 'open_agronomy_canadian_performance_v1',
}

const fallbackModelAdaptationReadiness: ModelAdaptationReadiness = {
  available: false,
  status: 'unavailable',
  new_global_lora_authorized: false,
  message: 'Model-adaptation readiness evidence is unavailable.',
  boundary: 'No new adapter training or promotion is authorized when the evidence record is unavailable.',
}

const fallbackPublicDemoRehearsalPacket: PublicDemoRehearsalPacket = {
  available: false,
  prompt_count_returned: 0,
  prompts: [],
  score_warning: 'The live rehearsal packet is unavailable.',
}

const fallbackHumanReviewQueuePacket: HumanReviewQueuePacket = {
  available: false,
  item_count_returned: 0,
  items: [],
  score_warning: 'The live review queue is unavailable.',
}

const fallbackPublicDemoAcceptanceChecklist: PublicDemoAcceptanceChecklist = {
  schema_version: 'open_agronomy_agent.public_demo_acceptance_checklist.unavailable',
  current_status: {
    automated_gate_passed: false,
    public_demo_ready: false,
    quality_claim_ready: false,
    aiagribench_submission_ready: false,
    automated_blocker_ids: ['benchmark_api_unavailable'],
    open_gate_ids: ['benchmark_api_unavailable'],
  },
  go_no_go: {
    public_demo: { status: 'no_go', blocking_gate_ids: ['benchmark_api_unavailable'] },
    quality_claim: { status: 'no_go', blocking_gate_ids: ['benchmark_api_unavailable'] },
    aiagribench_submission: { status: 'no_go', blocking_gate_ids: ['benchmark_api_unavailable'] },
  },
  review_plan: [],
  visual_qa_plan: {
    svg_html_current: false,
    pdf_current: false,
    pdf_rerender_required: true,
    pdf_render_status: 'unavailable',
  },
  commands: {},
}

const fallbackFreezeManifest: FreezeManifest = {
  schema_version: 'open_agronomy_agent.aiagribench_freeze_manifest.unavailable',
  status: 'unavailable',
  score_warning: 'The live freeze manifest is unavailable; no submission state is inferred.',
}

const scoreText = (value: number | undefined, digits = 2): string =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'n/a'

const countValue = (value: number | undefined): number | 'n/a' =>
  typeof value === 'number' && Number.isFinite(value) ? value : 'n/a'

const percentText = (value: number | undefined): string =>
  typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : 'n/a'

const repoRelativePath = (path: string | undefined): string =>
  path?.replace('/Volumes/ext/agronomy_agent/', '') || 'gap report pending'

const benchmarkArtifactHref = (artifactId: string): string => `/api/benchmarks/artifacts/${artifactId}`

const reviewBatchArtifactId = (batchId: string | undefined): string | undefined => {
  if (batchId === 'quickstart_smoke') return 'human-review-batch-quickstart-smoke'
  if (batchId === 'public_demo_p0') return 'human-review-batch-public-demo-p0'
  if (batchId === 'quality_claim_sample') return 'human-review-batch-quality-sample'
  if (batchId === 'source_card_p2_sample') return 'human-review-batch-source-card-sample'
  return undefined
}

const readableLabel = (value: string | undefined): string => value?.replace(/_/g, ' ') || 'n/a'

const compactReviewAction = (value: string): string => value.replace(/`/g, '')

const reviewStatusClass = (status: string | undefined): string =>
  (status || 'needs_review').toLowerCase().replace(/_/g, '-')

const reviewProgressPercent = (reviewed: number | undefined, total: number | undefined): number => {
  const reviewedCount = Number(reviewed || 0)
  const totalCount = Number(total || 0)
  if (!Number.isFinite(reviewedCount) || !Number.isFinite(totalCount) || totalCount <= 0) {
    return 0
  }
  return Math.max(0, Math.min(100, (reviewedCount / totalCount) * 100))
}

const compactSha = (value: string | undefined): string => (value ? value.slice(0, 12) : 'no hash')

const compactBytes = (value: number | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return 'size n/a'
  }
  if (value >= 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`
  }
  return `${value} B`
}

const familyFloor = (summary: BenchmarkSummary, family: string): BenchmarkFamilyFloor | undefined =>
  summary.family_floors?.find((item) => item.family === family)

const isCurrentFullGap = (
  fullGap: PublicSmokeGapSummary | undefined,
  publicCoverage: PublicCoverageSummary | undefined,
): boolean =>
  Boolean(
    fullGap?.available &&
      publicCoverage?.total_items &&
      fullGap.samples &&
      Number(fullGap.samples) === Number(publicCoverage.total_items),
  )

function SemanticReviewCard({ title, review }: { title: string; review: DirectSemanticReviewSummary }) {
  const dimensions = Object.entries(review.dimensions_0_to_100 || {}).sort((left, right) => left[1] - right[1])
  const sourceStrata = Object.entries(review.by_source || {}).sort(
    (left, right) => (right[1].rows || 0) - (left[1].rows || 0),
  )
  const lowestRows = review.lowest_rows || []
  const dispositions = review.answer_disposition || {}
  return (
    <article className="semantic-review-card">
      <div className="semantic-review-heading">
        <div>
          <span>{title}</span>
          <strong>{review.available ? scoreText(review.semantic_mean) : 'Pending'}</strong>
        </div>
        <small>{review.rows || 0} answers</small>
      </div>
      {review.available ? (
        <>
          <div className="semantic-verdict-row">
            <span>{dispositions.pass || 0} pass</span>
            <span>{dispositions.revise || 0} revise</span>
            <span>{dispositions.fail || 0} fail</span>
          </div>
          <dl className="semantic-review-metrics">
            <div><dt>Proxy comparison</dt><dd>{scoreText(review.source_proxy_mean)}</dd></div>
            <div><dt>Proxy correlation</dt><dd>{scoreText(review.proxy_semantic_pearson ?? undefined, 3)}</dd></div>
            <div><dt>Source checks</dt><dd>{review.needs_source_validation || 0}</dd></div>
          </dl>
          {dimensions.length ? (
            <div className="semantic-dimensions" aria-label={`${title} semantic dimensions`}>
              {dimensions.slice(0, 5).map(([name, value]) => (
                <div key={name}>
                  <span>{readableLabel(name)}</span>
                  <strong>{scoreText(value, 1)}</strong>
                  <i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
                </div>
              ))}
            </div>
          ) : null}
          {sourceStrata.length ? (
            <div className="semantic-lowest-list" aria-label={`${title} source strata`}>
              <span>Source strata</span>
              {sourceStrata.map(([source, payload]) => (
                <div key={source}>
                  <strong>{scoreText(payload.semantic_score_mean, 1)}</strong>
                  <span>{readableLabel(source)}</span>
                  <small>{payload.rows || 0} answers</small>
                </div>
              ))}
            </div>
          ) : null}
          {lowestRows.length ? (
            <div className="semantic-lowest-list">
              <span>Lowest reviewed cases</span>
              {lowestRows.slice(0, 3).map((row) => (
                <div key={row.eval_id}>
                  <strong>{scoreText(row.score, 1)}</strong>
                  <span>{[row.crop, row.jurisdiction].filter(Boolean).join(' / ') || readableLabel(row.eval_id)}</span>
                  <small>{readableLabel(row.material_errors?.[0])}</small>
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : <p>Blinded semantic adjudication has not completed for this suite.</p>}
    </article>
  )
}

function ModelAdaptationPanel({
  readiness,
  loadStatus,
}: {
  readiness: ModelAdaptationReadiness
  loadStatus: string
}) {
  const experiments = readiness.experiments || []
  const rabbit = experiments.find((item) => item.id === 'gemma3_270m_task_rabbit_lora_v1')
  const e2b = experiments.find((item) => item.id === 'gemma4_e2b_agxqa_grounded_lora_v3')
  const blockers = readiness.blockers || []
  return (
    <section className="semantic-evidence-panel" data-testid="model-adaptation-readiness">
      <div className="semantic-evidence-heading">
        <div>
          <h2>Local adaptation decision</h2>
          <p>
            Hardware fit is separated from evidence quality. A narrow adapter win does not authorize the
            grower-facing answer path.
          </p>
        </div>
        <span>{readiness.available ? readableLabel(readiness.status) : 'Evidence unavailable'}</span>
      </div>
      {readiness.available ? (
        <>
          <div className="benchmark-cards">
            <article>
              <span>Conference model</span>
              <strong>{readiness.conference_answer_model?.model_id?.split('/').pop() || 'n/a'}</strong>
              <small>
                revision {readiness.conference_answer_model?.revision?.slice(0, 12) || 'n/a'} ·{' '}
                {readiness.conference_answer_model?.active_identity_matches_decision ? 'active match' : 'process mismatch'}
              </small>
            </article>
            <article>
              <span>New global LoRA</span>
              <strong>{readiness.new_global_lora_authorized ? 'Authorized' : 'Not authorized'}</strong>
              <small>{readableLabel(readiness.hardware_feasibility?.status)}</small>
            </article>
            <article>
              <span>Gemma 270M route adapter</span>
              <strong>{readableLabel(rabbit?.status)}</strong>
              <small>
                {scoreText(rabbit?.strict_json_rate)}% JSON · {countValue(rabbit?.safety_critical_omission_rows)} critical omissions
              </small>
            </article>
            <article>
              <span>Gemma E2B scoped adapter</span>
              <strong>{readableLabel(e2b?.status)}</strong>
              <small>
                +{scoreText(e2b?.document_disjoint_balanced_delta)} scoped · {countValue(e2b?.critical_regression_rows)} system regressions
              </small>
            </article>
          </div>
          <p className="semantic-evidence-boundary">
            Open gates: {blockers.map((item) => readableLabel(item.id)).join(' · ')}
          </p>
          {readiness.next_experiment?.authorized_scope ? (
            <p className="semantic-evidence-boundary">
              Next valid experiment: {readiness.next_experiment.authorized_scope}
            </p>
          ) : null}
        </>
      ) : <p>{readiness.message || loadStatus}</p>}
      <p className="semantic-evidence-boundary">{readiness.boundary}</p>
    </section>
  )
}

const benchmarkRows = (summary: BenchmarkSummary): BenchmarkEvidenceRow[] => {
  if (!summary.available) return []
  const metrics = summary.metrics || {}
  const precision = familyFloor(summary, 'regional_precision_ag')
  const soilWater = familyFloor(summary, 'regional_soil_water')
  const publicCoverage = summary.public_coverage
  const smokeGap = summary.public_smoke_gap
  const fullGap = summary.public_full_gap
  const claimStressFocus = summary.public_claim_stress_focus
  const matrix = summary.agentic_gap_matrix
  const rehearsal = summary.public_demo_rehearsal
  const heldout = summary.public_shadow_heldout
  const heldoutResult = summary.public_shadow_heldout_result
  const heldoutReview = summary.heldout_gap_review
  const reviewQueue = summary.human_review_queue
  const answerHygiene = summary.submission_answer_hygiene
  const reportVisualQa = summary.report_visual_qa
  const fullGapCurrent = isCurrentFullGap(fullGap, publicCoverage)
  const activeGap = fullGapCurrent ? fullGap : smokeGap
  const coverageTotal = publicCoverage?.total_items
  const activeGapReference = fullGapCurrent
    ? `${countValue(fullGap?.core_items)} core + ${countValue(fullGap?.expansion_items)} public probes`
    : fullGap?.available
      ? `Current full ${countValue(coverageTotal)} pending; latest full artifact has ${countValue(fullGap.samples)}/${countValue(coverageTotal)} rows`
      : 'Expansion-only stratified smoke'
  const domainCount = Object.keys(publicCoverage?.domain_counts || {}).length
  const laneCount = Object.keys(publicCoverage?.source_lane_counts || {}).length
  const topicCount = Object.keys(publicCoverage?.aiagribench_topic_category_counts || {}).length
  return [
    {
      suite: 'AI AgriBench proxy full live',
      samples: countValue(summary.samples),
      reference: 'Previous clean live: 97.92',
      current: `Final clean live: ${scoreText(summary.mean_score)}`,
      note: `${summary.under90_rows ?? 0} under-90 rows`,
    },
    {
      suite: 'Public-domain coverage screen',
      samples: countValue(publicCoverage?.total_items),
      reference: `${countValue(publicCoverage?.core_items)} core rows + ${countValue(publicCoverage?.expansion_items)} public probes`,
      current: `${countValue(topicCount || undefined)} AI-AgriBench topics / ${countValue(domainCount || undefined)} domains / ${countValue(laneCount || undefined)} source lanes`,
      note: 'not official AI AgriBench',
    },
    {
      suite: fullGapCurrent ? 'Public full coverage gap run' : 'Public smoke gap run',
      samples: countValue(activeGap?.samples),
      reference: activeGapReference,
      current: `Mean ${scoreText(activeGap?.mean_score)} / ${activeGap?.under90_rows ?? 0} under 90`,
      note: 'gap finder, not score claim',
    },
    {
      suite: 'Public claim-stress focus run',
      samples: claimStressFocus?.samples || 80,
      reference: '80 new source-boundary rows',
      current: `Mean ${scoreText(claimStressFocus?.mean_score)} / demo ${scoreText(claimStressFocus?.demo_quality_mean)}`,
      note: `${claimStressFocus?.flagged_missing_required ?? 0} missing flags · ${claimStressFocus?.demo_quality_under82_rows ?? 0} under demo floor`,
    },
    {
      suite: 'Official-style answer metrics',
      samples: summary.samples || 416,
      reference: 'Local proxy rubric',
      current: `Accuracy ${scoreText(metrics.accuracy)} / completeness ${scoreText(metrics.completeness)}`,
      note: `${summary.missing_required_flags ?? 0} missing-required flags`,
    },
    {
      suite: 'Agentic gap matrix',
      samples: countValue(matrix?.rows),
      reference: `${countValue(matrix?.raw_under90_rows)} raw under-90 rows`,
      current: `${countValue(matrix?.open_failures)} open / ${countValue(matrix?.repaired_contract_gaps)} repaired`,
      note: `${countValue(matrix?.tool_integration_review_rows)} tool-integration review rows`,
    },
    {
      suite: 'Human review queue',
      samples: reviewQueue?.queue_item_count || 807,
      reference: `${reviewQueue?.by_priority?.P0 ?? 122} P0 app checks`,
      current: `${reviewQueue?.by_priority?.P1 ?? 169} P1 quality checks / ${reviewQueue?.by_priority?.P2 ?? 516} P2 tool checks`,
      note: 'assignment packet, not score claim',
    },
    {
      suite: 'Submission answer hygiene',
      samples: answerHygiene?.row_count || 1597,
      reference: 'Official-run preflight over local artifacts',
      current: `${answerHygiene?.quality_warning_count ?? 439} warnings / ${answerHygiene?.high_risk_warning_count ?? 18} high risk`,
      note: 'style and leakage screen',
    },
    {
      suite: 'Report visual QA',
      samples: reportVisualQa?.svg_preview_count || 8,
      reference: reportVisualQa?.strict_svg_validation || 'strict SVG preview pass',
      current: reportVisualQa?.pdf_rerender_required ? 'PDF rerender open' : 'PDF render current',
      note: 'publication readiness, not score claim',
    },
    {
      suite: 'Public-demo rehearsal prompts',
      samples: rehearsal?.prompt_count || 122,
      reference: `${rehearsal?.context_count || 8} field contexts`,
      current: `${rehearsal?.adapter_lane_count || 38} source lanes · ${Object.keys(rehearsal?.public_source_lanes || {}).length || 38} lane checks`,
      note: 'human app review, not official score',
    },
    {
      suite: 'Held-out public shadow set',
      samples: countValue(heldout?.row_count),
      reference: `${countValue(heldout?.context_count)} contexts · held out from RAG repair`,
      current: `${countValue(heldout?.topic_category_count)} AI-AgriBench topics / ${countValue(heldout?.source_lane_count)} source lanes`,
      note: 'post-freeze transfer review',
    },
    {
      suite: 'Held-out public shadow run',
      samples: countValue(heldoutResult?.samples),
      reference: `${countValue(heldoutResult?.manifest_row_count ?? heldout?.row_count)} held-out rows`,
      current: heldoutResult?.available
        ? `Mean ${scoreText(heldoutResult.mean_score)} / ${heldoutResult.under90_rows ?? 0} under 90`
        : 'pending frozen run',
      note: heldoutResult?.is_complete_to_manifest ? 'complete transfer batch' : 'not a repair target',
    },
    {
      suite: 'Held-out gap review packet',
      samples: countValue(heldoutReview?.row_count),
      reference: `${countValue(heldoutReview?.source_samples ?? heldout?.row_count)} transfer rows`,
      current: `Selected mean ${scoreText(heldoutReview?.selected_mean_score)} / ${heldoutReview?.selected_under90_rows ?? 25} under 90`,
      note: 'human review only',
    },
    {
      suite: 'Regional precision economics',
      samples: precision?.samples || 22,
      reference: 'Prior bottom band: low 90s',
      current: `Mean ${scoreText(precision?.mean_score)} / floor ${scoreText(precision?.min_score)}`,
      note: 'soil tests, expected response, audit trail',
    },
    {
      suite: 'Regional soil-water floor',
      samples: soilWater?.samples || 70,
      reference: 'Remaining gap family',
      current: `Mean ${scoreText(soilWater?.mean_score)} / floor ${scoreText(soilWater?.min_score)}`,
      note: 'cover-crop water and compaction nuance',
    },
    {
      suite: 'Full-run generation latency',
      samples: countValue(summary.samples),
      reference: 'Quality profile, 480 max tokens',
      current: `Mean ${scoreText(summary.average_seconds)}s / max ${scoreText(summary.max_seconds)}s`,
      note: summary.model_id ? `Historical run · ${summary.model_id}` : 'Historical run · model identity unavailable',
    },
  ]
}

export function BenchmarksRoute() {
  const [canonicalBenchmark, setCanonicalBenchmark] = useState<CanonicalBenchmarkSummary>(fallbackCanonicalBenchmark)
  const [benchmarkSummary, setBenchmarkSummary] = useState<BenchmarkSummary>(fallbackBenchmarkSummary)
  const [benchmarkStatus, setBenchmarkStatus] = useState('Loading latest local artifact')
  const [adaptationReadiness, setAdaptationReadiness] = useState<ModelAdaptationReadiness>(
    fallbackModelAdaptationReadiness,
  )
  const [adaptationStatus, setAdaptationStatus] = useState('Loading model-adaptation readiness')
  const [freezeManifest, setFreezeManifest] = useState<FreezeManifest>(fallbackFreezeManifest)
  const [freezeStatus, setFreezeStatus] = useState('Loading freeze packet')
  const [rehearsalPacket, setRehearsalPacket] = useState<PublicDemoRehearsalPacket>(fallbackPublicDemoRehearsalPacket)
  const [reviewQueuePacket, setReviewQueuePacket] = useState<HumanReviewQueuePacket>(fallbackHumanReviewQueuePacket)
  const [reviewOutcomeSummary, setReviewOutcomeSummary] = useState<HumanReviewOutcomeSummary>({ available: false })
  const [acceptanceChecklist, setAcceptanceChecklist] = useState<PublicDemoAcceptanceChecklist>(
    fallbackPublicDemoAcceptanceChecklist,
  )
  const [acceptanceLoadStatus, setAcceptanceLoadStatus] = useState('Loading public-demo acceptance gates')
  const [liveSourceQaPacket, setLiveSourceQaPacket] = useState<LiveSourceQaPacket | null>(null)
  const [liveSourceQaLoadStatus, setLiveSourceQaLoadStatus] = useState('Loading live-source QA packet')
  const rows = useMemo(() => benchmarkRows(benchmarkSummary), [benchmarkSummary])
  const publicCoverage = benchmarkSummary.public_coverage
  const fullGap = benchmarkSummary.public_full_gap
  const smokeGap = benchmarkSummary.public_smoke_gap
  const claimStressFocus =
    benchmarkSummary.public_claim_stress_focus || fallbackBenchmarkSummary.public_claim_stress_focus
  const fullGapCurrent = isCurrentFullGap(fullGap, publicCoverage)
  const activeGap = fullGapCurrent ? fullGap : smokeGap
  const gapMatrix = benchmarkSummary.agentic_gap_matrix
  const reviewQueue: HumanReviewQueueSummary =
    benchmarkSummary.human_review_queue || fallbackBenchmarkSummary.human_review_queue || { available: false }
  const reviewOutcomes: HumanReviewOutcomeSummary =
    reviewOutcomeSummary.available
      ? reviewOutcomeSummary
      : benchmarkSummary.human_review_outcomes || fallbackBenchmarkSummary.human_review_outcomes || { available: false }
  const answerHygiene: SubmissionAnswerHygieneSummary =
    benchmarkSummary.submission_answer_hygiene || fallbackBenchmarkSummary.submission_answer_hygiene || { available: false }
  const submissionDryRun: AiAgribenchSubmissionDryRunSummary =
    benchmarkSummary.aiagribench_submission_dry_run ||
    fallbackBenchmarkSummary.aiagribench_submission_dry_run ||
    { available: false }
  const reportVisualQa: ReportVisualQaSummary =
    benchmarkSummary.report_visual_qa || fallbackBenchmarkSummary.report_visual_qa || { available: false }
  const heldoutSummary: PublicShadowHeldoutSummary =
    benchmarkSummary.public_shadow_heldout || fallbackBenchmarkSummary.public_shadow_heldout || { available: false }
  const heldoutGapReview: HeldoutGapReviewSummary =
    benchmarkSummary.heldout_gap_review || fallbackBenchmarkSummary.heldout_gap_review || { available: false }
  const directSemantic: DirectSemanticReviewSummary =
    benchmarkSummary.direct_semantic_review || fallbackBenchmarkSummary.direct_semantic_review || { available: false }
  const canadianSemantic: DirectSemanticReviewSummary =
    benchmarkSummary.canadian_semantic_review || fallbackBenchmarkSummary.canadian_semantic_review || { available: false }
  const primarySemantic = canadianSemantic.available ? canadianSemantic : directSemantic
  const freezeArtifacts = useMemo(
    () => [...(freezeManifest.artifacts || []), ...(freezeManifest.corpora || []).slice(0, 4), ...(freezeManifest.graphs || [])].slice(0, 10),
    [freezeManifest],
  )
  const activeGapLabel = fullGapCurrent ? 'Full gap mean' : 'Smoke gap mean'
  const activeGapTitle = fullGapCurrent ? 'Public-domain full coverage gaps' : 'Public-domain smoke gaps'
  const activeGapHasOpenMisses = Boolean((activeGap?.under90_rows ?? 0) > 0 || (activeGap?.flagged_missing_required ?? 0) > 0)
  const rehearsalPrompts = rehearsalPacket.prompts || []
  const rehearsalLaneCount = Object.keys(rehearsalPacket.public_source_lanes || {}).length || rehearsalPacket.adapter_lane_count || 0
  const activeGapDescription = fullGapCurrent
    ? activeGapHasOpenMisses
      ? 'This is the full expanded public-domain coverage screen, not an official AI AgriBench score. It shows which domains and source lanes still need better evidence, answer contracts, or tool integration across the core proxy plus public expansion rows.'
      : 'This is the full expanded public-domain coverage screen, not an official AI AgriBench score. The repaired artifact has no under-90 rows or missing-required flags; the lowest lanes are now human-review targets for usefulness, source clarity, and live-tool integration.'
    : fullGap?.available
      ? `The latest full shadow artifact covers ${countValue(fullGap.samples)}/${countValue(publicCoverage?.total_items)} rows, so this panel is using the current ${countValue(smokeGap?.samples)}-row smoke screen until the full ${countValue(publicCoverage?.total_items)}-row run is regenerated.`
      : `This is the current gap-finding run, not the full ${countValue(publicCoverage?.total_items)}-row suite and not an official score. It tells us which public agronomy lanes still need better source context, answer contracts, or tool integration.`
  const reviewQueueItems = reviewQueuePacket.items || []
  const reviewActions =
    reviewOutcomes.next_actions?.length
      ? reviewOutcomes.next_actions
      : ['Start with the quickstart smoke batch and record outcomes in the outcome CSV.']
  const reviewBatches =
    reviewOutcomes.review_batches?.length
      ? reviewOutcomes.review_batches
      : fallbackBenchmarkSummary.human_review_outcomes?.review_batches || []
  const reviewBlockers = reviewOutcomes.top_blockers || []
  const reviewRecordIssues = reviewOutcomes.review_record_issues || []
  const acceptanceCurrent = acceptanceChecklist.current_status || fallbackPublicDemoAcceptanceChecklist.current_status || {}
  const acceptanceGoNoGo = acceptanceChecklist.go_no_go || fallbackPublicDemoAcceptanceChecklist.go_no_go || {}
  const acceptanceReviewPlan = acceptanceChecklist.review_plan || fallbackPublicDemoAcceptanceChecklist.review_plan || []
  const acceptanceVisualQa =
    acceptanceChecklist.visual_qa_plan || fallbackPublicDemoAcceptanceChecklist.visual_qa_plan || {}
  const acceptanceCommands = acceptanceChecklist.commands || fallbackPublicDemoAcceptanceChecklist.commands || {}
  const acceptanceOpenGates = acceptanceCurrent.open_gate_ids || []
  const acceptanceAutomatedBlockers = acceptanceCurrent.automated_blocker_ids || []
  const acceptanceFirstReview = acceptanceReviewPlan[0]
  const liveSourceQaGoNoGo = liveSourceQaPacket?.demo_go_no_go || {}
  const liveSourceQaSummary = liveSourceQaPacket?.readiness_summary || {}
  const liveSourceCredentialLabels = (liveSourceQaPacket?.credential_blockers || [])
    .map((item) => item.label || item.id)
    .filter(Boolean)
  const liveSourceMonitorLabels = (liveSourceQaPacket?.monitor_only_lanes || [])
    .map((item) => item.label || item.id)
    .filter(Boolean)
  const acceptanceCommandRows = [
    ['Smoke preflight', acceptanceCommands.human_smoke_preflight],
    ['Ingest reviewed batch', acceptanceCommands.ingest_filled_batch],
    ['Readiness gate', acceptanceCommands.readiness],
  ].filter(([, command]) => command)
  const hygieneActions =
    answerHygiene.next_actions?.length
      ? answerHygiene.next_actions
      : ['Run the submission answer hygiene audit before sending any answer-only benchmark file.']

  useEffect(() => {
    let active = true
    apiGet<CanonicalBenchmarkSummary>('/api/benchmarks/open-agronomy/latest')
      .then((summary) => {
        if (active) setCanonicalBenchmark(summary)
      })
      .catch(() => {
        if (active) setCanonicalBenchmark(fallbackCanonicalBenchmark)
      })
    apiGet<ModelAdaptationReadiness>('/api/models/adaptation-readiness')
      .then((readiness) => {
        if (!active) return
        setAdaptationReadiness(readiness)
        setAdaptationStatus(
          readiness.available
            ? 'Loaded hash-bound adaptation decision'
            : readiness.message || 'Adaptation evidence unavailable',
        )
      })
      .catch(() => {
        if (!active) return
        setAdaptationReadiness(fallbackModelAdaptationReadiness)
        setAdaptationStatus('Model-adaptation readiness evidence unavailable')
      })
    apiGet<BenchmarkSummary>('/api/benchmarks/aiagribench-proxy/latest')
      .then((summary) => {
        if (!active) {
          return
        }
        if (summary.available) {
          setBenchmarkSummary(summary)
          setBenchmarkStatus(`Loaded ${summary.run_id || 'latest local run'}`)
        } else {
          setBenchmarkStatus(summary.message || 'Benchmark evidence unavailable')
        }
      })
      .catch(() => {
        if (active) {
          setBenchmarkStatus('Benchmark evidence unavailable; no score snapshot is substituted')
        }
      })
    apiGet<FreezeManifest>('/api/benchmarks/aiagribench-proxy/freeze-manifest')
      .then((manifest) => {
        if (!active) {
          return
        }
        setFreezeManifest(manifest)
        setFreezeStatus(`Loaded ${manifest.schema_version}`)
      })
      .catch(() => {
        if (active) {
          setFreezeStatus('Freeze packet evidence unavailable')
        }
      })
    apiGet<PublicDemoRehearsalPacket>('/api/benchmarks/public-demo-rehearsal?limit=6')
      .then((packet) => {
        if (!active) {
          return
        }
        if (packet.available) {
          setRehearsalPacket(packet)
        }
      })
      .catch(() => {
        if (active) {
          setRehearsalPacket(fallbackPublicDemoRehearsalPacket)
        }
      })
    apiGet<HumanReviewQueuePacket>('/api/benchmarks/human-review-queue?limit=6')
      .then((packet) => {
        if (!active) {
          return
        }
        if (packet.available) {
          setReviewQueuePacket(packet)
        }
      })
      .catch(() => {
        if (active) {
          setReviewQueuePacket(fallbackHumanReviewQueuePacket)
        }
      })
    apiGet<HumanReviewOutcomeSummary>('/api/benchmarks/human-review-outcomes')
      .then((summary) => {
        if (active && summary.available) {
          setReviewOutcomeSummary(summary)
        }
      })
      .catch(() => {
        if (active) {
          setReviewOutcomeSummary({ available: false })
        }
      })
    apiGet<PublicDemoAcceptanceChecklist>(benchmarkArtifactHref('public-demo-acceptance-checklist-json'))
      .then((checklist) => {
        if (!active) {
          return
        }
        if (checklist.current_status || checklist.go_no_go) {
          setAcceptanceChecklist(checklist)
          setAcceptanceLoadStatus(`Loaded ${checklist.schema_version || 'public-demo acceptance checklist'}`)
        }
      })
      .catch(() => {
        if (active) {
          setAcceptanceChecklist(fallbackPublicDemoAcceptanceChecklist)
          setAcceptanceLoadStatus('Public-demo acceptance evidence unavailable')
        }
      })
    apiGet<LiveSourceQaPacket>(benchmarkArtifactHref('live-source-qa-packet-json'))
      .then((packet) => {
        if (!active) {
          return
        }
        if (packet.demo_go_no_go || packet.readiness_summary) {
          setLiveSourceQaPacket(packet)
          setLiveSourceQaLoadStatus(`Loaded ${packet.schema_version || 'live-source QA packet'}`)
        }
      })
      .catch(() => {
        if (active) {
          setLiveSourceQaPacket(null)
          setLiveSourceQaLoadStatus('Live-source QA packet unavailable')
        }
      })
    return () => {
      active = false
    }
  }, [])

  if (!benchmarkSummary.available && !canonicalBenchmark.available) {
    return (
      <div className="performance-page">
        <section className="performance-hero">
          <div className="panel-kicker">Benchmarks</div>
          <h2>Evidence is loading or unavailable</h2>
          <p>{benchmarkStatus}. No saved counts, scores, or model identity are substituted when the evidence API cannot load.</p>
        </section>
        <ModelAdaptationPanel readiness={adaptationReadiness} loadStatus={adaptationStatus} />
      </div>
    )
  }

  return (
    <div className="performance-page">
      <section className="performance-hero">
        <div className="panel-kicker">Benchmarks</div>
        <h2>Canadian development suite and external transfer diagnostic</h2>
        <p>
          The project-owned internal suite supports model and system development. A separately frozen AgroQA sample checks
          transfer on real farmer questions from Uganda; it is not Canadian field validation or a certification exam.
        </p>
        <div className="benchmark-status">
          <span>{canonicalBenchmark.available ? canonicalBenchmark.benchmark_id : benchmarkStatus}</span>
          <span>No question mixing, no public-set tuning loop, and no grand score. Grower usefulness still requires field confirmation.</span>
        </div>
        <div className="benchmark-cards">
          <article>
            <span>Internal questions</span>
            <strong>{countValue(canonicalBenchmark.rows)}</strong>
            <small>{countValue(canonicalBenchmark.unique_questions)} unique · {canonicalBenchmark.exact_duplicate_questions ?? 0} duplicates</small>
          </article>
          <article>
            <span>Canadian decisions</span>
            <strong>{countValue(canonicalBenchmark.lane_counts?.canadian_decision_quality)}</strong>
            <small>primary synthetic lane · agronomist review required</small>
          </article>
          <article>
            <span>Field history</span>
            <strong>{countValue(canonicalBenchmark.lane_counts?.field_history_lineage)}</strong>
            <small>saved context, corrections, and answer lineage</small>
          </article>
          <article>
            <span>External transfer</span>
            <strong>{countValue(canonicalBenchmark.external_diagnostic?.rows)}</strong>
            <small>AgroQA farmer questions · Uganda · diagnostic only</small>
          </article>
          <article>
            <span>Partition audit</span>
            <strong>{canonicalBenchmark.external_diagnostic?.separation_status === 'pass' ? 'Pass' : 'Blocked'}</strong>
            <small>{canonicalBenchmark.external_diagnostic?.exact_overlap ?? '—'} exact · {canonicalBenchmark.external_diagnostic?.near_overlap ?? '—'} near overlaps</small>
          </article>
          <article>
            <span>Canonical database</span>
            <strong>{canonicalBenchmark.database_available ? 'Ready' : 'Not run'}</strong>
            <small>paired answers and lineage stay machine-local</small>
          </article>
        </div>
      </section>
      <details className="historical-benchmark-disclosure">
        <summary>
          Historical research evidence
          <span>Legacy proxy, submission, and whitepaper artifacts · not the current benchmark</span>
        </summary>
        <div className="historical-benchmark-content">
      <ModelAdaptationPanel readiness={adaptationReadiness} loadStatus={adaptationStatus} />
      <section className="semantic-evidence-panel" data-testid="semantic-evidence-panel">
        <div className="semantic-evidence-heading">
          <div>
            <h2>Semantic answer review</h2>
            <p>
              Agronomic correctness is judged independently from keyword contracts and tool traces. The Canadian
              reserve measures current conference scope; the broad review measures the answered legacy packet.
            </p>
          </div>
          <span>No composite score</span>
        </div>
        <div className="semantic-review-grid">
          <SemanticReviewCard title="Canadian reserve" review={canadianSemantic} />
          <SemanticReviewCard title="Broad answer packet" review={directSemantic} />
        </div>
        <p className="semantic-evidence-boundary">
          These suites differ in age, difficulty, and question construction. Compare failure patterns and dispositions,
          not the headline means as though they were interchangeable leaderboard estimates.
        </p>
      </section>
      <section className="score-table">
        <h2>Current evidence snapshot</h2>
        <table>
          <thead>
            <tr>
              <th>Suite</th>
              <th>Rows</th>
              <th>Reference</th>
              <th>Current</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.suite}>
                <td data-label="Suite">{row.suite}</td>
                <td data-label="Rows">{row.samples}</td>
                <td data-label="Reference">{row.reference}</td>
                <td data-label="Current">{row.current}</td>
                <td data-label="Note">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="rehearsal-panel">
        <div className="rehearsal-heading">
          <div>
            <h2>Public-demo rehearsal packet</h2>
            <p>
              These prompts turn the source-lane coverage work into a human app test: drop a point, draw or upload a
              field, ask the question, and confirm the answer shows the expected public evidence without overclaiming.
            </p>
            <small>{repoRelativePath(rehearsalPacket.markdown_path || rehearsalPacket.suite_path)}</small>
          </div>
          <span>{rehearsalPacket.official_ai_agribench ? 'official' : 'not official AI AgriBench'}</span>
        </div>
        <div className="rehearsal-stats">
          <article>
            <span>Prompts</span>
            <strong>{rehearsalPacket.prompt_count || rehearsalPrompts.length}</strong>
            <small>{rehearsalPacket.prompt_count_returned} shown here</small>
          </article>
          <article>
            <span>Field contexts</span>
            <strong>{rehearsalPacket.context_count || Object.keys(rehearsalPacket.contexts || {}).length}</strong>
            <small>map-first review cases</small>
          </article>
          <article>
            <span>Source lanes</span>
            <strong>{rehearsalLaneCount}</strong>
            <small>adapter/evidence checks</small>
          </article>
        </div>
        <div className="rehearsal-prompt-list">
          {rehearsalPrompts.slice(0, 6).map((prompt, index) => (
            <article key={prompt.prompt_id || `${prompt.context_id}-${index}`}>
              <div className="rehearsal-prompt-meta">
                <span>{readableLabel(prompt.workflow)}</span>
                <span>{prompt.source_lane_label || readableLabel(prompt.public_source_lane)}</span>
              </div>
              <strong>{prompt.context_label || readableLabel(prompt.context_id)}</strong>
              <p>{prompt.question}</p>
              <small>
                Expected: {(prompt.expected_public_adapters || []).join(', ') || readableLabel(prompt.public_source_lane)}
              </small>
              <small>
                Visible evidence: {(prompt.expected_visible_evidence || []).slice(0, 3).join(' · ') || 'source card and boundary note'}
              </small>
              {prompt.release_blocking_failure ? <em>{prompt.release_blocking_failure}</em> : null}
            </article>
          ))}
        </div>
        <p className="rehearsal-boundary">
          {rehearsalPacket.boundary || rehearsalPacket.source_boundaries?.[0] || rehearsalPacket.score_warning}
        </p>
      </section>
      <section className="smoke-gap-panel">
        <div>
          <h2>{activeGapTitle}</h2>
          <p>{activeGapDescription}</p>
          <small>{repoRelativePath(activeGap?.markdown_report_path || activeGap?.report_path)}</small>
        </div>
        <div className="smoke-domain-list">
          {(activeGap?.low_domains || []).slice(0, 6).map((domain) => (
            <article key={domain.domain}>
              <strong>{domain.domain.replace(/_/g, ' ')}</strong>
              <span>mean {scoreText(domain.mean_score)} · floor {scoreText(domain.min_score)}</span>
              <small>{domain.flagged_missing_required ?? 0} rows with missing required evidence</small>
            </article>
          ))}
        </div>
      </section>
      <section className="agentic-gap-panel heldout-gap-review-panel" data-testid="heldout-gap-review">
        <div className="agentic-gap-summary">
          <div>
            <h2>Held-out gap review</h2>
            <p>
              The latest held-out public shadow run is complete transfer evidence, but the weak rows are not repair
              targets. This packet ranks the rows a human should inspect before we make public quality claims.
            </p>
            <small>{repoRelativePath(heldoutGapReview.markdown_path || heldoutGapReview.csv_path)}</small>
          </div>
          <div className="hygiene-downloads">
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('heldout-gap-review-csv')}
              download="open-agronomy-agent-heldout-gap-review.csv"
            >
              Review CSV
            </a>
            <a
              className="manifest-link secondary"
              href={benchmarkArtifactHref('heldout-gap-review-markdown')}
              download="open-agronomy-agent-heldout-gap-review.md"
            >
              Review notes
            </a>
            <a
              className="manifest-link secondary"
              href={benchmarkArtifactHref('heldout-gap-review-json')}
              download="open-agronomy-agent-heldout-gap-review.json"
            >
              Review JSON
            </a>
          </div>
        </div>
        <div className="agentic-gap-stats">
          <article>
            <span>Review rows</span>
            <strong>{heldoutGapReview.row_count ?? 0}</strong>
            <small>{heldoutGapReview.source_samples ?? heldoutSummary.row_count ?? 45} held-out source rows</small>
          </article>
          <article>
            <span>Source mean</span>
            <strong>{scoreText(heldoutGapReview.source_mean_score)}</strong>
            <small>{heldoutGapReview.source_under90_rows ?? 0} source rows under 90</small>
          </article>
          <article>
            <span>Selected mean</span>
            <strong>{scoreText(heldoutGapReview.selected_mean_score)}</strong>
            <small>{heldoutGapReview.selected_missing_required_rows ?? 0} missing-evidence rows</small>
          </article>
          <article>
            <span>Boundary</span>
            <strong>{heldoutGapReview.available ? 'Review only' : 'Pending'}</strong>
            <small>not training, prompt, RAG/KG, or regex repair data</small>
          </article>
        </div>
        <div className="agentic-gap-lists">
          <div>
            <h3>Top missing patterns</h3>
            {(heldoutGapReview.top_missing_required_patterns || []).slice(0, 5).map(([pattern, count]) => (
              <article key={pattern}>
                <strong>{pattern}</strong>
                <span>{count} rows</span>
                <small>review whether the answer still protects the user without this exact phrase</small>
              </article>
            ))}
          </div>
          <div>
            <h3>Review lanes</h3>
            {Object.entries(heldoutGapReview.by_public_source_lane || {})
              .slice(0, 5)
              .map(([lane, count]) => (
                <article key={lane}>
                  <strong>{lane.replace(/_/g, ' ')}</strong>
                  <span>{count} weak rows</span>
                  <small>inspect source-boundary honesty and grower usefulness</small>
                </article>
              ))}
          </div>
        </div>
        <p className="agentic-gap-boundary">
          {heldoutGapReview.quality_risk_note || heldoutGapReview.score_warning || 'Held-out gap review is human transfer review only.'}
        </p>
      </section>
      <section className="agentic-gap-panel">
        <div className="agentic-gap-summary">
          <div>
            <h2>Agentic gap matrix</h2>
            <p>
              This turns the proxy and public shadow traces into implementation targets: open failures, repaired
              answer-contract gaps, low-floor rows for human review, and source/tool lanes that still need app-level
              verification.
            </p>
            <small>{repoRelativePath(gapMatrix?.markdown_path)}</small>
          </div>
          <div className="agentic-gap-stats">
            <article>
              <span>Open</span>
              <strong>{gapMatrix?.open_failures ?? 0}</strong>
              <small>current failures</small>
            </article>
            <article>
              <span>Repaired</span>
              <strong>{gapMatrix?.repaired_contract_gaps ?? 0}</strong>
              <small>raw failures now clean</small>
            </article>
            <article>
              <span>Tool review</span>
              <strong>{gapMatrix?.tool_integration_review_rows ?? 0}</strong>
              <small>source-card checks</small>
            </article>
            <article>
              <span>Planned lanes</span>
              <strong>{gapMatrix?.planned_source_lane_review_rows ?? 0}</strong>
              <small>jurisdiction checks</small>
            </article>
            <article>
              <span>Backlog</span>
              <strong>{gapMatrix?.source_gap_backlog_rows ?? 0}</strong>
              <small>source lanes to build</small>
            </article>
          </div>
        </div>
        <div className="agentic-gap-lists">
          <div>
            <h3>Lowest current rows</h3>
            {(gapMatrix?.lowest_current_rows || []).slice(0, 5).map((row) => (
              <article key={`lowest-${row.eval_id}`}>
                <strong>{scoreText(row.current_score)} · {row.coverage_domain?.replace(/_/g, ' ')}</strong>
                <span>{row.public_source_lane?.replace(/_/g, ' ')}</span>
                <small>{row.recommended_action}</small>
              </article>
            ))}
          </div>
          <div>
            <h3>Largest repairs</h3>
            {(gapMatrix?.highest_raw_to_current_repairs || []).slice(0, 5).map((row) => (
              <article key={`repair-${row.eval_id}`}>
                <strong>+{scoreText(row.score_delta)} · {row.coverage_domain?.replace(/_/g, ' ')}</strong>
                <span>{scoreText(row.raw_score)} to {scoreText(row.current_score)} · {row.scenario_type?.replace(/_/g, ' ')}</span>
                <small>{row.public_source_lane?.replace(/_/g, ' ')}</small>
              </article>
            ))}
          </div>
        </div>
        <p className="agentic-gap-boundary">
          {gapMatrix?.score_warning || 'Local diagnostic matrix; not an official AI AgriBench score.'}
        </p>
      </section>
      <section className="agentic-gap-panel">
        <div className="agentic-gap-summary">
          <div>
            <h2>Human review queue</h2>
            <p>
              This is the actual assignment packet for the next freeze: public-demo workflow checks, held-out transfer
              rows, repaired contract gaps, low-floor answer reviews, and tool/source-card verification in one place.
            </p>
            <small>{repoRelativePath(reviewQueue.markdown_path || reviewQueue.queue_path)}</small>
          </div>
          <div className="agentic-gap-stats">
            <article>
              <span>P0</span>
              <strong>{reviewQueue.by_priority?.P0 ?? 0}</strong>
              <small>first review batch</small>
            </article>
            <article>
              <span>P1</span>
              <strong>{reviewQueue.by_priority?.P1 ?? 0}</strong>
              <small>quality sample next</small>
            </article>
            <article>
              <span>P2</span>
              <strong>{reviewQueue.by_priority?.P2 ?? 0}</strong>
              <small>tool/source cards</small>
            </article>
          </div>
        </div>
        <div className="agentic-gap-stats">
          <article>
            <span>Reviewed</span>
            <strong>{reviewOutcomes.reviewed_count ?? 0}/{reviewOutcomes.queue_item_count ?? reviewQueue.queue_item_count ?? 807}</strong>
            <small>{reviewOutcomes.p0_reviewed ?? 0}/{reviewOutcomes.p0_total ?? 122} P0 complete</small>
          </article>
          <article>
            <span>Demo gate</span>
            <strong>{reviewOutcomes.public_demo_gate?.status || 'needs_review'}</strong>
            <small>
              {reviewOutcomes.blocking_issue_count ?? 0} blockers · {reviewOutcomes.p0_review_record_issue_count ?? 0} P0 record issues
            </small>
          </article>
          <article>
            <span>Quality gate</span>
            <strong>{reviewOutcomes.quality_claim_gate?.status || 'needs_review'}</strong>
            <small>{reviewOutcomes.review_record_issue_count ?? 0} record issues · {repoRelativePath(reviewOutcomes.template_path)}</small>
          </article>
        </div>
        <div className="acceptance-status-panel" data-testid="public-demo-acceptance-panel">
          <div className="review-panel-heading">
            <span>Acceptance status</span>
            <strong>{acceptanceCurrent.automated_gate_passed ? 'Automated gate passed' : 'Automated gate pending'}</strong>
          </div>
          <p className="acceptance-status-note">
            {acceptanceLoadStatus}. This is the local go/no-go surface for the public demo, quality claims, and
            official AI AgriBench rehearsal; hidden official questions stay outside tracked corpora.
          </p>
          <div className="acceptance-gate-grid">
            {[
              { label: 'Public demo', gate: acceptanceGoNoGo.public_demo, ready: acceptanceCurrent.public_demo_ready },
              { label: 'Quality claim', gate: acceptanceGoNoGo.quality_claim, ready: acceptanceCurrent.quality_claim_ready },
              {
                label: 'AI AgriBench submission',
                gate: acceptanceGoNoGo.aiagribench_submission,
                ready: acceptanceCurrent.aiagribench_submission_ready,
              },
            ].map((item) => {
              const gateStatus = item.ready ? 'go' : item.gate?.status || 'needs_review'
              const blockers = item.gate?.blocking_gate_ids || []
              return (
                <article key={item.label} className={`acceptance-gate acceptance-gate-${reviewStatusClass(gateStatus)}`}>
                  <span>{item.label}</span>
                  <strong>{readableLabel(gateStatus)}</strong>
                  <small>
                    {blockers.length
                      ? `${blockers.length} blocking gates: ${blockers.slice(0, 3).map(readableLabel).join(', ')}`
                      : 'No blocking gates logged'}
                  </small>
                </article>
              )
            })}
          </div>
          <div className="acceptance-readiness-grid" data-testid="live-source-qa-panel">
            <article>
              <span>Live source QA</span>
              <strong>{readableLabel(liveSourceQaGoNoGo.status || 'loading')}</strong>
              <small>{liveSourceQaLoadStatus}</small>
            </article>
            <article>
              <span>Offline smoke</span>
              <strong>{readableLabel(liveSourceQaGoNoGo.offline_smoke_gate || 'unknown')}</strong>
              <small>
                {liveSourceQaSummary.smoke_passed_count ?? 0}/{liveSourceQaSummary.smoke_check_count ?? 0} smoke suites ·{' '}
                {(liveSourceQaSummary.smoke_failed_count ?? 0) + (liveSourceQaSummary.smoke_missing_count ?? 0)} open
              </small>
            </article>
            <article>
              <span>Keyed lanes</span>
              <strong>{liveSourceQaPacket?.credential_blockers?.length ?? liveSourceQaSummary.needs_key_count ?? 0}</strong>
              <small>
                {liveSourceCredentialLabels.length
                  ? liveSourceCredentialLabels.slice(0, 2).join(', ')
                  : 'No missing credential lanes logged'}
              </small>
            </article>
            <article>
              <span>Regional matrix</span>
              <strong>{liveSourceQaPacket?.regional_matrix?.adapter_case_count ?? 0}</strong>
              <small>
                {liveSourceQaPacket?.regional_matrix?.context_count ?? 0} contexts ·{' '}
                {liveSourceMonitorLabels.length || liveSourceQaSummary.monitor_count || 0} monitor lanes
              </small>
            </article>
          </div>
          <div className="acceptance-readiness-grid">
            <article>
              <span>Open gates</span>
              <strong>{acceptanceOpenGates.length}</strong>
              <small>
                {acceptanceOpenGates.length
                  ? acceptanceOpenGates.slice(0, 5).map(readableLabel).join(', ')
                  : 'No open gates logged'}
              </small>
            </article>
            <article>
              <span>First reviewer batch</span>
              <strong>
                {acceptanceFirstReview?.reviewed_count ?? 0}/{acceptanceFirstReview?.row_count ?? 0}
              </strong>
              <small>{acceptanceFirstReview?.label || 'Quickstart smoke app review'}</small>
            </article>
            <article>
              <span>Visual QA</span>
              <strong>{acceptanceVisualQa.pdf_current ? 'PDF current' : 'PDF gate open'}</strong>
              <small>
                SVG/HTML {acceptanceVisualQa.svg_html_current ? 'current' : 'pending'} · PDF{' '}
                {readableLabel(acceptanceVisualQa.pdf_render_status || 'pending')}
              </small>
            </article>
            <article>
              <span>Automated blockers</span>
              <strong>{acceptanceAutomatedBlockers.length}</strong>
              <small>
                {acceptanceAutomatedBlockers.length
                  ? acceptanceAutomatedBlockers.slice(0, 4).map(readableLabel).join(', ')
                  : 'Automated readiness gate is clean'}
              </small>
            </article>
          </div>
          <div className="acceptance-command-list">
            {acceptanceCommandRows.map(([label, command]) => (
              <article key={label}>
                <span>{label}</span>
                <code>{command}</code>
              </article>
            ))}
          </div>
        </div>
        <div className="review-execution-checklist" data-testid="human-review-execution-checklist">
          <div className="review-panel-heading">
            <span>Reviewer runbook</span>
            <strong>Quickstart smoke to gate check</strong>
          </div>
          <ol>
            <li>
              <strong>Download the quickstart batch and outcome CSV.</strong>
              <span>Use the links below before running the full 122-row P0 batch.</span>
            </li>
            <li>
              <strong>Run each row through the Map, Field, and Ask workflow.</strong>
              <span>Confirm the Data availability panel, trace groups, regional context, source cards, and final answer all agree.</span>
            </li>
            <li>
              <strong>Export evidence for any questionable turn.</strong>
              <span>Use Copy review report or Download .md from the chat answer before logging a blocker.</span>
            </li>
            <li>
              <strong>Fill outcome fields for every reviewed row.</strong>
              <span>Reviewer, device, field/file, visible status steps, evidence cards, result, severity, and expected behavior are required for useful records.</span>
            </li>
            <li>
              <strong>Preflight the filled batch before ingest.</strong>
              <code>preflight_human_review_batch.py --batch-csv human_review_batch_quickstart_smoke.csv</code>
            </li>
            <li>
              <strong>Ingest the filled batch and refresh gates.</strong>
              <code>ingest_human_review_batch.py --batch-csv human_review_batch_quickstart_smoke.csv</code>
            </li>
            <li>
              <strong>Check gates before making public claims.</strong>
              <span>Public demo stays closed until all P0 rows pass without release/demo blockers.</span>
            </li>
          </ol>
        </div>
        <div className="review-operations" data-testid="human-review-ops">
          <div className="review-action-panel">
            <div className="review-panel-heading">
              <span>Next reviewer action</span>
              <strong>{reviewOutcomes.public_demo_gate?.status === 'pass' ? 'Quality gate work' : 'Public-demo gate work'}</strong>
            </div>
            <ol className="review-action-list">
              {reviewActions.slice(0, 4).map((action, index) => (
                <li key={`${index}-${action}`}>{compactReviewAction(action)}</li>
              ))}
            </ol>
            <div className="review-artifact-grid">
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('public-demo-acceptance-checklist')}
                download="open-agronomy-agent-public-demo-acceptance-checklist.md"
              >
                Acceptance checklist
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('public-demo-acceptance-checklist-json')}
                download="open-agronomy-agent-public-demo-acceptance-checklist.json"
              >
                Acceptance JSON
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('live-source-qa-packet')}
                download="open-agronomy-agent-live-source-qa-packet.md"
              >
                Live source QA
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('live-source-qa-packet-json')}
                download="open-agronomy-agent-live-source-qa-packet.json"
              >
                Live source JSON
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('live-source-qa-packet-builder')}
                download="open-agronomy-agent-build-live-source-qa-packet.py"
              >
                Live source builder
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('mobile-app-qa-packet')}
                download="open-agronomy-agent-mobile-app-qa-packet.md"
              >
                Mobile QA
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('mobile-app-qa-packet-json')}
                download="open-agronomy-agent-mobile-app-qa-packet.json"
              >
                Mobile QA JSON
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('mobile-app-qa-packet-builder')}
                download="open-agronomy-agent-build-mobile-app-qa-packet.py"
              >
                Mobile QA builder
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('public-demo-artifact-bundle-manifest')}
                download="open-agronomy-agent-public-demo-artifact-bundle-manifest.md"
              >
                Artifact bundle
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('public-demo-artifact-bundle-manifest-json')}
                download="open-agronomy-agent-public-demo-artifact-bundle-manifest.json"
              >
                Bundle JSON
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('public-demo-artifact-bundle-builder')}
                download="open-agronomy-agent-build-public-demo-artifact-bundle.py"
              >
                Bundle builder
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-review-quickstart')}
                download="open-agronomy-agent-human-review-quickstart.md"
              >
                Reviewer quickstart
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-user-test-script')}
                download="open-agronomy-agent-human-user-test-script.md"
              >
                Human test script
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-smoke-preflight-markdown')}
                download="open-agronomy-agent-human-smoke-preflight.md"
              >
                Smoke preflight
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-smoke-preflight')}
                download="open-agronomy-agent-human-smoke-preflight.json"
              >
                Preflight JSON
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('public-demo-rehearsal-prompts')}
                download="open-agronomy-agent-public-demo-rehearsal-prompts.jsonl"
              >
                Rehearsal prompts
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-review-queue-jsonl')}
                download="open-agronomy-agent-human-review-queue.jsonl"
              >
                Review queue
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-review-outcomes-template')}
                download="open-agronomy-agent-human-review-outcomes-template.csv"
              >
                Outcome CSV
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-review-batch-ingest-latest')}
                download="open-agronomy-agent-human-review-batch-ingest-latest.json"
              >
                Ingest receipt
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-review-batch-preflight-latest')}
                download="open-agronomy-agent-human-review-batch-preflight-latest.json"
              >
                Preflight receipt
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-review-batch-preflight-markdown')}
                download="open-agronomy-agent-human-review-batch-preflight-latest.md"
              >
                Preflight notes
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-review-batch-ingest-helper')}
                download="open-agronomy-agent-human-review-batch-ingest.py"
              >
                Ingest helper
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-review-batch-preflight-helper')}
                download="open-agronomy-agent-human-review-batch-preflight.py"
              >
                Preflight helper
              </a>
              <a
                className="manifest-link"
                href={benchmarkArtifactHref('human-review-batches-manifest')}
                download="open-agronomy-agent-human-review-batches-manifest.json"
              >
                Batch manifest
              </a>
              <span>Worksheet: {repoRelativePath(reviewOutcomes.template_path)}</span>
              <span>Summary: {repoRelativePath(reviewOutcomes.markdown_path)}</span>
              {reviewOutcomes.latest_ingest ? (
                <span>
                  Latest ingest: {reviewOutcomes.latest_ingest.merged_rows ?? 0} merged from{' '}
                  {reviewOutcomes.latest_ingest.incoming_rows ?? 0} rows · {repoRelativePath(reviewOutcomes.latest_ingest.path)}
                </span>
              ) : null}
              {reviewOutcomes.latest_preflight ? (
                <span>
                  Latest preflight: {reviewOutcomes.latest_preflight.status || 'needs_review'} ·{' '}
                  {reviewOutcomes.latest_preflight.merged_rows ?? 0} would merge from{' '}
                  {reviewOutcomes.latest_preflight.incoming_rows ?? 0} rows ·{' '}
                  {repoRelativePath(reviewOutcomes.latest_preflight.path)}
                </span>
              ) : null}
            </div>
          </div>
          <div className="review-batch-panel">
            <div className="review-panel-heading">
              <span>Batch progress</span>
              <strong>{reviewOutcomes.review_batch_count || reviewBatches.length} review batches</strong>
            </div>
            <div className="review-batch-list">
              {reviewBatches.slice(0, 4).map((batch) => (
                <article key={batch.batch_id || batch.csv_path} className={`review-batch review-batch-${reviewStatusClass(batch.status)}`}>
                  <div>
                    <strong>{batch.label || readableLabel(batch.batch_id)}</strong>
                    <span>{readableLabel(batch.status)}</span>
                  </div>
                  <div className="review-progress-track" aria-label={`${batch.label || batch.batch_id} review progress`}>
                    <i style={{ width: `${reviewProgressPercent(batch.reviewed_count, batch.row_count)}%` }} />
                  </div>
                  <small>
                    {batch.reviewed_count ?? 0}/{batch.row_count ?? 0} reviewed
                    {batch.blocking_issue_count ? ` · ${batch.blocking_issue_count} blockers` : ' · no blockers logged'}
                    {batch.record_issue_count ? ` · ${batch.record_issue_count} record issues` : ' · records clean'}
                  </small>
                  {reviewBatchArtifactId(batch.batch_id) ? (
                    <a
                      className="manifest-link review-batch-download"
                      href={benchmarkArtifactHref(reviewBatchArtifactId(batch.batch_id) || '')}
                      download
                    >
                      Download batch CSV
                    </a>
                  ) : null}
                  <small>{repoRelativePath(batch.csv_path)}</small>
                </article>
              ))}
            </div>
          </div>
        </div>
        {reviewRecordIssues.length ? (
          <div className="review-blocker-panel review-record-issue-panel">
            <div className="review-panel-heading">
              <span>Review record issues</span>
              <strong>{reviewOutcomes.review_record_issue_count ?? reviewRecordIssues.length} total</strong>
            </div>
            <div className="review-blocker-list">
              {reviewRecordIssues.slice(0, 4).map((issue, index) => (
                <article key={`${issue.review_id || 'review-record-issue'}-${index}`}>
                  <strong>{issue.priority || 'review'} · {issue.review_id || 'unknown review id'}</strong>
                  <span>{readableLabel(issue.issue_type)}</span>
                  <small>{issue.detail || 'Review record needs more detail before it can clear a gate.'}</small>
                </article>
              ))}
            </div>
          </div>
        ) : (
          <p className="review-clear-note">
            No incomplete reviewed records are logged. Unreviewed rows still need reviewer, device, field/file,
            visible status steps, evidence cards, and expected behavior before they can clear a gate.
          </p>
        )}
        {reviewBlockers.length ? (
          <div className="review-blocker-panel">
            <div className="review-panel-heading">
              <span>Open blockers</span>
              <strong>{reviewBlockers.length} shown</strong>
            </div>
            <div className="review-blocker-list">
              {reviewBlockers.slice(0, 4).map((blocker) => (
                <article key={blocker.review_id}>
                  <strong>{blocker.priority || 'review'} · {blocker.review_id}</strong>
                  <span>{readableLabel(blocker.severity)} / {readableLabel(blocker.result_status)}</span>
                  <small>{blocker.issue_summary || 'No issue summary recorded.'}</small>
                  {blocker.followup_owner ? <small>Owner: {blocker.followup_owner}</small> : null}
                </article>
              ))}
            </div>
          </div>
        ) : (
          <p className="review-clear-note">
            No release/demo blockers are logged yet. The gates still stay closed until the required rows are actually
            reviewed.
          </p>
        )}
        <p className="agentic-gap-boundary">
          {reviewQueue.score_warning || 'Human review assignment queue; not an official AI AgriBench score.'}
        </p>
        <div className="rehearsal-prompt-list">
          {reviewQueueItems.slice(0, 6).map((item) => (
            <article key={item.review_id}>
              <div className="rehearsal-prompt-meta">
                <span>{item.priority || 'review'}</span>
                <span>{readableLabel(item.review_type || item.source)}</span>
              </div>
              <strong>{item.context_label || readableLabel(item.coverage_domain || item.public_source_lane)}</strong>
              <p>{item.question || item.human_review_focus || item.release_blocking_failure}</p>
              <small>
                Lane: {readableLabel(item.public_source_lane)} · Source: {readableLabel(item.source)}
              </small>
              <small>
                Expected:{' '}
                {(item.expected_public_adapters || item.expected_visible_evidence || []).slice(0, 3).join(' · ') ||
                  item.human_review_focus ||
                  'review visible answer and evidence'}
              </small>
              {item.no_repair_loop ? <em>No repair-loop target until frozen batch review is complete.</em> : null}
            </article>
          ))}
        </div>
        <p className="agentic-gap-boundary">
          {reviewQueuePacket.boundary || reviewQueuePacket.source_boundaries?.[0] || reviewQueuePacket.score_warning}
        </p>
      </section>
      <section className="submission-hygiene-panel visual-qa-panel" data-testid="report-visual-qa">
        <div className="freeze-heading">
          <div>
            <h2>Report visual QA</h2>
            <p>
              The public report package has refreshed SVG previews and HTML output. The PDF remains gated until Chrome can
              rerender and the contact sheet is rechecked.
            </p>
          </div>
          <div className="hygiene-downloads">
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('visual-qa-current-pass')}
              download="open-agronomy-agent-report-visual-qa-current-pass.md"
            >
              QA note
            </a>
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('visual-qa-manifest')}
              download="open-agronomy-agent-report-visual-qa-manifest.json"
            >
              QA manifest
            </a>
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('visual-qa-inspection-packet')}
              download="open-agronomy-agent-report-visual-qa-inspection-packet.md"
            >
              Inspection packet
            </a>
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('visual-qa-inspection-packet-json')}
              download="open-agronomy-agent-report-visual-qa-inspection-packet.json"
            >
              Inspection JSON
            </a>
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('visual-qa-inspection-packet-builder')}
              download="open-agronomy-agent-build-visual-qa-inspection-packet.py"
            >
              Inspection builder
            </a>
          </div>
        </div>
        <div className="hygiene-summary-grid">
          <article>
            <span>SVG previews</span>
            <strong>{reportVisualQa.svg_preview_count ?? 0}</strong>
            <small>{reportVisualQa.strict_svg_validation || 'strict validation pending'}</small>
          </article>
          <article>
            <span>Report package</span>
            <strong>{reportVisualQa.report_package_validation ? 'Pass' : 'Pending'}</strong>
            <small>{reportVisualQa.project_state_validation || 'project-state validation pending'}</small>
          </article>
          <article>
            <span>PDF state</span>
            <strong>{reportVisualQa.pdf_rerender_required ? 'Open' : 'Current'}</strong>
            <small>
              {reportVisualQa.pdf_render_status
                ? `render ${reportVisualQa.pdf_render_status}`
                : reportVisualQa.pdf_contact_sheet_exists
                  ? 'contact sheet exists but needs rerender check'
                  : 'contact sheet pending'}
            </small>
          </article>
          <article>
            <span>Run manifest</span>
            <strong>{reportVisualQa.manifest_available ? 'Tracked' : reportVisualQa.available ? 'Note only' : 'Missing'}</strong>
            <small>{repoRelativePath(reportVisualQa.manifest_path || reportVisualQa.current_pass_path)}</small>
          </article>
        </div>
        <p className="freeze-boundary">
          {reportVisualQa.boundary ||
            'Current SVG/HTML visual QA is tracked; PDF and contact-sheet rerender remains a manual gate.'}
        </p>
      </section>
      <section className="submission-hygiene-panel" data-testid="submission-answer-hygiene">
        <div className="freeze-heading">
          <div>
            <h2>Submission answer hygiene</h2>
            <p>
              Official-style preflight over local answer artifacts catches answer shape, source/tool leakage, public-chat
              scaffold, generic disclaimers, evasive language, and unsafe certainty before an answer-only file is sent.
            </p>
          </div>
          <div className="hygiene-downloads">
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('submission-answer-hygiene-audit')}
              download="open-agronomy-agent-submission-answer-hygiene-audit.json"
            >
              JSON
            </a>
            <a
              className="manifest-link secondary"
              href={benchmarkArtifactHref('submission-answer-hygiene-markdown')}
              download="open-agronomy-agent-submission-answer-hygiene-audit.md"
            >
              Notes
            </a>
            <a
              className="manifest-link secondary"
              href={benchmarkArtifactHref('submission-answer-hygiene-high-risk-csv')}
              download="open-agronomy-agent-submission-answer-hygiene-high-risk-review.csv"
            >
              High-risk CSV
            </a>
          </div>
        </div>
        <div className="hygiene-summary-grid">
          <article>
            <span>Rows audited</span>
            <strong>{answerHygiene.row_count ?? 0}</strong>
            <small>local public/proxy artifacts</small>
          </article>
          <article>
            <span>Warning rows</span>
            <strong>{answerHygiene.quality_warning_count ?? 0}</strong>
            <small>{percentText(answerHygiene.quality_warning_rate)} of audited answers</small>
          </article>
          <article>
            <span>High risk</span>
            <strong>{answerHygiene.high_risk_review_row_count ?? answerHygiene.high_risk_warning_count ?? 0}</strong>
            <small>
              {answerHygiene.current_high_risk_warning_count ?? 0} current,{' '}
              {answerHygiene.stale_high_risk_warning_count ?? 0} stale-before-cleanup; CSV triage packet available
            </small>
          </article>
          <article>
            <span>Format</span>
            <strong>{answerHygiene.format_warning_count ?? 0}</strong>
            <small>{percentText(answerHygiene.format_warning_rate)} length, paragraph, or checklist warnings</small>
          </article>
        </div>
        <ol className="hygiene-action-list">
          {hygieneActions.slice(0, 3).map((action) => (
            <li key={action}>{compactReviewAction(action)}</li>
          ))}
        </ol>
        <p className="freeze-boundary">
          {answerHygiene.score_warning ||
            'Submission hygiene is a local official-style screen over public/proxy answers, not an official AI AgriBench score.'}
        </p>
      </section>
      <section className="dry-run-panel" data-testid="aiagribench-submission-dry-run">
        <div className="freeze-heading">
          <div>
            <h2>Official dry run</h2>
            <p>
              Public surrogate questions are run through the same answer-only submission path before the confidential file
              arrives.
            </p>
            <small>{submissionDryRun.score_warning || LOCAL_NOT_OFFICIAL}</small>
          </div>
          <div className="hygiene-downloads">
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('aiagribench-submission-dry-run-packet')}
              download="open-agronomy-agent-aiagribench-submission-dry-run-packet.md"
            >
              Dry run
            </a>
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('aiagribench-submission-dry-run-packet-json')}
              download="open-agronomy-agent-aiagribench-submission-dry-run-packet.json"
            >
              Dry JSON
            </a>
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('aiagribench-submission-dry-run-submit-safe-sample')}
              download="open-agronomy-agent-aiagribench-submission-dry-run-submit-safe-sample.json"
            >
              Submit sample
            </a>
          </div>
        </div>
        <div className="dry-run-summary-grid">
          <article>
            <span>Rows</span>
            <strong>{submissionDryRun.row_count ?? 0}</strong>
            <small>{submissionDryRun.mock ? 'public surrogate mock contract' : submissionDryRun.dry_run_kind || 'dry run'}</small>
          </article>
          <article>
            <span>Payload</span>
            <strong>{submissionDryRun.official_payload_submit_safe ? 'safe' : 'review'}</strong>
            <small>qna_id + answer only</small>
          </article>
          <article>
            <span>Protocol</span>
            <strong>{submissionDryRun.minimum_protocol_passed ? 'pass' : 'review'}</strong>
            <small>{submissionDryRun.answer_profile || 'benchmark'} profile</small>
          </article>
          <article>
            <span>Warnings</span>
            <strong>{submissionDryRun.quality_warning_count ?? 0}</strong>
            <small>{submissionDryRun.quality_warning_passed ? 'quality preflight clean' : 'needs manual review'}</small>
          </article>
        </div>
        <p className="freeze-boundary">
          Official hidden questions still stay outside docs, screenshots, RAG/KG stores, training data, and repair loops.
        </p>
      </section>
      <section className="freeze-panel">
        <div className="freeze-heading">
          <div>
            <h2>Submission freeze packet</h2>
            <p>
              The official run should freeze model settings, RAG inventory, local evidence artifacts, and the answer-only
              submission boundary before the confidential question file is used.
            </p>
            <small>{freezeStatus}</small>
          </div>
          <div className="hygiene-downloads">
            <a
              className="manifest-link"
              href="/api/benchmarks/aiagribench-proxy/freeze-manifest"
              download="open-agronomy-agent-aiagribench-freeze-manifest.json"
            >
              Freeze manifest
            </a>
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('aiagribench-leaderboard-request-packet')}
              download="open-agronomy-agent-aiagribench-leaderboard-request-packet.md"
            >
              Request packet
            </a>
            <a
              className="manifest-link"
              href={benchmarkArtifactHref('aiagribench-leaderboard-request-packet-json')}
              download="open-agronomy-agent-aiagribench-leaderboard-request-packet.json"
            >
              Request JSON
            </a>
          </div>
        </div>
        <div className="official-target-grid" data-testid="aiagribench-official-target">
          <article>
            <span>Official target</span>
            <strong>416 QA rows</strong>
            <small>expert-validated text agronomy leaderboard, not the multimodal AgriBench paper</small>
          </article>
          <article>
            <span>Scored metrics</span>
            <strong>4 metrics</strong>
            <small>accuracy, relevance, completeness, conciseness</small>
          </article>
          <article>
            <span>Answer profile</span>
            <strong>2-4 paragraphs</strong>
            <small>benchmark answers should be concise and avoid citations unless organizers request them</small>
          </article>
          <article>
            <span>Request route</span>
            <strong>leaderboard/join</strong>
            <small>submit contact details, then use organizer-provided question file instructions</small>
          </article>
          <article className="official-target-warning">
            <span>Split metadata</span>
            <strong>organizer file wins</strong>
            <small>
              Public pages disagree on September 1 vs September 30, 2024 post-cutoff wording; do not hard-code either.
            </small>
          </article>
          <article className="official-target-warning">
            <span>Submit-safe file</span>
            <strong>qna_id + answer</strong>
            <small>keep official question text, traces, source rows, and audit CSV/JSONL files internal</small>
          </article>
        </div>
        <div className="freeze-summary-grid">
          <article>
            <span>Model</span>
            <strong>{freezeManifest.model?.model_id || benchmarkSummary.model_id || 'model pending'}</strong>
            <small>{freezeManifest.model?.answer_profile || 'benchmark'} profile · {freezeManifest.model?.max_tokens || 480} max tokens</small>
          </article>
          <article>
            <span>RAG inventory</span>
            <strong>{freezeManifest.rag?.configured_corpus_paths ?? 0} corpora / {freezeManifest.rag?.configured_graph_paths ?? 0} graphs</strong>
            <small>{freezeManifest.rag?.agent_runtime || 'local'} runtime · top {freezeManifest.rag?.retrieval_top_k ?? 'n/a'}</small>
          </article>
          <article>
            <span>Git freeze</span>
            <strong>{freezeManifest.git?.short_commit || 'pending'}</strong>
            <small>{freezeManifest.git?.ref || 'ref pending'} · dirty state manual</small>
          </article>
          <article>
            <span>Official response</span>
            <strong>{repoRelativePath(freezeManifest.runner?.official_response_file).replace('outputs/aiagribench_submission/', '')}</strong>
            <small>{repoRelativePath(freezeManifest.runner?.preflight_file).replace('outputs/aiagribench_submission/', '')}</small>
          </article>
        </div>
        <pre className="freeze-command">{freezeManifest.runner?.command_template}</pre>
        <div className="freeze-body">
          <div className="freeze-checklist">
            {(freezeManifest.checklist || []).map((item) => (
              <article key={item.id} className={`freeze-check freeze-check-${item.status.replace(/_/g, '-')}`}>
                <span>{item.status.replace(/_/g, ' ')}</span>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
              </article>
            ))}
          </div>
          <div className="freeze-artifacts">
            <h3>Hashed artifacts</h3>
            {freezeArtifacts.map((artifact) => (
              <article key={`${artifact.kind}-${artifact.label}-${artifact.path}`}>
                <strong>{artifact.label.replace(/_/g, ' ')}</strong>
                <span>{artifact.path}</span>
                <small>
                  {artifact.exists ? `${compactSha(artifact.sha256)} · ${compactBytes(artifact.bytes)}` : 'missing'}
                  {artifact.line_count ? ` · ${artifact.line_count} lines` : ''}
                </small>
              </article>
            ))}
          </div>
        </div>
        <p className="freeze-boundary">{freezeManifest.runner?.submission_boundary || freezeManifest.score_warning}</p>
      </section>
      <section className="next-work">
        <h2>Lowest live rows</h2>
        <ol>
          {(benchmarkSummary.lowest_rows || []).slice(0, 5).map((row) => (
            <li key={row.eval_id}>
              <strong>{scoreText(row.score)}</strong> {row.task_family.replace(/_/g, ' ')}
              {row.crop || row.region ? ` · ${[row.crop, row.region].filter(Boolean).join(' · ')}` : ''}
            </li>
          ))}
        </ol>
      </section>
      <section className="next-work">
        <h2>Next benchmark work</h2>
        <ol>
          <li>Human-review the lowest repaired public source lanes for usefulness, not just required-pattern coverage.</li>
          <li>Keep the 416-row proxy clean while adding official-submission rehearsal traces and human review notes.</li>
          <li>Wire NASA POWER, NRCS SDA, EPA PPLS, Daymet, CDL, Quick Stats, and OpenET traces into public answer audits.</li>
          <li>Keep official-style evaluations on the benchmark answer profile while preserving faster field-chat defaults.</li>
          <li>Submit only through the official AI AgriBench question file and keep private benchmark prompts out of tracked corpora.</li>
        </ol>
      </section>
        </div>
      </details>
    </div>
  )
}
