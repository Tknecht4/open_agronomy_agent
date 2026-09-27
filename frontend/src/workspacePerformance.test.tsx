import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { WorkspacePerformancePanel, installWorkspacePerformance, snapshotWorkspacePerformance, workspaceProfilingEnabled } from './workspacePerformance'

const originalUrl = window.location.href
afterEach(() => {
  window.history.replaceState({}, '', originalUrl)
  vi.unstubAllGlobals()
})

describe('local workspace performance profile', () => {
  it('is opt-in and reports unsupported measurements as null', () => {
    window.history.replaceState({}, '', '/?field_id=private-field')
    expect(workspaceProfilingEnabled()).toBe(false)
    expect(installWorkspacePerformance()).toBeTypeOf('function')
    const snapshot = snapshotWorkspacePerformance()
    expect(snapshot.first_contentful_paint.value).toBeNull()
    expect(snapshot.largest_contentful_paint.value).toBeNull()
    expect(snapshot.observed_interactions.count).toBeNull()
    expect(snapshot.long_tasks.count).toBeNull()
    expect(JSON.stringify(snapshot)).not.toContain('private-field')
  })

  it('shows a readable snapshot without sending data or exposing a URL', () => {
    window.history.replaceState({}, '', '/secret-route?profile=1&field_id=private-field')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<WorkspacePerformancePanel />)
    fireEvent.click(screen.getByText('Local performance profile', { selector: 'summary' }))
    fireEvent.click(screen.getByRole('button', { name: 'Refresh snapshot' }))
    const output = screen.getByTestId('workspace-performance-snapshot').textContent || ''
    expect(JSON.parse(output)).toMatchObject({ schema: 'open-agronomy.local-performance.v1' })
    expect(output).not.toContain('private-field')
    expect(output).not.toContain('secret-route')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('uses the largest layout-shift session window and aggregates resources without URLs', () => {
    window.history.replaceState({}, '', '/?profile=1')
    const callbacks = new Map<string, PerformanceObserverCallback>()
    class FakeObserver {
      static supportedEntryTypes = ['layout-shift', 'resource', 'event', 'longtask']
      constructor(private callback: PerformanceObserverCallback) {}
      observe(options: PerformanceObserverInit) { callbacks.set(String(options.type), this.callback) }
      disconnect() {}
    }
    vi.stubGlobal('PerformanceObserver', FakeObserver)
    const stop = installWorkspacePerformance()
    const emit = (type: string, entries: object[]) => callbacks.get(type)?.({ getEntries: () => entries as PerformanceEntry[] } as PerformanceObserverEntryList, {} as PerformanceObserver)
    emit('layout-shift', [
      { startTime: 100, value: 0.06, hadRecentInput: false },
      { startTime: 300, value: 0.04, hadRecentInput: false },
      { startTime: 7000, value: 0.03, hadRecentInput: false },
    ])
    emit('resource', [{ startTime: 400, duration: 50, initiatorType: 'fetch', transferSize: 120, decodedBodySize: 300, name: 'https://example.test/api/fields/private-id' }])
    emit('event', [{ interactionId: 9, duration: 80 }, { interactionId: 9, duration: 56 }])
    emit('longtask', [{ startTime: 200, duration: 55 }])
    const snapshot = snapshotWorkspacePerformance()
    expect(snapshot.cumulative_layout_shift.value).toBe(0.1)
    expect(snapshot.observed_interactions).toMatchObject({ count: 1, max_ms: 80 })
    expect(snapshot.resources.buckets.fetch).toMatchObject({ count: 1, transfer_bytes: 120 })
    expect(snapshot.long_tasks).toMatchObject({ count: 1, max_ms: 55 })
    expect(JSON.stringify(snapshot)).not.toContain('private-id')
    stop()
  })
})
