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

export type ToolInvocation =
  | {
      // Legacy adapter/guard trace record.
      name: string
      text?: string
      payload?: Record<string, unknown>
      schema_version?: undefined
      tool_id?: undefined
      authority_role?: string
    }
  | {
      schema_version: 'open_agronomy_agent.tool_invocation.v1' | 'open_agronomy_agent.tool_result.v1'
      tool_id: string
      status: string
      invocation_id?: string
      tool_version?: string
      operation?: string
      authority_role?: string
      limitations?: string[]
      missing_inputs?: string[]
      inputs?: Record<string, unknown>
      payload?: Record<string, unknown>
      name?: undefined
      text?: string
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

export type TurnExecutionStageReceipt = {
  schema_version: string
  topology_version: string
  stage_id: string
  position: number
  state: string
  evidence: Record<string, unknown>
  evidence_sha256?: string
  receipt_sha256?: string
}

export type TurnTrace = {
  route?: TurnRoute | null
  coverage_checklist?: string[]
  retrieved_docs?: RetrievedDoc[]
  graph_hits?: GraphHit[]
  tool_invocations?: ToolInvocation[]
  prompt_messages?: Array<Record<string, unknown>> | null
  structured_answer?: StructuredAnswerTrace | null
  metadata?: Record<string, unknown> & {
    execution_stage_receipts?: TurnExecutionStageReceipt[]
  }
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
  generation_path?: string
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
  metadata?: { client_operation_id?: string } & Record<string, unknown>
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
  turns_included?: boolean
  session_id: string
  created_at?: string
  updated_at?: string | null
  title: string
  tags: string[]
  status: SessionStatus
  archived: boolean
  consent: Consent
  context: Record<string, unknown>
  turns: Turn[]
}
