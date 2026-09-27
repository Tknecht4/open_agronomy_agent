import { useEffect, useRef, useState, type FormEvent } from 'react'
import { apiGet, apiPost, csrfHeaders } from './api'
import './FieldImageryAnalyticsPanel.css'

type AnalyticsAvailability = { status: 'ready' | 'not_configured'; network_mode: string }
type IndexStats = { mean?: number | null; min?: number | null; max?: number | null; area_m2?: number | null }
type AnalyticsReceipt = {
  status: 'available' | 'empty_valid_area' | 'empty_field_mask' | 'blocked_offline' | 'no_scene' | 'unavailable' | 'not_configured' | 'busy'
  provider_id?: string
  scene_id?: string | null
  source?: {
    provider_id?: string; collection?: string; scene_id?: string; acquired_at?: string
    availability_at?: string | null; scene_cloud_percent?: number | null
    asset_ids?: Record<string, string>; band_metadata?: Record<string, unknown>
  }
  qa?: {
    field_area_m2?: number | null; valid_area_m2?: number | null; valid_area_fraction?: number | null
    excluded_area_m2_by_reason?: Record<string, number>; nodata_area_m2?: number | null; overlap_note?: string
  }
  zonal_stats?: { NDVI?: IndexStats; NDMI?: IndexStats }
  grid?: { crs?: string; width?: number; height?: number; resampling_method?: string }
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

function statusText(receipt: AnalyticsReceipt): string {
  if (receipt.status === 'available') return 'Observed indices for the saved field polygon.'
  if (receipt.status === 'empty_valid_area') return 'No clear, valid area remains after QA. Index values are unavailable.'
  if (receipt.status === 'empty_field_mask') return 'The field polygon does not cover a usable pixel in this scene.'
  if (receipt.status === 'blocked_offline') return 'Network access is off and no matching cached analysis is available.'
  if (receipt.status === 'no_scene') return 'No matching HLS scene was found in this date window.'
  if (receipt.status === 'not_configured') return 'Optional imagery processing is not configured in this runtime.'
  if (receipt.status === 'busy') return 'Imagery processing is busy. Try again shortly.'
  return receipt.message || receipt.reason || 'This scene could not be processed. No index value is available.'
}

function IndexValue({ name, stats }: { name: 'NDVI' | 'NDMI'; stats?: IndexStats }) {
  return <div className="field-imagery-index">
    <strong>{name}</strong>
    <span className="field-imagery-index-value">{decimal(stats?.mean)}</span>
    <small>Observed mean · range {decimal(stats?.min)} to {decimal(stats?.max)} · valid area {area(stats?.area_m2)}</small>
  </div>
}

export function FieldImageryAnalyticsPanel({ fieldContextId, geometryKey, imageryReady }: {
  fieldContextId: string
  geometryKey: string
  imageryReady: boolean
}) {
  const [availability, setAvailability] = useState<AnalyticsAvailability | null>(null)
  const [availabilityError, setAvailabilityError] = useState('')
  const [providerId, setProviderId] = useState<(typeof providers)[number]['id']>(providers[0].id)
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
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

  useEffect(() => {
    requestRef.current += 1
    clearPreview()
    setReceipt(null)
    setBusy(false)
    return () => { requestRef.current += 1; clearPreview(false) }
  }, [fieldContextId, geometryKey, imageryReady])

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
    if (!imageryReady || availability?.status !== 'ready' || !startDate || !endDate || endDate < startDate || busy) return
    const requestId = ++requestRef.current
    clearPreview()
    setReceipt(null)
    setBusy(true)
    try {
      const result = await apiPost<AnalyticsReceipt>(`/api/demo/fields/${encodeURIComponent(fieldContextId)}/imagery/analyze`, {
        provider_id: providerId, start_date: startDate, end_date: endDate, buffer_m: 0,
      })
      if (requestId !== requestRef.current) return
      setReceipt(result)
      if (result.status === 'available' || result.status === 'empty_valid_area') void loadPreview(result, requestId)
    } catch (cause) {
      if (requestId === requestRef.current) setReceipt({ status: 'unavailable', message: errorText(cause) })
    } finally {
      if (requestId === requestRef.current) setBusy(false)
    }
  }

  return <details className="workspace-disclosure field-imagery-analytics">
    <summary>Observed satellite indices</summary>
    <p>Analyze one HLS scene over a saved field polygon. NDVI and NDMI are spectral observations, not yield, stress, or treatment predictions.</p>
    {!imageryReady ? <p role="status">Save a valid field polygon before analyzing imagery. A point or unknown location is insufficient.</p> : null}
    {availabilityError ? <p role="alert">{availabilityError}</p> : null}
    {availability?.status === 'not_configured' ? <p role="status">Optional imagery processing is not installed in this runtime.</p> : null}
    {availability?.network_mode === 'online' ? <p>Online analysis sends the saved field polygon and selected dates to Microsoft Planetary Computer to locate public HLS imagery. No account is required.</p> : null}
    {availability?.network_mode === 'offline' ? <p role="status">Network access is off. An exact cached analysis may still be available.</p> : null}
    <form onSubmit={(event) => void analyze(event)}>
      <label>HLS source<select value={providerId} onChange={(event) => setProviderId(event.target.value as typeof providerId)}>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></label>
      <div className="field-imagery-dates">
        <label>Acquired from<input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} required /></label>
        <label>Acquired through<input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} required /></label>
      </div>
      <button type="submit" disabled={!imageryReady || availability?.status !== 'ready' || !startDate || !endDate || endDate < startDate || busy}>{busy ? 'Analyzing…' : 'Analyze scene'}</button>
    </form>
    {receipt ? <section className="field-imagery-result" aria-label="Imagery analysis result">
      <p role="status">{statusText(receipt)}</p>
      {receipt.source ? <div className="field-imagery-source">
        <strong>{receipt.source.collection || receipt.source.provider_id || 'HLS scene'}</strong>
        <span>Scene {receipt.source.scene_id || receipt.scene_id || 'unknown'} · acquired {receipt.source.acquired_at || 'unknown'}</span>
        <span>Scene cloud {receipt.source.scene_cloud_percent == null ? 'unknown' : `${decimal(receipt.source.scene_cloud_percent, 1)}%`} · field clear coverage {receipt.qa?.valid_area_fraction == null ? 'unknown' : `${(receipt.qa.valid_area_fraction * 100).toFixed(1)}%`}</span>
      </div> : null}
      {receipt.qa ? <div className="field-imagery-qa">
        <span>Field area {area(receipt.qa.field_area_m2)}</span><span>Valid observed area {area(receipt.qa.valid_area_m2)}</span>
        <span>Nodata area {area(receipt.qa.nodata_area_m2)}</span>
        {receipt.qa.excluded_area_m2_by_reason ? <details><summary>QA exclusions</summary><ul>{Object.entries(receipt.qa.excluded_area_m2_by_reason).map(([reason, value]) => <li key={reason}>{reason.replace(/_/g, ' ')}: {area(value)}</li>)}</ul><small>{receipt.qa.overlap_note || 'QA reasons may overlap.'}</small></details> : null}
      </div> : null}
      {receipt.zonal_stats ? <div className="field-imagery-indices"><IndexValue name="NDVI" stats={receipt.zonal_stats.NDVI} /><IndexValue name="NDMI" stats={receipt.zonal_stats.NDMI} /></div> : null}
      {previewUrl ? <figure><img src={previewUrl} alt="Observed NDVI within the saved field polygon; transparent pixels are outside the field, excluded by QA, or have an undefined index" />
        <figcaption>Field-only NDVI display preview, enlarged for inspection from 30 m source pixels. Transparent pixels are outside the field, excluded by QA, or have an undefined index. Numerical results come from the server receipt.</figcaption>
        <div className="field-imagery-legend" aria-label="NDVI preview color scale">
          <div className="field-imagery-legend-ramp" aria-hidden="true" />
          <div className="field-imagery-legend-labels"><span>−1</span><span>0</span><span>+1</span></div>
          <span className="field-imagery-legend-missing"><i aria-hidden="true" />Transparent: outside field, excluded by QA, or undefined index</span>
        </div>
      </figure> : null}
      {previewState ? <p role="status">{previewState}</p> : null}
      {receipt.source ? <details className="field-imagery-provenance"><summary>Source and processing details</summary>
        <dl>
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
