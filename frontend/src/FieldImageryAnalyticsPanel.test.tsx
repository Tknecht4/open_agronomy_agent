import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FieldImageryAnalyticsPanel } from './FieldImageryAnalyticsPanel'

const apiGet = vi.hoisted(() => vi.fn())
const apiPost = vi.hoisted(() => vi.fn())
vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api')
  return { ...actual, apiGet, apiPost }
})

const polygon = { kind: 'polygon' as const, points: [{lon:-113.61,lat:53.3},{lon:-113.6,lat:53.3},{lon:-113.6,lat:53.31}], acres: 1 }
const point = { kind: 'point' as const, point: { lon: -113.6, lat: 53.3 } }
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

const pointAvailability = { status: 'ready', network_mode: 'online', sampling_modes: ['field_polygon', 'point_pixel', 'point_buffer'], sample_radius_bounds_m: { min: 15, max: 1500 } }
const pointReceipt = {
  ...receipt,
  grid: { crs: 'EPSG:32612', width: 1, height: 1, resolution_m: 30, resampling_method: 'nearest' },
  zonal_stats: { NDVI: { mean: 0.53, min: 0.53, max: 0.53, area_m2: 900 }, NDMI: { mean: null, min: null, max: null, area_m2: 0 } },
  sampling: {
    schema_version: 'imagery_sampling.v1', mode: 'point_pixel', support_kind: 'native_pixel',
    original_geometry: { type: 'Point', coordinates: [-113.6, 53.3] },
    footprint: { type: 'Polygon', coordinates: [[[-113.6003,53.2999],[-113.5999,53.2999],[-113.5999,53.3002],[-113.6003,53.3002],[-113.6003,53.2999]]] },
    footprint_crs: 'EPSG:4326', sample_radius_m: null, native_resolution_m: 30,
    pixel_count: 1, valid_pixel_count: 1, positional_uncertainty_m: null, point_role: 'unspecified',
    area_basis: 'native_grid_projected_metres', edge_policy: 'containing_pixel_floor',
    limitation: 'A sampled pixel may include neighboring land cover; it is not a field boundary.',
  },
  qa: { sample_area_m2: 900, valid_area_m2: 900, valid_area_fraction: 1, nodata_area_m2: 0,
    excluded_area_m2_by_reason: {}, overlap_note: 'QA reasons may overlap.' },
}
const v4PointReceipt = {
  ...pointReceipt,
  process_version: 'hls-point-sample-v4-hls-radiometry-index-qa',
  qa: { ...pointReceipt.qa, water_flag_area_m2: 0,
    index_undefined_area_m2_by_reason: {
      ndvi_negative_reflectance: 0, ndvi_nonpositive_denominator: 0,
      ndmi_negative_reflectance: 0, ndmi_nonpositive_denominator: 0,
    } },
  zonal_stats: { NDVI: pointReceipt.zonal_stats.NDVI,
    NDMI: { mean: 0.3, min: 0.3, max: 0.3, area_m2: 900 } },
}
const bufferArea = Math.PI * 60 ** 2 * Math.sin(2 * Math.PI / 256) / (2 * Math.PI / 256)
const bufferReceipt = { ...pointReceipt,
  zonal_stats: { NDVI: { mean: 0.53, min: 0.1, max: 0.8, area_m2: 8000 }, NDMI: { mean: null, min: null, max: null, area_m2: 0 } },
  grid: { ...pointReceipt.grid, width: 4, height: 4 },
  sampling: { ...pointReceipt.sampling, mode: 'point_buffer', support_kind: 'point_buffer', sample_radius_m: 60, pixel_count: 16, valid_pixel_count: 12 },
  qa: { ...pointReceipt.qa, sample_area_m2: bufferArea, valid_area_m2: 8000, valid_area_fraction: 8000 / bufferArea, excluded_area_m2_by_reason: { cloud: bufferArea - 8000 } },
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
    const view = render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-1" geometry={polygon} imageryReady />)
    open()
    setDates()
    expect(await screen.findByText(/sends the saved field polygon and selected dates to Microsoft Planetary Computer/)).toHaveTextContent('No account is required.')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(await screen.findByText('Observed indices for the saved field polygon.')).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledWith('/api/demo/fields/field-1/imagery/analyze', {
      provider_id: 'hls-s30-planetary-computer', start_date: '2025-06-01', end_date: '2025-06-30', buffer_m: 0,
    })
    const result = screen.getByRole('region', { name: 'Imagery analysis result' })
    expect(within(result).getByText('0.530')).toBeInTheDocument()
    expect(within(result).getByText('Unknown')).toBeInTheDocument()
    expect(within(result).getByText(/Scene cloud 25.0% · field QA clear coverage 80.0%/)).toBeInTheDocument()
    fireEvent.click(within(result).getByText('Source and processing details'))
    expect(within(result).getByText('B04: hls2-s30:scene-1:B04')).toBeInTheDocument()
    expect(await within(result).findByRole('img')).toHaveAttribute('src', 'blob:field-preview')
    expect(within(result).getByText(/enlarged for inspection from 30 m source pixels/)).toBeInTheDocument()
    expect(within(result).getByLabelText('NDVI preview color scale')).toHaveTextContent('−10+1Transparent: outside field, excluded by QA, or undefined index')
    expect(within(result).getByRole('img')).toHaveAttribute('alt', expect.stringContaining('undefined index'))
    expect(fetch).toHaveBeenCalledWith(previewPath, expect.objectContaining({ credentials: 'same-origin', headers: { 'X-CSRF-Token': 'token123' } }))
    view.rerender(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-2" geometry={polygon} imageryReady />)
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Imagery analysis result' })).not.toBeInTheDocument())
    expect(revokeUrl).toHaveBeenCalledWith('blob:field-preview')
  })

  it('blocks processing without saved geometry or optional runtime', async () => {
    apiGet.mockResolvedValue({ status: 'not_configured', network_mode: 'online' })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="none" geometry={{kind:'none'}} imageryReady={false} />)
    open()
    setDates()
    expect(await screen.findByText(/Optional imagery processing is not installed/)).toBeInTheDocument()
    expect(screen.getByText(/Add and save a location or boundary/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeDisabled()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('reports offline cache miss and keeps unavailable index values unknown', async () => {
    apiGet.mockResolvedValue({ status: 'ready', network_mode: 'offline' })
    apiPost.mockResolvedValue({ status: 'blocked_offline' })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-1" geometry={polygon} imageryReady />)
    open()
    setDates()
    expect(await screen.findByText(/Network access is off/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(await screen.findByText(/no matching cached analysis/)).toBeInTheDocument()
    expect(screen.queryByText('0.530')).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it.each([
    ['storage_limit', /imagery storage limit or free-disk reserve has been reached/, /Existing cached analyses remain available/],
    ['storage_unavailable', /local imagery cache could not be verified or opened/, /No new imagery was fetched/],
  ])('shows the typed %s failure without inventing observations', async (status, message, consequence) => {
    apiPost.mockResolvedValue({ status })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-1" geometry={polygon} imageryReady />)
    open()
    setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    const result = await screen.findByRole('region', { name: 'Imagery analysis result' })
    expect(within(result).getByRole('status')).toHaveTextContent(message)
    expect(within(result).getByRole('status')).toHaveTextContent(consequence)
    expect(within(result).queryByText('0.530')).not.toBeInTheDocument()
    expect(within(result).queryByRole('img')).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('labels an exact offline cache read and still loads its authenticated preview', async () => {
    apiGet.mockResolvedValue({ status: 'ready', network_mode: 'offline' })
    apiPost.mockResolvedValue({ ...receipt, cache_hit: true, cog_transfer_bytes: 819200 })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-1" geometry={polygon} imageryReady />)
    open()
    setDates()
    expect(await screen.findByText(/An exact cached analysis may still be available/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    const result = await screen.findByRole('region', { name: 'Imagery analysis result' })
    expect(within(result).getByText('Observed indices for the saved field polygon.')).toBeInTheDocument()
    expect(within(result).getByText(/· cached$/)).toBeInTheDocument()
    expect(within(result).getByText(/COG transfer 819,200 bytes/)).toBeInTheDocument()
    expect(await within(result).findByRole('img')).toHaveAttribute('src', 'blob:field-preview')
    expect(fetch).toHaveBeenCalledWith(previewPath, expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('drops an analysis response after geometry changes', async () => {
    let resolveAnalysis!: (value: unknown) => void
    apiPost.mockReturnValue(new Promise(resolve => { resolveAnalysis = resolve }))
    const view = render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-1" geometry={polygon} imageryReady />)
    open()
    setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    view.rerender(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point" geometry={point} imageryReady={false} />)
    resolveAnalysis(receipt)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeDisabled())
    expect(screen.queryByRole('region', { name: 'Imagery analysis result' })).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('defaults a saved point to its native pixel and labels preview/QA from the receipt', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue(pointReceipt)
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    expect(screen.getByLabelText('Sample')).toHaveValue('point_pixel')
    expect(screen.queryByLabelText('Radius (m)')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(apiPost).toHaveBeenCalledWith('/api/demo/fields/field-1/imagery/analyze', {
      provider_id: 'hls-s30-planetary-computer', start_date: '2025-06-01', end_date: '2025-06-30', buffer_m: 0, sampling_mode: 'point_pixel',
    })
    const result = await screen.findByRole('region', { name: 'Imagery analysis result' })
    expect(within(result).getByText('Observed indices for the sampled pixel.')).toBeInTheDocument()
    expect(within(result).getByText('Sample area 900 m²')).toBeInTheDocument()
    expect(within(result).getByText(/1 of 1 sample pixels pass QA/)).toBeInTheDocument()
    expect(within(result).getByText(/sample QA clear fraction 100.0%/)).toBeInTheDocument()
    expect(within(result).queryByText(/Field area|field clear coverage|whole.field/)).not.toBeInTheDocument()
    expect(await within(result).findByRole('img')).toHaveAttribute('alt', expect.stringContaining('sampled pixel'))
    expect(within(result).getByText(/sample may include neighboring land cover/)).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(previewPath, expect.objectContaining({ credentials: 'same-origin', headers: { 'X-CSRF-Token': 'token123' } }))
  })

  it('separates water flags and undefined index support from QA clear area', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue({ ...pointReceipt,
      qa: { ...pointReceipt.qa, water_flag_area_m2: 900,
        index_undefined_area_m2_by_reason: { ndvi_negative_reflectance: 900, ndvi_nonpositive_denominator: 0 } },
      zonal_stats: { ...pointReceipt.zonal_stats,
        NDVI: { mean: null, min: null, max: null, area_m2: 0 } },
    })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    const result = await screen.findByRole('region', { name: 'Imagery analysis result' })
    expect(within(result).getByText('QA clear area 900 m²')).toBeInTheDocument()
    expect(within(result).getByText(/Water flagged area 900 m² · retained in QA clear area/)).toBeInTheDocument()
    fireEvent.click(within(result).getByText('Index support limits'))
    expect(within(result).getByText('ndvi negative reflectance: 900 m²')).toBeInTheDocument()
    expect(within(result).getByText(/Negative reflectance or a near-zero band sum/)).toBeInTheDocument()
  })

  it.each([
    ['negative area overlaps NDVI support', { ...v4PointReceipt.qa,
      index_undefined_area_m2_by_reason: { ...v4PointReceipt.qa.index_undefined_area_m2_by_reason, ndvi_negative_reflectance: 900 } }],
    ['nonpositive area overlaps NDMI support', { ...v4PointReceipt.qa,
      index_undefined_area_m2_by_reason: { ...v4PointReceipt.qa.index_undefined_area_m2_by_reason, ndmi_nonpositive_denominator: 900 } }],
    ['missing reason', { ...v4PointReceipt.qa, index_undefined_area_m2_by_reason: {
      ndvi_negative_reflectance: 0, ndvi_nonpositive_denominator: 0, ndmi_negative_reflectance: 0 } }],
    ['extra reason', { ...v4PointReceipt.qa, index_undefined_area_m2_by_reason: {
      ...v4PointReceipt.qa.index_undefined_area_m2_by_reason, unknown: 0 } }],
    ['nonfinite reason', { ...v4PointReceipt.qa, index_undefined_area_m2_by_reason: {
      ...v4PointReceipt.qa.index_undefined_area_m2_by_reason, ndvi_negative_reflectance: NaN } }],
    ['missing reason map', { ...v4PointReceipt.qa, index_undefined_area_m2_by_reason: undefined }],
  ])('rejects v4 point receipt when %s', async (_label, qa) => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue({ ...v4PointReceipt, qa })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(await screen.findByText(/response did not confirm the requested sampling area/)).toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('renders a v4 point receipt with exact index support partition', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue(v4PointReceipt)
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(await screen.findByText('Observed indices for the sampled pixel.')).toBeInTheDocument()
  })

  it('reveals a bounded explicit radius only for area sampling and invalidates results when it changes', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue(bufferReceipt)
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(() => expect(screen.getByRole('option', { name: 'Area around location' })).toBeEnabled())
    fireEvent.change(screen.getByLabelText('Sample'), { target: { value: 'point_buffer' } })
    expect(screen.getByLabelText('Radius (m)')).toHaveValue(60)
    for (const radius of ['14', '1501', '29.5', '']) {
      fireEvent.change(screen.getByLabelText('Radius (m)'), { target: { value: radius } })
      expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeDisabled()
      fireEvent.submit(screen.getByRole('button', { name: 'Analyze scene' }).closest('form')!)
    }
    expect(apiPost).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Radius (m)'), { target: { value: '60' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(apiPost).toHaveBeenLastCalledWith('/api/demo/fields/field-1/imagery/analyze', expect.objectContaining({sampling_mode:'point_buffer',sample_radius_m:60,buffer_m:0}))
    const result = await screen.findByRole('region', { name: 'Imagery analysis result' })
    expect(within(result).getByText('Observed indices for the sampling area.')).toBeInTheDocument()
    expect(await within(result).findByRole('img')).toHaveAttribute('alt', expect.stringContaining('sampling area'))
    fireEvent.change(screen.getByLabelText('Radius (m)'), { target: { value: '90' } })
    expect(screen.queryByRole('region', {name:'Imagery analysis result'})).not.toBeInTheDocument()
    expect(revokeUrl).toHaveBeenCalledWith('blob:field-preview')
  })

  it('keeps point actions blocked on an older backend while preserving polygon support', async () => {
    const view = render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    expect(await screen.findByText('Point sampling is not supported by this runtime.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeDisabled()
    view.rerender(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="polygon-1" geometry={polygon} imageryReady />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    expect(screen.queryByLabelText('Sample')).not.toBeInTheDocument()
  })

  it.each([
    ['missing grid', { ...pointReceipt, grid: undefined }],
    ['oversized native pixel area', { ...pointReceipt, qa: { ...pointReceipt.qa, sample_area_m2: 100000, valid_area_m2: 100000 } }],
    ['empty status with valid pixel', { ...pointReceipt, status: 'empty_valid_area' }],
    ['available status with no valid pixel', { ...pointReceipt, sampling: { ...pointReceipt.sampling, valid_pixel_count: 0 }, qa: { ...pointReceipt.qa, valid_area_m2: 0, valid_area_fraction: 0 } }],
    ['partial area for native pixel', { ...pointReceipt, qa: { ...pointReceipt.qa, valid_area_m2: 450, valid_area_fraction: 0.5 } }],
    ['non-unit native pixel grid', { ...pointReceipt, grid: { ...pointReceipt.grid, width: 2 } }],
    ['counts exceed grid', { ...pointReceipt, sampling: { ...pointReceipt.sampling, pixel_count: 2 }, grid: { ...pointReceipt.grid, width: 1, height: 1 } }],
    ['unbounded grid', { ...pointReceipt, grid: { ...pointReceipt.grid, width: 257 } }],
    ['wrong grid resolution', { ...pointReceipt, grid: { ...pointReceipt.grid, resolution_m: 10 } }],
    ['footprint away from saved point', { ...pointReceipt, sampling: { ...pointReceipt.sampling, footprint: { type:'Polygon',coordinates:[[[0,0],[1,0],[1,1],[0,1],[0,0]]] } } }],
    ['point in footprint hole', { ...pointReceipt, sampling: { ...pointReceipt.sampling, footprint: { type:'Polygon',coordinates:[pointReceipt.sampling.footprint.coordinates[0], [[-113.6001,53.29995],[-113.59995,53.29995],[-113.59995,53.3001],[-113.6001,53.3001],[-113.6001,53.29995]]] } } }],
    ['unbounded footprint', { ...pointReceipt, sampling: { ...pointReceipt.sampling, footprint: { type:'Polygon',coordinates:[Array.from({length:1025},()=>pointReceipt.sampling.footprint.coordinates[0][0])] } } }],
    ['missing sampling', { ...pointReceipt, sampling: undefined }],
    ['wrong support', { ...pointReceipt, sampling: { ...pointReceipt.sampling, support_kind: 'field_polygon' } }],
    ['wrong mode', { ...pointReceipt, sampling: { ...pointReceipt.sampling, mode: 'point_buffer' } }],
    ['unexpected radius', { ...pointReceipt, sampling: { ...pointReceipt.sampling, sample_radius_m: 60 } }],
    ['moved point', { ...pointReceipt, sampling: { ...pointReceipt.sampling, original_geometry: { type:'Point',coordinates:[-113.5,53.3] } } }],
    ['missing footprint', { ...pointReceipt, sampling: { ...pointReceipt.sampling, footprint: null } }],
    ['invented positional precision', { ...pointReceipt, sampling: { ...pointReceipt.sampling, positional_uncertainty_m: 0 } }],
    ['invalid pixel counts', { ...pointReceipt, sampling: { ...pointReceipt.sampling, valid_pixel_count: 2 } }],
    ['field area in point QA', { ...pointReceipt, qa: { ...pointReceipt.qa, field_area_m2:900 } }],
    ['missing sample area', { ...pointReceipt, qa: { ...pointReceipt.qa, sample_area_m2: undefined } }],
  ])('rejects point success with %s instead of showing polygon or invented results', async (_label, invalid) => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue(invalid)
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(await screen.findByText(/response did not confirm the requested sampling area/)).toBeInTheDocument()
    expect(screen.queryByText('0.530')).not.toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('preserves zero valid pixels and undefined indices without claiming valid zeros', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue({ ...pointReceipt, status:'empty_valid_area', sampling:{...pointReceipt.sampling,valid_pixel_count:0},
      qa:{...pointReceipt.qa,valid_area_m2:0,valid_area_fraction:0,nodata_area_m2:900},
      zonal_stats:{NDVI:{mean:null,min:null,max:null,area_m2:0},NDMI:{mean:null,min:null,max:null,area_m2:0}} })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    expect(await screen.findByText(/sampled pixel has no clear, valid observation/)).toBeInTheDocument()
    expect(screen.getByText(/0 of 1 sample pixels pass QA/)).toBeInTheDocument()
    expect(screen.getAllByText('Unknown')).toHaveLength(2)
    expect(screen.queryByText('0.000')).not.toBeInTheDocument()
  })

  it('discards pending point results when mode changes and resets to pixel on new saved geometry', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    let release!: (value: unknown) => void
    apiPost.mockReturnValue(new Promise(resolve => { release = resolve }))
    const view=render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    fireEvent.change(screen.getByLabelText('Sample'), { target: { value: 'point_buffer' } })
    await act(async () => { release(pointReceipt) })
    expect(screen.queryByRole('region', {name:'Imagery analysis result'})).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
    view.rerender(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="moved-point" geometry={{kind:'point',point:{lon:-113.5,lat:53.3}}} imageryReady={false} />)
    expect(screen.getByLabelText('Sample')).toHaveValue('point_pixel')
    expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeDisabled()
  })

  it.each(['Acquired through', 'HLS source'])('clears an existing point preview after changing %s', async (label) => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue(pointReceipt)
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Analyze scene' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Analyze scene' }))
    await screen.findByRole('img')
    fireEvent.change(screen.getByLabelText(label), { target: { value:label==='HLS source'?'hls-l30-planetary-computer':'2025-07-01' } })
    expect(screen.queryByRole('region', {name:'Imagery analysis result'})).not.toBeInTheDocument()
    expect(revokeUrl).toHaveBeenCalledWith('blob:field-preview')
  })


  it('rejects a buffered receipt for a different radius', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue(bufferReceipt)
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(() => expect(screen.getByRole('option',{name:'Area around location'})).toBeEnabled())
    fireEvent.change(screen.getByLabelText('Sample'),{target:{value:'point_buffer'}})
    fireEvent.change(screen.getByLabelText('Radius (m)'),{target:{value:'90'}})
    fireEvent.click(screen.getByRole('button',{name:'Analyze scene'}))
    expect(await screen.findByText(/response did not confirm the requested sampling area/)).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('keeps QA-valid but mathematically undefined pixel indices unknown', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue({...pointReceipt,zonal_stats:{NDVI:{mean:null,min:null,max:null,area_m2:0},NDMI:{mean:null,min:null,max:null,area_m2:0}}})
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(()=>expect(screen.getByRole('button',{name:'Analyze scene'})).toBeEnabled())
    fireEvent.click(screen.getByRole('button',{name:'Analyze scene'}))
    expect(await screen.findByText(/1 of 1 sample pixels pass QA/)).toBeInTheDocument()
    expect(screen.getAllByText('Unknown')).toHaveLength(2)
    expect(screen.queryByText('0.000')).not.toBeInTheDocument()
  })


  it.each([
    ['edge', [[-113.6,53.2999],[-113.5997,53.2999],[-113.5997,53.3002],[-113.6,53.3002],[-113.6,53.2999]]],
    ['vertex', [[-113.6,53.3],[-113.5997,53.3],[-113.5997,53.3003],[-113.6,53.3003],[-113.6,53.3]]],
  ])('accepts a saved point on a valid footprint %s', async (_name, ring) => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue({ ...pointReceipt, sampling:{...pointReceipt.sampling,footprint:{type:'Polygon',coordinates:[ring]}} })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(()=>expect(screen.getByRole('button',{name:'Analyze scene'})).toBeEnabled())
    fireEvent.click(screen.getByRole('button',{name:'Analyze scene'}))
    expect(await screen.findByText('Observed indices for the sampled pixel.')).toBeInTheDocument()
    expect(await screen.findByRole('img')).toHaveAttribute('src','blob:field-preview')
  })

  it('rejects buffer counts larger than the returned grid', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue({...bufferReceipt,grid:{...bufferReceipt.grid,width:2,height:2}})
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(()=>expect(screen.getByRole('option',{name:'Area around location'})).toBeEnabled())
    fireEvent.change(screen.getByLabelText('Sample'),{target:{value:'point_buffer'}})
    fireEvent.click(screen.getByRole('button',{name:'Analyze scene'}))
    expect(await screen.findByText(/response did not confirm the requested sampling area/)).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })


  describe.each(['NDVI', 'NDMI'] as const)('%s support and numerical consistency', (name) => {
    it.each([
      ['missing statistics', undefined],
      ['missing support', { mean:0.5, min:0.4, max:0.6 }],
      ['nonfinite support', { mean:0.5, min:0.4, max:0.6, area_m2:Infinity }],
      ['negative support', { mean:null, min:null, max:null, area_m2:-1 }],
      ['support exceeding QA-valid area', { mean:0.5, min:0.4, max:0.6, area_m2:901 }],
      ['zero support with finite mean', { mean:0, min:null, max:null, area_m2:0 }],
      ['zero support with finite extrema', { mean:null, min:0, max:0, area_m2:0 }],
      ['positive support with null mean', { mean:null, min:0.4, max:0.6, area_m2:900 }],
      ['nonfinite mean', { mean:NaN, min:0.4, max:0.6, area_m2:900 }],
      ['nonfinite maximum', { mean:0.5, min:0.4, max:Infinity, area_m2:900 }],
      ['mean below minimum', { mean:0.3, min:0.4, max:0.6, area_m2:900 }],
      ['mean above maximum', { mean:0.8, min:0.4, max:0.6, area_m2:900 }],
    ])('rejects %s before rendering indices or fetching the preview', async (_label, invalid) => {
      apiGet.mockResolvedValue(pointAvailability)
      apiPost.mockResolvedValue({...pointReceipt,zonal_stats:{...pointReceipt.zonal_stats,[name]:invalid}})
      render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
      open(); setDates()
      await waitFor(()=>expect(screen.getByRole('button',{name:'Analyze scene'})).toBeEnabled())
      fireEvent.click(screen.getByRole('button',{name:'Analyze scene'}))
      expect(await screen.findByText(/response did not confirm the requested sampling area/)).toBeInTheDocument()
      expect(screen.queryByText('0.530')).not.toBeInTheDocument()
      expect(screen.queryByRole('img')).not.toBeInTheDocument()
      expect(fetch).not.toHaveBeenCalled()
    })

    it('rejects an empty-valid-area result carrying a finite index', async () => {
      apiGet.mockResolvedValue(pointAvailability)
      const missing = {mean:null,min:null,max:null,area_m2:0}
      apiPost.mockResolvedValue({...pointReceipt,status:'empty_valid_area',
        sampling:{...pointReceipt.sampling,valid_pixel_count:0},
        qa:{...pointReceipt.qa,valid_area_m2:0,valid_area_fraction:0},
        zonal_stats:{NDVI:missing,NDMI:missing,[name]:{mean:0.7,min:0.7,max:0.7,area_m2:900}},
      })
      render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
      open(); setDates()
      await waitFor(()=>expect(screen.getByRole('button',{name:'Analyze scene'})).toBeEnabled())
      fireEvent.click(screen.getByRole('button',{name:'Analyze scene'}))
      expect(await screen.findByText(/response did not confirm the requested sampling area/)).toBeInTheDocument()
      expect(screen.queryByText('0.700')).not.toBeInTheDocument()
      expect(fetch).not.toHaveBeenCalled()
    })

    it('keeps finite ordered ratios outside minus-one to one without clamping', async () => {
      apiGet.mockResolvedValue(pointAvailability)
      apiPost.mockResolvedValue({...pointReceipt,zonal_stats:{...pointReceipt.zonal_stats,[name]:{mean:2.4,min:2.4,max:2.4,area_m2:900}}})
      render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
      open(); setDates()
      await waitFor(()=>expect(screen.getByRole('button',{name:'Analyze scene'})).toBeEnabled())
      fireEvent.click(screen.getByRole('button',{name:'Analyze scene'}))
      expect(await screen.findByText('2.400')).toBeInTheDocument()
      expect(await screen.findByRole('img')).toHaveAttribute('src','blob:field-preview')
    })
  })


  it('rejects a buffer radius that contradicts its total sample area', async () => {
    apiGet.mockResolvedValue(pointAvailability)
    apiPost.mockResolvedValue({...pointReceipt,
      sampling:{...pointReceipt.sampling,mode:'point_buffer',support_kind:'point_buffer',sample_radius_m:1500},
    })
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(()=>expect(screen.getByRole('option',{name:'Area around location'})).toBeEnabled())
    fireEvent.change(screen.getByLabelText('Sample'),{target:{value:'point_buffer'}})
    fireEvent.change(screen.getByLabelText('Radius (m)'),{target:{value:'1500'}})
    fireEvent.click(screen.getByRole('button',{name:'Analyze scene'}))
    expect(await screen.findByText(/response did not confirm the requested sampling area/)).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })


  it.each([0.714285671710968, 0.7142857909202576])('accepts observed float32 buffer mean %s without changing the receipt', async (mean) => {
    apiGet.mockResolvedValue(pointAvailability)
    const observed = {...bufferReceipt, zonal_stats:{...bufferReceipt.zonal_stats,
      NDMI:{mean,min:0.7142857313156128,max:0.7142857313156128,area_m2:8000},
    }}
    apiPost.mockResolvedValue(observed)
    render(<FieldImageryAnalyticsPanel fieldContextId="field-1" geometryKey="point-1" geometry={point} imageryReady />)
    open(); setDates()
    await waitFor(()=>expect(screen.getByRole('option',{name:'Area around location'})).toBeEnabled())
    fireEvent.change(screen.getByLabelText('Sample'),{target:{value:'point_buffer'}})
    fireEvent.click(screen.getByRole('button',{name:'Analyze scene'}))
    expect(await screen.findByText('Observed indices for the sampling area.')).toBeInTheDocument()
    expect(screen.getByText('0.714')).toBeInTheDocument()
    expect(await screen.findByRole('img')).toHaveAttribute('src','blob:field-preview')
    expect(observed.zonal_stats.NDMI).toEqual({mean,min:0.7142857313156128,max:0.7142857313156128,area_m2:8000})
  })

})
