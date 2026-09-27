import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FieldImageryAnalyticsPanel } from './FieldImageryAnalyticsPanel'

const apiGet = vi.hoisted(() => vi.fn())
const apiPost = vi.hoisted(() => vi.fn())
vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return { ...actual, apiGet, apiPost }
})

const hash = 'a'.repeat(64)
const previewPath = `/api/demo/fields/field-1/imagery/analyses/${hash}/preview.png`
const receipt = {
  status: 'available', chip_hash: hash, geometry_hash: 'b'.repeat(64), process_version: 'hls-chip-v2',
  preview_url: previewPath, elapsed_seconds: 1.2, cog_transfer_bytes: null,
  source: { provider_id: 'hls-s30-planetary-computer', collection: 'hls2-s30', scene_id: 'hls2-s30:scene-1', acquired_at: '2025-06-10T00:00:00Z',
    availability_at: '2025-06-11T00:00:00Z', scene_cloud_percent: 25, asset_ids: { B04: 'hls2-s30:scene-1:B04' } },
  qa: { field_area_m2: 10000, valid_area_m2: 8000, valid_area_fraction: 0.8, nodata_area_m2: 0,
    excluded_area_m2_by_reason: { cloud: 1500 }, overlap_note: 'QA reason areas may overlap; do not sum them' },
  zonal_stats: { NDVI: { mean: 0.53, min: 0.1, max: 0.8, area_m2: 8000 }, NDMI: { mean: null, min: null, max: null, area_m2: 0 } },
}

const objectUrl = vi.fn(() => 'blob:field-preview')
const revokeUrl = vi.fn()

function open() { fireEvent.click(screen.getByText('Observed satellite indices')) }
function setDates() {
  fireEvent.change(screen.getByLabelText('Acquired from'), { target: { value: '2025-06-01' } })
  fireEvent.change(screen.getByLabelText('Acquired through'), { target: { value: '2025-06-30' } })
}

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
  objectUrl.mockClear()
  revokeUrl.mockClear()
  apiGet.mockResolvedValue({ status: 'ready', network_mode: 'online' })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, headers: { get: () => 'image/png' }, blob: async () => new Blob(['png'], { type: 'image/png' }) }))
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: objectUrl })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeUrl })
  document.cookie = 'agronomy_csrf=token123'
})

afterEach(() => { vi.unstubAllGlobals(); document.cookie = 'agronomy_csrf=; Max-Age=0' })

describe('FieldImageryAnalyticsPanel', () => {
  it('shows server-observed indices and loads its preview through an authenticated request', async () => {
    apiPost.mockResolvedValue(receipt)
    const view = render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-1" imageryReady />)
    open()
    setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(await screen.findByText('Observed indices for the saved field polygon.')).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledWith('/api/demo/fields/field-1/imagery/analyze', {
      provider_id: 'hls-s30-planetary-computer', start_date: '2025-06-01', end_date: '2025-06-30', buffer_m: 0,
    })
    const result = screen.getByRole('region', { name: 'Imagery analysis result' })
    expect(within(result).getByText('0.530')).toBeInTheDocument()
    expect(within(result).getByText('Unknown')).toBeInTheDocument()
    expect(within(result).getByText(/Scene cloud 25.0% · field clear coverage 80.0%/)).toBeInTheDocument()
    fireEvent.click(within(result).getByText('Source and processing details'))
    expect(within(result).getByText('B04: hls2-s30:scene-1:B04')).toBeInTheDocument()
    expect(await within(result).findByRole('img')).toHaveAttribute('src', 'blob:field-preview')
    expect(within(result).getByText(/enlarged for inspection from 30 m source pixels/)).toBeInTheDocument()
    expect(within(result).getByLabelText('NDVI preview color scale')).toHaveTextContent('−10+1Transparent: outside field, excluded by QA, or undefined index')
    expect(within(result).getByRole('img')).toHaveAttribute('alt', expect.stringContaining('undefined index'))
    expect(fetch).toHaveBeenCalledWith(previewPath, expect.objectContaining({ credentials: 'same-origin', headers: { 'X-CSRF-Token': 'token123' } }))
    view.rerender(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-2" imageryReady />)
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Imagery analysis result' })).not.toBeInTheDocument())
    expect(revokeUrl).toHaveBeenCalledWith('blob:field-preview')
  })

  it('blocks processing without a polygon or optional runtime', async () => {
    apiGet.mockResolvedValue({ status: 'not_configured', network_mode: 'online' })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="none" imageryReady={false} />)
    open()
    setDates()
    expect(await screen.findByText(/Optional imagery processing is not installed/)).toBeInTheDocument()
    expect(screen.getByText(/A point or unknown location is insufficient/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeDisabled()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('reports offline cache miss and keeps unavailable index values unknown', async () => {
    apiGet.mockResolvedValue({ status: 'ready', network_mode: 'offline' })
    apiPost.mockResolvedValue({ status: 'blocked_offline' })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-1" imageryReady />)
    open()
    setDates()
    expect(await screen.findByText(/Network access is off/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(await screen.findByText(/no matching cached analysis/)).toBeInTheDocument()
    expect(screen.queryByText('0.530')).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('drops an analysis response after geometry changes', async () => {
    let resolveAnalysis!: (value: unknown) => void
    apiPost.mockReturnValue(new Promise(resolve => { resolveAnalysis = resolve }))
    const view = render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-1" imageryReady />)
    open()
    setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    view.rerender(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point" imageryReady={false} />)
    resolveAnalysis(receipt)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeDisabled())
    expect(screen.queryByRole('region', { name: 'Imagery analysis result' })).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })
})
