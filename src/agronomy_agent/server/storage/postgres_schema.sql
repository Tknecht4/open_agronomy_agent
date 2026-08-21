-- Agronomy Agent Phase 4 hosted platform starter schema
-- PostgreSQL + pgvector. This is a design starter, not a final migration.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE member_role AS ENUM ('owner', 'admin', 'researcher', 'adviser', 'viewer');
CREATE TYPE visibility_level AS ENUM ('private', 'workspace', 'org', 'public_corpus');
CREATE TYPE trace_capture_level AS ENUM ('none', 'operational', 'research_opt_in');
CREATE TYPE redaction_status AS ENUM ('not_required', 'pending', 'redacted', 'reviewed', 'rejected');
CREATE TYPE thread_mode AS ENUM ('baseline', 'agronomic_rag', 'image_rag_research');
CREATE TYPE modality AS ENUM ('text', 'image', 'multimodal');

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text UNIQUE NOT NULL,
  display_name text NOT NULL,
  auth_provider text NOT NULL DEFAULT 'local_dev',
  auth_provider_subject text UNIQUE,
  status text NOT NULL DEFAULT 'active',
  role_label text,
  region_hint text,
  units_preference text DEFAULT 'mixed',
  privacy_mode text DEFAULT 'standard',
  training_consent_default text DEFAULT 'no',
  trace_storage_enabled boolean NOT NULL DEFAULT true,
  feedback_use_allowed boolean NOT NULL DEFAULT false,
  training_candidate_allowed boolean NOT NULL DEFAULT false,
  public_anonymized_examples_allowed boolean NOT NULL DEFAULT false,
  product_updates_allowed boolean NOT NULL DEFAULT false,
  retention_preference text NOT NULL DEFAULT 'default' CHECK (retention_preference IN ('default', 'short', 'delete_on_request')),
  consent_updated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz
);

CREATE TABLE auth_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  auth_subject text NOT NULL,
  email text NOT NULL,
  display_name text NOT NULL,
  issued_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz,
  user_agent_hash text
);

CREATE INDEX auth_sessions_user_idx ON auth_sessions(user_id, revoked_at, expires_at);

CREATE TABLE password_credentials (
  user_id uuid PRIMARY KEY REFERENCES users(id),
  email text UNIQUE NOT NULL,
  password_hash text NOT NULL,
  email_verified_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id),
  email text NOT NULL,
  purpose text NOT NULL CHECK (purpose IN ('email_verification', 'password_reset')),
  token_hash text UNIQUE NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX auth_tokens_lookup_idx ON auth_tokens(purpose, token_hash, consumed_at, expires_at);

CREATE TABLE organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  slug text UNIQUE NOT NULL,
  plan text NOT NULL DEFAULT 'demo',
  created_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  metadata jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role member_role NOT NULL DEFAULT 'adviser',
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, user_id)
);

CREATE TABLE workspaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  name text NOT NULL,
  created_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  settings jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE field_contexts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  created_by_user_id uuid REFERENCES users(id),
  display_name text NOT NULL,
  region_text text NOT NULL,
  country text,
  province_state text,
  county_rm text,
  generalized_geohash text,
  crop_current text,
  crop_year int,
  soil_series_or_texture text,
  drainage_class text,
  irrigation_status text,
  soil_test_summary text,
  crop_rotation_notes text,
  management_notes text,
  known_constraints text[] NOT NULL DEFAULT '{}',
  sensitivity text NOT NULL DEFAULT 'medium',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz,
  deleted_at timestamptz
);

CREATE TABLE threads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  created_by_user_id uuid REFERENCES users(id),
  field_context_id uuid REFERENCES field_contexts(id),
  title text NOT NULL,
  mode thread_mode NOT NULL DEFAULT 'agronomic_rag',
  task_family text,
  risk_level text,
  model_profile_id text,
  rag_config_id text,
  trace_capture trace_capture_level NOT NULL DEFAULT 'operational',
  training_eligible boolean NOT NULL DEFAULT false,
  redaction_status redaction_status NOT NULL DEFAULT 'not_required',
  visibility visibility_level NOT NULL DEFAULT 'workspace',
  status text NOT NULL DEFAULT 'active',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  thread_id uuid NOT NULL REFERENCES threads(id),
  actor text NOT NULL CHECK (actor IN ('user', 'assistant', 'system')),
  content text NOT NULL,
  content_hash text,
  sequence_no int NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (thread_id, sequence_no)
);

CREATE TABLE trace_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  thread_id uuid NOT NULL REFERENCES threads(id),
  message_id uuid REFERENCES messages(id),
  event_type text NOT NULL,
  actor text,
  payload jsonb NOT NULL DEFAULT '{}',
  prompt_hash text,
  output_hash text,
  source_hash text,
  elapsed_ms int,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX trace_events_thread_idx ON trace_events(thread_id, created_at);
CREATE INDEX trace_events_type_idx ON trace_events(event_type);

CREATE TABLE retrieval_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  created_by_user_id uuid REFERENCES users(id),
  thread_id uuid NOT NULL REFERENCES threads(id),
  message_id uuid REFERENCES messages(id),
  trace_event_id uuid REFERENCES trace_events(id),
  query text NOT NULL,
  filters jsonb NOT NULL DEFAULT '{}',
  retrieved_chunk_ids uuid[] NOT NULL DEFAULT '{}',
  results jsonb NOT NULL DEFAULT '[]',
  visibility visibility_level NOT NULL DEFAULT 'workspace',
  sensitivity text NOT NULL DEFAULT 'medium',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE INDEX retrieval_events_thread_idx ON retrieval_events(thread_id, created_at);

CREATE TABLE tool_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  created_by_user_id uuid REFERENCES users(id),
  thread_id uuid NOT NULL REFERENCES threads(id),
  message_id uuid REFERENCES messages(id),
  trace_event_id uuid REFERENCES trace_events(id),
  tool_name text NOT NULL,
  request jsonb NOT NULL DEFAULT '{}',
  response jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'completed',
  elapsed_ms int,
  visibility visibility_level NOT NULL DEFAULT 'workspace',
  sensitivity text NOT NULL DEFAULT 'medium',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE INDEX tool_events_thread_idx ON tool_events(thread_id, created_at);

CREATE TABLE feedback_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  thread_id uuid NOT NULL REFERENCES threads(id),
  message_id uuid REFERENCES messages(id),
  created_by_user_id uuid REFERENCES users(id),
  rating text NOT NULL,
  failure_tags text[] NOT NULL DEFAULT '{}',
  human_correction text,
  ideal_answer text,
  training_consent boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE reflection_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  thread_id uuid REFERENCES threads(id),
  target_component text NOT NULL,
  lesson text NOT NULL,
  candidate_rule text,
  evidence jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'candidate',
  created_by_user_id uuid REFERENCES users(id),
  reviewed_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz
);

CREATE TABLE eval_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  created_by_user_id uuid REFERENCES users(id),
  thread_id uuid REFERENCES threads(id),
  message_id uuid REFERENCES messages(id),
  feedback_event_id uuid REFERENCES feedback_events(id),
  prompt text NOT NULL,
  expected_behavior text,
  candidate_payload jsonb NOT NULL DEFAULT '{}',
  review_status text NOT NULL DEFAULT 'pending',
  reviewed_by_user_id uuid REFERENCES users(id),
  visibility visibility_level NOT NULL DEFAULT 'workspace',
  sensitivity text NOT NULL DEFAULT 'medium',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE eval_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  created_by_user_id uuid REFERENCES users(id),
  status text NOT NULL DEFAULT 'queued',
  suite_name text NOT NULL,
  model_profile_id text,
  candidate_ids uuid[] NOT NULL DEFAULT '{}',
  metrics jsonb NOT NULL DEFAULT '{}',
  gates jsonb NOT NULL DEFAULT '{}',
  failure_cases jsonb NOT NULL DEFAULT '[]',
  visibility visibility_level NOT NULL DEFAULT 'workspace',
  sensitivity text NOT NULL DEFAULT 'medium',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  deleted_at timestamptz
);

CREATE TABLE change_proposals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  created_by_user_id uuid REFERENCES users(id),
  title text NOT NULL,
  target_component text NOT NULL,
  proposal_type text NOT NULL,
  summary text NOT NULL,
  rationale text,
  linked_reflection_id uuid REFERENCES reflection_candidates(id),
  linked_eval_run_id uuid REFERENCES eval_runs(id),
  review_status text NOT NULL DEFAULT 'candidate',
  reviewed_by_user_id uuid REFERENCES users(id),
  gates jsonb NOT NULL DEFAULT '{}',
  visibility visibility_level NOT NULL DEFAULT 'workspace',
  sensitivity text NOT NULL DEFAULT 'medium',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz,
  deleted_at timestamptz
);

CREATE INDEX change_proposals_workspace_idx ON change_proposals(workspace_id, review_status, created_at);

CREATE TABLE attachments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  thread_id uuid REFERENCES threads(id),
  message_id uuid REFERENCES messages(id),
  created_by_user_id uuid REFERENCES users(id),
  filename text NOT NULL,
  content_type text NOT NULL,
  storage_uri text NOT NULL,
  size_bytes bigint NOT NULL,
  sha256 text NOT NULL,
  modality modality NOT NULL DEFAULT 'text',
  sensitivity text NOT NULL DEFAULT 'medium',
  parse_status text NOT NULL DEFAULT 'pending',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  created_by_user_id uuid REFERENCES users(id),
  thread_id uuid REFERENCES threads(id),
  message_id uuid REFERENCES messages(id),
  attachment_id uuid REFERENCES attachments(id),
  artifact_type text NOT NULL,
  storage_uri text NOT NULL,
  sha256 text,
  size_bytes bigint,
  visibility visibility_level NOT NULL DEFAULT 'workspace',
  sensitivity text NOT NULL DEFAULT 'medium',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE data_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  source_id text NOT NULL,
  title text NOT NULL,
  publisher text,
  canonical_url text,
  license_state text NOT NULL DEFAULT 'unknown',
  rag_eligible boolean NOT NULL DEFAULT false,
  sft_eligible boolean NOT NULL DEFAULT false,
  visibility visibility_level NOT NULL DEFAULT 'private',
  source_kind text NOT NULL,
  crops text[] NOT NULL DEFAULT '{}',
  regions text[] NOT NULL DEFAULT '{}',
  buckets text[] NOT NULL DEFAULT '{}',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  UNIQUE (organization_id, workspace_id, source_id)
);

CREATE TABLE knowledge_sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  source_id text NOT NULL,
  title text NOT NULL,
  owner text NOT NULL DEFAULT 'unknown',
  visibility text NOT NULL DEFAULT 'public',
  license_status text NOT NULL DEFAULT 'review_required',
  canonical_url text,
  artifact_path text,
  checksum_sha256 text,
  source_kind text,
  rag_eligible boolean NOT NULL DEFAULT true,
  sft_eligible boolean NOT NULL DEFAULT false,
  metadata_json jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, source_id)
);

CREATE TABLE knowledge_source_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  source_id text NOT NULL,
  checksum_sha256 text NOT NULL,
  canonical_url text,
  artifact_path text,
  status text NOT NULL,
  metadata_json jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE knowledge_chunk_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  source_id text NOT NULL,
  chunk_id text NOT NULL,
  reviewer_status text NOT NULL DEFAULT 'pending',
  rejection_reasons jsonb NOT NULL DEFAULT '[]',
  evidence_coordinates jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (source_id, chunk_id)
);

CREATE TABLE knowledge_ingest_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  source_id text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
  runtime text NOT NULL DEFAULT 'agno_knowledge',
  reader text NOT NULL,
  chunking_strategy text NOT NULL,
  embedder_profile text NOT NULL,
  knowledge_base text NOT NULL,
  contents_table text NOT NULL,
  vector_table text NOT NULL,
  chunk_count int NOT NULL DEFAULT 0,
  duplicate_of_source_id text,
  error_message text,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX knowledge_sources_workspace_idx ON knowledge_sources(workspace_id, visibility, license_status);
CREATE INDEX knowledge_ingest_jobs_source_idx ON knowledge_ingest_jobs(source_id, status);

CREATE TABLE source_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  created_by_user_id uuid REFERENCES users(id),
  data_source_id uuid REFERENCES data_sources(id),
  source_doc_id text NOT NULL,
  title text,
  canonical_url text,
  content_hash text,
  license_state text NOT NULL DEFAULT 'unknown',
  training_eligible boolean NOT NULL DEFAULT false,
  visibility visibility_level NOT NULL DEFAULT 'private',
  sensitivity text NOT NULL DEFAULT 'medium',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  UNIQUE (data_source_id, source_doc_id)
);

CREATE TABLE document_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  data_source_id uuid REFERENCES data_sources(id),
  source_document_id uuid REFERENCES source_documents(id),
  attachment_id uuid REFERENCES attachments(id),
  source_doc_id text,
  chunk_index int NOT NULL,
  title text,
  text_content text NOT NULL,
  source_url text,
  license_state text NOT NULL DEFAULT 'unknown',
  training_eligible boolean NOT NULL DEFAULT false,
  visibility visibility_level NOT NULL DEFAULT 'private',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE INDEX data_sources_workspace_idx ON data_sources(workspace_id, deleted_at);
CREATE INDEX document_chunks_source_idx ON document_chunks(data_source_id, chunk_index);
CREATE INDEX document_chunks_workspace_idx ON document_chunks(workspace_id);

-- Choose dimensions per encoder. 1024 is a placeholder.
CREATE TABLE embeddings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  chunk_id uuid REFERENCES document_chunks(id),
  attachment_id uuid REFERENCES attachments(id),
  source_kind text NOT NULL,
  source_id text NOT NULL,
  modality modality NOT NULL,
  encoder_name text NOT NULL,
  encoder_version text NOT NULL,
  dimensions int NOT NULL,
  embedding vector,
  license_state text NOT NULL DEFAULT 'unknown',
  training_eligible boolean NOT NULL DEFAULT false,
  visibility visibility_level NOT NULL DEFAULT 'private',
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE INDEX embeddings_workspace_idx ON embeddings(workspace_id, modality, encoder_name);
-- Use the actual vector dimension and operator class per encoder in migrations.
-- Example: CREATE INDEX embeddings_hnsw_cosine_idx ON embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE ingest_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  data_source_id uuid REFERENCES data_sources(id),
  attachment_id uuid REFERENCES attachments(id),
  job_type text NOT NULL,
  status text NOT NULL DEFAULT 'queued',
  queue_name text NOT NULL DEFAULT 'ingest',
  error_message text,
  result jsonb NOT NULL DEFAULT '{}',
  created_by_user_id uuid REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);

CREATE TABLE exports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  thread_id uuid REFERENCES threads(id),
  created_by_user_id uuid REFERENCES users(id),
  export_type text NOT NULL,
  storage_uri text NOT NULL,
  redaction_status redaction_status NOT NULL DEFAULT 'not_required',
  sha256 text,
  metadata jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX exports_workspace_idx ON exports(workspace_id, thread_id, created_at);

CREATE TABLE export_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  thread_id uuid REFERENCES threads(id),
  created_by_user_id uuid REFERENCES users(id),
  export_type text NOT NULL,
  redaction_status redaction_status NOT NULL DEFAULT 'not_required',
  status text NOT NULL DEFAULT 'queued',
  queue_name text NOT NULL DEFAULT 'exports',
  export_id uuid REFERENCES exports(id),
  error_message text,
  result jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);

CREATE INDEX export_jobs_workspace_idx ON export_jobs(workspace_id, status, created_at);

CREATE TABLE embedding_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  attachment_id uuid REFERENCES attachments(id),
  created_by_user_id uuid REFERENCES users(id),
  job_type text NOT NULL DEFAULT 'attachment_embedding_reindex',
  status text NOT NULL DEFAULT 'queued',
  queue_name text NOT NULL DEFAULT 'embedding',
  error_message text,
  result jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);

CREATE INDEX embedding_jobs_workspace_idx ON embedding_jobs(workspace_id, status, created_at);

CREATE TABLE image_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id),
  workspace_id uuid NOT NULL REFERENCES workspaces(id),
  thread_id uuid REFERENCES threads(id),
  created_by_user_id uuid REFERENCES users(id),
  question text NOT NULL,
  crop text,
  region text,
  attachment_ids uuid[] NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'queued',
  queue_name text NOT NULL DEFAULT 'image',
  error_message text,
  result jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz
);

CREATE INDEX image_jobs_workspace_idx ON image_jobs(workspace_id, status, created_at);

CREATE TABLE audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id),
  workspace_id uuid REFERENCES workspaces(id),
  actor_user_id uuid REFERENCES users(id),
  event_type text NOT NULL,
  target_type text,
  target_id uuid,
  ip_hash text,
  user_agent text,
  payload jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE corpus_audits (
  id text PRIMARY KEY,
  config_path text NOT NULL,
  corpus_hash text NOT NULL,
  corpus_count int NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Defense-in-depth RLS. Application code must still authorize every object access.
--
-- Production API transactions must set:
--   SET LOCAL app.current_user_id = '<uuid>';
--   SET LOCAL app.current_organization_id = '<uuid>';
--   SET LOCAL app.current_workspace_id = '<uuid>'; -- optional for org-level reads
--
-- These policies are intentionally conservative. They are a starter migration
-- target for managed Postgres, not a substitute for app-level BOLA checks.
CREATE OR REPLACE FUNCTION app_current_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION app_current_organization_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.current_organization_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION app_current_workspace_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.current_workspace_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION app_has_org_role(org_id uuid, allowed_roles member_role[])
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM memberships
    WHERE organization_id = org_id
      AND user_id = app_current_user_id()
      AND role = ANY(allowed_roles)
  )
$$;

CREATE OR REPLACE FUNCTION app_can_access_org(org_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT org_id = app_current_organization_id()
     AND app_has_org_role(org_id, ARRAY['owner','admin','researcher','adviser','viewer']::member_role[])
$$;

CREATE OR REPLACE FUNCTION app_can_write_workspace(org_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT org_id = app_current_organization_id()
     AND app_has_org_role(org_id, ARRAY['owner','admin','researcher','adviser']::member_role[])
$$;

CREATE OR REPLACE FUNCTION app_can_research_workspace(org_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT org_id = app_current_organization_id()
     AND app_has_org_role(org_id, ARRAY['owner','admin','researcher']::member_role[])
$$;

CREATE OR REPLACE FUNCTION app_can_admin_org(org_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT org_id = app_current_organization_id()
     AND app_has_org_role(org_id, ARRAY['owner','admin']::member_role[])
$$;

CREATE OR REPLACE FUNCTION app_workspace_matches(row_workspace_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT app_current_workspace_id() IS NULL OR row_workspace_id IS NULL OR row_workspace_id = app_current_workspace_id()
$$;

CREATE OR REPLACE FUNCTION app_can_access_visible_row(org_id uuid, row_visibility visibility_level)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
  SELECT row_visibility = 'public_corpus' OR app_can_access_org(org_id)
$$;

ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE field_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE trace_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE tool_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reflection_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE change_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_source_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_chunk_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_ingest_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingest_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE export_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE embedding_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE image_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE corpus_audits ENABLE ROW LEVEL SECURITY;

CREATE POLICY organizations_member_select ON organizations
  FOR SELECT USING (app_can_access_org(id) AND deleted_at IS NULL);

CREATE POLICY organizations_admin_write ON organizations
  FOR UPDATE USING (app_can_admin_org(id))
  WITH CHECK (app_can_admin_org(id));

CREATE POLICY memberships_admin_select ON memberships
  FOR SELECT USING (app_can_admin_org(organization_id));

CREATE POLICY memberships_admin_write ON memberships
  FOR ALL USING (app_can_admin_org(organization_id))
  WITH CHECK (app_can_admin_org(organization_id));

CREATE POLICY workspaces_member_select ON workspaces
  FOR SELECT USING (app_can_access_org(organization_id) AND deleted_at IS NULL);

CREATE POLICY workspaces_admin_write ON workspaces
  FOR ALL USING (app_can_admin_org(organization_id))
  WITH CHECK (app_can_admin_org(organization_id));

CREATE POLICY field_contexts_member_select ON field_contexts
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY field_contexts_writer_write ON field_contexts
  FOR ALL USING (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY threads_member_select ON threads
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY threads_writer_write ON threads
  FOR ALL USING (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY messages_member_select ON messages
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY messages_writer_insert ON messages
  FOR INSERT WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY trace_events_member_select ON trace_events
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY trace_events_system_insert ON trace_events
  FOR INSERT WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY retrieval_events_member_select ON retrieval_events
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY retrieval_events_system_insert ON retrieval_events
  FOR INSERT WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY retrieval_events_research_update ON retrieval_events
  FOR UPDATE USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY tool_events_member_select ON tool_events
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY tool_events_system_insert ON tool_events
  FOR INSERT WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY tool_events_research_update ON tool_events
  FOR UPDATE USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY feedback_events_member_select ON feedback_events
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY feedback_events_writer_insert ON feedback_events
  FOR INSERT WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY reflection_candidates_member_select ON reflection_candidates
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY reflection_candidates_writer_insert ON reflection_candidates
  FOR INSERT WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY reflection_candidates_research_review ON reflection_candidates
  FOR UPDATE USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY eval_candidates_member_select ON eval_candidates
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY eval_candidates_writer_insert ON eval_candidates
  FOR INSERT WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY eval_candidates_research_review ON eval_candidates
  FOR UPDATE USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY eval_runs_member_select ON eval_runs
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY eval_runs_research_write ON eval_runs
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY change_proposals_member_select ON change_proposals
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY change_proposals_research_write ON change_proposals
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY attachments_member_select ON attachments
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY attachments_writer_write ON attachments
  FOR ALL USING (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY artifacts_member_select ON artifacts
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY artifacts_writer_write ON artifacts
  FOR ALL USING (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY data_sources_member_select ON data_sources
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY data_sources_research_write ON data_sources
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY knowledge_sources_member_select ON knowledge_sources
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY knowledge_sources_research_write ON knowledge_sources
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY knowledge_source_versions_member_select ON knowledge_source_versions
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY knowledge_source_versions_research_write ON knowledge_source_versions
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY knowledge_chunk_reviews_member_select ON knowledge_chunk_reviews
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY knowledge_chunk_reviews_research_write ON knowledge_chunk_reviews
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY knowledge_ingest_jobs_member_select ON knowledge_ingest_jobs
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY knowledge_ingest_jobs_research_write ON knowledge_ingest_jobs
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY source_documents_member_select ON source_documents
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id) AND deleted_at IS NULL);

CREATE POLICY source_documents_research_write ON source_documents
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY document_chunks_member_select ON document_chunks
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id));

CREATE POLICY document_chunks_research_write ON document_chunks
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY embeddings_member_select ON embeddings
  FOR SELECT USING (app_can_access_visible_row(organization_id, visibility) AND app_workspace_matches(workspace_id));

CREATE POLICY embeddings_research_write ON embeddings
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY ingest_jobs_member_select ON ingest_jobs
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY ingest_jobs_research_write ON ingest_jobs
  FOR ALL USING (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_research_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY exports_member_select ON exports
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY exports_writer_insert ON exports
  FOR INSERT WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY export_jobs_member_select ON export_jobs
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY export_jobs_writer_write ON export_jobs
  FOR ALL USING (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY embedding_jobs_member_select ON embedding_jobs
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY embedding_jobs_writer_write ON embedding_jobs
  FOR ALL USING (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY image_jobs_member_select ON image_jobs
  FOR SELECT USING (app_can_access_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY image_jobs_writer_write ON image_jobs
  FOR ALL USING (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id))
  WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY audit_events_admin_select ON audit_events
  FOR SELECT USING (app_can_admin_org(organization_id) AND app_workspace_matches(workspace_id));

CREATE POLICY audit_events_system_insert ON audit_events
  FOR INSERT WITH CHECK (app_can_write_workspace(organization_id) AND app_workspace_matches(workspace_id));
