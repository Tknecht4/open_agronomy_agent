import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  PHASE6_FRONTEND_EVENT_NAMES,
  PHASE6_TELEMETRY_FAILURE_EVENT,
  configureFrontendRum,
  rateRumMetric,
  rumBudgetStatus,
  sendFrontendEvent,
  sendFrontendMeasure,
  sendRumMetric,
} from './rum'

describe('frontend RUM', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    configureFrontendRum({ workspaceId: undefined, threadId: undefined })
    document.cookie = 'agronomy_csrf=; Max-Age=0; path=/'
  })

  it('rates Core Web Vitals against Phase 6 budgets', () => {
    expect(rateRumMetric('LCP', 2400)).toBe('good')
    expect(rateRumMetric('LCP', 3200)).toBe('needs_improvement')
    expect(rateRumMetric('LCP', 4500)).toBe('poor')
    expect(rateRumMetric('INP', 180)).toBe('good')
    expect(rateRumMetric('open_interaction', 149)).toBe('good')
    expect(rateRumMetric('open_interaction', 151)).toBe('needs_improvement')
    expect(rateRumMetric('standard_thread_report_preview', 3200)).toBe('needs_improvement')
    expect(rateRumMetric('model_download_notice', 1)).toBe('good')
    expect(rateRumMetric('model_download_notice', 0)).toBe('poor')
    expect(rateRumMetric('CLS', 0.08)).toBe('good')
    expect(rateRumMetric('CLS', 0.2)).toBe('needs_improvement')
    expect(rateRumMetric('CLS', 0.4)).toBe('poor')
    expect(rumBudgetStatus('standard_thread_report_preview', 2999)).toMatchObject({
      status: 'pass',
      target: 3000,
      area: 'report preview',
      launch_gate: 'blocker',
    })
    expect(rumBudgetStatus('model_download_notice', 0)).toMatchObject({
      status: 'fail',
      target: 1,
      area: 'local model preview',
    })
  })

  it('sends redacted route and workspace context without blocking render', () => {
    configureFrontendRum({ workspaceId: 'workspace_1', threadId: 'thread_1' })
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => ({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: vi.fn(() => false) })

    sendRumMetric({
      metric_name: 'LCP',
      value: 3000,
      unit: 'ms',
      metadata: { entry_type: 'largest-contentful-paint' },
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/rum',
      expect.objectContaining({
        method: 'POST',
        keepalive: true,
      }),
    )
    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(String(init.body))
    expect(body).toMatchObject({
      schema_version: 'phase6.frontend_rum.v1',
      metric_name: 'LCP',
      value: 3000,
      unit: 'ms',
      rating: 'needs_improvement',
      workspace_id: 'workspace_1',
      thread_id: 'thread_1',
      metadata: {
        entry_type: 'largest-contentful-paint',
        budget_status: expect.objectContaining({ status: 'fail', target: 2500, area: 'home/app shell' }),
      },
    })
    expect(body).not.toHaveProperty('email')
    expect(body).not.toHaveProperty('message')
  })

  it('uses fetch transport even when sendBeacon is available so QA can observe failures', () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => ({ ok: true }))
    const beaconMock = vi.fn(() => true)
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: beaconMock })

    sendRumMetric({
      metric_name: 'TTI',
      value: 1200,
      unit: 'ms',
    })
    sendFrontendEvent('app_shell_loaded', { shell: 'hosted' })

    expect(beaconMock).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledWith('/api/rum', expect.objectContaining({ keepalive: true }))
    expect(fetchMock).toHaveBeenCalledWith('/api/frontend-events', expect.objectContaining({ keepalive: true }))
  })

  it('attaches the CSRF token to cookie-authenticated telemetry', () => {
    document.cookie = 'agronomy_csrf=paired%20csrf; path=/'
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => ({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    sendFrontendEvent('app_shell_loaded', { shell: 'field_lan' })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/frontend-events',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-CSRF-Token': 'paired csrf',
        }),
      }),
    )
  })

  it('dispatches local telemetry failure events without leaking payload contents', async () => {
    const failures: CustomEvent[] = []
    const onFailure = (event: Event) => failures.push(event as CustomEvent)
    window.addEventListener(PHASE6_TELEMETRY_FAILURE_EVENT, onFailure)
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error('field note network failure'))
      .mockResolvedValueOnce({ ok: false, status: 503 })
    vi.stubGlobal('fetch', fetchMock)

    sendRumMetric({
      metric_name: 'LCP',
      value: 1200,
      unit: 'ms',
      metadata: { message_text: 'raw field note should never reach failure event' },
    })
    sendFrontendEvent('app_shell_loaded', { shell: 'hosted' })
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    expect(failures.map((event) => event.detail)).toEqual([
      { path: '/api/rum', reason: 'network_error' },
      { path: '/api/frontend-events', reason: 'http_error', status: 503 },
    ])
    expect(JSON.stringify(failures.map((event) => event.detail))).not.toContain('raw field note')
    expect(JSON.stringify(failures.map((event) => event.detail))).not.toContain('field note network failure')
    window.removeEventListener(PHASE6_TELEMETRY_FAILURE_EVENT, onFailure)
  })

  it('sends route-level performance marks with budget metadata', () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => ({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: vi.fn(() => false) })
    sendFrontendMeasure('open_interaction', performance.now(), { action: 'open_evidence', evidence_count: 3 })

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body))
    expect(body.metric_name).toBe('open_interaction')
    expect(body.value).toBeGreaterThanOrEqual(0)
    expect(body.rating).toBe('good')
    expect(body.metadata).toMatchObject({
      action: 'open_evidence',
      evidence_count: 3,
      budget_status: { status: 'pass', target: 150, area: 'evidence drawer', launch_gate: 'blocker', unit: 'ms', budgeted: true },
    })
  })

  it('redacts sensitive RUM metadata before sending performance telemetry', () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => ({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: vi.fn(() => false) })

    sendRumMetric({
      metric_name: 'LCP',
      value: 1800,
      unit: 'ms',
      metadata: {
        entry_type: 'largest-contentful-paint',
        message_text: 'high soil-test phosphorus near a ditch',
        detail: 'raw field note sentence with spaces',
        nested: { raw: 'answer text' },
      },
    })

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body))
    expect(body.metadata.entry_type).toBe('largest-contentful-paint')
    expect(body.metadata.message_text).toMatchObject({ redacted: true, reason: 'restricted_key' })
    expect(body.metadata.detail).toMatchObject({ redacted: true, reason: 'restricted_value' })
    expect(body.metadata.nested).toMatchObject({ redacted: true, reason: 'unsupported_value' })
    expect(body.metadata.redacted_fields).toEqual(['message_text', 'detail', 'nested'])
    expect(JSON.stringify(body)).not.toContain('high soil-test phosphorus')
    expect(JSON.stringify(body)).not.toContain('raw field note sentence')
    expect(JSON.stringify(body)).not.toContain('answer text')
  })

  it('sends privacy-scoped product events without raw answer or field text', () => {
    configureFrontendRum({ workspaceId: 'workspace_1', threadId: 'thread_1' })
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => ({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: vi.fn(() => false) })

    sendFrontendEvent('message_submitted', {
      has_field_context: true,
      attachment_count: 2,
      attachment_mode: 'selected',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/frontend-events',
      expect.objectContaining({
        method: 'POST',
        keepalive: true,
      }),
    )
    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body))
    expect(body).toMatchObject({
      schema_version: 'phase6.frontend_event.v1',
      event_name: 'message_submitted',
      workspace_id: 'workspace_1',
      thread_id: 'thread_1',
      metadata: {
        has_field_context: true,
        attachment_count: 2,
        attachment_mode: 'selected',
      },
    })
    expect(JSON.stringify(body)).not.toContain('advisor@example.test')
    expect(JSON.stringify(body)).not.toContain('high soil-test phosphorus')
  })

  it('exports the full Phase 6 frontend event taxonomy', () => {
    expect(PHASE6_FRONTEND_EVENT_NAMES).toEqual([
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
    ])
  })

  it('rejects sensitive frontend event metadata keys before sending', () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => ({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: vi.fn(() => false) })

    expect(() => sendFrontendEvent('message_submitted', { message_text: 'raw field note' })).toThrow('restricted')
    expect(() => sendFrontendEvent('message_submitted', { detail: 'raw field note sentence' })).toThrow('restricted')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
