import { useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from './api'
import { importedFieldGeometry } from './FieldSetupDialog'
import { FieldImageryAnalyticsPanel, type ImageryJob } from './FieldImageryAnalyticsPanel'
import type { FieldSummary } from './farmTypes'
import { readableError } from './farmTypes'

type Provider = { id: string; name: string; capabilities: string[]; limitations: string; source: string }
type Scene = { id: string; acquired_at: string; scene_cloud_percent: number | null; collection: string }
const providerLabel = (id: string, fallback: string) => ({
  'sentinel2-c1-earth-search': 'Sentinel-2',
  'hls-s30-planetary-computer': 'HLS · Sentinel-2',
  'hls-l30-planetary-computer': 'HLS · Landsat',
}[id] || fallback)
const dates = (days: number) => { const end = new Date(); const start = new Date(end); start.setDate(start.getDate() - days); return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) } }

export default function FieldImageryWorkspace({ field, allowNetwork, onAsk }: { field: FieldSummary; allowNetwork: boolean; onAsk: (question: string) => void }) {
  const [providers, setProviders] = useState<Provider[]>([])
  const [provider, setProvider] = useState('hls-s30-planetary-computer')
  const [window, setWindow] = useState(() => dates(30))
  const [scenes, setScenes] = useState<Scene[]>([])
  const [scene, setScene] = useState<Scene | null>(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [recordStatus, setRecordStatus] = useState('')
  const [linking, setLinking] = useState(false)
  const [busy, setBusy] = useState(false)
  const epoch = useRef(0)
  const [jobs, setJobs] = useState<ImageryJob[] | null>(null)
  const [historyFailed, setHistoryFailed] = useState(false)
  const [providersLoaded, setProvidersLoaded] = useState(false)
  const [selectedJob, setSelectedJob] = useState<ImageryJob | null>(null)
  const [historyVersion, setHistoryVersion] = useState(0)
  const multipart = field.geometry.kind === 'geojson' && field.geometry.geojson.type === 'MultiPolygon'
  useEffect(() => { let active = true; setHistoryFailed(false); apiGet<{ jobs: ImageryJob[] }>(`/api/fields/${encodeURIComponent(field.id)}/imagery-jobs`).then(value => { if (active) setJobs(value.jobs) }).catch(cause => { if (active) { setHistoryFailed(true); setError(readableError(cause)) } }); return () => { active = false } }, [field.id, historyVersion])
  const supported = (provider.startsWith('hls-') && provider.endsWith('-planetary-computer')) || (provider === 'sentinel2-c1-earth-search' && field.geometry.kind !== 'point')
  useEffect(() => { let active = true; apiGet<{ providers: Provider[] }>('/api/imagery/providers').then(result => { if (active) setProviders(result.providers.filter(item => item.capabilities.includes('scene_discovery'))) }).catch(cause => { if (active) setError(readableError(cause)) }).finally(() => { if (active) setProvidersLoaded(true) }); return () => { active = false } }, [])
  useEffect(() => { epoch.current += 1; setScenes([]); setScene(null); setBusy(false); setStatus(''); return () => { epoch.current += 1 } }, [field.id, field.geometry_revision_id, provider, window.start, window.end])
  const search = async () => {
    const id = ++epoch.current
    setBusy(true); setError(''); setScene(null); setSelectedJob(null)
    try {
      const result = await apiPost<{ scenes?: Scene[]; status?: string; message?: string }>(`/api/demo/fields/${encodeURIComponent(field.id)}/imagery/search`, { provider_id: provider, start_date: window.start, end_date: window.end, limit: 10 })
      if (id !== epoch.current) return
      setScenes(result.scenes || [])
      setStatus(result.scenes?.length ? `${result.scenes.length} scenes returned, up to a limit of 10. Scene cloud is metadata; field coverage has not been assessed.` : result.message || 'No scenes returned for this provider and date window.')
    } catch (cause) { if (id === epoch.current) setError(readableError(cause)) } finally { if (id === epoch.current) setBusy(false) }
  }
  const linkAnalysis = async (ask: boolean) => {
    if (!selectedJob) return
    setLinking(true); setRecordStatus(''); setError('')
    try {
      await apiPost(`/api/imagery-jobs/${encodeURIComponent(selectedJob.id)}/record`, { season: field.season })
      setRecordStatus('Analysis reference saved to this field’s records. Repeating this action will reuse the same reference.')
      if (ask) onAsk(`Review the saved satellite analysis reference for ${selectedJob.request.provider_id} scene ${selectedJob.request.scene_id}, job ${selectedJob.id}. Distinguish its supported pixels and original boundary revision from current grower observations. Do not infer crop stress or a prescription.`)
    } catch (cause) { setError(readableError(cause)) } finally { setLinking(false) }
  }
  return <section className="field-imagery-workspace" aria-label="Field imagery">
    <form className="farm-imagery-search" onSubmit={event => { event.preventDefault(); void search() }}><label>Source<select value={provider} onChange={event => setProvider(event.target.value)}>{!providers.length ? <option value={provider}>{providersLoaded ? 'Sources unavailable' : 'Loading sources…'}</option> : null}{providers.map(item => <option key={item.id} value={item.id}>{providerLabel(item.id, item.name)}</option>)}</select></label><label>From<input type="date" required value={window.start} onChange={event => setWindow({ ...window, start: event.target.value })} /></label><label>Through<input type="date" required min={window.start} value={window.end} onChange={event => setWindow({ ...window, end: event.target.value })} /></label><button type="submit" className="primary-button" disabled={busy || !allowNetwork || multipart || field.geometry.kind === 'none'}>{busy ? 'Searching…' : 'Find scenes'}</button></form>
    <div className="farm-date-presets">{[30, 90, 180].map(days => <button type="button" key={days} onClick={() => setWindow(dates(days))}>Last {days} days</button>)}</div>
    {multipart ? <p role="status">This multipart boundary is preserved. The current image processors accept a single polygon (including holes); they cannot analyze multiple parts as one field.</p> : null}
    {!allowNetwork ? <p role="status">Offline: scene discovery needs a connection. Retained analyses remain available through local storage.</p> : field.geometry.kind === 'none' ? <p role="status">Add and save a location before searching imagery.</p> : status ? <p role="status">{status}</p> : null}
    {error ? <p role="alert" className="farm-error">{error}</p> : null}
    <div className="farm-scene-list">{scenes.map(item => <button type="button" key={item.id} aria-pressed={scene?.id === item.id} onClick={() => { setScene(item); setSelectedJob(null) }}><strong>{item.acquired_at ? new Date(item.acquired_at).toLocaleDateString() : 'Date unknown'}</strong><span>Scene cloud: {item.scene_cloud_percent == null ? 'Unknown' : `${item.scene_cloud_percent}%`}</span><small>{item.collection} · {item.id}</small><span>{scene?.id === item.id ? 'Selected' : 'Review scene'}</span></button>)}</div>
    {scenes.length === 10 ? <p>The search reached its result limit. Narrow the date window to inspect other dates; this list is not exhaustive or a best-image ranking.</p> : null}
    {scene && !selectedJob ? <div className="farm-scene-review"><h3>Selected scene · {scene.acquired_at?.slice(0, 10) || 'Unknown date'}</h3><p>{scene.id}</p>{supported ? <FieldImageryAnalyticsPanel key={`${provider}:${scene.id}:${field.geometry_revision_id}`} fieldContextId={field.id} geometry={field.geometry} geometryKey={field.geometry_revision_id} imageryReady={field.geometry.kind !== 'none'} embedded onJobChanged={() => setHistoryVersion(v => v + 1)} selection={{ providerId: provider, sceneId: scene.id, startDate: window.start, endDate: window.end }} /> : <p>This provider supports discovery here. Its processing integration is not yet available in this runtime.</p>}<button type="button" onClick={() => onAsk(`I am reviewing ${provider} scene ${scene.id}, acquired ${scene.acquired_at}. What should I check about its coverage and quality before interpreting it? Scene metadata alone is not processed field evidence.`)}>Ask about this scene</button></div> : null}
    <section className="farm-imagery-history" aria-label="Image analysis history"><h3>Image history</h3>{jobs === null ? <p role="status">{historyFailed ? 'Image history unavailable' : 'Loading image history…'}</p> : !jobs.length ? <p>No saved analyses</p> : <><div className="farm-scene-list">{jobs.map(job => <button type="button" key={job.id} aria-pressed={selectedJob?.id === job.id} onClick={() => { setSelectedJob(job); setScene(null) }}><strong>{job.result?.source?.acquired_at?.slice(0, 10) || `${job.request.start_date} – ${job.request.end_date}`}</strong><span>{job.status.replace(/_/g, ' ')} · {job.current_geometry ? 'Current boundary' : 'Historical boundary'}</span><small>{providerLabel(job.request.provider_id, providers.find(item => item.id === job.request.provider_id)?.name || job.request.provider_id)}</small></button>)}</div></>}</section>
    {selectedJob ? <section><h3>Analysis</h3>{['completed', 'superseded'].includes(selectedJob.status) ? <div className="farm-actions"><button type="button" disabled={linking} onClick={() => void linkAnalysis(false)}>Save to records</button><button type="button" disabled={linking} onClick={() => void linkAnalysis(true)}>Ask about this analysis</button></div> : null}{recordStatus ? <p role="status">{recordStatus}</p> : null}{!selectedJob.current_geometry ? <p role="status">Historical boundary: this analysis is retained for its original geometry and does not describe the current boundary.</p> : null}<FieldImageryAnalyticsPanel key={selectedJob.id} fieldContextId={field.id} geometry={importedFieldGeometry(selectedJob.geometry)} geometryKey={selectedJob.geometry_revision_id} imageryReady={selectedJob.current_geometry} embedded retainedJobId={selectedJob.id} onJobChanged={() => setHistoryVersion(v => v + 1)} selection={{ providerId: selectedJob.request.provider_id, sceneId: selectedJob.request.scene_id || '', startDate: selectedJob.request.start_date, endDate: selectedJob.request.end_date, samplingMode: selectedJob.request.sampling_mode, sampleRadiusM: selectedJob.request.sample_radius_m }} /></section> : null}
    <details><summary>Source and interpretation limits</summary><p>History shows up to 30 jobs, each tied to its saved boundary revision.</p><p>{providers.find(item => item.id === provider)?.name}</p><p>{providers.find(item => item.id === provider)?.source}</p><p>{providers.find(item => item.id === provider)?.limitations}</p><p>A failed process does not indicate crop stress. Valid pixels do not establish representative crop conditions or a management recommendation.</p></details>
  </section>
}
