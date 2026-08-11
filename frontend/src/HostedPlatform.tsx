import { FormEvent, useEffect, useMemo, useState } from 'react'
import {
  enqueuePhase6DeferredAction,
  listPhase6DeferredActions,
  removePhase6DeferredAction,
} from './deferredActions'
import { buildFieldContextReadiness } from './fieldContextReadiness'
import type { FieldContextReadiness } from './fieldContextReadiness'
import { preparePhase6ImageUpload } from './imageUploadPreparation'
import {
  buildLocalInferencePreviewState,
  disabledWebGpuPreviewState,
  isWebGpuPreviewEnabled,
  LocalInferencePreviewState,
  probeWebGpuPreview,
  WebGpuPreviewProbeResult,
} from './localPreview'
import {
  detectPhase6LowBandwidth,
  isPhase6LowBandwidthActive,
  loadPhase6LowBandwidthPreference,
  phase6LowBandwidthSummary,
  savePhase6LowBandwidthPreference,
  type Phase6LowBandwidthPreference,
} from './lowBandwidth'
import { configureFrontendRum, sendFrontendEvent, sendFrontendMeasure, sendRumMetric, startFrontendMeasure } from './rum'
import {
  HostedAuditEvent,
  HostedAttachment,
  HostedChangeProposal,
  HostedCorpusHealth,
  HostedDataSource,
  HostedEvalCandidate,
  HostedEvalRun,
  HostedExport,
  HostedExportJob,
  HostedFieldContext,
  HostedGeoPriors,
  HostedIngestJob,
  HostedOrganization,
  HostedQuotaReport,
  HostedThread,
  HostedTraceBundle,
  HostedUser,
  HostedWorkspace,
  Phase5AdminTrace,
  Phase5LatencyDashboard,
} from './types'
import { type Phase6VirtualListWindow, virtualizePhase6List } from './virtualizedList'

type AuthPayload = {
  user: HostedUser
  account_consent?: AccountConsent
  organizations: HostedOrganization[]
  workspaces: HostedWorkspace[]
}

type AccountConsent = {
  schema_version: string
  trace_storage_enabled: boolean
  feedback_use_allowed: boolean
  training_candidate_allowed: boolean
  public_anonymized_examples_allowed: boolean
  product_updates_allowed: boolean
  retention_preference: 'default' | 'short' | 'delete_on_request'
  updated_at?: string | null
}

type AccountConsentPayload = {
  schema_version: string
  consent: AccountConsent
}

type AccountExportPayload = {
  schema_version: string
  created_at: string
  account_consent?: AccountConsent
  organizations: unknown[]
  workspaces: Array<{
    workspace: HostedWorkspace
    threads: unknown[]
    attachments: unknown[]
    exports: unknown[]
  }>
  data_policy: Record<string, unknown>
}

type WorkspaceInvitePayload = {
  schema_version: string
  invite_token: string
  invite_url: string
  organization_id: string
  email: string
  role: string
  expires_at: string
}

type WorkspaceInviteAcceptPayload = {
  schema_version: string
  accepted: boolean
  organization: HostedOrganization
  membership: {
    organization_id: string
    user_id: string
    role: string
  }
  expires_at: string
}

type AuthSession = {
  id: string
  issued_at: string
  expires_at: string
  last_seen_at: string
  revoked_at?: string | null
  current?: boolean
  user_agent_hash?: string | null
}

type AuthSessionsPayload = {
  schema_version: string
  sessions: AuthSession[]
}

type PasswordSignupPayload = {
  schema_version: string
  status: string
  email: string
  dev_delivery?: { token?: string; delivery?: string }
}

type PasswordVerificationPayload = {
  schema_version: string
  status: string
  user: HostedUser
}

type PasswordLoginPayload = {
  schema_version: string
  user: HostedUser
  csrf_token: string
}

type PasswordResetRequestPayload = {
  schema_version: string
  status: string
  message: string
  dev_delivery?: { token?: string; delivery?: string }
}

type PasswordResetConfirmPayload = {
  schema_version: string
  status: string
  sessions_revoked: boolean
}

type StreamEvent = {
  event: string
  payload: Record<string, unknown>
}

type HostedRole = 'owner' | 'admin' | 'researcher' | 'adviser' | 'viewer'
type EvalCandidateFilter = 'all' | 'pending' | 'approved_for_suite' | 'rejected' | 'retired'
type AttachmentUseMode = 'all' | 'selected' | 'none'
type HostedFeedbackRating = 'good' | 'needs_work' | 'unsafe' | 'irrelevant' | 'unknown'
type Phase6SampleFieldContext = {
  id: string
  label: string
  body: {
    display_name: string
    region_text: string
    country?: string
    province_state?: string
    county_rm?: string
    crop_current: string
    soil_series_or_texture?: string
    drainage_class?: string
    irrigation_status?: string
    soil_test_summary?: string
    crop_rotation_notes?: string
    management_notes?: string
    known_constraints: string[]
    sensitivity: 'low' | 'medium' | 'high'
  }
}

type AdminOpsSummary = {
  health: Record<string, unknown>
  metrics: Record<string, unknown>
  monitoring: Record<string, unknown>
  latency: Phase5LatencyDashboard | null
  frontendRum: Record<string, unknown> | null
  frontendEvents: Record<string, unknown> | null
  auditEvents: HostedAuditEvent[]
  failures: string[]
}

const evalCandidateFilterOptions: EvalCandidateFilter[] = ['all', 'pending', 'approved_for_suite', 'rejected', 'retired']
const hostedFeedbackQuickTags = [
  { id: 'helpful', label: 'Helpful' },
  { id: 'not_helpful', label: 'Not helpful' },
  { id: 'safe', label: 'Safe' },
  { id: 'questionable', label: 'Questionable' },
  { id: 'missing_important_context', label: 'Missing important context' },
  { id: 'wrong_source_or_weak_evidence', label: 'Wrong source or weak evidence' },
  { id: 'too_generic', label: 'Too generic' },
  { id: 'too_cautious', label: 'Too cautious' },
  { id: 'exposed_internal_wording', label: 'Exposed internal wording' },
  { id: 'other', label: 'Other' },
]
const hostedFeedbackTriageTags = [
  { id: 'safety_issue', label: 'Safety issue' },
  { id: 'retrieval_miss', label: 'Retrieval miss' },
  { id: 'routing_error', label: 'Routing error' },
  { id: 'context_packing_error', label: 'Context packing error' },
  { id: 'tool_miss', label: 'Tool miss' },
  { id: 'ui_leak', label: 'UI leak' },
  { id: 'source_gap', label: 'Source gap' },
  { id: 'model_generation_failure', label: 'Model generation failure' },
]

const phase6SampleFieldContexts: Phase6SampleFieldContext[] = [
  {
    id: 'corn_belt_phosphorus',
    label: 'Corn Belt phosphorus field',
    body: {
      display_name: 'North field generalized',
      region_text: 'Iowa Des Moines Lobe',
      country: 'US',
      province_state: 'Iowa',
      crop_current: 'corn',
      soil_series_or_texture: 'silt loam; soil-test method unknown',
      drainage_class: 'tile-drained with nearby ditch',
      irrigation_status: 'rainfed',
      soil_test_summary: 'High phosphorus reported; method, units, and sample date unknown.',
      crop_rotation_notes: 'corn-soybean rotation',
      management_notes: 'Use as a water-quality and missing-data demo context, not a product/rate recommendation.',
      known_constraints: ['ditch nearby', 'high soil-test P', 'soil-test method missing'],
      sensitivity: 'medium',
    },
  },
  {
    id: 'prairie_canola_low_ph',
    label: 'Prairie canola low pH',
    body: {
      display_name: 'Prairie canola low pH',
      region_text: 'Saskatchewan Black soil zone',
      country: 'CA',
      province_state: 'Saskatchewan',
      crop_current: 'canola',
      soil_series_or_texture: 'clay loam; pH concern from older soil test',
      drainage_class: 'moderate',
      irrigation_status: 'rainfed',
      soil_test_summary: 'Low pH suspected; buffer pH and lab method not supplied.',
      crop_rotation_notes: 'cereal-canola-pulse rotation',
      management_notes: 'Use for lime-planning caveats and regional-prior uncertainty.',
      known_constraints: ['buffer pH missing', 'soil test date unknown', 'local recommendation basis required'],
      sensitivity: 'medium',
    },
  },
  {
    id: 'irrigated_salinity_field',
    label: 'Irrigated salinity field',
    body: {
      display_name: 'Irrigated salinity field',
      region_text: 'Southern Alberta irrigated corridor',
      country: 'CA',
      province_state: 'Alberta',
      crop_current: 'alfalfa',
      soil_series_or_texture: 'fine-textured soil; salinity symptoms suspected',
      drainage_class: 'imperfect',
      irrigation_status: 'irrigated',
      soil_test_summary: 'EC and SAR not supplied.',
      crop_rotation_notes: 'forage stand with variable growth',
      management_notes: 'Use for salinity/sodicity triage and measurement planning.',
      known_constraints: ['EC missing', 'SAR missing', 'irrigation water quality unknown'],
      sensitivity: 'medium',
    },
  },
]

const roleCapabilities = (role: string | undefined) => {
  const normalized = (role || 'viewer') as HostedRole
  return {
    role: normalized,
    canWrite: ['owner', 'admin', 'researcher', 'adviser'].includes(normalized),
    canReviewResearch: ['owner', 'admin', 'researcher'].includes(normalized),
    canAdmin: ['owner', 'admin'].includes(normalized),
  }
}

const parseSseEvents = (text: string): StreamEvent[] =>
  text
    .split('\n\n')
    .map((chunk) => {
      let event = 'message'
      let data = ''
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event:')) {
          event = line.slice('event:'.length).trim()
        }
        if (line.startsWith('data:')) {
          data += line.slice('data:'.length).trim()
        }
      }
      if (!data) {
        return null
      }
      try {
        return { event, payload: JSON.parse(data) as Record<string, unknown> }
      } catch {
        return null
      }
    })
    .filter((item): item is StreamEvent => item !== null)

const csrfHeaders = (): Record<string, string> => {
  const match = document.cookie.match(/(?:^|;\s*)agronomy_csrf=([^;]+)/)
  return match ? { 'X-CSRF-Token': decodeURIComponent(match[1]) } : {}
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}

const asStringList = (value: unknown): string[] => (Array.isArray(value) ? value.map(String).filter(Boolean) : [])

const countEntries = (value: unknown): Array<[string, number]> =>
  Object.entries(asRecord(value))
    .map(([key, count]) => [key, Number(count) || 0] as [string, number])
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))

const regressionFailureRows = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item)) : []

const numberMetric = (value: unknown): number | null => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const signedMetric = (value: number): string => {
  if (value > 0) return `+${value.toFixed(2)}`
  if (value < 0) return value.toFixed(2)
  return '0.00'
}

const sortedEvalRuns = (runs: HostedEvalRun[]): HostedEvalRun[] =>
  [...runs].sort((left, right) => {
    const rightTime = Date.parse(String(right.created_at || right.finished_at || ''))
    const leftTime = Date.parse(String(left.created_at || left.finished_at || ''))
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0)
  })

const decode = async <T,>(response: Response): Promise<T> => {
  if (!response.ok) {
    throw new Error(`${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

const errorMessage = (error: unknown): string => (error instanceof Error ? error.message : String(error))
const virtualizedNotice = <T,>(windowed: Phase6VirtualListWindow<T>, testId: string) =>
  windowed.isWindowed ? (
    <li data-testid={testId}>
      Showing first {windowed.visibleCount} of {windowed.totalCount}; {windowed.omittedCount} hidden for performance.
    </li>
  ) : null

export function HostedPlatform() {
  const [email, setEmail] = useState('advisor@example.test')
  const [user, setUser] = useState<HostedUser | null>(null)
  const [orgs, setOrgs] = useState<HostedOrganization[]>([])
  const [workspaces, setWorkspaces] = useState<HostedWorkspace[]>([])
  const [accountExport, setAccountExport] = useState<AccountExportPayload | null>(null)
  const [accountConsent, setAccountConsent] = useState<AccountConsent | null>(null)
  const [authSessions, setAuthSessions] = useState<AuthSessionsPayload | null>(null)
  const [inviteEmail, setInviteEmail] = useState('outsider@example.test')
  const [inviteRole, setInviteRole] = useState('viewer')
  const [inviteToken, setInviteToken] = useState('')
  const [inviteEvidence, setInviteEvidence] = useState('')
  const [authProvider, setAuthProvider] = useState<'local_dev' | 'password'>('local_dev')
  const [passwordEmail, setPasswordEmail] = useState('new-advisor@example.test')
  const [passwordDisplayName, setPasswordDisplayName] = useState('New Advisor')
  const [passwordValue, setPasswordValue] = useState('long enough demo password')
  const [verificationToken, setVerificationToken] = useState('')
  const [resetEmail, setResetEmail] = useState('new-advisor@example.test')
  const [resetToken, setResetToken] = useState('')
  const [newPasswordValue, setNewPasswordValue] = useState('brand new demo password')
  const [passwordAuthEvidence, setPasswordAuthEvidence] = useState('')
  const [localPreviewProbe, setLocalPreviewProbe] = useState<WebGpuPreviewProbeResult>(disabledWebGpuPreviewState)
  const [localInferencePreview, setLocalInferencePreview] = useState<LocalInferencePreviewState>(() =>
    buildLocalInferencePreviewState({ featureEnabled: isWebGpuPreviewEnabled(), webGpuProbe: disabledWebGpuPreviewState() }),
  )
  const [lowBandwidthPreference, setLowBandwidthPreference] = useState<Phase6LowBandwidthPreference>(() => loadPhase6LowBandwidthPreference())
  const [lowBandwidthDetection] = useState(() => detectPhase6LowBandwidth())
  const [workspaceId, setWorkspaceId] = useState('')
  const [fieldContexts, setFieldContexts] = useState<HostedFieldContext[]>([])
  const [fieldContextId, setFieldContextId] = useState('')
  const [sampleFieldContextId, setSampleFieldContextId] = useState(phase6SampleFieldContexts[0].id)
  const [geoLocationText, setGeoLocationText] = useState('Iowa Des Moines Lobe')
  const [geoPriors, setGeoPriors] = useState<HostedGeoPriors | null>(null)
  const [threadId, setThreadId] = useState('')
  const [threads, setThreads] = useState<HostedThread[]>([])
  const [thread, setThread] = useState<HostedThread | null>(null)
  const [trace, setTrace] = useState<HostedTraceBundle | null>(null)
  const [phase5Trace, setPhase5Trace] = useState<Phase5AdminTrace | null>(null)
  const [threadTrainingEligible, setThreadTrainingEligible] = useState(true)
  const [threadTraceCapture, setThreadTraceCapture] = useState<'none' | 'operational' | 'research_opt_in'>('research_opt_in')
  const [dataSources, setDataSources] = useState<HostedDataSource[]>([])
  const [ingestJob, setIngestJob] = useState<HostedIngestJob | null>(null)
  const [ingestJobs, setIngestJobs] = useState<HostedIngestJob[]>([])
  const [corpusHealth, setCorpusHealth] = useState<HostedCorpusHealth | null>(null)
  const [quotaReport, setQuotaReport] = useState<HostedQuotaReport | null>(null)
  const [attachments, setAttachments] = useState<HostedAttachment[]>([])
  const [attachmentIncludeDeleted, setAttachmentIncludeDeleted] = useState(false)
  const [attachmentScope, setAttachmentScope] = useState<'thread' | 'workspace'>('thread')
  const [attachmentSensitivity, setAttachmentSensitivity] = useState<'low' | 'medium' | 'high'>('high')
  const [attachmentRetention, setAttachmentRetention] = useState<'default' | 'short' | 'extended' | 'delete_on_request'>('delete_on_request')
  const [attachmentUseMode, setAttachmentUseMode] = useState<AttachmentUseMode>('all')
  const [selectedAttachmentIds, setSelectedAttachmentIds] = useState<string[]>([])
  const [imagePreview, setImagePreview] = useState<Record<string, unknown> | null>(null)
  const [imageEvalReport, setImageEvalReport] = useState<Record<string, unknown> | null>(null)
  const [attachmentText, setAttachmentText] = useState('Private note: high phosphorus near a ditch. Use only inside this workspace.')
  const [imageAttachmentBase64, setImageAttachmentBase64] = useState(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  )
  const [preserveOriginalImageUpload, setPreserveOriginalImageUpload] = useState(false)
  const [evalCandidateFilter, setEvalCandidateFilter] = useState<EvalCandidateFilter>('all')
  const [evalCandidates, setEvalCandidates] = useState<HostedEvalCandidate[]>([])
  const [evalRuns, setEvalRuns] = useState<HostedEvalRun[]>([])
  const [changeProposals, setChangeProposals] = useState<HostedChangeProposal[]>([])
  const [hostedFeedbackRating, setHostedFeedbackRating] = useState<HostedFeedbackRating>('needs_work')
  const [hostedFeedbackQuickTag, setHostedFeedbackQuickTag] = useState('missing_important_context')
  const [hostedFeedbackTriageTag, setHostedFeedbackTriageTag] = useState('retrieval_miss')
  const [hostedFeedbackCorrection, setHostedFeedbackCorrection] = useState('Ask for local calibration and runoff-path details.')
  const [hostedFeedbackIdeal, setHostedFeedbackIdeal] = useState('Lead with water-quality pathway and avoid additional P until risk is assessed.')
  const [hostedFeedbackTrainingConsent, setHostedFeedbackTrainingConsent] = useState(true)
  const [exports, setExports] = useState<HostedExport[]>([])
  const [exportJobs, setExportJobs] = useState<HostedExportJob[]>([])
  const [exportThreadFilter, setExportThreadFilter] = useState<'active' | 'workspace'>('active')
  const [exportTypeFilter, setExportTypeFilter] = useState('')
  const [exportLimit, setExportLimit] = useState(25)
  const [auditEvents, setAuditEvents] = useState<HostedAuditEvent[]>([])
  const [adminOps, setAdminOps] = useState<AdminOpsSummary | null>(null)
  const [message, setMessage] = useState('A corn field has high soil-test phosphorus near a ditch. What should we check?')
  const [events, setEvents] = useState<StreamEvent[]>([])
  const [deferredActionCount, setDeferredActionCount] = useState(() => listPhase6DeferredActions().length)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  const headers = useMemo(
    () => ({
      'content-type': 'application/json',
      'X-Agronomy-User-Email': email,
      'X-Agronomy-User-Name': 'Hosted Advisor',
    }),
    [email],
  )
  const selectedFieldContext = useMemo(
    () => fieldContexts.find((item) => item.id === fieldContextId) || null,
    [fieldContexts, fieldContextId],
  )
  const selectedFieldContextReadiness = useMemo(
    () => buildFieldContextReadiness(selectedFieldContext),
    [selectedFieldContext],
  )
  const selectedSampleFieldContext = useMemo(
    () => phase6SampleFieldContexts.find((item) => item.id === sampleFieldContextId) || phase6SampleFieldContexts[0],
    [sampleFieldContextId],
  )
  const lowBandwidthActive = isPhase6LowBandwidthActive(lowBandwidthPreference, lowBandwidthDetection)
  const lowBandwidthListLimit = lowBandwidthActive ? 5 : exportLimit
  const lowBandwidthStatus = phase6LowBandwidthSummary(lowBandwidthPreference, lowBandwidthDetection)

  useEffect(() => {
    configureFrontendRum({ workspaceId, threadId })
  }, [workspaceId, threadId])

  const request = async <T,>(
    path: string,
    init?: RequestInit,
    options: { includeLocalDevIdentity?: boolean } = {},
  ): Promise<T> =>
    decode<T>(
      await fetch(path, {
        ...init,
        headers: {
          'content-type': 'application/json',
          ...(options.includeLocalDevIdentity === false ? {} : headers),
          ...csrfHeaders(),
          ...(init?.headers || {}),
        },
      }),
    )

  const isOffline = () => typeof navigator !== 'undefined' && navigator.onLine === false
  const refreshDeferredActionCount = () => setDeferredActionCount(listPhase6DeferredActions().length)

  const runHostedAction = async (action: () => Promise<void>) => {
    setError('')
    try {
      await action()
    } catch (err) {
      setError(errorMessage(err))
      setStatus('Hosted request failed')
    }
  }

  const loadHostedAccount = async () => {
    const payload = await request<AuthPayload>('/auth/me')
    setUser(payload.user)
    setAccountConsent(payload.account_consent || payload.user.account_consent || null)
    setOrgs(payload.organizations)
    setWorkspaces(payload.workspaces)
    setAccountExport(null)
    setAuthSessions(null)
    const nextWorkspace = payload.workspaces[0]?.id || ''
    setWorkspaceId((current) => current || nextWorkspace)
    setStatus('Hosted account loaded')
  }

  const loadAuthSessions = async () => {
    const payload = await request<AuthSessionsPayload>('/auth/sessions')
    setAuthSessions(payload)
    setStatus('Auth sessions loaded')
  }

  const revokeAuthSessions = async () => {
    await request<Record<string, unknown>>('/auth/sessions/revoke-all', { method: 'POST' })
    setUser(null)
    setOrgs([])
    setWorkspaces([])
    setAccountExport(null)
    setAccountConsent(null)
    setAuthSessions(null)
    setWorkspaceId('')
    resetWorkspaceScopedState()
    setStatus('Sessions revoked')
  }

  const signupWithPassword = async () => {
    sendFrontendEvent('auth_flow_started', { flow: 'password_signup' })
    let payload: PasswordSignupPayload
    try {
      payload = await request<PasswordSignupPayload>(
        '/auth/signup',
        {
          method: 'POST',
          body: JSON.stringify({ email: passwordEmail, password: passwordValue, display_name: passwordDisplayName }),
        },
        { includeLocalDevIdentity: false },
      )
    } catch (error) {
      sendFrontendEvent('auth_flow_failed', { flow: 'password_signup' })
      throw error
    }
    setVerificationToken(payload.dev_delivery?.token || '')
    setPasswordAuthEvidence(`${payload.schema_version} ${payload.status} ${payload.email}`)
    sendFrontendEvent('auth_flow_completed', { flow: 'password_signup', status: payload.status })
    setStatus('Password signup verification required')
  }

  const verifyPasswordEmail = async () => {
    sendFrontendEvent('auth_flow_started', { flow: 'password_verify_email' })
    let payload: PasswordVerificationPayload
    try {
      payload = await request<PasswordVerificationPayload>(
        '/auth/verify-email',
        { method: 'POST', body: JSON.stringify({ token: verificationToken }) },
        { includeLocalDevIdentity: false },
      )
    } catch (error) {
      sendFrontendEvent('auth_flow_failed', { flow: 'password_verify_email' })
      throw error
    }
    setUser(payload.user)
    setPasswordAuthEvidence(`${payload.schema_version} ${payload.status}`)
    sendFrontendEvent('auth_flow_completed', { flow: 'password_verify_email', status: payload.status })
    setStatus('Password email verified')
  }

  const loginWithPassword = async () => {
    sendFrontendEvent('auth_flow_started', { flow: 'password_login' })
    let payload: PasswordLoginPayload
    try {
      payload = await request<PasswordLoginPayload>(
        '/auth/password-login',
        { method: 'POST', body: JSON.stringify({ email: passwordEmail, password: passwordValue }) },
        { includeLocalDevIdentity: false },
      )
    } catch (error) {
      sendFrontendEvent('auth_flow_failed', { flow: 'password_login' })
      throw error
    }
    setUser(payload.user)
    setAccountExport(null)
    setAuthSessions(null)
    setPasswordAuthEvidence(`${payload.schema_version} csrf ${String(Boolean(payload.csrf_token))}`)
    sendFrontendEvent('auth_flow_completed', { flow: 'password_login', csrf_ready: Boolean(payload.csrf_token) })
    setStatus('Password login complete')
  }

  const requestPasswordReset = async () => {
    const payload = await request<PasswordResetRequestPayload>(
      '/auth/password-reset/request',
      { method: 'POST', body: JSON.stringify({ email: resetEmail }) },
      { includeLocalDevIdentity: false },
    )
    setResetToken(payload.dev_delivery?.token || '')
    setPasswordAuthEvidence(`${payload.schema_version} ${payload.status}`)
    setStatus('Password reset requested')
  }

  const confirmPasswordReset = async () => {
    const payload = await request<PasswordResetConfirmPayload>(
      '/auth/password-reset/confirm',
      { method: 'POST', body: JSON.stringify({ token: resetToken, new_password: newPasswordValue }) },
      { includeLocalDevIdentity: false },
    )
    setUser(null)
    setAuthSessions(null)
    setPasswordAuthEvidence(`${payload.schema_version} ${payload.status} revoked ${String(payload.sessions_revoked)}`)
    setStatus('Password reset complete')
  }

  const exportAccountData = async () => {
    const payload = await request<AccountExportPayload>('/account/export')
    setAccountExport(payload)
    if (payload.account_consent) {
      setAccountConsent(payload.account_consent)
    }
    setStatus('Account data export ready')
  }

  const loadAccountConsent = async () => {
    const payload = await request<AccountConsentPayload>('/account/consent')
    setAccountConsent(payload.consent)
    setStatus('Account consent loaded')
  }

  const saveAccountConsent = async () => {
    if (!user || !accountConsent) {
      return
    }
    const payload = await request<AccountConsentPayload>('/account/consent', {
      method: 'PATCH',
      body: JSON.stringify({ ...accountConsent, confirm_email: user.email }),
    })
    setAccountConsent(payload.consent)
    setStatus('Account consent saved')
  }

  const deleteAccount = async () => {
    if (!user || !accountExport) {
      return
    }
    await request<Record<string, unknown>>('/account', {
      method: 'DELETE',
      body: JSON.stringify({ confirm_email: user.email, export_acknowledged: true }),
    })
    setUser(null)
    setOrgs([])
    setWorkspaces([])
    setAccountExport(null)
    setAccountConsent(null)
    setAuthSessions(null)
    setWorkspaceId('')
    resetWorkspaceScopedState()
    setStatus('Account deleted')
  }

  const probeLocalPreview = async () => {
    const featureEnabled = isWebGpuPreviewEnabled()
    const disabledPreview = disabledWebGpuPreviewState()
    sendRumMetric({
      metric_name: 'model_download_notice',
      value: featureEnabled ? 1 : 0,
      unit: 'count',
      metadata: { feature_enabled: featureEnabled, canonical_answer_path: disabledPreview.canonicalAnswerPath },
    })
    const result = await probeWebGpuPreview({ featureEnabled })
    setLocalPreviewProbe(result)
    setLocalInferencePreview(buildLocalInferencePreviewState({ featureEnabled, webGpuProbe: result }))
    sendFrontendEvent('webgpu_probe_completed', {
      feature_enabled: featureEnabled,
      status: result.status,
      webgpu_available: Boolean(result.adapterAvailable),
    })
    setStatus(`Local preview ${result.status}`)
  }

  const resetWorkspaceScopedState = () => {
    setFieldContexts([])
    setFieldContextId('')
    setGeoPriors(null)
    setThreads([])
    setThreadId('')
    setThread(null)
    setTrace(null)
    setThreadTrainingEligible(true)
    setThreadTraceCapture('research_opt_in')
    setDataSources([])
    setIngestJob(null)
    setIngestJobs([])
    setCorpusHealth(null)
    setQuotaReport(null)
    setAttachments([])
    setAttachmentIncludeDeleted(false)
    setAttachmentScope('thread')
    setAttachmentUseMode('all')
    setSelectedAttachmentIds([])
    setImagePreview(null)
    setImageEvalReport(null)
    setEvalCandidateFilter('all')
    setEvalCandidates([])
    setEvalRuns([])
    setChangeProposals([])
    setExports([])
    setExportJobs([])
    setExportThreadFilter('active')
    setExportTypeFilter('')
    setExportLimit(25)
    setAuditEvents([])
    setAdminOps(null)
  }

  const createDemoWorkspace = async () => {
    const suffix = Date.now().toString(36)
    const org = await request<HostedOrganization>('/orgs', {
      method: 'POST',
      body: JSON.stringify({ name: `Hosted Demo Org ${suffix}` }),
    })
    const workspace = await request<HostedWorkspace>('/workspaces', {
      method: 'POST',
      body: JSON.stringify({ organization_id: org.id, name: `Hosted demo workspace ${suffix}` }),
    })
    setOrgs([org])
    setWorkspaces([workspace])
    setWorkspaceId(workspace.id)
    resetWorkspaceScopedState()
    setStatus('Workspace created')
  }

  const createWorkspaceInvite = async () => {
    const inviteOrg = orgs.find((item) => item.id === workspaces.find((workspace) => workspace.id === workspaceId)?.organization_id) || orgs[0]
    if (!inviteOrg) {
      return
    }
    const invite = await request<WorkspaceInvitePayload>(`/orgs/${inviteOrg.id}/invites`, {
      method: 'POST',
      body: JSON.stringify({
        email: inviteEmail,
        role: inviteRole,
        expires_in_hours: 72,
      }),
    })
    setInviteToken(invite.invite_token)
    setInviteEvidence(`${invite.role} invite for ${invite.email} expires ${invite.expires_at}`)
    setStatus('Workspace invite created')
  }

  const acceptWorkspaceInvite = async () => {
    if (!inviteToken.trim()) {
      return
    }
    const accepted = await request<WorkspaceInviteAcceptPayload>('/orgs/invites/accept', {
      method: 'POST',
      body: JSON.stringify({ token: inviteToken }),
    })
    setOrgs((current) => {
      const remaining = current.filter((item) => item.id !== accepted.organization.id)
      return [...remaining, accepted.organization]
    })
    setInviteEvidence(`Accepted ${accepted.membership.role} invite for ${accepted.organization.name}`)
    setStatus('Workspace invite accepted')
  }

  const deleteWorkspace = async () => {
    if (!workspaceId) {
      return
    }
    const deleted = await request<HostedWorkspace & { deleted_at?: string; deletion_summary?: Record<string, unknown> }>(`/workspaces/${workspaceId}`, {
      method: 'DELETE',
    })
    const remaining = workspaces.filter((item) => item.id !== deleted.id)
    setWorkspaces(remaining)
    setWorkspaceId(remaining[0]?.id || '')
    resetWorkspaceScopedState()
    setStatus('Workspace deleted')
  }

  const createFieldContext = async () => {
    if (!workspaceId) {
      return
    }
    const created = await request<HostedFieldContext>('/field-contexts', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        ...selectedSampleFieldContext.body,
      }),
    })
    setFieldContexts((current) => [created, ...current.filter((item) => item.id !== created.id)])
    setFieldContextId(created.id)
    setGeoLocationText(created.region_text || selectedSampleFieldContext.body.region_text)
    sendFrontendEvent('field_context_created', { conceptual_ready: Boolean(created.quality_meter?.ready?.conceptual_answer) })
    setStatus('Field context created')
  }

  const runGeoPriors = async () => {
    if (!workspaceId || !geoLocationText.trim()) {
      return
    }
    const priors = await request<HostedGeoPriors>('/geo/priors', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        field_context_id: fieldContextId || undefined,
        location_text: geoLocationText,
      }),
    })
    setGeoPriors(priors)
    setStatus(`Geo priors loaded: ${priors.uncertainty}`)
  }

  const loadFieldContexts = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const loaded = await request<HostedFieldContext[]>(`/field-contexts?workspace_id=${nextWorkspaceId}`)
    setFieldContexts(loaded)
    setFieldContextId((current) => current || loaded[0]?.id || '')
  }

  const updateFieldContext = async () => {
    const selected = fieldContexts.find((item) => item.id === fieldContextId) || fieldContexts[0]
    if (!selected) {
      return
    }
    const updated = await request<HostedFieldContext>(`/field-contexts/${selected.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        display_name: `${selected.display_name.replace(/ updated$/, '')} updated`,
        management_notes: 'Reviewed in hosted cockpit.',
      }),
    })
    setFieldContexts((current) => current.map((item) => (item.id === updated.id ? updated : item)))
    setFieldContextId(updated.id)
    sendFrontendEvent('field_context_edited', { conceptual_ready: Boolean(updated.quality_meter?.ready?.conceptual_answer) })
    await loadAuditEvents(updated.workspace_id)
    setStatus('Field context updated')
  }

  const deleteFieldContext = async () => {
    const selected = fieldContexts.find((item) => item.id === fieldContextId) || fieldContexts[0]
    if (!selected) {
      return
    }
    const deleted = await request<HostedFieldContext>(`/field-contexts/${selected.id}`, {
      method: 'DELETE',
    })
    setFieldContexts((current) => current.filter((item) => item.id !== deleted.id))
    setFieldContextId((current) => (current === deleted.id ? '' : current))
    await loadAuditEvents(deleted.workspace_id)
    setStatus('Field context deleted')
  }

  const createHostedThread = async () => {
    if (!workspaceId) {
      return
    }
    const created = await request<HostedThread>('/threads', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        title: 'Hosted phosphorus review',
        mode: 'agronomic_rag',
        field_context_id: fieldContextId || undefined,
        trace_capture_level: threadTraceCapture,
        model_profile_id: 'mock',
        training_eligible: threadTrainingEligible,
      }),
    })
    setThreadId(created.id)
    setThread(created)
    setThreadTrainingEligible(Boolean(created.training_eligible))
    setThreadTraceCapture(created.trace_capture_level || 'operational')
    setThreads((current) => [created, ...current.filter((item) => item.id !== created.id)])
    sendFrontendEvent('thread_created', {
      has_field_context: Boolean(created.field_context_id),
      trace_capture_level: created.trace_capture_level || 'operational',
      training_eligible: Boolean(created.training_eligible),
    })
    await loadQuotaReport(created.workspace_id)
    setStatus('Thread created')
  }

  const loadThreads = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const startedAt = startFrontendMeasure()
    const loaded = await request<HostedThread[]>(`/threads?workspace_id=${nextWorkspaceId}`)
    setThreads(loaded)
    const nextThread = loaded[0]
    if (nextThread) {
      setThreadId(nextThread.id)
      setThread(nextThread)
      setThreadTrainingEligible(Boolean(nextThread.training_eligible))
      setThreadTraceCapture(nextThread.trace_capture_level || 'operational')
    }
    sendFrontendMeasure('render_time', startedAt, { action: 'load_threads', thread_count: loaded.length })
  }

  const loadTrace = async (nextThreadId = threadId) => {
    if (!nextThreadId) {
      return
    }
    const loaded = await request<HostedTraceBundle>(`/threads/${nextThreadId}/trace`)
    setTrace(loaded)
  }

  const sendHostedMessage = async () => {
    if (!workspaceId || !message.trim()) {
      return
    }
    const startedAt = startFrontendMeasure()
    const activeThreadId = threadId || thread?.id
    const activeAttachments = attachments.filter((item) => !item.deleted_at)
    const selectedActiveAttachmentIds = attachmentUseMode === 'none'
      ? []
      : attachmentUseMode === 'selected'
        ? activeAttachments.filter((item) => selectedAttachmentIds.includes(item.id)).map((item) => item.id)
        : activeAttachments.map((item) => item.id)
    const activeAttachmentIds = lowBandwidthActive ? [] : selectedActiveAttachmentIds
    sendFrontendEvent('message_submitted', {
      has_thread: Boolean(activeThreadId),
      has_field_context: Boolean(fieldContextId),
      attachment_count: activeAttachmentIds.length,
      attachment_mode: attachmentUseMode,
      skipped_attachment_count: selectedActiveAttachmentIds.length - activeAttachmentIds.length,
      low_bandwidth: lowBandwidthActive,
      low_bandwidth_preference: lowBandwidthPreference,
    })
    if (fieldContextId) {
      sendFrontendEvent('field_context_used', { source: 'hosted_chat' })
    }
    const response = await fetch('/chat/stream', {
      method: 'POST',
      headers: { ...headers, ...csrfHeaders() },
      body: JSON.stringify({
        workspace_id: workspaceId,
        thread_id: activeThreadId || undefined,
        field_context_id: fieldContextId || undefined,
        attachment_ids: activeAttachmentIds,
        message,
        mode: 'agronomic_rag',
        model_profile_id: 'mock',
        trace_capture_level: 'research_opt_in',
        research_consent: true,
      }),
    })
    if (!response.ok) {
      throw new Error(`${response.status}: ${await response.text()}`)
    }
    sendFrontendEvent('answer_stream_started', { has_thread: Boolean(activeThreadId) })
    const parsed = parseSseEvents(await response.text())
    setEvents(parsed)
    if (parsed.length > 0) {
      sendFrontendMeasure('first_visible_progress', startedAt, { action: 'hosted_chat_stream', event_count: parsed.length })
      sendFrontendEvent('answer_stream_first_token', { event_count: parsed.length })
    }
    const tracePersisted = parsed.find((item) => item.event === 'trace.persisted')
    const phase5TraceId = String(tracePersisted?.payload.phase5_trace_id || '')
    if (phase5TraceId && capabilities.canAdmin) {
      setPhase5Trace(await request<Phase5AdminTrace>(`/api/admin/traces/${phase5TraceId}`))
    } else {
      setPhase5Trace(null)
    }
    const completed = parsed.find((item) => item.event === 'model.completed')
    const nextThreadId = String(completed?.payload.thread_id || activeThreadId || '')
    if (nextThreadId) {
      const loadedThread = await request<HostedThread>(`/threads/${nextThreadId}`)
      setThreadId(nextThreadId)
      setThread(loadedThread)
      await loadTrace(nextThreadId)
    }
    sendFrontendEvent('answer_stream_completed', {
      event_count: parsed.length,
      has_trace: Boolean(phase5TraceId),
    })
    await loadQuotaReport(workspaceId)
    setStatus('Hosted chat completed')
  }

  const loadAttachments = async (nextWorkspaceId = workspaceId, includeDeleted = attachmentIncludeDeleted) => {
    if (!nextWorkspaceId) {
      return
    }
    const params = new URLSearchParams({ workspace_id: nextWorkspaceId })
    if (includeDeleted) {
      params.set('include_deleted', 'true')
    }
    const loaded = await request<HostedAttachment[]>(`/attachments?${params.toString()}`)
    setAttachments(loaded)
    setSelectedAttachmentIds((current) => current.filter((id) => loaded.some((item) => item.id === id && !item.deleted_at)))
  }

  const createAttachment = async () => {
    if (!workspaceId || !attachmentText.trim()) {
      return
    }
    const created = await request<HostedAttachment>('/attachments', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        thread_id: attachmentScope === 'thread' && threadId ? threadId : undefined,
        filename: 'hosted-field-note.txt',
        content_type: 'text/plain',
        text_content: attachmentText,
        sensitivity: attachmentSensitivity,
        retention_policy: attachmentRetention,
      }),
    })
    setAttachments((current) => [created, ...current.filter((item) => item.id !== created.id)])
    setSelectedAttachmentIds((current) => [created.id, ...current.filter((id) => id !== created.id)])
    await loadQuotaReport(created.workspace_id)
    setStatus('Private note uploaded')
  }

  const createImageAttachment = async () => {
    if (!workspaceId || !imageAttachmentBase64.trim()) {
      return
    }
    const preparedImage = await preparePhase6ImageUpload(imageAttachmentBase64, {
      preserveOriginal: preserveOriginalImageUpload,
    })
    const created = await request<HostedAttachment>('/attachments', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        thread_id: attachmentScope === 'thread' && threadId ? threadId : undefined,
        filename: preparedImage.contentType === 'image/jpeg' ? 'hosted-scouting-image.jpg' : 'hosted-scouting-image.png',
        content_type: preparedImage.contentType,
        base64_content: preparedImage.base64Content,
        modality: 'image',
        sensitivity: attachmentSensitivity,
        retention_policy: attachmentRetention,
        client_preprocessing: preparedImage.metadata,
      }),
    })
    setAttachments((current) => [created, ...current.filter((item) => item.id !== created.id)])
    setSelectedAttachmentIds((current) => [created.id, ...current.filter((id) => id !== created.id)])
    await loadQuotaReport(created.workspace_id)
    setStatus('Image uploaded for research preview')
  }

  const deleteAttachment = async () => {
    const attachment = attachments.find((item) => !item.deleted_at && selectedAttachmentIds.includes(item.id)) || attachments.find((item) => !item.deleted_at)
    if (!attachment) {
      return
    }
    await request<HostedAttachment>(`/attachments/${attachment.id}`, { method: 'DELETE' })
    await loadAttachments()
    await loadQuotaReport(attachment.workspace_id)
    setStatus('Private note deleted')
  }

  const toggleSelectedAttachment = (attachmentId: string, checked: boolean) => {
    setSelectedAttachmentIds((current) =>
      checked ? [attachmentId, ...current.filter((id) => id !== attachmentId)] : current.filter((id) => id !== attachmentId),
    )
  }

  const loadDataSources = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const loaded = await request<HostedDataSource[]>(`/data-sources?workspace_id=${nextWorkspaceId}`)
    setDataSources(loaded)
  }

  const loadCorpusHealth = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const loaded = await request<HostedCorpusHealth>(`/corpus-health?workspace_id=${nextWorkspaceId}`)
    setCorpusHealth(loaded)
  }

  const loadIngestJobs = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const loaded = await request<HostedIngestJob[]>(`/ingest-jobs?workspace_id=${nextWorkspaceId}`)
    setIngestJobs(loaded)
  }

  const loadQuotaReport = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const loaded = await request<HostedQuotaReport>(`/quotas?workspace_id=${nextWorkspaceId}`)
    setQuotaReport(loaded)
  }

  const createDataSource = async () => {
    if (!workspaceId) {
      return
    }
    const created = await request<HostedDataSource>('/data-sources', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        source_id: `demo_fertility_source_${Date.now().toString(36)}`,
        title: 'Demo fertility source',
        publisher: 'Example Extension',
        canonical_url: 'https://example.test/fertility',
        text_content:
          'Demo fertility source. High soil-test phosphorus near a ditch should trigger water-quality pathway review, local soil-test method checks, and setback/runoff context before adding more phosphorus.',
        license_state: 'review_required',
        rag_eligible: true,
        sft_eligible: false,
        source_kind: 'public_extension',
        crops: ['corn'],
        regions: ['Iowa'],
        buckets: ['nutrient_management'],
      }),
    })
    setDataSources((current) => [created, ...current.filter((item) => item.id !== created.id)])
    await loadQuotaReport()
    setStatus('Data source registered')
  }

  const updateDataSource = async () => {
    const activeSource = dataSources[0]
    if (!activeSource) {
      return
    }
    const updated = await request<HostedDataSource>(`/data-sources/${activeSource.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        title: `${activeSource.title.replace(/ reviewed$/, '')} reviewed`,
        license_state: 'approved',
        rag_eligible: true,
        metadata: { reviewed_in_cockpit: true },
      }),
    })
    setDataSources((current) => current.map((item) => (item.id === updated.id ? updated : item)))
    await Promise.all([loadQuotaReport(updated.workspace_id), loadCorpusHealth(updated.workspace_id), loadAuditEvents(updated.workspace_id)])
    setStatus('Data source updated')
  }

  const deleteDataSource = async () => {
    const activeSource = dataSources[0]
    if (!activeSource) {
      return
    }
    const deleted = await request<HostedDataSource>(`/data-sources/${activeSource.id}`, {
      method: 'DELETE',
    })
    setDataSources((current) => current.filter((item) => item.id !== deleted.id))
    await Promise.all([loadQuotaReport(deleted.workspace_id), loadCorpusHealth(deleted.workspace_id), loadAuditEvents(deleted.workspace_id)])
    setStatus('Data source deleted')
  }

  const queueDataSourceIngest = async () => {
    const activeSource = dataSources[0]
    if (!activeSource) {
      return
    }
    const queued = await request<HostedIngestJob>(`/data-sources/${activeSource.id}/ingest`, {
      method: 'POST',
    })
    setIngestJob(queued)
    await Promise.all([loadCorpusHealth(), loadIngestJobs()])
    setStatus('Ingest queued')
  }

  const runLocalIngestWorker = async () => {
    if (!ingestJob) {
      return
    }
    const updated = await request<HostedIngestJob>(`/ingest-jobs/${ingestJob.id}/run`, {
      method: 'POST',
    })
    setIngestJob(updated)
    setIngestJobs((current) => current.map((item) => (item.id === updated.id ? updated : item)))
    await Promise.all([loadCorpusHealth(), loadIngestJobs()])
    setStatus(`Ingest ${updated.status}`)
  }

  const saveHostedFeedback = async () => {
    const activeThread = thread
    const assistant = [...(activeThread?.messages || [])].reverse().find((item) => item.actor === 'assistant')
    if (!activeThread || !assistant) {
      return
    }
    const body = {
      rating: hostedFeedbackRating,
      failure_tags: [hostedFeedbackQuickTag, hostedFeedbackTriageTag].filter(Boolean),
      human_correction: hostedFeedbackCorrection.trim() || undefined,
      ideal_answer: hostedFeedbackIdeal.trim() || undefined,
      training_consent: hostedFeedbackTrainingConsent,
    }
    if (isOffline()) {
      enqueuePhase6DeferredAction({
        kind: 'hosted_feedback',
        path: `/messages/${assistant.id}/feedback`,
        method: 'POST',
        body,
        workspaceId: activeThread.workspace_id || workspaceId,
        threadId: activeThread.id,
      })
      refreshDeferredActionCount()
      sendFrontendEvent('feedback_submitted', { status: 'queued_offline', failure_tag_count: body.failure_tags.length, training_consent: body.training_consent })
      setStatus('Feedback saved locally for retry')
      return
    }
    await request(`/messages/${assistant.id}/feedback`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
    sendFrontendEvent('feedback_submitted', { status: 'submitted', failure_tag_count: body.failure_tags.length, training_consent: body.training_consent })
    await loadTrace()
    await loadEvalCandidates(activeThread.workspace_id || workspaceId)
    setStatus('Feedback saved')
  }

  const loadEvalCandidates = async (nextWorkspaceId = workspaceId, nextFilter: EvalCandidateFilter = evalCandidateFilter) => {
    if (!nextWorkspaceId) {
      return
    }
    const params = new URLSearchParams({ workspace_id: nextWorkspaceId })
    if (nextFilter !== 'all') {
      params.set('review_status', nextFilter)
    }
    const loaded = await request<HostedEvalCandidate[]>(`/eval-candidates?${params.toString()}`)
    setEvalCandidates(loaded)
  }

  const loadEvalRuns = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const loaded = await request<HostedEvalRun[]>(`/eval-runs?workspace_id=${nextWorkspaceId}`)
    setEvalRuns(loaded)
  }

  const loadAuditEvents = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const loaded = await request<HostedAuditEvent[]>(`/audit-events?workspace_id=${nextWorkspaceId}&limit=25`)
    setAuditEvents(loaded)
  }

  const loadAdminOps = async () => {
    if (!workspaceId) {
      return
    }
    const optionalAdminOps = async <T,>(label: string, path: string): Promise<{ value: T | null; failure: string | null }> => {
      try {
        return { value: await request<T>(path), failure: null }
      } catch (error) {
        return { value: null, failure: `${label}: ${errorMessage(error)}` }
      }
    }
    const [health, metrics, monitoring, latency, frontendRum, frontendEvents, adminAuditEvents] = await Promise.all([
      request<Record<string, unknown>>(`/admin/health?workspace_id=${workspaceId}`),
      request<Record<string, unknown>>(`/admin/metrics?workspace_id=${workspaceId}`),
      request<Record<string, unknown>>(`/admin/monitoring?workspace_id=${workspaceId}`),
      optionalAdminOps<Phase5LatencyDashboard>('Phase 5 latency', `/api/admin/latency?workspace_id=${workspaceId}`),
      optionalAdminOps<Record<string, unknown>>('Frontend RUM', `/api/admin/frontend-rum?workspace_id=${workspaceId}`),
      optionalAdminOps<Record<string, unknown>>('Frontend events', `/api/admin/frontend-events?workspace_id=${workspaceId}`),
      request<HostedAuditEvent[]>(`/admin/audit-events?workspace_id=${workspaceId}&limit=10`),
    ])
    const failures = [latency.failure, frontendRum.failure, frontendEvents.failure].filter((failure): failure is string => Boolean(failure))
    setAdminOps({
      health,
      metrics,
      monitoring,
      latency: latency.value,
      frontendRum: frontendRum.value,
      frontendEvents: frontendEvents.value,
      auditEvents: adminAuditEvents,
      failures,
    })
    setStatus(failures.length > 0 ? `Admin operations loaded with ${failures.length} observability warning${failures.length === 1 ? '' : 's'}` : 'Admin operations loaded')
  }

  const approveEvalCandidate = async () => {
    const candidate = evalCandidates.find((item) => item.review_status === 'pending') || evalCandidates[0]
    if (!candidate) {
      return
    }
    const reviewed = await request<HostedEvalCandidate>(`/eval-candidates/${candidate.id}/review`, {
      method: 'POST',
      body: JSON.stringify({ review_status: 'approved_for_suite' }),
    })
    setEvalCandidates((current) => current.map((item) => (item.id === reviewed.id ? reviewed : item)))
    await loadTrace()
    setStatus('Eval candidate approved')
  }

  const runEvalReplay = async () => {
    if (!workspaceId) {
      return
    }
    const run = await request<HostedEvalRun>('/eval-runs', {
      method: 'POST',
      body: JSON.stringify({ workspace_id: workspaceId, name: 'Hosted feedback replay' }),
    })
    setEvalRuns((current) => [run, ...current.filter((item) => item.id !== run.id)])
    await loadQuotaReport(run.workspace_id)
    setStatus('Eval replay completed')
  }

  const loadChangeProposals = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const loaded = await request<HostedChangeProposal[]>(`/change-proposals?workspace_id=${nextWorkspaceId}`)
    setChangeProposals(loaded)
  }

  const createChangeProposal = async () => {
    if (!workspaceId) {
      return
    }
    const latestRun = evalRuns[0]
    const created = await request<HostedChangeProposal>('/change-proposals', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        title: 'Router local-calibration guard',
        target_component: 'router',
        proposal_type: 'router_patch',
        summary: 'Route high-phosphorus runoff questions through local calibration and water-quality checks.',
        rationale: 'Hosted feedback replay found a missed local calibration failure tag.',
        linked_eval_run_id: latestRun?.id,
      }),
    })
    setChangeProposals((current) => [created, ...current.filter((item) => item.id !== created.id)])
    await loadAuditEvents()
    setStatus('Change proposal created')
  }

  const requestChangeProposalEval = async () => {
    const proposal = changeProposals.find((item) => item.review_status === 'candidate') || changeProposals[0]
    if (!proposal) {
      return
    }
    const reviewed = await request<HostedChangeProposal>(`/change-proposals/${proposal.id}/review`, {
      method: 'POST',
      body: JSON.stringify({
        review_status: 'needs_eval',
        notes: 'Hold rollout until a passing before/after regression suite exists.',
      }),
    })
    setChangeProposals((current) => current.map((item) => (item.id === reviewed.id ? reviewed : item)))
    await loadAuditEvents()
    setStatus('Change proposal needs eval')
  }

  const exportHostedThread = async () => {
    if (!threadId) {
      return
    }
    const exportType = exportTypeFilter.trim() || 'json'
    sendFrontendEvent('report_export_started', { export_type: exportType, offline: isOffline(), low_bandwidth: lowBandwidthActive })
    if (isOffline()) {
      enqueuePhase6DeferredAction({
        kind: 'hosted_thread_export',
        path: `/threads/${threadId}/exports`,
        method: 'POST',
        body: { export_type: exportType },
        workspaceId: thread?.workspace_id || workspaceId,
        threadId,
      })
      refreshDeferredActionCount()
      sendFrontendEvent('report_export_completed', { export_type: exportType, status: 'queued_offline' })
      setStatus('Export saved locally for retry')
      return
    }
    const startedAt = startFrontendMeasure()
    try {
      await request(`/threads/${threadId}/exports`, {
        method: 'POST',
        body: JSON.stringify({ export_type: exportType }),
      })
      sendFrontendMeasure('standard_thread_report_preview', startedAt, { action: 'thread_export', export_type: exportType })
      sendFrontendEvent('report_export_completed', { export_type: exportType, status: 'submitted', low_bandwidth: lowBandwidthActive })
    } catch (error) {
      sendFrontendEvent('report_export_failed', { export_type: exportType, status: 'failed' })
      throw error
    }
    await loadTrace()
    await loadExportJobs(thread?.workspace_id || workspaceId)
    await loadExports(thread?.workspace_id || workspaceId)
    await loadAuditEvents(thread?.workspace_id || workspaceId)
    await loadQuotaReport(thread?.workspace_id || workspaceId)
    setStatus('Export queued')
  }

  const retryDeferredActions = async () => {
    const actions = listPhase6DeferredActions()
    if (actions.length === 0) {
      setStatus('No deferred actions to retry')
      return
    }
    let replayed = 0
    for (const action of actions) {
      await request(action.path, {
        method: action.method,
        body: JSON.stringify(action.body),
      })
      removePhase6DeferredAction(action.id)
      replayed += 1
    }
    refreshDeferredActionCount()
    await Promise.all([
      loadTrace(),
      loadExportJobs(thread?.workspace_id || workspaceId),
      loadExports(thread?.workspace_id || workspaceId),
      loadAuditEvents(thread?.workspace_id || workspaceId),
      loadQuotaReport(thread?.workspace_id || workspaceId),
    ])
    setStatus(`Retried ${replayed} deferred action${replayed === 1 ? '' : 's'}`)
  }

  const loadExports = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const params = new URLSearchParams({
      workspace_id: nextWorkspaceId,
      limit: String(lowBandwidthListLimit),
    })
    if (exportThreadFilter === 'active' && threadId) {
      params.set('thread_id', threadId)
    }
    if (exportTypeFilter.trim()) {
      params.set('export_type', exportTypeFilter.trim())
    }
    const loaded = await request<HostedExport[]>(`/exports?${params.toString()}`)
    setExports(loaded)
  }

  const loadExportJobs = async (nextWorkspaceId = workspaceId) => {
    if (!nextWorkspaceId) {
      return
    }
    const params = new URLSearchParams({
      workspace_id: nextWorkspaceId,
      limit: String(lowBandwidthListLimit),
    })
    if (exportThreadFilter === 'active' && threadId) {
      params.set('thread_id', threadId)
    }
    const loaded = await request<HostedExportJob[]>(`/export-jobs?${params.toString()}`)
    setExportJobs(loaded)
  }

  const updateThreadConsent = async () => {
    if (!threadId) {
      return
    }
    const updated = await request<HostedThread>(`/threads/${threadId}`, {
      method: 'PATCH',
      body: JSON.stringify({
        training_eligible: threadTrainingEligible,
        trace_capture_level: threadTraceCapture,
      }),
    })
    setThread(updated)
    setThreadTrainingEligible(Boolean(updated.training_eligible))
    setThreadTraceCapture(updated.trace_capture_level || 'operational')
    setThreads((current) => current.map((item) => (item.id === updated.id ? updated : item)))
    await loadTrace(updated.id)
    await loadAuditEvents(updated.workspace_id)
    setStatus('Thread consent updated')
  }

  const deleteHostedThread = async () => {
    if (!threadId) {
      return
    }
    const deleted = await request<HostedThread>(`/threads/${threadId}`, {
      method: 'DELETE',
    })
    setThreads((current) => current.filter((item) => item.id !== deleted.id))
    setThread(null)
    setThreadId('')
    setTrace(null)
    setEvents([])
    await Promise.all([loadQuotaReport(deleted.workspace_id), loadAuditEvents(deleted.workspace_id)])
    setStatus('Thread deleted')
  }

  const runImagePreview = async () => {
    if (!workspaceId) {
      return
    }
    const preview = await request<Record<string, unknown>>('/image-rag/query', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        thread_id: threadId || undefined,
        attachment_ids: attachments.filter((item) => !item.deleted_at).map((item) => item.id),
        question: 'What does this image suggest?',
      }),
    })
    setImagePreview(preview)
    setStatus(`Image research preview: ${String(preview.research_preview)}`)
  }

  const runImageEval = async () => {
    if (!workspaceId) {
      return
    }
    const report = await request<Record<string, unknown>>('/image-rag/evals', {
      method: 'POST',
      body: JSON.stringify({
        workspace_id: workspaceId,
        top_k: 1,
        samples: [
          {
            sample_id: 'demo_image_eval_hit',
            expected_label: 'corn_n_deficiency',
            predicted_label: 'corn_n_deficiency',
            predicted_confidence: 0.9,
            relevant_attachment_ids: ['demo_similar_leaf'],
            retrieved_attachment_ids: ['demo_similar_leaf'],
            expected_ood: false,
            abstained: false,
            answer_text: 'Candidate causes include nitrogen stress; do not recommend treatment without diagnosis.',
          },
          {
            sample_id: 'demo_image_eval_unsafe',
            expected_label: 'unknown_condition',
            predicted_label: 'corn_n_deficiency',
            predicted_confidence: 0.55,
            relevant_attachment_ids: ['demo_unknown'],
            retrieved_attachment_ids: [],
            expected_ood: true,
            abstained: false,
            answer_text: 'Apply a foliar product now.',
          },
        ],
      }),
    })
    setImageEvalReport(report)
    setStatus(`Image eval: ${String(report.metric_set)}`)
  }

  const latestAssistant = [...(thread?.messages || [])].reverse().find((item) => item.actor === 'assistant')
  const latestRetrievalPayload = asRecord([...((trace?.events || []).filter((item) => item.event_type === 'retrieval_result'))].pop()?.payload)
  const latestRetrievedDocs = Array.isArray(latestRetrievalPayload.retrieved_docs)
    ? latestRetrievalPayload.retrieved_docs.map(asRecord).filter((item) => item.doc_id || item.title)
    : []
  const selectedWorkspace = workspaces.find((item) => item.id === workspaceId)
  const selectedOrg = orgs.find((item) => item.id === selectedWorkspace?.organization_id) || orgs[0]
  const capabilities = roleCapabilities(selectedOrg?.role)
  const evalSummary = {
    total: evalCandidates.length,
    pending: evalCandidates.filter((item) => item.review_status === 'pending').length,
    approved: evalCandidates.filter((item) => item.review_status === 'approved_for_suite').length,
    rejected: evalCandidates.filter((item) => item.review_status === 'rejected').length,
  }
  const evalRunTrend = sortedEvalRuns(evalRuns).slice(0, 5)
  const latestEvalRun = evalRunTrend[0]
  const previousEvalRun = evalRunTrend[1]
  const latestEvalPromotion = latestEvalRun ? Boolean(latestEvalRun.gates.promotion_allowed) : false
  const latestEvalGateReasons = latestEvalRun ? asStringList(latestEvalRun.gates.reasons) : []
  const latestEvalFailureTags = latestEvalRun ? countEntries(latestEvalRun.metrics.failure_tag_counts) : []
  const latestEvalTargetCounts = latestEvalRun ? countEntries(latestEvalRun.metrics.target_component_counts) : []
  const latestEvalRegressionFailures = latestEvalRun ? regressionFailureRows(latestEvalRun.metrics.regression_failures) : []
  const latestEvalPassRate = latestEvalRun ? numberMetric(latestEvalRun.metrics.pass_rate) : null
  const previousEvalPassRate = previousEvalRun ? numberMetric(previousEvalRun.metrics.pass_rate) : null
  const evalPassRateDelta = latestEvalPassRate !== null && previousEvalPassRate !== null ? latestEvalPassRate - previousEvalPassRate : null
  const latestEvalFailures = latestEvalRun ? numberMetric(latestEvalRun.metrics.failure_case_count) || 0 : 0
  const previousEvalFailures = previousEvalRun ? numberMetric(previousEvalRun.metrics.failure_case_count) || 0 : null
  const evalFailureDelta = previousEvalFailures !== null ? latestEvalFailures - previousEvalFailures : null
  const candidateEvidence = evalCandidates.slice(0, 5).map((candidate) => ({
    candidate,
    feedback: asRecord(candidate.payload.feedback),
  }))
  const streamEventsWindow = virtualizePhase6List(events)
  const traceEventsWindow = virtualizePhase6List(trace?.events || [])
  const dataSourcesWindow = virtualizePhase6List(dataSources)
  const ingestJobsWindow = virtualizePhase6List(ingestJobs)
  const corpusSourcesWindow = virtualizePhase6List(corpusHealth?.sources || [])
  const evalCandidatesWindow = virtualizePhase6List(evalCandidates)
  const evalRunsWindow = virtualizePhase6List(evalRuns)
  const changeProposalsWindow = virtualizePhase6List(changeProposals)
  const auditEventsWindow = virtualizePhase6List(auditEvents)
  const exportsWindow = virtualizePhase6List(exports)
  const exportJobsWindow = virtualizePhase6List(exportJobs)

  return (
    <section data-testid="hosted-platform">
      <h2>Hosted Platform</h2>
      {error ? <p role="alert">{error}</p> : null}
      <label>
        Local-dev user
        <input data-testid="hosted-email" value={email} onChange={(event) => setEmail(event.target.value)} />
      </label>
      <label>
        Auth provider
        <select data-testid="hosted-auth-provider" value={authProvider} onChange={(event) => setAuthProvider(event.target.value as 'local_dev' | 'password')}>
          <option value="local_dev">Local dev header</option>
          <option value="password">Email and password</option>
        </select>
      </label>
      {authProvider === 'password' ? (
        <section data-testid="hosted-password-auth">
          <label>
            Email
            <input data-testid="hosted-password-email" value={passwordEmail} onChange={(event) => setPasswordEmail(event.target.value)} />
          </label>
          <label>
            Display name
            <input data-testid="hosted-password-name" value={passwordDisplayName} onChange={(event) => setPasswordDisplayName(event.target.value)} />
          </label>
          <label>
            Password
            <input data-testid="hosted-password-value" type="password" value={passwordValue} onChange={(event) => setPasswordValue(event.target.value)} />
          </label>
          <button type="button" data-testid="hosted-password-signup" onClick={() => void runHostedAction(signupWithPassword)}>
            Sign up
          </button>
          <label>
            Verification token
            <input data-testid="hosted-verification-token" value={verificationToken} onChange={(event) => setVerificationToken(event.target.value)} />
          </label>
          <button type="button" data-testid="hosted-password-verify" onClick={() => void runHostedAction(verifyPasswordEmail)} disabled={!verificationToken}>
            Verify email
          </button>
          <button type="button" data-testid="hosted-password-login" onClick={() => void runHostedAction(loginWithPassword)}>
            Password login
          </button>
          <label>
            Reset email
            <input data-testid="hosted-reset-email" value={resetEmail} onChange={(event) => setResetEmail(event.target.value)} />
          </label>
          <button type="button" data-testid="hosted-reset-request" onClick={() => void runHostedAction(requestPasswordReset)}>
            Request reset
          </button>
          <label>
            Reset token
            <input data-testid="hosted-reset-token" value={resetToken} onChange={(event) => setResetToken(event.target.value)} />
          </label>
          <label>
            New password
            <input data-testid="hosted-new-password" type="password" value={newPasswordValue} onChange={(event) => setNewPasswordValue(event.target.value)} />
          </label>
          <button type="button" data-testid="hosted-reset-confirm" onClick={() => void runHostedAction(confirmPasswordReset)} disabled={!resetToken}>
            Confirm reset
          </button>
          {passwordAuthEvidence ? <div data-testid="hosted-password-auth-evidence">{passwordAuthEvidence}</div> : null}
        </section>
      ) : null}
      <button type="button" data-testid="hosted-load-account" onClick={() => void runHostedAction(loadHostedAccount)}>
        Load hosted account
      </button>
      <button type="button" data-testid="hosted-export-account" onClick={() => void runHostedAction(exportAccountData)} disabled={!user}>
        Export account data
      </button>
      <button type="button" data-testid="hosted-load-auth-sessions" onClick={() => void runHostedAction(loadAuthSessions)} disabled={!user}>
        Load sessions
      </button>
      <button type="button" data-testid="hosted-revoke-auth-sessions" onClick={() => void runHostedAction(revokeAuthSessions)} disabled={!user}>
        Revoke sessions
      </button>
      <button type="button" data-testid="hosted-load-account-consent" onClick={() => void runHostedAction(loadAccountConsent)} disabled={!user}>
        Load consent
      </button>
      <section data-testid="hosted-low-bandwidth-panel">
        <label>
          Low-bandwidth mode
          <select
            data-testid="hosted-low-bandwidth-mode"
            value={lowBandwidthPreference}
            onChange={(event) => {
              const nextPreference = event.target.value as Phase6LowBandwidthPreference
              setLowBandwidthPreference(nextPreference)
              savePhase6LowBandwidthPreference(nextPreference)
            }}
          >
            <option value="auto">auto</option>
            <option value="on">on</option>
            <option value="off">off</option>
          </select>
        </label>
        <div data-testid="hosted-low-bandwidth-status">
          {lowBandwidthStatus} Active {String(lowBandwidthActive)}. Export list limit {lowBandwidthListLimit}.
        </div>
      </section>
      {accountConsent ? (
        <section data-testid="hosted-account-consent">
          <label>
            Trace storage
            <input
              type="checkbox"
              data-testid="hosted-consent-trace-storage"
              checked={accountConsent.trace_storage_enabled}
              onChange={(event) => setAccountConsent({ ...accountConsent, trace_storage_enabled: event.target.checked })}
            />
          </label>
          <label>
            Feedback use
            <input
              type="checkbox"
              data-testid="hosted-consent-feedback-use"
              checked={accountConsent.feedback_use_allowed}
              onChange={(event) => setAccountConsent({ ...accountConsent, feedback_use_allowed: event.target.checked })}
            />
          </label>
          <label>
            Training candidates
            <input
              type="checkbox"
              data-testid="hosted-consent-training"
              checked={accountConsent.training_candidate_allowed}
              onChange={(event) => setAccountConsent({ ...accountConsent, training_candidate_allowed: event.target.checked })}
            />
          </label>
          <label>
            Public examples
            <input
              type="checkbox"
              data-testid="hosted-consent-public-examples"
              checked={accountConsent.public_anonymized_examples_allowed}
              onChange={(event) => setAccountConsent({ ...accountConsent, public_anonymized_examples_allowed: event.target.checked })}
            />
          </label>
          <label>
            Product updates
            <input
              type="checkbox"
              data-testid="hosted-consent-product-updates"
              checked={accountConsent.product_updates_allowed}
              onChange={(event) => setAccountConsent({ ...accountConsent, product_updates_allowed: event.target.checked })}
            />
          </label>
          <label>
            Retention
            <select
              data-testid="hosted-consent-retention"
              value={accountConsent.retention_preference}
              onChange={(event) => setAccountConsent({ ...accountConsent, retention_preference: event.target.value as AccountConsent['retention_preference'] })}
            >
              <option value="default">Default</option>
              <option value="short">Short</option>
              <option value="delete_on_request">Delete on request</option>
            </select>
          </label>
          <button type="button" data-testid="hosted-save-account-consent" onClick={() => void runHostedAction(saveAccountConsent)} disabled={!user}>
            Save consent
          </button>
          <div data-testid="hosted-account-consent-summary">
            consent trace {String(accountConsent.trace_storage_enabled)} training {String(accountConsent.training_candidate_allowed)} retention {accountConsent.retention_preference}
          </div>
        </section>
      ) : null}
      <button type="button" data-testid="hosted-create-workspace" onClick={() => void runHostedAction(createDemoWorkspace)}>
        Create hosted workspace
      </button>
      <label>
        Invite email
        <input data-testid="hosted-invite-email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} />
      </label>
      <label>
        Invite role
        <select data-testid="hosted-invite-role" value={inviteRole} onChange={(event) => setInviteRole(event.target.value)}>
          <option value="viewer">Viewer</option>
          <option value="adviser">Adviser</option>
          <option value="researcher">Researcher</option>
          <option value="admin">Admin</option>
        </select>
      </label>
      <button type="button" data-testid="hosted-create-invite" onClick={() => void runHostedAction(createWorkspaceInvite)} disabled={!selectedOrg || !capabilities.canAdmin}>
        Create invite
      </button>
      <label>
        Invite token
        <input data-testid="hosted-invite-token" value={inviteToken} onChange={(event) => setInviteToken(event.target.value)} />
      </label>
      <button type="button" data-testid="hosted-accept-invite" onClick={() => void runHostedAction(acceptWorkspaceInvite)} disabled={!inviteToken.trim()}>
        Accept invite
      </button>
      {inviteEvidence ? <div data-testid="hosted-invite-evidence">{inviteEvidence}</div> : null}
      <button type="button" data-testid="hosted-delete-account" onClick={() => void runHostedAction(deleteAccount)} disabled={!user || !accountExport}>
        Delete account
      </button>

      {user ? <p data-testid="hosted-user">{user.email}</p> : null}
      {accountExport ? (
        <div data-testid="hosted-account-export">
          {accountExport.schema_version} - workspaces {accountExport.workspaces.length} - threads{' '}
          {accountExport.workspaces.reduce((total, item) => total + item.threads.length, 0)} - exports{' '}
          {accountExport.workspaces.reduce((total, item) => total + item.exports.length, 0)}
        </div>
      ) : null}
      {authSessions ? (
        <div data-testid="hosted-auth-sessions">
          {authSessions.schema_version} - active {authSessions.sessions.filter((item) => !item.revoked_at).length} - current{' '}
          {authSessions.sessions.find((item) => item.current)?.id || 'none'}
        </div>
      ) : null}
      <section data-testid="hosted-local-preview">
        <button type="button" data-testid="hosted-probe-local-preview" onClick={() => void runHostedAction(probeLocalPreview)} disabled={!isWebGpuPreviewEnabled()}>
          Probe local preview
        </button>
        <div>
          Local preview: {localPreviewProbe.status} - canonical path {localPreviewProbe.canonicalAnswerPath}
        </div>
        <p>{localPreviewProbe.message}</p>
        <ul>
          {localPreviewProbe.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <div data-testid="hosted-local-inference-matrix">
          <div>{localInferencePreview.noDownloadGuarantee}</div>
          <div>Local inference lanes: {localInferencePreview.capabilities.map((capability) => `${capability.label} ${capability.status}`).join(' | ')}</div>
          <ul>
            {localInferencePreview.decisions.slice(0, 4).map((decision) => (
              <li key={decision.taskId}>
                {decision.task}: {decision.outputLabel} - {decision.candidateRuntime} - download {String(decision.downloadAllowed)}
              </li>
            ))}
          </ul>
        </div>
      </section>
      {selectedOrg ? (
        <div data-testid="hosted-role-panel">
          Role: {capabilities.role} - write {String(capabilities.canWrite)} - research {String(capabilities.canReviewResearch)} - admin {String(capabilities.canAdmin)}
        </div>
      ) : null}
      {workspaces.length > 0 ? (
        <label>
          Workspace
          <select
            data-testid="hosted-workspace"
            value={workspaceId}
            onChange={(event) => {
              const nextWorkspaceId = event.target.value
              setWorkspaceId(nextWorkspaceId)
              resetWorkspaceScopedState()
              void runHostedAction(async () => {
                await loadFieldContexts(nextWorkspaceId)
                await loadThreads(nextWorkspaceId)
                await loadDataSources(nextWorkspaceId)
                await loadCorpusHealth(nextWorkspaceId)
                await loadAttachments(nextWorkspaceId)
                await loadEvalCandidates(nextWorkspaceId, 'all')
                await loadEvalRuns(nextWorkspaceId)
                await loadAuditEvents(nextWorkspaceId)
              })
            }}
          >
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <button type="button" data-testid="hosted-delete-workspace" onClick={() => void runHostedAction(deleteWorkspace)} disabled={!workspaceId || !capabilities.canAdmin}>
        Delete workspace
      </button>

      <label>
        Safe sample field
        <select
          data-testid="hosted-sample-field-context"
          value={sampleFieldContextId}
          onChange={(event) => {
            const nextId = event.target.value
            setSampleFieldContextId(nextId)
            const sample = phase6SampleFieldContexts.find((item) => item.id === nextId)
            if (sample) {
              setGeoLocationText(sample.body.region_text)
            }
          }}
        >
          {phase6SampleFieldContexts.map((sample) => (
            <option key={sample.id} value={sample.id}>
              {sample.label}
            </option>
          ))}
        </select>
      </label>
      <div data-testid="hosted-sample-field-context-summary">
        {selectedSampleFieldContext.body.crop_current} - {selectedSampleFieldContext.body.region_text}
      </div>
      <button type="button" data-testid="hosted-create-field-context" onClick={() => void runHostedAction(createFieldContext)} disabled={!workspaceId || !capabilities.canWrite}>
        Create field context
      </button>
      <button type="button" data-testid="hosted-load-field-contexts" onClick={() => void runHostedAction(() => loadFieldContexts())} disabled={!workspaceId}>
        Load field contexts
      </button>
      <button type="button" data-testid="hosted-update-field-context" onClick={() => void runHostedAction(updateFieldContext)} disabled={!fieldContextId || !capabilities.canWrite}>
        Update field context
      </button>
      <button type="button" data-testid="hosted-delete-field-context" onClick={() => void runHostedAction(deleteFieldContext)} disabled={!fieldContextId || !capabilities.canWrite}>
        Delete field context
      </button>
      {fieldContexts.length > 0 ? (
        <label>
          Field context
          <select
            data-testid="hosted-field-context"
            value={fieldContextId}
            onChange={(event) => setFieldContextId(event.target.value)}
          >
            {fieldContexts.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name} - {item.region_text}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {selectedFieldContext?.quality_meter ? (
        <div data-testid="hosted-field-context-quality">
          <p>{selectedFieldContext.quality_meter.summary}</p>
          <ul>
            {selectedFieldContext.quality_meter.checks.map((check) => (
              <li key={check.id}>
                {check.label}: {check.status}
              </li>
            ))}
          </ul>
          <p>{selectedFieldContext.quality_meter.product_rate_boundary}</p>
        </div>
      ) : null}
      <FieldContextReadinessPanel readiness={selectedFieldContextReadiness} />

      <label>
        Regional lookup
        <input
          data-testid="hosted-geo-location"
          value={geoLocationText}
          onChange={(event) => setGeoLocationText(event.target.value)}
        />
      </label>
      <button type="button" data-testid="hosted-run-geo-priors" onClick={() => void runHostedAction(runGeoPriors)} disabled={!workspaceId || !geoLocationText.trim()}>
        Lookup regional priors
      </button>
      {geoPriors ? (
        <div data-testid="hosted-geo-priors">
          <p>{geoPriors.ui_notice}</p>
          <p>Uncertainty: {geoPriors.uncertainty}</p>
          <p>Boosted namespaces: {geoPriors.boosted_namespaces.join(', ')}</p>
          <ul>
            {geoPriors.candidate_regions.map((item) => (
              <li key={`${item.layer}-${item.label}`}>
                {item.label} - {item.system} {item.code} - {item.priors.join(', ')}
              </li>
            ))}
          </ul>
          <p>Missing context: {geoPriors.missing_context.join(', ')}</p>
        </div>
      ) : null}

      <label>
        Private note
        <textarea
          data-testid="hosted-attachment-text"
          value={attachmentText}
          onChange={(event) => setAttachmentText(event.target.value)}
        />
      </label>
      <label>
        Upload scope
        <select data-testid="hosted-attachment-scope" value={attachmentScope} onChange={(event) => setAttachmentScope(event.target.value as 'thread' | 'workspace')}>
          <option value="thread">current thread</option>
          <option value="workspace">workspace library</option>
        </select>
      </label>
      <label>
        Sensitivity
        <select
          data-testid="hosted-attachment-sensitivity"
          value={attachmentSensitivity}
          onChange={(event) => setAttachmentSensitivity(event.target.value as 'low' | 'medium' | 'high')}
        >
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
        </select>
      </label>
      <label>
        Retention
        <select
          data-testid="hosted-attachment-retention"
          value={attachmentRetention}
          onChange={(event) => setAttachmentRetention(event.target.value as 'default' | 'short' | 'extended' | 'delete_on_request')}
        >
          <option value="delete_on_request">delete_on_request</option>
          <option value="short">short</option>
          <option value="default">default</option>
          <option value="extended">extended</option>
        </select>
      </label>
      <button type="button" data-testid="hosted-create-attachment" onClick={() => void runHostedAction(createAttachment)} disabled={!workspaceId || !attachmentText.trim() || !capabilities.canWrite}>
        Upload private note
      </button>
      <label>
        Image base64
        <textarea
          data-testid="hosted-image-base64"
          value={imageAttachmentBase64}
          onChange={(event) => setImageAttachmentBase64(event.target.value)}
        />
      </label>
      <label>
        <input
          type="checkbox"
          data-testid="hosted-preserve-original-image"
          checked={preserveOriginalImageUpload}
          onChange={(event) => setPreserveOriginalImageUpload(event.target.checked)}
        />
        Preserve original image upload
      </label>
      <button type="button" data-testid="hosted-create-image-attachment" onClick={() => void runHostedAction(createImageAttachment)} disabled={!workspaceId || !imageAttachmentBase64.trim() || !capabilities.canWrite}>
        Upload image
      </button>
      <button type="button" data-testid="hosted-load-attachments" onClick={() => void runHostedAction(() => loadAttachments())} disabled={!workspaceId}>
        Load attachments
      </button>
      <label>
        <input
          type="checkbox"
          data-testid="hosted-include-deleted-attachments"
          checked={attachmentIncludeDeleted}
          onChange={(event) => setAttachmentIncludeDeleted(event.target.checked)}
        />
        Include deleted uploads
      </label>
      <label>
        Chat upload use
        <select data-testid="hosted-attachment-use-mode" value={attachmentUseMode} onChange={(event) => setAttachmentUseMode(event.target.value as AttachmentUseMode)}>
          <option value="all">all active uploads</option>
          <option value="selected">selected uploads</option>
          <option value="none">none</option>
        </select>
      </label>
      <button type="button" data-testid="hosted-delete-attachment" onClick={() => void runHostedAction(deleteAttachment)} disabled={!attachments.some((item) => !item.deleted_at) || !capabilities.canWrite}>
        Delete selected attachment
      </button>
      {attachments.length > 0 ? (
        <ul data-testid="hosted-attachments">
          {attachments.map((item) => (
            <li key={item.id}>
              <label>
                <input
                  type="checkbox"
                  data-testid={`hosted-attachment-select-${item.id}`}
                  checked={selectedAttachmentIds.includes(item.id)}
                  disabled={Boolean(item.deleted_at)}
                  onChange={(event) => toggleSelectedAttachment(item.id, event.target.checked)}
                />
                {item.filename} - {item.modality} - {item.sensitivity} - {item.parse_status} - scope {item.thread_id ? 'thread' : 'workspace'} - retention{' '}
                {String(item.metadata.retention_policy || 'unknown')} - chunks {String(item.metadata.chunk_count || 0)}
              </label>
              {item.metadata.image && typeof item.metadata.image === 'object'
                ? ` - image ${String((item.metadata.image as Record<string, unknown>).width || '?')}x${String((item.metadata.image as Record<string, unknown>).height || '?')}`
                : ''}
              {item.deleted_at ? ' - deleted' : ''}
            </li>
          ))}
        </ul>
      ) : null}

      <button type="button" data-testid="hosted-create-thread" onClick={() => void runHostedAction(createHostedThread)} disabled={!workspaceId || !capabilities.canWrite}>
        Create hosted thread
      </button>
      <button type="button" data-testid="hosted-load-threads" onClick={() => void runHostedAction(() => loadThreads())} disabled={!workspaceId}>
        Load hosted threads
      </button>

      {threads.length > 0 ? (
        <label>
          Thread
          <select
            data-testid="hosted-thread"
            value={threadId}
            onChange={(event) => {
              const startedAt = startFrontendMeasure()
              const nextThreadId = event.target.value
              setThreadId(nextThreadId)
              const selected = threads.find((item) => item.id === nextThreadId)
              if (selected) {
                setThread(selected)
                setThreadTrainingEligible(Boolean(selected.training_eligible))
                setThreadTraceCapture(selected.trace_capture_level || 'operational')
              }
              sendFrontendMeasure('open_time', startedAt, { action: 'select_thread', thread_found: Boolean(selected) })
            }}
          >
            {threads.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <label>
        <input
          type="checkbox"
          data-testid="hosted-training-eligible"
          checked={threadTrainingEligible}
          disabled={!capabilities.canWrite}
          onChange={(event) => setThreadTrainingEligible(event.target.checked)}
        />
        Training eligible
      </label>
      <label>
        Trace capture
        <select
          data-testid="hosted-trace-capture"
          value={threadTraceCapture}
          disabled={!capabilities.canWrite}
          onChange={(event) => setThreadTraceCapture(event.target.value as 'none' | 'operational' | 'research_opt_in')}
        >
          <option value="none">none</option>
          <option value="operational">operational</option>
          <option value="research_opt_in">research opt-in</option>
        </select>
      </label>
      <button type="button" data-testid="hosted-update-consent" onClick={() => void runHostedAction(updateThreadConsent)} disabled={!threadId || !capabilities.canWrite}>
        Update consent
      </button>
      <button type="button" data-testid="hosted-delete-thread" onClick={() => void runHostedAction(deleteHostedThread)} disabled={!threadId || !capabilities.canWrite}>
        Delete thread
      </button>

      <form
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          void runHostedAction(sendHostedMessage)
        }}
      >
        <label>
          Hosted ask
          <textarea
            data-testid="hosted-message"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
          />
        </label>
        <button type="submit" data-testid="hosted-send" disabled={!workspaceId || !capabilities.canWrite}>
          Send hosted message
        </button>
      </form>

      <p data-testid="hosted-status">{status || 'Hosted platform idle'}</p>

      {latestAssistant ? (
        <section data-testid="hosted-answer-panel" className="answer-panel">
          <p data-testid="hosted-answer">{latestAssistant.content}</p>
          {phase5Trace ? (
            <div data-testid="phase5-admin-trace" className="phase5-trace-summary">
              Trace {phase5Trace.trace_id} - {phase5Trace.metrics.total_latency_ms.toFixed(1)} ms - leak check{' '}
              {String(phase5Trace.metrics.leak_check_passed)}
              <div>
                Context {phase5Trace.metrics.context_packer_version || 'unknown'} - retrieved {phase5Trace.metrics.retrieval_doc_count}
              </div>
              <ul>
                {phase5Trace.spans.slice(0, 6).map((span) => (
                  <li key={span.span_id}>
                    {span.stage}: {span.duration_ms.toFixed(1)} ms{span.cache_status ? ` (${span.cache_status})` : ''}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}

      {latestRetrievedDocs.length > 0 ? (
        <section data-testid="hosted-evidence-panel" className="evidence-panel">
          <strong>Evidence</strong>
          <button
            type="button"
            data-testid="hosted-open-evidence"
            onClick={() => {
              const startedAt = startFrontendMeasure()
              sendFrontendMeasure('open_interaction', startedAt, { action: 'open_evidence', evidence_count: latestRetrievedDocs.length })
              sendFrontendEvent('evidence_drawer_opened', { evidence_count: latestRetrievedDocs.length })
            }}
          >
            Show evidence
          </button>
          <ul>
            {latestRetrievedDocs.slice(0, 5).map((doc, index) => (
              <li key={String(doc.doc_id || doc.title || index)}>
                {String(doc.title || doc.doc_id)} - {String(doc.source_type || doc.source || 'source')} - score {String(doc.score ?? 'n/a')}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {events.length > 0 ? (
        <ul data-testid="hosted-stream-events">
          {streamEventsWindow.visibleItems.map((item, index) => (
            <li key={`${item.event}-${index}`}>{item.event}</li>
          ))}
          {virtualizedNotice(streamEventsWindow, 'hosted-stream-events-window')}
        </ul>
      ) : null}

      {trace ? (
        <div data-testid="hosted-trace">
          <strong>Trace:</strong> {traceEventsWindow.visibleItems.map((item) => item.event_type).join(', ')}
          <div>Privacy: {trace.privacy.trace_capture_level}</div>
          <ul>
            {traceEventsWindow.visibleItems.map((item) => (
              <li key={item.event_id}>
                <strong>{item.event_type}</strong>
                <pre>{JSON.stringify(item.payload, null, 2)}</pre>
              </li>
            ))}
            {virtualizedNotice(traceEventsWindow, 'hosted-trace-window')}
          </ul>
        </div>
      ) : null}

      <button type="button" data-testid="hosted-create-data-source" onClick={() => void runHostedAction(createDataSource)} disabled={!workspaceId || !capabilities.canAdmin}>
        Register data source
      </button>
      <button type="button" data-testid="hosted-load-data-sources" onClick={() => void runHostedAction(() => loadDataSources())} disabled={!workspaceId}>
        Load data sources
      </button>
      <button type="button" data-testid="hosted-load-corpus-health" onClick={() => void runHostedAction(() => loadCorpusHealth())} disabled={!workspaceId}>
        Load corpus health
      </button>
      <button type="button" data-testid="hosted-load-ingest-jobs" onClick={() => void runHostedAction(() => loadIngestJobs())} disabled={!workspaceId}>
        Load ingest jobs
      </button>
      <button type="button" data-testid="hosted-load-quotas" onClick={() => void runHostedAction(() => loadQuotaReport())} disabled={!workspaceId}>
        Load quotas
      </button>
      <button type="button" data-testid="hosted-update-data-source" onClick={() => void runHostedAction(updateDataSource)} disabled={dataSources.length === 0 || !capabilities.canAdmin}>
        Update data source
      </button>
      <button type="button" data-testid="hosted-delete-data-source" onClick={() => void runHostedAction(deleteDataSource)} disabled={dataSources.length === 0 || !capabilities.canAdmin}>
        Delete data source
      </button>
      <button type="button" data-testid="hosted-ingest-data-source" onClick={() => void runHostedAction(queueDataSourceIngest)} disabled={dataSources.length === 0 || !capabilities.canAdmin}>
        Queue ingest
      </button>
      <button type="button" data-testid="hosted-run-ingest-worker" onClick={() => void runHostedAction(runLocalIngestWorker)} disabled={!ingestJob || !capabilities.canAdmin}>
        Run local ingest
      </button>
      {dataSources.length > 0 ? (
        <ul data-testid="hosted-data-sources">
          {dataSourcesWindow.visibleItems.map((item) => (
            <li key={item.id}>
              {item.title} - {item.license_state} - RAG {String(item.rag_eligible)}
            </li>
          ))}
          {virtualizedNotice(dataSourcesWindow, 'hosted-data-sources-window')}
        </ul>
      ) : null}
      {ingestJob ? (
        <p data-testid="hosted-ingest-job">
          {ingestJob.status}
          {ingestJob.result?.chunk_count !== undefined ? ` chunks ${String(ingestJob.result.chunk_count)}` : ''}
          {ingestJob.error_message ? ` ${ingestJob.error_message}` : ''}
        </p>
      ) : null}
      {ingestJobs.length > 0 ? (
        <ul data-testid="hosted-ingest-jobs">
          {ingestJobsWindow.visibleItems.map((item) => (
            <li key={item.id}>
              {item.status} - {item.queue_name}
              {item.error_message ? ` - ${item.error_message}` : ''}
            </li>
          ))}
          {virtualizedNotice(ingestJobsWindow, 'hosted-ingest-jobs-window')}
        </ul>
      ) : null}
      {corpusHealth ? (
        <div data-testid="hosted-corpus-health">
          Corpus health: {corpusHealth.status} - sources {corpusHealth.source_count} - chunks {corpusHealth.chunk_count}
          <ul>
            {corpusSourcesWindow.visibleItems.map((item) => (
              <li key={item.data_source_id}>
                {item.title} - {item.latest_ingest_status} - {item.issue_flags.join(', ') || 'ok'}
              </li>
            ))}
            {virtualizedNotice(corpusSourcesWindow, 'hosted-corpus-sources-window')}
          </ul>
        </div>
      ) : null}
      {quotaReport ? (
        <div data-testid="hosted-quotas">
          Quotas: {quotaReport.blocked ? 'blocked' : 'ok'}
          <ul>
            {quotaReport.limits.map((item) => (
              <li key={item.quota}>
                {item.quota}: {item.used}/{item.limit}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div data-testid="hosted-deferred-actions">
        Deferred actions: {deferredActionCount} - feedback/report uploads only, retried by explicit user action
      </div>
      <button type="button" data-testid="hosted-retry-deferred-actions" onClick={() => void runHostedAction(retryDeferredActions)} disabled={deferredActionCount === 0 || !capabilities.canWrite}>
        Retry deferred actions
      </button>

      <button type="button" data-testid="hosted-feedback" onClick={() => void runHostedAction(saveHostedFeedback)} disabled={!latestAssistant || !capabilities.canWrite}>
        Save hosted feedback
      </button>
      <label>
        Rating
        <select data-testid="hosted-feedback-rating" value={hostedFeedbackRating} onChange={(event) => setHostedFeedbackRating(event.target.value as HostedFeedbackRating)}>
          {(['good', 'needs_work', 'unsafe', 'irrelevant', 'unknown'] as HostedFeedbackRating[]).map((rating) => (
            <option key={rating} value={rating}>
              {rating}
            </option>
          ))}
        </select>
      </label>
      <label>
        Quick feedback
        <select data-testid="hosted-feedback-quick-tag" value={hostedFeedbackQuickTag} onChange={(event) => setHostedFeedbackQuickTag(event.target.value)}>
          {hostedFeedbackQuickTags.map((tag) => (
            <option key={tag.id} value={tag.id}>
              {tag.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Triage
        <select data-testid="hosted-feedback-triage-tag" value={hostedFeedbackTriageTag} onChange={(event) => setHostedFeedbackTriageTag(event.target.value)}>
          {hostedFeedbackTriageTags.map((tag) => (
            <option key={tag.id} value={tag.id}>
              {tag.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Correction
        <textarea data-testid="hosted-feedback-correction" value={hostedFeedbackCorrection} onChange={(event) => setHostedFeedbackCorrection(event.target.value)} />
      </label>
      <label>
        Ideal answer
        <textarea data-testid="hosted-feedback-ideal" value={hostedFeedbackIdeal} onChange={(event) => setHostedFeedbackIdeal(event.target.value)} />
      </label>
      <label>
        <input
          type="checkbox"
          data-testid="hosted-feedback-training-consent"
          checked={hostedFeedbackTrainingConsent}
          onChange={(event) => setHostedFeedbackTrainingConsent(event.target.checked)}
        />
        Use for improvement
      </label>
      <label>
        Eval candidate status
        <select
          data-testid="hosted-eval-candidate-filter"
          value={evalCandidateFilter}
          onChange={(event) => setEvalCandidateFilter(event.target.value as EvalCandidateFilter)}
        >
          {evalCandidateFilterOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      <button type="button" data-testid="hosted-load-eval-candidates" onClick={() => void runHostedAction(() => loadEvalCandidates())} disabled={!workspaceId}>
        Load eval candidates
      </button>
      <button type="button" data-testid="hosted-load-eval-runs" onClick={() => void runHostedAction(() => loadEvalRuns())} disabled={!workspaceId}>
        Load eval runs
      </button>
      <button type="button" data-testid="hosted-load-audit-events" onClick={() => void runHostedAction(() => loadAuditEvents())} disabled={!workspaceId}>
        Load audit log
      </button>
      <button type="button" data-testid="hosted-approve-eval-candidate" onClick={() => void runHostedAction(approveEvalCandidate)} disabled={evalCandidates.length === 0 || !capabilities.canReviewResearch}>
        Approve eval candidate
      </button>
      <button type="button" data-testid="hosted-run-eval" onClick={() => void runHostedAction(runEvalReplay)} disabled={!evalCandidates.some((item) => item.review_status === 'approved_for_suite') || !capabilities.canReviewResearch}>
        Run eval replay
      </button>
      <button type="button" data-testid="hosted-load-change-proposals" onClick={() => void runHostedAction(() => loadChangeProposals())} disabled={!workspaceId}>
        Load change proposals
      </button>
      <button type="button" data-testid="hosted-create-change-proposal" onClick={() => void runHostedAction(createChangeProposal)} disabled={!workspaceId || !capabilities.canReviewResearch}>
        Create change proposal
      </button>
      <button type="button" data-testid="hosted-review-change-proposal" onClick={() => void runHostedAction(requestChangeProposalEval)} disabled={changeProposals.length === 0 || !capabilities.canReviewResearch}>
        Request eval for proposal
      </button>
      <div data-testid="hosted-eval-dashboard" className="hosted-eval-dashboard">
        Eval dashboard: candidates {evalSummary.total} - pending {evalSummary.pending} - approved {evalSummary.approved} - rejected {evalSummary.rejected} - runs {evalRuns.length}
        {latestEvalRun ? (
          <span>
            {' '}
            - latest {latestEvalRun.name} {latestEvalRun.status} - gate {latestEvalPromotion ? 'pass' : 'blocked'} - candidates{' '}
            {String(latestEvalRun.metrics.candidate_count || latestEvalRun.candidate_ids.length)} - failures {String(latestEvalRun.metrics.failure_case_count || 0)} - pass rate{' '}
            {String(latestEvalRun.metrics.pass_rate ?? 'n/a')}
            {latestEvalGateReasons.length ? ` - reasons ${latestEvalGateReasons.join(', ')}` : ''}
          </span>
        ) : null}
      </div>
      {latestEvalRun ? (
        <div data-testid="hosted-eval-drilldown" className="hosted-eval-drilldown">
          <p>
            Eval drill-down: {latestEvalRun.status} - gate {latestEvalPromotion ? 'pass' : 'blocked'} - reviewed{' '}
            {String(latestEvalRun.metrics.reviewed_count ?? 0)}/{String(latestEvalRun.metrics.candidate_count ?? latestEvalRun.candidate_ids.length)}
            {evalPassRateDelta !== null ? ` - pass delta ${signedMetric(evalPassRateDelta)}` : ''}
            {evalFailureDelta !== null ? ` - failure delta ${signedMetric(evalFailureDelta)}` : ''}
          </p>
          {evalRunTrend.length > 0 ? (
            <ol data-testid="hosted-eval-trend" className="hosted-eval-trend">
              {evalRunTrend.map((run) => (
                <li key={run.id}>
                  {run.name} - {run.status} - pass {String(run.metrics.pass_rate ?? 'n/a')} - failures {String(run.metrics.failure_case_count || 0)} - gate{' '}
                  {Boolean(run.gates.promotion_allowed) ? 'pass' : 'blocked'}
                  {run.created_at ? ` - ${new Date(run.created_at).toISOString()}` : ''}
                </li>
              ))}
            </ol>
          ) : null}
          {latestEvalGateReasons.length > 0 ? (
            <ul data-testid="hosted-eval-gate-reasons">
              {latestEvalGateReasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          ) : null}
          {latestEvalFailureTags.length > 0 ? (
            <ul data-testid="hosted-eval-failure-tags">
              {latestEvalFailureTags.map(([tag, count]) => (
                <li key={tag}>
                  {tag}: {count}
                </li>
              ))}
            </ul>
          ) : null}
          {latestEvalTargetCounts.length > 0 ? (
            <ul data-testid="hosted-eval-target-counts">
              {latestEvalTargetCounts.map(([target, count]) => (
                <li key={target}>
                  {target}: {count}
                </li>
              ))}
            </ul>
          ) : null}
          {latestEvalRegressionFailures.length > 0 ? (
            <ul data-testid="hosted-eval-regression-failures">
              {latestEvalRegressionFailures.map((failure) => (
                <li key={String(failure.candidate_id)}>
                  {String(failure.candidate_id)} - {String(failure.target_component || 'unknown')} - {asStringList(failure.failure_tags).join(', ') || 'untagged'} - ideal{' '}
                  {String(Boolean(failure.has_ideal_answer))}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {evalCandidates.length > 0 ? (
        <ul data-testid="hosted-eval-candidates">
          {evalCandidatesWindow.visibleItems.map((item) => (
            <li key={item.id}>
              {item.target_component} - {item.review_status} - thread {item.thread_id}
            </li>
          ))}
          {virtualizedNotice(evalCandidatesWindow, 'hosted-eval-candidates-window')}
        </ul>
      ) : null}
      {candidateEvidence.length > 0 ? (
        <ul data-testid="hosted-eval-candidate-evidence">
          {candidateEvidence.map(({ candidate, feedback }) => (
            <li key={candidate.id}>
              {candidate.id} - {asStringList(feedback.failure_tags).join(', ') || 'no failure tags'} - ideal {String(Boolean(feedback.ideal_answer))} - consent{' '}
              {String(Boolean(feedback.training_consent))}
            </li>
          ))}
        </ul>
      ) : null}
      {evalRuns.length > 0 ? (
        <ul data-testid="hosted-eval-runs">
          {evalRunsWindow.visibleItems.map((item) => (
            <li key={item.id}>
              {item.name} - {item.status} - {String(item.metrics.candidate_count || item.candidate_ids.length)} candidates - failures{' '}
              {String(item.metrics.failure_case_count || 0)} - pass rate {String(item.metrics.pass_rate ?? 'n/a')} - gate{' '}
              {Boolean(item.gates.promotion_allowed) ? 'pass' : 'blocked'}
            </li>
          ))}
          {virtualizedNotice(evalRunsWindow, 'hosted-eval-runs-window')}
        </ul>
      ) : null}
      {changeProposals.length > 0 ? (
        <ul data-testid="hosted-change-proposals">
          {changeProposalsWindow.visibleItems.map((item) => (
            <li key={item.id}>
              {item.proposal_type} - {item.review_status} - rollout {String(item.gates.promotion_allowed)}
            </li>
          ))}
          {virtualizedNotice(changeProposalsWindow, 'hosted-change-proposals-window')}
        </ul>
      ) : null}
      {auditEvents.length > 0 ? (
        <ul data-testid="hosted-audit-events">
          {auditEventsWindow.visibleItems.map((item) => (
            <li key={item.id}>
              {item.event_type} - {item.target_type || 'target'} - {String(item.payload.export_type || item.payload.filename || item.payload.name || '')}
            </li>
          ))}
          {virtualizedNotice(auditEventsWindow, 'hosted-audit-events-window')}
        </ul>
      ) : null}
      <button type="button" data-testid="hosted-export" onClick={() => void runHostedAction(exportHostedThread)} disabled={!threadId || !capabilities.canWrite}>
        Export hosted thread
      </button>
      <label>
        Export scope
        <select
          data-testid="hosted-export-scope"
          value={exportThreadFilter}
          onChange={(event) => setExportThreadFilter(event.target.value as 'active' | 'workspace')}
        >
          <option value="active">active thread</option>
          <option value="workspace">workspace</option>
        </select>
      </label>
      <label>
        Export type
        <select
          data-testid="hosted-export-type-filter"
          value={exportTypeFilter}
          onChange={(event) => setExportTypeFilter(event.target.value)}
        >
          <option value="">all types</option>
          <option value="json">json</option>
          <option value="markdown">markdown</option>
          <option value="csv">csv</option>
          <option value="zip">zip</option>
          <option value="thread_report">thread_report</option>
          <option value="field_context_brief">field_context_brief</option>
          <option value="source_evidence_bundle">source_evidence_bundle</option>
          <option value="diagnostic_checklist">diagnostic_checklist</option>
          <option value="learning_trace_export">learning_trace_export</option>
          <option value="data_source_audit">data_source_audit</option>
          <option value="demo_eval_snapshot">demo_eval_snapshot</option>
        </select>
      </label>
      <label>
        Export limit
        <input
          data-testid="hosted-export-limit"
          type="number"
          min={1}
          max={500}
          value={exportLimit}
          onChange={(event) => {
            const parsed = Number(event.target.value)
            setExportLimit(Number.isFinite(parsed) ? Math.min(500, Math.max(1, parsed)) : 25)
          }}
        />
      </label>
      <button type="button" data-testid="hosted-load-exports" onClick={() => void runHostedAction(() => loadExports())} disabled={!workspaceId}>
        Load exports
      </button>
      <button type="button" data-testid="hosted-load-export-jobs" onClick={() => void runHostedAction(() => loadExportJobs())} disabled={!workspaceId}>
        Load export jobs
      </button>
      {exportJobs.length > 0 ? (
        <ul data-testid="hosted-export-jobs">
          {exportJobsWindow.visibleItems.map((item) => (
            <li key={item.id}>
              {item.export_type} - {item.status} - queue {item.queue_name} - export {item.export_id || 'pending'} - thread {item.thread_id}
            </li>
          ))}
          {virtualizedNotice(exportJobsWindow, 'hosted-export-jobs-window')}
        </ul>
      ) : null}
      {exports.length > 0 ? (
        <ul data-testid="hosted-exports">
          {exportsWindow.visibleItems.map((item) => (
            <li key={item.id}>
              {item.export_type} - {item.redaction_status} - {item.sha256 ? item.sha256.slice(0, 8) : 'pending'} - thread {item.thread_id || 'workspace'} - files {Object.keys((item.metadata.files as Record<string, unknown> | undefined) || {}).length} - {new Date(item.created_at).toISOString()}
            </li>
          ))}
          {virtualizedNotice(exportsWindow, 'hosted-exports-window')}
        </ul>
      ) : null}
      <button type="button" data-testid="hosted-image-preview" onClick={() => void runHostedAction(runImagePreview)} disabled={!workspaceId || !capabilities.canReviewResearch}>
        Image research preview
      </button>
      <button type="button" data-testid="hosted-image-eval" onClick={() => void runHostedAction(runImageEval)} disabled={!workspaceId || !capabilities.canReviewResearch}>
        Image eval report
      </button>
      {imagePreview ? (
        <pre data-testid="hosted-image-preview-result">{JSON.stringify(imagePreview, null, 2)}</pre>
      ) : null}
      {imageEvalReport ? (
        <pre data-testid="hosted-image-eval-result">{JSON.stringify(imageEvalReport, null, 2)}</pre>
      ) : null}

      {capabilities.canAdmin ? (
        <section data-testid="hosted-admin-panel">
          <button type="button" data-testid="hosted-load-admin-ops" onClick={() => void runHostedAction(loadAdminOps)} disabled={!workspaceId}>
            Load admin operations
          </button>
          {adminOps ? (
            <div data-testid="hosted-admin-ops">
              Health: {String(adminOps.health.status)} - storage {String(adminOps.health.storage)}
              <div>Metrics workspace: {String(adminOps.metrics.workspace_id)}</div>
              <div>
                Monitoring: {String(adminOps.monitoring.status)} - alerts {String(adminOps.monitoring.alert_count ?? 0)}
              </div>
              {adminOps.latency ? (
                <div data-testid="hosted-phase5-latency">
                  Phase 5 latency: {adminOps.latency.dashboard.turn_count} turns - p95 {String(adminOps.latency.dashboard.latency_ms.p95 ?? 'n/a')} ms - leaks{' '}
                  {adminOps.latency.dashboard.leak_failures}
                </div>
              ) : null}
              {adminOps.frontendRum ? (
                <div data-testid="hosted-frontend-rum">Frontend RUM samples: {String(adminOps.frontendRum.sample_count ?? 0)}</div>
              ) : null}
              {adminOps.frontendEvents ? (
                <div data-testid="hosted-frontend-events">Frontend event samples: {String(adminOps.frontendEvents.sample_count ?? 0)}</div>
              ) : null}
              {adminOps.failures.length > 0 ? (
                <ul data-testid="hosted-admin-ops-failures">
                  {adminOps.failures.map((failure) => (
                    <li key={failure}>{failure}</li>
                  ))}
                </ul>
              ) : null}
              {Array.isArray(adminOps.monitoring.alerts) && adminOps.monitoring.alerts.length > 0 ? (
                <ul data-testid="hosted-monitoring-alerts">
                  {adminOps.monitoring.alerts.map((item, index) => {
                    const alert = asRecord(item)
                    return (
                      <li key={`${String(alert.key || 'alert')}-${index}`}>
                        {String(alert.severity)} - {String(alert.key)} - {String(alert.message)}
                      </li>
                    )
                  })}
                </ul>
              ) : null}
              <div>Recent admin audit events: {adminOps.auditEvents.length}</div>
            </div>
          ) : null}
        </section>
      ) : null}

      {orgs.length > 0 ? <p data-testid="hosted-org-count">Organizations: {orgs.length}</p> : null}
    </section>
  )
}

function FieldContextReadinessPanel({ readiness }: { readiness: FieldContextReadiness }) {
  return (
    <div data-testid="hosted-field-context-readiness">
      <p>{readiness.headline}</p>
      {readiness.readyUses.length > 0 ? (
        <p>Ready for: {readiness.readyUses.join(', ')}</p>
      ) : (
        <p>Ready for: general, non-field-specific answer only</p>
      )}
      <p>Blocked: {readiness.blockedUses.join(', ')}</p>
      {readiness.missingData.length > 0 ? (
        <p>Missing: {readiness.missingData.join(', ')}</p>
      ) : (
        <p>Missing: none for triage</p>
      )}
      <p>Next: {readiness.nextMeasurements.join(' ')}</p>
      <p>{readiness.decisionBoundary}</p>
    </div>
  )
}
