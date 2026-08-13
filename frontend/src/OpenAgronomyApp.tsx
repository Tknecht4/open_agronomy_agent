import { Fragment, FormEvent, Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  Database,
  Eraser,
  Layers3,
  MapPin,
  MessageSquareText,
  MousePointer2,
  Pencil,
  RefreshCw,
  Save,
  Send,
  Settings2,
  Sparkles,
  CloudSun,
  Upload,
  X,
} from 'lucide-react'
import { apiDelete, apiGet, apiPatch, apiPost, apiUpload } from './api'
import { clearPhase6ChatDraft, loadPhase6ChatDraft, savePhase6ChatDraft } from './offlineDrafts'
import { clearPhase6Scratchpad, loadPhase6Scratchpad, savePhase6Scratchpad } from './offlineScratchpad'
import {
  PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT,
  downloadPhase6OfflineStorageRecovery,
  type Phase6OfflineStorageRepairDetail,
} from './offlineStorageRepair'
import {
  fieldAnswerCapability,
  isRuntimeTransportFailure,
  type RuntimeAccess,
} from './fieldRuntimeAvailability'
import {
  estimatePolygonAcres,
  fieldGeometryIssue,
  isUsableFieldGeometry,
  type FieldGeometry,
  type FieldPoint,
  type MapMode,
} from './fieldGeometry'
import {
  buildSourceCheckSummary,
  buildTraceToolGroups,
  buildPublicToolCard,
  buildStructuredEvidenceCard,
  mapContextEvidenceCards,
  PublicToolCard,
  SourceCheckSummary,
  summarizePublicToolCards,
  summarizeStructuredEvidenceCards,
  TraceToolGroup,
} from './sourceCards'
import { buildReviewerExportMarkdown, reviewerExportFilename } from './reviewerExport'
import {
  RetrievedDoc,
  SessionRecord,
  StructuredEvidenceCard,
  ToolInvocation,
  Turn,
  TurnRoute,
  TurnSystemState,
} from './types'
import type { PrivateKnowledgeDoc, PrivateKnowledgeInspection } from './PrivateKnowledgePanel'

type Page = 'analyze' | 'fields' | 'evidence' | 'benchmarks' | 'sources' | 'privacy' | 'about'
type DemoMode = 'mock' | 'agronomic_rag' | 'baseline'

type AgroclimateIndicator = {
  label?: string
  units?: string
  time_window?: string
  observation_end?: string
  value?: number
  mean?: number
}

type AgroclimateResponse = {
  tool: string
  status: string
  source: string
  source_name?: string
  observation_end?: string
  data_age_days?: number
  freshness_status?: string
  sample_point_count?: number
  indicator_summary?: Record<string, AgroclimateIndicator>
  boundary?: string
}

type AgroclimateState = {
  status: 'idle' | 'loading' | 'available' | 'partial_available' | 'unavailable' | 'error'
  payload?: AgroclimateResponse
  message?: string
}

type NasaPowerMetric = {
  days?: number
  mean?: number
  sum?: number
}

type NasaPowerResponse = {
  tool: 'nasa_power_daily'
  source: string
  cache_hit?: boolean
  latitude: number
  longitude: number
  start: string
  end: string
  parameter_summary?: Record<string, NasaPowerMetric>
  boundary?: string
}

type NasaPowerState = {
  status: 'idle' | 'loading' | 'available' | 'error'
  payload?: NasaPowerResponse
  message?: string
}

const APP_PAGES: Page[] = ['analyze', 'fields', 'evidence', 'benchmarks', 'sources', 'privacy', 'about']
const WHITEPAPER_DIR = 'docs/open_agronomy_agent_whitepaper_20260709'
const CANADIAN_JURISDICTIONS = new Set([
  'alberta',
  'british columbia',
  'manitoba',
  'new brunswick',
  'newfoundland and labrador',
  'nova scotia',
  'ontario',
  'prince edward island',
  'quebec',
  'saskatchewan',
])
const AGROCLIMATE_METRICS = [
  { key: 'spi', label: '13 wk SPI' },
  { key: 'spei', label: '13 wk SPEI' },
  { key: 'temperature_anomaly', label: '4 wk temperature' },
  { key: 'percent_of_average_precipitation', label: '13 wk precipitation' },
] as const

const BenchmarksRoute = lazy(() => import('./BenchmarksRoute').then((module) => ({ default: module.BenchmarksRoute })))
const LeafletFieldMap = lazy(() => import('./LeafletFieldMap').then((module) => ({ default: module.LeafletFieldMap })))
const FieldSyncPanel = lazy(() => import('./FieldSyncPanel'))
const PrivateKnowledgePanel = lazy(() => import('./PrivateKnowledgePanel'))
const OfflineTerrainContextPanel = lazy(() => import('./OfflineTerrainContextPanel'))
const CanadianKnowledgeCoveragePanel = lazy(() => import('./CanadianKnowledgeCoveragePanel'))
const OpenAgronomyInfoPages = lazy(() => import('./OpenAgronomyInfoPages'))

const pageHash = (page: Page): string => `#${page}`

const pageFromHash = (hash: string): Page => {
  const candidate = hash.replace(/^#\/?/, '').split(/[/?&]/)[0]
  return APP_PAGES.includes(candidate as Page) ? (candidate as Page) : 'analyze'
}

const currentHashPage = (): Page => (typeof window === 'undefined' ? 'analyze' : pageFromHash(window.location.hash))

const privateKnowledgeForQuestion = (
  inspections: PrivateKnowledgeInspection[],
  question: string,
): PrivateKnowledgeDoc[] => {
  const queryTokens = new Set(
    question
      .toLocaleLowerCase()
      .split(/[^\p{L}\p{N}]+/u)
      .filter((token) => token.length >= 3),
  )
  return inspections
    .flatMap((inspection) => inspection.chunks)
    .map((doc) => {
      const tokens = new Set(
        `${doc.title} ${doc.text}`
          .toLocaleLowerCase()
          .split(/[^\p{L}\p{N}]+/u)
          .filter((token) => token.length >= 3),
      )
      const overlap = [...queryTokens].filter((token) => tokens.has(token)).length
      return {
        ...doc,
        score: queryTokens.size ? overlap / queryTokens.size : 0,
      }
    })
    .sort((left, right) => right.score - left.score || left.chunk_index - right.chunk_index)
    .slice(0, 6)
}

type GeoPriorCandidate = {
  label: string
  name: string
  layer: string
  system: string
  code: string
  confidence: number
  match_reason: string
  priors: string[]
  evidence_terms: string[]
  source: string
}

type RegionalIntersection = {
  layer_id: string
  layer_label: string
  system: string
  code: string
  name: string
  label: string
  source_url?: string
  confidence: number
  coverage_estimate: number
  match_reason: string
  source: string
  boundary?: string
  capability_label?: string
  capability_summary?: string
  primary_class?: string
  components?: Array<{ percent?: number; class?: string; subclasses?: string[] }>
  source_scale?: number
  source_scale_label?: string
  source_scale_range?: string
  source_scale_note?: string
  map_unit?: string
  dominant_components?: Array<Record<string, unknown>>
  mapping_basis?: string
  drainage_class?: string
  capability_class?: string
  capability_interpretation?: string
  erosion_risk?: string
  erosion_indicator_2021?: number
  erosion_risk_1981?: string
  erosion_indicator_1981?: number
  erosion_change_1981_2021?: string
  erosion_change_indicator?: number
  erosion_summary?: string
  soil_landscape_id?: string
  source_year?: number
  publication_year?: number
  coverage_area?: string
  slope_class?: string
  surface_texture_group?: string
  soil_summary?: string
}

type GeoFeature = {
  type: 'Feature'
  id?: string
  geometry: { type: string; coordinates: unknown }
  properties?: Record<string, unknown>
}

type GeoFeatureCollection = {
  type: 'FeatureCollection'
  features: GeoFeature[]
}

type GeoPriors = {
  location_text: string
  candidate_regions: GeoPriorCandidate[]
  regional_intersections?: RegionalIntersection[]
  regional_feature_collection?: GeoFeatureCollection
  geo_errors?: Array<{ layer_id: string; message: string }>
  official_layer_status?: OfficialLayerStatus[]
  boosted_namespaces: string[]
  evidence: string[]
  missing_context: string[]
  uncertainty: string
  used_as_prior_only: boolean
  not_field_specific_fact: boolean
  disclaimer: string
  ui_notice: string
  recommended_followups: string[]
}

type UploadFeatureSummary = {
  id: string
  label: string
  geometry_type: string
  bbox: number[]
  acres: number
  selected: boolean
  properties: Record<string, unknown>
}

type OfficialLayerStatus = {
  layer_id: string
  label: string
  system: string
  source_url?: string
  status: 'matched' | 'error' | 'no_match' | string
  match_count: number
  message: string
}

type BoundaryUploadResponse = {
  schema_version: string
  filename: string
  source_format: string
  feature_count: number
  parsed_feature_count?: number
  selected_feature_id?: string
  geometry: { type: string; coordinates: unknown }
  geometry_type: string
  bbox: number[]
  acres: number
  feature_collection?: GeoFeatureCollection
  feature_summaries?: UploadFeatureSummary[]
  warnings?: string[]
  regional_intersections?: RegionalIntersection[]
  regional_feature_collection?: GeoFeatureCollection
  geo_errors?: Array<{ layer_id: string; message: string }>
  official_layer_status?: OfficialLayerStatus[]
  status_message: string
  boundary: string
}

type GeometryEditSnapshot = {
  geoPriors: GeoPriors | null
  uploadContext: BoundaryUploadResponse | null
  selectedUploadFeatureId: string
}

type ConfigResponse = {
  modes: string[]
  rag_configs: string[]
  models: string[]
  model_profiles?: ModelProfile[]
  prompt_versions: string[]
  default_rag_config: string
  network?: {
    mode: 'online' | 'offline' | string
    external_calls_allowed: boolean
    telemetry_enabled: boolean
  }
  knowledge_update?: {
    configured: boolean
    status: 'active' | 'no_active_update' | 'not_configured' | string
    package_id?: string | null
    previous_package_id?: string | null
    activated_at?: string | null
    operation?: string | null
    release_sequence?: number | null
    highest_release_sequence?: number | null
    expires_at?: string | null
    freshness_checked_at?: string | null
    signature_required: boolean
    signature_mode?: 'threshold_policy' | 'legacy_single_key' | 'unsigned_development' | 'not_configured' | string
    trust_policy_id?: string | null
    trust_policy_sequence?: number | null
    trust_policy_threshold?: number | null
    trust_policy_sha256?: string | null
    startup_validation: 'passed' | 'not_applicable' | string
  }
}

type ModelProfile = {
  id: string
  label: string
  role: 'default' | 'fast' | string
  max_tokens: number
  quality_gate?: string
  local_ready?: boolean
  local_status?: string
  local_detail?: string
}

type TurnCreateResponse = {
  turn_id: string
  turn: Turn
}

type ParsedSseEvent = {
  event: string
  payload: Record<string, unknown>
}

type StreamProgressStep = {
  label: string
  detail: string
  progress: number
  elapsedMs: number
  kind: 'step' | 'heartbeat'
  stageId?: string
  status?: string
  category?: string
  durationMs?: number
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

type PublicCoverageSummary = {
  available: boolean
  suite?: string
  suite_path?: string
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

type PublicAdapterReadinessItem = {
  id: string
  label: string
  provider: string
  status: 'ready' | 'needs_key' | 'monitor' | string
  status_label?: string
  credential_required: boolean
  configured: boolean
  required_env_vars?: string[]
  configured_env_vars?: string[]
  source?: string
  cache_dir?: string
  cache_entries?: number
  smoke_checks?: PublicAdapterSmokeCheck[]
  smoke_status?: 'passed' | 'missing' | 'failed' | 'not_required' | string
  field_context_required?: boolean
  trigger?: string
  demo_impact?: string
  boundary?: string
}

type PublicAdapterSmokeCheck = {
  id?: string
  label?: string
  status?: 'passed' | 'missing' | 'failed' | string
  status_label?: string
  passed?: boolean
  mode?: string
  artifact_path?: string
  case_count?: number
  failure_count?: number
  case_ids?: string[]
  updated_at?: string
  boundary?: string
}

type PublicAdapterReadiness = {
  schema_version: string
  generated_at?: string
  summary: {
    adapter_count: number
    ready_count: number
    needs_key_count: number
    monitor_count?: number
    key_gated_count?: number
    field_context_required_count?: number
    smoke_check_count?: number
    smoke_passed_count?: number
    smoke_missing_count?: number
    smoke_failed_count?: number
  }
  smoke_checks?: PublicAdapterSmokeCheck[]
  adapters: PublicAdapterReadinessItem[]
  boundary?: string
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
  core_rows?: number
  public_expansion_rows?: number
  raw_under90_rows?: number
  current_under90_rows?: number
  raw_missing_required_rows?: number
  current_missing_required_rows?: number
  repaired_contract_gaps?: number
  open_failures?: number
  low_floor_human_review_rows?: number
  tool_integration_review_rows?: number
  live_adapter_review_rows?: number
  planned_source_lane_review_rows?: number
  source_gap_backlog_rows?: number
  source_requirement_counts?: Record<string, number>
  status_counts?: Record<string, number>
  action_priority_counts?: Record<string, number>
  gap_type_counts?: Record<string, number>
  top_raw_missing_required_patterns?: Array<[string, number]>
  lowest_current_rows?: AgenticGapMatrixRow[]
  highest_raw_to_current_repairs?: AgenticGapMatrixRow[]
  source_boundaries?: string[]
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
  adapter_counts?: Record<string, number>
  workflow_counts?: Record<string, number>
  public_source_lanes?: Record<string, number>
  regional_matrix_artifact?: string
  official_ai_agribench?: boolean
  source_boundaries?: string[]
  score_warning?: string
}

type PublicDemoRehearsalPrompt = {
  prompt_id: string
  context_id?: string
  context_label?: string
  crop?: string
  state_alpha?: string
  workflow?: string
  public_source_lane?: string
  source_lane_label?: string
  question: string
  expected_public_adapters?: string[]
  expected_visible_evidence?: string[]
  expected_boundaries?: string[]
  human_review_focus?: string
  release_blocking_failure?: string
  official_ai_agribench?: boolean
}

type PublicDemoRehearsalPacket = PublicDemoRehearsalSummary & {
  prompt_count_returned: number
  prompts: PublicDemoRehearsalPrompt[]
  boundary?: string
}

type PublicShadowHeldoutSummary = {
  available: boolean
  suite?: string
  suite_path?: string
  manifest_path?: string
  markdown_path?: string
  row_count?: number
  context_count?: number
  topic_category_count?: number
  domain_count?: number
  source_lane_count?: number
  source_family_count?: number
  contexts?: Record<string, number>
  domain_counts?: Record<string, number>
  aiagribench_topic_category_counts?: Record<string, number>
  public_source_lanes?: Record<string, number>
  source_family_counts?: Record<string, number>
  expected_tool_counts?: Record<string, number>
  heldout_policy?: {
    excluded_from_rag_ingestion?: boolean
    excluded_from_gap_repair?: boolean
    excluded_from_training?: boolean
    run_after_answer_contract_freeze?: boolean
    human_or_external_judge_only?: boolean
    purpose?: string
  }
  official_ai_agribench?: boolean
  source_boundaries?: string[]
  score_warning?: string
}

type PublicShadowHeldoutResultSummary = PublicSmokeGapSummary & {
  manifest_row_count?: number
  is_complete_to_manifest?: boolean
  low_topics?: Array<{
    topic: string
    samples: number
    mean_score?: number
    min_score?: number
    flagged_missing_required?: number
    common_missing_required?: Array<[string, number]>
  }>
  lowest_rows?: AgenticGapMatrixRow[]
  heldout_policy?: PublicShadowHeldoutSummary['heldout_policy']
}

type HumanReviewQueueSummary = {
  available: boolean
  suite?: string
  manifest_path?: string
  queue_path?: string
  markdown_path?: string
  queue_item_count?: number
  source_counts?: Record<string, number>
  by_source?: Record<string, number>
  by_priority?: Record<string, number>
  by_review_type?: Record<string, number>
  top_coverage_domains?: Array<[string, number]>
  top_public_source_lanes?: Array<[string, number]>
  review_policy?: string[]
  source_boundaries?: string[]
  official_ai_agribench?: boolean
  score_warning?: string
}

type HumanReviewQueueItem = {
  review_id: string
  source?: string
  source_id?: string
  priority?: string
  review_type?: string
  workflow?: string
  context_label?: string
  question?: string
  coverage_domain?: string
  public_source_lane?: string
  expected_public_adapters?: string[]
  expected_visible_evidence?: string[]
  release_blocking_failure?: string
  human_review_focus?: string
  official_ai_agribench?: boolean
  no_repair_loop?: boolean
}

type HumanReviewQueuePacket = HumanReviewQueueSummary & {
  item_count_returned: number
  items: HumanReviewQueueItem[]
  boundary?: string
}

type HumanReviewBatch = {
  batch_id?: string
  label?: string
  purpose?: string
  review_goal?: string
  csv_path?: string
  absolute_path?: string
  row_count?: number
  by_priority?: Record<string, number>
  by_review_type?: Record<string, number>
  by_source?: Record<string, number>
}

type HumanReviewOutcomeBatch = {
  batch_id?: string
  label?: string
  csv_path?: string
  row_count?: number
  reviewed_count?: number
  unreviewed_count?: number
  blocking_issue_count?: number
  record_issue_count?: number
  status?: string
}

type HumanReviewBlocker = {
  review_id?: string
  priority?: string
  review_type?: string
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

type HumanReviewBatchesSummary = {
  available: boolean
  suite?: string
  manifest_path?: string
  markdown_path?: string
  queue_path?: string
  queue_item_count?: number
  quality_claim_review_floor?: number
  p0_public_demo_rows?: number
  p1_available_rows?: number
  p2_available_rows?: number
  quality_sample_plus_p0_rows?: number
  batch_count?: number
  batches?: HumanReviewBatch[]
  source_boundaries?: string[]
  official_ai_agribench?: boolean
  score_warning?: string
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
  unreviewed_count?: number
  p0_total?: number
  p0_reviewed?: number
  p0_unreviewed?: number
  review_record_issue_count?: number
  p0_review_record_issue_count?: number
  review_record_issues?: HumanReviewRecordIssue[]
  blocking_issue_count?: number
  release_blocking_count?: number
  demo_blocking_count?: number
  public_demo_gate?: { status?: string; requirement?: string }
  quality_claim_gate?: { status?: string; requirement?: string }
  review_batch_count?: number
  review_batches?: HumanReviewOutcomeBatch[]
  next_actions?: string[]
  top_blockers?: HumanReviewBlocker[]
  source_boundaries?: string[]
  official_ai_agribench?: boolean
  score_warning?: string
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
    dirty_state_note?: string
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
  local_evidence?: {
    proxy?: { samples?: number; mean_score?: number; under90_rows?: number; missing_required_flags?: number }
    public_full_gap?: { samples?: number; mean_score?: number; under90_rows?: number; flagged_missing_required?: number }
    public_claim_stress_focus?: { samples?: number; mean_score?: number; under90_rows?: number; flagged_missing_required?: number }
    public_demo_rehearsal?: { prompt_count?: number; context_count?: number; adapter_lane_count?: number }
    public_shadow_heldout?: { row_count?: number; context_count?: number; topic_category_count?: number; excluded_from_gap_repair?: boolean }
    human_review_queue?: { queue_item_count?: number; p0_items?: number; p1_items?: number; p2_items?: number }
    human_review_batches?: { batch_count?: number; p0_public_demo_rows?: number; quality_sample_plus_p0_rows?: number; quality_claim_review_floor?: number }
    human_review_outcomes?: { reviewed_count?: number; unreviewed_count?: number; blocking_issue_count?: number; public_demo_gate?: string; quality_claim_gate?: string }
  }
  artifacts?: FreezeArtifact[]
  corpora?: FreezeArtifact[]
  graphs?: FreezeArtifact[]
  checklist?: FreezeChecklistItem[]
  data_boundaries?: string[]
}

type BenchmarkSummary = {
  available: boolean
  suite: string
  run_id?: string
  created_at?: string
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
  public_coverage?: PublicCoverageSummary
  public_full_gap?: PublicSmokeGapSummary
  public_smoke_gap?: PublicSmokeGapSummary
  public_claim_stress_focus?: PublicSmokeGapSummary
  public_demo_rehearsal?: PublicDemoRehearsalSummary
  public_shadow_heldout?: PublicShadowHeldoutSummary
  public_shadow_heldout_result?: PublicShadowHeldoutResultSummary
  agentic_gap_matrix?: AgenticGapMatrixSummary
  human_review_queue?: HumanReviewQueueSummary
  human_review_batches?: HumanReviewBatchesSummary
  human_review_outcomes?: HumanReviewOutcomeSummary
  score_warning?: string
  message?: string
}

type FieldProfile = {
  crop: string
  region: string
  jurisdiction: string
  acres: string
  concern: string
  notes: string
}

type StoredField = FieldProfile & {
  id: string
  field_context_id?: string
  name: string
  geometry: FieldGeometry
  regionalContext: string
  createdAt: string
  updatedAt?: string
  storageMode?: 'account_workspace' | 'device' | string
  geoPriors?: GeoPriors | null
  sourceBoundary?: string | null
  fieldRevision?: {
    snapshot_sha256?: string
    previous_snapshot_sha256?: string | null
    update_kind?: string
  } | null
}

type DemoFieldsResponse = {
  schema_version: string
  storage: {
    mode: 'account_workspace' | string
    workspace_id?: string
    workspace_name?: string
    user_id?: string
    user_email?: string
    boundary?: string
  }
  fields: StoredField[]
}

type DemoFieldSavedResponse = {
  schema_version: string
  storage: DemoFieldsResponse['storage']
  field: StoredField
}

type KnowledgeCoverageBoundary = {
  jurisdiction: string
  status: string
  requires_prompt_boundary?: boolean | null
  registered_source_ids?: string[]
  distributable_source_ids?: string[]
  retrieved_source_ids?: string[]
  retrieved_context_source_ids?: string[]
}

type AnswerTimeKnowledgeCoverage = {
  schema_version?: string
  capture_status: 'captured' | 'captured_no_boundary' | 'not_captured' | 'invalid_snapshot' | string
  record_source?: 'trace_metadata' | 'legacy_agno_runtime_metadata' | string | null
  boundaries: KnowledgeCoverageBoundary[]
}

type FieldHistoryTurn = {
  session_id: string
  turn_id: string
  created_at?: string
  question: string
  answer: string
  answer_status?: 'draft' | 'reviewed' | 'approved' | 'rejected' | 'exported' | string
  feedback?: {
    rating?: number | null
    accepted?: boolean | null
    correction?: string | null
    reviewer_notes?: string | null
    answer_status?: 'draft' | 'reviewed' | 'approved' | 'rejected' | 'exported' | string | null
  }
  answer_integrity_receipt?: Turn['answer_integrity_receipt']
  binding_status: 'verified_snapshot' | 'legacy_session_binding' | string
  retrieved_document_count: number
  tool_invocation_count: number
  field_lineage?: {
    field_snapshot_sha256?: string
    field_record_updated_at?: string
  } | null
  knowledge_coverage?: AnswerTimeKnowledgeCoverage
}

type FieldEvent = {
  id: string
  event_type: 'observation' | 'sample' | 'operation' | 'decision' | 'outcome' | 'note' | 'correction'
  occurred_at: string
  payload: Record<string, unknown>
  provenance: Record<string, unknown>
  corrects_event_id?: string | null
  previous_event_sha256?: string | null
  integrity_sha256: string
  recorded_at: string
}

type FieldEventChain = {
  valid: boolean
  event_count: number
  head_sha256?: string | null
  failure_count: number
}

type FieldHistorySummary = Pick<
  StoredField,
  | 'id'
  | 'field_context_id'
  | 'name'
  | 'crop'
  | 'region'
  | 'jurisdiction'
  | 'acres'
  | 'createdAt'
  | 'updatedAt'
  | 'storageMode'
>

type DemoFieldHistoryResponse = {
  schema_version: string
  field: FieldHistorySummary
  event_count: number
  events: FieldEvent[]
  event_chain: FieldEventChain
  turn_count: number
  turns: FieldHistoryTurn[]
  boundary: string
}

type DemoFieldEventResponse = {
  schema_version: string
  event: FieldEvent
  chain: FieldEventChain
}

const emptyGeometry: FieldGeometry = { kind: 'none' }

const emptyFieldProfile: FieldProfile = {
  crop: '',
  region: '',
  jurisdiction: '',
  acres: '',
  concern: '',
  notes: '',
}

type SampleProfile = FieldProfile & {
  id: string
  name: string
  mlra: string
  geometry: string
  initialGeometry?: FieldGeometry
}

const sampleBoundary = (acres: number, south: number, west: number, north: number, east: number): FieldGeometry => ({
  kind: 'polygon',
  points: [
    { lat: south, lon: west },
    { lat: south, lon: east },
    { lat: north, lon: east },
    { lat: north, lon: west },
  ],
  acres,
})

const sampleProfiles: SampleProfile[] = [
  {
    id: 'central-alberta-barley',
    name: 'Alberta barley field',
    crop: 'barley',
    region: 'Leduc County',
    jurisdiction: 'Alberta',
    acres: '160',
    concern: 'Low soil-test phosphorus and uneven early growth',
    notes: 'Compare normal and weak zones. Confirm soil-test method and units, pH, moisture, rooting, previous crops and inputs, yield goal, and current Alberta guidance before choosing a rate.',
    mlra: 'Alberta detailed soil survey context',
    geometry: 'Local Alberta soil intersection when the Prairie soil package is installed.',
    initialGeometry: sampleBoundary(160, 53.296, -113.608, 53.304, -113.592),
  },
  {
    id: 'regina-thematic-soil',
    name: 'Saskatchewan wheat field',
    crop: 'spring wheat',
    region: 'Regina Plain',
    jurisdiction: 'Saskatchewan',
    acres: '96',
    concern: 'how the mapped soil constraints should change scouting and crop planning',
    notes: 'Use mapped drainage, capability, erosion, slope, and surface texture as regional screening context. Confirm field variability, soil profile, nutrient status, salinity, compaction, drainage performance, and current Saskatchewan guidance before choosing a crop or rate.',
    mlra: 'Saskatchewan detailed soil context with thematic fallback',
    geometry: 'Local Saskatchewan detailed-soil intersection when the Prairie spatial pack is installed.',
    initialGeometry: sampleBoundary(96, 50.447, -104.734, 50.453, -104.726),
  },
  {
    id: 'canola-acidity',
    name: 'Manitoba canola field',
    crop: 'canola',
    region: 'Aspen Parkland',
    jurisdiction: 'Manitoba',
    acres: '320',
    concern: 'Pale, patchy stand after a cool wet start',
    notes: 'Compare affected and normal strips, field position, rooting, moisture, fertility history, and soil or tissue evidence before calling sulfur deficiency.',
    mlra: 'Canadian prairie parkland context',
    geometry: 'Local Manitoba soil intersection when the Prairie soil package is installed.',
    initialGeometry: sampleBoundary(320, 49.865, -99.959, 49.875, -99.941),
  },
]

const sampleConversationKey = (scenarioId: string) => `sample:${scenarioId}`
const storedFieldConversationKey = (fieldId: string) => `field:${fieldId}`
const freshConversationKey = (base: string) => {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  return `${base}:chat:${suffix}`
}

const sessionContextValue = (session: SessionRecord, key: string): string => {
  const direct = session.context?.[key]
  if (typeof direct === 'string') return direct
  const extra = session.context?.extra
  if (extra && typeof extra === 'object' && typeof (extra as Record<string, unknown>)[key] === 'string') {
    return (extra as Record<string, string>)[key]
  }
  return ''
}

const sessionForField = (
  candidates: SessionRecord[],
  fieldConversationKey: string,
  fieldContextId = '',
): SessionRecord | undefined =>
  candidates.find((session) => {
    const sessionFieldId = sessionContextValue(session, 'field_context_id')
    const sessionKey = sessionContextValue(session, 'field_conversation_key')
    return fieldConversationKey
      ? sessionKey === fieldConversationKey
      : Boolean(fieldContextId && sessionFieldId === fieldContextId)
  })

const fallbackAdapterReadiness: PublicAdapterReadiness = {
  schema_version: 'open_agronomy_agent.public_adapter_readiness.v1',
  summary: {
    adapter_count: 0,
    ready_count: 0,
    needs_key_count: 0,
    key_gated_count: 0,
    field_context_required_count: 0,
    smoke_check_count: 0,
    smoke_passed_count: 0,
    smoke_missing_count: 0,
    smoke_failed_count: 0,
  },
  smoke_checks: [],
  adapters: [],
  boundary: 'Adapter readiness loads from the local API when available.',
}

const readableLabel = (value: string | undefined): string => value?.replace(/_/g, ' ') || 'n/a'

export const answerModelLineageView = (
  identity: TurnSystemState['model_identity'] | undefined,
): { label: string; status: string } => {
  if (!identity) {
    return { label: 'Runtime model availability', status: 'Unavailable' }
  }
  if (identity.response_model_id) {
    return { label: 'Answer generation model', status: 'Response identity bound' }
  }
  const receiptStatus = identity.status ? readableLabel(identity.status) : 'Runtime receipt unavailable'
  return {
    label: 'Runtime model availability',
    status: `${receiptStatus} · this answer is not model-bound`,
  }
}

const copyTextToClipboard = async (text: string): Promise<void> => {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  document.body.appendChild(textarea)
  textarea.select()
  const copied = document.execCommand('copy')
  textarea.remove()
  if (!copied) {
    throw new Error('clipboard copy is unavailable in this browser')
  }
}

const defaultQuestion = (field: SampleProfile): string => {
  if (field.id === 'central-alberta-barley') {
    return 'This Alberta barley field has low soil-test phosphorus and uneven early growth. What should I compare and verify before choosing a phosphorus rate or placement strategy?'
  }
  if (field.id === 'regina-thematic-soil') {
    return 'This Saskatchewan spring wheat field has patchy emergence and white crusting in low areas. What should I compare and sample before deciding whether salinity is the cause or changing next year\'s crop plan?'
  }
  if (field.id === 'canola-acidity') {
    return 'This Manitoba canola field has a pale, patchy stand after a cool wet start. What should I compare and sample before deciding whether sulphur deficiency is the cause or choosing a corrective treatment?'
  }
  return `Use this ${field.jurisdiction} ${field.crop} field and map context to give me a practical agronomic read on ${field.concern.toLowerCase()}: what matters most, what should I do next, and what evidence would change the decision?`
}

const geometryForScenario = (scenario: SampleProfile): FieldGeometry => {
  const geometry = scenario.initialGeometry
  if (!geometry || geometry.kind === 'none') {
    return emptyGeometry
  }
  if (geometry.kind === 'point') {
    return { kind: 'point', point: { ...geometry.point } }
  }
  return { kind: 'polygon', points: geometry.points.map((point) => ({ ...point })), acres: geometry.acres }
}

const storedFieldsKey = 'open-agronomy-agent.fields.v1'
const activeStoredFieldKey = 'open-agronomy-agent.active-field.v1'

const loadStoredFields = (): StoredField[] => {
  try {
    const raw = window.localStorage.getItem(storedFieldsKey)
    return raw ? (JSON.parse(raw) as StoredField[]) : []
  } catch {
    return []
  }
}

const loadActiveStoredFieldId = (): string => {
  try {
    return window.localStorage.getItem(activeStoredFieldKey) || ''
  } catch {
    return ''
  }
}

const persistActiveStoredFieldId = (fieldId: string): void => {
  try {
    if (fieldId) {
      window.localStorage.setItem(activeStoredFieldKey, fieldId)
    } else {
      window.localStorage.removeItem(activeStoredFieldKey)
    }
  } catch {
    // Field selection persistence is optional; the account workspace remains authoritative.
  }
}

const fieldPointFromCoords = (coords: unknown): FieldPoint | null => {
  if (!Array.isArray(coords) || coords.length < 2) {
    return null
  }
  const lon = Number(coords[0])
  const lat = Number(coords[1])
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return null
  }
  return { lat, lon }
}

const fieldGeometryFromPolygonCoordinates = (coordinates: unknown): FieldGeometry | null => {
  if (!Array.isArray(coordinates)) {
    return null
  }
  const ring = coordinates[0]
  if (!Array.isArray(ring)) {
    return null
  }
  const points = ring
    .map(fieldPointFromCoords)
    .filter((point): point is FieldPoint => Boolean(point))
  const openRing =
    points.length > 1 && points[0].lat === points[points.length - 1].lat && points[0].lon === points[points.length - 1].lon
      ? points.slice(0, -1)
      : points
  return openRing.length > 2 ? { kind: 'polygon', points: openRing, acres: estimatePolygonAcres(openRing) } : null
}

const fieldGeometryFromGeoJsonLike = (parsed: {
  type?: string
  coordinates?: unknown
  geometry?: { type?: string; coordinates?: unknown }
  features?: Array<{ geometry?: { type?: string; coordinates?: unknown } }>
}): FieldGeometry | null => {
  const geometry =
    parsed.type === 'FeatureCollection'
      ? parsed.features?.find((feature) => feature.geometry)?.geometry
      : parsed.type === 'Feature'
        ? parsed.geometry
        : parsed
  if (geometry?.type === 'Point') {
    const point = fieldPointFromCoords(geometry.coordinates)
    return point ? { kind: 'point', point } : null
  }
  if (geometry?.type === 'Polygon') {
    return fieldGeometryFromPolygonCoordinates(geometry.coordinates)
  }
  if (geometry?.type === 'MultiPolygon' && Array.isArray(geometry.coordinates)) {
    return geometry.coordinates
      .map(fieldGeometryFromPolygonCoordinates)
      .filter((candidate): candidate is FieldGeometry & { kind: 'polygon' } => candidate?.kind === 'polygon')
      .sort((left, right) => right.acres - left.acres)[0] || null
  }
  return null
}

const geoPriorCandidateFromIntersection = (item: RegionalIntersection): GeoPriorCandidate => ({
  label: item.name,
  name: item.name,
  layer: item.layer_id,
  system: item.system,
  code: item.code,
  confidence: item.confidence,
  match_reason: item.match_reason,
  priors: ['official polygon intersection', 'use as regional context prior'],
  evidence_terms: [item.code, item.name],
  source: item.source,
})

const geoPriorsFromIntersections = (
  locationText: string,
  intersections: RegionalIntersection[] = [],
  featureCollection?: GeoFeatureCollection,
  geoErrors: Array<{ layer_id: string; message: string }> = [],
  layerStatus: OfficialLayerStatus[] = [],
): GeoPriors => ({
  location_text: locationText,
  candidate_regions: intersections.map(geoPriorCandidateFromIntersection),
  regional_intersections: intersections,
  regional_feature_collection: featureCollection,
  geo_errors: geoErrors,
  official_layer_status: layerStatus,
  boosted_namespaces: intersections.length ? ['regional_environment_context', 'soil_water', 'crop_management'] : [],
  evidence: intersections.length ? ['official_polygon_intersection'] : [],
  missing_context: intersections.length ? [] : ['regional polygon intersection'],
  uncertainty: intersections[0]?.confidence >= 0.9 ? 'low' : intersections.length ? 'medium' : 'high',
  used_as_prior_only: true,
  not_field_specific_fact: true,
  disclaimer: 'Official regional polygons are used as context priors, not as legal field boundaries.',
  ui_notice: intersections.length
    ? 'Official regional polygons intersected the uploaded or drawn field geometry.'
    : 'No official regional polygon intersection is available for this geometry yet.',
  recommended_followups: ['Confirm the field boundary and local recommendation source before acting.'],
})

const geoPriorsFromBoundaryUpload = (parsed: BoundaryUploadResponse): GeoPriors =>
  geoPriorsFromIntersections(
    `${parsed.filename} ${parsed.source_format} boundary upload`,
    parsed.regional_intersections || [],
    parsed.regional_feature_collection,
    parsed.geo_errors || [],
    parsed.official_layer_status || [],
  )

const formatPercent = (value: number | undefined, fallback = 'unknown'): string =>
  typeof value === 'number' && Number.isFinite(value)
    ? `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
    : fallback

const isCanadianJurisdiction = (jurisdiction: string): boolean =>
  CANADIAN_JURISDICTIONS.has(jurisdiction.trim().toLowerCase())

const agroclimateValue = (indicator: AgroclimateIndicator | undefined): number | null => {
  const value = indicator?.mean ?? indicator?.value
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

const formatAgroclimateValue = (key: string, indicator: AgroclimateIndicator | undefined): string => {
  const value = agroclimateValue(indicator)
  if (value === null) return 'No data'
  if (key === 'temperature_anomaly') return `${value > 0 ? '+' : ''}${value.toFixed(1)} C`
  if (key === 'percent_of_average_precipitation') return `${Math.round(value)}%`
  return value.toFixed(2)
}

const fieldWeatherPoint = (geometry: FieldGeometry): FieldPoint | null => {
  if (geometry.kind === 'point') return geometry.point
  if (geometry.kind !== 'polygon' || geometry.points.length === 0) return null
  return geometry.points.reduce(
    (center, point) => ({
      lat: center.lat + point.lat / geometry.points.length,
      lon: center.lon + point.lon / geometry.points.length,
    }),
    { lat: 0, lon: 0 },
  )
}

const powerMetricValue = (metric: NasaPowerMetric | undefined, key: 'mean' | 'sum', digits = 1): string => {
  const value = metric?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

const powerWindowDates = (): { start: string; end: string } => {
  const end = new Date()
  const start = new Date(end)
  start.setUTCDate(start.getUTCDate() - 2)
  const format = (date: Date) => date.toISOString().slice(0, 10).replace(/-/g, '')
  return { start: format(start), end: format(end) }
}

const regionalContextSummary = (priors: GeoPriors): string => {
  const count = priors.regional_intersections?.length || 0
  if (!count) {
    return 'No official regional polygon matched this field yet. Use the map tools or upload a WGS84 boundary to refresh context.'
  }
  const systems = Array.from(new Set((priors.regional_intersections || []).map((item) => item.system))).slice(0, 3)
  return `${count} official regional match${count === 1 ? '' : 'es'} from ${systems.join(', ')}. Use this as regional guidance for retrieval and source checks, not as soil-test, scouting, yield, legal-boundary, or product-rate evidence.`
}

const regionalMatchDetail = (item: RegionalIntersection): string =>
  `${formatPercent(item.coverage_estimate)} field-geometry coverage estimate · ${formatPercent(item.confidence)} match confidence`

const regionalAuthorityNote = (item: RegionalIntersection): string =>
  item.coverage_area
    ? `${item.coverage_area} historical context—not province-wide or current field truth.`
    : item.layer_id === 'pei_detailed_soil'
    ? 'Historical mapped context, not current field truth.'
    : 'Generalized regional context, not current field truth.'

const regionalSourceScale = (item: RegionalIntersection): string | null => {
  const scale = item.source_scale_label || item.source_scale_range
  if (scale) return `Source mapping scale ${scale}`
  return item.source_scale_note ? `Source resolution: ${item.source_scale_note}` : null
}

const uploadFeatureById = (upload: BoundaryUploadResponse | null, featureId: string): GeoFeature | null =>
  upload?.feature_collection?.features.find((feature) => String(feature.id || '') === featureId) || null

const topDocs = (turn: Turn | null): RetrievedDoc[] => (turn?.trace?.retrieved_docs || []).slice(0, 4)

const decisionLabel = (questionType: string | undefined): string => {
  if (!questionType) return 'Pending'
  if (questionType === 'fertility_diagnostic') return 'Crop stress'
  const label = questionType.replace(/[_-]+/g, ' ')
  return `${label.charAt(0).toUpperCase()}${label.slice(1)}`
}

const sensitivityLabel = (riskLevel: string | undefined): string => {
  if (!riskLevel) return 'Pending'
  if (riskLevel === 'low') return 'Low'
  if (riskLevel === 'medium') return 'Moderate'
  if (riskLevel === 'high') return 'High'
  return riskLevel
}

const publicToolCards = (turn: Turn | null): ToolInvocation[] =>
  (turn?.trace?.tool_invocations || []).filter((tool) => tool.payload?.kind === 'public_adapter')

const geometrySummary = (geometry: FieldGeometry, fallback: string): string => {
  if (geometry.kind === 'point') {
    return `point ${geometry.point.lat.toFixed(5)}, ${geometry.point.lon.toFixed(5)} · prior-only match`
  }
  if (geometry.kind === 'polygon') {
    return `${geometry.points.length} vertices · approx ${Math.round(geometry.acres).toLocaleString()} ac · editable boundary`
  }
  return fallback
}

const fieldGeometryToGeoJson = (geometry: FieldGeometry) => {
  if (geometry.kind === 'point') {
    return { type: 'Point', coordinates: [geometry.point.lon, geometry.point.lat] }
  }
  if (geometry.kind === 'polygon') {
    const ring = geometry.points.map((point) => [point.lon, point.lat])
    if (ring.length > 0) {
      ring.push(ring[0])
    }
    return { type: 'Polygon', coordinates: [ring] }
  }
  return null
}

const representativePointForGeometry = (geometry: FieldGeometry): FieldPoint | null => {
  if (geometry.kind === 'point') {
    return geometry.point
  }
  if (geometry.kind === 'polygon' && geometry.points.length > 0) {
    const lat = geometry.points.reduce((sum, point) => sum + point.lat, 0) / geometry.points.length
    const lon = geometry.points.reduce((sum, point) => sum + point.lon, 0) / geometry.points.length
    return { lat, lon }
  }
  return null
}

const fieldContextIntersections = (items: RegionalIntersection[]) =>
  items.slice(0, 6).map((item) => ({
    layer_id: item.layer_id,
    system: item.system,
    code: item.code,
    name: item.name,
    source_url: item.source_url,
    confidence: item.confidence,
    coverage_estimate: item.coverage_estimate,
    match_reason: item.match_reason,
    source: item.source,
    boundary: item.boundary,
    capability_label: item.capability_label,
    capability_summary: item.capability_summary,
    primary_class: item.primary_class,
    components: item.components,
    source_scale: item.source_scale,
    source_scale_label: item.source_scale_label,
    source_scale_range: item.source_scale_range,
    source_scale_note: item.source_scale_note,
    drainage_class: item.drainage_class,
    capability_class: item.capability_class,
    capability_interpretation: item.capability_interpretation,
    erosion_risk: item.erosion_risk,
    erosion_indicator_2021: item.erosion_indicator_2021,
    erosion_risk_1981: item.erosion_risk_1981,
    erosion_indicator_1981: item.erosion_indicator_1981,
    erosion_change_1981_2021: item.erosion_change_1981_2021,
    erosion_change_indicator: item.erosion_change_indicator,
    erosion_summary: item.erosion_summary,
    soil_landscape_id: item.soil_landscape_id,
    source_year: item.source_year,
    slope_class: item.slope_class,
    surface_texture_group: item.surface_texture_group,
    soil_summary: item.soil_summary,
  }))

const fieldContextLayerStatus = (items: OfficialLayerStatus[]) =>
  items.slice(0, 6).map((item) => ({
    layer_id: item.layer_id,
    system: item.system,
    source_url: item.source_url,
    status: item.status,
    match_count: item.match_count,
    message: item.message,
  }))

const fieldContextSelectedUploadFeature = (feature: UploadFeatureSummary | null) =>
  feature
    ? {
        label: feature.label,
        geometry_type: feature.geometry_type,
        acres: feature.acres,
      }
    : undefined

const parseSseEvent = (chunk: string): ParsedSseEvent | null => {
  const lines = chunk.split('\n')
  let eventName = 'message'
  let dataText = ''
  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventName = line.slice('event:'.length).trim()
    }
    if (line.startsWith('data:')) {
      const value = line.slice('data:'.length).trim()
      dataText = `${dataText}${dataText ? '\n' : ''}${value}`
    }
  }
  if (!dataText) {
    return null
  }
  try {
    return { event: eventName, payload: JSON.parse(dataText) as Record<string, unknown> }
  } catch {
    return null
  }
}

const readSseStream = async (
  response: Response,
  onEvent: (event: ParsedSseEvent) => void,
): Promise<void> => {
  const reader = response.body?.getReader()
  if (!reader) {
    const text = await response.text()
    text.split('\n\n').map(parseSseEvent).forEach((event) => {
      if (event) onEvent(event)
    })
    return
  }
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const chunk = await reader.read()
    if (chunk.done) {
      break
    }
    buffer += decoder.decode(chunk.value, { stream: true })
    const pieces = buffer.split('\n\n')
    buffer = pieces.pop() || ''
    for (const piece of pieces) {
      const event = parseSseEvent(piece)
      if (event) onEvent(event)
    }
  }
  if (buffer.trim()) {
    const event = parseSseEvent(buffer)
    if (event) onEvent(event)
  }
}

const normalizeChatMarkdown = (text: string): string =>
  text
    .replace(/\s+\*\s+(?=\*\*)/g, '\n* ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()

const safeMarkdownUrl = (url: string): string => (/^https:\/\//i.test(url) ? url : '')

export function FormattedAnswer({ text }: { text: string }) {
  return (
    <div className="formatted-answer">
      <ReactMarkdown
        skipHtml
        urlTransform={safeMarkdownUrl}
        components={{
          a: ({ href, children }) => href?.startsWith('https://')
            ? <a href={href} target="_blank" rel="noreferrer">{children}</a>
            : <span>{children}</span>,
        }}
      >
        {normalizeChatMarkdown(text)}
      </ReactMarkdown>
    </div>
  )
}

const primaryRegionalCandidate = (priors: GeoPriors | null): GeoPriorCandidate | null => {
  const candidates = priors?.candidate_regions || []
  return candidates.find((candidate) =>
    /(?:soil|capability|erosion)/i.test(`${candidate.system} ${candidate.name} ${candidate.code}`),
  ) || candidates[0] || null
}

const streamProgressFromPayload = (payload: Record<string, unknown>, kind: StreamProgressStep['kind']): StreamProgressStep => ({
  label: String(payload.label || (kind === 'heartbeat' ? 'Working locally' : 'Working')),
  detail: String(payload.detail || ''),
  progress: Math.max(0, Math.min(100, Number(payload.progress || 0))),
  elapsedMs: Math.max(0, Number(payload.elapsed_ms || 0)),
  kind,
  stageId: typeof payload.stage_id === 'string' ? payload.stage_id : undefined,
  status: typeof payload.stage_status === 'string' ? payload.stage_status : undefined,
  category: typeof payload.category === 'string' ? payload.category : undefined,
  durationMs: typeof payload.duration_ms === 'number' ? payload.duration_ms : undefined,
})

const formatElapsed = (elapsedMs: number): string => {
  if (elapsedMs < 1000) return '<1s'
  return `${Math.round(elapsedMs / 1000)}s`
}

function StreamProgressPanel({ steps, draft }: { steps: StreamProgressStep[]; draft: string }) {
  const latest = steps[steps.length - 1]
  const visibleSteps = steps.filter((step) => step.kind === 'step').slice(-5)
  if (!latest) {
    return null
  }
  return (
    <div className="stream-progress" aria-live="polite">
      <div className="stream-progress-header">
        <strong>{latest.label}</strong>
        <span>{formatElapsed(latest.elapsedMs)}</span>
      </div>
      <div className="stream-progress-bar" aria-label="Agent progress">
        <div style={{ width: `${latest.progress}%` }} />
      </div>
      <p>{latest.detail}</p>
      <ol>
        {visibleSteps.map((step) => (
          <li key={`${step.stageId || step.label}-${step.elapsedMs}`} className={`stream-step status-${step.status || 'ok'}`}>
            <span>{step.label}</span>
            {step.category ? <small>{step.category}</small> : null}
          </li>
        ))}
      </ol>
      {!draft ? <small>Waiting for the first answer chunk from the local model.</small> : null}
    </div>
  )
}

function PublicToolSourceList({ tools, emptyLabel = 'Draw a point or boundary to let the backend check public soil, crop-cover, and weather sources for this turn.' }: {
  tools: ToolInvocation[]
  emptyLabel?: string
}) {
  const cards = tools.map(buildPublicToolCard)
  return (
    <div className="tool-source-list">
      <div className="tool-source-header">
        <span>Live source checks</span>
        <strong>{summarizePublicToolCards(tools)}</strong>
      </div>
      {cards.length ? (
        cards.map((card) => <PublicToolSourceCard key={`${card.name}-${card.status}-${card.title}`} card={card} />)
      ) : (
        <p>{emptyLabel}</p>
      )}
    </div>
  )
}

function StructuredEvidenceList({ cards, label = 'Map context evidence', emptyLabel = 'Run a layer intersection from a point, drawn boundary, or uploaded field file to populate map evidence.' }: {
  cards: StructuredEvidenceCard[]
  label?: string
  emptyLabel?: string
}) {
  const displayCards = cards.map(buildStructuredEvidenceCard)
  return (
    <div className="tool-source-list structured-evidence-list">
      <div className="tool-source-header">
        <span>{label}</span>
        <strong>{summarizeStructuredEvidenceCards(cards)}</strong>
      </div>
      {displayCards.length ? (
        displayCards.map((card) => <PublicToolSourceCard key={`${card.name}-${card.status}-${card.title}`} card={card} />)
      ) : (
        <p>{emptyLabel}</p>
      )}
    </div>
  )
}

function PublicToolSourceCard({ card }: { card: PublicToolCard }) {
  return (
    <article className={`tool-source-card status-${card.statusTone}`}>
      <div className="tool-source-title-row">
        <div>
          <strong>{card.title}</strong>
          <small>{card.provider}</small>
        </div>
        <span className={`source-status ${card.statusTone}`}>{card.statusLabel}</span>
      </div>
      {card.facts.length ? (
        <div className="tool-source-facts" aria-label={`${card.title} facts`}>
          {card.facts.slice(0, 4).map((fact) => (
            <span key={fact}>{fact}</span>
          ))}
        </div>
      ) : null}
      <p className="tool-source-boundary">{card.limitation}</p>
      {card.sourceUrl || card.sourceLabel || card.links?.length ? (
        <div className="tool-source-links">
          {card.sourceUrl ? (
            <a className="tool-source-reference" href={card.sourceUrl} target="_blank" rel="noreferrer">
              Source
            </a>
          ) : card.sourceLabel ? (
            <small className="tool-source-reference">{card.sourceLabel}</small>
          ) : null}
          {card.links?.map((link) => (
            <a key={`${link.label}-${link.url}`} className="tool-source-reference" href={link.url} target="_blank" rel="noreferrer">
              {link.label}
            </a>
          ))}
        </div>
      ) : null}
    </article>
  )
}

function SourceCheckSummaryPanel({ summary }: { summary: SourceCheckSummary }) {
  return (
    <div className={`source-check-summary status-${summary.tone}`} aria-label="Source check summary">
      <div className="source-check-summary-header">
        <span>Source check</span>
        <strong>{summary.label}</strong>
      </div>
      <div className="source-check-summary-grid">
        {summary.items.map((item) => (
          <div key={item.label} className={`source-check-summary-item status-${item.tone}`}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
    </div>
  )
}

const adapterReadinessTone = (status: string): 'ok' | 'attention' | 'unavailable' => {
  if (status === 'ready') return 'ok'
  if (status === 'needs_key' || status === 'monitor') return 'attention'
  return 'unavailable'
}

const smokeReadinessTone = (status?: string): 'ok' | 'attention' | 'unavailable' => {
  if (status === 'passed') return 'ok'
  if (status === 'missing' || status === 'not_required' || !status) return 'attention'
  return 'unavailable'
}

const adapterPanelTone = (adapter: PublicAdapterReadinessItem): 'ok' | 'attention' | 'unavailable' => {
  const baseTone = adapterReadinessTone(adapter.status)
  const smokeTone = smokeReadinessTone(adapter.smoke_status)
  if (smokeTone === 'unavailable') return 'unavailable'
  if (smokeTone === 'attention' && baseTone === 'ok' && adapter.smoke_status !== 'not_required') return 'attention'
  return baseTone
}

const summarizeAdapterReadiness = (readiness: PublicAdapterReadiness): string => {
  const ready = readiness.summary.ready_count || 0
  const total = readiness.summary.adapter_count || readiness.adapters.length
  const needsKey = readiness.summary.needs_key_count || 0
  const base = needsKey ? `${ready}/${total} ready · ${needsKey} need key` : `${ready}/${total} ready`
  const smokeTotal = readiness.summary.smoke_check_count || readiness.smoke_checks?.length || 0
  const smokePassed = readiness.summary.smoke_passed_count || 0
  return smokeTotal ? `${base} · ${smokePassed}/${smokeTotal} smokes` : base
}

const formatSmokeNumber = (value: number): string => new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value)

const smokeCheckText = (check: PublicAdapterSmokeCheck): string => {
  const parts = []
  if (check.mode) parts.push(check.mode)
  if (check.case_count !== undefined) parts.push(`${formatSmokeNumber(check.case_count)} cases`)
  if (check.failure_count) parts.push(`${formatSmokeNumber(check.failure_count)} failures`)
  if (check.artifact_path) parts.push(check.artifact_path)
  return parts.join(' · ')
}

function PublicAdapterReadinessPanel({ readiness, compact = false }: { readiness: PublicAdapterReadiness; compact?: boolean }) {
  const visibleAdapters = compact
    ? readiness.adapters
        .filter((adapter) => adapter.credential_required || adapter.status !== 'ready' || adapter.smoke_status === 'failed' || adapter.smoke_status === 'missing')
        .slice(0, 4)
    : readiness.adapters
  return (
    <section className="adapter-readiness-panel">
      <div className="adapter-readiness-header">
        <div>
          <span>Public source readiness</span>
          <strong>{summarizeAdapterReadiness(readiness)}</strong>
        </div>
        {readiness.generated_at ? <small>{new Date(readiness.generated_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</small> : null}
      </div>
      {visibleAdapters.length ? (
        <div className="adapter-readiness-list">
          {visibleAdapters.map((adapter) => {
            const tone = adapterPanelTone(adapter)
            const neededKey = adapter.status === 'needs_key' && adapter.required_env_vars?.length
              ? `Set ${adapter.required_env_vars.slice(0, 2).join(' or ')}`
              : adapter.demo_impact || adapter.trigger || 'Ready for source-context checks.'
            return (
              <article key={adapter.id} className={`adapter-readiness-item status-${tone}`}>
                <div>
                  <strong>{adapter.label}</strong>
                  <span>{adapter.provider}</span>
                </div>
                <small className={`source-status ${tone}`}>{adapter.status_label || adapter.status.replace(/_/g, ' ')}</small>
                <p>{neededKey}</p>
                {adapter.smoke_checks?.length ? (
                  <div className="adapter-smoke-checks">
                    {adapter.smoke_checks.map((check) => {
                      const smokeTone = smokeReadinessTone(check.status)
                      return (
                        <p key={check.id || check.label || check.artifact_path}>
                          <small className={`source-status ${smokeTone}`}>{check.status_label || check.status || 'smoke status'}</small>
                          <span>{smokeCheckText(check)}</span>
                        </p>
                      )
                    })}
                  </div>
                ) : null}
                {!compact && adapter.boundary ? <p className="adapter-readiness-boundary">{adapter.boundary}</p> : null}
              </article>
            )
          })}
        </div>
      ) : (
        <p>{readiness.boundary || 'Adapter readiness loads from the local API.'}</p>
      )}
      {compact ? <small>{readiness.boundary}</small> : null}
    </section>
  )
}

function CredentialPreflightPanel({ readiness }: { readiness: PublicAdapterReadiness }) {
  const keyGatedAdapters = readiness.adapters.filter((adapter) => adapter.credential_required)
  const missingAdapters = keyGatedAdapters.filter((adapter) => adapter.status === 'needs_key')
  const readyAdapters = keyGatedAdapters.length - missingAdapters.length
  return (
    <section className={`credential-preflight-panel status-${missingAdapters.length ? 'attention' : 'ok'}`}>
      <div className="credential-preflight-header">
        <div>
          <span>Credential preflight</span>
          <strong>
            {keyGatedAdapters.length
              ? `${readyAdapters}/${keyGatedAdapters.length} key-gated adapters configured`
              : 'No key-gated adapters reported'}
          </strong>
        </div>
        <small>Variable names only. Secret values are never shown.</small>
      </div>
      <div className="credential-preflight-list">
        {keyGatedAdapters.map((adapter) => (
          <article key={adapter.id} className={`status-${adapter.status === 'needs_key' ? 'attention' : 'ok'}`}>
            <div>
              <strong>{adapter.label}</strong>
              <span className={`source-status ${adapter.status === 'needs_key' ? 'attention' : 'ok'}`}>
                {adapter.status_label || readableLabel(adapter.status)}
              </span>
            </div>
            <p>{adapter.demo_impact || adapter.trigger || 'Required for live public-source demo coverage.'}</p>
            {adapter.required_env_vars?.length ? (
              <code>Set one: {adapter.required_env_vars.join(' or ')}</code>
            ) : null}
          </article>
        ))}
        {!keyGatedAdapters.length ? (
          <article className="status-attention">
            <div>
              <strong>Adapter readiness unavailable</strong>
              <span className="source-status attention">review</span>
            </div>
            <p>Load the local API before making live-source credential claims.</p>
          </article>
        ) : null}
      </div>
      <div className="credential-command-list">
        <span>After setting credentials in the local shell or container, run:</span>
        <code>PYTHONPATH=src:. python scripts/smoke_keyed_public_adapters.py</code>
        <code>PYTHONPATH=src:. python scripts/smoke_keyed_public_adapters.py --live</code>
        <code>curl -s http://127.0.0.1:8001/api/tools/public-adapter-readiness</code>
      </div>
      <p>
        Offline smokes prove credential handling and fixture normalization. Live smoke is still required before the demo
        claims OpenET or NASS Quick Stats as live coverage.
      </p>
    </section>
  )
}

export function OpenAgronomyApp() {
  const conversationThreadRef = useRef<HTMLDivElement | null>(null)
  const latestAssistantMessageRef = useRef<HTMLElement | null>(null)
  const observedTurnCountRef = useRef(0)
  const completedTurnPendingRef = useRef(false)
  const regionalLookupRequestRef = useRef(0)
  const agroclimateRequestRef = useRef(0)
  const nasaPowerRequestRef = useRef(0)
  const [page, setPage] = useState<Page>(() => currentHashPage())
  const [sessions, setSessions] = useState<SessionRecord[]>([])
  const [sessionId, setSessionId] = useState('')
  const [activeFieldContextId, setActiveFieldContextId] = useState('')
  const [activeFieldConversationKey, setActiveFieldConversationKey] = useState(
    sampleConversationKey(sampleProfiles[0].id),
  )
  const [activeFieldRecordUpdatedAt, setActiveFieldRecordUpdatedAt] = useState('')
  const [field, setField] = useState<FieldProfile>(sampleProfiles[0])
  const [fieldName, setFieldName] = useState(sampleProfiles[0].name)
  const [scenarioId, setScenarioId] = useState(sampleProfiles[0].id)
  const [boundaryStatus, setBoundaryStatus] = useState('Sample boundary loaded.')
  const [isMapContextChecking, setIsMapContextChecking] = useState(false)
  const [geometryDraft, setGeometryDraft] = useState<FieldGeometry | null>(null)
  const [geometryEditSnapshot, setGeometryEditSnapshot] = useState<GeometryEditSnapshot | null>(null)
  const [fieldToolsOpen, setFieldToolsOpen] = useState(false)
  const [mapMode, setMapMode] = useState<MapMode>('inspect')
  const [fieldGeometry, setFieldGeometry] = useState<FieldGeometry>(() => geometryForScenario(sampleProfiles[0]))
  const [uploadContext, setUploadContext] = useState<BoundaryUploadResponse | null>(null)
  const [selectedUploadFeatureId, setSelectedUploadFeatureId] = useState('')
  const [storedFields, setStoredFields] = useState<StoredField[]>([])
  const [fieldLibraryQuery, setFieldLibraryQuery] = useState('')
  const [fieldLibrarySort, setFieldLibrarySort] = useState<'updated' | 'name' | 'crop' | 'region'>('updated')
  const [renamingFieldId, setRenamingFieldId] = useState('')
  const [renameValue, setRenameValue] = useState('')
  const [fieldsHydrated, setFieldsHydrated] = useState(false)
  const [storedFieldRestoreAttempted, setStoredFieldRestoreAttempted] = useState(false)
  const [fieldStorageMode, setFieldStorageMode] = useState<'account_workspace' | 'device'>('device')
  const [fieldStorageStatus, setFieldStorageStatus] = useState('Loading fields.')
  const [fieldHistory, setFieldHistory] = useState<DemoFieldHistoryResponse | null>(null)
  const [fieldHistoryStatus, setFieldHistoryStatus] = useState('Select a field.')
  const [fieldAnswerReviewPending, setFieldAnswerReviewPending] = useState('')
  const [fieldEventType, setFieldEventType] = useState<FieldEvent['event_type']>('observation')
  const [fieldEventSummary, setFieldEventSummary] = useState('')
  const [fieldEventOccurredAt, setFieldEventOccurredAt] = useState('')
  const [fieldCorrectionTarget, setFieldCorrectionTarget] = useState('')
  const [geoPriors, setGeoPriors] = useState<GeoPriors | null>(null)
  const [agroclimate, setAgroclimate] = useState<AgroclimateState>({ status: 'idle' })
  const [agroclimateRefresh, setAgroclimateRefresh] = useState(0)
  const [nasaPower, setNasaPower] = useState<NasaPowerState>({ status: 'idle' })
  const [nasaPowerRefresh, setNasaPowerRefresh] = useState(0)
  const [message, setMessage] = useState(defaultQuestion(sampleProfiles[0]))
  const [mode] = useState<DemoMode>('agronomic_rag')
  const [modelId, setModelId] = useState('mock')
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([])
  const [networkMode, setNetworkMode] = useState<'online' | 'offline' | 'unknown'>('unknown')
  const [runtimeAccess, setRuntimeAccess] = useState<RuntimeAccess>('checking')
  const [draftHydratedFor, setDraftHydratedFor] = useState('')
  const [scratchpadHydratedFor, setScratchpadHydratedFor] = useState('')
  const [scratchpadNotes, setScratchpadNotes] = useState('')
  const [offlineStorageRepair, setOfflineStorageRepair] =
    useState<Phase6OfflineStorageRepairDetail | null>(null)
  const [privateKnowledge, setPrivateKnowledge] = useState<PrivateKnowledgeInspection[]>([])
  const [ragConfig, setRagConfig] = useState('configs/rag_final_mvp.yaml')
  const [adapterReadiness, setAdapterReadiness] = useState<PublicAdapterReadiness>(fallbackAdapterReadiness)
  const [turns, setTurns] = useState<Turn[]>([])
  const [evidenceTurnId, setEvidenceTurnId] = useState('')
  const [status, setStatus] = useState('Ready')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [streamDraft, setStreamDraft] = useState('')
  const [streamProgress, setStreamProgress] = useState<StreamProgressStep[]>([])
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [error, setError] = useState('')

  const latestTurn = turns[turns.length - 1] || null
  const evidenceTurn = turns.find((turn) => turn.turn_id === evidenceTurnId) || latestTurn
  const activeScenario = sampleProfiles.find((sample) => sample.id === scenarioId) || sampleProfiles[0]
  const evidenceDocs = topDocs(evidenceTurn)
  const evidenceRetrievedDocCount = evidenceTurn?.trace?.retrieved_docs?.length || 0
  const evidenceLiveToolCards = publicToolCards(evidenceTurn)
  const evidenceMapCards = mapContextEvidenceCards(evidenceTurn)
  const evidenceSourceSummary = buildSourceCheckSummary(evidenceLiveToolCards, evidenceMapCards)
  const evidenceTraceGroups = buildTraceToolGroups(evidenceTurn, evidenceMapCards)
  const primaryGeoCandidate = primaryRegionalCandidate(geoPriors)
  const mapGeometry = geometryDraft || fieldGeometry
  const isEditingGeometry = geometryEditSnapshot !== null
  const committedWeatherPoint = fieldWeatherPoint(fieldGeometry)
  const geometryIssue = fieldGeometryIssue(fieldGeometry)
  const geometryReady = isUsableFieldGeometry(fieldGeometry)
  const activeArea = fieldGeometry.kind === 'polygon' ? Math.round(fieldGeometry.acres).toLocaleString() : field.acres
  const selectedModelProfile = modelProfiles.find((profile) => profile.id === modelId)
  const selectedModelReady = selectedModelProfile?.local_ready !== false
  const selectedUploadFeature =
    uploadContext?.feature_summaries?.find((feature) => feature.id === selectedUploadFeatureId) ||
    uploadContext?.feature_summaries?.find((feature) => feature.selected) ||
    null
  const officialIntersections = geoPriors?.regional_intersections || []
  const officialLayerStatus = geoPriors?.official_layer_status || uploadContext?.official_layer_status || []
  const geoErrors = geoPriors?.geo_errors || uploadContext?.geo_errors || []
  const geoErrorCount = geoErrors.length
  const answerCapability = fieldAnswerCapability(runtimeAccess, networkMode)

  const navigateToPage = (nextPage: Page) => {
    setPage(nextPage)
    if (typeof window === 'undefined') {
      return
    }
    const nextHash = pageHash(nextPage)
    if (window.location.hash !== nextHash) {
      window.history.pushState(null, '', nextHash)
    }
  }

  const contextCompleteness = useMemo(() => {
    const values = [field.crop, field.region, field.jurisdiction, field.concern]
    return Math.round((values.filter((value) => value.trim()).length / values.length) * 100)
  }, [field])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    const syncPageFromHash = () => {
      setPage(currentHashPage())
    }
    window.addEventListener('hashchange', syncPageFromHash)
    window.addEventListener('popstate', syncPageFromHash)
    syncPageFromHash()
    return () => {
      window.removeEventListener('hashchange', syncPageFromHash)
      window.removeEventListener('popstate', syncPageFromHash)
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    const markUnavailable = () => setRuntimeAccess('unavailable')
    const checkRuntime = async () => {
      setRuntimeAccess('checking')
      try {
        await apiGet('/api/health')
        setRuntimeAccess('available')
      } catch {
        setRuntimeAccess('unavailable')
      }
    }
    window.addEventListener('offline', markUnavailable)
    window.addEventListener('online', checkRuntime)
    return () => {
      window.removeEventListener('offline', markUnavailable)
      window.removeEventListener('online', checkRuntime)
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') {
      return
    }
    const showRecoveryNotice = (event: Event) => {
      setOfflineStorageRepair((event as CustomEvent<Phase6OfflineStorageRepairDetail>).detail)
    }
    window.addEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, showRecoveryNotice)
    return () => {
      window.removeEventListener(PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT, showRecoveryNotice)
    }
  }, [])

  useEffect(() => {
    const saved = loadPhase6ChatDraft(activeFieldConversationKey)
    if (saved?.message) {
      setMessage(saved.message)
    }
    setDraftHydratedFor(activeFieldConversationKey)
  }, [activeFieldConversationKey])

  useEffect(() => {
    if (draftHydratedFor !== activeFieldConversationKey) {
      return
    }
    savePhase6ChatDraft(activeFieldConversationKey, message)
  }, [activeFieldConversationKey, draftHydratedFor, message])

  useEffect(() => {
    const saved = loadPhase6Scratchpad(activeFieldConversationKey)
    setScratchpadNotes(saved?.notes || '')
    setScratchpadHydratedFor(activeFieldConversationKey)
  }, [activeFieldConversationKey])

  useEffect(() => {
    if (scratchpadHydratedFor !== activeFieldConversationKey) {
      return
    }
    savePhase6Scratchpad(activeFieldConversationKey, scratchpadNotes)
  }, [activeFieldConversationKey, scratchpadHydratedFor, scratchpadNotes])

  useEffect(() => {
    ;(async () => {
      try {
        const [loadedSessions, configs] = await Promise.all([
          apiGet<SessionRecord[]>('/api/sessions?include_archived=true'),
          apiGet<ConfigResponse>('/api/configs'),
        ])
        setSessions(loadedSessions)
        const persistedFieldId = loadActiveStoredFieldId()
        const matchingSession = sessionForField(
          loadedSessions,
          persistedFieldId
            ? storedFieldConversationKey(persistedFieldId)
            : sampleConversationKey(sampleProfiles[0].id),
          persistedFieldId,
        )
        setSessionId(matchingSession?.session_id || '')
        setTurns(matchingSession?.turns || [])
        const nextModels = configs.models.length > 0 ? configs.models : ['mock']
        const nextRagConfigs = configs.rag_configs.length > 0 ? configs.rag_configs : ['configs/rag_final_mvp.yaml']
        const nextProfiles = configs.model_profiles || []
        setModelProfiles(nextProfiles)
        setNetworkMode(
          configs.network?.mode === 'offline'
            ? 'offline'
            : configs.network?.mode === 'online'
              ? 'online'
              : 'unknown',
        )
        setRuntimeAccess('available')
        const readyProfile = nextProfiles.find((profile) => profile.local_ready !== false)
        setModelId(readyProfile?.id || (nextModels.includes('mock') ? 'mock' : nextModels[0]))
        setRagConfig(configs.default_rag_config || nextRagConfigs[0])
      } catch (err) {
        setRuntimeAccess('unavailable')
        setError(String((err as Error).message || err))
      }
    })()
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        setAdapterReadiness(await apiGet<PublicAdapterReadiness>('/api/tools/public-adapter-readiness'))
      } catch {
        setAdapterReadiness(fallbackAdapterReadiness)
      }
    })()
  }, [])

  useEffect(() => {
    ;(async () => {
      try {
        const payload = await apiGet<DemoFieldsResponse>('/api/demo/fields')
        setStoredFields(payload.fields || [])
        setFieldStorageMode('account_workspace')
        setFieldStorageStatus(
          payload.storage.workspace_name
            ? `Saved to ${payload.storage.workspace_name}.`
            : 'Saved to the local account workspace.',
        )
      } catch {
        setStoredFields(loadStoredFields())
        setFieldStorageMode('device')
        setFieldStorageStatus('Device-only fallback; backend field storage is unavailable.')
      } finally {
        setFieldsHydrated(true)
      }
    })()
  }, [])

  useEffect(() => {
    if (!fieldsHydrated || fieldStorageMode !== 'device') {
      return
    }
    window.localStorage.setItem(storedFieldsKey, JSON.stringify(storedFields))
  }, [fieldStorageMode, fieldsHydrated, storedFields])

  useEffect(() => {
    const conversation = conversationThreadRef.current
    if (!conversation) {
      return
    }
    if (turns.length > observedTurnCountRef.current) {
      completedTurnPendingRef.current = true
    }
    observedTurnCountRef.current = turns.length
    const frame = window.requestAnimationFrame(() => {
      if (isAnalyzing) {
        conversation.scrollTop = conversation.scrollHeight
        return
      }
      const latestAnswer = latestAssistantMessageRef.current
      if (!completedTurnPendingRef.current || !latestAnswer) {
        return
      }
      const conversationTop = conversation.getBoundingClientRect().top
      const answerTop = latestAnswer.getBoundingClientRect().top
      conversation.scrollTop = Math.max(0, conversation.scrollTop + answerTop - conversationTop - 8)
      completedTurnPendingRef.current = false
    })
    return () => window.cancelAnimationFrame(frame)
  }, [turns.length, isAnalyzing, streamDraft, streamProgress.length])

  const applyScenario = (id: string) => {
    regionalLookupRequestRef.current += 1
    const scenario = sampleProfiles.find((sample) => sample.id === id) || sampleProfiles[0]
    const fieldConversationKey = sampleConversationKey(scenario.id)
    const matchingSession = sessionForField(sessions, fieldConversationKey)
    setScenarioId(scenario.id)
    setActiveFieldContextId('')
    persistActiveStoredFieldId('')
    setActiveFieldConversationKey(fieldConversationKey)
    setActiveFieldRecordUpdatedAt('')
    setFieldHistory(null)
    setFieldHistoryStatus('Save this field to build a durable answer history.')
    setSessionId(matchingSession?.session_id || '')
    setTurns(matchingSession?.turns || [])
    setEvidenceTurnId('')
    setField(scenario)
    setFieldName(scenario.name)
    setBoundaryStatus('Sample boundary loaded.')
    setFieldGeometry(geometryForScenario(scenario))
    setGeometryDraft(null)
    setGeometryEditSnapshot(null)
    setFieldToolsOpen(false)
    setUploadContext(null)
    setSelectedUploadFeatureId('')
    setGeoPriors(null)
    setMessage(defaultQuestion(scenario))
    setMapMode('inspect')
  }

  const startNewField = () => {
    regionalLookupRequestRef.current += 1
    setIsMapContextChecking(false)
    persistActiveStoredFieldId('')
    setActiveFieldContextId('')
    setActiveFieldConversationKey(freshConversationKey('new-field'))
    setActiveFieldRecordUpdatedAt('')
    setSessionId('')
    setTurns([])
    setEvidenceTurnId('')
    setMessage('')
    setScratchpadNotes('')
    setFieldName('')
    setField({ ...emptyFieldProfile })
    setFieldGeometry(emptyGeometry)
    setGeometryDraft(emptyGeometry)
    setGeometryEditSnapshot({ geoPriors: null, uploadContext: null, selectedUploadFeatureId: '' })
    setUploadContext(null)
    setSelectedUploadFeatureId('')
    setGeoPriors(null)
    setFieldHistory(null)
    setFieldHistoryStatus('Save this new field to begin a durable field timeline.')
    setAgroclimate({ status: 'idle' })
    setNasaPower({ status: 'idle' })
    setFieldToolsOpen(true)
    setMapMode('boundary')
    setBoundaryStatus('Start with field details, then draw or upload a boundary. Save the geometry to retrieve regional context.')
  }

  const ensureSession = async (): Promise<string> => {
    const currentSession = sessions.find((session) => session.session_id === sessionId)
    if (
      currentSession &&
      sessionForField([currentSession], activeFieldConversationKey, activeFieldContextId)
    ) {
      return sessionId
    }
    const matchingSession = sessionForField(
      sessions,
      activeFieldConversationKey,
      activeFieldContextId,
    )
    if (matchingSession) {
      setSessionId(matchingSession.session_id)
      setTurns(matchingSession.turns || [])
      return matchingSession.session_id
    }
    const created = await apiPost<SessionRecord>('/api/sessions', {
      title: `${field.crop || 'Field'} · ${field.region || field.jurisdiction || 'field review'}`,
      tags: ['open-agronomy-agent', 'field-analysis'],
      consent: {
        local_trace_capture: true,
        research_export_allowed: true,
        training_export_allowed: false,
      },
      context: {
        crop: field.crop,
        region: field.region,
        jurisdiction: field.jurisdiction,
        notes: field.notes,
        field_context_id: activeFieldContextId || undefined,
        field_conversation_key: activeFieldConversationKey,
        field_record_updated_at: activeFieldRecordUpdatedAt || undefined,
      },
    })
    setSessions((current) => [created, ...current])
    setSessionId(created.session_id)
    setTurns(created.turns || [])
    return created.session_id
  }

  const resetChat = () => {
    if (isAnalyzing) return
    const baseConversationKey = activeFieldContextId
      ? storedFieldConversationKey(activeFieldContextId)
      : sampleConversationKey(scenarioId)
    clearPhase6ChatDraft(activeFieldConversationKey)
    clearPhase6Scratchpad(activeFieldConversationKey)
    setActiveFieldConversationKey(freshConversationKey(baseConversationKey))
    setSessionId('')
    setTurns([])
    setEvidenceTurnId('')
    setMessage('')
    setScratchpadNotes('')
    setStreamDraft('')
    setStreamProgress([])
    setPendingQuestion('')
    setError('')
    setStatus('Fresh chat ready')
  }

  const sendQuestion = async (event: FormEvent) => {
    event.preventDefault()
    if (!message.trim()) {
      return
    }
    if (!answerCapability.canGenerateAnswer) {
      savePhase6ChatDraft(activeFieldConversationKey, message)
      setStatus('Notes only')
      setError('The local agronomy runtime is unavailable. Your question draft remains on this device; reconnect to the prepared runtime before asking.')
      return
    }
    setError('')
    setStatus('Analyzing field context')
    setIsAnalyzing(true)
    setPendingQuestion(message.trim())
    setStreamDraft('')
    setStreamProgress([
      {
        label: 'Submitting field question',
        detail: 'Sending map and field context to the local agent.',
        progress: 4,
        elapsedMs: 0,
        kind: 'step',
        stageId: 'client.submit',
        status: 'ok',
        category: 'request',
      },
    ])
    try {
      const id = await ensureSession()
      const payload = {
        message,
        mode,
        model_id: mode === 'mock' || modelId === 'mock' ? undefined : modelId,
        rag_config: mode === 'baseline' ? undefined : ragConfig,
        max_tokens: selectedModelProfile?.max_tokens || 240,
        session_context: {
          crop: field.crop,
          region: field.region,
          jurisdiction: field.jurisdiction,
          concern: field.concern,
          field_context_id: activeFieldContextId || undefined,
          field_conversation_key: activeFieldConversationKey,
          field_record_updated_at: activeFieldRecordUpdatedAt || undefined,
          field_context: {
            enable_public_adapters: true,
            crop: field.crop,
            region: field.region,
            jurisdiction: field.jurisdiction,
            concern: field.concern,
            field_context_id: activeFieldContextId || undefined,
            field_conversation_key: activeFieldConversationKey,
            field_record_updated_at: activeFieldRecordUpdatedAt || undefined,
            geometry: fieldGeometryToGeoJson(fieldGeometry),
            representative_point: representativePointForGeometry(fieldGeometry),
            geometry_summary: geometrySummary(fieldGeometry, activeScenario.geometry),
            regional_context: primaryGeoCandidate
              ? `${primaryGeoCandidate.system} ${primaryGeoCandidate.code} ${primaryGeoCandidate.name}`
              : activeScenario.mlra,
            regional_intersections: fieldContextIntersections(officialIntersections),
            official_layer_status: fieldContextLayerStatus(officialLayerStatus),
            upload_warnings: uploadContext?.warnings || [],
            selected_upload_feature: fieldContextSelectedUploadFeature(selectedUploadFeature),
          },
          workspace_retrieved_docs: privateKnowledgeForQuestion(privateKnowledge, message),
          ephemeral_private_source_summary: privateKnowledge.map((item) => ({
            filename: item.filename,
            raw_sha256: item.raw_sha256,
            chunk_count: item.chunks.length,
          })),
        },
        trace_options: {
          store_prompt_messages: privateKnowledge.length === 0,
          store_retrieved_text: privateKnowledge.length === 0,
          redaction_mode: 'none',
        },
      }
      const response = await fetch(`/api/sessions/${id}/turns/stream`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) {
        throw new Error(`${response.status}: ${await response.text()}`)
      }
      let completedTurn: Turn | null = null
      let streamError = ''
      await readSseStream(response, (event) => {
        if (event.event === 'progress.step' || event.event === 'progress.heartbeat') {
          const nextStep = streamProgressFromPayload(
            event.payload,
            event.event === 'progress.heartbeat' ? 'heartbeat' : 'step',
          )
          setStreamProgress((current) => [...current, nextStep].slice(-12))
          setStatus(nextStep.label)
        }
        if (event.event === 'generation.token') {
          setStatus('Writing answer')
          const token = typeof event.payload.token === 'string' ? event.payload.token : ''
          if (token) {
            setStreamDraft((current) => `${current}${token}`)
          }
        }
        if (event.event === 'error') {
          streamError = String(event.payload.message || 'generation failed')
        }
        if (event.event === 'answer.completed' && event.payload.turn && typeof event.payload.turn === 'object') {
          completedTurn = event.payload.turn as Turn
        }
      })
      if (streamError) {
        throw new Error(streamError)
      }
      if (completedTurn) {
        setTurns((current) => [...current, completedTurn as Turn])
        setEvidenceTurnId((completedTurn as Turn).turn_id)
        setSessions((current) =>
          current.map((session) =>
            session.session_id === id
              ? { ...session, turns: [...(session.turns || []), completedTurn as Turn] }
              : session,
          ),
        )
        setStreamDraft('')
      } else {
        const fallback = await apiPost<TurnCreateResponse>(`/api/sessions/${id}/turns`, payload)
        setTurns((current) => [...current, fallback.turn])
        setEvidenceTurnId(fallback.turn.turn_id)
        setSessions((current) =>
          current.map((session) =>
            session.session_id === id
              ? { ...session, turns: [...(session.turns || []), fallback.turn] }
              : session,
          ),
        )
        setStreamDraft('')
      }
      if (activeFieldContextId && fieldStorageMode === 'account_workspace') {
        await refreshFieldHistory(activeFieldContextId)
      }
      setRuntimeAccess('available')
      clearPhase6ChatDraft(activeFieldConversationKey)
      setMessage('')
      setStatus('Answer ready')
      navigateToPage('analyze')
    } catch (err) {
      if (isRuntimeTransportFailure(err)) {
        setRuntimeAccess('unavailable')
      }
      setStatus('Needs attention')
      setError(String((err as Error).message || err))
    } finally {
      setIsAnalyzing(false)
      setPendingQuestion('')
    }
  }

  const onBoundaryFile = async (file: File | null) => {
    if (!file) {
      return
    }
    regionalLookupRequestRef.current += 1
    setError('')
    setStatus('Parsing boundary upload')
    const formData = new FormData()
    formData.append('file', file)
    try {
      const parsed = await apiUpload<BoundaryUploadResponse>('/api/geo/boundary-upload?intersect=true', formData)
      const geometry = fieldGeometryFromGeoJsonLike(parsed.geometry)
      if (!geometry) {
        throw new Error('Uploaded boundary did not contain a map-ready point or polygon.')
      }
      setFieldGeometry(geometry)
      setGeometryDraft(null)
      setGeometryEditSnapshot(null)
      setFieldToolsOpen(false)
      setUploadContext(parsed)
      setSelectedUploadFeatureId(parsed.selected_feature_id || parsed.feature_summaries?.[0]?.id || '')
      setMapMode(geometry.kind === 'polygon' ? 'edit' : 'inspect')
      setBoundaryStatus(`${parsed.status_message} ${parsed.boundary}`)
      if (geometry.kind === 'polygon' && parsed.acres > 0) {
        setField((current) => ({ ...current, acres: String(Math.round(parsed.acres)) }))
      }
      if (parsed.regional_intersections || parsed.geo_errors) {
        const priors = geoPriorsFromBoundaryUpload(parsed)
        setGeoPriors(priors)
        const candidate = primaryRegionalCandidate(priors)
        setBoundaryStatus(
          candidate
            ? `Matched ${candidate.system} ${candidate.code} from uploaded boundary.`
            : parsed.geo_errors?.length
              ? 'Boundary parsed, but one or more official regional layers could not be reached.'
              : 'Boundary parsed; no official regional polygon intersected it.',
        )
        setStatus('Regional context ready')
      } else {
        await lookupRegionalContext(geometry)
      }
    } catch (err) {
      setStatus('Needs attention')
      setBoundaryStatus(`Could not parse ${file.name}.`)
      setError(String((err as Error).message || err))
    }
  }

  const beginGeometryEdit = (nextMode: 'point' | 'boundary' | 'edit') => {
    if (!geometryEditSnapshot) {
      setGeometryEditSnapshot({
        geoPriors,
        uploadContext,
        selectedUploadFeatureId,
      })
    }
    setGeometryDraft(nextMode === 'point' || nextMode === 'boundary' ? emptyGeometry : geometryDraft || fieldGeometry)
    regionalLookupRequestRef.current += 1
    setIsMapContextChecking(false)
    setUploadContext(null)
    setSelectedUploadFeatureId('')
    setGeoPriors(null)
    setFieldToolsOpen(false)
    setMapMode(nextMode)
    setBoundaryStatus(
      nextMode === 'point'
        ? 'Choose a point, then save edits or cancel.'
        : nextMode === 'boundary'
          ? 'Draw the field boundary, then save edits or cancel.'
          : 'Drag boundary vertices, then save edits or cancel.',
    )
  }

  const onMapGeometryChange = (geometry: FieldGeometry) => {
    if (!isEditingGeometry) {
      return
    }
    regionalLookupRequestRef.current += 1
    setGeometryDraft(geometry)
    setBoundaryStatus('Draft geometry updated. Save edits or cancel.')
  }

  const onMapStatusChange = (message: string) => {
    setBoundaryStatus(isEditingGeometry ? `${message} Save edits or cancel.` : message)
  }

  const resetGeometryDraft = () => {
    if (!isEditingGeometry) {
      return
    }
    regionalLookupRequestRef.current += 1
    setGeometryDraft(emptyGeometry)
    setMapMode('boundary')
    setBoundaryStatus('Draw a new field boundary, then save edits or cancel.')
  }

  const cancelGeometryEdits = () => {
    if (!geometryEditSnapshot) {
      return
    }
    regionalLookupRequestRef.current += 1
    setGeometryDraft(null)
    setGeoPriors(geometryEditSnapshot.geoPriors)
    setUploadContext(geometryEditSnapshot.uploadContext)
    setSelectedUploadFeatureId(geometryEditSnapshot.selectedUploadFeatureId)
    setGeometryEditSnapshot(null)
    setFieldToolsOpen(false)
    setMapMode('inspect')
    setBoundaryStatus('Field edits cancelled. The prior geometry and map context were restored.')
  }

  const saveGeometryEdits = async () => {
    if (!geometryDraft) {
      return
    }
    const issue = fieldGeometryIssue(geometryDraft)
    if (issue) {
      setBoundaryStatus(issue)
      return
    }
    const geometry = geometryDraft
    setFieldGeometry(geometry)
    if (geometry.kind === 'polygon') {
      setField((current) => ({ ...current, acres: String(Math.round(geometry.acres)) }))
    }
    setGeometryDraft(null)
    setGeometryEditSnapshot(null)
    setFieldToolsOpen(false)
    setMapMode('inspect')
    setBoundaryStatus('Field edits saved. Refreshing regional context…')
    await lookupRegionalContext(geometry)
  }

  const refreshFieldHistory = async (fieldContextId: string) => {
    if (!fieldContextId || fieldStorageMode !== 'account_workspace') {
      setFieldHistory(null)
      setFieldHistoryStatus('Device-only field: timeline is not saved.')
      return
    }
    setFieldHistoryStatus('Loading field timeline.')
    try {
      const history = await apiGet<DemoFieldHistoryResponse>(
        `/api/demo/fields/${encodeURIComponent(fieldContextId)}/history`,
      )
      setFieldHistory(history)
      setFieldHistoryStatus(
        `${history.event_count || 0} field record${history.event_count === 1 ? '' : 's'} · `
        + `${history.turn_count || 0} answer${history.turn_count === 1 ? '' : 's'}.`,
      )
    } catch (err) {
      setFieldHistory(null)
      setFieldHistoryStatus(`Field history unavailable: ${String((err as Error).message || err)}`)
    }
  }

  const openFieldAnswerEvidence = async (historyTurn: FieldHistoryTurn) => {
    setError('')
    setFieldHistoryStatus('Opening the saved answer trace.')
    try {
      let matchingSession = sessions.find((session) => session.session_id === historyTurn.session_id)
      if (!matchingSession) {
        matchingSession = await apiGet<SessionRecord>(
          `/api/sessions/${encodeURIComponent(historyTurn.session_id)}`,
        )
        setSessions((current) => [matchingSession as SessionRecord, ...current])
      }
      setSessionId(matchingSession.session_id)
      setTurns(matchingSession.turns || [])
      setEvidenceTurnId(historyTurn.turn_id)
      setFieldHistoryStatus('Saved answer trace opened in Evidence.')
      navigateToPage('evidence')
    } catch (err) {
      setFieldHistoryStatus(`Answer trace unavailable: ${String((err as Error).message || err)}`)
    }
  }

  const reviewFieldAnswer = async (historyTurn: FieldHistoryTurn, accepted: boolean) => {
    setFieldAnswerReviewPending(historyTurn.turn_id)
    try {
      await apiPost('/api/feedback', {
        session_id: historyTurn.session_id,
        turn_id: historyTurn.turn_id,
        accepted,
        answer_status: accepted ? 'reviewed' : 'rejected',
      })
      await refreshFieldHistory(activeFieldContextId)
    } catch (err) {
      setFieldHistoryStatus(`Could not save answer review: ${String((err as Error).message || err)}`)
    } finally {
      setFieldAnswerReviewPending('')
    }
  }

  const appendFieldEvent = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!activeFieldContextId || fieldStorageMode !== 'account_workspace' || !fieldEventSummary.trim()) {
      return
    }
    if (fieldEventType === 'correction' && !fieldCorrectionTarget) {
      setFieldHistoryStatus('Choose the record this correction refers to.')
      return
    }
    setFieldHistoryStatus('Saving an append-only field record.')
    try {
      const payload: Record<string, unknown> = {
        event_type: fieldEventType,
        payload: {
          summary: fieldEventSummary.trim(),
          ...(fieldEventType === 'correction' ? { correction_kind: 'user_entered' } : {}),
        },
        provenance: {
          capture_method: 'user_entered',
          surface: 'fields_timeline',
        },
      }
      if (fieldEventOccurredAt) {
        payload.occurred_at = new Date(fieldEventOccurredAt).toISOString()
      }
      if (fieldEventType === 'correction') {
        payload.corrects_event_id = fieldCorrectionTarget
      }
      await apiPost<DemoFieldEventResponse>(
        `/api/demo/fields/${encodeURIComponent(activeFieldContextId)}/events`,
        payload,
      )
      setFieldEventSummary('')
      setFieldEventOccurredAt('')
      setFieldCorrectionTarget('')
      setFieldEventType('observation')
      await refreshFieldHistory(activeFieldContextId)
    } catch (err) {
      setFieldHistoryStatus(`Could not save field record: ${String((err as Error).message || err)}`)
    }
  }

  const storeCurrentField = async (saveAsNew = false) => {
    if (!geometryReady) {
      setBoundaryStatus(geometryIssue || 'Draw a boundary or add a point before storing the field.')
      return
    }
    const candidate = primaryGeoCandidate
      ? `${primaryGeoCandidate.system} ${primaryGeoCandidate.code}`
      : activeScenario.mlra
    const selectedName = fieldName.trim() || `${field.crop || 'Field'} · ${field.region || field.jurisdiction || 'new field'}`
    const name = saveAsNew && activeFieldContextId ? `${selectedName} copy` : selectedName
    const sourceBoundary = geoPriors?.disclaimer || 'Map and public-source context are decision-support priors, not field truth.'
    const payload = {
      name,
      field: {
        crop: field.crop,
        region: field.region,
        jurisdiction: field.jurisdiction,
        acres: activeArea || field.acres,
        concern: field.concern,
        notes: field.notes,
      },
      geometry: fieldGeometry,
      regionalContext: candidate,
      geoPriors,
      sourceBoundary,
    }
    const stored: StoredField = {
      ...field,
      id: `${Date.now()}`,
      name,
      geometry: fieldGeometry,
      acres: activeArea || field.acres,
      regionalContext: candidate,
      createdAt: new Date().toISOString(),
      storageMode: fieldStorageMode,
      geoPriors,
      sourceBoundary,
    }
    const updatingCurrentField = Boolean(activeFieldContextId) && !saveAsNew
    try {
      if (fieldStorageMode === 'account_workspace') {
        const saved = updatingCurrentField
          ? await apiPatch<DemoFieldSavedResponse>(`/api/demo/fields/${encodeURIComponent(activeFieldContextId)}`, payload)
          : await apiPost<DemoFieldSavedResponse>('/api/demo/fields', payload)
        setStoredFields((current) => [saved.field, ...current.filter((item) => item.id !== saved.field.id)])
        const savedFieldId = saved.field.field_context_id || saved.field.id
        setActiveFieldContextId(savedFieldId)
        persistActiveStoredFieldId(savedFieldId)
        setActiveFieldRecordUpdatedAt(saved.field.updatedAt || '')
        setFieldName(saved.field.name)
        if (!updatingCurrentField) {
          setActiveFieldConversationKey(storedFieldConversationKey(savedFieldId))
          setSessionId('')
          setTurns([])
          setEvidenceTurnId('')
          setMessage('')
          setScratchpadNotes('')
        }
        setBoundaryStatus(
          updatingCurrentField
            ? `Saved changes to ${saved.field.name} in the local workspace.`
            : `Stored ${saved.field.name} in the local workspace.`,
        )
        setFieldStorageStatus(saved.storage.workspace_name ? `Saved to ${saved.storage.workspace_name}.` : 'Saved to the local account workspace.')
        void refreshFieldHistory(savedFieldId)
        return
      }
    } catch (err) {
      setError(String((err as Error).message || err))
      setFieldStorageMode('device')
      setFieldStorageStatus('Device-only fallback; workspace save failed.')
    }
    const localStored = updatingCurrentField
      ? {
          ...stored,
          id: activeFieldContextId,
          createdAt: storedFields.find((item) => (item.field_context_id || item.id) === activeFieldContextId)?.createdAt || stored.createdAt,
          updatedAt: stored.createdAt,
          storageMode: 'device' as const,
        }
      : { ...stored, storageMode: 'device' as const }
    setStoredFields((current) => [localStored, ...current.filter((item) => item.id !== localStored.id)].slice(0, 12))
    setActiveFieldContextId(localStored.id)
    persistActiveStoredFieldId(localStored.id)
    setFieldName(localStored.name)
    if (!updatingCurrentField) {
      setActiveFieldConversationKey(storedFieldConversationKey(localStored.id))
      setSessionId('')
      setTurns([])
      setEvidenceTurnId('')
      setMessage('')
      setScratchpadNotes('')
    }
    setActiveFieldRecordUpdatedAt(localStored.updatedAt || localStored.createdAt)
    setFieldHistory(null)
    setFieldHistoryStatus('Device-only field: timeline is not saved.')
    setBoundaryStatus(updatingCurrentField ? `Saved changes to ${localStored.name} on this device.` : `Stored ${localStored.name} on this device.`)
  }

  const loadStoredField = (stored: StoredField) => {
    regionalLookupRequestRef.current += 1
    const storedFieldId = stored.field_context_id || stored.id
    const fieldConversationKey = storedFieldConversationKey(storedFieldId)
    const matchingSession = sessionForField(sessions, fieldConversationKey, storedFieldId)
    setActiveFieldContextId(storedFieldId)
    persistActiveStoredFieldId(storedFieldId)
    setActiveFieldConversationKey(fieldConversationKey)
    setActiveFieldRecordUpdatedAt(stored.updatedAt || stored.createdAt || '')
    setSessionId(matchingSession?.session_id || '')
    setTurns(matchingSession?.turns || [])
    setEvidenceTurnId('')
    void refreshFieldHistory(storedFieldId)
    setField({
      crop: stored.crop,
      region: stored.region,
      jurisdiction: stored.jurisdiction,
      acres: stored.acres,
      concern: stored.concern,
      notes: stored.notes,
    })
    setFieldName(stored.name)
    setFieldGeometry(stored.geometry)
    setGeometryDraft(null)
    setGeometryEditSnapshot(null)
    setFieldToolsOpen(false)
    setUploadContext(null)
    setSelectedUploadFeatureId('')
    setGeoPriors(stored.geoPriors || null)
    setBoundaryStatus(`Loaded ${stored.name}.`)
    setMapMode(stored.geometry.kind === 'polygon' ? 'edit' : 'inspect')
  }

  useEffect(() => {
    if (!fieldsHydrated || storedFieldRestoreAttempted) {
      return
    }
    setStoredFieldRestoreAttempted(true)
    const persistedFieldId = loadActiveStoredFieldId()
    if (!persistedFieldId) {
      return
    }
    const stored = storedFields.find(
      (candidate) => (candidate.field_context_id || candidate.id) === persistedFieldId,
    )
    if (!stored) {
      persistActiveStoredFieldId('')
      return
    }
    loadStoredField(stored)
  }, [fieldsHydrated, storedFieldRestoreAttempted, storedFields])

  const deleteStoredField = async (id: string) => {
    const target = storedFields.find((stored) => stored.id === id)
    if (target && (target.storageMode === 'account_workspace' || fieldStorageMode === 'account_workspace')) {
      try {
        await apiDelete<DemoFieldSavedResponse>(`/api/demo/fields/${encodeURIComponent(target.field_context_id || target.id)}`)
      } catch (err) {
        setError(String((err as Error).message || err))
        return
      }
    }
    setStoredFields((current) => current.filter((stored) => stored.id !== id))
    if (target && (target.field_context_id || target.id) === activeFieldContextId) {
      startNewField()
      setFieldHistoryStatus('The selected field was deleted. Save or load another field to build durable history.')
      setBoundaryStatus('The selected field was deleted. Start a new field or load another saved field.')
    }
  }

  const renameStoredField = async (stored: StoredField) => {
    const name = renameValue.trim()
    if (!name || name === stored.name) {
      setRenamingFieldId('')
      return
    }
    const storedFieldId = stored.field_context_id || stored.id
    try {
      let renamed: StoredField
      if (stored.storageMode === 'account_workspace' || fieldStorageMode === 'account_workspace') {
        const saved = await apiPatch<DemoFieldSavedResponse>(
          `/api/demo/fields/${encodeURIComponent(storedFieldId)}`,
          {
            name,
            field: {
              crop: stored.crop,
              region: stored.region,
              jurisdiction: stored.jurisdiction,
              acres: stored.acres,
              concern: stored.concern,
              notes: stored.notes,
            },
            geometry: stored.geometry,
            regionalContext: stored.regionalContext,
            geoPriors: stored.geoPriors,
            sourceBoundary: stored.sourceBoundary,
          },
        )
        renamed = saved.field
        setFieldStorageMode('account_workspace')
        setFieldStorageStatus(saved.storage.workspace_name ? `Saved to ${saved.storage.workspace_name}.` : 'Saved to the local account workspace.')
      } else {
        renamed = { ...stored, name, updatedAt: new Date().toISOString(), storageMode: 'device' }
      }
      setStoredFields((current) => current.map((item) => item.id === stored.id ? renamed : item))
      if (storedFieldId === activeFieldContextId) {
        setFieldName(renamed.name)
        setActiveFieldRecordUpdatedAt(renamed.updatedAt || activeFieldRecordUpdatedAt)
      }
      setBoundaryStatus(`Renamed field to ${renamed.name}.`)
      setRenamingFieldId('')
    } catch (err) {
      setError(String((err as Error).message || err))
    }
  }

  const lookupRegionalContext = async (geometryOverride?: FieldGeometry, fieldOverride?: FieldProfile) => {
    const requestId = regionalLookupRequestRef.current + 1
    regionalLookupRequestRef.current = requestId
    const geometryForLookup = geometryOverride || fieldGeometry
    const fieldForLookup = fieldOverride || field
    const lookupIssue = fieldGeometryIssue(geometryForLookup)
    if (lookupIssue) {
      setBoundaryStatus(lookupIssue)
      return
    }
    const geometryText =
      geometryForLookup.kind === 'point'
        ? `point ${geometryForLookup.point.lat} ${geometryForLookup.point.lon}`
        : geometryForLookup.kind === 'polygon'
          ? `boundary ${geometryForLookup.points.length} vertices ${Math.round(geometryForLookup.acres)} acres`
          : ''
    const locationText = [
      fieldForLookup.jurisdiction,
      fieldForLookup.region,
      fieldForLookup.crop,
      fieldForLookup.concern,
      geometryText,
    ]
      .filter(Boolean)
      .join(' ')
    const geometry = fieldGeometryToGeoJson(geometryForLookup)
    setIsMapContextChecking(true)
    setBoundaryStatus('Checking official regional layers…')
    setStatus('Intersecting regional layers')
    try {
      const priors = await apiPost<GeoPriors>('/api/geo/priors', { location_text: locationText, geometry })
      if (requestId !== regionalLookupRequestRef.current) {
        return
      }
      setGeoPriors(priors)
      const candidate = primaryRegionalCandidate(priors)
      setBoundaryStatus(
        candidate
          ? `Regional context refreshed: ${candidate.system} ${candidate.code} matched at ${Math.round(candidate.confidence * 100)}% confidence.`
          : 'Regional context refreshed: no regional candidate matched.',
      )
      setStatus('Regional context ready')
    } catch (err) {
      if (requestId !== regionalLookupRequestRef.current) {
        return
      }
      setStatus('Needs attention')
      setBoundaryStatus('Could not refresh regional context. Review the error and retry.')
      setError(String((err as Error).message || err))
    } finally {
      if (requestId === regionalLookupRequestRef.current) {
        setIsMapContextChecking(false)
      }
    }
  }

  useEffect(() => {
    const scenario = sampleProfiles.find((sample) => sample.id === scenarioId) || sampleProfiles[0]
    const geometry = geometryForScenario(scenario)
    if (geometry.kind !== 'none') {
      void lookupRegionalContext(geometry, scenario)
    }
  }, [scenarioId])

  useEffect(() => {
    const requestId = agroclimateRequestRef.current + 1
    agroclimateRequestRef.current = requestId
    if (!geoPriors || !geometryReady || !isCanadianJurisdiction(field.jurisdiction)) {
      setAgroclimate({ status: 'idle' })
      return
    }

    setAgroclimate({ status: 'loading' })
    ;(async () => {
      try {
        const payload = await apiPost<AgroclimateResponse>('/api/tools/aafc-nasdi-agroclimate', {
          geometry: fieldGeometryToGeoJson(fieldGeometry),
          crop: field.crop,
          province: field.jurisdiction,
          sample_points: fieldGeometry.kind === 'polygon' ? 3 : 1,
        })
        if (requestId !== agroclimateRequestRef.current) return
        if (payload.status === 'available' || payload.status === 'partial_available') {
          setAgroclimate({ status: payload.status, payload })
        } else {
          setAgroclimate({
            status: 'unavailable',
            payload,
            message: 'Current AAFC regional conditions are unavailable for this geometry.',
          })
        }
      } catch (err) {
        if (requestId !== agroclimateRequestRef.current) return
        setAgroclimate({
          status: 'error',
          message: String((err as Error).message || err),
        })
      }
    })()
  }, [agroclimateRefresh, field.crop, field.jurisdiction, fieldGeometry, geoPriors, geometryReady])

  useEffect(() => {
    const requestId = nasaPowerRequestRef.current + 1
    nasaPowerRequestRef.current = requestId
    if (!committedWeatherPoint) {
      setNasaPower({ status: 'idle' })
      return
    }

    const { start, end } = powerWindowDates()
    setNasaPower({ status: 'loading' })
    ;(async () => {
      try {
        const payload = await apiPost<NasaPowerResponse>('/api/tools/weather-power', {
          lat: committedWeatherPoint.lat,
          lon: committedWeatherPoint.lon,
          start,
          end,
          parameters: ['T2M', 'PRECTOTCORR', 'WS2M'],
        })
        if (requestId !== nasaPowerRequestRef.current) return
        setNasaPower({ status: 'available', payload })
      } catch (err) {
        if (requestId !== nasaPowerRequestRef.current) return
        setNasaPower({
          status: 'error',
          message: String((err as Error).message || err),
        })
      }
    })()
  }, [committedWeatherPoint?.lat, committedWeatherPoint?.lon, nasaPowerRefresh])

  const selectUploadedFeature = async (featureId: string) => {
    const feature = uploadFeatureById(uploadContext, featureId)
    if (!feature) {
      setBoundaryStatus('Uploaded feature was not found in the parsed file.')
      return
    }
    const geometry = fieldGeometryFromGeoJsonLike(feature)
    if (!geometry) {
      setBoundaryStatus('Selected upload feature is not a map-ready point or polygon.')
      return
    }
    setSelectedUploadFeatureId(featureId)
    setFieldGeometry(geometry)
    setGeometryDraft(null)
    setGeometryEditSnapshot(null)
    setFieldToolsOpen(false)
    setMapMode(geometry.kind === 'polygon' ? 'edit' : 'inspect')
    if (geometry.kind === 'polygon') {
      setField((current) => ({ ...current, acres: String(Math.round(geometry.acres)) }))
    }
    const summary = uploadContext?.feature_summaries?.find((candidate) => candidate.id === featureId)
    setBoundaryStatus(`Selected ${summary?.label || 'uploaded feature'}; intersecting official regional layers.`)
    setGeoPriors(null)
    await lookupRegionalContext(geometry)
  }

  const reviewerExportMarkdown = (generatedAt: string): string | null => {
    if (!evidenceTurn) {
      return null
    }
    return buildReviewerExportMarkdown({
      generatedAt,
      field: {
        crop: field.crop,
        region: field.region,
        jurisdiction: field.jurisdiction,
        acres: activeArea,
        concern: field.concern,
        notes: field.notes,
        geometrySummary: geometrySummary(fieldGeometry, activeScenario.geometry),
        regionalContext: officialIntersections.map(
          (item) => `${item.system} ${item.code}: ${item.name} (${Math.round(item.coverage_estimate * 100)}% field coverage estimate)`,
        ),
        sourceBoundary: geoPriors?.disclaimer || 'Map and public-source context are decision-support priors, not field truth.',
      },
      turn: evidenceTurn,
      docs: evidenceDocs,
      graphHits: evidenceTurn.trace?.graph_hits || [],
      publicTools: evidenceLiveToolCards,
      mapEvidenceCards: evidenceMapCards,
    })
  }

  const copyReviewerReport = async () => {
    const generatedAt = new Date().toISOString()
    const report = reviewerExportMarkdown(generatedAt)
    if (!report) {
      setStatus('Ask a question before exporting a review report.')
      return
    }
    try {
      await copyTextToClipboard(report)
      setStatus('Reviewer report copied to clipboard')
    } catch (err) {
      setStatus('Copy failed')
      setError(String((err as Error).message || err))
    }
  }

  const downloadReviewerReport = () => {
    const generatedAt = new Date().toISOString()
    const report = reviewerExportMarkdown(generatedAt)
    if (!report || !evidenceTurn) {
      setStatus('Ask a question before exporting a review report.')
      return
    }
    const blob = new Blob([report], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = reviewerExportFilename(evidenceTurn, generatedAt)
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
    setStatus('Reviewer report downloaded')
  }

  const visibleStoredFields = useMemo(() => {
    const query = fieldLibraryQuery.trim().toLocaleLowerCase()
    const filtered = query
      ? storedFields.filter((stored) => [stored.name, stored.crop, stored.region, stored.jurisdiction]
        .some((value) => value.toLocaleLowerCase().includes(query)))
      : storedFields
    return [...filtered].sort((left, right) => {
      if (fieldLibrarySort === 'updated') {
        return String(right.updatedAt || right.createdAt).localeCompare(String(left.updatedAt || left.createdAt))
      }
      return String(left[fieldLibrarySort] || '').localeCompare(String(right[fieldLibrarySort] || ''))
    })
  }, [fieldLibraryQuery, fieldLibrarySort, storedFields])

  return (
    <main className="demo-app">
      <DemoHeader page={page} setPage={navigateToPage} answerCapability={answerCapability} />
      {error ? <div className="demo-alert" role="alert">{error}</div> : null}

      {page === 'analyze' || page === 'fields' ? (
        <div className={`map-workspace ${page === 'fields' ? 'fields-workspace' : 'analyze-workspace'}`}>
          {page === 'analyze' ? <nav className="mobile-workspace-tabs" aria-label="Mobile map workflow">
            <a href="#map-panel">Map</a>
            <a href="#chat-panel">Ask</a>
          </nav> : null}
          {page === 'fields' ? (
          <aside id="field-context-panel" className="field-panel" aria-label="Field context">
            <section className="field-library" aria-labelledby="field-library-heading">
              <div className="field-library-heading">
                <div>
                  <span className="panel-kicker">Workspace</span>
                  <h2 id="field-library-heading">My fields</h2>
                </div>
                <span className={`field-storage-badge ${fieldStorageMode}`}>
                  {fieldStorageMode === 'account_workspace' ? 'Workspace' : 'This device'}
                </span>
              </div>
              <p className="field-library-status">{fieldStorageStatus}</p>
              <div className="field-library-controls">
                <input
                  aria-label="Search saved fields"
                  placeholder="Search name, crop, or region"
                  value={fieldLibraryQuery}
                  onChange={(event) => setFieldLibraryQuery(event.target.value)}
                />
                <select
                  aria-label="Sort saved fields"
                  value={fieldLibrarySort}
                  onChange={(event) => setFieldLibrarySort(event.target.value as typeof fieldLibrarySort)}
                >
                  <option value="updated">Last updated</option>
                  <option value="name">Name</option>
                  <option value="crop">Crop</option>
                  <option value="region">Region</option>
                </select>
              </div>
              <button type="button" className="map-primary-action new-field-action" onClick={startNewField}>
                <MapPin size={16} /> New field
              </button>
              {visibleStoredFields.length === 0 ? (
                <p className="field-library-empty">{storedFields.length ? 'No fields match this search.' : 'Create a field to store its boundary, context, chats, and timeline.'}</p>
              ) : (
                <div className="field-library-list" aria-label="Saved field library">
                  {visibleStoredFields.map((stored) => {
                    const storedFieldId = stored.field_context_id || stored.id
                    const active = storedFieldId === activeFieldContextId
                    const renaming = renamingFieldId === storedFieldId
                    return (
                      <article key={stored.id} className={active ? 'active' : ''}>
                        {renaming ? (
                          <div className="field-rename-editor">
                            <input
                              aria-label={`Rename ${stored.name}`}
                              value={renameValue}
                              onChange={(event) => setRenameValue(event.target.value)}
                              onKeyDown={(event) => {
                                if (event.key === 'Enter') void renameStoredField(stored)
                                if (event.key === 'Escape') setRenamingFieldId('')
                              }}
                            />
                            <button type="button" onClick={() => void renameStoredField(stored)}>Save</button>
                            <button type="button" onClick={() => setRenamingFieldId('')}>Cancel</button>
                          </div>
                        ) : (
                          <button type="button" className="field-library-load" onClick={() => loadStoredField(stored)}>
                            <strong>{stored.name}</strong>
                            <span>{[stored.crop, stored.region || stored.jurisdiction].filter(Boolean).join(' · ') || stored.regionalContext}</span>
                            <small>{active ? 'Active field' : `Updated ${new Date(stored.updatedAt || stored.createdAt).toLocaleDateString()}`}</small>
                          </button>
                        )}
                        <div className="field-library-actions">
                          {!renaming ? (
                            <button
                              type="button"
                              className="icon-button"
                              title={`Rename ${stored.name}`}
                              aria-label={`Rename ${stored.name}`}
                              onClick={() => {
                                setRenamingFieldId(storedFieldId)
                                setRenameValue(stored.name)
                              }}
                            >
                              <Pencil size={15} />
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="icon-button danger"
                            title={`Delete ${stored.name}`}
                            aria-label={`Delete ${stored.name}`}
                            onClick={() => void deleteStoredField(stored.id)}
                          >
                            <Eraser size={15} />
                          </button>
                        </div>
                      </article>
                    )
                  })}
                </div>
              )}
            </section>
            <div className="workspace-panel-heading">
              <div>
                <span className="panel-kicker">Field</span>
                <h2>{activeFieldContextId ? 'Edit field' : 'New field setup'}</h2>
              </div>
              <span className={`context-state ${geometryReady ? 'ready' : 'pending'}`}>
                {activeFieldContextId ? 'Saved field' : fieldGeometry.kind === 'none' ? 'Add a boundary' : geometryReady ? 'Ready to save' : 'Fix geometry'}
              </span>
            </div>
            <p className="field-workflow-hint">1. Add details  2. Draw or upload the boundary  3. Save edits to refresh map context  4. Save the field</p>
            {!geometryReady ? (
              <button type="button" className="field-copy-action field-draw-action" onClick={() => navigateToPage('analyze')}>
                <MapPin size={15} /> Draw boundary on map
              </button>
            ) : null}
            <details className="workspace-disclosure sample-disclosure">
              <summary><Sparkles size={16} /> Load a demonstration field</summary>
              <label>
                Example
                <select value={scenarioId} onChange={(event) => applyScenario(event.target.value)}>
                  {sampleProfiles.map((sample) => (
                    <option key={sample.id} value={sample.id}>
                      {sample.name}
                    </option>
                  ))}
                </select>
              </label>
            </details>
            <label>
              Field name
              <input
                aria-label="Field name"
                placeholder="e.g. North quarter"
                value={fieldName}
                onChange={(event) => setFieldName(event.target.value)}
              />
            </label>
            <div className="field-grid">
              <label>
                Crop
                <input value={field.crop} onChange={(event) => setField({ ...field, crop: event.target.value })} />
              </label>
              <label>
                Acres
                <input value={field.acres} onChange={(event) => setField({ ...field, acres: event.target.value })} />
              </label>
              <label>
                Region
                <input value={field.region} onChange={(event) => setField({ ...field, region: event.target.value })} />
              </label>
              <label>
                Jurisdiction
                <input value={field.jurisdiction} onChange={(event) => setField({ ...field, jurisdiction: event.target.value })} />
              </label>
            </div>
            <label>
              Main concern
              <textarea value={field.concern} onChange={(event) => setField({ ...field, concern: event.target.value })} />
            </label>
            <label>
              Boundary upload
              <span className="boundary-upload-control">
                <Upload size={17} />
                <input
                  className="file-input"
                  type="file"
                  accept=".geojson,.json,.zip,.shp,.gpkg"
                  onChange={(event) => onBoundaryFile(event.target.files?.[0] || null)}
                />
              </span>
            </label>
            {uploadContext ? (
              <div className="upload-context">
                <div className="upload-heading">
                  <strong>{uploadContext.filename}</strong>
                  <span>{uploadContext.feature_count} feature{uploadContext.feature_count === 1 ? '' : 's'}</span>
                </div>
                {uploadContext.warnings?.length ? (
                  <ul className="upload-warnings">
                    {uploadContext.warnings.slice(0, 3).map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                ) : null}
                {uploadContext.feature_summaries?.length ? (
                  <div className="upload-feature-list">
                    {uploadContext.feature_summaries.slice(0, 8).map((feature) => (
                      <button
                        type="button"
                        key={feature.id}
                        data-testid={`upload-feature-${feature.id}`}
                        aria-pressed={feature.id === selectedUploadFeatureId}
                        className={feature.id === selectedUploadFeatureId ? 'active' : ''}
                        onClick={() => void selectUploadedFeature(feature.id)}
                      >
                        <span>{feature.label}</span>
                        <strong>
                          {feature.geometry_type}
                          {feature.acres > 0 ? ` · ${Math.round(feature.acres).toLocaleString()} ac` : ''}
                        </strong>
                      </button>
                    ))}
                  </div>
                ) : null}
                {selectedUploadFeature ? (
                  <div className="selected-upload-feature">
                    <span>Selected feature</span>
                    <strong>{selectedUploadFeature.label}</strong>
                  </div>
                ) : null}
              </div>
            ) : null}
            <div className="field-readiness-summary" aria-label="Field readiness">
              <div>
                <span>Field details</span>
                <strong>{contextCompleteness}%</strong>
              </div>
              <div>
                <span>Regional matches</span>
                <strong>{officialIntersections.length || 'Pending'}</strong>
              </div>
              <div>
                <span>Storage</span>
                <strong>{fieldStorageMode === 'account_workspace' ? 'Workspace' : 'Device'}</strong>
              </div>
            </div>
            <div className="field-save-actions">
              <button
                type="button"
                className="map-primary-action field-save-action"
                aria-label="Save field"
                onClick={() => void storeCurrentField()}
                disabled={!geometryReady}
              >
                <Save size={16} /> {activeFieldContextId ? 'Save changes' : 'Save new field'}
              </button>
              {activeFieldContextId ? (
                <button
                  type="button"
                  className="field-copy-action"
                  onClick={() => void storeCurrentField(true)}
                  disabled={!geometryReady}
                >
                  Save as new field
                </button>
              ) : null}
            </div>
            {geoPriors ? (
              <details className="workspace-disclosure regional-context-disclosure">
                <summary>
                  <Layers3 size={16} />
                  Regional context
                  <span>{officialIntersections.length} match{officialIntersections.length === 1 ? '' : 'es'} · {geoPriors.uncertainty}</span>
                </summary>
                <div className="regional-context-card">
                  <p className="regional-context-summary">{regionalContextSummary(geoPriors)}</p>
                  {officialIntersections.length ? (
                    <div className="regional-match-list">
                      {officialIntersections.slice(0, 4).map((item) => (
                        <article key={`${item.layer_id}-${item.code}`}>
                          <strong>{item.name}</strong>
                          <span>{item.system} {item.code}</span>
                          {regionalSourceScale(item) ? <small>{regionalSourceScale(item)}</small> : null}
                          <small>{regionalMatchDetail(item)}</small>
                          <small>{item.match_reason}</small>
                          {item.erosion_summary ? <small>{item.erosion_summary}</small> : null}
                          {item.source === 'bundled_official_geospatial_layer' ? (
                            <small className="regional-authority-note">{regionalAuthorityNote(item)}</small>
                          ) : null}
                          {item.source_url ? (
                            <a href={item.source_url} target="_blank" rel="noreferrer">
                              Official layer source
                            </a>
                          ) : null}
                        </article>
                      ))}
                    </div>
                  ) : (
                    <p>{(geoPriors.missing_context || []).join(', ') || 'No official regional match yet.'}</p>
                  )}
                  {officialLayerStatus.length ? (
                    <div className="layer-status-list">
                      {officialLayerStatus.map((layer) => (
                        <span key={layer.layer_id} className={`layer-status ${layer.status}`}>
                          {layer.system}: {layer.status === 'matched' ? `${layer.match_count} match${layer.match_count === 1 ? '' : 'es'}` : layer.message}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {geoErrorCount ? (
                    <p className="geo-error-note">
                      {geoErrorCount} regional layer request failed. Edit and save the field geometry to retry; answers should treat regional context as incomplete.
                    </p>
                  ) : null}
                </div>
              </details>
            ) : null}
            {geoPriors && isCanadianJurisdiction(field.jurisdiction) ? (
              <details className="workspace-disclosure agroclimate-disclosure">
                <summary>
                  <RefreshCw size={16} />
                  Current regional conditions
                  <span>{agroclimate.status === 'partial_available' ? 'partial' : agroclimate.status}</span>
                </summary>
                <section className="agroclimate-context" aria-label="Current regional conditions">
                  <div className="agroclimate-heading">
                    <div>
                      <strong>AAFC regional conditions</strong>
                      <span>NASDI</span>
                    </div>
                    <button
                      type="button"
                      className="icon-button agroclimate-refresh"
                      title="Refresh AAFC regional conditions"
                      aria-label="Refresh AAFC regional conditions"
                      disabled={agroclimate.status === 'loading'}
                      onClick={() => setAgroclimateRefresh((value) => value + 1)}
                    >
                      <RefreshCw size={15} className={agroclimate.status === 'loading' ? 'spin' : ''} />
                    </button>
                  </div>
                  {agroclimate.status === 'loading' ? (
                    <p className="agroclimate-status">Loading the latest official grid observations...</p>
                  ) : agroclimate.status === 'available' || agroclimate.status === 'partial_available' ? (
                    <>
                      <div className="agroclimate-metrics">
                        {AGROCLIMATE_METRICS.map((metric) => {
                          const indicator = agroclimate.payload?.indicator_summary?.[metric.key]
                          return (
                            <div key={metric.key} data-testid={`agroclimate-${metric.key}`}>
                              <span>{metric.label}</span>
                              <strong>{formatAgroclimateValue(metric.key, indicator)}</strong>
                            </div>
                          )
                        })}
                      </div>
                      <p className="agroclimate-freshness">
                        Observed through <strong>{agroclimate.payload?.observation_end || 'latest available date'}</strong>
                        {typeof agroclimate.payload?.data_age_days === 'number'
                          ? ` · ${agroclimate.payload.data_age_days} day${agroclimate.payload.data_age_days === 1 ? '' : 's'} old`
                          : ''}
                        {agroclimate.status === 'partial_available' ? ' · some indicators unavailable' : ''}
                      </p>
                    </>
                  ) : (
                    <p className="agroclimate-status">
                      {agroclimate.message || 'Current official conditions are not available for this field.'}
                    </p>
                  )}
                  <div className="agroclimate-source">
                    <span>Regional grid context, not a field measurement or prescription.</span>
                    {agroclimate.payload?.source ? (
                      <a href={agroclimate.payload.source} target="_blank" rel="noreferrer">
                        Official source
                      </a>
                    ) : null}
                  </div>
                </section>
              </details>
            ) : null}
            <Suspense fallback={null}>
              <OfflineTerrainContextPanel
                id={activeFieldContextId}
                m={fieldStorageMode}
                k={fieldGeometry.kind}
                area={field.jurisdiction}
              />
            </Suspense>
            <details className="workspace-disclosure local-field-notes">
              <summary><Pencil size={16} /> Offline field notes</summary>
              <p>Stored only on this device. These notes are not synced, sent to the model, or included in reports until you copy them into a field record or question.</p>
              {offlineStorageRepair ? (
                <div role="alert" data-testid="offline-storage-recovery-notice">
                  <strong>Unreadable local data was preserved</strong>
                  <p>
                    The application did not load the affected {offlineStorageRepair.store.replace(/_/g, ' ')} data.
                    Download the private recovery file before clearing browser storage or reinstalling the app.
                  </p>
                  <button
                    type="button"
                    onClick={() => downloadPhase6OfflineStorageRecovery(offlineStorageRepair)}
                  >
                    Download recovery file
                  </button>
                  <button type="button" onClick={() => setOfflineStorageRepair(null)}>
                    Dismiss
                  </button>
                </div>
              ) : null}
              <textarea
                aria-label="Offline field notes"
                value={scratchpadNotes}
                onChange={(event) => setScratchpadNotes(event.target.value)}
                maxLength={12000}
                placeholder="Record observations while the local runtime is unavailable."
              />
              <div>
                <small data-testid="local-field-notes-status">Local only · {scratchpadNotes.length.toLocaleString()} characters</small>
                <button
                  type="button"
                  onClick={() => {
                    clearPhase6Scratchpad(activeFieldConversationKey)
                    setScratchpadNotes('')
                  }}
                  disabled={!scratchpadNotes}
                >
                  Clear local notes
                </button>
              </div>
            </details>
            <section className="field-history-panel" aria-label="Field timeline">
              <div className="field-history-heading">
                <div>
                  <strong>Field timeline</strong>
                  <span>Records and linked answers</span>
                </div>
                {activeFieldContextId ? (
                  <button
                    type="button"
                    className="icon-button"
                    aria-label="Refresh field timeline"
                    onClick={() => void refreshFieldHistory(activeFieldContextId)}
                  >
                    <RefreshCw size={15} />
                  </button>
                ) : null}
              </div>
              <p className="field-history-status">{fieldHistoryStatus}</p>
              <form className="field-event-form" aria-label="Add field record" onSubmit={(event) => void appendFieldEvent(event)}>
                <label>
                  Record type
                  <select
                    value={fieldEventType}
                    onChange={(event) => {
                      const nextType = event.target.value as FieldEvent['event_type']
                      setFieldEventType(nextType)
                      if (nextType !== 'correction') setFieldCorrectionTarget('')
                    }}
                    disabled={!activeFieldContextId || fieldStorageMode !== 'account_workspace'}
                  >
                    <option value="observation">Observation</option>
                    <option value="sample">Sample</option>
                    <option value="operation">Operation</option>
                    <option value="decision">Decision</option>
                    <option value="outcome">Outcome</option>
                    <option value="note">Note</option>
                    <option value="correction">Correction</option>
                  </select>
                </label>
                <label>
                  When it happened
                  <input
                    type="datetime-local"
                    value={fieldEventOccurredAt}
                    onChange={(event) => setFieldEventOccurredAt(event.target.value)}
                    disabled={!activeFieldContextId || fieldStorageMode !== 'account_workspace'}
                  />
                </label>
                {fieldEventType === 'correction' ? (
                  <label className="field-event-correction-target">
                    Record to correct
                    <select
                      value={fieldCorrectionTarget}
                      onChange={(event) => setFieldCorrectionTarget(event.target.value)}
                      required
                    >
                      <option value="">Choose a prior record</option>
                      {(fieldHistory?.events || []).slice().reverse().map((fieldEvent) => (
                        <option key={fieldEvent.id} value={fieldEvent.id}>
                          {fieldEvent.event_type}: {String(fieldEvent.payload.summary || fieldEvent.id).slice(0, 80)}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
                <label className="field-event-summary">
                  What happened
                  <textarea
                    value={fieldEventSummary}
                    onChange={(event) => setFieldEventSummary(event.target.value)}
                    placeholder={
                      fieldEventType === 'correction'
                        ? 'Explain the error and correction.'
                        : 'Describe the record.'
                    }
                    maxLength={2000}
                    required
                    disabled={!activeFieldContextId || fieldStorageMode !== 'account_workspace'}
                  />
                </label>
                <button
                  type="submit"
                  className="map-primary-action"
                  disabled={
                    !activeFieldContextId
                    || fieldStorageMode !== 'account_workspace'
                    || !fieldEventSummary.trim()
                    || (fieldEventType === 'correction' && !fieldCorrectionTarget)
                  }
                >
                  <Save size={15} /> Add record
                </button>
              </form>
              {fieldHistory?.events?.length ? (
                <div className="field-history-list field-event-list" aria-label="Field records">
                  {fieldHistory.events.slice().reverse().slice(0, 12).map((fieldEvent) => (
                    <article key={fieldEvent.id}>
                      <div>
                        <span className="lineage-state verified">{fieldEvent.event_type}</span>
                        <time>{new Date(fieldEvent.occurred_at || fieldEvent.recorded_at).toLocaleString()}</time>
                      </div>
                      <p>{String(fieldEvent.payload.summary || 'Structured field record')}</p>
                      <small>
                        Immutable record · {fieldEvent.integrity_sha256.slice(0, 12)}
                        {fieldEvent.corrects_event_id ? ` · corrects ${fieldEvent.corrects_event_id.slice(0, 8)}` : ''}
                      </small>
                    </article>
                  ))}
                </div>
              ) : null}
              {fieldHistory?.turns?.length ? <strong className="field-answer-history-title">Answer history</strong> : null}
              {fieldHistory?.turns?.length ? (
                <div className="field-history-list">
                  {fieldHistory.turns.slice().reverse().slice(0, 12).map((turn) => {
                    const answerAccepted = turn.feedback?.accepted
                    const answerStatus = turn.feedback?.answer_status || turn.answer_status || 'draft'
                    const reviewLabel = answerAccepted === true
                      ? 'Marked useful'
                      : answerAccepted === false || answerStatus === 'rejected'
                        ? 'Do not rely'
                        : answerStatus === 'approved'
                          ? 'Approved answer'
                          : answerStatus === 'reviewed'
                            ? 'Reviewed answer'
                            : 'Unreviewed answer'
                    const reviewClass = answerAccepted === true || answerStatus === 'approved'
                      ? 'accepted'
                      : answerAccepted === false || answerStatus === 'rejected'
                        ? 'rejected'
                        : 'unreviewed'
                    const [coverageLabel, coverageVerified] = knowledgeCoverageView(turn.knowledge_coverage)
                    return (
                      <article key={turn.turn_id}>
                        <div>
                          <span className={`lineage-state ${turn.binding_status === 'verified_snapshot' ? 'verified' : 'legacy'}`}>
                            {turn.binding_status === 'verified_snapshot' ? 'Field snapshot verified' : 'Legacy binding'}
                          </span>
                          <span className={`answer-review-state ${reviewClass}`}>{reviewLabel}</span>
                          <span className={`lineage-state ${coverageVerified ? 'verified' : 'legacy'}`}>
                            {coverageLabel}
                          </span>
                          <time>{turn.created_at ? new Date(turn.created_at).toLocaleString() : 'Time unavailable'}</time>
                        </div>
                        <strong>{turn.question}</strong>
                        <p>{turn.answer}</p>
                        <small>
                          {turn.retrieved_document_count} documents · {turn.tool_invocation_count} tools
                          {turn.field_lineage?.field_snapshot_sha256
                            ? ` · snapshot ${turn.field_lineage.field_snapshot_sha256.slice(0, 12)}`
                            : ''}
                          {turn.answer_integrity_receipt?.receipt_sha256
                            ? ` · answer receipt ${turn.answer_integrity_receipt.receipt_sha256.slice(0, 12)}`
                            : ' · legacy answer receipt'}
                        </small>
                        <div className="field-history-actions">
                          <button type="button" onClick={() => void openFieldAnswerEvidence(turn)}>
                            Review evidence
                          </button>
                          <button
                            type="button"
                            disabled={fieldAnswerReviewPending === turn.turn_id}
                            onClick={() => void reviewFieldAnswer(turn, true)}
                          >
                            Mark useful
                          </button>
                          <button
                            type="button"
                            className="answer-reject-action"
                            disabled={fieldAnswerReviewPending === turn.turn_id}
                            onClick={() => void reviewFieldAnswer(turn, false)}
                          >
                            Do not rely
                          </button>
                        </div>
                      </article>
                    )
                  })}
                </div>
              ) : null}
              {activeFieldContextId && fieldStorageMode === 'account_workspace' ? (
                <Suspense fallback={null}>
                  <FieldSyncPanel
                    fieldContextId={activeFieldContextId}
                    onImported={() => refreshFieldHistory(activeFieldContextId)}
                  />
                </Suspense>
              ) : null}
              {fieldHistory?.boundary ? (
                <small className="field-history-boundary">
                  Field records are append-only: corrections keep the original. Saved answers stay linked to the exact
                  field snapshot and evidence available at the time. Open Review evidence for technical hashes and
                  source lineage.
                </small>
              ) : null}
            </section>
          </aside>
          ) : null}

          {page === 'analyze' ? (
          <>
          <section id="map-panel" className="map-stage" aria-label="Map">
            <div className="map-toolbar">
              <div>
                <strong>{field.crop || 'Field'} analysis</strong>
                <span>{field.region || 'Unknown region'} · {field.jurisdiction || 'Unknown jurisdiction'}</span>
              </div>
              <div className="map-actions" aria-label="Map tools">
                {isEditingGeometry ? (
                  <div className="map-draft-actions" role="group" aria-label="Field edit actions">
                    <button type="button" className="map-secondary-action" onClick={cancelGeometryEdits}>
                      <X size={16} /> Cancel
                    </button>
                    <button
                      type="button"
                      className="map-primary-action"
                      onClick={() => void saveGeometryEdits()}
                      disabled={fieldGeometryIssue(mapGeometry) !== null || isMapContextChecking}
                    >
                      <Save size={16} /> {isMapContextChecking ? 'Saving…' : 'Save edits'}
                    </button>
                  </div>
                ) : null}
                {committedWeatherPoint ? (
                  <details className="map-weather-pill">
                    <summary aria-label="NASA POWER field weather" title="Recent NASA POWER gridded weather">
                      <CloudSun size={16} />
                      <span>NASA POWER</span>
                      {nasaPower.status === 'loading' ? (
                        <small>loading</small>
                      ) : nasaPower.status === 'available' ? (
                        <small data-testid="map-nasa-power-summary">
                          {powerMetricValue(nasaPower.payload?.parameter_summary?.PRECTOTCORR, 'sum')} mm · {powerMetricValue(nasaPower.payload?.parameter_summary?.WS2M, 'mean')} m/s
                        </small>
                      ) : (
                        <small>unavailable</small>
                      )}
                    </summary>
                    <section className="map-weather-popover" aria-label="NASA POWER recent field weather">
                      <div className="map-weather-heading">
                        <div>
                          <strong>Recent gridded weather</strong>
                          <span>3-day point summary</span>
                        </div>
                        <button
                          type="button"
                          className="icon-button map-weather-refresh"
                          title="Refresh NASA POWER field weather"
                          aria-label="Refresh NASA POWER field weather"
                          disabled={nasaPower.status === 'loading'}
                          onClick={() => setNasaPowerRefresh((value) => value + 1)}
                        >
                          <RefreshCw size={15} className={nasaPower.status === 'loading' ? 'spin' : ''} />
                        </button>
                      </div>
                      {nasaPower.status === 'available' ? (
                        <>
                          <div className="map-weather-metrics">
                            <div><span>Mean air temp.</span><strong>{powerMetricValue(nasaPower.payload?.parameter_summary?.T2M, 'mean')} °C</strong></div>
                            <div><span>Precipitation</span><strong>{powerMetricValue(nasaPower.payload?.parameter_summary?.PRECTOTCORR, 'sum')} mm</strong></div>
                            <div><span>Mean wind</span><strong>{powerMetricValue(nasaPower.payload?.parameter_summary?.WS2M, 'mean')} m/s</strong></div>
                          </div>
                          <p>UTC {nasaPower.payload?.start}–{nasaPower.payload?.end}{nasaPower.payload?.cache_hit ? ' · local cache' : ''}</p>
                          <p>{nasaPower.payload?.boundary || 'NASA POWER is gridded weather context, not an on-field sensor.'}</p>
                          {nasaPower.payload?.source ? (
                            <a href={nasaPower.payload.source} target="_blank" rel="noreferrer">Official NASA POWER response</a>
                          ) : null}
                        </>
                      ) : (
                        <p>{nasaPower.status === 'loading' ? 'Fetching recent gridded weather…' : nasaPower.message || 'NASA POWER weather is unavailable for this field.'}</p>
                      )}
                    </section>
                  </details>
                ) : null}
                <details
                  className="map-advanced-tools map-field-tools"
                  open={fieldToolsOpen}
                  onToggle={(event) => setFieldToolsOpen((event.target as HTMLDetailsElement).open)}
                >
                  <summary title="Set or edit the field" aria-label="Set field">
                    <MapPin size={16} /> <span>Set field</span>
                  </summary>
                  <div className="map-advanced-menu">
                    <button
                      type="button"
                      className={mapMode === 'point' ? 'active' : ''}
                      aria-pressed={mapMode === 'point'}
                      aria-label="Select point"
                      onClick={() => beginGeometryEdit('point')}
                    >
                      <MapPin size={15} /> Select one location
                    </button>
                    <button
                      type="button"
                      className={mapMode === 'boundary' ? 'active' : ''}
                      aria-pressed={mapMode === 'boundary'}
                      aria-label="Draw boundary"
                      onClick={() => beginGeometryEdit('boundary')}
                    >
                      <Pencil size={15} /> Draw field boundary
                    </button>
                    <button
                      type="button"
                      className={mapMode === 'inspect' ? 'active' : ''}
                      aria-pressed={mapMode === 'inspect'}
                      onClick={() => setMapMode('inspect')}
                    >
                      <MousePointer2 size={15} /> Pause editing
                    </button>
                    <button
                      type="button"
                      className={mapMode === 'edit' ? 'active' : ''}
                      aria-pressed={mapMode === 'edit'}
                      aria-label="Edit boundary vertices"
                      onClick={() => beginGeometryEdit('edit')}
                      disabled={mapGeometry.kind !== 'polygon'}
                    >
                      <Pencil size={15} /> Edit boundary
                    </button>
                    <button
                      type="button"
                      aria-label="Start over"
                      onClick={resetGeometryDraft}
                      disabled={!isEditingGeometry}
                    >
                      <Eraser size={15} /> Start over
                    </button>
                    <button type="button" onClick={() => navigateToPage('fields')}>
                      <Database size={15} /> Field details & history
                    </button>
                  </div>
                </details>
              </div>
            </div>
            <Suspense
              fallback={
                <div className="leaflet-map-shell">
                  <div className="leaflet-map map-loading" aria-label="Loading field map">
                    Loading map
                  </div>
                </div>
              }
            >
              <LeafletFieldMap
                mode={mapMode}
                scenarioId={scenarioId}
                fieldLabel={`${field.crop || 'Field'} ${field.region || field.jurisdiction}`}
                geometry={mapGeometry}
                regionalCandidates={geoPriors?.candidate_regions || []}
                regionalFeatureCollection={geoPriors?.regional_feature_collection || null}
                onGeometryChange={onMapGeometryChange}
                onStatusChange={onMapStatusChange}
              />
            </Suspense>
            <div className="map-context-bar" aria-label="Current field context">
              <div>
                <span aria-live="polite">{boundaryStatus}</span>
                <strong>
                  {geometrySummary(mapGeometry, activeScenario.geometry)}
                  {isEditingGeometry
                    ? ' · draft changes'
                    : primaryGeoCandidate
                    ? ` · ${primaryGeoCandidate.system} ${primaryGeoCandidate.code}`
                    : geometryReady
                      ? ' · layers not checked'
                      : ''}
                </strong>
              </div>
              <button type="button" onClick={() => navigateToPage('fields')}>
                Open field details
              </button>
            </div>
          </section>

          <aside id="chat-panel" className="chat-panel" aria-label="Agronomy chat">
            <div className="chat-heading">
              <div>
                <span className="panel-kicker">Agent</span>
                <h2>Ask about this field</h2>
              </div>
              <span className={`agent-state ${isAnalyzing ? 'working' : 'ready'}`}>
                {isAnalyzing ? status : 'Ready'}
              </span>
              <button
                type="button"
                className="chat-reset-button"
                onClick={resetChat}
                disabled={isAnalyzing}
                data-testid="reset-chat"
                title="Start a fresh chat for this field"
              >
                <Eraser size={15} /> Reset chat
              </button>
            </div>
            <div className={`network-answer-state ${answerCapability.state}`}>
              <strong title={answerCapability.detail}>
                {answerCapability.state === 'runtime_online'
                  ? 'Answer engine ready · live checks on demand'
                  : answerCapability.state === 'runtime_offline'
                    ? 'Answer engine ready · offline sources only'
                    : answerCapability.state === 'notes_only'
                      ? 'Notes only · local runtime unavailable'
                      : 'Checking answer engine'}
              </strong>
              {answerCapability.state === 'notes_only' ? <span>{answerCapability.detail}</span> : null}
              {!selectedModelReady ? <span>{selectedModelProfile?.local_detail || 'Selected local model is not installed.'}</span> : null}
              {runtimeAccess === 'unavailable' ? (
                <button
                  type="button"
                  onClick={() => {
                    setRuntimeAccess('checking')
                    void apiGet('/api/health')
                      .then(() => setRuntimeAccess('available'))
                      .catch(() => setRuntimeAccess('unavailable'))
                  }}
                >
                  Retry local runtime
                </button>
              ) : null}
            </div>

            <div ref={conversationThreadRef} className="conversation-thread" aria-live="polite">
              {turns.length === 0 && !isAnalyzing ? (
                <div className="conversation-empty">
                  <MessageSquareText size={24} />
                  <strong>Start with a field question</strong>
                  <p>Field context is included.</p>
                </div>
              ) : null}
              {turns.slice(-4).map((turn) => (
                <Fragment key={turn.turn_id}>
                  <article className="chat-message user-message">
                    <span>You</span>
                    <p>{turn.user_message}</p>
                  </article>
                  <article
                    ref={turn.turn_id === latestTurn?.turn_id ? latestAssistantMessageRef : undefined}
                    className="chat-message assistant-message"
                  >
                    <span>Open Agronomy Agent</span>
                    <FormattedAnswer text={turn.answer} />
                  </article>
                </Fragment>
              ))}
              {isAnalyzing ? (
                <>
                  <article className="chat-message user-message pending-message">
                    <span>You</span>
                    <p>{pendingQuestion}</p>
                  </article>
                  <article className="chat-message assistant-message working-message">
                    <span>Open Agronomy Agent</span>
                    <StreamProgressPanel steps={streamProgress} draft={streamDraft} />
                    {streamDraft ? <FormattedAnswer text={streamDraft} /> : null}
                  </article>
                </>
              ) : null}
            </div>

            {!isAnalyzing && latestTurn ? (
              <section className="answer-receipt" aria-label="Latest answer receipt">
                <div className="answer-receipt-summary">
                  <div>
                    <strong>Evidence and trace available</strong>
                    <span>Sources, checks, context lineage, and technical receipts</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setEvidenceTurnId(latestTurn.turn_id)
                    navigateToPage('evidence')
                  }}
                >
                  Review evidence
                </button>
              </section>
            ) : null}

            <form className="chat-composer" onSubmit={sendQuestion}>
              <textarea
                aria-label="Ask about this field"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                disabled={isAnalyzing}
              />
              <div className="composer-actions">
                <details className="model-settings-disclosure">
                  <summary title="Model settings" aria-label="Model settings"><Settings2 size={17} /></summary>
                  {modelProfiles.length > 0 ? (
                    <label className="model-profile-select">
                      Model
                      <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
                        {modelProfiles.map((profile) => (
                          <option key={profile.id} value={profile.id} disabled={profile.local_ready === false}>
                            {profile.label} · {profile.role} · {profile.max_tokens} tok{profile.local_ready === false ? ' · setup required' : ''}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : <span>Local model profile</span>}
                </details>
                <button type="submit" disabled={isAnalyzing || !message.trim() || !answerCapability.canGenerateAnswer || !selectedModelReady}>
                  <Send size={17} /> {isAnalyzing ? 'Working' : 'Ask'}
                </button>
              </div>
            </form>
          </aside>
          </>
          ) : null}
        </div>
      ) : null}

      {page === 'evidence' ? (
        <EvidencePage
          latestTurn={evidenceTurn}
          docs={evidenceDocs}
          liveToolCards={evidenceLiveToolCards}
          mapEvidenceCards={evidenceMapCards}
          retrievedDocCount={evidenceRetrievedDocCount}
          sourceCheckSummary={evidenceSourceSummary}
          traceToolGroups={evidenceTraceGroups}
          adapterReadiness={adapterReadiness}
          onCopyReport={() => void copyReviewerReport()}
          onDownloadReport={downloadReviewerReport}
        />
      ) : null}

      {page === 'benchmarks' ? (
        <Suspense fallback={<section className="route-loading-panel">Loading benchmark readiness...</section>}>
          <BenchmarksRoute />
        </Suspense>
      ) : null}

      {page === 'sources' ? (
        <SourcesPage
          privateKnowledge={privateKnowledge}
          onPrivateKnowledgeAdded={(inspection) =>
            setPrivateKnowledge((current) => [
              inspection,
              ...current.filter((item) => item.raw_sha256 !== inspection.raw_sha256),
            ])
          }
          onClearPrivateKnowledge={() => setPrivateKnowledge([])}
        />
      ) : null}

      {page === 'privacy' || page === 'about' ? (
        <Suspense fallback={null}>
          <OpenAgronomyInfoPages page={page} />
        </Suspense>
      ) : null}
    </main>
  )
}

function DemoHeader({
  page,
  setPage,
  answerCapability,
}: {
  page: Page
  setPage: (page: Page) => void
  answerCapability: ReturnType<typeof fieldAnswerCapability>
}) {
  const morePagesRef = useRef<HTMLDetailsElement | null>(null)
  const primaryItems: Array<[Page, string]> = [
    ['analyze', 'Workspace'],
    ['fields', 'Fields'],
    ['evidence', 'Evidence'],
  ]
  const secondaryItems: Array<[Page, string]> = [
    ['sources', 'Sources'],
    ['benchmarks', 'Benchmarks'],
    ['privacy', 'Privacy'],
    ['about', 'About'],
  ]
  const choosePage = (nextPage: Page) => {
    setPage(nextPage)
    if (morePagesRef.current) morePagesRef.current.open = false
  }
  return (
    <header className="demo-header">
      <div className="brand-block">
        <span>Open Agronomy Agent</span>
        <strong>Field-aware agronomy answers with visible evidence</strong>
        <small className={`network-mode-badge ${answerCapability.state}`}>
          {answerCapability.badge}
        </small>
      </div>
      <nav className="demo-nav" aria-label="Primary">
        {primaryItems.map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={page === id ? 'active' : ''}
            aria-current={page === id ? 'page' : undefined}
            onClick={() => choosePage(id)}
          >
            {label}
          </button>
        ))}
        <details
          ref={morePagesRef}
          className={`demo-nav-more ${secondaryItems.some(([id]) => page === id) ? 'active' : ''}`}
        >
          <summary aria-label="More pages">More</summary>
          <div className="demo-nav-more-menu">
            {secondaryItems.map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={page === id ? 'active' : ''}
                aria-current={page === id ? 'page' : undefined}
                onClick={() => choosePage(id)}
              >
                {label}
              </button>
            ))}
          </div>
        </details>
      </nav>
    </header>
  )
}

function TraceToolGroupPanel({ groups }: { groups: TraceToolGroup[] }) {
  return (
    <section className="trace-group-panel">
      <div className="trace-group-header">
        <span>Evidence checks</span>
        <strong>{groups.filter((group) => group.count > 0).length || 0} active</strong>
      </div>
      <div className="trace-group-list">
        {groups.map((group) => (
          <article key={group.id} className={`trace-group-card status-${group.statusTone}`}>
            <div>
              <strong>{group.label}</strong>
              <span>{group.summary}</span>
            </div>
            {group.items.length ? (
              <ul>
                {group.items.slice(0, 3).map((item) => (
                  <li key={`${group.id}-${item.name}`}>
                    <span className={`trace-evidence-label ${item.statusTone}`}>{item.label}</span>
                    <p>{item.detail}</p>
                  </li>
                ))}
              </ul>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  )
}

function EvidenceMetrics({ route, docCount, graphCount, mapCount, checkCount }: {
  route: TurnRoute | null | undefined
  docCount: number
  graphCount: number
  mapCount: number
  checkCount: number
}) {
  const items: Array<[string, string, string?]> = [
    ['Decision', decisionLabel(route?.question_type), route?.question_type],
    ['Sensitivity', sensitivityLabel(route?.risk_level), route?.risk_level],
    ['Docs', `${docCount} used`],
    ['Graph', `${graphCount} linked`],
    ['Checks', `${checkCount} active`],
    ['Map', `${mapCount} matched`],
  ]
  return (
    <div className="trace-strip">
      {items.map(([label, value, title]) => <div key={label}><span>{label}</span><strong title={title}>{value}</strong></div>)}
    </div>
  )
}

function EvidenceDisclosure({
  heading,
  children,
}: {
  heading: [string, string]
  children: ReactNode
}) {
  return (
    <details className="evidence-disclosure">
      <summary>
        <span>{heading[0]}</span>
        {heading[1]}
      </summary>
      {children}
    </details>
  )
}

function CompiledFieldContextPanel({ receipt }: { receipt: Record<string, unknown> | undefined }) {
  const mapContext = Array.isArray(receipt?.map_context) ? receipt.map_context : []
  const liveContext = Array.isArray(receipt?.live_context) ? receipt.live_context : []
  const field = receipt?.field && typeof receipt.field === 'object' ? receipt.field as Record<string, unknown> : {}
  const fieldLabel = ['crop', 'region', 'jurisdiction', 'concern']
    .map((key) => typeof field[key] === 'string' ? field[key] : '')
    .filter(Boolean)
    .join(' · ')
  return (
    <section className="compiled-field-context" data-testid="compiled-field-context">
      <p>{fieldLabel || 'No bounded field details were supplied for this turn.'}</p>
      {mapContext.map((value, index) => {
        const item = value && typeof value === 'object' ? value as Record<string, unknown> : {}
        const components = Array.isArray(item.dominant_components) ? item.dominant_components : []
        return (
          <article key={`map-${index}`}>
            <strong>{String(item.label || item.layer_id || 'Mapped context')}</strong>
            <p>{String(item.soil_summary || item.map_unit || 'Mapped prior used.')}</p>
            {components.length ? <small>{components.length} dominant mapped component{components.length === 1 ? '' : 's'} retained</small> : null}
          </article>
        )
      })}
      {liveContext.map((value, index) => {
        const item = value && typeof value === 'object' ? value as Record<string, unknown> : {}
        const facts = Array.isArray(item.facts) ? item.facts.map(String).filter(Boolean) : []
        return (
          <article key={`live-${index}`}>
            <strong>{String(item.label || item.adapter || 'Public source')}</strong>
            <p>{facts.join(' · ') || 'No usable value returned.'}</p>
          </article>
        )
      })}
      {typeof receipt?.boundary === 'string' ? <small>{receipt.boundary}</small> : null}
    </section>
  )
}

function knowledgeCoverageView(coverage?: AnswerTimeKnowledgeCoverage): [string, boolean] {
  const statuses = coverage?.boundaries.map((boundary) => boundary.status) || []
  if (!statuses.length) {
    return [
      coverage?.capture_status === 'captured_no_boundary'
        ? 'No Canadian boundary'
        : 'Coverage unavailable',
      false,
    ]
  }
  if (statuses.every((status) => status === 'province_specific_guidance_retrieved')) {
    return ['Applied guidance used', true]
  }
  if (statuses.every((status) => (
    status === 'province_specific_guidance_retrieved'
    || status === 'province_specific_context_retrieved'
  ))) {
    return ['Context only', false]
  }
  return ['Local guidance missing', false]
}

function EvidencePage({
  latestTurn,
  docs,
  retrievedDocCount,
  liveToolCards,
  mapEvidenceCards,
  sourceCheckSummary,
  traceToolGroups,
  adapterReadiness,
  onCopyReport,
  onDownloadReport,
}: {
  latestTurn: Turn | null
  docs: RetrievedDoc[]
  retrievedDocCount: number
  liveToolCards: ToolInvocation[]
  mapEvidenceCards: StructuredEvidenceCard[]
  sourceCheckSummary: SourceCheckSummary
  traceToolGroups: TraceToolGroup[]
  adapterReadiness: PublicAdapterReadiness
  onCopyReport: () => void
  onDownloadReport: () => void
}) {
  const graphHits = latestTurn?.trace?.graph_hits || []
  const route = latestTurn?.trace?.route
  const activeEvidenceGroups = traceToolGroups.filter((group) => group.count > 0).length
  const knowledgeCoverage = latestTurn?.knowledge_coverage as AnswerTimeKnowledgeCoverage | undefined
  const [knowledgeCoverageLabel, knowledgeCoverageVerified] = knowledgeCoverageView(knowledgeCoverage)
  const knowledgeSourceIds = knowledgeCoverage?.boundaries.flatMap((boundary) => [
    ...(boundary.retrieved_source_ids || []),
    ...(boundary.retrieved_context_source_ids || []),
  ]) || []
  const knowledgeJurisdictions = knowledgeCoverage?.boundaries.map((boundary) => boundary.jurisdiction) || []
  const answerModelIdentity = latestTurn?.system_state?.model_identity
  const answerModelLineage = answerModelLineageView(answerModelIdentity)
  const answerReceipt = latestTurn?.answer_integrity_receipt
  const fieldLineage = latestTurn?.trace?.metadata?.field_lineage as
    | {
      field_context_id?: string
      field_snapshot_sha256?: string
      field_record_updated_at?: string
      field_history?: { chain_valid?: boolean; event_count?: number; head_sha256?: string }
      field_answer_history?: {
        total_bound_turn_count?: number
        included_turn_count?: number
        prior_model_answers_are_evidence?: boolean
      }
    }
    | undefined
  const compiledFieldContext = latestTurn?.trace?.metadata?.field_context_compiler as Record<string, unknown> | undefined
  return (
    <div className="evidence-page">
      <section className="evidence-summary">
        <div className="panel-kicker">Evidence audit</div>
        <h2>What the agent used</h2>
        <p>{latestTurn ? latestTurn.user_message : 'Run a question from the map page to populate this view.'}</p>
        {latestTurn ? (
          <section className="answer-lineage-receipt" aria-label="Answer lineage">
            <div>
              <strong>Saved answer trace</strong>
              <span className={`lineage-state ${fieldLineage?.field_snapshot_sha256 ? 'verified' : 'legacy'}`}>
                {fieldLineage?.field_snapshot_sha256 ? 'Field context hash verified' : 'Session trace'}
              </span>
            </div>
            <dl>
              <div>
                <dt>Turn</dt>
                <dd><code>{latestTurn.turn_id}</code></dd>
              </div>
              <div>
                <dt>{answerModelLineage.label}</dt>
                <dd>
                  <span>{answerModelLineage.status}</span>
                  {answerModelIdentity?.configured_model_id
                    ? ` · ${answerModelIdentity.configured_model_id.split('/').pop()}`
                    : ''}
                  {answerModelIdentity?.configured_model_revision
                    ? ` · ${answerModelIdentity.configured_model_revision.slice(0, 12)}`
                    : ''}
                </dd>
              </div>
              {fieldLineage?.field_snapshot_sha256 ? (
                <div>
                  <dt>Field snapshot SHA-256</dt>
                  <dd><code>{fieldLineage.field_snapshot_sha256}</code></dd>
                </div>
              ) : null}
              {fieldLineage?.field_history ? (
                <div>
                  <dt>Field record chain</dt>
                  <dd>
                    {fieldLineage.field_history.chain_valid ? 'Valid' : 'Needs review'}
                    {' · '}{fieldLineage.field_history.event_count || 0} records
                    {fieldLineage.field_history.head_sha256
                      ? ` · head ${fieldLineage.field_history.head_sha256.slice(0, 12)}`
                      : ''}
                  </dd>
                </div>
              ) : null}
              {fieldLineage?.field_answer_history ? (
                <div>
                  <dt>Prior answer context</dt>
                  <dd>
                    {fieldLineage.field_answer_history.included_turn_count || 0} reviewed/history turn
                    {fieldLineage.field_answer_history.included_turn_count === 1 ? '' : 's'} consulted
                    {' · '}prior model outputs are not evidence
                  </dd>
                </div>
              ) : null}
              <div>
                <dt>Evidence at answer time</dt>
                <dd>
                  <span className={`lineage-state ${knowledgeCoverageVerified ? 'verified' : 'legacy'}`}>
                    {knowledgeCoverageLabel}
                  </span>
                </dd>
              </div>
              {answerReceipt ? (
                <div>
                  <dt>Answer integrity receipt</dt>
                  <dd>
                    <span className={`lineage-state ${answerReceipt.status === 'verified' ? 'verified' : 'legacy'}`}>
                      {answerReceipt.status === 'verified' ? 'Content hashes verified' : readableLabel(answerReceipt.status)}
                    </span>
                    {answerReceipt.receipt_sha256 ? ` · ${answerReceipt.receipt_sha256}` : ''}
                  </dd>
                </div>
              ) : null}
              <div>
                <dt>Source IDs</dt>
                <dd>
                  {knowledgeJurisdictions.length ? `${knowledgeJurisdictions.join(', ')} · ` : ''}
                  {knowledgeSourceIds.length ? `Retrieved: ${knowledgeSourceIds.join(', ')}` : 'No local source retrieved'}
                </dd>
              </div>
            </dl>
            <div className="answer-actions" aria-label="Review export actions">
              <button type="button" onClick={onCopyReport}>Copy review report</button>
              <button type="button" onClick={onDownloadReport}>Download .md</button>
            </div>
          </section>
        ) : null}
        <EvidenceMetrics
          route={route}
          docCount={retrievedDocCount}
          graphCount={graphHits.length}
          mapCount={mapEvidenceCards.length}
          checkCount={activeEvidenceGroups}
        />
        <EvidenceDisclosure
          heading={['Evidence checks', `${activeEvidenceGroups} active · ${sourceCheckSummary.label}`]}
        >
          <TraceToolGroupPanel groups={traceToolGroups} />
          <SourceCheckSummaryPanel summary={sourceCheckSummary} />
        </EvidenceDisclosure>
      </section>
      <EvidenceDisclosure
        heading={['Map context', summarizeStructuredEvidenceCards(mapEvidenceCards)]}
      >
        <StructuredEvidenceList
          cards={mapEvidenceCards}
          emptyLabel="None."
        />
      </EvidenceDisclosure>
      <EvidenceDisclosure
        heading={['Compiled field context', compiledFieldContext?.status === 'available' ? 'source-bound values retained' : 'limited context']}
      >
        <CompiledFieldContextPanel receipt={compiledFieldContext} />
      </EvidenceDisclosure>
      <EvidenceDisclosure
        heading={['Live public sources', summarizePublicToolCards(liveToolCards)]}
      >
        <PublicAdapterReadinessPanel readiness={adapterReadiness} compact />
        <PublicToolSourceList
          tools={liveToolCards}
          emptyLabel="None."
        />
      </EvidenceDisclosure>
      <EvidenceDisclosure
        heading={['Retrieved evidence', `${retrievedDocCount} used`]}
      >
        {retrievedDocCount > docs.length ? <p>Showing {docs.length} of {retrievedDocCount} documents.</p> : null}
        {docs.length === 0 ? <p>None yet.</p> : docs.map((doc) => (
          <article key={doc.doc_id} className="source-row">
            <span>{doc.rank}</span>
            <div>
              <strong>{doc.title}</strong>
              <p>{doc.snippet || 'No snippet available.'}</p>
              <small>
                {doc.source_type} · score {doc.score.toFixed(2)} · {doc.source || 'seed corpus'}
                {doc.retrieval_policy ? ` · ${readableLabel(doc.retrieval_policy)}` : ''}
                {doc.distribution_scope === 'local_only_not_for_redistribution' ? ' · local private' : ''}
                {doc.chunk_sha256 ? ` · #${doc.chunk_sha256.slice(0, 12)}` : ''}
              </small>
            </div>
          </article>
        ))}
      </EvidenceDisclosure>
      <EvidenceDisclosure
        heading={['Graph context', `${graphHits.length} linked`]}
      >
        {graphHits.length === 0 ? <p>None yet.</p> : graphHits.slice(0, 6).map((hit) => (
          <article key={hit.node_id}>
            <strong>{hit.name}</strong>
            <p>{hit.evidence}</p>
          </article>
        ))}
      </EvidenceDisclosure>
    </div>
  )
}


function SourcesPage({
  privateKnowledge,
  onPrivateKnowledgeAdded,
  onClearPrivateKnowledge,
}: {
  privateKnowledge: PrivateKnowledgeInspection[]
  onPrivateKnowledgeAdded: (inspection: PrivateKnowledgeInspection) => void
  onClearPrivateKnowledge: () => void
}) {
  const [adapterReadiness, setAdapterReadiness] = useState<PublicAdapterReadiness>(fallbackAdapterReadiness)
  const [sourceStatus, setSourceStatus] = useState('Loading adapters')
  const [packageStatus, setPackageStatus] = useState('Update status unavailable')

  useEffect(() => {
    let active = true
    apiGet<PublicAdapterReadiness>('/api/tools/public-adapter-readiness')
      .then((readiness) => {
        if (active) {
          setAdapterReadiness(readiness)
          setSourceStatus(
            `${readiness.summary.ready_count || 0}/${readiness.summary.adapter_count || 0} source adapters ready`,
          )
        }
      })
      .catch(() => {
        if (active) {
          setAdapterReadiness(fallbackAdapterReadiness)
          setSourceStatus('Source adapter evidence unavailable')
        }
      })
    apiGet<ConfigResponse>('/api/configs')
      .then(({ knowledge_update: update }) => {
        if (active) {
          setPackageStatus(
            update?.status === 'active'
              ? `${update.package_id || 'Knowledge'} · seq ${update.release_sequence || '?'} · until ${update.expires_at?.slice(0, 10) || '?'}${
                  update.signature_mode === 'threshold_policy'
                    ? ` · ${update.trust_policy_threshold || '?'}-signature policy`
                    : update.signature_mode === 'legacy_single_key'
                      ? ' · legacy single-key'
                      : ''
                }`
              : `Update ${readableLabel(update?.status || 'not configured')}`,
          )
        }
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="sources-page">
      <Suspense fallback={<section className="canadian-knowledge-coverage">Loading governed Canadian knowledge...</section>}>
        <CanadianKnowledgeCoveragePanel />
      </Suspense>
      <Suspense fallback={<section className="source-private-knowledge">Loading private references...</section>}>
        <PrivateKnowledgePanel
          privateKnowledge={privateKnowledge}
          onAdded={onPrivateKnowledgeAdded}
          onClear={onClearPrivateKnowledge}
        />
      </Suspense>
      <section className="source-coverage-hero">
        <div className="panel-kicker">Source system checks</div>
        <h2>Private and public sources</h2>
        <div className="benchmark-status">
          <span>{sourceStatus}</span>
          <span>{packageStatus}</span>
        </div>
      </section>
      <PublicAdapterReadinessPanel readiness={adapterReadiness} compact />
      <CredentialPreflightPanel readiness={adapterReadiness} />
      <p className="source-boundary-panel">{adapterReadiness.boundary}</p>
    </div>
  )
}
