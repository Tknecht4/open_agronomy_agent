import { readFileSync } from 'node:fs'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { auditPhase6Accessibility } from './accessibilityAudit'
import { PHASE6_DEFERRED_ACTION_STORAGE_KEY } from './deferredActions'
import { PHASE6_LOW_BANDWIDTH_STORAGE_KEY } from './lowBandwidth'
import { PHASE6_CHAT_DRAFT_STORAGE_KEY } from './offlineDrafts'
import { PHASE6_SCRATCHPAD_STORAGE_KEY } from './offlineScratchpad'
import { auditPhase6RenderingSecurity } from './renderingSecurityAudit'
import { auditPhase6ResponsiveReadiness } from './responsiveAudit'
import { PHASE6_VIRTUAL_LIST_LIMIT } from './virtualizedList'

type FetchResult = {
  ok: boolean
  status: number
  json: () => Promise<unknown>
  text?: () => Promise<string>
}

type FetchHandler = (reqInit?: RequestInit) => Promise<FetchResult>
type HostedMessageFixture = {
  id: string
  thread_id: string
  actor: string
  content: string
  metadata: Record<string, unknown>
}
type HostedTraceEventFixture = {
  event_id: string
  event_type: string
  actor: string
  payload: Record<string, unknown>
  created_at: string
}

const createTestStorage = (): Storage => {
  const values = new Map<string, string>()
  return {
    get length() {
      return values.size
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => values.delete(key),
    setItem: (key: string, value: string) => values.set(key, String(value)),
  }
}

const mkOk = (payload: unknown): FetchResult => ({
  ok: true,
  status: 200,
  json: async () => payload,
})

const mkFail = (status: number, message: string): FetchResult => ({
  ok: false,
  status,
  text: async () => message,
  json: async () => ({ message }),
})

const mkSse = (payload: string): FetchResult => ({
  ok: true,
  status: 200,
  text: async () => payload,
  json: async () => {
    try {
      return JSON.parse(payload)
    } catch {
      return {}
    }
  },
})

const createBaseMock = (overrides: Record<string, FetchHandler> = {}) => {
  const sourceState = [
    {
      source_id: 'src_1',
      source_type: 'file',
      path: '/tmp/source-1.txt',
      url: null,
      owner: null,
      license_status: 'unknown',
      checksum: '111',
      inspection: { exists: true, path: '/tmp/source-1.txt', type: 'file' },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ]

  const sessionRecord = {
    session_id: 'sess_1',
    title: 'Seed session',
    tags: ['demo'],
    status: 'active' as const,
    archived: false,
    consent: {
      local_trace_capture: true,
      research_export_allowed: true,
      training_export_allowed: false,
    },
    context: {
      crop: 'corn',
      region: 'IA',
      notes: '',
      jurisdiction: '',
      soil_context: '',
      season: '',
    },
    turns: [
      {
        turn_id: 'turn_1',
        user_message: 'How to manage high phosphorus?',
        answer: 'Start by checking runoff exposure and ask for soil texture.',
        answer_status: 'draft',
        trace: {
          route: {
            risk_level: 'medium',
            question_type: 'fertility',
            namespaces: ['fertility', 'soil_water'],
            required_tools: ['fertility_frame'],
          },
          coverage_checklist: ['check soil test'],
          retrieved_docs: [
            {
              rank: 1,
              doc_id: 'doc_1',
              title: 'Phosphorus runoff',
              source_type: 'applied_guidance',
              score: 0.9,
              snippet: 'manage P loss',
            },
          ],
          graph_hits: [],
          tool_invocations: [],
        },
      },
    ],
  }

  const sessions = [
    sessionRecord,
  ]
  const hostedOrg = {
    id: 'org_1',
    name: 'Hosted Demo Org',
    slug: 'hosted-demo-org',
    role: 'owner',
  }
  const hostedWorkspace = {
    id: 'workspace_1',
    organization_id: hostedOrg.id,
    name: 'Hosted demo workspace',
  }
  let hostedWorkspaceDeleted = false
  let hostedAccountDeleted = false
  let hostedSessionsRevoked = false
  let hostedPasswordVerified = false
  let hostedPasswordReset = false
  let hostedAccountConsent = {
    schema_version: 'phase6.account_consent.v1',
    trace_storage_enabled: true,
    feedback_use_allowed: false,
    training_candidate_allowed: false,
    public_anonymized_examples_allowed: false,
    product_updates_allowed: false,
    retention_preference: 'default',
    updated_at: null as string | null,
  }
  const hostedVerificationToken = 'verify-token-123'
  const hostedResetToken = 'reset-token-123'
  const hostedAuthSession = {
    id: '11111111-1111-4111-8111-111111111111',
    issued_at: '2026-01-01T00:00:00+00:00',
    expires_at: '2026-01-01T08:00:00+00:00',
    last_seen_at: '2026-01-01T00:05:00+00:00',
    revoked_at: null as string | null,
    current: true,
    user_agent_hash: 'user-agent-sha',
  }
  const hostedFieldContext = {
    id: 'field_context_1',
    workspace_id: hostedWorkspace.id,
    display_name: 'North field generalized',
    region_text: 'Iowa Des Moines Lobe',
    crop_current: 'corn',
    management_notes: null as string | null,
    sensitivity: 'medium',
    quality_meter: {
      schema_version: 'phase6_field_context_quality_v1',
      summary: 'diagnostic_triage_ready',
      ready: {
        conceptual_answer: true,
        diagnostic_triage: true,
        product_rate_decision: false,
      },
      checks: [
        {
          id: 'conceptual_answer',
          label: 'Enough for conceptual answer',
          status: 'ready',
          available_fields: ['crop_current', 'region_text'],
          missing_fields: [],
        },
        {
          id: 'diagnostic_triage',
          label: 'Enough for diagnostic triage',
          status: 'ready',
          available_fields: ['crop_current', 'region_text', 'management_notes'],
          missing_fields: [],
        },
        {
          id: 'product_rate_decision',
          label: 'Not enough for product/rate decision',
          status: 'blocked',
          available_fields: ['crop_current', 'region_text'],
          missing_fields: ['current product label'],
        },
      ],
      missing_minimum_next_prompts: ['For product or rate decisions, attach the current label and local recommendation basis.'],
      product_rate_boundary: 'Field profiles do not authorize product, label, or rate decisions.',
    },
    deleted_at: null as string | null,
  }
  const hostedThread = {
    id: 'thread_1',
    workspace_id: hostedWorkspace.id,
    organization_id: hostedOrg.id,
    field_context_id: null as string | null,
    title: 'Hosted phosphorus review',
    mode: 'agronomic_rag',
    trace_capture_level: 'research_opt_in',
    training_eligible: true,
    status: 'active',
    deleted_at: null as string | null,
    messages: [] as HostedMessageFixture[],
  }
  const hostedTrace = {
    schema_version: 'phase4.thread_trace.v1',
    workspace_id: hostedWorkspace.id,
    organization_id: hostedOrg.id,
    thread: {
      thread_id: hostedThread.id,
      title: hostedThread.title,
      mode: 'agronomic_rag',
      risk_level: 'medium',
      task_family: 'fertility_diagnostic',
    },
    events: [] as HostedTraceEventFixture[],
    privacy: {
      trace_capture_level: 'research_opt_in',
      training_eligible: true,
      redaction_status: 'not_required',
    },
  }
  const fieldContexts = [] as typeof hostedFieldContext[]
  const hostedDataSource = {
    id: 'data_source_1',
    workspace_id: hostedWorkspace.id,
    source_id: 'demo_fertility_source',
    title: 'Demo fertility source',
    publisher: 'Example Extension',
    canonical_url: 'https://example.test/fertility',
    license_state: 'review_required',
    rag_eligible: true,
    sft_eligible: false,
    source_kind: 'public_extension',
    crops: ['corn'],
    regions: ['Iowa'],
    buckets: ['nutrient_management'],
    metadata: {},
    deleted_at: null as string | null,
  }
  const dataSources = [] as typeof hostedDataSource[]
  const ingestJobs = [] as Array<{
    id: string
    workspace_id: string
    data_source_id: string
    status: string
    queue_name: string
    error_message?: string | null
    result?: Record<string, unknown>
  }>
  const hostedAttachment = {
    id: 'attachment_1',
    workspace_id: hostedWorkspace.id,
    thread_id: hostedThread.id,
    filename: 'hosted-field-note.txt',
    content_type: 'text/plain',
    size_bytes: 72,
    sha256: 'attachment-sha',
    modality: 'text',
    sensitivity: 'high',
    parse_status: 'private_indexed',
    metadata: { chunk_count: 1, private_rag_scope: 'workspace', retention_policy: 'delete_on_request' },
    deleted_at: null as string | null,
  }
  const attachments = [] as typeof hostedAttachment[]
  const evalCandidates = [] as Array<{
    id: string
    workspace_id: string
    thread_id: string
    message_id: string
    target_component: string
    payload: Record<string, unknown>
    review_status: string
  }>
  const evalRuns = [] as Array<{
    id: string
    workspace_id: string
    name: string
    status: string
    candidate_ids: string[]
    metrics: Record<string, unknown>
    gates: Record<string, unknown>
  }>
  const changeProposals = [] as Array<{
    id: string
    workspace_id: string
    title: string
    target_component: string
    proposal_type: string
    summary: string
    linked_eval_run_id?: string
    review_status: string
    gates: Record<string, unknown>
    metadata: Record<string, unknown>
  }>
  const hostedExports = [] as Array<{
    id: string
    workspace_id: string
    thread_id: string
    export_type: string
    object_store_uris_included: false
    redaction_status: string
    sha256: string
    metadata: Record<string, unknown>
    created_at: string
  }>
  const hostedExportJobs = [] as Array<{
    id: string
    workspace_id: string
    thread_id: string
    export_type: string
    redaction_status: string
    status: string
    queue_name: string
    export_id: string | null
    error_message: string | null
    result: Record<string, unknown>
    created_at: string
    started_at: string | null
    finished_at: string | null
  }>
  const auditEvents = [] as Array<{
    id: string
    organization_id: string
    workspace_id: string
    actor_user_id: string
    event_type: string
    target_type: string
    target_id: string
    payload: Record<string, unknown>
    created_at: string
  }>

  const fetchMap: Record<string, FetchHandler> = {
    'GET /api/sessions': async () => mkOk(sessions),
    'GET /api/sessions?include_archived=true': async () => mkOk(sessions),
    'GET /api/configs': async () =>
      mkOk({
        modes: ['baseline', 'agronomic_rag', 'mock'],
        rag_configs: ['configs/rag_final_mvp.yaml', 'configs/rag.yaml'],
        models: ['mlx-community/Qwen3.5-2B-OptiQ-4bit', 'mlx-community/Qwen3.5-2B-8bit'],
        prompt_versions: ['phase3_default_v0'],
        default_rag_config: 'configs/rag_final_mvp.yaml',
      }),
    'GET /api/data-sources': async () => mkOk(sourceState),
    'POST /api/data-sources': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const created = {
        source_id: `src_${sourceState.length + 1}`,
        source_type: body.source_type,
        path: body.path || null,
        url: body.url || null,
        owner: body.owner || null,
        license_status: body.license_status || 'unknown',
        training_eligible: body.training_eligible || false,
        refresh_policy: body.refresh_policy || 'manual',
        checksum: 'checksum-new',
        inspection: { exists: true, path: body.path || body.url, type: body.path ? 'file' : 'url' },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }
      sourceState.push(created)
      return mkOk(created)
    },
    'POST /api/sessions/sess_1/turns': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      return mkOk({
        turn_id: 'turn_2',
        turn: {
          turn_id: 'turn_2',
          user_message: body.message,
          answer: 'Mocked answer response',
          answer_status: 'draft',
          trace: {
            route: {
              risk_level: 'low',
              question_type: 'crop_management',
              namespaces: ['crop_management'],
              required_tools: [],
            },
            coverage_checklist: ['ask for date'],
            retrieved_docs: [],
            graph_hits: [],
            tool_invocations: [],
          },
        },
      })
    },
    'POST /api/feedback': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      return mkOk({ status: 'ok', feedback: body })
    },
    'POST /api/exports': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      return mkOk({
        export_id: 'exp_1',
        manifest: {
          export_id: 'exp_1',
          created_at: new Date().toISOString(),
          redaction_mode: body.redaction_mode,
          training_eligible: false,
          files: [{ file: 'session.json', checksum: 'abc' }],
          checksums: { session: 'abc', 'session.json': 'abc' },
        },
        files: { 'session.json': '/tmp/session.json' },
      })
    },
    'POST /api/replay': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const topK = body.top_k
      const maxTokens = body.max_tokens
      return mkOk({
        turn_id: 'turn_3',
        turn: {
          turn_id: 'turn_3',
          parent_turn_id: body.base_turn_id,
          user_message: 'replayed question',
          answer: 'replayed answer',
          answer_status: 'draft',
          trace: {
            route: {
              risk_level: 'medium',
              question_type: 'fertility',
              namespaces: ['fertility'],
              required_tools: [],
            },
            coverage_checklist: [],
            retrieved_docs: [],
            graph_hits: [],
            tool_invocations: [],
          },
        },
        base_turn: {
          turn_id: body.base_turn_id,
          user_message: 'source turn',
          answer: 'source answer',
          answer_status: 'draft',
        },
        config_delta: {
          pipeline: body.pipeline || 'full',
          mode: {
            base: 'mock',
            replay: body.mode || 'mock',
          },
          ...(typeof topK === 'number' ? { top_k: topK } : {}),
          max_tokens: maxTokens ?? 280,
        },
        pipeline: body.pipeline || 'full',
      })
    },
    'POST /api/reflections': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      return mkOk({ status: 'ok', reflection: body })
    },
    'POST /api/tools/route': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      return mkOk({ output: 'ok', payload: body })
    },
    'POST /api/sessions/sess_1/tools': async () => mkOk({ output: 'unsupported' }),
    'PATCH /api/sessions/sess_1': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      Object.assign(sessionRecord, body)
      if (body.context) {
        sessionRecord.context = { ...sessionRecord.context, ...body.context }
      }
      if (Object.prototype.hasOwnProperty.call(body, 'status')) {
        sessionRecord.status = body.status
      }
      if (Object.prototype.hasOwnProperty.call(body, 'archived')) {
        sessionRecord.archived = body.archived
      }
      return mkOk(sessionRecord)
    },
    'POST /api/sessions/sess_1/turns/stream': async () =>
      mkSse(
        [
          'event: generation.token\ndata: {"token":"Streaming "}\n',
          '\nevent: generation.token\ndata: {"token":"answer"}\n\n',
          'event: answer.completed\ndata: {"turn_id":"turn_2","turn":{"turn_id":"turn_2","answer":"Streaming answer"}}\n\n',
        ].join('\n'),
      ),
    'GET /api/sessions/sess_1/events': async () =>
      mkSse(
        [
          'event: turn.started\nid: 1\ndata: {"turn_id":"turn_1","message_len":12}\n\n',
          'event: answer.completed\nid: 2\ndata: {"turn_id":"turn_1"}\n\n',
        ].join(''),
      ),
    'GET /api/sessions/sess_1/events?block_ms=0': async () =>
      mkSse(
        [
          'event: turn.started\nid: 1\ndata: {"turn_id":"turn_1","message_len":12}\n\n',
          'event: answer.completed\nid: 2\ndata: {"turn_id":"turn_1"}\n\n',
        ].join(''),
      ),
    'GET /auth/me': async () =>
      hostedAccountDeleted
        ? mkFail(403, 'user is not active')
        : mkOk({
        user: {
          id: 'user_1',
          email: 'advisor@example.test',
          display_name: 'Hosted Advisor',
          account_consent: hostedAccountConsent,
        },
        account_consent: hostedAccountConsent,
        organizations: [hostedOrg],
        workspaces: hostedWorkspaceDeleted ? [] : [hostedWorkspace],
      }),
    'GET /account/consent': async () =>
      mkOk({
        schema_version: 'phase6.account_consent_response.v1',
        consent: hostedAccountConsent,
      }),
    'PATCH /account/consent': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      if (body.confirm_email !== 'advisor@example.test') {
        return mkFail(400, 'email confirmation does not match current account')
      }
      hostedAccountConsent = {
        ...hostedAccountConsent,
        trace_storage_enabled: Boolean(body.trace_storage_enabled),
        feedback_use_allowed: Boolean(body.feedback_use_allowed),
        training_candidate_allowed: Boolean(body.training_candidate_allowed),
        public_anonymized_examples_allowed: Boolean(body.public_anonymized_examples_allowed),
        product_updates_allowed: Boolean(body.product_updates_allowed),
        retention_preference: body.retention_preference || hostedAccountConsent.retention_preference,
        updated_at: '2026-01-01T00:10:00+00:00',
      }
      return mkOk({
        schema_version: 'phase6.account_consent_response.v1',
        consent: hostedAccountConsent,
      })
    },
    'GET /account/export': async () =>
      mkOk({
        schema_version: 'phase6.account_data_export.v1',
        created_at: new Date().toISOString(),
        account_consent: hostedAccountConsent,
        organizations: [hostedOrg],
        workspaces: [
          {
            workspace: hostedWorkspace,
            threads: hostedThread ? [hostedThread] : [],
            attachments,
            exports: hostedExports,
          },
        ],
        data_policy: { object_store_bytes_included: false, embedding_vectors_included: false },
      }),
    'GET /auth/sessions': async () =>
      mkOk({
        schema_version: 'phase6.auth_sessions.v1',
        sessions: [{ ...hostedAuthSession, revoked_at: hostedSessionsRevoked ? '2026-01-01T00:10:00+00:00' : null }],
      }),
    'POST /auth/sessions/revoke-all': async () => {
      hostedSessionsRevoked = true
      return mkOk({
        schema_version: 'phase6.auth_sessions_revoked.v1',
        revoked_at: '2026-01-01T00:10:00+00:00',
        revoked_count: 1,
      })
    },
    'POST /auth/signup': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      return {
        ...mkOk({
          schema_version: 'phase6.password_signup.v1',
          status: 'verification_required',
          email: String(body.email || '').toLowerCase(),
          dev_delivery: { token: hostedVerificationToken, delivery: 'local_dev_response_only' },
        }),
        status: 201,
      }
    },
    'POST /auth/verify-email': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      if (body.token !== hostedVerificationToken) {
        return mkFail(400, 'email verification token is invalid or expired')
      }
      hostedPasswordVerified = true
      return mkOk({
        schema_version: 'phase6.email_verification.v1',
        status: 'verified',
        user: { id: 'user_password', email: 'new-advisor@example.test', display_name: 'New Advisor' },
      })
    },
    'POST /auth/password-login': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      if (!hostedPasswordVerified || hostedPasswordReset || body.password !== 'long enough demo password') {
        return mkFail(401, 'invalid email or password')
      }
      return mkOk({
        schema_version: 'phase6.password_login.v1',
        user: { id: 'user_password', email: String(body.email || '').toLowerCase(), display_name: 'New Advisor' },
        csrf_token: 'csrf-from-password-login',
      })
    },
    'POST /auth/password-reset/request': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const known = String(body.email || '').toLowerCase() === 'new-advisor@example.test'
      return {
        ...mkOk({
          schema_version: 'phase6.password_reset_requested.v1',
          status: 'accepted',
          message: 'If this account exists and is verified, a password reset email will be sent.',
          ...(known ? { dev_delivery: { token: hostedResetToken, delivery: 'local_dev_response_only' } } : {}),
        }),
        status: 202,
      }
    },
    'POST /auth/password-reset/confirm': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      if (body.token !== hostedResetToken) {
        return mkFail(400, 'password reset token is invalid or expired')
      }
      hostedPasswordReset = true
      hostedSessionsRevoked = true
      return mkOk({
        schema_version: 'phase6.password_reset_confirmed.v1',
        status: 'password_reset',
        sessions_revoked: true,
      })
    },
    'DELETE /account': async () => {
      hostedAccountDeleted = true
      return mkOk({
        schema_version: 'phase6.account_delete.v1',
        user: { id: 'user_1', email: 'advisor@example.test', display_name: 'Hosted Advisor', status: 'deleted' },
        workspace_count: hostedWorkspaceDeleted ? 0 : 1,
        memberships_inactivated: true,
      })
    },
    'POST /orgs': async () => mkOk(hostedOrg),
    'POST /orgs/org_1/invites': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      return {
        ...mkOk({
          schema_version: 'phase6.workspace_invite.v1',
          invite_token: 'invite.token.signature',
          invite_url: 'http://localhost:8000/invite?token=invite.token.signature',
          organization_id: hostedOrg.id,
          email: String(body.email || '').toLowerCase(),
          role: body.role || 'viewer',
          expires_at: '2026-01-04T00:00:00+00:00',
        }),
        status: 201,
      }
    },
    'POST /orgs/invites/accept': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      if (body.token !== 'invite.token.signature') {
        return mkFail(400, 'invite token is invalid')
      }
      return mkOk({
        schema_version: 'phase6.workspace_invite.v1',
        accepted: true,
        organization: { ...hostedOrg, role: 'viewer' },
        membership: {
          organization_id: hostedOrg.id,
          user_id: 'user_2',
          role: 'viewer',
        },
        expires_at: '2026-01-04T00:00:00+00:00',
      })
    },
    'POST /workspaces': async () => mkOk(hostedWorkspace),
    'DELETE /workspaces/workspace_1': async () => {
      hostedWorkspaceDeleted = true
      auditEvents.unshift({
        id: 'audit_workspace_deleted',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'workspace.deleted',
        target_type: 'workspace',
        target_id: hostedWorkspace.id,
        payload: { thread_count: 1, soft_deleted: true },
        created_at: new Date().toISOString(),
      })
      return mkOk({ ...hostedWorkspace, deleted_at: new Date().toISOString(), deletion_summary: { thread_count: 1, soft_deleted: true } })
    },
    'POST /field-contexts': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const created = {
        ...hostedFieldContext,
        ...body,
        id: 'field_context_1',
        workspace_id: hostedWorkspace.id,
        quality_meter: hostedFieldContext.quality_meter,
      }
      fieldContexts.splice(0, fieldContexts.length, created)
      return mkOk(created)
    },
    'PATCH /field-contexts/field_context_1': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      fieldContexts[0] = { ...fieldContexts[0], ...body }
      auditEvents.unshift({
        id: 'audit_field_context_updated',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'field_context.updated',
        target_type: 'field_context',
        target_id: 'field_context_1',
        payload: { updated_fields: Object.keys(body).sort() },
        created_at: new Date().toISOString(),
      })
      return mkOk(fieldContexts[0])
    },
    'DELETE /field-contexts/field_context_1': async () => {
      const deleted = { ...fieldContexts[0], deleted_at: new Date().toISOString() }
      fieldContexts.splice(0, fieldContexts.length)
      auditEvents.unshift({
        id: 'audit_field_context_deleted',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'field_context.deleted',
        target_type: 'field_context',
        target_id: 'field_context_1',
        payload: { display_name: deleted.display_name },
        created_at: new Date().toISOString(),
      })
      return mkOk(deleted)
    },
    'GET /field-contexts?workspace_id=workspace_1': async () => mkOk(fieldContexts),
    'POST /geo/priors': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      return mkOk({
        workspace_id: hostedWorkspace.id,
        field_context_id: body.field_context_id || null,
        location_text: body.location_text,
        candidate_regions: [
          {
            label: 'Central Iowa and Minnesota Till Prairies',
            name: 'Central Iowa and Minnesota Till Prairies',
            layer: 'mlra_candidate',
            system: 'NRCS MLRA',
            code: 'MLRA_103',
            match_reason: 'Iowa or Des Moines Lobe text match',
            confidence: 0.74,
            priors: ['tile drainage common', 'corn-soy systems'],
            evidence_terms: ['iowa', 'des moines lobe'],
            source: 'local_rule_stub',
          },
        ],
        boosted_namespaces: ['fertility', 'regional_environment', 'soil_water'],
        evidence: ['string_match:iowa', 'string_match:des_moines_lobe'],
        missing_context: ['county', 'soil series or texture', 'drainage class'],
        uncertainty: 'medium',
        used_as_prior_only: true,
        not_field_specific_fact: true,
        disclaimer: 'Regional context used as prior, not field-specific fact.',
        ui_notice: 'Regional context used as prior, not field-specific fact.',
        recommended_followups: ['Confirm soil texture.'],
      })
    },
    'POST /threads': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      hostedThread.field_context_id = body.field_context_id || null
      return mkOk(hostedThread)
    },
    'GET /threads?workspace_id=workspace_1': async () => mkOk([hostedThread]),
    'GET /threads/thread_1': async () => mkOk(hostedThread),
    'PATCH /threads/thread_1': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      hostedThread.trace_capture_level = body.trace_capture_level || hostedThread.trace_capture_level
      hostedThread.training_eligible = Boolean(body.training_eligible)
      hostedTrace.privacy.trace_capture_level = hostedThread.trace_capture_level
      hostedTrace.privacy.training_eligible = hostedThread.training_eligible
      auditEvents.unshift({
        id: 'audit_training_consent',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'training_consent.updated',
        target_type: 'thread',
        target_id: hostedThread.id,
        payload: { changes: { training_eligible: { from: true, to: hostedThread.training_eligible } } },
        created_at: new Date().toISOString(),
      })
      return mkOk(hostedThread)
    },
    'DELETE /threads/thread_1': async () => {
      hostedThread.status = 'deleted'
      hostedThread.deleted_at = new Date().toISOString()
      hostedThread.training_eligible = false
      auditEvents.unshift({
        id: 'audit_thread_deleted',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'thread.deleted',
        target_type: 'thread',
        target_id: hostedThread.id,
        payload: { message_count: hostedThread.messages.length, training_eligible: false },
        created_at: new Date().toISOString(),
      })
      return mkOk(hostedThread)
    },
    'GET /threads/thread_1/trace': async () => mkOk(hostedTrace),
    'GET /attachments?workspace_id=workspace_1': async () => mkOk(attachments.filter((item) => !item.deleted_at)),
    'GET /attachments?workspace_id=workspace_1&include_deleted=true': async () => mkOk(attachments),
    'POST /attachments': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const created = body.content_type === 'image/png'
        ? {
            ...hostedAttachment,
            thread_id: body.thread_id || null,
            filename: body.filename,
            content_type: 'image/png',
            size_bytes: 68,
            modality: 'image',
            sensitivity: body.sensitivity || 'medium',
            parse_status: 'image_staged',
            metadata: {
              chunk_count: 0,
              private_rag_scope: 'workspace',
              retention_policy: body.retention_policy || 'delete_on_request',
              image: { width: 1, height: 1, quality_flags: ['image_processor_not_configured', 'low_resolution_image'] },
            },
            deleted_at: null,
          }
        : {
            ...hostedAttachment,
            thread_id: body.thread_id || null,
            sensitivity: body.sensitivity || 'high',
            metadata: {
              ...hostedAttachment.metadata,
              retention_policy: body.retention_policy || 'delete_on_request',
            },
            deleted_at: null,
          }
      attachments.splice(0, attachments.length, created)
      auditEvents.unshift({
        id: 'audit_attachment_created',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'attachment.created',
        target_type: 'attachment',
        target_id: created.id,
        payload: { filename: created.filename, chunk_count: created.metadata.chunk_count },
        created_at: new Date().toISOString(),
      })
      hostedTrace.events.push({
        event_id: 'evt_attachment_upload',
        event_type: 'attachment_event',
        actor: 'user',
        payload: { attachment_id: created.id, parse_status: created.parse_status },
        created_at: new Date().toISOString(),
      })
      return mkOk(created)
    },
    'DELETE /attachments/attachment_1': async () => {
      const deleted = attachments[0] ? { ...attachments[0], deleted_at: new Date().toISOString(), parse_status: 'deleted' } : { ...hostedAttachment, deleted_at: new Date().toISOString(), parse_status: 'deleted' }
      attachments.splice(0, attachments.length, deleted)
      auditEvents.unshift({
        id: 'audit_attachment_deleted',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'attachment.deleted',
        target_type: 'attachment',
        target_id: deleted.id,
        payload: { filename: deleted.filename, derived_chunks_tombstoned: true },
        created_at: new Date().toISOString(),
      })
      hostedTrace.events.push({
        event_id: 'evt_attachment_delete',
        event_type: 'attachment_event',
        actor: 'user',
        payload: { attachment_id: deleted.id, deleted: true },
        created_at: new Date().toISOString(),
      })
      return mkOk(deleted)
    },
    'POST /chat/stream': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      hostedThread.messages = [
        {
          id: 'msg_u1',
          thread_id: hostedThread.id,
          actor: 'user',
          content: body.message,
          metadata: {},
        },
        {
          id: 'msg_a1',
          thread_id: hostedThread.id,
          actor: 'assistant',
          content: 'Hosted mock answer with water-quality caution.',
          metadata: { legacy_turn_id: 'turn_hosted_1' },
        },
      ]
      hostedTrace.events = [
        { event_id: 'evt_1', event_type: 'user_message', actor: 'user', payload: {}, created_at: new Date().toISOString() },
        { event_id: 'evt_2', event_type: 'route_result', actor: 'system', payload: { risk_level: 'medium' }, created_at: new Date().toISOString() },
        {
          event_id: 'evt_3',
          event_type: 'retrieval_result',
          actor: 'system',
          payload: {
            doc_count: Array.isArray(body.attachment_ids) && body.attachment_ids.length > 0 ? 2 : 1,
            private_doc_count: Array.isArray(body.attachment_ids) && body.attachment_ids.length > 0 ? 1 : 0,
            retrieved_docs: Array.isArray(body.attachment_ids) && body.attachment_ids.length > 0
              ? [{ source_type: 'user_upload_private', attachment_id: body.attachment_ids[0], snippet: 'Private phosphorus note' }]
              : [{ doc_id: 'doc_phase5_1', title: 'Phosphorus runoff', source_type: 'applied_guidance', source: 'seed', score: 0.81 }],
          },
          created_at: new Date().toISOString(),
        },
        { event_id: 'evt_4', event_type: 'assistant_answer', actor: 'assistant', payload: {}, created_at: new Date().toISOString() },
        ...(Array.isArray(body.attachment_ids) && body.attachment_ids.length > 0
          ? [{
              event_id: 'evt_attachment_chat',
              event_type: 'attachment_event',
              actor: 'user',
              payload: { attachment_id: body.attachment_ids[0], chunk_count: 1 },
              created_at: new Date().toISOString(),
            }]
          : []),
      ]
      return mkSse(
        [
          'event: route.completed\ndata: {"risk_level":"medium","question_type":"fertility_diagnostic"}\n\n',
          'event: retrieval.completed\ndata: {"doc_count":1}\n\n',
          'event: model.delta\ndata: {"text":"Hosted mock answer"}\n\n',
          'event: model.completed\ndata: {"thread_id":"thread_1","message_id":"msg_a1"}\n\n',
          'event: trace.persisted\ndata: {"thread_id":"thread_1","event_count":4,"phase5_trace_id":"phase5-trace-1"}\n\n',
        ].join(''),
      )
    },
    'GET /api/admin/traces/phase5-trace-1': async () =>
      mkOk({
        trace_id: 'phase5-trace-1',
        metrics: {
          trace_id: 'phase5-trace-1',
          thread_id: 'thread_1',
          turn_id: 'msg_a1',
          workspace_id: 'workspace_1',
          route_question_type: 'fertility_diagnostic',
          risk_level: 'medium',
          context_packer_version: 'phase5_context_packer_v1',
          model_id: 'mock',
          total_latency_ms: 42.2,
          retrieval_doc_count: 1,
          leak_check_passed: true,
          answer_word_count: 6,
          quality_flags: [],
        },
        spans: [
          { trace_id: 'phase5-trace-1', span_id: 'span_1', stage: 'agent.rag.lexical_search', duration_ms: 2.1, status: 'ok', cache_status: 'miss' },
        ],
        prompt_leak_events: [],
      }),
    'POST /messages/msg_a1/feedback': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const candidate = {
        id: 'eval_candidate_1',
        workspace_id: hostedWorkspace.id,
        thread_id: hostedThread.id,
        message_id: 'msg_a1',
        target_component: 'eval',
        payload: { feedback: body },
        review_status: 'pending',
      }
      evalCandidates.splice(0, evalCandidates.length, candidate)
      hostedTrace.events.push({
        event_id: 'evt_feedback',
        event_type: 'user_feedback',
        actor: 'user',
        payload: body,
        created_at: new Date().toISOString(),
      })
      hostedTrace.events.push({
        event_id: 'evt_eval',
        event_type: 'eval_candidate',
        actor: 'system',
        payload: candidate,
        created_at: new Date().toISOString(),
      })
      return mkOk({ id: 'feedback_1', ...body })
    },
    'GET /eval-candidates?workspace_id=workspace_1': async () => mkOk(evalCandidates),
    'GET /eval-candidates?workspace_id=workspace_1&review_status=pending': async () =>
      mkOk(evalCandidates.filter((item) => item.review_status === 'pending')),
    'GET /eval-candidates?workspace_id=workspace_1&review_status=approved_for_suite': async () =>
      mkOk(evalCandidates.filter((item) => item.review_status === 'approved_for_suite')),
    'GET /eval-candidates?workspace_id=workspace_1&review_status=rejected': async () =>
      mkOk(evalCandidates.filter((item) => item.review_status === 'rejected')),
    'GET /eval-candidates?workspace_id=workspace_1&review_status=retired': async () =>
      mkOk(evalCandidates.filter((item) => item.review_status === 'retired')),
    'POST /eval-candidates/eval_candidate_1/review': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const current = evalCandidates[0]
      if (!current) {
        return mkFail(404, 'candidate not found')
      }
      evalCandidates[0] = { ...current, review_status: body.review_status || 'approved_for_suite' }
      hostedTrace.events.push({
        event_id: 'evt_eval_review',
        event_type: 'eval_candidate',
        actor: 'reviewer',
        payload: evalCandidates[0],
        created_at: new Date().toISOString(),
      })
      return mkOk(evalCandidates[0])
    },
    'POST /eval-runs': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const run = {
        id: 'eval_run_1',
        workspace_id: hostedWorkspace.id,
        name: body.name || 'Hosted feedback replay',
        status: 'completed',
        created_at: '2026-05-30T12:00:00.000Z',
        candidate_ids: evalCandidates.filter((item) => item.review_status === 'approved_for_suite').map((item) => item.id),
        metrics: {
          candidate_count: 1,
          approved_count: 1,
          reviewed_count: 1,
          ideal_answer_count: 1,
          human_correction_count: 1,
          training_consent_count: 1,
          failure_case_count: 1,
          pass_count: 0,
          pass_rate: 0,
          target_component_counts: { eval: 1 },
          failure_tag_counts: { missed_local_calibration: 1 },
          regression_failures: [
            {
              candidate_id: 'eval_candidate_1',
              target_component: 'eval',
              failure_tags: ['missed_local_calibration'],
              has_ideal_answer: true,
              has_human_correction: true,
            },
          ],
        },
        gates: { promotion_allowed: false, reasons: ['regression_failures_present'] },
      }
      const previousRun = {
        id: 'eval_run_previous',
        workspace_id: hostedWorkspace.id,
        name: 'Previous hosted replay',
        status: 'completed',
        created_at: '2026-05-29T12:00:00.000Z',
        candidate_ids: ['eval_candidate_previous'],
        metrics: {
          candidate_count: 1,
          reviewed_count: 1,
          failure_case_count: 0,
          pass_rate: 1,
        },
        gates: { promotion_allowed: true, reasons: [] },
      }
      evalRuns.splice(0, evalRuns.length, run, previousRun)
      return mkOk(run)
    },
    'GET /eval-runs?workspace_id=workspace_1': async () => mkOk(evalRuns),
    'GET /change-proposals?workspace_id=workspace_1': async () => mkOk(changeProposals),
    'POST /change-proposals': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const proposal = {
        id: 'change_proposal_1',
        workspace_id: hostedWorkspace.id,
        title: body.title,
        target_component: body.target_component,
        proposal_type: body.proposal_type,
        summary: body.summary,
        linked_eval_run_id: body.linked_eval_run_id,
        review_status: 'candidate',
        gates: { reviewed_eval_run: Boolean(body.linked_eval_run_id), promotion_allowed: false },
        metadata: {},
      }
      changeProposals.splice(0, changeProposals.length, proposal)
      auditEvents.unshift({
        id: 'audit_change_proposal_created',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'change_proposal.created',
        target_type: 'change_proposal',
        target_id: proposal.id,
        payload: { title: proposal.title, proposal_type: proposal.proposal_type },
        created_at: new Date().toISOString(),
      })
      return mkOk(proposal)
    },
    'POST /change-proposals/change_proposal_1/review': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const current = changeProposals[0]
      if (!current) {
        return mkFail(404, 'change proposal not found')
      }
      changeProposals[0] = { ...current, review_status: body.review_status || 'needs_eval', metadata: { review_notes: body.notes } }
      auditEvents.unshift({
        id: 'audit_change_proposal_reviewed',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'change_proposal.reviewed',
        target_type: 'change_proposal',
        target_id: current.id,
        payload: { review_status: changeProposals[0].review_status },
        created_at: new Date().toISOString(),
      })
      return mkOk(changeProposals[0])
    },
    'GET /exports?workspace_id=workspace_1&limit=25&thread_id=thread_1': async () => mkOk(hostedExports),
    'GET /exports?workspace_id=workspace_1&limit=25': async () => mkOk(hostedExports),
    'GET /exports?workspace_id=workspace_1&limit=1&thread_id=thread_1&export_type=json': async () => mkOk(hostedExports.slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=1&export_type=json': async () => mkOk(hostedExports.slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=1&export_type=zip': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'zip').slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=1&export_type=csv': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'csv').slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=1&thread_id=thread_1&export_type=field_context_brief': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'field_context_brief').slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=25&thread_id=thread_1&export_type=thread_report': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'thread_report')),
    'GET /exports?workspace_id=workspace_1&limit=1&export_type=field_context_brief': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'field_context_brief').slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=1&export_type=source_evidence_bundle': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'source_evidence_bundle').slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=1&export_type=diagnostic_checklist': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'diagnostic_checklist').slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=1&export_type=learning_trace_export': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'learning_trace_export').slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=1&export_type=data_source_audit': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'data_source_audit').slice(0, 1)),
    'GET /exports?workspace_id=workspace_1&limit=1&export_type=demo_eval_snapshot': async () =>
      mkOk(hostedExports.filter((item) => item.export_type === 'demo_eval_snapshot').slice(0, 1)),
    'GET /export-jobs?workspace_id=workspace_1&limit=25&thread_id=thread_1': async () => mkOk(hostedExportJobs),
    'GET /export-jobs?workspace_id=workspace_1&limit=25': async () => mkOk(hostedExportJobs),
    'GET /export-jobs?workspace_id=workspace_1&limit=1&thread_id=thread_1': async () => mkOk(hostedExportJobs.slice(0, 1)),
    'GET /export-jobs?workspace_id=workspace_1&limit=1': async () => mkOk(hostedExportJobs.slice(0, 1)),
    'POST /threads/thread_1/exports': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const exportType = body.export_type || 'json'
      const exportIndex = hostedExports.length + 1
      const exportId = `export_${exportIndex}`
      const jobId = `export_job_${exportIndex}`
      hostedExports.unshift({
        id: exportId,
        workspace_id: hostedWorkspace.id,
        thread_id: hostedThread.id,
        export_type: exportType,
        object_store_uris_included: false,
        redaction_status: 'not_required',
        sha256: 'abcdef123456',
        metadata: {
          files:
            exportType === 'zip'
              ? {
                  'thread_trace.json': '/tmp/thread_trace.json',
                  'thread.md': '/tmp/thread.md',
                  'thread_messages.csv': '/tmp/thread_messages.csv',
                  'thread_events.csv': '/tmp/thread_events.csv',
                  'thread_bundle.zip': '/tmp/thread_bundle.zip',
                }
              : exportType === 'csv'
                ? {
                    'thread_trace.json': '/tmp/thread_trace.json',
                    'thread.md': '/tmp/thread.md',
                    'thread_messages.csv': '/tmp/thread_messages.csv',
                    'thread_events.csv': '/tmp/thread_events.csv',
                  }
                : exportType === 'field_context_brief'
                  ? {
                      'phase6_report_manifest.json': '/tmp/phase6_report_manifest.json',
                      'field_context_brief.md': '/tmp/field_context_brief.md',
                      'field_context_brief.pdf': '/tmp/field_context_brief.pdf',
                    }
                  : exportType === 'source_evidence_bundle'
                    ? {
                        'phase6_report_manifest.json': '/tmp/phase6_report_manifest.json',
                        'source_evidence_bundle.json': '/tmp/source_evidence_bundle.json',
                        'source_evidence_bundle.csv': '/tmp/source_evidence_bundle.csv',
                        'source_evidence_bundle.md': '/tmp/source_evidence_bundle.md',
                      }
                    : exportType === 'diagnostic_checklist'
                      ? {
                          'phase6_report_manifest.json': '/tmp/phase6_report_manifest.json',
                          'diagnostic_checklist.csv': '/tmp/diagnostic_checklist.csv',
                          'diagnostic_checklist.md': '/tmp/diagnostic_checklist.md',
                          'diagnostic_checklist.pdf': '/tmp/diagnostic_checklist.pdf',
                        }
                    : exportType === 'learning_trace_export'
                      ? {
                          'phase6_report_manifest.json': '/tmp/phase6_report_manifest.json',
                          'learning_trace_export.jsonl': '/tmp/learning_trace_export.jsonl',
                        }
                    : exportType === 'data_source_audit'
                      ? {
                          'phase6_report_manifest.json': '/tmp/phase6_report_manifest.json',
                          'data_source_audit.csv': '/tmp/data_source_audit.csv',
                          'data_source_audit.pdf': '/tmp/data_source_audit.pdf',
                        }
                    : exportType === 'demo_eval_snapshot'
                      ? {
                          'phase6_report_manifest.json': '/tmp/phase6_report_manifest.json',
                          'demo_eval_snapshot.md': '/tmp/demo_eval_snapshot.md',
                          'demo_eval_snapshot.pdf': '/tmp/demo_eval_snapshot.pdf',
                        }
                : { 'thread_trace.json': '/tmp/thread_trace.json' },
        },
        created_at: new Date().toISOString(),
      })
      hostedExportJobs.unshift({
        id: jobId,
        workspace_id: hostedWorkspace.id,
        thread_id: hostedThread.id,
        export_type: exportType,
        redaction_status: 'not_required',
        status: 'completed',
        queue_name: 'exports',
        export_id: exportId,
        error_message: null,
        result: { export_id: exportId, sha256: hostedExports[0].sha256 },
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        finished_at: new Date().toISOString(),
      })
      auditEvents.unshift({
        id: `audit_export_created_${exportIndex}`,
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'export.created',
        target_type: 'export',
        target_id: exportId,
        payload: { export_type: exportType, thread_id: hostedThread.id },
        created_at: new Date().toISOString(),
      })
      hostedTrace.events.push({
        event_id: `evt_export_${exportIndex}`,
        event_type: 'export_event',
        actor: 'system',
        payload: { export_type: exportType },
        created_at: new Date().toISOString(),
      })
      return mkOk({ export: hostedExports[0], trace: hostedTrace })
    },
    'GET /audit-events?workspace_id=workspace_1&limit=25': async () => mkOk(auditEvents),
    'GET /admin/health?workspace_id=workspace_1': async () =>
      mkOk({
        status: 'ok',
        workspace_id: hostedWorkspace.id,
        storage: 'sqlite-local-dev',
        corpus_status: 'healthy',
      }),
    'GET /admin/metrics?workspace_id=workspace_1': async () =>
      mkOk({
        workspace_id: hostedWorkspace.id,
        organization_id: hostedOrg.id,
        usage: { thread_count: hostedThread ? 1 : 0, export_count: hostedExports.length },
        quota: { blocked: false },
      }),
    'GET /admin/monitoring?workspace_id=workspace_1': async () =>
      mkOk({
        workspace_id: hostedWorkspace.id,
        status: 'degraded',
        alert_count: 1,
        alerts: [
          {
            key: 'otel_exporter_not_configured',
            severity: 'info',
            message: 'OpenTelemetry export is disabled; local dashboards rely on admin endpoints and access logs.',
          },
        ],
      }),
    'GET /api/admin/latency?workspace_id=workspace_1': async () =>
      mkOk({
        workspace_id: 'workspace_1',
        schema_version: 'phase5.turn_metrics.v1',
        dashboard: { turn_count: 1, latency_ms: { p50: 42.2, p95: 42.2, max: 42.2 }, leak_failures: 0, cache: {} },
      }),
    'GET /api/admin/frontend-rum?workspace_id=workspace_1': async () =>
      mkOk({
        workspace_id: 'workspace_1',
        schema_version: 'phase6.frontend_rum_summary.v1',
        sample_count: 2,
        metrics: { LCP: { p75: 1800, budget_status: { status: 'pass' } } },
      }),
    'GET /api/admin/frontend-events?workspace_id=workspace_1': async () =>
      mkOk({
        workspace_id: 'workspace_1',
        schema_version: 'phase6.frontend_event_summary.v1',
        sample_count: 3,
        events: { message_submitted: { count: 1 } },
      }),
    'POST /api/rum': async () => mkOk({ accepted: true }),
    'POST /api/frontend-events': async () => mkOk({ accepted: true }),
    'GET /admin/audit-events?workspace_id=workspace_1&limit=10': async () => mkOk(auditEvents),
    'GET /quotas?workspace_id=workspace_1': async () =>
      mkOk({
        workspace_id: hostedWorkspace.id,
        quotas: {
          max_threads: 100,
          max_messages: 2000,
          max_attachments: 100,
          max_attachment_bytes: 50000000,
          max_data_sources: 100,
          max_eval_runs: 100,
          max_exports: 200,
        },
        usage: {
          thread_count: hostedThread ? 1 : 0,
          message_count: hostedThread.messages.length,
          attachment_count: attachments.filter((item) => !item.deleted_at).length,
          attachment_bytes: attachments.filter((item) => !item.deleted_at).reduce((total, item) => total + item.size_bytes, 0),
          data_source_count: dataSources.length,
          eval_run_count: evalRuns.length,
          export_count: hostedExports.length,
        },
        limits: [
          { quota: 'max_threads', usage_key: 'thread_count', used: hostedThread ? 1 : 0, limit: 100, remaining: 99, exceeded: false },
          { quota: 'max_exports', usage_key: 'export_count', used: hostedExports.length, limit: 200, remaining: 200 - hostedExports.length, exceeded: false },
        ],
        blocked: false,
      }),
    'GET /data-sources?workspace_id=workspace_1': async () => mkOk(dataSources),
    'POST /data-sources': async () => {
      dataSources.splice(0, dataSources.length, hostedDataSource)
      return mkOk(hostedDataSource)
    },
    'PATCH /data-sources/data_source_1': async (reqInit?: RequestInit) => {
      const body = JSON.parse(String(reqInit?.body || '{}'))
      const current = dataSources[0] || hostedDataSource
      const updated = {
        ...current,
        ...body,
        metadata: { ...(current.metadata || {}), ...(body.metadata || {}) },
      }
      dataSources.splice(0, dataSources.length, updated)
      auditEvents.unshift({
        id: 'audit_data_source_updated',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'data_source.updated',
        target_type: 'data_source',
        target_id: updated.id,
        payload: { updated_fields: Object.keys(body).sort() },
        created_at: new Date().toISOString(),
      })
      return mkOk(updated)
    },
    'DELETE /data-sources/data_source_1': async () => {
      const deleted = { ...(dataSources[0] || hostedDataSource), deleted_at: new Date().toISOString() }
      dataSources.splice(0, dataSources.length)
      auditEvents.unshift({
        id: 'audit_data_source_deleted',
        organization_id: hostedOrg.id,
        workspace_id: hostedWorkspace.id,
        actor_user_id: 'user_1',
        event_type: 'data_source.deleted',
        target_type: 'data_source',
        target_id: deleted.id,
        payload: { source_id: deleted.source_id, title: deleted.title },
        created_at: new Date().toISOString(),
      })
      return mkOk(deleted)
    },
    'GET /corpus-health?workspace_id=workspace_1': async () => {
      const latestJob = ingestJobs[0]
      const completed = latestJob?.status === 'completed'
      const failed = latestJob?.status === 'failed'
      const licenseReviewCount = dataSources.filter((item) => item.license_state === 'review_required').length
      return mkOk({
        workspace_id: hostedWorkspace.id,
        status: dataSources.length === 0 || failed ? 'blocked' : completed ? 'warning' : 'blocked',
        source_count: dataSources.length,
        rag_eligible_count: dataSources.filter((item) => item.rag_eligible).length,
        sft_eligible_count: dataSources.filter((item) => item.sft_eligible).length,
        ingest_job_count: ingestJobs.length,
        queued_ingest_count: ingestJobs.filter((item) => item.status === 'queued').length,
        failed_ingest_count: ingestJobs.filter((item) => item.status === 'failed').length,
        chunk_count: dataSources.length > 0 && completed ? 1 : 0,
        issue_counts: dataSources.length === 0
          ? { no_data_sources: 1 }
          : completed
            ? (licenseReviewCount ? { license_review_required: licenseReviewCount } : {})
          : {
              ...(licenseReviewCount ? { license_review_required: licenseReviewCount } : {}),
              ...(completed ? {} : { no_chunks_indexed: 1 }),
              ...(ingestJobs.length === 0 ? { missing_ingest_job: 1 } : failed ? { ingest_failed: 1 } : { ingest_queued: 1 }),
            },
        sources: dataSources.map((item) => ({
          data_source_id: item.id,
          source_id: item.source_id,
          title: item.title,
          license_state: item.license_state,
          rag_eligible: item.rag_eligible,
          sft_eligible: item.sft_eligible,
          source_kind: item.source_kind,
          chunk_count: completed ? 1 : 0,
          latest_ingest_status: latestJob?.status || 'not_started',
          latest_ingest_error: latestJob?.error_message || null,
          issue_flags: [
            ...(item.license_state === 'review_required' ? ['license_review_required'] : []),
            ...(ingestJobs.length === 0 ? ['missing_ingest_job'] : failed ? ['ingest_failed'] : completed ? [] : ['ingest_queued']),
            ...(completed ? [] : ['no_chunks_indexed']),
          ],
        })),
      })
    },
    'POST /data-sources/data_source_1/ingest': async () => {
      const job = {
        id: 'ingest_1',
        workspace_id: hostedWorkspace.id,
        data_source_id: hostedDataSource.id,
        status: 'queued',
        queue_name: 'ingest',
      }
      ingestJobs.splice(0, ingestJobs.length, job)
      return mkOk(job)
    },
    'GET /ingest-jobs?workspace_id=workspace_1': async () => mkOk(ingestJobs),
    'POST /ingest-jobs/ingest_1/run': async () => {
      const job = {
        id: 'ingest_1',
        workspace_id: hostedWorkspace.id,
        data_source_id: hostedDataSource.id,
        status: 'completed',
        queue_name: 'ingest',
        error_message: null,
        result: { chunk_count: 1, worker: 'local_inline' },
      }
      ingestJobs.splice(0, ingestJobs.length, job)
      return mkOk(job)
    },
    'POST /image-rag/query': async () =>
      mkOk({
        research_preview: true,
        not_a_diagnosis: true,
        image_quality_flags: ['image_processor_not_configured'],
        visible_observations: [
          {
            type: 'retrieval_context',
            text: 'Similar workspace images were found using local fingerprint metadata filters.',
          },
        ],
        ood_gate: {
          abstain: true,
          reasons: ['image_quality_too_low_for_observation'],
          method: 'local_quality_and_metadata_stub',
          requires_expert_review: true,
        },
      }),
    'POST /image-rag/evals': async () =>
      mkOk({
        workspace_id: hostedWorkspace.id,
        research_preview: true,
        not_for_diagnosis_or_treatment: true,
        metric_set: 'phase4.image_research_eval.v1',
        sample_count: 2,
        top_k: 1,
        retrieval: { query_count: 2, recall_at_k: 0.5, missing_relevance_labels: 0 },
        classification: { sample_count: 2, accuracy: 0.5, macro_f1: 0.3333 },
        calibration: { sample_count: 2, brier_score: 0.3013, expected_calibration_error: 0.325 },
        ood: { expected_ood_count: 1, abstention_count: 0, precision: 0, recall: 0 },
        safety: {
          unsafe_treatment_recommendation_rate: 0.5,
          unsafe_flags: [{ sample_id: 'demo_image_eval_unsafe', reason: 'treatment_or_product_language_without_guardrail' }],
        },
      }),
    ...overrides,
  }

  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method || 'GET').toUpperCase()
    const url = String(input)
    const key = `${method} ${url}`
    if (fetchMap[key]) {
      return fetchMap[key](init)
    }

    const normalizedKey = key.replace(/sess_[^/]+/g, 'sess_1')
    if (fetchMap[normalizedKey]) {
      return fetchMap[normalizedKey](init)
    }
    const hostedNormalizedKey = normalizedKey
      .replace(/thread_[^/?]+/g, 'thread_1')
      .replace(/msg_[^/?]+/g, 'msg_a1')
      .replace(/workspace_[^/?]+/g, 'workspace_1')
      .replace(/data_source_[^/?]+/g, 'data_source_1')
      .replace(/attachment_[^/?]+/g, 'attachment_1')
      .replace(/eval_candidate_[^/?]+/g, 'eval_candidate_1')
    if (fetchMap[hostedNormalizedKey]) {
      return fetchMap[hostedNormalizedKey](init)
    }

    return mkFail(404, `endpoint not mocked: ${key}`)
  })
}

describe('cockpit app', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  it('proxies hosted API routes used by the cockpit during local development', () => {
    const configText = readFileSync('vite.config.ts', 'utf8')

    for (const path of [
      '/auth',
      '/orgs',
      '/workspaces',
      '/field-contexts',
      '/geo',
      '/threads',
      '/chat',
      '/attachments',
      '/messages',
      '/eval-candidates',
      '/eval-runs',
      '/change-proposals',
      '/data-sources',
      '/ingest-jobs',
      '/corpus-health',
      '/quotas',
      '/audit-events',
      '/exports',
      '/export-jobs',
      '/image-rag',
      '/api',
    ]) {
      expect(configText, `${path} must proxy to the API server`).toContain(`'${path}'`)
    }
  })

  beforeEach(() => {
    Object.defineProperty(window, 'localStorage', { value: createTestStorage(), configurable: true })
    Object.defineProperty(window.navigator, 'onLine', { value: true, configurable: true })
    fetchMock = createBaseMock()
    global.fetch = fetchMock as unknown as typeof fetch
  })

  afterEach(() => {
    Object.defineProperty(window.navigator, 'onLine', { value: true, configurable: true })
    window.localStorage.removeItem(PHASE6_DEFERRED_ACTION_STORAGE_KEY)
    window.localStorage.removeItem(PHASE6_LOW_BANDWIDTH_STORAGE_KEY)
    window.localStorage.removeItem(PHASE6_CHAT_DRAFT_STORAGE_KEY)
    window.localStorage.removeItem(PHASE6_SCRATCHPAD_STORAGE_KEY)
    vi.clearAllMocks()
  })

  it('submits chat prompt and shows answer', async () => {
    render(<App />)

    const messageInput = await screen.findByTestId('chat-input')
    fireEvent.change(await screen.findByTestId('mode-select'), { target: { value: 'agronomic_rag' } })
    fireEvent.change(messageInput, { target: { value: 'How much nitrogen?' } })
    fireEvent.change(await screen.findByTestId('chat-model'), {
      target: { value: 'mlx-community/Qwen3.5-2B-8bit' },
    })
    fireEvent.change(await screen.findByTestId('chat-rag-config'), {
      target: { value: 'configs/rag.yaml' },
    })

    fireEvent.click(screen.getByTestId('send-turn'))

    await waitFor(() => {
      const lastCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/api/sessions/sess_1/turns'),
      )
      expect(lastCall?.[1]?.body).toBeDefined()
      const payload = JSON.parse(String(lastCall?.[1]?.body || '{}'))
      expect(payload).toMatchObject({
        model_id: 'mlx-community/Qwen3.5-2B-8bit',
        rag_config: 'configs/rag.yaml',
        mode: 'agronomic_rag',
      })
    })

    await waitFor(() => {
      expect(screen.getByText('Mocked answer response')).toBeInTheDocument()
    })
  })

  it('restores local chat draft and clears it after successful send', async () => {
    window.localStorage.setItem(
      PHASE6_CHAT_DRAFT_STORAGE_KEY,
      JSON.stringify({
        sess_1: {
          sessionId: 'sess_1',
          message: 'Draft question about salinity after irrigation',
          updatedAt: '2026-06-01T00:00:00.000Z',
        },
      }),
    )

    render(<App />)

    const messageInput = (await screen.findByTestId('chat-input')) as HTMLTextAreaElement
    await waitFor(() => expect(messageInput).toHaveValue('Draft question about salinity after irrigation'))

    fireEvent.change(messageInput, { target: { value: 'Updated draft about salinity after irrigation' } })
    expect(JSON.parse(window.localStorage.getItem(PHASE6_CHAT_DRAFT_STORAGE_KEY) || '{}').sess_1.message).toBe(
      'Updated draft about salinity after irrigation',
    )

    fireEvent.click(screen.getByTestId('send-turn'))

    await waitFor(() => {
      expect(window.localStorage.getItem(PHASE6_CHAT_DRAFT_STORAGE_KEY)).toBeNull()
      expect(screen.getByText('Mocked answer response')).toBeInTheDocument()
    })
  })

  it('keeps local field notes in an unsynced session scratchpad', async () => {
    window.localStorage.setItem(
      PHASE6_SCRATCHPAD_STORAGE_KEY,
      JSON.stringify({
        sess_1: {
          sessionId: 'sess_1',
          notes: 'Scouted west low spot; keep as local note.',
          updatedAt: '2026-06-01T00:00:00.000Z',
          syncState: 'local_only',
        },
      }),
    )

    render(<App />)

    expect(await screen.findByTestId('local-scratchpad-status')).toHaveTextContent('Local only')
    expect(screen.getByTestId('local-scratchpad-status')).toHaveTextContent('not synced')
    const scratchpad = (await screen.findByTestId('local-scratchpad-input')) as HTMLTextAreaElement
    await waitFor(() => expect(scratchpad).toHaveValue('Scouted west low spot; keep as local note.'))

    fireEvent.change(scratchpad, { target: { value: 'Updated local scouting note' } })
    const stored = JSON.parse(window.localStorage.getItem(PHASE6_SCRATCHPAD_STORAGE_KEY) || '{}')
    expect(stored.sess_1).toMatchObject({
      notes: 'Updated local scouting note',
      syncState: 'local_only',
    })

    fireEvent.click(screen.getByTestId('local-scratchpad-clear'))
    await waitFor(() => {
      expect(scratchpad).toHaveValue('')
      expect(window.localStorage.getItem(PHASE6_SCRATCHPAD_STORAGE_KEY)).toBeNull()
    })
  })

  it('appends new turn from turn endpoint response into visible turn list', async () => {
    render(<App />)

    const messageInput = await screen.findByTestId('chat-input')
    fireEvent.change(await screen.findByTestId('mode-select'), { target: { value: 'mock' } })
    fireEvent.change(messageInput, { target: { value: 'How much nitrogen today?' } })
    fireEvent.click(screen.getByTestId('send-turn'))

    await waitFor(() => {
      const turnList = screen.getByTestId('turn-list')
      const headings = within(turnList).getAllByRole('heading')
      expect(headings).toHaveLength(2)
      expect(headings[1]).toHaveTextContent('How much nitrogen today?')
      expect(screen.getByText('Mocked answer response')).toBeInTheDocument()
    })
  })

  it('renders risk badge from turn route', async () => {
    render(<App />)
    expect(await screen.findByTestId('risk-badge')).toHaveTextContent('medium')
  })

  it('renders evidence list from retrieved docs', async () => {
    render(<App />)
    expect(await screen.findByTestId('retrieved-doc-title-doc_1')).toHaveTextContent('Phosphorus runoff')
  })

  it('saves structured feedback payload', async () => {
    render(<App />)

    const tagSelect = await screen.findByTestId('failure-tag')
    fireEvent.change(tagSelect, { target: { value: 'wrong retrieval' } })
    const ratingInput = screen.getByTestId('feedback-rating')
    fireEvent.change(ratingInput, { target: { value: '4' } })
    const routeCorrect = screen.getByTestId('route-correct')
    fireEvent.change(routeCorrect, { target: { value: 'false' } })
    fireEvent.click(screen.getByTestId('save-feedback'))

    await waitFor(() => {
      const payloadCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/api/feedback') && init?.method === 'POST',
      )
      expect(payloadCall?.[1]?.body).toBeDefined()
    })
    const payload = JSON.parse(
      String(
        fetchMock.mock.calls.find(([url, init]) => String(url).includes('/api/feedback') && init?.method === 'POST')?.[1]
          ?.body || '{}',
      ),
    )
    expect(payload).toMatchObject({
      failure_tags: ['wrong retrieval'],
      accepted: false,
      route_correct: false,
      answer_status: 'reviewed',
      rating: 4,
    })
  })

  it('supports backend-parity feedback tags', async () => {
    render(<App />)

    fireEvent.change(await screen.findByTestId('failure-tag'), { target: { value: 'bad fertility calibration' } })
    const ratingInput = screen.getByTestId('feedback-rating')
    fireEvent.change(ratingInput, { target: { value: '2' } })
    fireEvent.click(screen.getByTestId('save-feedback'))

    await waitFor(() => {
      const payload = JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body || '{}'))
      expect(payload).toMatchObject({
        failure_tags: ['bad fertility calibration'],
        rating: 2,
      })
    })
  })

  it('creates export artifact with selected redaction mode', async () => {
    render(<App />)

    const exportMode = await screen.findByTestId('export-mode')
    fireEvent.change(exportMode, { target: { value: 'training_safe' } })
    fireEvent.click(screen.getByTestId('export-include-turns'))
    fireEvent.click(screen.getByTestId('export-include-artifacts'))
    const exportButton = await screen.findByTestId('create-export')
    fireEvent.click(exportButton)

    await waitFor(() => {
      const lastCall = fetchMock.mock.calls.find(([url, init]) => String(url).includes('/api/exports'))
      expect(lastCall?.[1]?.body).toBeDefined()
      const payload = JSON.parse(String(lastCall?.[1]?.body || '{}'))
      expect(payload).toMatchObject({
        redaction_mode: 'training_safe',
        include_turns: false,
        include_artifacts: false,
      })
      expect(lastCall).toHaveLength(2)
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/exports',
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  it('runs replay and sends base turn id', async () => {
    render(<App />)

    const replayButton = await screen.findByTestId('run-replay')
    fireEvent.change(await screen.findByTestId('replay-pipeline'), { target: { value: 'route_only' } })
    fireEvent.change(await screen.findByTestId('replay-top-k'), { target: { value: '4' } })
    fireEvent.click(replayButton)

    await waitFor(() => {
      const lastCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/api/replay'),
      )
      expect(lastCall?.[1]?.body).toBeDefined()
      const payload = JSON.parse(String(lastCall?.[1]?.body || '{}'))
      expect(payload).toMatchObject({
        base_turn_id: 'turn_1',
        pipeline: 'route_only',
        top_k: 4,
      })
    })

    expect(await screen.findByTestId('replay-delta')).toHaveTextContent('route_only')
    expect(await screen.findByTestId('replay-delta')).toHaveTextContent('"top_k": 4')
    expect(await screen.findByTestId('replay-delta')).toHaveTextContent('"max_tokens": 280')
  })

  it('saves reflection payload with structured fields', async () => {
    render(<App />)

    const observation = await screen.findByTestId('reflection-observation')
    const evidence = screen.getByTestId('reflection-evidence')
    const hypothesis = screen.getByTestId('reflection-hypothesis')
    const proposedRule = screen.getByTestId('reflection-rule')
    const component = screen.getByTestId('reflection-component')
    const confidence = screen.getByTestId('reflection-confidence')

    fireEvent.change(observation, { target: { value: 'route missed soil moisture' } })
    fireEvent.change(evidence, { target: { value: 'retrieved_doc:phosphorus_risk' } })
    fireEvent.change(hypothesis, { target: { value: 'water context missing' } })
    fireEvent.change(proposedRule, { target: { value: 'Always include water context when runoff risk is high' } })
    fireEvent.change(component, { target: { value: 'router' } })
    fireEvent.change(confidence, { target: { value: '0.84' } })

    fireEvent.click(screen.getByTestId('save-reflection'))

    await waitFor(() => {
      const lastCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/api/reflections'),
      )
      expect(lastCall?.[1]?.body).toBeDefined()
      const payload = JSON.parse(String(lastCall?.[1]?.body || '{}'))
      expect(payload).toMatchObject({
        observation: 'route missed soil moisture',
        evidence: ['retrieved_doc:phosphorus_risk'],
        failure_hypothesis: 'water context missing',
        proposed_rule: 'Always include water context when runoff risk is high',
        affected_component: 'router',
        confidence: 0.84,
      })
    })
  })

  it('updates session status and pinned context', async () => {
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Pause session' }))
    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/api/sessions/sess_1') && init?.method === 'PATCH',
      )
      expect(patchCall?.[1]?.body).toBeDefined()
      const payload = JSON.parse(String(patchCall?.[1]?.body || '{}'))
      expect(payload).toMatchObject({ status: 'paused' })
    })

    fireEvent.change(await screen.findByTestId('session-crop'), { target: { value: 'soy' } })
    fireEvent.change(screen.getByTestId('session-region'), { target: { value: 'Iowa' } })
    fireEvent.change(screen.getByTestId('session-jurisdiction'), { target: { value: 'US-IA' } })
    fireEvent.click(screen.getByText('Save context'))

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.filter(
        ([url, init]) => String(url).includes('/api/sessions/sess_1') && init?.method === 'PATCH',
      )
      const contextPayload = JSON.parse(String(patchCall.at(-1)?.[1]?.body || '{}'))
      expect(contextPayload).toMatchObject({
        context: {
          crop: 'soy',
          region: 'Iowa',
          jurisdiction: 'US-IA',
        },
      })
    })
  })

  it('runs a local tool', async () => {
    render(<App />)

    fireEvent.change(await screen.findByTestId('tool-name'), { target: { value: 'route' } })
    fireEvent.change(screen.getByTestId('tool-payload'), {
      target: { value: JSON.stringify({ question: 'What is the latest drought risk?' }) },
    })
    fireEvent.click(screen.getByTestId('run-tool'))

    await waitFor(() => {
      const toolCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/api/tools/route') && init?.method === 'POST',
      )
      expect(toolCall?.[1]?.body).toBeDefined()
    })
    expect(await screen.findByTestId('tool-output')).toBeInTheDocument()
  })

  it('streams turn answer when streaming checkbox is enabled', async () => {
    render(<App />)

    const streamingToggle = await screen.findByTestId('streaming-enabled')
    fireEvent.click(streamingToggle)

    fireEvent.change(await screen.findByTestId('mode-select'), { target: { value: 'mock' } })
    fireEvent.change(await screen.findByTestId('chat-input'), { target: { value: 'How to check runoff risk?' } })
    fireEvent.click(screen.getByTestId('send-turn'))

    await waitFor(() => {
      const streamingCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/turns/stream') && init?.method === 'POST',
      )
      expect(streamingCall).toBeDefined()
    })

    expect(await screen.findByTestId('streaming-answer')).toHaveTextContent('Streaming answer')
    expect(await screen.findByTestId('streaming-status')).toHaveTextContent('completed')
    expect(screen.getByTestId('cancel-streaming')).toBeDisabled()
  })

  it('cancels an in-flight streaming answer without recording a partial turn', async () => {
    fetchMock = createBaseMock({
      'POST /api/sessions/sess_1/turns/stream': async (reqInit?: RequestInit) =>
        new Promise<FetchResult>((_resolve, reject) => {
          reqInit?.signal?.addEventListener('abort', () => {
            const error = new Error('stream aborted')
            error.name = 'AbortError'
            reject(error)
          })
        }),
    })
    global.fetch = fetchMock as unknown as typeof fetch
    render(<App />)

    fireEvent.click(await screen.findByTestId('streaming-enabled'))
    fireEvent.change(await screen.findByTestId('chat-input'), { target: { value: 'How to check runoff risk?' } })
    fireEvent.click(screen.getByTestId('send-turn'))

    await waitFor(() => expect(screen.getByTestId('cancel-streaming')).not.toBeDisabled())
    expect(screen.getByTestId('streaming-status')).toHaveTextContent('streaming')
    fireEvent.click(screen.getByTestId('cancel-streaming'))

    expect(await screen.findByTestId('streaming-status')).toHaveTextContent('cancelled')
    expect(screen.getByTestId('streaming-answer')).toHaveTextContent('Generation cancelled')
    expect(screen.queryByTestId('status-turn_2')).toBeNull()
  })

  it('shows a stable streaming error state without recording a failed turn', async () => {
    fetchMock = createBaseMock({
      'POST /api/sessions/sess_1/turns/stream': async () => mkFail(503, 'model unavailable'),
    })
    global.fetch = fetchMock as unknown as typeof fetch
    render(<App />)

    fireEvent.click(await screen.findByTestId('streaming-enabled'))
    fireEvent.change(await screen.findByTestId('chat-input'), { target: { value: 'How to check runoff risk?' } })
    fireEvent.click(screen.getByTestId('send-turn'))

    expect(await screen.findByTestId('streaming-status')).toHaveTextContent('error')
    expect(screen.getByTestId('streaming-answer')).toHaveTextContent('Generation failed')
    expect(screen.getByRole('alert')).toHaveTextContent('503: model unavailable')
    expect(screen.getByTestId('cancel-streaming')).toBeDisabled()
    expect(screen.queryByTestId('status-turn_2')).toBeNull()
  })

  it('loads and parses session events stream', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('load-events'))

    expect(await screen.findByText(/turn.started/)).toBeInTheDocument()
  })

  it('compares latest turn against alternate mode via answer_only replay', async () => {
    render(<App />)

    const compareMode = await screen.findByTestId('compare-mode')
    fireEvent.change(compareMode, { target: { value: 'baseline' } })
    fireEvent.click(screen.getByTestId('compare-turn'))

    await waitFor(() => {
      const replayCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/api/replay') && init?.method === 'POST',
      )
      expect(replayCall?.[1]?.body).toBeDefined()
      const payload = JSON.parse(String(replayCall?.[1]?.body || '{}'))
      expect(payload.pipeline).toBe('answer_only')
      expect(payload.mode).toBe('baseline')
    })

    expect(await screen.findByTestId('comparison-result')).toBeInTheDocument()
  })

  it('saves structured feedback route labels and evidence feedback metadata', async () => {
    render(<App />)

    const turnTag = await screen.findByTestId('route-correction-wrong_route')
    fireEvent.click(turnTag)
    fireEvent.change(await screen.findByTestId('feedback-evidence-aspect'), { target: { value: 'missing' } })
    const ratingInput = screen.getByTestId('feedback-evidence')
    fireEvent.change(ratingInput, { target: { value: 'retrieved evidence is incomplete' } })
    fireEvent.click(screen.getByTestId('save-feedback'))

    await waitFor(() => {
      const payload = JSON.parse(String(fetchMock.mock.calls.at(-1)?.[1]?.body || '{}'))
      expect(payload).toMatchObject({
        route_correction_labels: ['wrong_route'],
        evidence_feedback: [{ aspect: 'missing', note: 'retrieved evidence is incomplete' }],
      })
    })
  })

  it('registers a data source and refreshes list', async () => {
    render(<App />)

    const sourceType = await screen.findByTestId('source-type')
    const sourcePath = screen.getByTestId('source-path')
    fireEvent.change(sourceType, { target: { value: 'file' } })
    fireEvent.change(sourcePath, { target: { value: '/tmp/new-source.txt' } })
    fireEvent.click(screen.getByTestId('register-source'))

    await waitFor(() => {
      const lastCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/api/data-sources') && init?.method === 'POST',
      )
      expect(lastCall?.[1]?.body).toBeDefined()
      const payload = JSON.parse(String(lastCall?.[1]?.body || '{}'))
      expect(payload).toMatchObject({ source_type: 'file', path: '/tmp/new-source.txt' })
    })

    fireEvent.click(await screen.findByTestId('load-sources'))
    expect(await screen.findByTestId('data-source-id-src_1')).toBeInTheDocument()
    expect(await screen.findByTestId('data-source-id-src_2')).toBeInTheDocument()
  })

  it('loads and lists registered data sources', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('load-sources'))

    expect(await screen.findByTestId('data-source-id-src_1')).toBeInTheDocument()
    expect(await screen.findByTestId('data-source-type-src_1')).toHaveTextContent('file')
  })

  it('runs the hosted account workspace thread chat flow', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    expect(await screen.findByTestId('hosted-user')).toHaveTextContent('advisor@example.test')

    fireEvent.click(screen.getByTestId('hosted-create-thread'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread created')
    })

    fireEvent.change(screen.getByTestId('hosted-message'), {
      target: { value: 'What should we check for high P runoff?' },
    })
    fireEvent.click(screen.getByTestId('hosted-send'))

    expect(await screen.findByTestId('hosted-answer')).toHaveTextContent('Hosted mock answer')
    expect(await screen.findByTestId('hosted-stream-events')).toHaveTextContent('route.completed')
    expect(await screen.findByTestId('hosted-stream-events')).toHaveTextContent('trace.persisted')
    expect(await screen.findByTestId('phase5-admin-trace')).toHaveTextContent('phase5_context_packer_v1')
    expect(await screen.findByTestId('hosted-evidence-panel')).toHaveTextContent('Phosphorus runoff')
    expect(await screen.findByTestId('hosted-trace')).toHaveTextContent('route_result')
    expect(await screen.findByTestId('hosted-trace')).toHaveTextContent('assistant_answer')

    const chatCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/chat/stream' && init?.method === 'POST')
    expect(chatCall?.[1]?.headers).toMatchObject({
      'X-Agronomy-User-Email': 'advisor@example.test',
    })
    expect(JSON.parse(String(chatCall?.[1]?.body || '{}'))).toMatchObject({
      workspace_id: 'workspace_1',
      thread_id: 'thread_1',
      model_profile_id: 'mock',
      trace_capture_level: 'research_opt_in',
      research_consent: true,
    })
  })

  it('keeps hostile answer and evidence markup inert in hosted launch surfaces', async () => {
    fetchMock = createBaseMock({
      'POST /chat/stream': async () =>
        mkSse('event: model.completed\ndata: {"thread_id":"thread_1","message_id":"msg_a1"}\n\n'),
      'GET /threads/thread_1': async () =>
        mkOk({
          id: 'thread_1',
          workspace_id: 'workspace_1',
          organization_id: 'org_1',
          field_context_id: null,
          title: 'Hosted phosphorus review',
          mode: 'agronomic_rag',
          trace_capture_level: 'research_opt_in',
          training_eligible: true,
          status: 'active',
          deleted_at: null,
          messages: [
            {
              id: 'msg_a1',
              thread_id: 'thread_1',
              actor: 'assistant',
              content: '<script>alert("x")</script><img src=x onerror=alert(1)> Keep this as text.',
              metadata: {},
            },
          ],
        }),
      'GET /threads/thread_1/trace': async () =>
        mkOk({
          schema_version: 'phase4.thread_trace.v1',
          workspace_id: 'workspace_1',
          organization_id: 'org_1',
          thread: { thread_id: 'thread_1', title: 'Hosted phosphorus review', mode: 'agronomic_rag' },
          privacy: { trace_capture_level: 'research_opt_in', training_eligible: true, redaction_status: 'not_required' },
          events: [
            {
              event_id: 'evt_malicious_retrieval',
              event_type: 'retrieval_result',
              actor: 'system',
              created_at: new Date().toISOString(),
              payload: {
                retrieved_docs: [
                  {
                    doc_id: 'doc_malicious',
                    title: '<svg onload=alert(1)>Source title</svg>',
                    source_type: '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
                    source: 'javascript:alert(1)',
                    score: 0.4,
                  },
                ],
              },
            },
          ],
        }),
    })
    global.fetch = fetchMock as unknown as typeof fetch
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => expect(screen.getByTestId('hosted-create-thread')).not.toBeDisabled())
    fireEvent.click(screen.getByTestId('hosted-create-thread'))
    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread created'))
    fireEvent.click(screen.getByTestId('hosted-send'))

    expect(await screen.findByTestId('hosted-answer')).toHaveTextContent('<script>alert("x")</script>')
    expect(await screen.findByTestId('hosted-evidence-panel')).toHaveTextContent('<svg onload=alert(1)>Source title</svg>')
    expect(document.querySelector('[data-testid="hosted-answer-panel"] script')).toBeNull()
    expect(document.querySelector('[data-testid="hosted-evidence-panel"] iframe')).toBeNull()
    expect(auditPhase6RenderingSecurity(document)).toEqual([])
  })

  it('shows admin operations only for owner or admin roles', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))

    expect(await screen.findByTestId('hosted-role-panel')).toHaveTextContent('Role: owner')
    expect(screen.getByTestId('hosted-admin-panel')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('hosted-load-admin-ops'))

    expect(await screen.findByTestId('hosted-admin-ops')).toHaveTextContent('Health: ok')
    expect(screen.getByTestId('hosted-admin-ops')).toHaveTextContent('storage sqlite-local-dev')
    expect(screen.getByTestId('hosted-admin-ops')).toHaveTextContent('Metrics workspace: workspace_1')
    expect(screen.getByTestId('hosted-admin-ops')).toHaveTextContent('Monitoring: degraded - alerts 1')
    expect(screen.getByTestId('hosted-phase5-latency')).toHaveTextContent('p95 42.2')
    expect(screen.getByTestId('hosted-frontend-rum')).toHaveTextContent('Frontend RUM samples: 2')
    expect(screen.getByTestId('hosted-frontend-events')).toHaveTextContent('Frontend event samples: 3')
    expect(screen.getByTestId('hosted-monitoring-alerts')).toHaveTextContent('otel_exporter_not_configured')
  })

  it('surfaces partial admin observability load failures', async () => {
    fetchMock = createBaseMock({
      'GET /api/admin/frontend-rum?workspace_id=workspace_1': async () => mkFail(503, 'RUM summary unavailable'),
    })
    global.fetch = fetchMock as unknown as typeof fetch
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    fireEvent.click(await screen.findByTestId('hosted-load-admin-ops'))

    expect(await screen.findByTestId('hosted-admin-ops')).toHaveTextContent('Health: ok')
    expect(screen.getByTestId('hosted-status')).toHaveTextContent('Admin operations loaded with 1 observability warning')
    expect(screen.getByTestId('hosted-admin-ops-failures')).toHaveTextContent('Frontend RUM: 503: RUM summary unavailable')
    expect(screen.getByTestId('hosted-phase5-latency')).toHaveTextContent('p95 42.2')
    expect(screen.getByTestId('hosted-frontend-events')).toHaveTextContent('Frontend event samples: 3')
    expect(screen.queryByTestId('hosted-frontend-rum')).not.toBeInTheDocument()
  })

  it('loads hosted account data export evidence', async () => {
    render(<App />)

    expect(await screen.findByTestId('hosted-export-account')).toBeDisabled()
    fireEvent.click(screen.getByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-user')).toHaveTextContent('advisor@example.test')
    })

    fireEvent.click(screen.getByTestId('hosted-export-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Account data export ready')
      expect(screen.getByTestId('hosted-account-export')).toHaveTextContent('phase6.account_data_export.v1')
      expect(screen.getByTestId('hosted-account-export')).toHaveTextContent('workspaces 1')
      expect(screen.getByTestId('hosted-account-export')).toHaveTextContent('threads 1')
    })
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/account/export')).toBe(true)
  })

  it('edits hosted account consent settings with email confirmation', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-account-consent-summary')).toHaveTextContent('retention default')
    })

    fireEvent.click(screen.getByTestId('hosted-consent-trace-storage'))
    fireEvent.click(screen.getByTestId('hosted-consent-feedback-use'))
    fireEvent.click(screen.getByTestId('hosted-consent-training'))
    fireEvent.change(screen.getByTestId('hosted-consent-retention'), { target: { value: 'short' } })
    fireEvent.click(screen.getByTestId('hosted-save-account-consent'))

    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Account consent saved')
      expect(screen.getByTestId('hosted-account-consent-summary')).toHaveTextContent('trace false')
      expect(screen.getByTestId('hosted-account-consent-summary')).toHaveTextContent('training true')
      expect(screen.getByTestId('hosted-account-consent-summary')).toHaveTextContent('retention short')
    })
    const consentCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/account/consent' && init?.method === 'PATCH')
    expect(consentCall).toBeTruthy()
    expect(JSON.parse(String(consentCall?.[1]?.body || '{}'))).toMatchObject({
      confirm_email: 'advisor@example.test',
      trace_storage_enabled: false,
      feedback_use_allowed: true,
      training_candidate_allowed: true,
      retention_preference: 'short',
    })
  })

  it('creates and accepts hosted workspace invite links', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-create-invite')).not.toBeDisabled()
    })

    fireEvent.change(screen.getByTestId('hosted-invite-email'), { target: { value: 'outsider@example.test' } })
    fireEvent.change(screen.getByTestId('hosted-invite-role'), { target: { value: 'viewer' } })
    fireEvent.click(screen.getByTestId('hosted-create-invite'))

    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Workspace invite created')
      expect(screen.getByTestId('hosted-invite-token')).toHaveValue('invite.token.signature')
      expect(screen.getByTestId('hosted-invite-evidence')).toHaveTextContent('viewer invite for outsider@example.test')
    })

    fireEvent.click(screen.getByTestId('hosted-accept-invite'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Workspace invite accepted')
      expect(screen.getByTestId('hosted-invite-evidence')).toHaveTextContent('Accepted viewer invite')
    })
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/orgs/org_1/invites' && init?.method === 'POST')).toBe(true)
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/orgs/invites/accept' && init?.method === 'POST')).toBe(true)
  })

  it('lists and revokes hosted auth sessions', async () => {
    render(<App />)

    expect(await screen.findByTestId('hosted-load-auth-sessions')).toBeDisabled()
    fireEvent.click(screen.getByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-user')).toHaveTextContent('advisor@example.test')
    })

    fireEvent.click(screen.getByTestId('hosted-load-auth-sessions'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-auth-sessions')).toHaveTextContent('phase6.auth_sessions.v1')
      expect(screen.getByTestId('hosted-auth-sessions')).toHaveTextContent('active 1')
      expect(screen.getByTestId('hosted-auth-sessions')).toHaveTextContent('11111111-1111-4111-8111-111111111111')
    })

    fireEvent.click(screen.getByTestId('hosted-revoke-auth-sessions'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Sessions revoked')
    })
    expect(screen.queryByTestId('hosted-user')).toBeNull()
    expect(screen.queryByTestId('hosted-auth-sessions')).toBeNull()
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/auth/sessions/revoke-all' && init?.method === 'POST')).toBe(true)
  })

  it('emits route-level Phase 6 performance marks without answer or email payloads', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => expect(screen.getByTestId('hosted-user')).toHaveTextContent('advisor@example.test'))

    fireEvent.click(screen.getByTestId('hosted-load-threads'))
    await waitFor(() => expect(screen.getByTestId('hosted-thread')).toBeInTheDocument())
    fireEvent.change(screen.getByTestId('hosted-thread'), { target: { value: 'thread_1' } })

    fireEvent.click(screen.getByTestId('hosted-send'))
    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Hosted chat completed'))
    fireEvent.click(screen.getByTestId('hosted-open-evidence'))

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'thread_report' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Export queued'))

    const rumPayloads = fetchMock.mock.calls
      .filter(([url]) => String(url) === '/api/rum')
      .map(([, init]) => JSON.parse(String(init?.body || '{}')))
    const metrics = rumPayloads.map((payload) => payload.metric_name)
    expect(metrics).toEqual(expect.arrayContaining(['render_time', 'open_time', 'first_visible_progress', 'open_interaction', 'standard_thread_report_preview']))
    for (const payload of rumPayloads) {
      expect(payload.metadata.budget_status).toMatchObject({ budgeted: true, launch_gate: 'blocker' })
      expect(JSON.stringify(payload)).not.toContain('advisor@example.test')
      expect(JSON.stringify(payload)).not.toContain('Hosted mock answer')
      expect(JSON.stringify(payload)).not.toContain('high soil-test phosphorus')
    }
    const eventPayloads = fetchMock.mock.calls
      .filter(([url]) => String(url) === '/api/frontend-events')
      .map(([, init]) => JSON.parse(String(init?.body || '{}')))
    const events = eventPayloads.map((payload) => payload.event_name)
    expect(events).toEqual(expect.arrayContaining([
      'message_submitted',
      'answer_stream_started',
      'answer_stream_first_token',
      'answer_stream_completed',
      'evidence_drawer_opened',
      'report_export_started',
      'report_export_completed',
    ]))
    for (const payload of eventPayloads) {
      expect(JSON.stringify(payload)).not.toContain('advisor@example.test')
      expect(JSON.stringify(payload)).not.toContain('Hosted mock answer')
      expect(JSON.stringify(payload)).not.toContain('high soil-test phosphorus')
      expect(JSON.stringify(payload.metadata)).not.toContain('message')
      expect(JSON.stringify(payload.metadata)).not.toContain('answer')
    }
  })

  it('runs the hosted password provider signup verify login and reset browser flow without local-dev identity headers', async () => {
    render(<App />)

    fireEvent.change(await screen.findByTestId('hosted-auth-provider'), { target: { value: 'password' } })
    expect(screen.getByTestId('hosted-password-auth')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('hosted-password-signup'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Password signup verification required')
      expect(screen.getByTestId('hosted-password-auth-evidence')).toHaveTextContent('phase6.password_signup.v1')
      expect(screen.getByTestId('hosted-verification-token')).toHaveValue('verify-token-123')
    })

    fireEvent.click(screen.getByTestId('hosted-password-verify'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Password email verified')
      expect(screen.getByTestId('hosted-user')).toHaveTextContent('new-advisor@example.test')
    })

    fireEvent.click(screen.getByTestId('hosted-password-login'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Password login complete')
      expect(screen.getByTestId('hosted-password-auth-evidence')).toHaveTextContent('phase6.password_login.v1 csrf true')
    })

    fireEvent.click(screen.getByTestId('hosted-reset-request'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Password reset requested')
      expect(screen.getByTestId('hosted-reset-token')).toHaveValue('reset-token-123')
    })

    fireEvent.click(screen.getByTestId('hosted-reset-confirm'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Password reset complete')
      expect(screen.getByTestId('hosted-password-auth-evidence')).toHaveTextContent('phase6.password_reset_confirmed.v1 password_reset revoked true')
    })
    expect(screen.queryByTestId('hosted-user')).toBeNull()

    for (const path of ['/auth/signup', '/auth/verify-email', '/auth/password-login', '/auth/password-reset/request', '/auth/password-reset/confirm']) {
      const call = fetchMock.mock.calls.find(([url]) => String(url) === path)
      expect(call, `${path} should be called`).toBeTruthy()
      expect(call?.[1]?.headers).not.toHaveProperty('X-Agronomy-User-Email')
      expect(call?.[1]?.headers).not.toHaveProperty('X-Agronomy-User-Name')
    }
  })

  it('keeps local preview behind the WebGPU feature flag by default', async () => {
    render(<App />)

    expect(await screen.findByTestId('hosted-local-preview')).toHaveTextContent('Local preview: disabled')
    expect(screen.getByTestId('hosted-local-preview')).toHaveTextContent('server_harness')
    expect(screen.getByTestId('hosted-local-preview')).toHaveTextContent('No browser model download starts from this probe')
    expect(screen.getByTestId('hosted-local-inference-matrix')).toHaveTextContent('No local model download')
    expect(screen.getByTestId('hosted-local-inference-matrix')).toHaveTextContent('Transformers.js')
    expect(screen.getByTestId('hosted-local-inference-matrix')).toHaveTextContent('WebLLM')
    expect(screen.getByTestId('hosted-local-inference-matrix')).toHaveTextContent('server_harness_required')
    expect(screen.getByTestId('hosted-probe-local-preview')).toBeDisabled()
  })

  it('renders public demo launch pages with caveated claims', async () => {
    render(<App />)

    expect(await screen.findByTestId('public-demo-pages')).toHaveTextContent('Landing')
    expect(screen.getByTestId('public-demo-pages')).toHaveTextContent('Data Source Coverage')
    expect(screen.getByTestId('public-demo-pages')).toHaveTextContent('Known Limitations')
    expect(screen.getByTestId('public-demo-pages')).toHaveTextContent('Privacy and Data Use')
    expect(screen.getByTestId('public-demo-pages')).toHaveTextContent('Feedback and Help')
    expect(screen.getByTestId('public-page-what-it-is-not')).toHaveTextContent('Not a certified agronomist')
    expect(screen.getByTestId('public-page-sample-reports')).toHaveTextContent('Demo eval snapshot')
    expect(screen.getByTestId('public-page-changelog-contribute')).toHaveTextContent('Incident runbook owners')
  })

  it('passes Phase 6 accessibility audit across primary launch flows', async () => {
    render(<App />)

    expect(await screen.findByTestId('chat-input')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('hosted-load-account'))
    await waitFor(() => expect(screen.getByTestId('hosted-user')).toHaveTextContent('advisor@example.test'))

    fireEvent.click(screen.getByTestId('hosted-create-thread'))
    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread created'))
    fireEvent.click(screen.getByTestId('hosted-send'))
    await waitFor(() => expect(screen.getByTestId('hosted-answer')).toHaveTextContent('Hosted mock answer'))
    fireEvent.click(screen.getByTestId('hosted-open-evidence'))

    fireEvent.click(screen.getByTestId('hosted-export-account'))
    await waitFor(() => expect(screen.getByTestId('hosted-account-export')).toHaveTextContent('phase6.account_data_export.v1'))
    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'thread_report' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Export queued'))

    fireEvent.click(screen.getByTestId('hosted-load-corpus-health'))
    await waitFor(() => expect(screen.getByTestId('hosted-corpus-health')).toHaveTextContent('Corpus health'))
    fireEvent.click(screen.getByTestId('hosted-load-admin-ops'))
    await waitFor(() => expect(screen.getByTestId('hosted-admin-ops')).toHaveTextContent('Health: ok'))

    const report = auditPhase6Accessibility(document)
    expect(report).toMatchObject({
      schemaVersion: 'phase6.frontend_accessibility_audit.v1',
      passed: true,
      violationCount: 0,
    })
    expect(report.violations).toEqual([])
  })

  it('passes Phase 6 responsive readiness audit for mobile and tablet launch flows', async () => {
    render(<App />)

    expect(screen.getByTestId('hosted-platform')).toBeInTheDocument()
    expect(await screen.findByTestId('chat-input')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('hosted-load-account'))
    await waitFor(() => expect(screen.getByTestId('hosted-user')).toHaveTextContent('advisor@example.test'))

    fireEvent.change(screen.getByTestId('hosted-sample-field-context'), { target: { value: 'prairie_canola_low_ph' } })
    fireEvent.click(screen.getByTestId('hosted-create-field-context'))
    await waitFor(() => expect(screen.getByTestId('hosted-field-context')).toHaveTextContent('Prairie canola low pH'))

    fireEvent.click(screen.getByTestId('hosted-create-thread'))
    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread created'))
    fireEvent.click(screen.getByTestId('hosted-send'))
    await waitFor(() => expect(screen.getByTestId('hosted-evidence-panel')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('hosted-open-evidence'))

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'thread_report' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Export queued'))

    const cssText = readFileSync('src/styles.css', 'utf-8')
    const report = auditPhase6ResponsiveReadiness(document, cssText, [375, 768, 1120])
    expect(report).toMatchObject({
      schemaVersion: 'phase6.frontend_responsive_audit.v1',
      passed: true,
      violationCount: 0,
      viewportWidths: [375, 768, 1120],
    })
    expect(report.viewportProfiles.map((profile) => profile.id)).toEqual(['mobile', 'tablet', 'desktop'])
    expect(report.violations).toEqual([])
  })

  it('renders viewer workspaces as read-only and hides admin operations', async () => {
    fetchMock = createBaseMock({
      'GET /auth/me': async () =>
        mkOk({
          user: {
            id: 'user_viewer',
            email: 'viewer@example.test',
            display_name: 'Hosted Viewer',
          },
          organizations: [
            {
              id: 'org_1',
              name: 'Hosted Demo Org',
              slug: 'hosted-demo-org',
              role: 'viewer',
            },
          ],
          workspaces: [
            {
              id: 'workspace_1',
              organization_id: 'org_1',
              name: 'Hosted demo workspace',
            },
          ],
        }),
    })
    global.fetch = fetchMock as unknown as typeof fetch
    render(<App />)

    fireEvent.change(await screen.findByTestId('hosted-email'), { target: { value: 'viewer@example.test' } })
    fireEvent.click(screen.getByTestId('hosted-load-account'))

    expect(await screen.findByTestId('hosted-role-panel')).toHaveTextContent('Role: viewer')
    expect(screen.getByTestId('hosted-create-thread')).toBeDisabled()
    expect(screen.getByTestId('hosted-send')).toBeDisabled()
    expect(screen.getByTestId('hosted-create-field-context')).toBeDisabled()
    expect(screen.getByTestId('hosted-create-data-source')).toBeDisabled()
    expect(screen.getByTestId('hosted-image-preview')).toBeDisabled()
    expect(screen.getByTestId('hosted-image-eval')).toBeDisabled()
    expect(screen.queryByTestId('hosted-admin-panel')).not.toBeInTheDocument()
    expect(screen.getByTestId('hosted-load-threads')).not.toBeDisabled()
  })

  it('persists hosted feedback and export events into trace view', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    fireEvent.click(await screen.findByTestId('hosted-create-thread'))
    fireEvent.click(await screen.findByTestId('hosted-send'))

    expect(await screen.findByTestId('hosted-answer')).toBeInTheDocument()
    fireEvent.change(screen.getByTestId('hosted-feedback-rating'), { target: { value: 'unsafe' } })
    fireEvent.change(screen.getByTestId('hosted-feedback-quick-tag'), { target: { value: 'wrong_source_or_weak_evidence' } })
    fireEvent.change(screen.getByTestId('hosted-feedback-triage-tag'), { target: { value: 'source_gap' } })
    fireEvent.change(screen.getByTestId('hosted-feedback-correction'), { target: { value: 'Ask for local source coverage first.' } })
    fireEvent.change(screen.getByTestId('hosted-feedback-ideal'), { target: { value: 'Start with source coverage, then explain uncertainty.' } })
    fireEvent.click(screen.getByTestId('hosted-feedback-training-consent'))
    fireEvent.click(screen.getByTestId('hosted-feedback'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Feedback saved')
    })
    const feedbackCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/messages/msg_a1/feedback' && init?.method === 'POST')
    expect(JSON.parse(String(feedbackCall?.[1]?.body))).toEqual({
      rating: 'unsafe',
      failure_tags: ['wrong_source_or_weak_evidence', 'source_gap'],
      human_correction: 'Ask for local source coverage first.',
      ideal_answer: 'Start with source coverage, then explain uncertainty.',
      training_consent: false,
    })
    expect(screen.getByTestId('hosted-trace')).toHaveTextContent('user_feedback')
    expect(screen.getByTestId('hosted-trace')).toHaveTextContent('eval_candidate')
    expect(screen.getByTestId('hosted-eval-candidates')).toHaveTextContent('pending')

    fireEvent.click(screen.getByTestId('hosted-approve-eval-candidate'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Eval candidate approved')
    })
    expect(screen.getByTestId('hosted-eval-candidates')).toHaveTextContent('approved_for_suite')

    fireEvent.click(screen.getByTestId('hosted-run-eval'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Eval replay completed')
    })
    expect(screen.getByTestId('hosted-eval-runs')).toHaveTextContent('Hosted feedback replay')
    expect(screen.getByTestId('hosted-eval-runs')).toHaveTextContent('1 candidates')
    expect(screen.getByTestId('hosted-eval-dashboard')).toHaveTextContent('approved 1')
    expect(screen.getByTestId('hosted-eval-dashboard')).toHaveTextContent('latest Hosted feedback replay completed')
    expect(screen.getByTestId('hosted-eval-dashboard')).toHaveTextContent('gate blocked')
    expect(screen.getByTestId('hosted-eval-dashboard')).toHaveTextContent('failures 1')
    expect(screen.getByTestId('hosted-eval-dashboard')).toHaveTextContent('pass rate 0')
    expect(screen.getByTestId('hosted-eval-dashboard')).toHaveTextContent('regression_failures_present')
    expect(screen.getByTestId('hosted-eval-drilldown')).toHaveTextContent('reviewed 1/1')
    expect(screen.getByTestId('hosted-eval-gate-reasons')).toHaveTextContent('regression_failures_present')
    expect(screen.getByTestId('hosted-eval-failure-tags')).toHaveTextContent('missed_local_calibration: 1')
    expect(screen.getByTestId('hosted-eval-target-counts')).toHaveTextContent('eval: 1')
    expect(screen.getByTestId('hosted-eval-regression-failures')).toHaveTextContent('eval_candidate_1')
    expect(screen.getByTestId('hosted-eval-regression-failures')).toHaveTextContent('ideal true')
    expect(screen.getByTestId('hosted-eval-candidate-evidence')).toHaveTextContent('wrong_source_or_weak_evidence, source_gap')
    expect(screen.getByTestId('hosted-eval-candidate-evidence')).toHaveTextContent('consent false')

    fireEvent.change(screen.getByTestId('hosted-eval-candidate-filter'), { target: { value: 'approved_for_suite' } })
    fireEvent.click(screen.getByTestId('hosted-load-eval-candidates'))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url) === '/eval-candidates?workspace_id=workspace_1&review_status=approved_for_suite'),
      ).toBe(true)
    })
    expect(screen.getByTestId('hosted-eval-candidates')).toHaveTextContent('approved_for_suite')

    fireEvent.click(screen.getByTestId('hosted-load-eval-runs'))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/eval-runs?workspace_id=workspace_1')).toBe(true)
    })
    expect(screen.getByTestId('hosted-eval-dashboard')).toHaveTextContent('runs 2')
    expect(screen.getByTestId('hosted-eval-drilldown')).toHaveTextContent('pass delta -1.00')
    expect(screen.getByTestId('hosted-eval-drilldown')).toHaveTextContent('failure delta +1.00')
    expect(screen.getByTestId('hosted-eval-trend')).toHaveTextContent('Hosted feedback replay')
    expect(screen.getByTestId('hosted-eval-trend')).toHaveTextContent('Previous hosted replay')
    expect(screen.getByTestId('hosted-eval-trend')).toHaveTextContent('gate pass')

    fireEvent.click(screen.getByTestId('hosted-create-change-proposal'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Change proposal created')
    })
    expect(screen.getByTestId('hosted-change-proposals')).toHaveTextContent('router_patch')
    expect(screen.getByTestId('hosted-change-proposals')).toHaveTextContent('candidate')
    expect(screen.getByTestId('hosted-change-proposals')).toHaveTextContent('rollout false')

    fireEvent.click(screen.getByTestId('hosted-review-change-proposal'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Change proposal needs eval')
    })
    expect(screen.getByTestId('hosted-change-proposals')).toHaveTextContent('needs_eval')
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('change_proposal.reviewed')

    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Export queued')
    })
    expect(screen.getByTestId('hosted-trace')).toHaveTextContent('export_event')
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('export.created')
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('json')
    expect(screen.getByTestId('hosted-exports')).toHaveTextContent('json')
    expect(screen.getByTestId('hosted-exports')).toHaveTextContent('abcdef12')
    expect(screen.getByTestId('hosted-exports')).toHaveTextContent('thread thread_1')
    expect(screen.getByTestId('hosted-exports')).toHaveTextContent('files 1')
    expect(screen.getByTestId('hosted-export-jobs')).toHaveTextContent('json')
    expect(screen.getByTestId('hosted-export-jobs')).toHaveTextContent('completed')
    expect(screen.getByTestId('hosted-export-jobs')).toHaveTextContent('queue exports')
    expect(screen.getByTestId('hosted-export-jobs')).toHaveTextContent('export export_1')
    expect(screen.getByTestId('hosted-quotas')).toHaveTextContent('max_exports')
    expect(screen.getByTestId('hosted-quotas')).toHaveTextContent('1/200')
  })

  it('defers hosted feedback and thread export while offline and replays them explicitly', async () => {
    Object.defineProperty(window.navigator, 'onLine', { value: false, configurable: true })
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    fireEvent.click(await screen.findByTestId('hosted-create-thread'))
    fireEvent.click(await screen.findByTestId('hosted-send'))

    expect(await screen.findByTestId('hosted-answer')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('hosted-feedback'))
    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Feedback saved locally for retry'))
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Export saved locally for retry'))

    expect(screen.getByTestId('hosted-deferred-actions')).toHaveTextContent('Deferred actions: 2')
    const deferred = JSON.parse(window.localStorage.getItem(PHASE6_DEFERRED_ACTION_STORAGE_KEY) || '[]')
    expect(deferred.map((action: { kind: string }) => action.kind)).toEqual(['hosted_feedback', 'hosted_thread_export'])
    expect(deferred[0].body.deferred_text_omitted).toBe(true)
    expect(JSON.stringify(deferred[0].body)).not.toContain('Ask for local calibration')
    expect(JSON.stringify(deferred[0].body)).not.toContain('Lead with water-quality')
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url) === '/messages/msg_a1/feedback' && init?.method === 'POST')).toHaveLength(0)
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url) === '/threads/thread_1/exports' && init?.method === 'POST')).toHaveLength(0)

    Object.defineProperty(window.navigator, 'onLine', { value: true, configurable: true })
    fireEvent.click(screen.getByTestId('hosted-retry-deferred-actions'))

    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Retried 2 deferred actions'))
    expect(window.localStorage.getItem(PHASE6_DEFERRED_ACTION_STORAGE_KEY)).toBeNull()
    expect(screen.getByTestId('hosted-deferred-actions')).toHaveTextContent('Deferred actions: 0')
    expect(screen.getByTestId('hosted-trace')).toHaveTextContent('user_feedback')
    expect(screen.getByTestId('hosted-trace')).toHaveTextContent('export_event')
  })

  it('windows large hosted trace panels with visible omitted-count status', async () => {
    const largeTraceEvents = Array.from({ length: PHASE6_VIRTUAL_LIST_LIMIT + 4 }, (_, index) => ({
      event_id: `evt_large_${index}`,
      event_type: `large_trace_event_${index}`,
      actor: 'system',
      payload: { index },
      created_at: new Date().toISOString(),
    }))
    fetchMock = createBaseMock({
      'GET /threads/thread_1/trace': async () =>
        mkOk({
          schema_version: 'phase4.thread_trace.v1',
          workspace_id: 'workspace_1',
          organization_id: 'org_1',
          thread: { thread_id: 'thread_1', title: 'Hosted phosphorus review', mode: 'agronomic_rag' },
          privacy: { trace_capture_level: 'research_opt_in', training_eligible: true, redaction_status: 'not_required' },
          events: largeTraceEvents,
        }),
    })
    global.fetch = fetchMock as unknown as typeof fetch

    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    fireEvent.click(await screen.findByTestId('hosted-create-thread'))
    fireEvent.click(await screen.findByTestId('hosted-send'))

    expect(await screen.findByTestId('hosted-trace-window')).toHaveTextContent(
      `Showing first ${PHASE6_VIRTUAL_LIST_LIMIT} of ${PHASE6_VIRTUAL_LIST_LIMIT + 4}`,
    )
    expect(screen.getByTestId('hosted-trace')).toHaveTextContent('large_trace_event_0')
    expect(screen.getByTestId('hosted-trace')).not.toHaveTextContent(`large_trace_event_${PHASE6_VIRTUAL_LIST_LIMIT}`)
  })

  it('filters hosted exports by scope type and limit', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    fireEvent.click(await screen.findByTestId('hosted-create-thread'))
    fireEvent.click(await screen.findByTestId('hosted-export'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Export queued')
    })

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'json' } })
    fireEvent.change(screen.getByTestId('hosted-export-limit'), { target: { value: '1' } })
    fireEvent.click(screen.getByTestId('hosted-load-exports'))

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url) === '/exports?workspace_id=workspace_1&limit=1&thread_id=thread_1&export_type=json'),
      ).toBe(true)
    })
    fireEvent.click(screen.getByTestId('hosted-load-export-jobs'))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url) === '/export-jobs?workspace_id=workspace_1&limit=1&thread_id=thread_1'),
      ).toBe(true)
    })

    fireEvent.change(screen.getByTestId('hosted-export-scope'), { target: { value: 'workspace' } })
    fireEvent.click(screen.getByTestId('hosted-load-exports'))

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url) === '/exports?workspace_id=workspace_1&limit=1&export_type=json'),
      ).toBe(true)
    })
    fireEvent.click(screen.getByTestId('hosted-load-export-jobs'))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url) === '/export-jobs?workspace_id=workspace_1&limit=1'),
      ).toBe(true)
    })

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'zip' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => {
      const exportCall = fetchMock.mock.calls
        .filter(([url, init]) => String(url) === '/threads/thread_1/exports' && init?.method === 'POST')
        .at(-1)
      expect(JSON.parse(String(exportCall?.[1]?.body || '{}')).export_type).toBe('zip')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('files 5')
    })

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'csv' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => {
      const exportCall = fetchMock.mock.calls
        .filter(([url, init]) => String(url) === '/threads/thread_1/exports' && init?.method === 'POST')
        .at(-1)
      expect(JSON.parse(String(exportCall?.[1]?.body || '{}')).export_type).toBe('csv')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('files 4')
    })

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'field_context_brief' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => {
      const exportCall = fetchMock.mock.calls
        .filter(([url, init]) => String(url) === '/threads/thread_1/exports' && init?.method === 'POST')
        .at(-1)
      expect(JSON.parse(String(exportCall?.[1]?.body || '{}')).export_type).toBe('field_context_brief')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('field_context_brief')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('files 3')
    })

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'source_evidence_bundle' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => {
      const exportCall = fetchMock.mock.calls
        .filter(([url, init]) => String(url) === '/threads/thread_1/exports' && init?.method === 'POST')
        .at(-1)
      expect(JSON.parse(String(exportCall?.[1]?.body || '{}')).export_type).toBe('source_evidence_bundle')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('source_evidence_bundle')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('files 4')
    })

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'diagnostic_checklist' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => {
      const exportCall = fetchMock.mock.calls
        .filter(([url, init]) => String(url) === '/threads/thread_1/exports' && init?.method === 'POST')
        .at(-1)
      expect(JSON.parse(String(exportCall?.[1]?.body || '{}')).export_type).toBe('diagnostic_checklist')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('diagnostic_checklist')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('files 4')
    })

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'learning_trace_export' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => {
      const exportCall = fetchMock.mock.calls
        .filter(([url, init]) => String(url) === '/threads/thread_1/exports' && init?.method === 'POST')
        .at(-1)
      expect(JSON.parse(String(exportCall?.[1]?.body || '{}')).export_type).toBe('learning_trace_export')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('learning_trace_export')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('files 2')
    })

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'data_source_audit' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => {
      const exportCall = fetchMock.mock.calls
        .filter(([url, init]) => String(url) === '/threads/thread_1/exports' && init?.method === 'POST')
        .at(-1)
      expect(JSON.parse(String(exportCall?.[1]?.body || '{}')).export_type).toBe('data_source_audit')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('data_source_audit')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('files 3')
    })

    fireEvent.change(screen.getByTestId('hosted-export-type-filter'), { target: { value: 'demo_eval_snapshot' } })
    fireEvent.click(screen.getByTestId('hosted-export'))
    await waitFor(() => {
      const exportCall = fetchMock.mock.calls
        .filter(([url, init]) => String(url) === '/threads/thread_1/exports' && init?.method === 'POST')
        .at(-1)
      expect(JSON.parse(String(exportCall?.[1]?.body || '{}')).export_type).toBe('demo_eval_snapshot')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('demo_eval_snapshot')
      expect(screen.getByTestId('hosted-exports')).toHaveTextContent('files 3')
    })
  })

  it('creates hosted field context and binds it to thread chat', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-create-field-context')).not.toBeDisabled()
    })
    fireEvent.click(screen.getByTestId('hosted-create-field-context'))

    expect(await screen.findByTestId('hosted-field-context')).toHaveTextContent('North field generalized')
    expect(await screen.findByTestId('hosted-field-context-quality')).toHaveTextContent('diagnostic_triage_ready')
    expect(screen.getByTestId('hosted-field-context-quality')).toHaveTextContent('Not enough for product/rate decision: blocked')
    expect(screen.getByTestId('hosted-field-context-readiness')).toHaveTextContent('Ready for: Conceptual answer, Diagnostic triage')
    expect(screen.getByTestId('hosted-field-context-readiness')).toHaveTextContent(
      'Product/rate decision requires current label evidence and local recommendation authority.',
    )

    fireEvent.click(screen.getByTestId('hosted-update-field-context'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Field context updated')
    })
    expect(screen.getByTestId('hosted-field-context')).toHaveTextContent('North field generalized updated')
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('field_context.updated')

    fireEvent.click(screen.getByTestId('hosted-run-geo-priors'))
    expect(await screen.findByTestId('hosted-geo-priors')).toHaveTextContent(
      'Regional context used as prior, not field-specific fact.',
    )
    expect(screen.getByTestId('hosted-geo-priors')).toHaveTextContent('Central Iowa and Minnesota Till Prairies')
    expect(screen.getByTestId('hosted-geo-priors')).toHaveTextContent('regional_environment')
    expect(screen.getByTestId('hosted-geo-priors')).toHaveTextContent('tile drainage common')
    const geoCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/geo/priors' && init?.method === 'POST')
    expect(JSON.parse(String(geoCall?.[1]?.body || '{}'))).toMatchObject({
      workspace_id: 'workspace_1',
      field_context_id: 'field_context_1',
      location_text: 'Iowa Des Moines Lobe',
    })

    fireEvent.click(screen.getByTestId('hosted-create-thread'))
    await waitFor(() => {
      const threadCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/threads' && init?.method === 'POST')
      expect(JSON.parse(String(threadCall?.[1]?.body || '{}'))).toMatchObject({
        workspace_id: 'workspace_1',
        field_context_id: 'field_context_1',
      })
    })

    fireEvent.click(screen.getByTestId('hosted-send'))
    await waitFor(() => {
      const chatCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/chat/stream' && init?.method === 'POST')
      expect(JSON.parse(String(chatCall?.[1]?.body || '{}'))).toMatchObject({
        workspace_id: 'workspace_1',
        thread_id: 'thread_1',
        field_context_id: 'field_context_1',
      })
    })

    fireEvent.click(screen.getByTestId('hosted-delete-field-context'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Field context deleted')
    })
    expect(screen.queryByTestId('hosted-field-context')).toBeNull()
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('field_context.deleted')
  })

  it('creates a selected safe sample field context for demo onboarding', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-create-field-context')).not.toBeDisabled()
    })

    fireEvent.change(screen.getByTestId('hosted-sample-field-context'), {
      target: { value: 'prairie_canola_low_ph' },
    })
    expect(screen.getByTestId('hosted-sample-field-context-summary')).toHaveTextContent('canola - Saskatchewan Black soil zone')
    expect(screen.getByTestId('hosted-geo-location')).toHaveValue('Saskatchewan Black soil zone')

    fireEvent.click(screen.getByTestId('hosted-create-field-context'))
    expect(await screen.findByTestId('hosted-field-context')).toHaveTextContent('Prairie canola low pH')

    const createCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/field-contexts' && init?.method === 'POST')
    expect(JSON.parse(String(createCall?.[1]?.body || '{}'))).toMatchObject({
      workspace_id: 'workspace_1',
      display_name: 'Prairie canola low pH',
      region_text: 'Saskatchewan Black soil zone',
      country: 'CA',
      province_state: 'Saskatchewan',
      crop_current: 'canola',
      sensitivity: 'medium',
      known_constraints: ['buffer pH missing', 'soil test date unknown', 'local recommendation basis required'],
    })
  })

  it('registers hosted data source and queues ingest loudly', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-create-data-source')).not.toBeDisabled()
    })
    fireEvent.click(screen.getByTestId('hosted-create-data-source'))

    expect(await screen.findByTestId('hosted-data-sources')).toHaveTextContent('Demo fertility source')
    expect(screen.getByTestId('hosted-data-sources')).toHaveTextContent('review_required')
    fireEvent.click(screen.getByTestId('hosted-update-data-source'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Data source updated')
    })
    expect(screen.getByTestId('hosted-data-sources')).toHaveTextContent('Demo fertility source reviewed')
    expect(screen.getByTestId('hosted-data-sources')).toHaveTextContent('approved')
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('data_source.updated')

    fireEvent.click(screen.getByTestId('hosted-load-corpus-health'))
    expect(await screen.findByTestId('hosted-corpus-health')).toHaveTextContent('blocked')
    expect(screen.getByTestId('hosted-corpus-health')).toHaveTextContent('missing_ingest_job')
    expect(screen.getByTestId('hosted-corpus-health')).toHaveTextContent('no_chunks_indexed')

    fireEvent.click(screen.getByTestId('hosted-ingest-data-source'))
    expect(await screen.findByTestId('hosted-ingest-job')).toHaveTextContent('queued')
    expect(await screen.findByTestId('hosted-ingest-jobs')).toHaveTextContent('queued')
    expect(screen.getByTestId('hosted-corpus-health')).toHaveTextContent('ingest_queued')
    expect(screen.getByTestId('hosted-status')).toHaveTextContent('Ingest queued')

    fireEvent.click(screen.getByTestId('hosted-run-ingest-worker'))
    expect(await screen.findByTestId('hosted-ingest-job')).toHaveTextContent('completed')
    expect(screen.getByTestId('hosted-ingest-jobs')).toHaveTextContent('completed')
    expect(screen.getByTestId('hosted-ingest-job')).toHaveTextContent('chunks 1')
    expect(screen.getByTestId('hosted-corpus-health')).toHaveTextContent('chunks 1')
    expect(screen.getByTestId('hosted-status')).toHaveTextContent('Ingest completed')

    fireEvent.click(screen.getByTestId('hosted-delete-data-source'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Data source deleted')
    })
    expect(screen.queryByTestId('hosted-data-sources')).toBeNull()
    expect(screen.getByTestId('hosted-corpus-health')).toHaveTextContent('sources 0')
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('data_source.deleted')
  })

  it('updates hosted thread training consent and surfaces audit evidence', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    fireEvent.click(await screen.findByTestId('hosted-create-thread'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread created')
    })

    expect(screen.getByTestId('hosted-training-eligible')).toBeChecked()
    fireEvent.click(screen.getByTestId('hosted-training-eligible'))
    fireEvent.change(screen.getByTestId('hosted-trace-capture'), { target: { value: 'operational' } })
    fireEvent.click(screen.getByTestId('hosted-update-consent'))

    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread consent updated')
    })
    expect(screen.getByTestId('hosted-training-eligible')).not.toBeChecked()
    expect(screen.getByTestId('hosted-trace')).toHaveTextContent('Privacy: operational')
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('training_consent.updated')

    const consentCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/threads/thread_1' && init?.method === 'PATCH')
    expect(JSON.parse(String(consentCall?.[1]?.body || '{}'))).toMatchObject({
      training_eligible: false,
      trace_capture_level: 'operational',
    })
  })

  it('deletes hosted thread and surfaces audit evidence', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    fireEvent.click(await screen.findByTestId('hosted-create-thread'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread created')
    })

    fireEvent.click(screen.getByTestId('hosted-delete-thread'))

    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread deleted')
    })
    expect(screen.queryByTestId('hosted-thread')).toBeNull()
    expect(screen.queryByTestId('hosted-trace')).toBeNull()
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('thread.deleted')

    const deleteCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/threads/thread_1' && init?.method === 'DELETE')
    expect(deleteCall).toBeTruthy()
  })

  it('deletes the selected workspace and clears workspace scoped state', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-workspace')).toHaveValue('workspace_1')
    })

    fireEvent.click(screen.getByTestId('hosted-delete-workspace'))

    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Workspace deleted')
    })
    expect(screen.queryByTestId('hosted-workspace')).toBeNull()
    expect(screen.getByTestId('hosted-delete-workspace')).toBeDisabled()
    expect(screen.getByTestId('hosted-create-thread')).toBeDisabled()

    const deleteCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/workspaces/workspace_1' && init?.method === 'DELETE')
    expect(deleteCall).toBeTruthy()
  })

  it('requires account export before deleting the hosted account', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-user')).toHaveTextContent('advisor@example.test')
    })
    expect(screen.getByTestId('hosted-delete-account')).toBeDisabled()

    fireEvent.click(screen.getByTestId('hosted-export-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-account-export')).toHaveTextContent('phase6.account_data_export.v1')
    })

    fireEvent.click(screen.getByTestId('hosted-delete-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Account deleted')
    })
    expect(screen.queryByTestId('hosted-user')).toBeNull()
    expect(screen.queryByTestId('hosted-workspace')).toBeNull()
    expect(screen.getByTestId('hosted-delete-account')).toBeDisabled()

    const deleteCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/account' && init?.method === 'DELETE')
    expect(deleteCall).toBeTruthy()
    expect(JSON.parse(String(deleteCall?.[1]?.body))).toEqual({
      confirm_email: 'advisor@example.test',
      export_acknowledged: true,
    })
  })

  it('uploads private note attachment, sends it with chat, and deletes it', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-create-thread')).not.toBeDisabled()
    })
    fireEvent.click(screen.getByTestId('hosted-create-thread'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread created')
    })

    fireEvent.change(screen.getByTestId('hosted-attachment-text'), {
      target: { value: 'Private phosphorus note for this workspace only.' },
    })
    fireEvent.click(screen.getByTestId('hosted-create-attachment'))

    expect(await screen.findByTestId('hosted-attachments')).toHaveTextContent('private_indexed')
    expect(screen.getByTestId('hosted-attachments')).toHaveTextContent('retention delete_on_request')
    expect(screen.getByTestId('hosted-attachments')).toHaveTextContent('scope thread')
    expect(screen.getByTestId('hosted-attachments')).toHaveTextContent('chunks 1')

    fireEvent.click(screen.getByTestId('hosted-send'))
    expect(await screen.findByTestId('hosted-trace')).toHaveTextContent('attachment_event')
    expect(screen.getByTestId('hosted-trace')).toHaveTextContent('user_upload_private')

    const chatCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/chat/stream' && init?.method === 'POST')
    expect(JSON.parse(String(chatCall?.[1]?.body || '{}'))).toMatchObject({
      attachment_ids: ['attachment_1'],
    })

    fireEvent.click(screen.getByTestId('hosted-delete-attachment'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Private note deleted')
    })
    expect(screen.queryByTestId('hosted-attachments')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('hosted-load-audit-events'))
    expect(await screen.findByTestId('hosted-audit-events')).toHaveTextContent('attachment.deleted')
    expect(screen.getByTestId('hosted-audit-events')).toHaveTextContent('attachment.created')
  })

  it('uses low-bandwidth mode to skip chat uploads and shrink export list loads', async () => {
    render(<App />)

    expect(await screen.findByTestId('hosted-low-bandwidth-status')).toHaveTextContent('Active false')
    fireEvent.change(screen.getByTestId('hosted-low-bandwidth-mode'), { target: { value: 'on' } })
    expect(window.localStorage.getItem(PHASE6_LOW_BANDWIDTH_STORAGE_KEY)).toBe('on')
    expect(screen.getByTestId('hosted-low-bandwidth-status')).toHaveTextContent('Active true')
    expect(screen.getByTestId('hosted-low-bandwidth-status')).toHaveTextContent('Export list limit 5')

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    fireEvent.click(await screen.findByTestId('hosted-create-thread'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread created')
    })
    fireEvent.click(screen.getByTestId('hosted-create-attachment'))
    expect(await screen.findByTestId('hosted-attachments')).toHaveTextContent('private_indexed')

    fireEvent.click(screen.getByTestId('hosted-send'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Hosted chat completed')
    })
    const chatCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/chat/stream' && init?.method === 'POST')
    expect(JSON.parse(String(chatCall?.[1]?.body || '{}'))).toMatchObject({ attachment_ids: [] })

    const messageEvent = fetchMock.mock.calls
      .filter(([url]) => String(url) === '/api/frontend-events')
      .map(([, init]) => JSON.parse(String(init?.body || '{}')))
      .find((payload) => payload.event_name === 'message_submitted')
    expect(messageEvent?.metadata).toMatchObject({
      low_bandwidth: true,
      low_bandwidth_preference: 'on',
      skipped_attachment_count: 1,
    })

    fireEvent.click(screen.getByTestId('hosted-load-exports'))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/exports?workspace_id=workspace_1&limit=5&thread_id=thread_1')).toBe(true)
    })
  })

  it('manages private upload scope, chat selection, and deleted tombstone visibility', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    fireEvent.click(await screen.findByTestId('hosted-create-thread'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Thread created')
    })

    fireEvent.change(screen.getByTestId('hosted-attachment-scope'), { target: { value: 'workspace' } })
    fireEvent.change(screen.getByTestId('hosted-attachment-sensitivity'), { target: { value: 'medium' } })
    fireEvent.change(screen.getByTestId('hosted-attachment-retention'), { target: { value: 'short' } })
    fireEvent.click(screen.getByTestId('hosted-create-attachment'))

    expect(await screen.findByTestId('hosted-attachments')).toHaveTextContent('medium')
    expect(screen.getByTestId('hosted-attachments')).toHaveTextContent('scope workspace')
    expect(screen.getByTestId('hosted-attachments')).toHaveTextContent('retention short')
    const uploadCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/attachments' && init?.method === 'POST')
    expect(JSON.parse(String(uploadCall?.[1]?.body || '{}'))).toMatchObject({
      workspace_id: 'workspace_1',
      sensitivity: 'medium',
      retention_policy: 'short',
    })
    expect(JSON.parse(String(uploadCall?.[1]?.body || '{}'))).not.toHaveProperty('thread_id')

    fireEvent.change(screen.getByTestId('hosted-attachment-use-mode'), { target: { value: 'none' } })
    fireEvent.click(screen.getByTestId('hosted-send'))
    await waitFor(() => {
      const chatCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/chat/stream' && init?.method === 'POST')
      expect(JSON.parse(String(chatCall?.[1]?.body || '{}'))).toMatchObject({ attachment_ids: [] })
    })

    fireEvent.click(screen.getByTestId('hosted-delete-attachment'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Private note deleted')
    })
    expect(screen.queryByTestId('hosted-attachments')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('hosted-include-deleted-attachments'))
    fireEvent.click(screen.getByTestId('hosted-load-attachments'))
    expect(await screen.findByTestId('hosted-attachments')).toHaveTextContent('deleted')
    expect(screen.getByTestId('hosted-attachment-select-attachment_1')).toBeDisabled()
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/attachments?workspace_id=workspace_1&include_deleted=true')).toBe(true)
    })
  })

  it('uploads image attachment metadata for image-rag research preview', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-create-image-attachment')).not.toBeDisabled()
    })
    fireEvent.click(screen.getByTestId('hosted-create-image-attachment'))

    expect(await screen.findByTestId('hosted-attachments')).toHaveTextContent('hosted-scouting-image.png')
    expect(screen.getByTestId('hosted-attachments')).toHaveTextContent('image_staged')
    expect(screen.getByTestId('hosted-attachments')).toHaveTextContent('image 1x1')

    const imageUploadCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/attachments' && init?.method === 'POST')
    expect(JSON.parse(String(imageUploadCall?.[1]?.body || '{}'))).toMatchObject({
      content_type: 'image/png',
      modality: 'image',
      client_preprocessing: {
        schema_version: 'phase6.image_upload_preparation.v1',
        preserve_original: false,
        status: 'within_inline_budget',
      },
    })
  })

  it('requires explicit preserve-original consent for oversized inline image uploads', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-create-image-attachment')).not.toBeDisabled()
    })
    fireEvent.change(screen.getByTestId('hosted-image-base64'), { target: { value: 'x'.repeat(360000) } })
    fireEvent.click(screen.getByTestId('hosted-create-image-attachment'))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('preserve-original consent')
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Hosted request failed')
    })
    expect(fetchMock.mock.calls.filter(([url, init]) => String(url) === '/attachments' && init?.method === 'POST')).toHaveLength(0)

    fireEvent.click(screen.getByTestId('hosted-preserve-original-image'))
    fireEvent.click(screen.getByTestId('hosted-create-image-attachment'))

    await waitFor(() => expect(screen.getByTestId('hosted-status')).toHaveTextContent('Image uploaded for research preview'))
    const imageUploadCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/attachments' && init?.method === 'POST')
    expect(JSON.parse(String(imageUploadCall?.[1]?.body || '{}')).client_preprocessing).toMatchObject({
      preserve_original: true,
      status: 'preserved_original',
    })
  })

  it('keeps image-rag UI explicitly in research preview mode', async () => {
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-image-preview')).not.toBeDisabled()
    })
    fireEvent.click(screen.getByTestId('hosted-image-preview'))

    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Image research preview: true')
    })
    expect(screen.getByTestId('hosted-image-preview-result')).toHaveTextContent('local_quality_and_metadata_stub')
    expect(screen.getByTestId('hosted-image-preview-result')).toHaveTextContent('retrieval_context')
    const imageCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === '/image-rag/query' && init?.method === 'POST',
    )
    expect(JSON.parse(String(imageCall?.[1]?.body || '{}'))).toMatchObject({
      workspace_id: 'workspace_1',
      question: 'What does this image suggest?',
    })

    fireEvent.click(screen.getByTestId('hosted-image-eval'))
    await waitFor(() => {
      expect(screen.getByTestId('hosted-status')).toHaveTextContent('Image eval: phase4.image_research_eval.v1')
    })
    expect(screen.getByTestId('hosted-image-eval-result')).toHaveTextContent('recall_at_k')
    expect(screen.getByTestId('hosted-image-eval-result')).toHaveTextContent('macro_f1')
    expect(screen.getByTestId('hosted-image-eval-result')).toHaveTextContent('expected_calibration_error')
    expect(screen.getByTestId('hosted-image-eval-result')).toHaveTextContent('unsafe_treatment_recommendation_rate')
    const imageEvalCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url) === '/image-rag/evals' && init?.method === 'POST',
    )
    expect(JSON.parse(String(imageEvalCall?.[1]?.body || '{}'))).toMatchObject({
      workspace_id: 'workspace_1',
      samples: expect.arrayContaining([
        expect.objectContaining({ sample_id: 'demo_image_eval_hit' }),
        expect.objectContaining({ sample_id: 'demo_image_eval_unsafe' }),
      ]),
    })
  })

  it('surfaces hosted request failures instead of leaving stale status', async () => {
    fetchMock = createBaseMock({
      'GET /auth/me': async () => mkFail(503, 'hosted auth unavailable'),
    })
    global.fetch = fetchMock as unknown as typeof fetch
    render(<App />)

    fireEvent.click(await screen.findByTestId('hosted-load-account'))

    expect(await screen.findByRole('alert')).toHaveTextContent('503: hosted auth unavailable')
    expect(screen.getByTestId('hosted-status')).toHaveTextContent('Hosted request failed')
  })
})
