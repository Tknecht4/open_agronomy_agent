type RumMetricName =
  | 'LCP'
  | 'CLS'
  | 'INP'
  | 'TTI'
  | 'long_task'
  | 'render_time'
  | 'open_time'
  | 'first_visible_progress'
  | 'open_interaction'
  | 'standard_thread_report_preview'
  | 'model_download_notice'
type RumRating = 'good' | 'needs_improvement' | 'poor' | 'unknown'

type RumContext = {
  workspaceId?: string
  threadId?: string
}

type RumMetric = {
  metric_name: RumMetricName
  value: number
  unit: 'ms' | 'score' | 'count'
  rating?: RumRating
  metadata?: Record<string, unknown>
}

export const PHASE6_FRONTEND_EVENT_NAMES = [
  'app_shell_loaded',
  'auth_flow_started',
  'auth_flow_completed',
  'auth_flow_failed',
  'field_context_created',
  'field_context_edited',
  'field_context_used',
  'thread_created',
  'message_submitted',
  'answer_stream_started',
  'answer_stream_first_token',
  'answer_stream_completed',
  'answer_stream_cancelled',
  'evidence_drawer_opened',
  'report_export_started',
  'report_export_completed',
  'report_export_failed',
  'feedback_submitted',
  'webgpu_probe_completed',
  'local_model_download_started',
  'local_model_download_completed',
  'local_model_download_cancelled',
  'local_model_download_failed',
  'error_boundary_triggered',
  'hidden_template_leak_detected_client',
] as const

export type FrontendEventName = (typeof PHASE6_FRONTEND_EVENT_NAMES)[number]
export const PHASE6_TELEMETRY_FAILURE_EVENT = 'phase6:telemetry-failed'

const PHASE6_EVENT_RESTRICTED_KEYS = [
  'answer',
  'email',
  'field_note',
  'file',
  'message',
  'note',
  'private',
  'prompt',
  'raw',
  'text',
  'upload',
]

const normalizeTelemetryMetadataKey = (key: string): string => {
  const normalized = key.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
  return normalized.slice(0, 80) || 'field'
}

const restrictedTelemetryKeyReason = (key: string): string | null => {
  const normalizedKey = normalizeTelemetryMetadataKey(key)
  const keyTokens = normalizedKey.split('_').filter(Boolean)
  return PHASE6_EVENT_RESTRICTED_KEYS.some((restricted) => keyTokens.includes(restricted)) ? 'restricted_key' : null
}

const safeRumMetadataValue = (key: string, value: unknown): [string, unknown, string | null] => {
  const safeKey = normalizeTelemetryMetadataKey(key)
  const restrictedReason = restrictedTelemetryKeyReason(key)
  if (restrictedReason) {
    return [safeKey, { type: typeof value, redacted: true, reason: restrictedReason }, key]
  }
  if (typeof value === 'string') {
    if (!/^[A-Za-z0-9_.:-]{0,80}$/.test(value)) {
      return [safeKey, { type: 'string', redacted: true, reason: 'restricted_value' }, key]
    }
    return [safeKey, value.slice(0, 80), null]
  }
  if (typeof value === 'number' || typeof value === 'boolean' || value === null) {
    return [safeKey, value, null]
  }
  return [safeKey, { type: typeof value, redacted: true, reason: 'unsupported_value' }, key]
}

const safeFrontendRumMetadata = (metadata: Record<string, unknown>) => {
  const safeEntries: [string, unknown][] = []
  const redactedFields: string[] = []
  Object.entries(metadata)
    .slice(0, 20)
    .forEach(([key, value]) => {
      const [safeKey, safeValue, redactedField] = safeRumMetadataValue(key, value)
      safeEntries.push([safeKey, safeValue])
      if (redactedField) {
        redactedFields.push(normalizeTelemetryMetadataKey(redactedField))
      }
    })
  if (redactedFields.length) {
    safeEntries.push(['redacted_fields', redactedFields])
  }
  return Object.fromEntries(safeEntries)
}

export const PHASE6_FRONTEND_PERFORMANCE_BUDGETS: Record<
  RumMetricName,
  { target: number; unit: 'ms' | 'score' | 'count'; area: string; launchGate: 'blocker' | 'monitor' }
> = {
  LCP: { target: 2500, unit: 'ms', area: 'home/app shell', launchGate: 'blocker' },
  CLS: { target: 0.1, unit: 'score', area: 'all primary routes', launchGate: 'blocker' },
  INP: { target: 200, unit: 'ms', area: 'all primary routes', launchGate: 'blocker' },
  TTI: { target: 2000, unit: 'ms', area: 'login -> app shell', launchGate: 'blocker' },
  render_time: { target: 500, unit: 'ms', area: 'thread list', launchGate: 'blocker' },
  open_time: { target: 800, unit: 'ms', area: 'existing thread', launchGate: 'blocker' },
  first_visible_progress: { target: 500, unit: 'ms', area: 'answer stream', launchGate: 'blocker' },
  long_task: { target: 50, unit: 'ms', area: 'trace/debug drawer', launchGate: 'blocker' },
  open_interaction: { target: 150, unit: 'ms', area: 'evidence drawer', launchGate: 'blocker' },
  standard_thread_report_preview: { target: 3000, unit: 'ms', area: 'report preview', launchGate: 'blocker' },
  model_download_notice: { target: 1, unit: 'count', area: 'local model preview', launchGate: 'blocker' },
}

const navigationId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
let context: RumContext = {}

export const configureFrontendRum = (nextContext: RumContext) => {
  context = { ...context, ...nextContext }
}

export const rateRumMetric = (metricName: RumMetricName, value: number): RumRating => {
  const budget = PHASE6_FRONTEND_PERFORMANCE_BUDGETS[metricName]
  if (!budget) {
    return 'unknown'
  }
  if (metricName === 'model_download_notice') {
    return value >= 1 ? 'good' : 'poor'
  }
  if (metricName === 'CLS') {
    if (value <= 0.1) return 'good'
    if (value <= 0.25) return 'needs_improvement'
    return 'poor'
  }
  if (metricName === 'INP') {
    if (value <= 200) return 'good'
    if (value <= 500) return 'needs_improvement'
    return 'poor'
  }
  if (metricName === 'long_task') {
    if (value <= 50) return 'good'
    if (value <= 100) return 'needs_improvement'
    return 'poor'
  }
  if (value <= budget.target) return 'good'
  if (value <= budget.target * 1.6) return 'needs_improvement'
  return 'poor'
}

export const rumBudgetStatus = (metricName: RumMetricName, value: number) => {
  const budget = PHASE6_FRONTEND_PERFORMANCE_BUDGETS[metricName]
  return {
    budgeted: Boolean(budget),
    status: budget ? (metricName === 'model_download_notice' ? (value >= budget.target ? 'pass' : 'fail') : value <= budget.target ? 'pass' : 'fail') : 'monitor',
    target: budget?.target ?? null,
    unit: budget?.unit ?? null,
    area: budget?.area ?? null,
    launch_gate: budget?.launchGate ?? 'monitor',
  }
}

export const startFrontendMeasure = (): number => (typeof performance === 'undefined' ? Date.now() : performance.now())

export const sendFrontendMeasure = (metricName: RumMetricName, startedAt: number, metadata: Record<string, unknown> = {}) => {
  const now = typeof performance === 'undefined' ? Date.now() : performance.now()
  sendRumMetric({ metric_name: metricName, value: Math.max(0, now - startedAt), unit: 'ms', metadata })
}

export const sendRumMetric = (metric: RumMetric) => {
  const value = Number(metric.value)
  if (!Number.isFinite(value) || value < 0) {
    return
  }
  const payload = {
    schema_version: 'phase6.frontend_rum.v1',
    metric_name: metric.metric_name,
    value,
    unit: metric.unit,
    rating: metric.rating || rateRumMetric(metric.metric_name, value),
    route: window.location.pathname || '/',
    workspace_id: context.workspaceId || null,
    thread_id: context.threadId || null,
    navigation_id: navigationId,
    metadata: {
      ...safeFrontendRumMetadata(metric.metadata || {}),
      budget_status: rumBudgetStatus(metric.metric_name, value),
    },
  }
  const body = JSON.stringify(payload)
  void postTelemetry('/api/rum', body)
}

const safeFrontendEventMetadata = (metadata: Record<string, unknown>) => {
  return Object.fromEntries(
    Object.entries(metadata).slice(0, 20).map(([key, value]) => {
      const normalizedKey = normalizeTelemetryMetadataKey(key)
      const keyTokens = normalizedKey.split('_').filter(Boolean)
      if (PHASE6_EVENT_RESTRICTED_KEYS.some((restricted) => keyTokens.includes(restricted))) {
        throw new Error(`frontend event metadata field is restricted: ${key}`)
      }
      if (typeof value === 'string') {
        if (!/^[A-Za-z0-9_.:-]{0,80}$/.test(value)) {
          throw new Error(`frontend event metadata value is restricted: ${key}`)
        }
        return [key, value.slice(0, 80)]
      }
      if (typeof value === 'number' || typeof value === 'boolean' || value === null) {
        return [key, value]
      }
      return [key, { type: typeof value, redacted: true }]
    }),
  )
}

export const sendFrontendEvent = (eventName: FrontendEventName, metadata: Record<string, unknown> = {}) => {
  const payload = {
    schema_version: 'phase6.frontend_event.v1',
    event_name: eventName,
    route: window.location.pathname || '/',
    workspace_id: context.workspaceId || null,
    thread_id: context.threadId || null,
    navigation_id: navigationId,
    metadata: safeFrontendEventMetadata(metadata),
  }
  const body = JSON.stringify(payload)
  void postTelemetry('/api/frontend-events', body)
}

const postTelemetry = async (path: '/api/rum' | '/api/frontend-events', body: string) => {
  try {
    const csrfMatch = document.cookie.match(/(?:^|;\s*)agronomy_csrf=([^;]+)/)
    const response = await fetch(path, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(csrfMatch ? { 'X-CSRF-Token': decodeURIComponent(csrfMatch[1]) } : {}),
      },
      body,
      keepalive: true,
    })
    if (!response.ok) {
      notifyTelemetryFailure({ path, reason: 'http_error', status: response.status })
    }
  } catch {
    notifyTelemetryFailure({ path, reason: 'network_error' })
  }
}

const notifyTelemetryFailure = (detail: { path: '/api/rum' | '/api/frontend-events'; reason: 'http_error' | 'network_error'; status?: number }) => {
  if (typeof window === 'undefined') {
    return
  }
  window.dispatchEvent(new CustomEvent(PHASE6_TELEMETRY_FAILURE_EVENT, { detail }))
}

export const installFrontendRum = () => {
  if (typeof window === 'undefined' || typeof PerformanceObserver === 'undefined') {
    return () => undefined
  }
  const observers: PerformanceObserver[] = []
  const supported = new Set(PerformanceObserver.supportedEntryTypes || [])
  const observe = (entryType: string, callback: (entries: PerformanceEntry[]) => void, options: Record<string, unknown> = {}) => {
    if (!supported.has(entryType)) {
      return
    }
    const observer = new PerformanceObserver((list) => callback(list.getEntries()))
    observer.observe({ type: entryType, buffered: true, ...options } as PerformanceObserverInit)
    observers.push(observer)
  }

  let latestLcp = 0
  observe('largest-contentful-paint', (entries) => {
    const latest = entries[entries.length - 1]
    latestLcp = latest ? latest.startTime : latestLcp
  })

  let cls = 0
  observe('layout-shift', (entries) => {
    entries.forEach((entry) => {
      const shift = entry as PerformanceEntry & { hadRecentInput?: boolean; value?: number }
      if (!shift.hadRecentInput) {
        cls += Number(shift.value || 0)
      }
    })
  })

  let inp = 0
  observe(
    'event',
    (entries) => {
      entries.forEach((entry) => {
        const eventEntry = entry as PerformanceEntry & { duration?: number; interactionId?: number }
        if (eventEntry.interactionId && Number(eventEntry.duration || 0) > inp) {
          inp = Number(eventEntry.duration || 0)
        }
      })
    },
    { durationThreshold: 40 },
  )

  observe('longtask', (entries) => {
    entries.forEach((entry) => {
      sendRumMetric({ metric_name: 'long_task', value: entry.duration, unit: 'ms', metadata: { name: entry.name } })
    })
  })

  window.setTimeout(() => {
    sendRumMetric({ metric_name: 'TTI', value: performance.now(), unit: 'ms' })
  }, 0)

  let flushed = false
  const flush = () => {
    if (flushed) {
      return
    }
    flushed = true
    if (latestLcp > 0) {
      sendRumMetric({ metric_name: 'LCP', value: latestLcp, unit: 'ms' })
    }
    sendRumMetric({ metric_name: 'CLS', value: cls, unit: 'score' })
    if (inp > 0) {
      sendRumMetric({ metric_name: 'INP', value: inp, unit: 'ms' })
    }
  }
  window.addEventListener('visibilitychange', flush, { once: true })
  window.addEventListener('pagehide', flush, { once: true })
  return () => {
    observers.forEach((observer) => observer.disconnect())
    window.removeEventListener('visibilitychange', flush)
    window.removeEventListener('pagehide', flush)
  }
}
