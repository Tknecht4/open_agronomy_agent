import { useEffect, useRef, useState } from 'react'
import { apiPost } from './api'
import { WorkspaceDialog } from './WorkspaceDialog'
import { readableError } from './farmTypes'
import { measurementLabel, soilMeasurements } from './fieldLabels'
import { recordLabel, type SavedRecord } from './RecordDetails'

type Analyte = { custom?: boolean; metric: string; value: string; unit: string; method: string }
type Draft = { kind: string; summary: string; occurred: string; sample: string; lab: string; depthTop: string; depthBottom: string; depthUnit: string; scope: string; analytes: Analyte[]; correction: string; operation: string; group: string; signature: string }
const blank = (): Draft => ({ kind: 'observation', summary: '', occurred: '', sample: '', lab: '', depthTop: '', depthBottom: '', depthUnit: 'cm', scope: 'composite', analytes: [{ metric: '', value: '', unit: '', method: '' }], correction: '', operation: crypto.randomUUID(), group: crypto.randomUUID(), signature: '' })
function correctionDraft(event: SavedRecord): Draft {
    const measurement = event.payload.measurement as Record<string, unknown> | undefined
    const next = { ...blank(), summary: recordLabel(event), correction: event.id, occurred: (event.provenance.sampling_time_status === 'unknown' || event.provenance.observation_time_status === 'unknown') ? '' : new Date(new Date(event.occurred_at).getTime() - new Date(event.occurred_at).getTimezoneOffset() * 60000).toISOString().slice(0, 16), kind: measurement ? 'sample' : event.event_type === 'correction' ? 'observation' : event.event_type }
    if (measurement) {
      const depth = measurement.sample_depth as { top: number; bottom: number; unit: string }
      Object.assign(next, { sample: String(measurement.sample_id), lab: String(measurement.lab_name || ''), depthTop: String(depth.top), depthBottom: String(depth.bottom), depthUnit: depth.unit, scope: String(measurement.spatial_scope), analytes: [{ metric: String(measurement.metric), value: String(measurement.value), unit: String(measurement.unit), method: String(measurement.method) }] })
    }
    return next
  }

export default function RecordEntryDialog({ fieldId, fieldName, season, initialRecord, onClose, onSaved }: {
  fieldId: string; fieldName?: string; season: number; initialRecord?: SavedRecord
  onClose: () => void; onSaved: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [storageError, setStorageError] = useState(false)
  const draftKey = `open-agronomy.record-draft.${fieldId}.${season}${initialRecord ? `.correction.${initialRecord.id}` : ''}`
  const [draft, setDraft] = useState<Draft>(() => { try { const saved = JSON.parse(localStorage.getItem(draftKey) || 'null'); return saved && typeof saved.summary === 'string' && Array.isArray(saved.analytes) && typeof saved.operation === 'string' && saved.correction === (initialRecord?.id || '') ? saved : initialRecord ? correctionDraft(initialRecord) : blank() } catch { return initialRecord ? correctionDraft(initialRecord) : blank() } })
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => { try { localStorage.setItem(draftKey, JSON.stringify(draft)); setStorageError(false) } catch { setStorageError(true) } }, [draftKey, draft])
  const change = (patch: Partial<Draft>) => setDraft(current => ({ ...current, ...patch }))
  const save = async () => {
    if (!fieldId || busy) return
    setBusy(true); setError('')
    try {
      if (draft.kind !== 'sample' && !draft.summary.trim()) throw new Error('Enter a record before saving.')
      const common = { ...(draft.occurred ? { occurred_at: new Date(draft.occurred).toISOString() } : {}), provenance: { capture_method: draft.kind === 'sample' ? 'user_transcribed_lab_report' : 'grower_entry', original_report_retained: false, ...(draft.kind === 'sample' ? { sampling_time_status: draft.occurred ? 'user_supplied' : 'unknown' } : { observation_time_status: draft.occurred ? 'user_supplied' : 'unknown' }), ...(draft.kind === 'sample' && draft.occurred ? { sampled_at: new Date(draft.occurred).toISOString() } : {}) } }
      const events = draft.kind === 'sample' ? draft.analytes.map(analyte => {
        if (!analyte.value.trim() || !Number.isFinite(Number(analyte.value))) throw new Error('Enter a numeric value for every measurement; blank is not zero.')
        if (!draft.depthTop.trim() || !draft.depthBottom.trim()) throw new Error('Enter the sample depth; unknown depth cannot become zero.')
        if (Number(draft.depthBottom) <= Number(draft.depthTop)) throw new Error('The bottom of the sample must be deeper than the top.')
        return { ...common, event_type: draft.correction ? 'correction' : 'sample', ...(draft.correction ? { corrects_event_id: draft.correction } : {}), payload: { season, report_group: draft.group || draft.operation, summary: draft.summary || `${draft.sample}: ${analyte.metric} ${analyte.value} ${analyte.unit}`, measurement: { schema_version: 'open_agronomy_agent.field_measurement.v1', kind: 'soil_test', sample_id: draft.sample, metric: analyte.metric.trim().toLowerCase(), value: Number(analyte.value), unit: analyte.unit, method: analyte.method, sample_depth: { top: Number(draft.depthTop), bottom: Number(draft.depthBottom), unit: draft.depthUnit }, spatial_scope: draft.scope, source_quality: 'user_transcribed_lab_report', ...(draft.lab.trim() ? { lab_name: draft.lab } : {}) } } }
      }) : [{ ...common, event_type: draft.correction ? 'correction' : draft.kind, ...(draft.correction ? { corrects_event_id: draft.correction } : {}), payload: { season, summary: draft.summary.trim() } }]
      const signature = JSON.stringify(events)
      const operation = draft.signature && draft.signature !== signature ? crypto.randomUUID() : draft.operation
      // Persist the exact retry identity before the request, including across reloads.
      const attempt = { ...draft, operation, signature }
      setDraft(attempt); localStorage.setItem(draftKey, JSON.stringify(attempt))
      await apiPost(`/api/fields/${encodeURIComponent(fieldId)}/records`, { operation_id: operation, events })
      if (!mounted.current) return
      localStorage.removeItem(draftKey); onSaved(); onClose()
    } catch (cause) { if (mounted.current) setError(readableError(cause)) } finally { if (mounted.current) setBusy(false) }
  }
  const updateAnalyte = (index: number, key: keyof Analyte, value: string) => change({ analytes: draft.analytes.map((row, i) => i === index ? { ...row, [key]: value } : row) })
  return <WorkspaceDialog title={draft.correction ? 'Correct field record' : 'Add record'} busy={busy} wide onClose={() => { if (!busy) onClose() }}><form className="farm-form" onSubmit={event => { event.preventDefault(); void save() }}>
      <p>{fieldName ? `${fieldName} · ` : ''}{season} season{storageError ? ' · Draft is only kept in this window' : ' · Draft saved on this device'}</p>
      {!draft.correction ? <label>Record type<select value={draft.kind} onChange={event => change({ kind: event.target.value })}><option value="observation">Observation</option><option value="operation">Operation</option><option value="note">Note</option><option value="sample">Soil sample / report</option><option value="outcome">Outcome</option></select></label> : <p>The original record will remain available.</p>}
      <label>{draft.kind === 'sample' ? 'Sampled at (leave blank if unknown)' : 'Observed at (leave blank if unknown)'}<input type="datetime-local" value={draft.occurred} onChange={event => change({ occurred: event.target.value })} /></label>
      <label>{draft.kind === 'sample' ? 'Report note (optional)' : 'What did you observe or do?'}<textarea required={draft.kind !== 'sample'} data-dialog-initial-focus value={draft.summary} onChange={event => change({ summary: event.target.value })} maxLength={6000} /></label>
      {draft.kind === 'sample' ? <><div className="farm-form-grid"><label>Sample ID<input value={draft.sample} onChange={event => change({ sample: event.target.value })} required maxLength={128} /></label><label>Lab (optional)<input value={draft.lab} onChange={event => change({ lab: event.target.value })} maxLength={160} /></label><label>Depth from<input type="number" min="0" step="any" value={draft.depthTop} onChange={event => change({ depthTop: event.target.value })} required /></label><label>Depth to<input type="number" min="0" step="any" value={draft.depthBottom} onChange={event => change({ depthBottom: event.target.value })} required /></label><label>Depth unit<select value={draft.depthUnit} onChange={event => change({ depthUnit: event.target.value })}><option>cm</option><option>in</option></select></label><label>Sample scope<select value={draft.scope} onChange={event => change({ scope: event.target.value })}>{['point', 'zone', 'composite', 'field'].map(value => <option key={value} value={value}>{({point: 'Single point', zone: 'Management zone', composite: 'Composite sample', field: 'Whole field'})[value]}</option>)}</select></label></div>
        <p>Enter values exactly as reported. Method, units and sample depth are required. This form records a transcription; keep the original lab report with your field records.</p>
        {draft.analytes.map((analyte, index) => <fieldset key={index} className="farm-analyte"><legend>Measurement {index + 1}</legend>{(['metric', 'value', 'unit', 'method'] as const).map(key => <label key={key}>{key === 'metric' ? 'Measurement' : key === 'value' ? 'Value' : key === 'unit' ? 'Unit' : 'Lab method'}{key === 'metric' ? <><select aria-label={`Measurement ${index + 1}`} required value={analyte.custom ? "custom" : analyte.metric} onChange={event => change({ analytes: draft.analytes.map((row, i) => i === index ? { ...row, custom: event.target.value === "custom", metric: event.target.value === "custom" ? "" : event.target.value } : row) })}><option value="">Choose a measurement</option>{soilMeasurements.map(([id, label]) => <option key={id} value={id}>{label}</option>)}{analyte.metric && !soilMeasurements.some(([id]) => id === analyte.metric) ? <option value={analyte.metric}>{measurementLabel(analyte.metric)}</option> : null}<option value="custom">Other measurement</option></select>{analyte.custom ? <input aria-label={`Measurement ${index + 1} identifier`} placeholder="e.g. zinc" required pattern="[a-z0-9][a-z0-9_.\x2d]*" maxLength={64} value={analyte.metric} onChange={event => updateAnalyte(index, key, event.target.value)} /> : null}</> : <input aria-label={`Measurement ${index + 1} ${key}`} required inputMode={key === 'value' ? 'decimal' : undefined} value={analyte[key]} onChange={event => updateAnalyte(index, key, event.target.value)} />}</label>)}{draft.analytes.length > 1 ? <button type="button" onClick={() => change({ analytes: draft.analytes.filter((_, i) => i !== index) })}>Remove measurement</button> : null}</fieldset>)}
        {!draft.correction ? <button type="button" disabled={draft.analytes.length >= 50} onClick={() => change({ analytes: [...draft.analytes, { metric: '', value: '', unit: '', method: '' }] })}>Add measurement</button> : null}
      </> : null}
      {error ? <p role="alert">{error}</p> : null}<footer><button type="button" disabled={busy} onClick={() => { try { localStorage.removeItem(draftKey); onClose() } catch { setError('The draft could not be removed from this device. Try again before closing.') } }}>Discard draft</button><button type="submit" className="primary-button" disabled={busy}>{busy ? 'Saving…' : 'Save record'}</button></footer>
    </form></WorkspaceDialog>
}
