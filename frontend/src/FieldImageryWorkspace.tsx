import { useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from './api'
import { importedFieldGeometry } from './FieldSetupDialog'
import { FieldImageryAnalyticsPanel, type ImageryJob } from './FieldImageryAnalyticsPanel'
import type { FieldSummary } from './farmTypes'
import { readableError } from './farmTypes'
import { displayDate } from './fieldLabels'
import type { ImageryOverlay, ShowFieldImage } from './ImageryMapPreview'
import { sourceStateLabel } from './FieldSourceSummary'

type Dates = { start: string; end: string }
type Index = 'NDVI' | 'NDMI'
type Scene = {
  scene_id: string
  provider_id: string
  acquired_at: string
  scene_cloud_percent: number
  field_cloud_fraction: number | null
  field_cloud_status: 'unknown' | 'detected' | 'clear'
  usable_fraction: number | null
  indices: Record<Index, number | null>
  job_id?: string
}
type Series = {
  id: string
  current_geometry: boolean
  geometry_revision_id: string
  status: string
  request: { start_date: string; end_date: string }
  result?: {
    status: string
    scenes: Scene[]
    total: number
    processed: number
    minimum_usable_fraction: number
    exclusions: { low_coverage: number; unknown_coverage: number; no_usable_pixels: number; unavailable: number }
  }
}
type Availability = { status: string; worker?: { message?: string } }
type SceneImage = ImageryOverlay & {
  status?: string
  message?: string
  provider_id?: string
  scene_id?: string
  index?: Index
  geometry_revision_id: string
}

function recentDates(days: number): Dates {
  const today = new Date()
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (days - 1))
  const iso = (date: Date) => new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate())).toISOString().slice(0, 10)
  return { start: iso(start), end: iso(today) }
}

const sensor = (scene: Scene) => scene.provider_id === 'hls-l30-planetary-computer' ? 'Landsat' : 'Sentinel-2'
const pct = (fraction: number) => fraction.toLocaleString(undefined, { style: 'percent', maximumFractionDigits: 1 })
const active = (job?: Series | null) => job?.status === 'queued' || job?.status === 'running'
const rangeOf = (job: Series) => ({ start: job.request.start_date, end: job.request.end_date })
const acquisitionTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' })
const acquired = (scene: Scene) => `${acquisitionTime.format(new Date(scene.acquired_at))} UTC`
const analysisQuestion = 'For this field, what are the NDVI and NDMI averages in the selected satellite image, and what area do those averages describe?'
const UTC_DAY_MS = 86_400_000
const indexTick = new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 })
const boundedIndex = (value: number) => Math.max(-1, Math.min(1, value))

function indexScale(values: number[]) {
  const low = Math.min(...values)
  const high = Math.max(...values)
  const padding = Math.max(.04, (high - low) * .08)
  const bottom = Math.max(-1, low - padding)
  const top = Math.min(1, high + padding)
  const step = [.025, .05, .1, .2, .5, 1].find(candidate => candidate >= (top - bottom) / 4) ?? 1
  const min = Math.max(-1, Math.floor(bottom / step) * step)
  const max = Math.min(1, Math.ceil(top / step) * step)
  const ticks = Array.from({ length: Math.round((max - min) / step) + 1 }, (_, i) => Number((max - i * step).toFixed(3)))
  return { min, max, ticks }
}

function IndexChart({ index, dates, rows, selected, onPick }: {
  index: Index; dates: Dates; rows: Scene[]; selected: string; onPick: (scene: Scene, index: Index) => void
}) {
  const start = Date.parse(dates.start)
  const end = Date.parse(dates.end) + UTC_DAY_MS
  const middle = new Date(start + (end - start) / 2).toISOString().slice(0, 10)
  const points = rows.flatMap(scene => {
    const value = scene.indices[index]
    return typeof value === 'number' && Number.isFinite(value) ? [{ scene, value, time: Date.parse(scene.acquired_at) }] : []
  })
  if (!points.length) return null
  const daily = new Map<number, { count: number; timeSum: number; valueSum: number }>()
  for (const { time, value } of points) {
    const day = Math.floor(time / UTC_DAY_MS)
    const totals = daily.get(day) ?? { count: 0, timeSum: 0, valueSum: 0 }
    totals.count += 1
    totals.timeSum += time
    totals.valueSum += value
    daily.set(day, totals)
  }
  const { min, max, ticks } = indexScale(points.map(({ value }) => boundedIndex(value)))
  const x = (time: number) => 100 * (time - start) / (end - start)
  const y = (value: number) => 100 * (max - boundedIndex(value)) / (max - min)
  const dailyMeans = [...daily].sort(([a], [b]) => a - b)
    .map(([, { count, timeSum, valueSum }]) => ({ x: x(timeSum / count), y: y(valueSum / count) }))
  return <section className="imagery-series-chart" aria-label={`${index} by acquisition date`}>
    <div className="imagery-chart-heading">
      <h4>{index}</h4>
      <span className="imagery-chart-mean-label">Daily mean</span>
    </div>
    <div className="imagery-chart-grid">
      <div className="imagery-chart-scale">
        {ticks.map(tick => <span key={tick} style={{ top: `${y(tick)}%` }}>{indexTick.format(tick)}</span>)}
      </div>
      <div className="imagery-chart-plot">
        {ticks.map(tick => <span className="imagery-chart-line" aria-hidden="true" key={tick} style={{ top: `${y(tick)}%` }} />)}
        {dailyMeans.length > 1
          ? <svg className="imagery-chart-mean-path" aria-hidden="true" viewBox="0 0 100 100" preserveAspectRatio="none">
            <polyline points={dailyMeans.map(point => `${point.x},${point.y}`).join(' ')} vectorEffect="non-scaling-stroke" />
          </svg>
          : <span className="imagery-chart-mean-marker" aria-hidden="true"
            style={{ left: `${dailyMeans[0].x}%`, top: `${dailyMeans[0].y}%` }} />}
        {points.map(({ scene, value, time }) => {
          const left = x(time)
          const pointValue = `${index} ${value.toFixed(3)}`
          return <button type="button" className="imagery-chart-point" key={scene.scene_id}
            data-sensor={sensor(scene)} aria-label={`${pointValue} · ${acquired(scene)} · ${sensor(scene)}`} aria-pressed={selected === scene.scene_id}
            style={{ left: `${left}%`, top: `${y(value)}%` }} onClick={() => onPick(scene, index)}>
            <span className="imagery-chart-tooltip" aria-hidden="true" data-align={left > 85 ? 'end' : undefined}>{pointValue}</span>
          </button>
        })}
      </div>
      <div className="imagery-chart-dates" aria-hidden="true"><span>{displayDate(dates.start)}</span>{middle !== dates.start && middle !== dates.end ? <span>{displayDate(middle)}</span> : null}<span>{dates.end !== dates.start ? displayDate(dates.end) : ''}</span></div>
    </div>
  </section>
}

export default function FieldImageryWorkspace({ field, allowNetwork, onAsk, onShowImage }: {
  field: FieldSummary; allowNetwork: boolean; onShowImage: ShowFieldImage
  onAsk: (question: string, imageryJobId?: string) => void
}) {
  const [dates, setDates] = useState(() => recentDates(30))
  const [series, setSeries] = useState<Series | null>(null)
  const [ranges, setRanges] = useState<Series[]>([])
  const [selected, setSelected] = useState<Scene | null>(null)
  const [retained, setRetained] = useState<ImageryJob | null>(null)
  const [jobs, setJobs] = useState<ImageryJob[]>([])
  const [historyVersion, setHistoryVersion] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [setup, setSetup] = useState<Availability | null>(null)
  const [setupAttempt, setSetupAttempt] = useState(0)
  const [setupError, setSetupError] = useState('')
  const [error, setError] = useState('')
  const [imageError, setImageError] = useState('')
  const [imageBusy, setImageBusy] = useState(false)
  const [recordStatus, setRecordStatus] = useState('')
  const [linking, setLinking] = useState(false)
  const loadingEpoch = useRef(0)
  const imageEpoch = useRef(0)
  const attempted = useRef<{ start_date: string; end_date: string; operation_id: string } | null>(null)
  const fieldUrl = `/api/fields/${encodeURIComponent(field.id)}`
  const revision = field.geometry_revision_id
  const multipart = field.geometry.kind === 'geojson' && field.geometry.geojson.type === 'MultiPolygon'

  useEffect(() => {
    let live = true
    setSetup(null)
    setSetupError('')
    apiGet<Availability>(`/api/demo/fields/${encodeURIComponent(field.id)}/imagery/analytics`)
      .then(value => { if (live) setSetup(value) })
      .catch(cause => { if (live) setSetupError(readableError(cause)) })
    return () => { live = false }
  }, [field.id, setupAttempt])

  useEffect(() => {
    let live = true
    const generation = loadingEpoch.current
    apiGet<{ jobs: Series[] }>(`${fieldUrl}/imagery-series`).then(value => {
      if (!live) return
      const current = (value.jobs || []).filter(job => job.current_geometry && job.geometry_revision_id === revision)
      setRanges(previous => [...new Map([...current, ...previous].map(job => [job.id, job])).values()].slice(0, 8))
      if (current.length && generation === loadingEpoch.current) {
        setSeries(current[0])
        setDates(rangeOf(current[0]))
      }
    }).catch(cause => { if (live) setError(readableError(cause)) })
    return () => { live = false; loadingEpoch.current += 1; imageEpoch.current += 1 }
  }, [fieldUrl, revision])

  useEffect(() => {
    let live = true
    apiGet<{ jobs: ImageryJob[] }>(`${fieldUrl}/imagery-jobs`).then(value => {
      if (live) setJobs(value.jobs)
    }).catch(cause => { if (live) setError(readableError(cause)) })
    return () => { live = false }
  }, [fieldUrl, historyVersion])

  const seriesId = active(series) ? series?.id : undefined
  useEffect(() => {
    if (!seriesId) return
    let live = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const job = await apiGet<Series>(`/api/imagery-jobs/${encodeURIComponent(seriesId)}`)
        if (!live) return
        setSeries(job)
        if (!active(job)) {
          setRanges(previous => [job, ...previous.filter(range => range.id !== job.id)].slice(0, 8))
          setHistoryVersion(version => version + 1)
          return
        }
      } catch (cause) {
        if (live) setError(readableError(cause))
      }
      if (live) timer = setTimeout(poll, 1400)
    }
    timer = setTimeout(poll, 700)
    return () => { live = false; clearTimeout(timer) }
  }, [seriesId])

  function clearImage() {
    imageEpoch.current += 1
    onShowImage(null)
    setImageBusy(false)
    setImageError('')
  }

  function editDates(next: Dates) {
    loadingEpoch.current += 1
    clearImage()
    setDates(next)
    setSeries(null)
    setSelected(null)
    setError('')
  }

  async function run() {
    if (submitting || seriesId) return
    const generation = ++loadingEpoch.current
    clearImage()
    setSelected(null)
    setRetained(null)
    setSeries(null)
    setSubmitting(true)
    setError('')
    const { start, end } = dates
    if (!attempted.current || attempted.current.start_date !== start || attempted.current.end_date !== end) {
      attempted.current = { start_date: start, end_date: end, operation_id: crypto.randomUUID() }
    }
    try {
      const job = await apiPost<Series>(`${fieldUrl}/imagery-series`, {
        ...attempted.current, expected_geometry_revision_id: revision,
      })
      if (generation !== loadingEpoch.current) return
      if (!job.current_geometry || job.geometry_revision_id !== revision) throw new Error('The saved field boundary changed.')
      attempted.current = null
      setSeries(job)
      setRanges(previous => [job, ...previous.filter(range => range.id !== job.id)].slice(0, 8))
    } catch (cause) {
      if (generation === loadingEpoch.current) setError(readableError(cause))
    } finally {
      if (generation === loadingEpoch.current) setSubmitting(false)
    }
  }

  async function show(scene: Scene, display: Index | 'True color') {
    const turn = ++imageEpoch.current
    onShowImage(null)
    setImageBusy(true)
    setImageError('')
    const day = scene.acquired_at.slice(0, 10)
    try {
      let image: SceneImage
      if (display === 'True color') {
        image = await apiPost<SceneImage>(`${fieldUrl}/imagery-preview`, {
          provider_id: scene.provider_id, scene_id: scene.scene_id, start_date: day, end_date: day, expected_geometry_revision_id: revision,
        })
        if (image.status !== 'available') throw new Error(image.message || 'The satellite image is unavailable.')
        if (image.provider_id !== scene.provider_id || image.scene_id !== scene.scene_id) throw new Error('The image did not match this date.')
      } else {
        if (!scene.job_id) return
        image = await apiGet<SceneImage>(`/api/imagery-jobs/${encodeURIComponent(scene.job_id)}/overlay?index=${display}`)
        if ((image.index || 'NDVI') !== display) throw new Error('The map layer did not match the requested index.')
      }
      if (turn !== imageEpoch.current) return
      if (image.geometry_revision_id !== revision) throw new Error('The saved field boundary changed.')
      onShowImage({
        overlay: image, label: `${display} · ${displayDate(day)} · ${sensor(scene)}`, geometryKey: revision,
      })
    } catch (cause) {
      if (turn === imageEpoch.current) setImageError(readableError(cause))
    } finally {
      if (turn === imageEpoch.current) setImageBusy(false)
    }
  }

  function pick(scene: Scene, index?: Index) {
    setSelected(scene)
    setRetained(null)
    setRecordStatus('')
    const display = index || (scene.indices.NDVI !== null ? 'NDVI' : scene.indices.NDMI !== null ? 'NDMI' : null)
    if (display) void show(scene, display)
    else clearImage()
  }

  async function linkAnalysis(jobId: string) {
    setLinking(true)
    setRecordStatus('')
    try {
      await apiPost(`/api/imagery-jobs/${encodeURIComponent(jobId)}/record`, { season: field.season })
      setRecordStatus('Saved to field records.')
    } catch (cause) { setRecordStatus(readableError(cause)) }
    finally { setLinking(false) }
  }

  const result = series?.current_geometry ? series.result : undefined
  const rows = result?.scenes || []
  const locked = submitting || Boolean(seriesId)
  const seriesStatus = result?.status
  const exclusions = result?.exclusions
  const coverageLimit = result?.minimum_usable_fraction != null ? pct(result.minimum_usable_fraction) : ''
  const selectedCoverage = selected?.usable_fraction != null ? pct(selected.usable_fraction) : null
  const displayedCoverage = selectedCoverage === coverageLimit ? `>${coverageLimit}` : selectedCoverage
  const history = jobs.filter(job => !job.request.series_job_id)
  return <section className="field-imagery-workspace" aria-label="Field imagery">
    <form className="imagery-range-form" onSubmit={event => { event.preventDefault(); void run() }}>
      <div className="imagery-range-dates">
        <label>From<input type="date" required disabled={locked} value={dates.start} onChange={event => editDates({ ...dates, start: event.target.value })} /></label>
        <label>Through<input type="date" required disabled={locked} min={dates.start} value={dates.end} onChange={event => editDates({ ...dates, end: event.target.value })} /></label>
      </div>
      <div className="farm-date-presets">
        {[30, 90, 180].map(days => <button type="button" key={days} disabled={locked} onClick={() => editDates(recentDates(days))}>Last {days} days</button>)}
      </div>
      <div className="imagery-range-actions">
        {locked ? <>
          <span role="status">{result ? `Analyzed ${result.processed} of ${result.total} scenes` : series?.status === 'queued' ? 'Date range queued' : 'Searching Sentinel-2 and Landsat…'}</span>
          {seriesId ? <button type="button" className="imagery-cancel" onClick={() => void apiPost<Series>(`/api/imagery-jobs/${encodeURIComponent(seriesId)}/cancel`, {})
            .then(job => { setSeries(job); setRanges(previous => previous.map(item => item.id === job.id ? job : item)); setHistoryVersion(version => version + 1) })
            .catch(cause => setError(readableError(cause)))}>Cancel analysis</button> : null}
        </> : <button type="submit" className="primary-button" disabled={setup?.status !== 'ready' || !allowNetwork || multipart || field.geometry.kind === 'none'}>Analyze</button>}
        {ranges.length > 1 ? <label className="imagery-range-picker"><span>Recent analyses</span><select disabled={locked} value={series?.id || ''} onChange={event => {
          const job = ranges.find(range => range.id === event.target.value)
          if (!job) return
          clearImage()
          setSelected(null)
          setRetained(null)
          setDates(rangeOf(job))
          setSeries(job)
        }}><option value="">Choose a date range</option>{ranges.map(job => <option key={job.id} value={job.id}>{displayDate(job.request.start_date)} – {displayDate(job.request.end_date)}</option>)}</select></label> : null}
      </div>
    </form>
    {setupError || setup?.status === 'not_configured' || setup?.status === 'worker_unavailable' ? <div className="farm-imagery-setup" role="status">
      <span>{setupError || setup?.worker?.message || 'Install the local imagery worker to analyze images.'}</span>
      <a href="https://tknecht4.github.io/open_agronomy_agent/operations/native-setup/#field-location-and-imagery" target="_blank" rel="noreferrer">Imagery setup</a>
      <button type="button" onClick={() => setSetupAttempt(attempt => attempt + 1)}>Check again</button>
    </div> : null}
    {multipart ? <p role="status">Imagery analysis requires a single field polygon.</p> : null}
    {!allowNetwork ? <p role="status">Connect to analyze a new date range. Saved results remain available.</p> : null}
    {field.geometry.kind === 'none' ? <p role="status">Save a field location to analyze imagery.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {series && !locked ? <div role="status">
      {seriesStatus === 'range_too_large' ? 'Too many scenes match this date range. Choose a shorter range.' :
        seriesStatus === 'catalog_unavailable' ? 'Sentinel-2 and Landsat search is unavailable. Try again.' :
        seriesStatus === 'boundary_changed' ? 'The saved field boundary changed. Run the date range again.' :
        series.status === 'cancelled' ? 'Analysis cancelled. Completed dates are shown below.' :
        series.status === 'interrupted' || series.status === 'failed' ? 'Analysis stopped. Run the date range again to finish.' :
        seriesStatus === 'time_limit' ? 'Analysis reached its time limit. Select a shorter date range to finish.' :
        !result?.total ? 'No Sentinel-2 or Landsat scenes met the 70% scene cloud limit.' :
        !rows.length ? `No acquisitions had more than ${coverageLimit} usable coverage and a usable index.` : null}
    </div> : null}
    {series && result?.processed ? <div className="imagery-series-results">
      <div className="imagery-series-summary">
        {rows.length ? <strong>{rows.length} with usable values</strong> : null}
        {exclusions?.low_coverage ? <span>{exclusions.low_coverage} with {coverageLimit} usable coverage or less</span> : null}
        {exclusions?.unknown_coverage ? <span>{exclusions.unknown_coverage} with unverified coverage</span> : null}
        {exclusions?.no_usable_pixels ? <span>{exclusions.no_usable_pixels} with no usable index pixels</span> : null}
        {exclusions?.unavailable ? <span>{exclusions.unavailable} could not be analyzed</span> : null}
      </div>
      {rows.length ? <>
        <div className="imagery-chart-key"><span data-sensor="Sentinel-2">Sentinel-2</span><span data-sensor="Landsat">Landsat</span></div>
        <IndexChart index="NDVI" dates={rangeOf(series)} rows={rows} selected={selected?.scene_id || ''} onPick={pick} />
        <IndexChart index="NDMI" dates={rangeOf(series)} rows={rows} selected={selected?.scene_id || ''} onPick={pick} />
        <label className="imagery-range-picker"><span>Acquisition</span><select value={selected?.scene_id || ''} onChange={event => {
          const row = rows.find(scene => scene.scene_id === event.target.value)
          if (row) pick(row)
          else { setSelected(null); clearImage() }
        }}><option value="">Choose an acquisition</option>{rows.map(scene => <option key={scene.scene_id} value={scene.scene_id}>
          {acquired(scene)} · {sensor(scene)} · {scene.scene_id.match(/T\d{2}[A-Z]{3}/)?.[0] || scene.scene_id}
        </option>)}</select></label>
      </> : null}
    </div> : null}
    {selected ? <div className="imagery-selected-scene">
      <h3>{acquired(selected)} · {sensor(selected)}</h3>
      <p>{selected.indices.NDVI !== null ? `NDVI ${selected.indices.NDVI.toFixed(3)} · ` : ''}{selected.indices.NDMI !== null ? `NDMI ${selected.indices.NDMI.toFixed(3)} · ` : ''}{displayedCoverage ? `${displayedCoverage} usable · ` : ''}{selected.scene_cloud_percent}% scene cloud</p>
      <p>{selected.field_cloud_fraction != null ? `${pct(selected.field_cloud_fraction)} cloud over ${field.geometry.kind === 'point' ? 'sample' : 'field'}` :
        selected.field_cloud_status === 'detected' ? 'Cloud detected in the observed area' : 'Cloud coverage over the field unavailable'}
      </p>
      <div className="farm-actions">
        <button type="button" disabled={imageBusy || setup?.status !== 'ready'} onClick={() => void show(selected, 'True color')}>Preview image</button>
        {(['NDVI', 'NDMI'] as const).map(index => selected.indices[index] !== null ? <button key={index} type="button" disabled={imageBusy} onClick={() => void show(selected, index)}>Show {index} on map</button> : null)}
      </div>
      {selected.job_id ? <div className="farm-actions imagery-record-actions">
        <button type="button" disabled={linking} onClick={() => void linkAnalysis(selected.job_id!)}>Save to records</button>
        <button type="button" onClick={() => onAsk(analysisQuestion, selected.job_id)}>Ask about this analysis</button>
      </div> : null}
      {recordStatus ? <p role="status">{recordStatus}</p> : null}
      {imageBusy ? <p role="status">Loading image…</p> : null}
      {imageError ? <p role="alert">{imageError}</p> : null}
    </div> : null}
    {history.length ? <section className="farm-imagery-history" aria-label="Image analysis history">
      <h3>Image history</h3>
      <div className="farm-scene-list">{history.map(job => <button type="button" key={job.id} aria-pressed={retained?.id === job.id}
        onClick={() => { clearImage(); setRetained(job); setSelected(null); setRecordStatus('') }}>
        <strong>{displayDate(job.result?.source?.acquired_at || job.request.start_date)}</strong>
        <span>{job.status === 'completed' ? job.result?.status === 'empty_valid_area' ? 'No usable pixels' : 'Ready' : sourceStateLabel(job.status)} · {job.current_geometry ? 'Current boundary' : 'Historical boundary'}</span>
      </button>)}</div>
    </section> : null}
    {retained ? <section>
      {['completed', 'superseded'].includes(retained.status) && retained.result?.status !== 'empty_valid_area' ? <div className="farm-actions">
        <button type="button" disabled={linking} onClick={() => void linkAnalysis(retained.id)}>Save to records</button>
        <button type="button" onClick={() => onAsk(analysisQuestion, retained.id)}>Ask about this analysis</button>
      </div> : null}
      {recordStatus ? <p role="status">{recordStatus}</p> : null}
      {!retained.current_geometry ? <p role="status">Analysis for a historical boundary</p> : null}
      <FieldImageryAnalyticsPanel key={retained.id} fieldContextId={field.id} geometry={importedFieldGeometry(retained.geometry)}
        geometryKey={retained.geometry_revision_id} imageryReady={retained.current_geometry} embedded
        onShowImage={retained.current_geometry ? onShowImage : undefined} retainedJobId={retained.id}
        onJobChanged={() => setHistoryVersion(version => version + 1)} selection={{
          providerId: retained.request.provider_id, sceneId: retained.request.scene_id || '', startDate: retained.request.start_date,
          endDate: retained.request.end_date, samplingMode: retained.request.sampling_mode, sampleRadiusM: retained.request.sample_radius_m,
        }} />
    </section> : null}
  </section>
}
