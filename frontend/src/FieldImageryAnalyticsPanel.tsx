import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { apiGet, apiPost, csrfHeaders } from './api'
import type { FieldGeometry } from './fieldGeometry'
import './FieldImageryAnalyticsPanel.css'

type SamplingMode = 'field_polygon' | 'point_pixel' | 'point_buffer'
type AnalyticsAvailability = {
  status: 'ready' | 'not_configured'; network_mode: string
  sampling_modes?: SamplingMode[]; sample_radius_bounds_m?: { min: number; max: number }
}
type PointSampling = {
  schema_version: 'imagery_sampling.v1'; mode: 'point_pixel' | 'point_buffer'
  support_kind: 'native_pixel' | 'point_buffer'
  original_geometry: { type: 'Point'; coordinates: [number, number] }
  footprint: { type: 'Polygon'; coordinates: number[][][] }; footprint_crs: 'EPSG:4326'
  sample_radius_m: number | null; native_resolution_m: number
  pixel_count: number; valid_pixel_count: number; positional_uncertainty_m: null
  point_role: 'unspecified'; area_basis: 'native_grid_projected_metres'
  edge_policy: 'containing_pixel_floor'; limitation: string
}
type IndexStats = { mean?: number | null; min?: number | null; max?: number | null; area_m2?: number | null }
type AnalyticsReceipt = {
  status: 'available' | 'empty_valid_area' | 'empty_field_mask' | 'blocked_offline' | 'no_scene' | 'unavailable' | 'not_configured' | 'busy' | 'storage_limit' | 'storage_unavailable'
  provider_id?: string
  scene_id?: string | null
  source?: {
    provider_id?: string; collection?: string; scene_id?: string; acquired_at?: string
    availability_at?: string | null; scene_cloud_percent?: number | null
    asset_ids?: Record<string, string>; band_metadata?: Record<string, unknown>
  }
  qa?: {
    field_area_m2?: number | null; sample_area_m2?: number | null; valid_area_m2?: number | null; valid_area_fraction?: number | null
    excluded_area_m2_by_reason?: Record<string, number>; nodata_area_m2?: number | null; overlap_note?: string
  }
  sampling?: PointSampling
  zonal_stats?: { NDVI?: IndexStats; NDMI?: IndexStats }
  grid?: { crs?: string; width?: number; height?: number; resolution_m?: number; resampling_method?: string }
  chip_hash?: string; geometry_hash?: string; process_version?: string
  elapsed_seconds?: number | null; cog_transfer_bytes?: number | null; cache_hit?: boolean
  preview_url?: string | null; message?: string; reason?: string
}

const providers = [
  { id: 'hls-s30-planetary-computer', label: 'HLS Sentinel-2 (S30)' },
  { id: 'hls-l30-planetary-computer', label: 'HLS Landsat (L30)' },
] as const

function decimal(value: number | null | undefined, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'Unknown'
}

function area(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value).toLocaleString()} m²` : 'Unknown'
}

function errorText(cause: unknown): string {
  const text = cause instanceof Error ? cause.message : String(cause)
  const match = text.match(/^\d+:\s*(.*)$/s)
  if (!match) return text
  try {
    const parsed = JSON.parse(match[1]) as { detail?: string | { message?: string } }
    return typeof parsed.detail === 'string' ? parsed.detail : parsed.detail?.message || text
  } catch { return text }
}

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const nonnegative = (value: unknown): value is number => finite(value) && value >= 0
const coordinate = (value: unknown): value is [number, number] => Array.isArray(value) && value.length === 2
  && finite(value[0]) && finite(value[1]) && Math.abs(value[0]) <= 180 && Math.abs(value[1]) <= 90

/** Linear, bounded point-in-polygon check; edges count as covered, hole interiors do not. */
function footprintCoversPoint(footprint: PointSampling['footprint'], point: [number, number]): boolean {
  if (footprint?.type !== 'Polygon' || !Array.isArray(footprint.coordinates)
    || !footprint.coordinates.length || footprint.coordinates.length > 64) return false
  let positions = 0
  const locations: Array<'inside' | 'outside' | 'edge'> = []
  for (const ring of footprint.coordinates) {
    if (!Array.isArray(ring) || ring.length < 4 || (positions += ring.length) > 1024
      || !ring.every(coordinate) || ring[0][0] !== ring[ring.length - 1][0] || ring[0][1] !== ring[ring.length - 1][1]) return false
    // Unwrap around the saved longitude, so a small sample crossing ±180° stays local.
    const local = ring.map(([lon, lat]) => [((lon - point[0] + 540) % 360) - 180, lat - point[1]])
    let inside = false
    let edge = false
    let twiceArea = 0
    for (let i = 0; i < local.length - 1; i += 1) {
      const [ax, ay] = local[i], [bx, by] = local[i + 1]
      const dx = bx - ax, dy = by - ay, lengthSquared = dx * dx + dy * dy
      const t = lengthSquared ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / lengthSquared)) : 0
      if ((ax + t * dx) ** 2 + (ay + t * dy) ** 2 <= 1e-18) edge = true
      if ((ay > 0) !== (by > 0) && ax - ay * dx / dy > 0) inside = !inside
      twiceArea += ax * by - bx * ay
    }
    if (Math.abs(twiceArea) < 1e-18) return false
    locations.push(edge ? 'edge' : inside ? 'inside' : 'outside')
  }
  return locations[0] !== 'outside' && !locations.slice(1).includes('inside')
}

function validIndexStats(stats: IndexStats | undefined, qaArea: number): boolean {
  if (!stats || !nonnegative(stats.area_m2) || stats.area_m2 > qaArea) return false
  if (stats.area_m2 === 0) return stats.mean === null && stats.min === null && stats.max === null
  if (!finite(stats.mean) || !finite(stats.min) || !finite(stats.max)) return false
  // Native float32 weighted sums can drift just outside the observed extrema.
  const tolerance = 1e-6 * Math.max(1, Math.abs(stats.min), Math.abs(stats.mean), Math.abs(stats.max))
  return stats.min <= stats.mean + tolerance && stats.mean <= stats.max + tolerance
}

/** A point result cannot inherit the legacy polygon interpretation. */
function validPointReceipt(receipt: AnalyticsReceipt, geometry: FieldGeometry, mode: SamplingMode, radius: number): boolean {
  const sample = receipt.sampling
  const qa = receipt.qa
  const grid = receipt.grid
  const areaTolerance = 1e-3
  if (geometry.kind !== 'point' || !sample || !qa || !grid || typeof qa !== 'object' || Array.isArray(qa) || sample.schema_version !== 'imagery_sampling.v1'
    || sample.mode !== mode || sample.support_kind !== (mode === 'point_pixel' ? 'native_pixel' : 'point_buffer')
    || sample.sample_radius_m !== (mode === 'point_buffer' ? radius : null)
    || sample.native_resolution_m !== 30 || sample.footprint_crs !== 'EPSG:4326'
    || sample.point_role !== 'unspecified' || sample.positional_uncertainty_m !== null
    || sample.area_basis !== 'native_grid_projected_metres' || sample.edge_policy !== 'containing_pixel_floor'
    || typeof sample.limitation !== 'string' || !sample.limitation.trim()
    || sample.original_geometry?.type !== 'Point' || !coordinate(sample.original_geometry.coordinates)
    || sample.original_geometry.coordinates[0] !== geometry.point.lon || sample.original_geometry.coordinates[1] !== geometry.point.lat
    || !footprintCoversPoint(sample.footprint, sample.original_geometry.coordinates)
    || !Number.isSafeInteger(grid.width) || !Number.isSafeInteger(grid.height)
    || !finite(grid.width) || !finite(grid.height) || grid.width < 1 || grid.height < 1 || grid.width > 256 || grid.height > 256
    || grid.resolution_m !== 30
    || !Number.isSafeInteger(sample.pixel_count) || sample.pixel_count < 1
    || !Number.isSafeInteger(sample.valid_pixel_count) || sample.valid_pixel_count < 0 || sample.valid_pixel_count > sample.pixel_count
    || sample.pixel_count > grid.width * grid.height
    || (mode === 'point_pixel' && (sample.pixel_count !== 1 || grid.width !== 1 || grid.height !== 1))
    || 'field_area_m2' in qa || !nonnegative(qa.sample_area_m2) || qa.sample_area_m2 <= 0
    || qa.sample_area_m2 > sample.pixel_count * 900 + areaTolerance
    || (mode === 'point_pixel' && Math.abs(qa.sample_area_m2 - 900) > areaTolerance)
    || (mode === 'point_buffer' && Math.abs(qa.sample_area_m2 - Math.PI * radius ** 2) > Math.max(areaTolerance, Math.PI * radius ** 2 * 2e-4))
    || !nonnegative(qa.valid_area_m2) || qa.valid_area_m2 > qa.sample_area_m2
    || qa.valid_area_m2 > sample.valid_pixel_count * 900 + areaTolerance
    || (mode === 'point_pixel' && Math.abs(qa.valid_area_m2 - sample.valid_pixel_count * 900) > areaTolerance)
    || (receipt.status === 'empty_valid_area' && (sample.valid_pixel_count !== 0 || qa.valid_area_m2 !== 0))
    || (receipt.status === 'available' && (sample.valid_pixel_count < 1 || qa.valid_area_m2 <= 0))
    || (sample.valid_pixel_count === 0) !== (qa.valid_area_m2 === 0)
    || (qa.valid_area_fraction !== null && finite(qa.valid_area_fraction) && Math.abs(qa.valid_area_fraction - qa.valid_area_m2 / qa.sample_area_m2) > 1e-6)
    || !nonnegative(qa.nodata_area_m2) || qa.nodata_area_m2 > qa.sample_area_m2
    || !(qa.valid_area_fraction === null || (nonnegative(qa.valid_area_fraction) && qa.valid_area_fraction <= 1))
    || !qa.excluded_area_m2_by_reason || typeof qa.excluded_area_m2_by_reason !== 'object' || Array.isArray(qa.excluded_area_m2_by_reason)
    || !Object.values(qa.excluded_area_m2_by_reason).every(nonnegative) || typeof qa.overlap_note !== 'string') return false
  return validIndexStats(receipt.zonal_stats?.NDVI, qa.valid_area_m2)
    && validIndexStats(receipt.zonal_stats?.NDMI, qa.valid_area_m2)
}

function statusText(receipt: AnalyticsReceipt, mode: SamplingMode): string {
  if (receipt.status === 'available') return mode === 'point_pixel' ? 'Observed indices for the sampled pixel.'
    : mode === 'point_buffer' ? 'Observed indices for the sampling area.' : 'Observed indices for the saved field polygon.'
  if (receipt.status === 'empty_valid_area') return mode === 'point_pixel' ? 'The sampled pixel has no clear, valid observation after QA. Index values are unavailable.'
    : 'No clear, valid area remains after QA. Index values are unavailable.'
  if (receipt.status === 'empty_field_mask') return mode === 'field_polygon' ? 'The field polygon does not cover a usable pixel in this scene.' : 'No usable pixels intersect this sample in the scene.'
  if (receipt.status === 'blocked_offline') return 'Network access is off and no matching cached analysis is available.'
  if (receipt.status === 'no_scene') return 'No matching HLS scene was found in this date window.'
  if (receipt.status === 'not_configured') return 'Optional imagery processing is not configured in this runtime.'
  if (receipt.status === 'busy') return 'Imagery processing is busy. Try again shortly.'
  if (receipt.status === 'storage_limit') return 'The imagery storage limit or free-disk reserve has been reached. Existing cached analyses remain available. Review local storage settings before requesting more imagery.'
  if (receipt.status === 'storage_unavailable') return 'The local imagery cache could not be verified or opened. No new imagery was fetched.'
  return receipt.message || receipt.reason || 'This scene could not be processed. No index value is available.'
}

function IndexValue({ name, stats, singlePixel = false }: { name: 'NDVI' | 'NDMI'; stats?: IndexStats; singlePixel?: boolean }) {
  return <div className="field-imagery-index">
    <strong>{name}</strong>
    <span className="field-imagery-index-value">{decimal(stats?.mean)}</span>
    <small>{singlePixel ? 'Sampled pixel' : `Observed mean · range ${decimal(stats?.min)} to ${decimal(stats?.max)}`} · valid area {area(stats?.area_m2)}</small>
  </div>
}

export function FieldImageryAnalyticsPanel({ fieldContextId, geometryKey, geometry, imageryReady }: {
  fieldContextId: string
  geometryKey: string
  geometry: FieldGeometry
  imageryReady: boolean
}) {
  const [availability, setAvailability] = useState<AnalyticsAvailability | null>(null)
  const [availabilityError, setAvailabilityError] = useState('')
  const [providerId, setProviderId] = useState<(typeof providers)[number]['id']>(providers[0].id)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const radiusHelpId = useId()
  const [pointMode, setPointMode] = useState<'point_pixel' | 'point_buffer'>('point_pixel')
  const [radius, setRadius] = useState('')
  const point = geometry.kind === 'point'
  const mode: SamplingMode = point ? pointMode : 'field_polygon'
  const modeSupported = !point || availability?.sampling_modes?.includes(mode) === true
  const radiusBounds = availability?.sample_radius_bounds_m
  const radiusValid = mode !== 'point_buffer' || (radius.trim() !== '' && Number.isInteger(Number(radius))
    && Number(radius) >= Math.max(15, radiusBounds?.min ?? 15) && Number(radius) <= Math.min(1500, radiusBounds?.max ?? 1500))
  const canAnalyze = imageryReady && geometry.kind !== 'none' && availability?.status === 'ready' && modeSupported && radiusValid
    && (mode !== 'point_buffer' || (radiusBounds?.min === 15 && radiusBounds?.max === 1500))
  const [receipt, setReceipt] = useState<AnalyticsReceipt | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewState, setPreviewState] = useState('')
  const [busy, setBusy] = useState(false)
  const requestRef = useRef(0)
  const previewAbortRef = useRef<AbortController | null>(null)
  const objectUrlRef = useRef('')

  const clearPreview = (resetState = true) => {
    previewAbortRef.current?.abort()
    previewAbortRef.current = null
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
    objectUrlRef.current = ''
    if (resetState) { setPreviewUrl(''); setPreviewState('') }
  }

  useEffect(() => {
    let active = true
    setAvailability(null)
    setAvailabilityError('')
    void apiGet<AnalyticsAvailability>(`/api/demo/fields/${encodeURIComponent(fieldContextId)}/imagery/analytics`)
      .then((result) => { if (active) setAvailability(result) })
      .catch((cause) => { if (active) setAvailabilityError(`Imagery availability could not be checked: ${errorText(cause)}`) })
    return () => { active = false }
  }, [fieldContextId])

  useEffect(() => { setPointMode('point_pixel'); setRadius('') }, [fieldContextId, geometryKey, geometry.kind])

  useEffect(() => {
    requestRef.current += 1
    clearPreview()
    setReceipt(null)
    setBusy(false)
    return () => { requestRef.current += 1; clearPreview(false) }
  }, [fieldContextId, geometryKey, geometry.kind, imageryReady, mode, radius, providerId, startDate, endDate])

  const loadPreview = async (result: AnalyticsReceipt, requestId: number) => {
    if (!result.preview_url || !result.chip_hash || !/^[0-9a-f]{64}$/.test(result.chip_hash)) return
    const expected = `/api/demo/fields/${encodeURIComponent(fieldContextId)}/imagery/analyses/${result.chip_hash}/preview.png`
    if (result.preview_url !== expected) { setPreviewState('Preview address did not match this field analysis.'); return }
    const controller = new AbortController()
    previewAbortRef.current = controller
    setPreviewState('Loading authenticated preview…')
    try {
      const response = await fetch(expected, { headers: csrfHeaders(), credentials: 'same-origin', signal: controller.signal })
      if (!response.ok) throw new Error(`Preview request failed (${response.status}).`)
      if (!response.headers.get('content-type')?.startsWith('image/png')) throw new Error('Preview response was not PNG.')
      const blob = await response.blob()
      if (!blob.size || blob.size > 2 * 1024 * 1024) throw new Error('Preview size is invalid.')
      if (requestId !== requestRef.current) return
      const objectUrl = URL.createObjectURL(blob)
      objectUrlRef.current = objectUrl
      setPreviewUrl(objectUrl)
      setPreviewState('')
    } catch (cause) {
      if (requestId === requestRef.current && !controller.signal.aborted) setPreviewState(errorText(cause))
    } finally {
      if (previewAbortRef.current === controller) previewAbortRef.current = null
    }
  }

  const analyze = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canAnalyze || !startDate || !endDate || endDate < startDate || busy) return
    const requestId = ++requestRef.current
    clearPreview()
    setReceipt(null)
    setBusy(true)
    try {
      const result = await apiPost<AnalyticsReceipt>(`/api/demo/fields/${encodeURIComponent(fieldContextId)}/imagery/analyze`, {
        provider_id: providerId, start_date: startDate, end_date: endDate, buffer_m: 0,
        ...(point ? { sampling_mode: mode, ...(mode === 'point_buffer' ? { sample_radius_m: Number(radius) } : {}) } : {}),
      })
      if (requestId !== requestRef.current) return
      if ((result.status === 'available' || result.status === 'empty_valid_area')
        && (point ? !validPointReceipt(result, geometry, mode, Number(radius)) : result.sampling && (result.sampling as { mode: string }).mode !== 'field_polygon')) {
        setReceipt({ status: 'unavailable', message: 'The response did not confirm the requested sampling area. No indices or preview are shown. Try again.' })
        return
      }
      setReceipt(result)
      if (result.status === 'available' || result.status === 'empty_valid_area') void loadPreview(result, requestId)
    } catch (cause) {
      if (requestId === requestRef.current) setReceipt({ status: 'unavailable', message: errorText(cause) })
    } finally {
      if (requestId === requestRef.current) setBusy(false)
    }
  }

  const resultMode = receipt?.sampling?.mode || mode
  const resultPoint = resultMode !== 'field_polygon'
  const pointSampling = resultPoint ? receipt?.sampling : undefined
  const previewSupport = resultMode === 'point_pixel' ? 'sampled pixel' : resultMode === 'point_buffer' ? 'sampling area' : 'saved field polygon'
  const resolution = receipt?.sampling?.native_resolution_m || 30
  const transparency = resultPoint ? 'outside the sample, excluded by QA, or undefined index' : 'outside field, excluded by QA, or undefined index'

  return <details className="workspace-disclosure field-imagery-analytics">
    <summary>Observed satellite indices</summary>
    <p>{point ? 'Inspect one HLS scene at the saved location. A pixel or surrounding sample can include other land covers.' : 'Analyze one HLS scene over a saved field polygon.'} NDVI and NDMI are observations, not yield or diagnosis.</p>
    {!imageryReady || geometry.kind === 'none' ? <p role="status">{geometry.kind === 'none' ? 'Add and save a location or boundary before analyzing imagery.' : 'Save the current location or boundary before analyzing imagery.'}</p> : null}
    {point && availability && !modeSupported ? <p role="status">Point sampling is not supported by this runtime.</p> : null}
    {availabilityError ? <p role="alert">{availabilityError}</p> : null}
    {availability?.status === 'not_configured' ? <p role="status">Optional imagery processing is not installed in this runtime.</p> : null}
    {availability?.network_mode === 'online' ? <p>{point ? 'Online analysis sends the saved location and selected dates to Microsoft Planetary Computer to find scenes, then requests imagery covering the sample.' : 'Online analysis sends the saved field polygon and selected dates to Microsoft Planetary Computer to locate public HLS imagery.'} No account is required.</p> : null}
    {availability?.network_mode === 'offline' ? <p role="status">Network access is off. An exact cached analysis may still be available.</p> : null}
    <form onSubmit={(event) => void analyze(event)}>
      {point ? <div className="field-imagery-sampling"><label>Sample<select value={pointMode} onChange={event => {
        const next = event.target.value as 'point_pixel' | 'point_buffer'
        setPointMode(next)
        if (next === 'point_buffer' && !radius) setRadius('60')
      }}><option value="point_pixel">Pixel at location</option><option value="point_buffer" disabled={!availability?.sampling_modes?.includes('point_buffer')}>Area around location</option></select></label>
      {mode === 'point_buffer' ? <label>Radius (m)<input aria-label="Radius (m)" aria-describedby={radiusHelpId} type="number" min="15" max="1500" step="1" value={radius} onChange={event => setRadius(event.target.value)} required /><small id={radiusHelpId}>15–1,500 m · sampling area, not field size</small></label> : null}</div> : null}
      <label>HLS source<select value={providerId} onChange={(event) => setProviderId(event.target.value as typeof providerId)}>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></label>
      <div className="field-imagery-dates">
        <label>Acquired from<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required /></label>
        <label>Acquired through<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} required /></label>
      </div>
      <button type="submit" disabled={!canAnalyze || !startDate || !endDate || endDate < startDate || busy}>{busy ? 'Analyzing…' : 'Analyze scene'}</button>
    </form>
    {receipt ? <section className="field-imagery-result" aria-label="Imagery analysis result">
      <p role="status">{statusText(receipt, resultMode)}</p>
      {receipt.source ? <div className="field-imagery-source">
        <strong>{receipt.source.collection || receipt.source.provider_id || 'HLS scene'}</strong>
        <span>Scene {receipt.source.scene_id || receipt.scene_id || 'unknown'} · acquired {receipt.source.acquired_at || 'unknown'}</span>
        <span>Scene cloud {receipt.source.scene_cloud_percent == null ? 'unknown' : `${decimal(receipt.source.scene_cloud_percent, 1)}%`} · {resultPoint ? 'valid sample fraction' : 'field clear coverage'} {receipt.qa?.valid_area_fraction == null ? 'unknown' : `${(receipt.qa.valid_area_fraction * 100).toFixed(1)}%`}</span>
      </div> : null}
      {receipt.qa ? <div className="field-imagery-qa">
        <span>{resultPoint ? `Sample area ${area(receipt.qa.sample_area_m2)}` : `Field area ${area(receipt.qa.field_area_m2)}`}</span><span>{resultPoint ? 'Clear sample area' : 'Valid observed area'} {area(receipt.qa.valid_area_m2)}</span>
        {pointSampling ? <span>{pointSampling.valid_pixel_count} of {pointSampling.pixel_count} sample pixels pass QA · {pointSampling.native_resolution_m} m source pixels</span> : null}
        <span>Nodata area {area(receipt.qa.nodata_area_m2)}</span>
        {receipt.qa.excluded_area_m2_by_reason ? <details><summary>QA exclusions</summary><ul>{Object.entries(receipt.qa.excluded_area_m2_by_reason).map(([reason, value]) => <li key={reason}>{reason.replace(/_/g, ' ')}: {area(value)}</li>)}</ul><small>{receipt.qa.overlap_note || 'QA reasons may overlap.'}</small></details> : null}
      </div> : null}
      {pointSampling ? <p className="field-imagery-sampling-note">{pointSampling.limitation}</p> : null}
      {receipt.zonal_stats ? <div className="field-imagery-indices"><IndexValue name="NDVI" stats={receipt.zonal_stats.NDVI} singlePixel={resultMode === 'point_pixel'} /><IndexValue name="NDMI" stats={receipt.zonal_stats.NDMI} singlePixel={resultMode === 'point_pixel'} /></div> : null}
      {previewUrl ? <figure><img src={previewUrl} alt={`Observed NDVI in the ${previewSupport}; transparent pixels are ${transparency}`} />
        <figcaption>{resultPoint ? `NDVI ${previewSupport} preview` : 'Field-only NDVI display preview'}, enlarged for inspection from {resolution} m source pixels. {resultPoint ? 'The sample may include neighboring land cover. ' : ''}Transparent pixels are {transparency}. Numerical results come from the server receipt.</figcaption>
        <div className="field-imagery-legend" aria-label="NDVI preview color scale">
          <div className="field-imagery-legend-ramp" aria-hidden="true" />
          <div className="field-imagery-legend-labels"><span>−1</span><span>0</span><span>+1</span></div>
          <span className="field-imagery-legend-missing"><i aria-hidden="true" />Transparent: {transparency}</span>
        </div>
      </figure> : null}
      {previewState ? <p role="status">{previewState}</p> : null}
      {receipt.source ? <details className="field-imagery-provenance"><summary>Source and processing details</summary>
        <dl>
          {pointSampling ? <><div><dt>Sample</dt><dd>{pointSampling.mode === 'point_pixel' ? 'Containing native pixel' : `${pointSampling.sample_radius_m} m radius around location`} · {pointSampling.support_kind.replace(/_/g, ' ')}</dd></div>
          <div><dt>Saved point</dt><dd>{pointSampling.original_geometry.coordinates[1]}, {pointSampling.original_geometry.coordinates[0]}</dd></div>
          <div><dt>Position accuracy</dt><dd>Unknown · location role unspecified</dd></div></> : null}
          <div><dt>Provider</dt><dd>{receipt.source.provider_id || receipt.provider_id || 'unknown'}</dd></div>
          <div><dt>Published</dt><dd>{receipt.source.availability_at || 'unknown'}</dd></div>
          <div><dt>Grid</dt><dd>{receipt.grid?.crs || 'unknown'} · {receipt.grid?.width ?? '?'} × {receipt.grid?.height ?? '?'} pixels · {receipt.grid?.resampling_method || 'method unknown'}</dd></div>
        </dl>
        {receipt.source.asset_ids ? <ul>{Object.entries(receipt.source.asset_ids).map(([band, id]) => <li key={band}>{band}: {id}</li>)}</ul> : null}
      </details> : null}
      {receipt.chip_hash ? <small>Chip {receipt.chip_hash.slice(0, 12)} · geometry {receipt.geometry_hash?.slice(0, 12) || 'unknown'} · {receipt.process_version || 'version unknown'}{receipt.cache_hit ? ' · cached' : ''}</small> : null}
      {receipt.elapsed_seconds != null ? <small>Processing {decimal(receipt.elapsed_seconds, 1)} s · COG transfer {receipt.cog_transfer_bytes == null ? 'unknown' : `${Math.round(receipt.cog_transfer_bytes).toLocaleString()} bytes`}</small> : null}
    </section> : null}
  </details>
}

export default FieldImageryAnalyticsPanel
