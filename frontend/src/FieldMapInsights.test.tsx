import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FieldMapInsights, type FieldMapAnalysis } from './FieldMapInsights'

const geometry = { type: 'Polygon', coordinates: [[[-113.61, 53.3], [-113.6, 53.3], [-113.6, 53.31], [-113.61, 53.3]]] }
const props = { geometry, fieldKey: 'field-one', fieldName: 'North field', layerIds: ['canada_ecozones'], allowNetwork: true }
const result: FieldMapAnalysis = {
  schema_version: 'open_agronomy_agent.field_map_analysis.v1', status: 'complete',
  geometry: { type: 'Polygon', status: 'complete', area_ha: 10, area_ac: 24.71, perimeter_m: 1300,
    location: { longitude: -113.605, latitude: 53.304 }, method: 'WGS84 ellipsoid' },
  layers: [{ layer_id: 'canada_ecozones', label: 'Canada ecozones', source_mode: 'arcgis', status: 'complete', feature_count: 1,
    source_url: 'https://example.test/official', covered_area_ha: 5, coverage_fraction: 0.5,
    zones: [{ code: 'Z1', name: 'Test mapped zone', area_ha: 5, fraction_of_field: 0.5 }], omitted_zone_count: 0 }],
  elapsed_ms: 12, warnings: ['Mapped context is not a measurement.'],
}
const response = (data: FieldMapAnalysis) => ({ ok: true, json: async () => data })
const geometryResult = { ...result, layers: [] }
const isGeometryOnly = (options: RequestInit) => JSON.parse(String(options.body)).layers.length === 0
const deferred = () => {
  let resolve!: (value: unknown) => void
  const promise = new Promise(release => { resolve = release })
  return { promise, resolve }
}
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('compact on-demand field map insights', () => {
  it('shows a compact summary and discloses zone areas and source details without refetching', async () => {
    const fetcher = vi.fn().mockResolvedValue(response(result))
    vi.stubGlobal('fetch', fetcher)
    render(<FieldMapInsights {...props} />)
    expect(await screen.findByText('10 ha')).toBeInTheDocument()
    expect(screen.getByText('1.3 km')).toBeInTheDocument()
    expect(screen.getByText('Canada ecozones', { selector: '.insight-layer-label strong' }).closest('details')).not.toHaveAttribute('open')
    expect(screen.getByRole('link', { name: 'Open source' })).not.toBeVisible()
    fireEvent.click(screen.getByText('Canada ecozones', { selector: '.insight-layer-label strong' }))
    expect(screen.getByRole('table', { name: 'Mapped zones in Canada ecozones' })).toHaveTextContent('Test mapped zone5 ha50%')
    expect(screen.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', 'https://example.test/official')
    fireEvent.click(screen.getByRole('button', { name: 'ac' }))
    expect(screen.getByText('24.7 ac')).toBeInTheDocument()
    expect(screen.getByRole('table')).toHaveTextContent('12.4 ac')
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(fetcher.mock.calls.map(call => JSON.parse(call[1].body).layers)).toEqual([[], ['canada_ecozones']])
  })

  it('shows measurements while sources remain pending, then retains them if sources fail', async () => {
    const source = deferred()
    vi.stubGlobal('fetch', vi.fn((_url, options) => isGeometryOnly(options) ? Promise.resolve(response(geometryResult)) : source.promise))
    render(<FieldMapInsights {...props} />)
    expect(await screen.findByText('10 ha')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Reading 1 map source')
    await act(async () => { source.resolve({ ok: false, status: 503 }); await source.promise })
    expect(screen.getByRole('alert')).toHaveTextContent('Boundary measurements remain available above')
    expect(screen.getByText('10 ha')).toBeInTheDocument()
    expect(screen.queryByText('Canada ecozones')).not.toBeInTheDocument()
  })

  it('keeps zero mapped coverage distinct from unavailable data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ...result, status: 'partial', layers: [
      { ...result.layers[0], zones: [], covered_area_ha: 0, coverage_fraction: 0 },
      { ...result.layers[0], layer_id: 'ab_detailed_soil', label: 'Alberta soils', status: 'not_installed', reason: 'local_layer_not_installed', zones: [], covered_area_ha: null, coverage_fraction: null },
    ] })))
    render(<FieldMapInsights {...props} />)
    expect(await screen.findByText('Not installed')).toBeInTheDocument()
    expect(screen.getByText(/This map pack is not installed/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('1 layer had no mapped match'))
    expect(screen.getAllByText('0%')).toHaveLength(1)
  })

  it('keeps partial-source warnings visible while details are collapsed', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ...result, status: 'partial', layers: [
      { ...result.layers[0], status: 'partial', reason: 'source_transfer_limit_reached', covered_area_ha: null, coverage_fraction: null },
    ] })))
    render(<FieldMapInsights {...props} />)
    expect(await screen.findByText(/Total coverage is unknown/)).toBeVisible()
    expect(screen.getByText('Canada ecozones', { selector: '.insight-layer-label strong' }).closest('details')).not.toHaveAttribute('open')
    expect(screen.queryByText('50%', { selector: '.insight-layer-value strong' })).not.toBeInTheDocument()
  })

  it('does not invent area from a point location', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ...result,
      geometry: { ...result.geometry, type: 'Point', area_ha: null, area_ac: null, perimeter_m: null },
      layers: [{ ...result.layers[0], covered_area_ha: null, coverage_fraction: null, zones: [{ ...result.layers[0].zones[0], area_ha: null, fraction_of_field: null }] }],
    })))
    render(<FieldMapInsights {...props} geometry={{ type: 'Point', coordinates: [-113.6, 53.3] }} />)
    expect(await screen.findByText(/Pin only/)).toBeInTheDocument()
    expect(screen.getByText('At this location')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Area units' })).not.toBeInTheDocument()
    expect(screen.queryByText('50%')).not.toBeInTheDocument()
    expect(screen.queryByText('Boundary length')).not.toBeInTheDocument()
  })

  it('rejects late geometry and source results after changing field and aborts on unmount', async () => {
    const pending = [deferred(), deferred()]
    const fetcher = vi.fn().mockReturnValueOnce(pending[0].promise).mockReturnValueOnce(pending[1].promise)
      .mockResolvedValue(response({ ...result, geometry: { ...result.geometry, area_ha: 20 } }))
    vi.stubGlobal('fetch', fetcher)
    const { rerender, unmount } = render(<FieldMapInsights {...props} />)
    rerender(<FieldMapInsights {...props} fieldKey="field-two" fieldName="South field" />)
    expect(await screen.findByText('20 ha')).toBeInTheDocument()
    await act(async () => { pending.forEach(item => item.resolve(response(result))); await Promise.all(pending.map(item => item.promise)) })
    expect(screen.queryByText('10 ha')).not.toBeInTheDocument()
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
    expect(fetcher.mock.calls[1][1].signal.aborted).toBe(true)
    unmount()
    expect(fetcher.mock.calls.every(call => call[1].signal.aborted)).toBe(true)
  })

  it('does not repeat geometry requests when only selected layers change', async () => {
    const source = deferred()
    const fetcher = vi.fn((_url, options) => isGeometryOnly(options) ? Promise.resolve(response(geometryResult)) : source.promise)
    vi.stubGlobal('fetch', fetcher)
    const { rerender } = render(<FieldMapInsights {...props} />)
    expect(await screen.findByText('10 ha')).toBeInTheDocument()
    rerender(<FieldMapInsights {...props} layerIds={['other-layer']} />)
    expect(fetcher).toHaveBeenCalledTimes(3)
    expect(fetcher.mock.calls.filter(call => isGeometryOnly(call[1]))).toHaveLength(1)
    expect(fetcher.mock.calls[1][1].signal.aborted).toBe(true)
    expect(screen.getByText('10 ha')).toBeInTheDocument()
  })

  it('uses just one geometry-only request with no selected layers', async () => {
    const fetcher = vi.fn().mockResolvedValue(response(geometryResult))
    vi.stubGlobal('fetch', fetcher)
    render(<FieldMapInsights {...props} layerIds={[]} allowNetwork={false} />)
    expect(await screen.findByText('10 ha')).toBeInTheDocument()
    expect(fetcher).toHaveBeenCalledOnce()
    expect(isGeometryOnly(fetcher.mock.calls[0][1])).toBe(true)
  })

  it('retries a failed source response without displaying raw server paths', async () => {
    let sourceCalls = 0
    const fetcher = vi.fn((_url, options) => Promise.resolve(isGeometryOnly(options) ? response(geometryResult) : ++sourceCalls === 1 ? { ok: false, status: 500, text: async () => '/private/server/path' } : response(result)))
    vi.stubGlobal('fetch', fetcher)
    render(<FieldMapInsights {...props} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Field insights are unavailable')
    expect(screen.queryByText('/private/server/path')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(screen.getByText('Canada ecozones', { selector: '.insight-layer-label strong' })).toBeInTheDocument())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps recorded acreage distinct from the boundary estimate', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(result)))
    render(<FieldMapInsights {...props} recordedAcres={40} />)
    expect(await screen.findByText('10 ha')).toBeInTheDocument()
    expect(screen.getByText('40 ac recorded')).toBeInTheDocument()
    expect(screen.getByText('24.7 ac from boundary')).toBeInTheDocument()
  })

  it('times out sources without losing geometry, and ignores a late response', async () => {
    vi.useFakeTimers()
    const source = deferred()
    vi.stubGlobal('fetch', vi.fn((_url, options) => isGeometryOnly(options) ? Promise.resolve(response(geometryResult)) : source.promise))
    render(<FieldMapInsights {...props} />)
    await act(async () => { await Promise.resolve() })
    expect(screen.getByText('10 ha')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
    expect(screen.getByRole('alert')).toHaveTextContent('taking too long')
    await act(async () => { source.resolve(response(result)); await source.promise })
    expect(screen.queryByText('Canada ecozones')).not.toBeInTheDocument()
    expect(screen.getByText('10 ha')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeEnabled()
  })
})
