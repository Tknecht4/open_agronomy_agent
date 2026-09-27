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
afterEach(() => vi.unstubAllGlobals())

describe('on-demand field map insights', () => {
  it('shows geometry, bounded source coverage and units without another request', async () => {
    const fetcher = vi.fn().mockResolvedValue(response(result))
    vi.stubGlobal('fetch', fetcher)
    render(<FieldMapInsights {...props} />)
    expect(await screen.findByText('10 ha')).toBeInTheDocument()
    expect(screen.getByText('1.3 km')).toBeInTheDocument()
    expect(screen.getByText('Test mapped zone')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'ac' }))
    expect(screen.getByText('24.7 ac')).toBeInTheDocument()
    expect(fetcher).toHaveBeenCalledOnce()
    const request = JSON.parse(fetcher.mock.calls[0][1].body)
    expect(request).toEqual({ geometry, layers: ['canada_ecozones'] })
    expect(screen.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', 'https://example.test/official')
  })

  it('keeps zero mapped coverage distinct from unavailable data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ...result, status: 'partial', layers: [
      { ...result.layers[0], zones: [], covered_area_ha: 0, coverage_fraction: 0 },
      { ...result.layers[0], layer_id: 'ab_detailed_soil', label: 'Alberta soils', status: 'not_installed', reason: 'local_layer_not_installed', zones: [], covered_area_ha: null, coverage_fraction: null },
    ] })))
    render(<FieldMapInsights {...props} />)
    expect(await screen.findByText('0%')).toBeInTheDocument()
    expect(screen.getByText('Not installed')).toBeInTheDocument()
    expect(screen.getByText('This map pack is not installed.')).toBeInTheDocument()
    expect(screen.getAllByText('0%')).toHaveLength(1)
  })

  it('does not invent area from a point location', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ ...result,
      geometry: { ...result.geometry, type: 'Point', area_ha: null, area_ac: null, perimeter_m: null },
      layers: [{ ...result.layers[0], covered_area_ha: null, coverage_fraction: null, zones: [{ ...result.layers[0].zones[0], area_ha: null, fraction_of_field: null }] }],
    })))
    render(<FieldMapInsights {...props} geometry={{ type: 'Point', coordinates: [-113.6, 53.3] }} />)
    expect(await screen.findByText('Pin only')).toBeInTheDocument()
    expect(screen.getByText('At this location')).toBeInTheDocument()
    expect(screen.queryByText('50%')).not.toBeInTheDocument()
  })

  it('rejects stale results after a field changes and aborts on unmount', async () => {
    let release!: (value: unknown) => void
    const pending = new Promise(resolve => { release = resolve })
    const fetcher = vi.fn().mockReturnValueOnce(pending).mockResolvedValueOnce(response({ ...result, geometry: { ...result.geometry, area_ha: 20 } }))
    vi.stubGlobal('fetch', fetcher)
    const { rerender, unmount } = render(<FieldMapInsights {...props} />)
    rerender(<FieldMapInsights {...props} fieldKey="field-two" fieldName="South field" />)
    expect(await screen.findByText('20 ha')).toBeInTheDocument()
    await act(async () => { release(response(result)); await pending })
    expect(screen.queryByText('10 ha')).not.toBeInTheDocument()
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true)
    unmount()
    expect(fetcher.mock.calls[1][1].signal.aborted).toBe(true)
  })

  it('provides retry after a failed response without displaying raw server paths', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce({ ok: false, status: 500, text: async () => '/private/server/path' }).mockResolvedValueOnce(response(result))
    vi.stubGlobal('fetch', fetcher)
    render(<FieldMapInsights {...props} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Field insights are unavailable')
    expect(screen.queryByText('/private/server/path')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    await waitFor(() => expect(screen.getByText('10 ha')).toBeInTheDocument())
  })
  it('keeps recorded acreage distinct from a boundary-derived estimate', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(result)))
    render(<FieldMapInsights {...props} recordedAcres={40} />)
    expect(await screen.findByText('10 ha')).toBeInTheDocument()
    expect(screen.getByText('40 ac')).toBeInTheDocument()
    expect(screen.getByText('24.7 ac')).toBeInTheDocument()
    expect(screen.getByText(/Your field record says/)).toHaveTextContent('This boundary is about')
  })

})
