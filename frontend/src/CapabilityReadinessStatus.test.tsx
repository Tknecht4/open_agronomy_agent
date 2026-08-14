import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CapabilityReadinessStatus, summarizeCapabilityRegistry } from './CapabilityReadinessStatus'

const response = (payload: unknown): Response =>
  ({
    ok: true,
    status: 200,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  }) as Response

const catalog = {
  schema_version: 'open_agronomy_agent.capability_registry.v1',
  surface: 'all',
  capability_count: 3,
  capabilities: [
    { capability_id: 'calculator', status: { implemented: true, tested: true, benchmark_exercised: true } },
    { capability_id: 'retriever', status: { implemented: true, tested: true, benchmark_exercised: false } },
    { capability_id: 'weather', status: { implemented: true, tested: true, benchmark_exercised: false } },
  ],
  preflight: { status: 'passed', issues: [] },
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('canonical capability registry readiness', () => {
  it('loads the all-surface catalog and renders a compact, bounded status', async () => {
    const fetchMock = vi.fn(async () => response(catalog))
    vi.stubGlobal('fetch', fetchMock)

    render(<CapabilityReadinessStatus />)

    expect(screen.getByTestId('capability-registry-status')).toHaveTextContent('Capability registry loading')
    await waitFor(() => {
      expect(screen.getByTestId('capability-registry-status')).toHaveTextContent(
        'Capabilities 3/3 implemented · parity passed',
      )
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/tools/capabilities')
    expect(screen.getByTestId('capability-registry-status')).toHaveAttribute('data-capability-state', 'ready')
    expect(screen.getByTestId('capability-registry-status')).toHaveAttribute(
      'title',
      expect.stringContaining('1/3 benchmark-exercised'),
    )
    expect(screen.getByTestId('capability-registry-status')).toHaveAttribute(
      'title',
      expect.stringContaining('does not prove live provider access or agronomic validity'),
    )
  })

  it('marks incomplete implementation or failed parity for review', () => {
    const summary = summarizeCapabilityRegistry({
      ...catalog,
      capabilities: [
        catalog.capabilities[0],
        { ...catalog.capabilities[1], status: { ...catalog.capabilities[1].status, implemented: false } },
        catalog.capabilities[2],
      ],
      preflight: { status: 'failed', issues: [{ code: 'missing_surface' }] },
    })

    expect(summary.state).toBe('review')
    expect(summary.label).toBe('Capabilities 2/3 implemented · parity failed')
  })

  it('fails closed when the service response is malformed or unavailable', async () => {
    const fetchMock = vi.fn(async () => response({ capability_count: 0 }))
    vi.stubGlobal('fetch', fetchMock)

    render(<CapabilityReadinessStatus />)

    expect(await screen.findByText('Capability registry unavailable')).toHaveAttribute(
      'data-capability-state',
      'unavailable',
    )
  })
})
