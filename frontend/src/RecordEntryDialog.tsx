import { useEffect, useRef, useState } from 'react'
import { ApiError, apiPost } from './api'
import { WorkspaceDialog } from './WorkspaceDialog'
import { readableError } from './farmTypes'
import { measurementLabel, soilMeasurements } from './fieldLabels'
import { recordLabel, type SavedRecord } from './RecordDetails'

type Analyte = { custom?: boolean; metric: string; value: string; unit: string; method: string }
type Draft = { kind: string; summary: string; occurred: string; sample: string; lab: string; depthTop: string; depthBottom: string; depthUnit: string; scope: string; analytes: Analyte[]; correction: string; operation: string; group: string; signature: string }
const blank = (): Draft => ({ kind: 'observation', summary: '', occurred: '', sample: '', lab: '', depthTop: '', depthBottom: '', depthUnit: 'cm', scope: 'composite', analytes: [{ metric: '', value: '', unit: '', method: '' }], correction: '', operation: crypto.randomUUID(), group: crypto.randomUUID(), signature: '' })
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
function validDraft(value: unknown, correction: string): value is Draft {
  if (!value || typeof value !== 'object') return false
  const draft = value as Draft
  return ['kind', 'summary', 'occurred', 'sample', 'lab', 'depthTop', 'depthBottom', 'depthUnit', 'scope', 'correction', 'operation', 'group', 'signature'].every(key => typeof draft[key as keyof Draft] === 'string')
    && draft.correction === correction && uuid.test(draft.operation)
    && Array.isArray(draft.analytes) && draft.analytes.length > 0 && draft.analytes.length <= 50
    && draft.analytes.every(row => row && ['metric', 'value', 'unit', 'method'].every(key => typeof row[key as keyof Analyte] === 'string'))
}

const recordDraftKey = (fieldId: string, season: number, correction: string) => `open-agronomy.record-draft.${fieldId}.${season}${correction ? `.correction.${correction}` : ''}`
export function hasUnconfirmedRecordDraft(fieldId: string, season: number, correction: string): boolean {
  try {
    const raw = localStorage.getItem(recordDraftKey(fieldId, season, correction))
    if (raw === null) return false
    try { const saved: unknown = JSON.parse(raw); return !validDraft(saved, correction) || Boolean(saved.signature) }
    catch { return true }
  } catch { return false }
}

function correctionDraft(event: SavedRecord): Draft {
    const measurement = event.payload.measurement as Record<string, unknown> | undefined
    const next = { ...blank(), summary: recordLabel(event), correction: event.id, occurred: (event.provenance.sampling_time_status === 'unknown' || event.provenance.observation_time_status === 'unknown') ? '' : new Date(new Date(event.occurred_at).getTime() - new Date(event.occurred_at).getTimezoneOffset() * 60000).toISOString().slice(0, 16), kind: measurement ? 'sample' : event.event_type === 'correction' ? 'observation' : event.event_type }
    if (measurement) {
      const depth = measurement.sample_depth as { top: number; bottom: number; unit: string }
      Object.assign(next, { sample: String(measurement.sample_id), lab: String(measurement.lab_name || ''), depthTop: String(depth.top), depthBottom: String(depth.bottom), depthUnit: depth.unit, scope: String(measurement.spatial_scope), analytes: [{ metric: String(measurement.metric), value: String(measurement.value), unit: String(measurement.unit), method: String(measurement.method) }] })
    }
    return next
  }

function draftEvents(draft: Draft, season: number) {
      if (draft.kind !== 'sample' && !draft.summary.trim()) throw new Error('Enter a record before saving.')
      const common = { ...(draft.occurred ? { occurred_at: new Date(draft.occurred).toISOString() } : {}), provenance: { capture_method: draft.kind === 'sample' ? 'user_transcribed_lab_report' : 'grower_entry', original_report_retained: false, ...(draft.kind === 'sample' ? { sampling_time_status: draft.occurred ? 'user_supplied' : 'unknown' } : { observation_time_status: draft.occurred ? 'user_supplied' : 'unknown' }), ...(draft.kind === 'sample' && draft.occurred ? { sampled_at: new Date(draft.occurred).toISOString() } : {}) } }
      return draft.kind === 'sample' ? draft.analytes.map(analyte => {
        if (!analyte.value.trim() || !Number.isFinite(Number(analyte.value))) throw new Error('Enter a numeric value for every measurement; blank is not zero.')
        if (!draft.depthTop.trim() || !draft.depthBottom.trim()) throw new Error('Enter the sample depth; unknown depth cannot become zero.')
        if (Number(draft.depthBottom) <= Number(draft.depthTop)) throw new Error('The bottom of the sample must be deeper than the top.')
        return { ...common, event_type: draft.correction ? 'correction' : 'sample', ...(draft.correction ? { corrects_event_id: draft.correction } : {}), payload: { season, report_group: draft.group || draft.operation, summary: draft.summary || `${draft.sample}: ${analyte.metric} ${analyte.value} ${analyte.unit}`, measurement: { schema_version: 'open_agronomy_agent.field_measurement.v1', kind: 'soil_test', sample_id: draft.sample, metric: analyte.metric.trim().toLowerCase(), value: Number(analyte.value), unit: analyte.unit, method: analyte.method, sample_depth: { top: Number(draft.depthTop), bottom: Number(draft.depthBottom), unit: draft.depthUnit }, spatial_scope: draft.scope, source_quality: 'user_transcribed_lab_report', ...(draft.lab.trim() ? { lab_name: draft.lab } : {}) } } }
      }) : [{ ...common, event_type: draft.correction ? 'correction' : draft.kind, ...(draft.correction ? { corrects_event_id: draft.correction } : {}), payload: { season, summary: draft.summary.trim() } }]
}

// JSON objects may arrive in a different key order. Array order remains meaningful.
function sameJSON(left: unknown, right: unknown): boolean {
  if (left === right) return true
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false
  if (Array.isArray(left) !== Array.isArray(right)) return false
  const a = Object.keys(left), b = Object.keys(right)
  return a.length === b.length && a.every(key => Object.prototype.hasOwnProperty.call(right, key) && sameJSON((left as Record<string, unknown>)[key], (right as Record<string, unknown>)[key]))
}
function confirmedEvents(reply: unknown, events: ReturnType<typeof draftEvents>, fieldId: string): SavedRecord[] {
  const ack = reply as { status?: string; events?: SavedRecord[] } | null
  if (!ack || !['saved', 'already_saved'].includes(ack.status || '') || !Array.isArray(ack.events)
      || ack.events.length !== events.length || new Set(ack.events.map(event => event?.id)).size !== events.length
      || !ack.events.every((event, i) => event && typeof event.id === 'string' && uuid.test(event.id) && event.id !== event.corrects_event_id
        && event.field_context_id === fieldId && event.event_type === events[i].event_type
        && (event.corrects_event_id || '') === ('corrects_event_id' in events[i] ? events[i].corrects_event_id : '')
        && sameJSON(event.payload, events[i].payload) && sameJSON(event.provenance, events[i].provenance)
        && (!events[i].occurred_at || Date.parse(event.occurred_at) === Date.parse(events[i].occurred_at!)))) {
    throw new Error('The save confirmation could not be verified. Keep this draft and retry the saved request.')
  }
  return ack.events
}

export default function RecordEntryDialog({ fieldId, fieldName, season, initialRecord, recoveryOnly = false, onClose, onSaved }: {
  fieldId: string; fieldName?: string; season: number; initialRecord?: SavedRecord; recoveryOnly?: boolean
  onClose: () => void; onSaved: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [storageError, setStorageError] = useState(false)
  const keyFor = (correction: string) => recordDraftKey(fieldId, season, correction)
  const [initial] = useState(() => {
    const key = keyFor(initialRecord?.id || '')
    let raw: string | null = null
    try { raw = localStorage.getItem(key) } catch { /* Persistence below blocks dispatch if storage is unavailable. */ }
    let saved: unknown = null
    try { saved = JSON.parse(raw || 'null') } catch { /* Invalid draft shapes cannot be used as requests. */ }
    const valid = validDraft(saved, initialRecord?.id || '')
    const draft = valid ? saved as Draft : initialRecord ? correctionDraft(initialRecord) : blank()
    return { draft, key, raw, invalid: (raw !== null && !valid) || (recoveryOnly && (!valid || !(saved as Draft).signature)) }
  })
  const [draft, setDraft] = useState<Draft>(initial.draft)
  const stored = useRef({ key: initial.key, raw: initial.raw })
  const mounted = useRef(true)
  const locked = busy || initial.invalid || Boolean(draft.signature)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const assertStored = () => {
    if (localStorage.getItem(stored.current.key) !== stored.current.raw) throw new Error('This draft changed in another window. Close and reopen it before saving; this window has not replaced that version.')
  }
  const persist = (next: Draft) => {
    assertStored()
    const key = keyFor(next.correction), raw = JSON.stringify(next)
    if (key !== stored.current.key) {
      if (localStorage.getItem(key) !== null) throw new Error('A draft for the confirmed correction already exists. Both drafts have been kept; close this form and review them before continuing.')
      // Reserve the new draft before removing the old one. A failure keeps the old attempt recoverable.
      localStorage.setItem(key, raw)
      try { assertStored(); localStorage.removeItem(stored.current.key) }
      catch { throw new Error('The later draft was copied to the confirmed record, but the earlier draft could not be cleared safely. Both stored versions have been kept. Close and reload the timeline, then correct the confirmed record to resume your later draft.') }
    } else localStorage.setItem(key, raw)
    stored.current = { key, raw }
    setStorageError(false)
  }
  useEffect(() => { if (initial.invalid) return; try { persist(draft) } catch { setStorageError(true) } }, [draft]) // Only this form's expected stored version may be replaced.
  const change = (patch: Partial<Draft>) => { if (!locked) setDraft(current => ({ ...current, ...patch })) }
  const save = async () => {
    if (!fieldId || busy || initial.invalid) return
    setBusy(true); setError('')
    const wasUncertain = Boolean(draft.signature)
    let dispatched = false
    try {
      const events: ReturnType<typeof draftEvents> = draft.signature ? JSON.parse(draft.signature) : draftEvents(draft, season)
      if (!Array.isArray(events) || events.length < 1 || events.length > 50) throw new Error('The saved request is unreadable. Keep this draft and review the field timeline before continuing.')
      const attempt = { ...draft, signature: draft.signature || JSON.stringify(events) }
      // Capture exact JSON and UUID before dispatch. Reopening never rebuilds an uncertain payload.
      persist(attempt); setDraft(attempt)
      dispatched = true
      const reply = await apiPost(`/api/fields/${encodeURIComponent(fieldId)}/records`, { operation_id: attempt.operation, events })
      const saved = confirmedEvents(reply, events, fieldId)
      if (!mounted.current) return
      let newer = false
      try { newer = !sameJSON(draftEvents(draft, season), events) } catch { newer = true }
      if (newer) {
        // Earlier app versions allowed edits after dispatch. Recover the old save first, then retain those edits.
        if (draft.correction && saved.length !== 1) throw new Error('The earlier save was confirmed, but its correction is ambiguous. Both the captured request and your edits have been kept for review.')
        const next = { ...draft, signature: '', operation: crypto.randomUUID(), group: crypto.randomUUID(), correction: draft.correction ? saved[0].id : '' }
        persist(next); setDraft(next); onSaved()
        setError('The earlier save was confirmed. Your later edits are kept below for a new explicit save.')
      } else {
        assertStored(); localStorage.removeItem(stored.current.key)
        stored.current.raw = null
        onSaved(); onClose()
      }
    } catch (cause) {
      if (mounted.current) {
        // Only a definite first 422 proves this attempt never reached the atomic append handler.
        if (dispatched && !wasUncertain && cause instanceof ApiError && cause.status === 422) {
          const next = { ...draft, signature: '', operation: crypto.randomUUID() }
          try { persist(next); setDraft(next) } catch { setStorageError(true) }
        }
        setError(readableError(cause))
      }
    } finally { if (mounted.current) setBusy(false) }
  }
  const updateAnalyte = (index: number, key: keyof Analyte, value: string) => change({ analytes: draft.analytes.map((row, i) => i === index ? { ...row, [key]: value } : row) })
  return <WorkspaceDialog title={draft.correction ? 'Correct field record' : 'Add record'} busy={busy} wide onClose={() => { if (!busy) onClose() }}><form className="farm-form" onSubmit={event => { event.preventDefault(); void save() }}>
      <p>{fieldName ? `${fieldName} · ` : ''}{season} season{storageError ? ' · Draft is only kept in this window' : ' · Draft saved on this device'}</p>
      {!draft.correction ? <label>Record type<select disabled={locked} value={draft.kind} onChange={event => change({ kind: event.target.value })}><option value="observation">Observation</option><option value="operation">Operation</option><option value="note">Note</option><option value="sample">Soil sample / report</option><option value="outcome">Outcome</option></select></label> : <p>The original record will remain available.</p>}
      <label>{draft.kind === 'sample' ? 'Sampled at (leave blank if unknown)' : 'Observed at (leave blank if unknown)'}<input disabled={locked} type="datetime-local" value={draft.occurred} onChange={event => change({ occurred: event.target.value })} /></label>
      <label>{draft.kind === 'sample' ? 'Report note (optional)' : 'What did you observe or do?'}<textarea disabled={locked} required={draft.kind !== 'sample'} data-dialog-initial-focus value={draft.summary} onChange={event => change({ summary: event.target.value })} maxLength={6000} /></label>
      {draft.kind === 'sample' ? <><div className="farm-form-grid"><label>Sample ID<input disabled={locked} value={draft.sample} onChange={event => change({ sample: event.target.value })} required maxLength={128} /></label><label>Lab (optional)<input disabled={locked} value={draft.lab} onChange={event => change({ lab: event.target.value })} maxLength={160} /></label><label>Depth from<input disabled={locked} type="number" min="0" step="any" value={draft.depthTop} onChange={event => change({ depthTop: event.target.value })} required /></label><label>Depth to<input disabled={locked} type="number" min="0" step="any" value={draft.depthBottom} onChange={event => change({ depthBottom: event.target.value })} required /></label><label>Depth unit<select disabled={locked} value={draft.depthUnit} onChange={event => change({ depthUnit: event.target.value })}><option>cm</option><option>in</option></select></label><label>Sample scope<select disabled={locked} value={draft.scope} onChange={event => change({ scope: event.target.value })}>{['point', 'zone', 'composite', 'field'].map(value => <option key={value} value={value}>{({point: 'Single point', zone: 'Management zone', composite: 'Composite sample', field: 'Whole field'})[value]}</option>)}</select></label></div>
        <p>Enter values exactly as reported. Method, units and sample depth are required. This form records a transcription; keep the original lab report with your field records.</p>
        {draft.analytes.map((analyte, index) => <fieldset key={index} className="farm-analyte"><legend>Measurement {index + 1}</legend>{(['metric', 'value', 'unit', 'method'] as const).map(key => <label key={key}>{key === 'metric' ? 'Measurement' : key === 'value' ? 'Value' : key === 'unit' ? 'Unit' : 'Lab method'}{key === 'metric' ? <><select disabled={locked} aria-label={`Measurement ${index + 1}`} required value={analyte.custom ? "custom" : analyte.metric} onChange={event => change({ analytes: draft.analytes.map((row, i) => i === index ? { ...row, custom: event.target.value === "custom", metric: event.target.value === "custom" ? "" : event.target.value } : row) })}><option value="">Choose a measurement</option>{soilMeasurements.map(([id, label]) => <option key={id} value={id}>{label}</option>)}{analyte.metric && !soilMeasurements.some(([id]) => id === analyte.metric) ? <option value={analyte.metric}>{measurementLabel(analyte.metric)}</option> : null}<option value="custom">Other measurement</option></select>{analyte.custom ? <input disabled={locked} aria-label={`Measurement ${index + 1} identifier`} placeholder="e.g. zinc" required pattern="[a-z0-9][a-z0-9_.\x2d]*" maxLength={64} value={analyte.metric} onChange={event => updateAnalyte(index, key, event.target.value)} /> : null}</> : <input disabled={locked} aria-label={`Measurement ${index + 1} ${key}`} required inputMode={key === 'value' ? 'decimal' : undefined} value={analyte[key]} onChange={event => updateAnalyte(index, key, event.target.value)} />}</label>)}{draft.analytes.length > 1 ? <button type="button" disabled={locked} onClick={() => change({ analytes: draft.analytes.filter((_, i) => i !== index) })}>Remove measurement</button> : null}</fieldset>)}
        {!draft.correction ? <button type="button" disabled={locked || draft.analytes.length >= 50} onClick={() => change({ analytes: [...draft.analytes, { metric: '', value: '', unit: '', method: '' }] })}>Add measurement</button> : null}
      </> : null}
      {initial.invalid ? <p role="alert">The saved draft is unreadable. Its original bytes have been kept on this device. Close this form and review recovery with your workspace administrator before starting another record.</p> : null}
      {draft.signature && !busy ? <p>The save outcome is unconfirmed. Retry the captured request before editing or starting another record. Closing keeps this request on this device.</p> : null}
      {error ? <p role="alert">{error}</p> : null}<footer><button type="button" disabled={locked} onClick={() => { try { assertStored(); localStorage.removeItem(stored.current.key); onClose() } catch { setError('The draft could not be removed from this device. Try again before closing.') } }}>Discard draft</button><button type="submit" className="primary-button" disabled={busy || initial.invalid}>{initial.invalid ? 'Recovery unavailable' : busy ? 'Saving…' : draft.signature ? 'Retry saved request' : 'Save record'}</button></footer>
    </form></WorkspaceDialog>
}
