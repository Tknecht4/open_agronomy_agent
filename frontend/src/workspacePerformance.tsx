import { useEffect, useState } from 'react'

type TimedMetric = { supported: boolean; value: number | null }
type CountMetric = { supported: boolean; count: number | null; max_ms: number | null }
type ResourceBucket = { count: number; duration_ms: number; transfer_bytes: number; decoded_bytes: number }
type LayoutShiftEntry = PerformanceEntry & { value: number; hadRecentInput: boolean }
type EventTimingEntry = PerformanceEntry & { interactionId?: number }

export type WorkspacePerformanceSnapshot = {
  schema: 'open-agronomy.local-performance.v1'
  captured_at: string
  environment: { mode: string; viewport_width: number; viewport_height: number; device_pixel_ratio: number; user_agent_family: string }
  navigation: { duration_ms: number | null; dom_content_loaded_ms: number | null; response_end_ms: number | null }
  first_contentful_paint: TimedMetric
  largest_contentful_paint: TimedMetric
  cumulative_layout_shift: TimedMetric
  observed_interactions: CountMetric
  long_tasks: { supported: boolean; count: number | null; total_ms: number | null; max_ms: number | null }
  resources: { supported: boolean; buckets: Record<string, ResourceBucket> }
  errors: { script: number; unhandled_rejection: number; resource: number }
  caveats: string[]
}

const state = {
  fcp: null as number | null,
  lcp: null as number | null,
  cls: 0,
  clsWindow: 0,
  clsWindowStart: 0,
  clsWindowLast: 0,
  interactions: new Map<number, number>(),
  longTasks: [] as number[],
  resources: {} as Record<string, ResourceBucket>,
  seenResources: new Set<string>(),
  seenLongTasks: new Set<string>(),
  errors: { script: 0, unhandled_rejection: 0, resource: 0 },
  supported: new Set<string>(),
}

const finite = (value: number): number | null => Number.isFinite(value) && value >= 0 ? Math.round(value * 100) / 100 : null
const safeBucket = (entry: PerformanceResourceTiming): string => {
  const type = entry.initiatorType.toLowerCase()
  return ['script', 'link', 'css', 'img', 'image', 'fetch', 'xmlhttprequest', 'iframe', 'font', 'other'].includes(type) ? type : 'other'
}
const browserFamily = (): string => {
  const ua = navigator.userAgent
  if (/Firefox\//.test(ua)) return 'Firefox'
  if (/Edg\//.test(ua)) return 'Edge'
  if (/Chrome\//.test(ua)) return 'Chrome'
  if (/Safari\//.test(ua)) return 'Safari'
  return 'Other'
}

const recordResource = (entry: PerformanceResourceTiming) => {
  // Repeated buffered observer delivery (including React StrictMode remounts)
  // must not count a request twice. No resource URL is retained.
  const key = `${entry.startTime}:${entry.duration}:${entry.initiatorType}`
  if (state.seenResources.has(key)) return
  state.seenResources.add(key)
  const bucket = state.resources[safeBucket(entry)] ||= { count: 0, duration_ms: 0, transfer_bytes: 0, decoded_bytes: 0 }
  bucket.count += 1
  bucket.duration_ms += entry.duration || 0
  bucket.transfer_bytes += entry.transferSize || 0
  bucket.decoded_bytes += entry.decodedBodySize || 0
}

export const workspaceProfilingEnabled = (): boolean => typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('profile') === '1'

/** Browser-only, local-only recorder. Call from one mounted component; cleanup on unmount. */
export const installWorkspacePerformance = (): (() => void) => {
  if (!workspaceProfilingEnabled()) return () => undefined
  const observers: PerformanceObserver[] = []
  const supported = new Set(typeof PerformanceObserver === 'undefined' ? [] : PerformanceObserver.supportedEntryTypes || [])
  const observe = (type: string, callback: (entries: PerformanceEntry[]) => void, options: Record<string, unknown> = {}) => {
    if (!supported.has(type)) return
    try {
      const observer = new PerformanceObserver((list) => callback(list.getEntries()))
      observer.observe({ type, buffered: true, ...options } as PerformanceObserverInit)
      observers.push(observer)
      state.supported.add(type)
    } catch { /* Unsupported observer options remain explicitly unavailable. */ }
  }
  observe('paint', (entries) => {
    for (const entry of entries) if (entry.name === 'first-contentful-paint') state.fcp = entry.startTime
  })
  observe('largest-contentful-paint', (entries) => {
    const last = entries[entries.length - 1]
    if (last) state.lcp = last.startTime
  })
  observe('layout-shift', (entries) => {
    for (const entry of entries as LayoutShiftEntry[]) {
      if (entry.hadRecentInput) continue
      if (entry.startTime - state.clsWindowLast > 1000 || entry.startTime - state.clsWindowStart > 5000) {
        state.clsWindow = 0
        state.clsWindowStart = entry.startTime
      }
      state.clsWindow += entry.value
      state.clsWindowLast = entry.startTime
      state.cls = Math.max(state.cls, state.clsWindow)
    }
  })
  observe('event', (entries) => {
    for (const entry of entries as EventTimingEntry[]) {
      if (!entry.interactionId) continue
      const previous = state.interactions.get(entry.interactionId) || 0
      state.interactions.set(entry.interactionId, Math.max(previous, entry.duration))
    }
  }, { durationThreshold: 40 })
  observe('longtask', (entries) => {
    for (const entry of entries) {
      const key = `${entry.startTime}:${entry.duration}`
      if (state.seenLongTasks.has(key)) continue
      state.seenLongTasks.add(key)
      state.longTasks.push(entry.duration)
    }
  })
  observe('resource', (entries) => {
    for (const entry of entries) recordResource(entry as PerformanceResourceTiming)
  })
  const onError = (event: Event) => {
    if (event instanceof ErrorEvent) state.errors.script += 1
    else state.errors.resource += 1
  }
  const onRejection = () => { state.errors.unhandled_rejection += 1 }
  window.addEventListener('error', onError, true)
  window.addEventListener('unhandledrejection', onRejection)
  return () => {
    observers.forEach((observer) => observer.disconnect())
    window.removeEventListener('error', onError, true)
    window.removeEventListener('unhandledrejection', onRejection)
  }
}

export const snapshotWorkspacePerformance = (): WorkspacePerformanceSnapshot => {
  const navigation = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
  const interactionValues = [...state.interactions.values()]
  const resources = Object.fromEntries(Object.entries(state.resources).map(([key, value]) => [key, {
    count: value.count,
    duration_ms: finite(value.duration_ms) || 0,
    transfer_bytes: value.transfer_bytes,
    decoded_bytes: value.decoded_bytes,
  }]))
  return {
    schema: 'open-agronomy.local-performance.v1',
    captured_at: new Date().toISOString(),
    environment: {
      mode: import.meta.env.MODE,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      device_pixel_ratio: window.devicePixelRatio,
      user_agent_family: browserFamily(),
    },
    navigation: {
      duration_ms: navigation ? finite(navigation.duration) : null,
      dom_content_loaded_ms: navigation ? finite(navigation.domContentLoadedEventEnd) : null,
      response_end_ms: navigation ? finite(navigation.responseEnd) : null,
    },
    first_contentful_paint: { supported: state.supported.has('paint'), value: state.fcp === null ? null : finite(state.fcp) },
    largest_contentful_paint: { supported: state.supported.has('largest-contentful-paint'), value: state.lcp === null ? null : finite(state.lcp) },
    cumulative_layout_shift: { supported: state.supported.has('layout-shift'), value: state.supported.has('layout-shift') ? finite(state.cls) : null },
    observed_interactions: { supported: state.supported.has('event'), count: state.supported.has('event') ? interactionValues.length : null, max_ms: interactionValues.length ? finite(Math.max(...interactionValues)) : null },
    long_tasks: { supported: state.supported.has('longtask'), count: state.supported.has('longtask') ? state.longTasks.length : null, total_ms: state.supported.has('longtask') ? finite(state.longTasks.reduce((sum, duration) => sum + duration, 0)) : null, max_ms: state.longTasks.length ? finite(Math.max(...state.longTasks)) : null },
    resources: { supported: state.supported.has('resource'), buckets: resources },
    errors: { ...state.errors },
    caveats: [
      'Local opt-in observation only; no network telemetry is sent by this recorder.',
      'Largest contentful paint and layout shift may change until pagehide.',
      'Observed interaction durations are thresholded at 40 ms and are not INP.',
      'Resource timings and transfer sizes may be unavailable or restricted by the browser.',
    ],
  }
}

export function WorkspacePerformancePanel() {
  const [snapshot, setSnapshot] = useState<WorkspacePerformanceSnapshot | null>(null)
  useEffect(() => installWorkspacePerformance(), [])
  if (!workspaceProfilingEnabled()) return null
  const download = () => {
    const blob = new Blob([JSON.stringify(snapshotWorkspacePerformance(), null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'open-agronomy-frontend-profile.json'
    anchor.click()
    URL.revokeObjectURL(url)
  }
  return <aside aria-label="Local performance profile" style={{ position: 'fixed', right: 8, bottom: 8, zIndex: 10000, padding: 10, maxWidth: 'min(650px, 90vw)', maxHeight: '65vh', overflow: 'auto', background: '#fff', color: '#254333', border: '1px solid #bdcbb6', borderRadius: 8, fontSize: 12 }}>
    <details><summary>Local performance profile</summary><h2>Local performance profile</h2>
    <p>Opt-in browser measurements. No field text, route, query, or session identifiers are recorded.</p>
    <button type="button" onClick={() => setSnapshot(snapshotWorkspacePerformance())}>Refresh snapshot</button>{' '}
    <button type="button" onClick={download}>Download JSON</button>
    <pre data-testid="workspace-performance-snapshot" style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{snapshot ? JSON.stringify(snapshot, null, 2) : 'Refresh to inspect measurements.'}</pre>
    </details>
  </aside>
}
