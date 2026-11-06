import { Suspense, useEffect, useRef, useState } from 'react'
import { apiGet, apiPatch, apiPost, apiPut } from './api'
import { recoverableLazy as lazy } from './WorkspaceSectionBoundary'
import { WorkspaceDialog } from './WorkspaceDialog'
import { fieldArea, readableError, type Farm, type FieldSummary, type SeasonCrop, type CropSystem } from './farmTypes'
import { fieldGeometryGeoJson } from './fieldGeometry'
import { FieldSourceSummary, sourceStateLabel as stateLabel } from './FieldSourceSummary'

const FieldMapInsights = lazy(() => import('./FieldMapInsights').then(m => ({ default: m.FieldMapInsights })), 'Mapped context')
const FieldDataPanel = lazy(() => import('./FieldDataPanel'), 'Field tables')
const FieldImageryWorkspace = lazy(() => import('./FieldImageryWorkspace'), 'Imagery')
const FarmRecords = lazy(() => import('./FarmRecords'), 'Field records')
const tabs = [['overview', 'Overview'], ['imagery', 'Imagery'], ['soil', 'Soil & terrain'], ['records', 'Records'], ['tables', 'Data tables']] as const
type LocationSuggestions = { status: string; message: string; boundary: string; candidates: Array<{ id: string; country: string; province: string; coverage: number; confirmable: boolean; source_url: string }> }


export default function FieldDossier({ fieldId, season, tab, farms, allowNetwork, unit, onTab, onChanged, onEdit, onAsk }: {
  fieldId: string; season: number; tab: string; farms: Farm[]; allowNetwork: boolean; unit: 'ac' | 'ha'
  onTab: (tab: string) => void; onChanged: () => void; onEdit: () => void; onAsk: (question?: string) => void
}) {
  const [field, setField] = useState<FieldSummary | null>(null)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [seasonOpen, setSeasonOpen] = useState(false)
  const [crops, setCrops] = useState<SeasonCrop[]>([{ crop: '', cultivar: null }])
  const [cropSystem, setCropSystem] = useState<CropSystem>('single')
  const [planting, setPlanting] = useState('')
  const [harvest, setHarvest] = useState('')
  const [busy, setBusy] = useState(false)
  const [enrichment, setEnrichment] = useState('')
  const [jobId, setJobId] = useState('')
  const [locations, setLocations] = useState<LocationSuggestions | null>(null)
  const [locating, setLocating] = useState(false)
  const epoch = useRef(0)
  useEffect(() => {
    const id = ++epoch.current
    setField(null); setError('')
    apiGet<FieldSummary>(`/api/fields/${encodeURIComponent(fieldId)}/summary?season=${season}`).then(value => { if (id === epoch.current) { setField(value); if (value.latest_context_job && ['queued', 'running'].includes(value.latest_context_job.status)) { setJobId(value.latest_context_job.id); setEnrichment(stateLabel(value.latest_context_job.status)) } } }).catch(cause => { if (id === epoch.current) setError(readableError(cause)) })
    return () => { epoch.current += 1 }
  }, [fieldId, season, refresh])
  useEffect(() => {
    if (!jobId) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const result = await apiGet<{ status: string }>(`/api/enrichment-jobs/${encodeURIComponent(jobId)}`)
        if (!active) return
        setEnrichment(stateLabel(result.status))
        if (['queued', 'running'].includes(result.status)) timer = setTimeout(poll, 1500)
        else { setJobId(''); setRefresh(v => v + 1); onChanged() }
      } catch (cause) { if (active) { setError(readableError(cause)); setJobId('') } }
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [jobId])
  const move = async (farmId: string) => {
    if (!field) return
    setBusy(true); setError('')
    try { await apiPatch(`/api/fields/${encodeURIComponent(fieldId)}/farm`, { farm_id: farmId || null, expected_revision: field.assignment_revision }); setRefresh(v => v + 1); onChanged() } catch (cause) { setError(readableError(cause)) } finally { setBusy(false) }
  }
  const saveSeason = async () => {
    if (!field) return
    setBusy(true); setError('')
    try { await apiPut(`/api/fields/${encodeURIComponent(fieldId)}/seasons/${season}`, { expected_revision: field.season_revision, crops: crops.filter(item => item.crop.trim()).map(item => ({ crop: item.crop.trim(), cultivar: item.cultivar?.trim() || null })), crop_system: crops.filter(item => item.crop.trim()).length > 1 ? cropSystem : 'single', planted_at: planting || null, harvested_at: harvest || null }); setSeasonOpen(false); setRefresh(v => v + 1); onChanged() } catch (cause) { setError(readableError(cause)) } finally { setBusy(false) }
  }
  const refreshContext = async () => {
    setError(''); setEnrichment('Requesting update…')
    try { const job = await apiPost<{ id: string; status: string }>(`/api/fields/${encodeURIComponent(fieldId)}/enrichment-jobs`, { sources: ['weather', 'soil', 'crop_cover', 'imagery'] }); setJobId(job.id); setEnrichment(stateLabel(job.status)) } catch (cause) { setError(readableError(cause)); setEnrichment('Update unavailable') }
  }
  const checkLocation = async () => {
    setLocating(true); setError('')
    try { setLocations(await apiGet<LocationSuggestions>(`/api/fields/${encodeURIComponent(fieldId)}/location-suggestions`)) }
    catch (cause) { setError(readableError(cause)) } finally { setLocating(false) }
  }
  const confirmLocation = async (suggestion: string) => {
    if (!field) return
    setLocating(true); setError('')
    try { await apiPost(`/api/fields/${encodeURIComponent(fieldId)}/confirm-location`, { suggestion_id: suggestion, expected_updated_at: field.updated_at }); setLocations(null); setRefresh(v => v + 1); onChanged() }
    catch (cause) { setError(readableError(cause)) } finally { setLocating(false) }
  }
  return <section className="field-dossier" aria-label="Field detail">
    {error ? <p role="alert" className="farm-error">{error}<button type="button" onClick={() => setRefresh(v => v + 1)}>Reload field</button></p> : null}
    {!field ? <p role="status">Loading field summary…</p> : <>
      <header className="field-dossier-heading"><div><h1>{field.name}</h1><p>{field.crop || 'Crop not confirmed'} · {fieldArea(field.boundary_area_m2, unit)}{field.geometry_status === 'point' ? ' · Point location' : field.geometry_status === 'unknown' ? ' · Location unknown' : ''}</p></div><div className="farm-actions"><button type="button" onClick={onEdit}>Edit field</button><button type="button" className="primary-button" onClick={() => onAsk()}>Ask about this field</button></div></header>
      <nav className="field-dossier-tabs" aria-label="Field sections">{tabs.map(([id, label]) => <button type="button" key={id} aria-current={tab === id ? 'page' : undefined} onClick={() => onTab(id)}>{label}</button>)}</nav>
      {tab === 'overview' || !tabs.some(([id]) => id === tab) ? <>
        <div className="field-summary-grid"><section><h3>Field facts</h3><dl><div><dt>Farm</dt><dd><select aria-label="Assign field to farm" disabled={busy} value={field.farm_id || ''} onChange={event => void move(event.target.value)}><option value="">Unassigned</option>{farms.filter(farm => !farm.archived).map(farm => <option key={farm.id} value={farm.id}>{farm.name}</option>)}</select></dd></div><div><dt>{season} crop</dt><dd>{field.crop || 'Not confirmed'}{field.crop_system && !['single', 'unknown'].includes(field.crop_system) ? ` · ${field.crop_system.replace(/_/g, ' ')}` : ''}</dd></div><div><dt>Country</dt><dd>{field.country || 'Not confirmed'}</dd></div><div><dt>Boundary area</dt><dd>{fieldArea(field.boundary_area_m2, unit)}<small className="field-area-note">Calculated, not surveyed</small></dd></div><div><dt>Last record</dt><dd>{field.last_record_at ? new Date(field.last_record_at).toLocaleString() : 'No records this season'}</dd></div></dl>
          {field.legacy_undated_crop ? <p className="farm-unknown">An older entry says “{field.legacy_undated_crop}” without a year. It has not been assigned to this season.</p> : null}
          <div className="field-fact-actions"><button type="button" onClick={() => { const saved = field.seasons.find(item => item.season === season); setCrops(saved?.crops?.length ? saved.crops : [{ crop: saved?.crop || '', cultivar: saved?.cultivar || null }]); setCropSystem(saved?.crop_system || 'single'); setPlanting(saved?.planted_at || ''); setHarvest(saved?.harvested_at || ''); setSeasonOpen(true) }}>{field.crop ? 'Edit season' : 'Confirm crop & season'}</button>
          {field.geometry.kind !== 'none' ? <button type="button" disabled={locating} onClick={() => void checkLocation()}>{locating ? 'Checking location…' : 'Check mapped location'}</button> : null}</div>
          {locations ? <div role="status"><p>{locations.message}</p>{locations.candidates.map(candidate => <p key={candidate.id}>{candidate.province}, {candidate.country} · {(candidate.coverage * 100).toFixed(1)}% mapped coverage. {candidate.confirmable ? <button type="button" disabled={locating} onClick={() => void confirmLocation(candidate.id)}>Confirm {candidate.province} as field location</button> : null}<a href={candidate.source_url} target="_blank" rel="noreferrer">Source</a></p>)}<small>{locations.boundary}</small></div> : null}
        </section><section><div className="field-activity-block"><h3>Records</h3><p>{field.record_count} saved for {season}</p><button type="button" onClick={() => onTab('records')}>View records</button></div><div className="field-activity-block"><h3>Latest imagery</h3>{field.latest_image ? <><p>{field.latest_image.acquired_at?.slice(0, 10) || 'Date unknown'} · {field.latest_image.provider_id.startsWith('hls') ? 'HLS' : 'Sentinel-2'}</p><p>{field.latest_image.current_geometry ? 'Current boundary' : 'Historical boundary — does not describe the current shape.'}</p><button type="button" onClick={() => onTab('imagery')}>View analysis</button></> : <p>No saved analysis</p>}</div></section></div>
        <div className="farm-section-heading"><div><h3>Public sources</h3></div><button type="button" disabled={Boolean(jobId) || field.geometry.kind === 'none'} onClick={() => void refreshContext()}>Refresh sources</button></div>
        <p className="farm-network-note">{allowNetwork ? 'Refresh shares this field’s location or boundary with public data providers.' : 'Offline · using saved data and installed sources.'}</p>
        {enrichment ? <p role="status">{enrichment}{jobId ? <button type="button" onClick={() => { void apiPost(`/api/enrichment-jobs/${jobId}/cancel`, {}).then(() => { setJobId(''); setEnrichment('Cancelled'); setRefresh(v => v + 1) }).catch(cause => setError(readableError(cause))) }}>Cancel update</button> : null}</p> : null}
        <div className="field-source-summaries">{Object.entries(field.source_status).map(([source, result]) => <FieldSourceSummary key={source} source={source} result={result} onOpen={source === 'imagery' ? () => onTab('imagery') : source === 'soil' ? () => onTab('soil') : undefined} />)}</div>
        <details className="field-source-details"><summary>Boundary source & revisions</summary><p>{field.geometry_revisions.length} retained geometry revisions. An older analysis belongs to its original geometry.</p><pre>{JSON.stringify({ boundary_import: field.boundary_import, location_confirmation: field.location_confirmation, geometry_revisions: field.geometry_revisions }, null, 2)}</pre></details>
      </> : null}
      <Suspense fallback={<p role="status">Opening field section…</p>}>
        {tab === 'imagery' ? <FieldImageryWorkspace field={field} allowNetwork={allowNetwork} onAsk={onAsk} /> : null}
        {tab === 'soil' ? <><h3>Mapped soil & terrain context</h3><p>Mapped soil is not a lab result. Terrain source discovery does not establish a derived terrain result.</p>{field.geometry.kind !== 'none' ? <FieldMapInsights geometry={fieldGeometryGeoJson(field.geometry)} fieldKey={field.geometry_revision_id} fieldName={field.name} layerIds={[]} allowNetwork={allowNetwork} recordedAcres={null} /> : <p>Add a location before requesting spatial context.</p>}<details><summary>Retained regional context</summary><pre>{JSON.stringify(field.public_context, null, 2)}</pre></details></> : null}
        {tab === 'records' ? <FarmRecords key={`${fieldId}:${season}`} fieldId={fieldId} season={season} onChanged={() => { setRefresh(v => v + 1); onChanged() }} /> : null}
        {tab === 'tables' ? <FieldDataPanel fieldContextId={fieldId} geometryKey={field.geometry_revision_id} geometryKind={field.geometry.kind} imageryReady={false} showImagery={false} onAskQuestion={onAsk} /> : null}
      </Suspense>
    </>}
    {seasonOpen && field ? <WorkspaceDialog title={`Confirm ${season} season`} busy={busy} onClose={() => { if (!busy) setSeasonOpen(false) }}><form className="farm-form" onSubmit={event => { event.preventDefault(); void saveSeason() }}>{crops.map((item, index) => <fieldset key={index}><legend>Crop {index + 1}</legend><label>Crop<input data-dialog-initial-focus={index === 0 ? true : undefined} aria-label={`Crop ${index + 1}`} value={item.crop} maxLength={120} onChange={event => setCrops(rows => rows.map((row, at) => at === index ? { ...row, crop: event.target.value } : row))} /></label><label>Cultivar (optional)<input aria-label={`Cultivar ${index + 1}`} value={item.cultivar || ''} maxLength={120} onChange={event => setCrops(rows => rows.map((row, at) => at === index ? { ...row, cultivar: event.target.value } : row))} /></label>{crops.length > 1 ? <button type="button" onClick={() => setCrops(rows => rows.filter((_, at) => at !== index))}>Remove crop {index + 1}</button> : null}</fieldset>)}<button type="button" disabled={crops.length >= 12} onClick={() => { setCrops(rows => [...rows, { crop: '', cultivar: null }]); if (cropSystem === 'single') setCropSystem('unknown') }}>Add another crop</button>{crops.length > 1 ? <label>How do the crops share this field?<select value={cropSystem} onChange={event => setCropSystem(event.target.value as CropSystem)}><option value="unknown">Choose when known</option><option value="intercrop">Intercrop / mixture grown together</option><option value="sequence">Grown in sequence</option><option value="separate_areas">Separate parts of the field</option></select></label> : null}<h3>Season dates</h3><label>Planted (optional)<input type="date" value={planting} onChange={event => setPlanting(event.target.value)} /></label><label>Harvested (optional)<input type="date" min={planting || undefined} value={harvest} onChange={event => setHarvest(event.target.value)} /></label>{error ? <p role="alert">{error}</p> : null}<button type="submit" className="primary-button" disabled={busy}>{busy ? 'Saving…' : 'Save season'}</button></form></WorkspaceDialog> : null}
  </section>
}
