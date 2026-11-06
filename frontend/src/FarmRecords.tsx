import { useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from './api'
import { WorkspaceDialog } from './WorkspaceDialog'
import { readableError, type FarmField } from './farmTypes'
import { FieldSyncPanel } from './FieldSyncPanel'

type SavedRecord = { id: string; field_context_id: string; field_name: string; event_type: string; occurred_at: string; recorded_at: string; payload: Record<string, unknown>; provenance: Record<string, unknown>; corrects_event_id?: string; corrected_by?: string; season_binding: string }
type Records = { events: SavedRecord[]; total: number; next_offset: number | null }
type Analyte = { metric: string; value: string; unit: string; method: string }
type Draft = { kind: string; summary: string; occurred: string; sample: string; lab: string; depthTop: string; depthBottom: string; depthUnit: string; scope: string; analytes: Analyte[]; correction: string; operation: string; group: string; signature: string }
const blank = (): Draft => ({ kind: 'observation', summary: '', occurred: '', sample: '', lab: '', depthTop: '', depthBottom: '', depthUnit: 'cm', scope: 'composite', analytes: [{ metric: '', value: '', unit: '', method: '' }], correction: '', operation: crypto.randomUUID(), group: crypto.randomUUID(), signature: '' })
const recordLabel = (event: SavedRecord) => typeof event.payload.summary === 'string' ? event.payload.summary : typeof event.payload.note === 'string' ? event.payload.note : event.event_type.replace(/_/g, ' ')

export default function FarmRecords({ fields = [], fieldId, farmId, season, onOpenField, onChanged }: {
  fields?: FarmField[]; fieldId?: string; farmId?: string; season: number; onOpenField?: (id: string) => void; onChanged?: () => void
}) {
  const [records, setRecords] = useState<Records | null>(null)
  const [offset, setOffset] = useState(0)
  const [kindFilter, setKindFilter] = useState('all')
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const draftKey = `open-agronomy.record-draft.${fieldId || 'none'}.${season}`
  const [draft, setDraft] = useState<Draft>(() => { try { return JSON.parse(localStorage.getItem(draftKey) || 'null') || blank() } catch { return blank() } })
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { try { localStorage.setItem(draftKey, JSON.stringify(draft)) } catch { /* retain in memory */ } }, [draftKey, draft])
  useEffect(() => {
    let current = true
    const query = new URLSearchParams({ season: String(season), offset: String(offset) })
    if (fieldId) query.set('field_id', fieldId)
    if (farmId) query.set('farm_id', farmId)
    apiGet<Records>(`/api/records?${query}`).then(value => { if (current) { setRecords(value); setLoadError('') } }).catch(cause => { if (current) setLoadError(readableError(cause)) })
    return () => { current = false }
  }, [fieldId, farmId, season, refresh, offset])
  const change = (patch: Partial<Draft>) => setDraft(current => ({ ...current, ...patch }))
  const save = async () => {
    if (!fieldId || busy) return
    setBusy(true); setError('')
    try {
      if (draft.kind !== 'sample' && !draft.summary.trim()) throw new Error('Enter a record before saving.')
      const common = { ...(draft.occurred ? { occurred_at: new Date(draft.occurred).toISOString() } : {}), provenance: { capture_method: draft.kind === 'sample' ? 'user_transcribed_lab_report' : 'grower_entry', original_report_retained: false, ...(draft.kind === 'sample' ? { sampling_time_status: draft.occurred ? 'user_supplied' : 'unknown' } : { observation_time_status: draft.occurred ? 'user_supplied' : 'unknown' }), ...(draft.kind === 'sample' && draft.occurred ? { sampled_at: new Date(draft.occurred).toISOString() } : {}) } }
      const events = draft.kind === 'sample' ? draft.analytes.map(analyte => {
        if (!analyte.value.trim() || !Number.isFinite(Number(analyte.value))) throw new Error('Enter a numeric value for every analyte; blank is not zero.')
        if (!draft.depthTop.trim() || !draft.depthBottom.trim()) throw new Error('Enter the sample depth; unknown depth cannot become zero.')
        return { ...common, event_type: draft.correction ? 'correction' : 'sample', ...(draft.correction ? { corrects_event_id: draft.correction } : {}), payload: { season, report_group: draft.group || draft.operation, summary: draft.summary || `${draft.sample}: ${analyte.metric} ${analyte.value} ${analyte.unit}`, measurement: { schema_version: 'open_agronomy_agent.field_measurement.v1', kind: 'soil_test', sample_id: draft.sample, metric: analyte.metric.trim().toLowerCase(), value: Number(analyte.value), unit: analyte.unit, method: analyte.method, sample_depth: { top: Number(draft.depthTop), bottom: Number(draft.depthBottom), unit: draft.depthUnit }, spatial_scope: draft.scope, source_quality: 'user_transcribed_lab_report', ...(draft.lab.trim() ? { lab_name: draft.lab } : {}) } } }
      }) : [{ ...common, event_type: draft.correction ? 'correction' : draft.kind, ...(draft.correction ? { corrects_event_id: draft.correction } : {}), payload: { season, summary: draft.summary.trim() } }]
      const signature = JSON.stringify(events)
      const operation = draft.signature && draft.signature !== signature ? crypto.randomUUID() : draft.operation
      // Persist the exact retry identity before the request, including across reloads.
      const attempt = { ...draft, operation, signature }
      setDraft(attempt); localStorage.setItem(draftKey, JSON.stringify(attempt))
      await apiPost(`/api/fields/${encodeURIComponent(fieldId)}/records`, { operation_id: operation, events })
      if (!mounted.current) return
      setDraft(blank()); setOpen(false); setRefresh(value => value + 1); setOffset(0); onChanged?.()
    } catch (cause) { if (mounted.current) setError(readableError(cause)) } finally { if (mounted.current) setBusy(false) }
  }
  const correct = (event: SavedRecord) => {
    const measurement = event.payload.measurement as Record<string, unknown> | undefined
    const next = { ...blank(), summary: recordLabel(event), correction: event.id, occurred: (event.provenance.sampling_time_status === 'unknown' || event.provenance.observation_time_status === 'unknown') ? '' : new Date(new Date(event.occurred_at).getTime() - new Date(event.occurred_at).getTimezoneOffset() * 60000).toISOString().slice(0, 16), kind: measurement ? 'sample' : 'observation' }
    if (measurement) {
      const depth = measurement.sample_depth as { top: number; bottom: number; unit: string }
      Object.assign(next, { sample: String(measurement.sample_id), lab: String(measurement.lab_name || ''), depthTop: String(depth.top), depthBottom: String(depth.bottom), depthUnit: depth.unit, scope: String(measurement.spatial_scope), analytes: [{ metric: String(measurement.metric), value: String(measurement.value), unit: String(measurement.unit), method: String(measurement.method) }] })
    }
    setDraft(next); setOpen(true)
  }
  const visible = (records?.events || []).filter(event => kindFilter === 'all' || event.event_type === kindFilter)
  return <section className="farm-records" aria-label="Records">
    <div className="farm-section-heading"><div><h2>{fieldId ? 'Field records' : 'Farm records'}</h2><p>{season} · {records?.total ?? 'Loading'} saved records. Corrections retain the original.</p></div>{fieldId ? <button type="button" className="primary-button" onClick={() => setOpen(true)}>Add to field</button> : null}</div>
    {loadError ? <p role="alert" className="farm-error">{loadError}<button type="button" onClick={() => setRefresh(v => v + 1)}>Refresh records</button></p> : null}
    <label className="farm-record-filter">Record type<select value={kindFilter} onChange={event => setKindFilter(event.target.value)}><option value="all">All records on this page</option>{['observation', 'sample', 'operation', 'note', 'decision', 'outcome', 'correction'].map(kind => <option key={kind} value={kind}>{kind}</option>)}</select></label>
    {!records ? <p role="status">Loading records…</p> : !visible.length ? <p>No matching records for this season.{!fieldId && fields.length ? ' Open a field to add an observation or soil report.' : ''}</p> : <ol className="farm-record-list">{visible.map(event => <li key={event.id} className={event.corrected_by ? 'record-superseded' : ''}>
      <div className="farm-record-meta"><span>{event.event_type}</span><time dateTime={(event.provenance.sampling_time_status === 'unknown' || event.provenance.observation_time_status === 'unknown') ? event.recorded_at : event.occurred_at}>{(event.provenance.sampling_time_status === 'unknown' || event.provenance.observation_time_status === 'unknown') ? 'Recorded ' : ''}{new Date((event.provenance.sampling_time_status === 'unknown' || event.provenance.observation_time_status === 'unknown') ? event.recorded_at : event.occurred_at).toLocaleString()}</time>{event.corrected_by ? <strong>Corrected</strong> : null}</div>
      {!fieldId ? <button type="button" className="field-open" onClick={() => onOpenField?.(event.field_context_id)}>{event.field_name}</button> : null}<p>{recordLabel(event)}</p>
      {event.payload.measurement ? <p>{String((event.payload.measurement as Record<string, unknown>).metric)}: {String((event.payload.measurement as Record<string, unknown>).value)} {String((event.payload.measurement as Record<string, unknown>).unit)}</p> : null}
      {event.corrects_event_id ? <small>Correction of record {event.corrects_event_id.slice(0, 8)}</small> : null}
      <details><summary>Source & record details</summary><p>{event.season_binding === 'explicit' ? `Assigned to season ${season}` : event.season_binding === 'observation_year' ? 'Shown by observation year; season was not explicitly supplied.' : 'Season and observation date are unknown.'}</p><pre>{JSON.stringify({ payload: event.payload, provenance: event.provenance }, null, 2)}</pre></details>
      {fieldId && !event.corrected_by ? <button type="button" onClick={() => correct(event)}>Correct record</button> : null}
    </li>)}</ol>}
    <div className="farm-pagination">{offset > 0 ? <button type="button" onClick={() => setOffset(Math.max(0, offset - 100))}>Previous records</button> : null}{records?.next_offset != null ? <button type="button" onClick={() => setOffset(records.next_offset!)}>Next records</button> : null}</div>
    {fieldId ? <FieldSyncPanel fieldContextId={fieldId} onImported={() => { setRefresh(v => v + 1); onChanged?.() }} /> : null}
    {open && fieldId ? <WorkspaceDialog title={draft.correction ? 'Correct field record' : 'Add to field'} busy={busy} wide onClose={() => { if (!busy) setOpen(false) }}><form className="farm-form" onSubmit={event => { event.preventDefault(); void save() }}>
      <p>Field record · {season} season. Your draft stays on this device until the save is acknowledged.</p>
      {!draft.correction ? <label>Record type<select value={draft.kind} onChange={event => change({ kind: event.target.value })}><option value="observation">Observation</option><option value="operation">Operation</option><option value="note">Note</option><option value="sample">Soil sample / report</option><option value="outcome">Outcome</option></select></label> : <p>The original record will remain available.</p>}
      <label>{draft.kind === 'sample' ? 'Sampled at (leave blank if unknown)' : 'Observed at (leave blank if unknown)'}<input type="datetime-local" value={draft.occurred} onChange={event => change({ occurred: event.target.value })} /></label>
      <label>{draft.kind === 'sample' ? 'Report note (optional)' : 'What did you observe or do?'}<textarea required={draft.kind !== 'sample'} data-dialog-initial-focus value={draft.summary} onChange={event => change({ summary: event.target.value })} maxLength={6000} /></label>
      {draft.kind === 'sample' ? <><div className="farm-form-grid"><label>Sample ID<input value={draft.sample} onChange={event => change({ sample: event.target.value })} required maxLength={128} /></label><label>Lab (optional)<input value={draft.lab} onChange={event => change({ lab: event.target.value })} maxLength={160} /></label><label>Depth from<input type="number" min="0" step="any" value={draft.depthTop} onChange={event => change({ depthTop: event.target.value })} required /></label><label>Depth to<input type="number" min="0" step="any" value={draft.depthBottom} onChange={event => change({ depthBottom: event.target.value })} required /></label><label>Depth unit<select value={draft.depthUnit} onChange={event => change({ depthUnit: event.target.value })}><option>cm</option><option>in</option></select></label><label>Sample scope<select value={draft.scope} onChange={event => change({ scope: event.target.value })}>{['point', 'zone', 'composite', 'field'].map(value => <option key={value}>{value}</option>)}</select></label></div>
        <p>Enter values exactly as reported. Method, units and sample depth are required. This form records a transcription; attach the original through field table intake when available.</p>
        {draft.analytes.map((analyte, index) => <fieldset key={index} className="farm-analyte"><legend>Analyte {index + 1}</legend>{(['metric', 'value', 'unit', 'method'] as const).map(key => <label key={key}>{key === 'metric' ? 'Metric (for example, soil_ph)' : key}<input aria-label={`Analyte ${index + 1} ${key}`} required value={analyte[key]} onChange={event => change({ analytes: draft.analytes.map((row, i) => i === index ? { ...row, [key]: event.target.value } : row) })} /></label>)}{draft.analytes.length > 1 ? <button type="button" onClick={() => change({ analytes: draft.analytes.filter((_, i) => i !== index) })}>Remove analyte</button> : null}</fieldset>)}
        {!draft.correction ? <button type="button" disabled={draft.analytes.length >= 50} onClick={() => change({ analytes: [...draft.analytes, { metric: '', value: '', unit: '', method: '' }] })}>Add analyte</button> : null}
      </> : null}
      {error ? <p role="alert">{error}</p> : null}<footer><button type="button" disabled={busy} onClick={() => { setDraft(blank()); setOpen(false) }}>Discard draft</button><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Saving…' : 'Save record'}</button></footer>
    </form></WorkspaceDialog> : null}
  </section>
}
