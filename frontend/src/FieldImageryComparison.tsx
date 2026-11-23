import { Suspense, useEffect, useState } from 'react'
import { apiPost } from './api'
import { decodeImageryOverlay, type ImageryOverlay } from './ImageryMapPreview'
import { recoverableLazy as lazy } from './WorkspaceSectionBoundary'
import type { FieldSummary } from './farmTypes'
import { readableError } from './farmTypes'
import type { ImageryJob } from './FieldImageryAnalyticsPanel'
import { imagerySourceLabel } from './fieldLabels'
import type { ImageryComparisonSelection } from './turnReadiness'

const LeafletFieldMap = lazy(() => import('./LeafletFieldMap').then(m => ({ default: m.LeafletFieldMap })), 'Change map')
type Comparison = {
  status: string
  map_status?: 'available' | 'limited'
  overview: string
  question: string
  selection: { jobs: { id: string }[]; geometry_revision_id: string }
  indices?: Record<string, { status: string; before_mean?: number; after_mean?: number }>
  scouting_observation?: { date: string; date_basis: 'utc' | 'recorded_local'; location: string } | null
  maps?: Partial<Record<'NDVI' | 'NDMI', ImageryOverlay>>
}

function ChangeMap({ field, map, index, allowNetwork }: {
  field: FieldSummary; map: ImageryOverlay; index: string; allowNetwork: boolean
}) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    try {
      const objectUrl = URL.createObjectURL(decodeImageryOverlay(map))
      setUrl(objectUrl)
      return () => URL.revokeObjectURL(objectUrl)
    } catch (cause) {
      setError(readableError(cause))
    }
  }, [map])
  return <section aria-label={`${index} change map`}>
    {error ? <p role="alert">{error}</p> : url ? <div className="farm-map">
      <Suspense fallback={<p>Loading change map…</p>}>
        <LeafletFieldMap mode="inspect" scenarioId="analysis" fieldLabel="Saved field boundary" fieldKey={field.geometry_revision_id}
          geometry={field.geometry} analyticalOverlay={{ url, bounds: map.bounds, opacity: .85 }} regionalCandidates={[]}
          regionalFeatureCollection={null} onGeometryChange={() => {}} onStatusChange={() => {}} allowNetwork={allowNetwork} />
      </Suspense>
    </div> : null}
    <p>Orange shows a decrease, white shows zero change, and blue shows an increase. Colors reach their limits at −0.2 and +0.2. Transparent areas have no displayed comparison.</p>
  </section>
}

export default function FieldImageryComparison({ field, jobs, allowNetwork, onAsk }: {
  field: FieldSummary; jobs: ImageryJob[]; allowNetwork: boolean
  onAsk: (question: string, jobId?: string, comparison?: ImageryComparisonSelection) => void
}) {
  const [first, setFirst] = useState('')
  const [second, setSecond] = useState('')
  const [resolved, setResolved] = useState<{ result: Comparison; selection: ImageryComparisonSelection } | null>(null)
  const [index, setIndex] = useState<'NDVI' | 'NDMI' | ''>('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const eligible = jobs.filter(job => job.current_geometry && job.status === 'completed'
    && job.geometry_revision_id === field.geometry_revision_id && job.geometry.type === 'Polygon' && job.result?.source?.acquired_at)

  const compare = async () => {
    const selection = { first_job_id: first, second_job_id: second, geometry_revision_id: field.geometry_revision_id }
    setBusy(true); setError(''); setResolved(null); setIndex('')
    try {
      const result = await apiPost<Comparison>(`/api/fields/${encodeURIComponent(field.id)}/imagery-comparison`, selection)
      if (result.selection.geometry_revision_id !== selection.geometry_revision_id
        || result.selection.jobs.map(job => job.id).sort().join() !== [first, second].sort().join()) {
        throw new Error('The comparison did not match the selected analyses.')
      }
      setResolved({ result, selection })
      setIndex(result.maps?.NDVI ? 'NDVI' : result.maps?.NDMI ? 'NDMI' : '')
    } catch (cause) {
      setError(readableError(cause))
    } finally {
      setBusy(false)
    }
  }

  const options = (other: string) => eligible.map(job => <option key={job.id} value={job.id} disabled={job.id === other}>
    {job.result?.source?.acquired_at?.slice(0, 10)} UTC · {imagerySourceLabel(job.request.provider_id)} · {job.request.scene_id || job.id.slice(0, 8)}
  </option>)
  const result = resolved?.result
  const map = index && result?.maps?.[index]
  return <section className="farm-imagery-history" aria-label="Compare two dates">
    <h3>Change between dates</h3>
    {eligible.length < 2 ? <p>Save two analyses on the current field boundary to compare them.</p> : <>
      <form className="farm-imagery-search" onSubmit={event => { event.preventDefault(); void compare() }}>
        <label>First analysis<select value={first} disabled={busy} onChange={event => { setFirst(event.target.value); setResolved(null); setError('') }}>
          <option value="">Choose an analysis</option>{options(second)}
        </select></label>
        <label>Second analysis<select value={second} disabled={busy} onChange={event => { setSecond(event.target.value); setResolved(null); setError('') }}>
          <option value="">Choose an analysis</option>{options(first)}
        </select></label>
        <button type="submit" disabled={busy || !first || !second || first === second}>{busy ? 'Comparing…' : 'Compare saved analyses'}</button>
      </form>
      {error ? <p role="alert">{error}</p> : null}
      {result ? <>
        <p role="status">{result.overview}</p>
        {result.status === 'descriptive_only' ? <ul aria-label="Index means on shared usable pixels">
          {Object.entries(result.indices || {}).map(([name, values]) => values.status === 'observed_on_overlap'
            && typeof values.before_mean === 'number' && typeof values.after_mean === 'number'
            ? <li key={name}>{name} on shared pixels · Earlier {values.before_mean.toFixed(3)} · Later {values.after_mean.toFixed(3)}</li> : null)}
        </ul> : null}
        {result.status === 'descriptive_only' && result.maps ? <div className="farm-actions">
          {(['NDVI', 'NDMI'] as const).map(name => result.maps?.[name] ? <button key={name} type="button"
            aria-pressed={name === index} onClick={() => setIndex(name)}>{name} change</button> : null)}
        </div> : null}
        {result.map_status === 'limited' ? <p>The change values remain available. One or more maps could not be displayed.</p> : null}
        {map && result.status === 'descriptive_only'
          ? <ChangeMap key={index} index={index} field={field} map={map} allowNetwork={allowNetwork} /> : null}
        {result.scouting_observation ? <p>For a ground check, use the location in your {result.scouting_observation.date}{result.scouting_observation.date_basis === 'utc' ? ' (UTC)' : ''} field observation. <strong>{result.scouting_observation.location}</strong></p>
          : <p>Add a dated field observation with a location to guide a ground check.</p>}
        <button type="button" onClick={() => onAsk(result.question, undefined, resolved!.selection)}>Ask about this comparison</button>
      </> : null}
    </>}
  </section>
}
