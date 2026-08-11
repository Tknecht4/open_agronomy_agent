-- Phase 5 observability, optimization, and SFT readiness tables
CREATE TABLE IF NOT EXISTS field_events (
  id UUID PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id),
  workspace_id UUID NOT NULL REFERENCES workspaces(id),
  field_context_id UUID NOT NULL REFERENCES field_contexts(id),
  recorded_by_user_id UUID REFERENCES users(id),
  event_type TEXT NOT NULL CHECK (
    event_type IN ('observation', 'sample', 'operation', 'decision', 'outcome', 'note', 'correction')
  ),
  occurred_at TIMESTAMPTZ NOT NULL,
  payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(provenance) = 'object'),
  corrects_event_id UUID REFERENCES field_events(id),
  previous_event_sha256 TEXT,
  integrity_sha256 TEXT NOT NULL UNIQUE CHECK (integrity_sha256 ~ '^[0-9a-f]{64}$'),
  recorded_at TIMESTAMPTZ NOT NULL,
  CHECK (
    (event_type = 'correction' AND corrects_event_id IS NOT NULL)
    OR (event_type <> 'correction' AND corrects_event_id IS NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_field_events_field_time
  ON field_events(field_context_id, recorded_at, id);

CREATE OR REPLACE FUNCTION reject_field_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION 'field events are append-only';
END;
$$;

DROP TRIGGER IF EXISTS field_events_no_update ON field_events;
CREATE TRIGGER field_events_no_update
BEFORE UPDATE ON field_events
FOR EACH ROW EXECUTE FUNCTION reject_field_event_mutation();

DROP TRIGGER IF EXISTS field_events_no_delete ON field_events;
CREATE TRIGGER field_events_no_delete
BEFORE DELETE ON field_events
FOR EACH ROW EXECUTE FUNCTION reject_field_event_mutation();

ALTER TABLE field_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS field_events_member_select ON field_events;
CREATE POLICY field_events_member_select ON field_events
  FOR SELECT USING (
    app_can_access_org(organization_id)
    AND app_workspace_matches(workspace_id)
  );

DROP POLICY IF EXISTS field_events_writer_insert ON field_events;
CREATE POLICY field_events_writer_insert ON field_events
  FOR INSERT WITH CHECK (
    app_can_write_workspace(organization_id)
    AND app_workspace_matches(workspace_id)
  );

CREATE TABLE IF NOT EXISTS agent_trace_spans (
  id BIGSERIAL PRIMARY KEY,
  trace_id UUID NOT NULL,
  thread_id UUID,
  turn_id UUID,
  span_id TEXT NOT NULL,
  parent_span_id TEXT,
  stage TEXT NOT NULL,
  start_ns BIGINT NOT NULL,
  end_ns BIGINT NOT NULL,
  duration_ms DOUBLE PRECISION NOT NULL,
  status TEXT NOT NULL,
  error_type TEXT,
  error_message_redacted TEXT,
  input_size INTEGER,
  output_size INTEGER,
  token_estimate_in INTEGER,
  token_estimate_out INTEGER,
  cache_status TEXT,
  component_version TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_trace_spans_trace ON agent_trace_spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_agent_trace_spans_stage_time ON agent_trace_spans(stage, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_turn_metrics (
  trace_id UUID PRIMARY KEY,
  thread_id UUID NOT NULL,
  turn_id UUID NOT NULL,
  user_id UUID,
  workspace_id UUID,
  route_question_type TEXT,
  risk_level TEXT,
  namespaces TEXT[] NOT NULL DEFAULT '{}',
  required_tools TEXT[] NOT NULL DEFAULT '{}',
  rag_config_version TEXT,
  corpus_bundle_version TEXT,
  prompt_template_version TEXT,
  context_packer_version TEXT,
  model_id TEXT NOT NULL,
  quantization TEXT,
  max_tokens INTEGER NOT NULL DEFAULT 0,
  temperature DOUBLE PRECISION NOT NULL DEFAULT 0,
  top_p DOUBLE PRECISION NOT NULL DEFAULT 0.9,
  top_k INTEGER NOT NULL DEFAULT 0,
  total_latency_ms DOUBLE PRECISION NOT NULL,
  time_to_first_token_ms DOUBLE PRECISION,
  decode_tokens_per_sec DOUBLE PRECISION,
  prompt_tokens_est INTEGER,
  completion_tokens_est INTEGER,
  context_tokens_est INTEGER,
  retrieval_doc_count INTEGER NOT NULL DEFAULT 0,
  top_doc_score DOUBLE PRECISION,
  source_diversity INTEGER NOT NULL DEFAULT 0,
  required_support_rate DOUBLE PRECISION,
  tool_notes_count INTEGER NOT NULL DEFAULT 0,
  tool_precision_proxy DOUBLE PRECISION,
  tool_recall_proxy DOUBLE PRECISION,
  answer_word_count INTEGER NOT NULL DEFAULT 0,
  leak_check_passed BOOLEAN NOT NULL DEFAULT false,
  risk_banner_present BOOLEAN NOT NULL DEFAULT false,
  missing_data_present BOOLEAN NOT NULL DEFAULT false,
  quality_flags TEXT[] NOT NULL DEFAULT '{}',
  user_feedback_score DOUBLE PRECISION,
  human_review_status TEXT NOT NULL DEFAULT 'unreviewed',
  reflection_status TEXT NOT NULL DEFAULT 'not_created',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_agent_turn_metrics_created ON agent_turn_metrics(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_turn_metrics_route ON agent_turn_metrics(route_question_type, risk_level);
CREATE INDEX IF NOT EXISTS idx_agent_turn_metrics_latency ON agent_turn_metrics(total_latency_ms DESC);

CREATE TABLE IF NOT EXISTS prompt_leak_events (
  id BIGSERIAL PRIMARY KEY,
  trace_id UUID NOT NULL,
  thread_id UUID,
  turn_id UUID,
  leak_class TEXT NOT NULL,
  matched_text_hash TEXT NOT NULL,
  severity TEXT NOT NULL,
  reviewer_status TEXT NOT NULL DEFAULT 'unreviewed',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_prompt_leak_trace ON prompt_leak_events(trace_id);

CREATE TABLE IF NOT EXISTS optimization_candidates (
  id BIGSERIAL PRIMARY KEY,
  candidate_id UUID NOT NULL,
  workspace_id UUID,
  created_by_user_id UUID,
  candidate_type TEXT NOT NULL,
  parent_version TEXT,
  candidate_version TEXT NOT NULL,
  generated_from_trace_ids UUID[] NOT NULL DEFAULT '{}',
  reflection_summary TEXT,
  patch JSONB NOT NULL DEFAULT '{}'::jsonb,
  eval_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  rollback_plan TEXT,
  pareto_status TEXT NOT NULL DEFAULT 'pending',
  promoted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_optimization_candidates_id ON optimization_candidates(candidate_id);
CREATE INDEX IF NOT EXISTS idx_optimization_candidates_workspace ON optimization_candidates(workspace_id, pareto_status);

CREATE TABLE IF NOT EXISTS phase5_training_candidates (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL,
  thread_id UUID NOT NULL,
  trace_id UUID NOT NULL,
  reviewer_user_id UUID,
  review_status TEXT NOT NULL DEFAULT 'pending',
  consent_scope TEXT NOT NULL,
  redaction_status TEXT NOT NULL DEFAULT 'redacted',
  repair_layer TEXT,
  failure_class TEXT,
  messages JSONB NOT NULL DEFAULT '[]'::jsonb,
  labels JSONB NOT NULL DEFAULT '{}'::jsonb,
  dataset_card JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_at TIMESTAMPTZ,
  exported_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_phase5_training_candidates_workspace ON phase5_training_candidates(workspace_id, review_status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_phase5_training_candidates_trace ON phase5_training_candidates(trace_id);

CREATE TABLE IF NOT EXISTS phase5_adapter_registry (
  id UUID PRIMARY KEY,
  workspace_id UUID,
  adapter_id TEXT NOT NULL,
  base_model_id TEXT NOT NULL,
  method TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planned',
  artifact_uri TEXT,
  eval_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  rollback_plan TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_phase5_adapter_registry_adapter ON phase5_adapter_registry(adapter_id);

CREATE TABLE IF NOT EXISTS phase5_model_registry (
  id UUID PRIMARY KEY,
  workspace_id UUID NOT NULL,
  model_id TEXT NOT NULL,
  quantization TEXT NOT NULL,
  context_window INTEGER NOT NULL,
  hardware_profile TEXT NOT NULL,
  license TEXT NOT NULL,
  latency_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
  eval_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
  release_status TEXT NOT NULL DEFAULT 'candidate',
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_phase5_model_registry_workspace_model ON phase5_model_registry(workspace_id, model_id);
CREATE INDEX IF NOT EXISTS idx_phase5_model_registry_status ON phase5_model_registry(workspace_id, release_status);
