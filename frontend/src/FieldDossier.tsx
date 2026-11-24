import type { ShowFieldImage } from './ImageryMapPreview'
import { Suspense, useEffect, useState } from 'react'
import { apiGet, apiPatch, apiPost, apiPut } from './api'
import { recoverableLazy as lazy } from './WorkspaceSectionBoundary'
import { WorkspaceDialog } from './WorkspaceDialog'
import { fieldArea, readableError, type Farm, type FieldSummary, type SeasonCrop, type CropSystem } from './farmTypes'
import { displayDate } from './fieldLabels'
import { FieldSourceSummary, sourceStateLabel as stateLabel } from './FieldSourceSummary'

const OfflineTerrainContextPanel = lazy(() => import('./OfflineTerrainContextPanel'), 'Terrain context')
const FieldDataPanel = lazy(() => import('./FieldDataPanel'), 'Field tables')
const FieldImageryWorkspace = lazy(() => import('./FieldImageryWorkspace'), 'Imagery')
const FarmRecords = lazy(() => import('./FarmRecords'), 'Field records')
const tabs = [['overview', 'Overview'], ['imagery', 'Imagery'], ['soil', 'Soil & terrain'], ['records', 'Records'], ['tables', 'Data tables']] as const
const isActiveContextJob = (status: string) => status === 'queued' || status === 'running'


export default function FieldDossier({ field, summaryError, fieldId, season, tab, farms, allowNetwork, unit, onTab, onChanged, onEdit, onAsk, onShowImage }: {
  field: FieldSummary | null; summaryError: string; fieldId: string; season: number; tab: string; farms: Farm[]; allowNetwork: boolean; unit: 'ac' | 'ha'
  onShowImage: ShowFieldImage
  onTab: (tab: string) => void; onChanged: () => void; onEdit: () => void; onAsk: (question?: string, imageryJobId?: string) => void
}) {
  const [error, setError] = useState('')
  const [seasonOpen, setSeasonOpen] = useState(false)
  const [crops, setCrops] = useState<SeasonCrop[]>([{ crop: '', cultivar: null }])
  const [cropSystem, setCropSystem] = useState<CropSystem>('single')
  const [planting, setPlanting] = useState('')
  const [harvest, setHarvest] = useState('')
  const [busy, setBusy] = useState(false)
  const [enrichment, setEnrichment] = useState('')
  const [requestingEnrichment, setRequestingEnrichment] = useState(false)
  const [jobId, setJobId] = useState('')
  const latestJob = field?.latest_context_job
  useEffect(() => {
    if (latestJob && isActiveContextJob(latestJob.status)) {
      setJobId(latestJob.id)
      setEnrichment(stateLabel(latestJob.status))
    }
  }, [latestJob])
  useEffect(() => {
    if (!jobId || requestingEnrichment) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const result = await apiGet<{ status: string }>(`/api/enrichment-jobs/${encodeURIComponent(jobId)}`)
        if (!active) return
        setEnrichment(stateLabel(result.status))
        if (isActiveContextJob(result.status)) timer = setTimeout(poll, 1500)
        else { setJobId(''); onChanged() }
      } catch (cause) { if (active) { setError(readableError(cause)); setJobId('') } }
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [jobId, requestingEnrichment])
  const move = async (farmId: string) => {
    if (!field) return
    setBusy(true); setError('')
    try { await apiPatch(`/api/fields/${encodeURIComponent(fieldId)}/farm`, { farm_id: farmId || null, expected_revision: field.assignment_revision }); onChanged() } catch (cause) { setError(readableError(cause)) } finally { setBusy(false) }
  }
  const saveSeason = async () => {
    if (!field) return
    setBusy(true); setError('')
    try { await apiPut(`/api/fields/${encodeURIComponent(fieldId)}/seasons/${season}`, { expected_revision: field.season_revision, crops: crops.filter(item => item.crop.trim()).map(item => ({ crop: item.crop.trim(), cultivar: item.cultivar?.trim() || null })), crop_system: crops.filter(item => item.crop.trim()).length > 1 ? cropSystem : 'single', planted_at: planting || null, harvested_at: harvest || null }); setSeasonOpen(false); onChanged() } catch (cause) { setError(readableError(cause)) } finally { setBusy(false) }
  }
  const refreshContext = async (sources: string[]) => {
    setError('')
    setEnrichment('Requesting update…')
    setRequestingEnrichment(true)
    try {
      const job = await apiPost<{ id: string; status: string }>(`/api/fields/${encodeURIComponent(fieldId)}/enrichment-jobs`, { sources })
      setJobId(job.id)
      setEnrichment(stateLabel(job.status))
    } catch (cause) {
      setError(readableError(cause))
      setEnrichment('Update unavailable')
    } finally {
      setRequestingEnrichment(false)
    }
  }
  const cancelContextRefresh = async () => {
    if (!jobId || requestingEnrichment) return
    setError('')
    setRequestingEnrichment(true)
    try {
      const result = await apiPost<{ status: string }>(`/api/enrichment-jobs/${encodeURIComponent(jobId)}/cancel`, {})
      setEnrichment(stateLabel(result.status))
      if (!isActiveContextJob(result.status)) {
        setJobId('')
        onChanged()
      }
    } catch (cause) {
      setError(readableError(cause))
    } finally {
      setRequestingEnrichment(false)
    }
  }
  return <section className="field-dossier" aria-label="Field detail">
    {error || summaryError ? <p role="alert" className="farm-error">{error || summaryError}<button type="button" onClick={() => { setError(''); onChanged() }}>Reload field</button></p> : null}
    {!field ? !summaryError && <p role="status">Loading field summary…</p> : <>
      <nav className="field-dossier-tabs" aria-label="Field sections">{tabs.map(([id, label]) => <button type="button" key={id} aria-current={tab === id ? 'page' : undefined} onClick={() => onTab(id)}>{label}</button>)}</nav>
      {tab === 'overview' || !tabs.some(([id]) => id === tab) ? <>
        <dl className="field-facts">
          <div><dt>{season} crop</dt><dd>{field.crop || 'Not confirmed'}{field.legacy_undated_crop && !field.crop ? <small> · Undated: {field.legacy_undated_crop}</small> : null}{field.crop && field.crop_system && field.crop_system !== 'single' && field.crop_system !== 'unknown' ?
            <small> · {({ intercrop: 'Grown together', sequence: 'Grown in sequence', separate_areas: 'Separate areas' })[field.crop_system]}</small> : null}</dd></div>
          <div><dt>Boundary area</dt><dd>{field.geometry_status === 'point' ? 'Point location' : fieldArea(field.boundary_area_m2, unit)}</dd></div>
          <div><dt>Farm</dt><dd><select aria-label="Assign field to farm" disabled={busy} value={field.farm_id || ''} onChange={event => void move(event.target.value)}><option value="">Unassigned</option>{farms.filter(farm => !farm.archived).map(farm => <option key={farm.id} value={farm.id}>{farm.name}</option>)}</select></dd></div>
          <div><dt>Last record</dt><dd>{field.last_record_at ? displayDate(field.last_record_at) : 'None this season'}</dd></div>
          {field.latest_image ? <div><dt>Latest image</dt><dd>{displayDate(field.latest_image.acquired_at)}{!field.latest_image.current_geometry ? ' · Earlier boundary' : ''}</dd></div> : null}
        </dl>
        {field.mapped_location?.message ? <p className="farm-network-note" role="status">{field.mapped_location.message}</p> : null}
        <div className="field-fact-actions">
          <button type="button" onClick={() => { const saved = field.seasons.find(item => item.season === season); setCrops(saved?.crops?.length ? saved.crops : [{ crop: saved?.crop || '', cultivar: saved?.cultivar || null }]); setCropSystem(saved?.crop_system || 'single'); setPlanting(saved?.planted_at || ''); setHarvest(saved?.harvested_at || ''); setSeasonOpen(true) }}>{field.crop ? 'Edit season' : 'Confirm crop & season'}</button>
          {field.mapped_location?.status === 'conflict' ? <button type="button" onClick={onEdit}>Review location</button> : null}
        </div>
        <div className="farm-section-heading"><div><h2>Public sources</h2></div><button type="button" disabled={requestingEnrichment || Boolean(jobId) || field.geometry.kind === 'none'} onClick={() => void refreshContext(['weather', 'soil', 'crop_cover', 'imagery'])}>Refresh sources</button></div>
        <ul className="field-source-rows" aria-label="Source status">
          {Object.entries(field.source_status).map(([source, result]) => <li key={source}><span>{({ weather: 'Weather', soil: 'Mapped soil', crop_cover: 'Crop cover', imagery: 'Imagery' })[source] || source}</span><span>{stateLabel(result.refresh_status || result.availability)}</span></li>)}
        </ul>
        <details className="field-source-details"><summary>Sources &amp; boundary details</summary>
          {allowNetwork ? <p className="farm-network-note">Refreshing shares the field location with the selected public providers.</p> : null}
          <div className="field-source-summaries">{Object.entries(field.source_status).map(([source, result]) => <FieldSourceSummary key={source} source={source} result={result} />)}</div>
          <pre>{JSON.stringify({ mapped_location: field.mapped_location, boundary_import: field.boundary_import, location_confirmation: field.location_confirmation, geometry_revisions: field.geometry_revisions }, null, 2)}</pre>
        </details>
      </> : null}
      {(tab === 'overview' || tab === 'soil') && enrichment ? <p role="status">{enrichment}{jobId ? <button type="button" disabled={requestingEnrichment} onClick={() => void cancelContextRefresh()}>Cancel update</button> : null}</p> : null}
      <Suspense fallback={<p role="status">Opening field section…</p>}>
        {tab === 'imagery' ? <FieldImageryWorkspace key={field.geometry_revision_id} field={field} allowNetwork={allowNetwork} onAsk={onAsk} onShowImage={onShowImage} /> : null}
        {tab === 'soil' ? <>
          <div className="farm-section-heading">
            <h2>Mapped soil</h2>
            <button type="button" disabled={requestingEnrichment || Boolean(jobId) || field.geometry.kind === 'none'} onClick={() => void refreshContext(['soil'])}>Refresh mapped soil</button>
          </div>
          <p>{field.geometry.kind === 'none' ? 'Add a field location to check mapped soil.' : allowNetwork ? 'Refresh may share the field location with a public soil data provider.' : 'Offline · using saved data and installed sources.'}</p>
          <FieldSourceSummary source="soil" result={field.source_status.soil || { availability: 'not_requested', freshness: 'unknown' }} />
          <OfflineTerrainContextPanel key={`${field.geometry_revision_id}:${field.mapped_location?.province_state || field.confirmed_facts?.province_state || ''}`} id={fieldId} m="account_workspace" k={field.geometry.kind} area={field.mapped_location?.province_state || field.confirmed_facts?.province_state || ''} />
          <details className="field-source-details"><summary>Technical regional record</summary><pre>{JSON.stringify(field.public_context, null, 2)}</pre></details>
        </> : null}
        {tab === 'records' ? <FarmRecords key={`${fieldId}:${season}`} fieldId={fieldId} fields={[field]} season={season} onChanged={onChanged} /> : null}
        {tab === 'tables' ? <FieldDataPanel fieldContextId={fieldId} geometryKey={field.geometry_revision_id} geometryKind={field.geometry.kind} imageryReady={false} showImagery={false} onAskQuestion={onAsk} /> : null}
      </Suspense>
    </>}
    {seasonOpen && field ? <WorkspaceDialog title={`Confirm ${season} season`} busy={busy} onClose={() => { if (!busy) setSeasonOpen(false) }}><form className="farm-form" onSubmit={event => { event.preventDefault(); void saveSeason() }}>{crops.map((item, index) => <fieldset key={index}><legend>Crop {index + 1}</legend><label>Crop<input data-dialog-initial-focus={index === 0 ? true : undefined} aria-label={`Crop ${index + 1}`} value={item.crop} maxLength={120} onChange={event => setCrops(rows => rows.map((row, at) => at === index ? { ...row, crop: event.target.value } : row))} /></label><label>Cultivar (optional)<input aria-label={`Cultivar ${index + 1}`} value={item.cultivar || ''} maxLength={120} onChange={event => setCrops(rows => rows.map((row, at) => at === index ? { ...row, cultivar: event.target.value } : row))} /></label>{crops.length > 1 ? <button type="button" onClick={() => setCrops(rows => rows.filter((_, at) => at !== index))}>Remove crop {index + 1}</button> : null}</fieldset>)}<button type="button" disabled={crops.length >= 12} onClick={() => { setCrops(rows => [...rows, { crop: '', cultivar: null }]); if (cropSystem === 'single') setCropSystem('unknown') }}>Add another crop</button>{crops.length > 1 ? <label>How do the crops share this field?<select value={cropSystem} onChange={event => setCropSystem(event.target.value as CropSystem)}><option value="unknown">Choose when known</option><option value="intercrop">Intercrop / mixture grown together</option><option value="sequence">Grown in sequence</option><option value="separate_areas">Separate parts of the field</option></select></label> : null}<h3>Season dates</h3><label>Planted (optional)<input type="date" value={planting} onChange={event => setPlanting(event.target.value)} /></label><label>Harvested (optional)<input type="date" min={planting || undefined} value={harvest} onChange={event => setHarvest(event.target.value)} /></label>{error ? <p role="alert">{error}</p> : null}<button type="submit" className="primary-button" disabled={busy}>{busy ? 'Saving…' : 'Save season'}</button></form></WorkspaceDialog> : null}
  </section>
}
