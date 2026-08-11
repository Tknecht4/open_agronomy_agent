export type TurnRoute = {
  question_type?: string
  risk_level?: string
  namespaces?: string[]
  required_tools?: string[]
  query_expansion?: string[]
  answer_style?: string
  audience?: string
  guidance?: string | null
}

export type RetrievedDoc = {
  rank: number
  doc_id: string
  title: string
  source_type: string
  score: number
  source?: string
  snippet?: string
  tags?: string[]
  source_id?: string
  jurisdictions?: string[]
  languages?: string[]
  currency_status?: string
  retrieval_policy?: string
  content_risk_tags?: string[]
  license_status?: string
  raw_sha256?: string
  chunk_sha256?: string
  manifest_sha256?: string
  distribution_scope?: string
  answer_role?: string
}

export type GraphHit = {
  rank: number
  node_id: string
  name: string
  kind: string
  neighbors: string[]
  evidence: string
}

export type ToolInvocation = {
  name: string
  text?: string
  payload?: Record<string, unknown>
}

export type StructuredEvidenceCard = {
  doc_id?: string | null
  title?: string | null
  publisher?: string | null
  source?: string | null
  source_id?: string | null
  url?: string | null
  source_type?: string | null
  updated_at?: string | null
  license_status?: string | null
  score?: number | null
  why_used?: string | string[] | null
  known_limitations?: string | string[] | null
  adapter_status?: string | null
  adapter_name?: string | null
  summary?: Record<string, unknown> | null
}

export type StructuredAnswerTrace = {
  answer?: string
  public_answer_markdown?: string
  evidence?: StructuredEvidenceCard[]
  evidence_cards?: StructuredEvidenceCard[]
  missing_data?: string[]
  missing_data_prompts?: string[]
  risk_banner?: string | null
  risk_level?: string
  answer_type?: string
  field_context_used?: Array<Record<string, unknown>>
  caveats?: string[]
  recommended_next_steps?: string[]
}

export type TurnTrace = {
  route?: TurnRoute | null
  coverage_checklist?: string[]
  retrieved_docs?: RetrievedDoc[]
  graph_hits?: GraphHit[]
  tool_invocations?: ToolInvocation[]
  prompt_messages?: Array<Record<string, unknown>> | null
  structured_answer?: StructuredAnswerTrace | null
  metadata?: Record<string, unknown>
}

export type TurnFeedback = {
  rating?: number | null
  accepted?: boolean | null
  failure_tags?: string[]
  correction?: string | null
  ideal_answer?: string | null
  reviewer_notes?: string | null
  route_correct?: boolean | null
  route_correction_labels?: string[]
  evidence_feedback?: Array<Record<string, unknown>>
}

export type TurnSystemState = {
  mode: 'baseline' | 'agronomic_rag' | 'mock'
  model_id: string
  rag_config: string | null
  prompt_version: string
  latency_ms?: number | null
  model_identity?: {
    schema_version?: string
    status?: string
    configured_model_id?: string
    configured_model_revision?: string | null
    backend?: string
    response_model_id?: string | null
    model_config_sha256?: string | null
    receipt_sha256?: string | null
  }
}

export type AnswerIntegrityReceipt = {
  schema_version: string
  status: 'verified' | 'invalid' | 'legacy_not_captured' | string
  receipt_sha256?: string | null
  question_sha256?: string
  answer_sha256?: string
  trace_sha256?: string
  system_state_sha256?: string
  field_snapshot_sha256?: string | null
  current_answer_sha256?: string
  current_trace_sha256?: string
  boundary?: string
}

export type Turn = {
  turn_id: string
  session_id?: string
  parent_turn_id?: string | null
  created_at?: string
  user_message: string
  answer: string
  answer_status: string
  system_state?: TurnSystemState
  trace?: TurnTrace
  feedback?: TurnFeedback
  answer_integrity_receipt?: AnswerIntegrityReceipt
  knowledge_coverage?: {
    schema_version?: string
    capture_status: string
    record_source?: string | null
    boundaries: Array<{
      jurisdiction: string
      status: string
      requires_prompt_boundary?: boolean | null
      registered_source_ids?: string[]
      distributable_source_ids?: string[]
      retrieved_source_ids?: string[]
      retrieved_context_source_ids?: string[]
    }>
  }
}

export type Consent = {
  local_trace_capture: boolean
  research_export_allowed: boolean
  training_export_allowed: boolean
  redaction_required?: boolean
}

export type SessionStatus = 'active' | 'paused' | 'archived'

export type SessionRecord = {
  session_id: string
  title: string
  tags: string[]
  status: SessionStatus
  archived: boolean
  consent: Consent
  context: Record<string, unknown>
  turns: Turn[]
}

export type HostedUser = {
  id: string
  email: string
  display_name: string
  account_consent?: {
    schema_version: string
    trace_storage_enabled: boolean
    feedback_use_allowed: boolean
    training_candidate_allowed: boolean
    public_anonymized_examples_allowed: boolean
    product_updates_allowed: boolean
    retention_preference: 'default' | 'short' | 'delete_on_request'
    updated_at?: string | null
  }
}

export type HostedOrganization = {
  id: string
  name: string
  slug: string
  role?: string
}

export type HostedWorkspace = {
  id: string
  organization_id: string
  name: string
}

export type HostedMessage = {
  id: string
  thread_id: string
  actor: 'user' | 'assistant' | 'system'
  content: string
  metadata?: Record<string, unknown>
  created_at?: string
}

export type HostedThread = {
  id: string
  workspace_id: string
  organization_id: string
  field_context_id?: string | null
  title: string
  mode: 'baseline' | 'agronomic_rag' | 'image_rag_research'
  risk_level?: string | null
  task_family?: string | null
  trace_capture_level?: 'none' | 'operational' | 'research_opt_in'
  training_eligible?: boolean
  status?: string
  deleted_at?: string | null
  messages?: HostedMessage[]
}

export type HostedFieldContext = {
  id: string
  workspace_id: string
  display_name: string
  region_text: string
  country?: string | null
  province_state?: string | null
  county_rm?: string | null
  crop_current?: string | null
  crop_year?: number | null
  soil_series_or_texture?: string | null
  drainage_class?: string | null
  irrigation_status?: string | null
  soil_test_summary?: string | null
  crop_rotation_notes?: string | null
  management_notes?: string | null
  known_constraints?: string[]
  sensitivity: 'low' | 'medium' | 'high'
  quality_meter?: {
    schema_version: string
    summary: string
    ready: {
      conceptual_answer: boolean
      diagnostic_triage: boolean
      product_rate_decision: boolean
    }
    checks: Array<{
      id: string
      label: string
      status: 'ready' | 'missing' | 'blocked'
      available_fields: string[]
      missing_fields: string[]
    }>
    missing_minimum_next_prompts: string[]
    product_rate_boundary: string
  }
  deleted_at?: string | null
}

export type HostedDataSource = {
  id: string
  workspace_id: string
  source_id: string
  title: string
  publisher?: string | null
  canonical_url?: string | null
  license_state: string
  rag_eligible: boolean
  sft_eligible: boolean
  source_kind: string
  crops?: string[]
  regions?: string[]
  buckets: string[]
  metadata?: Record<string, unknown>
  deleted_at?: string | null
}

export type HostedAttachment = {
  id: string
  workspace_id: string
  thread_id?: string | null
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  modality: 'text' | 'image' | 'multimodal'
  sensitivity: 'low' | 'medium' | 'high'
  parse_status: string
  metadata: Record<string, unknown>
  deleted_at?: string | null
}

export type HostedGeoPriors = {
  workspace_id: string
  field_context_id?: string | null
  location_text: string
  candidate_regions: Array<{
    label: string
    name: string
    layer: string
    system: string
    code: string
    match_reason: string
    confidence: number
    priors: string[]
    evidence_terms: string[]
    source: string
  }>
  boosted_namespaces: string[]
  evidence: string[]
  missing_context: string[]
  uncertainty: 'medium' | 'high'
  used_as_prior_only: boolean
  not_field_specific_fact: boolean
  disclaimer: string
  ui_notice: string
  recommended_followups: string[]
}

export type HostedIngestJob = {
  id: string
  workspace_id: string
  data_source_id?: string | null
  status: string
  queue_name: string
  error_message?: string | null
  result?: Record<string, unknown>
}

export type HostedCorpusHealth = {
  workspace_id: string
  status: 'healthy' | 'warning' | 'blocked'
  source_count: number
  rag_eligible_count: number
  sft_eligible_count: number
  ingest_job_count: number
  queued_ingest_count: number
  failed_ingest_count: number
  chunk_count: number
  issue_counts: Record<string, number>
  sources: Array<{
    data_source_id: string
    source_id: string
    title: string
    license_state: string
    rag_eligible: boolean
    sft_eligible: boolean
    source_kind: string
    chunk_count: number
    latest_ingest_status: string
    latest_ingest_error?: string | null
    issue_flags: string[]
  }>
}

export type HostedQuotaReport = {
  workspace_id: string
  quotas: Record<string, number>
  usage: Record<string, number>
  limits: Array<{
    quota: string
    usage_key: string
    used: number
    limit: number
    remaining: number
    exceeded: boolean
  }>
  blocked: boolean
}

export type HostedEvalCandidate = {
  id: string
  workspace_id: string
  thread_id: string
  message_id?: string | null
  target_component: string
  payload: Record<string, unknown>
  review_status: string
}

export type HostedEvalRun = {
  id: string
  workspace_id: string
  name: string
  status: string
  candidate_ids: string[]
  metrics: Record<string, unknown>
  gates: Record<string, unknown>
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export type HostedChangeProposal = {
  id: string
  workspace_id: string
  title: string
  target_component: string
  proposal_type: string
  summary: string
  linked_reflection_id?: string | null
  linked_eval_run_id?: string | null
  review_status: string
  gates: Record<string, unknown>
  metadata: Record<string, unknown>
}

export type HostedExport = {
  id: string
  workspace_id: string
  thread_id?: string | null
  export_type: string
  object_store_uris_included?: false
  redaction_status: string
  sha256?: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export type HostedExportJob = {
  id: string
  workspace_id: string
  thread_id: string
  export_type: string
  redaction_status: string
  status: 'queued' | 'running' | 'completed' | 'failed' | string
  queue_name: string
  export_id?: string | null
  error_message?: string | null
  result: Record<string, unknown>
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

export type HostedAuditEvent = {
  id: string
  organization_id?: string | null
  workspace_id?: string | null
  actor_user_id?: string | null
  event_type: string
  target_type?: string | null
  target_id?: string | null
  payload: Record<string, unknown>
  created_at: string
}

export type HostedTraceEvent = {
  event_id: string
  event_type: string
  actor?: string | null
  payload: Record<string, unknown>
  created_at: string
}

export type HostedTraceBundle = {
  schema_version: 'phase4.thread_trace.v1'
  workspace_id: string
  organization_id?: string
  thread: {
    thread_id: string
    title: string
    mode: string
    risk_level?: string | null
    task_family?: string | null
  }
  events: HostedTraceEvent[]
  privacy: {
    trace_capture_level: string
    training_eligible: boolean
    redaction_status: string
  }
}

export type Phase5TraceSpan = {
  trace_id: string
  thread_id?: string | null
  turn_id?: string | null
  span_id: string
  stage: string
  duration_ms: number
  status: string
  cache_status?: string | null
  metadata?: Record<string, unknown>
}

export type Phase5TurnMetrics = {
  trace_id: string
  thread_id: string
  turn_id: string
  workspace_id?: string | null
  route_question_type?: string | null
  risk_level?: string | null
  context_packer_version?: string | null
  model_id: string
  total_latency_ms: number
  retrieval_doc_count: number
  leak_check_passed: boolean
  answer_word_count: number
  quality_flags: string[]
}

export type Phase5AdminTrace = {
  trace_id: string
  metrics: Phase5TurnMetrics
  spans: Phase5TraceSpan[]
  prompt_leak_events: Array<Record<string, unknown>>
}

export type Phase5LatencyDashboard = {
  workspace_id: string
  schema_version: string
  dashboard: {
    turn_count: number
    latency_ms: { p50?: number | null; p95?: number | null; max?: number | null }
    leak_failures: number
    cache?: Record<string, unknown>
  }
}
