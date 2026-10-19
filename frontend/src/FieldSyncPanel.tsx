import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { apiGet } from './api'
import { FIELD_EVENT_OPERATION_CHANGED, pendingFieldEvents, submitFieldEvent, resolveRejectedFieldEvent, legacyFieldEventWarning, canonicalFieldEvent, watchFieldEventConfirmation, type PendingFieldEvent } from './fieldEventSave'
import { WorkspaceDialog } from './WorkspaceDialog'

type SyncExport = {
  schema_version: 'open_agronomy_agent.field_event_sync.v1'
  field_context_id: string
  base_head_sha256: string | null
  head_sha256: string | null
  event_count: number
  events: Array<Record<string, unknown>>
}

type SyncResult = {
  status: 'imported' | 'already_applied'
  imported_event_count: number
  chain: { valid: boolean; head_sha256?: string | null }
}

type ConflictDetail = {
  code?: string
  message?: string
  requested_base_head_sha256?: string | null
  local_head_sha256?: string | null
  resolution?: string
}

const MAX_SYNC_FILE_BYTES = 2_000_000
const DEVICE_KEY = 'open-agronomy-agent.field-sync-device.v1'

function deviceLabel(): string {
  const existing = window.localStorage.getItem(DEVICE_KEY)
  if (existing) return existing
  const random = typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  const created = `browser-${random}`
  window.localStorage.setItem(DEVICE_KEY, created)
  return created
}

function csrfHeaders(): Record<string, string> {
  const match = document.cookie.match(/(?:^|;\s*)agronomy_csrf=([^;]+)/)
  return match ? { 'X-CSRF-Token': decodeURIComponent(match[1]) } : {}
}

function saveJson(filename: string, payload: unknown): void {
  const url = URL.createObjectURL(
    new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: 'application/json' }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function FieldSyncPanel({
  fieldContextId,
  onImported,
}: {
  fieldContextId: string
  onImported: () => void | Promise<void>
}) {
  const [status, setStatus] = useState('Export/import private records.')
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState<ConflictDetail | null>(null)

  const exportBranch = async () => {
    if (!fieldContextId) return
    setBusy(true)
    setConflict(null)
    setStatus('Preparing records.')
    try {
      const exported = await apiGet<SyncExport>(
        `/api/demo/fields/${encodeURIComponent(fieldContextId)}/events/sync`,
      )
      if (!exported.event_count) {
        setStatus('No records to export.')
        return
      }
      saveJson(
        `field-records-${fieldContextId.slice(0, 8)}-${new Date().toISOString().slice(0, 10)}.json`,
        {
          schema_version: exported.schema_version,
          source_device_id: deviceLabel(),
          base_head_sha256: exported.base_head_sha256,
          events: exported.events,
        },
      )
      setStatus(`${exported.event_count} records exported. Keep the file private.`)
    } catch (error) {
      setStatus(`Export failed: ${String((error as Error).message || error)}`)
    } finally {
      setBusy(false)
    }
  }

  const importBranch = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !fieldContextId) return
    setBusy(true)
    setConflict(null)
    setStatus('Validating field records.')
    try {
      if (file.size > MAX_SYNC_FILE_BYTES) throw new Error('File exceeds the 2 MB limit.')
      const envelope = JSON.parse(await file.text()) as Record<string, unknown>
      if (
        envelope.schema_version !== 'open_agronomy_agent.field_event_sync.v1'
        || !Array.isArray(envelope.events)
        || !envelope.events.length
      ) {
        throw new Error('This is not a non-empty Open Agronomy field-record file.')
      }
      if (envelope.events.some((item) => (
        !item
        || typeof item !== 'object'
        || (item as Record<string, unknown>).field_context_id !== fieldContextId
      ))) {
        throw new Error('The branch belongs to a different field.')
      }
      const response = await fetch(
        `/api/demo/fields/${encodeURIComponent(fieldContextId)}/events/sync`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json', ...csrfHeaders() },
          body: JSON.stringify(envelope),
        },
      )
      const payload = await response.json() as SyncResult | { detail?: ConflictDetail }
      if (!response.ok) {
        const detail = 'detail' in payload ? payload.detail || {} : {}
        if (response.status === 409 && detail.code === 'divergent_head') {
          setConflict(detail)
          setStatus('Branch conflict. No records were changed.')
          return
        }
        throw new Error(detail.message || `Import failed with status ${response.status}.`)
      }
      const result = payload as SyncResult
      setStatus(
        result.status === 'already_applied'
          ? 'Branch already applied; no duplicates added.'
          : `${result.imported_event_count} records imported with a valid chain.`,
      )
      await onImported()
    } catch (error) {
      setStatus(`Import failed: ${String((error as Error).message || error)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="workspace-disclosure field-sync-panel">
      <summary>Move field records between devices</summary>
      <p>
        Append-only records only. Answers and traces remain in backup/export. Conflicts never overwrite a branch.
      </p>
      <div className="field-history-actions">
        <button type="button" disabled={busy} onClick={() => void exportBranch()}>
          Export records
        </button>
        <label>
          Import records
          <input
            type="file"
            accept=".json,application/json"
            disabled={busy}
            onChange={(event) => void importBranch(event)}
          />
        </label>
      </div>
      <p role="status">{status}</p>
      {conflict ? (
        <div className="demo-alert" role="alert">
          <strong>Keep both files. Nothing was overwritten.</strong>
          <p>{conflict.resolution || 'Export the current branch, compare both histories, then add a note or correction.'}</p>
          <small>
            Local {conflict.local_head_sha256?.slice(0, 12) || 'empty'}
            {' · '}Incoming base {conflict.requested_base_head_sha256?.slice(0, 12) || 'empty'}
          </small>
        </div>
      ) : null}
      <small>Export device labels are descriptive, not authenticated.</small>
    </details>
  )
}

const soilMetrics = [
  ['soil_ph', 'Soil pH'],
  ['nitrate_n', 'Nitrate-N'],
  ['phosphorus', 'Phosphorus'],
  ['potassium', 'Potassium'],
  ['organic_matter', 'Organic matter'],
  ['salinity_ec', 'Salinity / EC'],
] as const

export function FieldEventRecoveryPanel({ fieldContextId, onRecovered }: {
  fieldContextId: string; onRecovered: () => void | Promise<void>
}) {
  const [requests, setRequests] = useState<PendingFieldEvent[]>([])
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const active = useRef(false)
  const fieldIdRef = useRef(fieldContextId)
  fieldIdRef.current = fieldContextId
  useEffect(() => {
    active.current = true
    setStatus('')
    setBusy(false)
    setRequests([])
    let generation = 0
    const refresh = () => {
      const current = ++generation
      setRequests([]) // Do not leave another account's requests visible during scope resolution.
      void pendingFieldEvents(fieldContextId).then(rows => {
        if (!active.current || current !== generation) return
        setRequests(rows)
        if (legacyFieldEventWarning(fieldContextId)) setStatus('Older unscoped requests are preserved. Review them manually in the original account; they cannot be replayed safely.')
      }).catch(error => {
        if (active.current && current === generation) setStatus(String((error as Error).message || error))
      })
    }
    refresh()
    window.addEventListener(FIELD_EVENT_OPERATION_CHANGED, refresh)
    window.addEventListener('storage', refresh)
    window.addEventListener('focus', refresh)
    return () => {
      active.current = false; generation++
      window.removeEventListener(FIELD_EVENT_OPERATION_CHANGED, refresh)
      window.removeEventListener('storage', refresh)
      window.removeEventListener('focus', refresh)
    }
  }, [fieldContextId])
  const retry = async (request: PendingFieldEvent) => {
    const targetFieldId = fieldContextId
    setBusy(true)
    setRequests([])
    setStatus('Checking the saved record request.')
    try {
      await submitFieldEvent(fieldContextId, request.payload, { operation: request })
      if (!active.current || fieldIdRef.current !== targetFieldId) return
      setStatus('Saved record confirmed.')
      try { await onRecovered() } catch {
        if (active.current && fieldIdRef.current === targetFieldId) setStatus('Saved record confirmed; refresh the timeline to view it.')
      }
    } catch (error) {
      if (active.current && fieldIdRef.current === targetFieldId) {
        setStatus(`Save not confirmed: ${String((error as Error).message || error)}`)
        try { const rows = await pendingFieldEvents(targetFieldId); if (active.current && fieldIdRef.current === targetFieldId) setRequests(rows) } catch { /* Keep scope errors visible without showing another account's queue. */ }
      }
    } finally { if (active.current && fieldIdRef.current === targetFieldId) setBusy(false) }
  }
  const resolve = async (request: PendingFieldEvent) => {
    const targetFieldId = fieldContextId
    setBusy(true); setRequests([])
    try {
      await resolveRejectedFieldEvent(request)
      if (active.current && fieldIdRef.current === targetFieldId) setStatus('Rejected request resolved. Review and correct the entry before starting a new save.')
    } catch (error) {
      if (active.current && fieldIdRef.current === targetFieldId) {
        setStatus(String((error as Error).message || error))
        try { const rows = await pendingFieldEvents(targetFieldId); if (active.current && fieldIdRef.current === targetFieldId) setRequests(rows) } catch { /* Preserve scope errors without exposing another account's queue. */ }
      }
    } finally { if (active.current && fieldIdRef.current === targetFieldId) setBusy(false) }
  }

  if (!requests.length && !status) return null
  return <section aria-label="Unconfirmed field records">
    {requests.length ? <><p>These record requests have no confirmed receipt on this device. Check the timeline, or retry the exact saved request.</p>
      <ul>{requests.map(request => <li key={request.operationId}>
        <span>{String((request.payload.payload as Record<string, unknown> | undefined)?.summary || 'Field record')}</span>
        {request.state === 'rejected' ? <>
          <span> Validation rejected this first attempt; no record was accepted.</span>
          <button type="button" disabled={busy} onClick={() => void resolve(request)}>Resolve rejected request</button>
        </> : <button type="button" disabled={busy} onClick={() => void retry(request)}>Retry saved record</button>}
      </li>)}</ul></> : null}
    {status ? <p role="status">{status}</p> : null}
  </section>
}

export function SoilTestEntryPanel({
  fieldContextId,
  onSaved,
}: {
  fieldContextId: string
  onSaved: () => void | Promise<void>
}) {
  const [sampleId, setSampleId] = useState('')
  const [metric, setMetric] = useState<(typeof soilMetrics)[number][0]>('soil_ph')
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('')
  const [method, setMethod] = useState('')
  const [depthTop, setDepthTop] = useState('0')
  const [depthBottom, setDepthBottom] = useState('')
  const [depthUnit, setDepthUnit] = useState<'cm' | 'in'>('cm')
  const [spatialScope, setSpatialScope] = useState('composite')
  const [sourceQuality, setSourceQuality] = useState('user_transcribed_lab_report')
  const [labName, setLabName] = useState('')
  const [occurredAt, setOccurredAt] = useState('')
  const [originalReportRetained, setOriginalReportRetained] = useState(false)
  const [saveStatus, setSaveStatus] = useState('')
  const [open, setOpen] = useState(false)
  const [pending, setPending] = useState(false)
  const pendingRef = useRef(false)
  const mountedRef = useRef(false)
  const fieldIdRef = useRef(fieldContextId)
  fieldIdRef.current = fieldContextId
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  const operationRef = useRef<PendingFieldEvent | undefined>(undefined)
  const operationDraftRef = useRef('')
  const draftRef = useRef('')
  draftRef.current = canonicalFieldEvent([sampleId, metric, value, unit, method, depthTop, depthBottom, depthUnit, spatialScope, sourceQuality, labName, occurredAt, originalReportRetained])
  useEffect(() => watchFieldEventConfirmation(() => operationRef.current, operation => {
    if (pendingRef.current) return
    operationRef.current = undefined
    if (fieldIdRef.current !== operation.scope.field_context_id) return
    const unchanged = draftRef.current === operationDraftRef.current
    if (unchanged) setValue('')
    setSaveStatus(unchanged ? 'Saved. Keep the original report if available.' : 'The previous soil result was confirmed. Review this edited entry before saving it as a new result.')
    void Promise.resolve(onSaved()).catch(() => setSaveStatus(unchanged ? 'Saved. Refresh the timeline to view it.' : 'The previous result was confirmed. Refresh the timeline; this edited entry remains unsaved.'))
  }, () => { operationRef.current = undefined; setSaveStatus('Rejected request resolved. Correct the entry before saving again.') }), [fieldContextId, onSaved])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (pendingRef.current || !fieldContextId) return
    const targetFieldId = fieldContextId
    pendingRef.current = true
    setPending(true)
    const selectedMetric = soilMetrics.find(([id]) => id === metric)
    setSaveStatus('Saving soil test. Closing this window leaves the request running; check the timeline before trying again.')
    try {
      const payload: Record<string, unknown> = {
        event_type: 'sample',
        ...(occurredAt ? { occurred_at: new Date(occurredAt).toISOString() } : {}),
        payload: {
          summary: `${selectedMetric?.[1] || metric}: ${value} ${unit} · sample ${sampleId}`,
          measurement: {
            schema_version: 'open_agronomy_agent.field_measurement.v1',
            kind: 'soil_test',
            sample_id: sampleId.trim(),
            metric,
            label: selectedMetric?.[1] || metric,
            value: Number(value),
            unit: unit.trim(),
            method: method.trim(),
            sample_depth: {
              top: Number(depthTop),
              bottom: Number(depthBottom),
              unit: depthUnit,
            },
            spatial_scope: spatialScope,
            source_quality: sourceQuality,
            ...(labName.trim() ? { lab_name: labName.trim() } : {}),
          },
        },
        provenance: {
          capture_method: sourceQuality,
          surface: 'fields_soil_test_form',
          sampling_time_status: occurredAt ? 'user_supplied' : 'unknown',
          ...(occurredAt ? { sampled_at: new Date(occurredAt).toISOString() } : {}),
          original_report_retained: originalReportRetained,
        },
      }
      const previous = operationRef.current
      await submitFieldEvent(targetFieldId, payload, {
        ...(previous?.payloadKey === canonicalFieldEvent(payload) ? { operation: previous } : {}),
        onPrepared: operation => { operationRef.current = operation; operationDraftRef.current = draftRef.current },
      })
      if (!mountedRef.current || fieldIdRef.current !== targetFieldId) return
      operationRef.current = undefined
      setValue('')
      setSaveStatus('Saved. Keep the original report if available.')
      try { await onSaved() } catch {
        setSaveStatus('Saved. Timeline refresh failed; refresh the field records before adding another result.')
      }
    } catch (error) {
      if (mountedRef.current && fieldIdRef.current === targetFieldId) {
        setSaveStatus(`Save not confirmed: ${String((error as Error).message || error)}. The server may have saved it; check the timeline before trying again.`)
      }
    } finally {
      pendingRef.current = false
      window.dispatchEvent(new Event(FIELD_EVENT_OPERATION_CHANGED))
      if (mountedRef.current && fieldIdRef.current === targetFieldId) setPending(false)
    }
  }

  return (
    <div className="soil-entry-action">
      <button type="button" className="secondary-button" onClick={() => setOpen(true)}>{pending ? 'View pending soil test' : 'Add soil test'}</button>
      {!open && saveStatus ? <small className="soil-entry-outcome" role="status">{saveStatus}</small> : null}
      {open ? <WorkspaceDialog title="Add soil test" onClose={() => setOpen(false)}>
      <p className="soil-entry-hint">Copy the report's value, unit, method and depth exactly.</p>
      <form className="field-event-form record-entry-form" aria-label="Add structured soil-test result" onSubmit={(event) => void submit(event)}>
        <fieldset className="soil-entry-fields" disabled={pending}>
        <label>
          Sample ID
          <input value={sampleId} onChange={(event) => setSampleId(event.target.value)} required maxLength={128} />
        </label>
        <label>
          Measurement
          <select value={metric} onChange={(event) => setMetric(event.target.value as typeof metric)}>
            {soilMetrics.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
        <label>
          Value
          <input type="number" step="any" value={value} onChange={(event) => setValue(event.target.value)} required />
        </label>
        <label>
          Unit on report
          <input value={unit} onChange={(event) => setUnit(event.target.value)} required maxLength={48} placeholder="ppm, mg/kg, pH" />
        </label>
        <label className="field-event-summary">
          Lab method
          <input value={method} onChange={(event) => setMethod(event.target.value)} required maxLength={160} placeholder="Copy from the report" />
        </label>
        <label>
          Depth top
          <input type="number" min="0" step="any" value={depthTop} onChange={(event) => setDepthTop(event.target.value)} required />
        </label>
        <label>
          Depth bottom
          <input type="number" min="0" step="any" value={depthBottom} onChange={(event) => setDepthBottom(event.target.value)} required />
        </label>
        <label>
          Depth unit
          <select value={depthUnit} onChange={(event) => setDepthUnit(event.target.value as 'cm' | 'in')}>
            <option value="cm">cm</option>
            <option value="in">inches</option>
          </select>
        </label>
        <label>
          Sample scope
          <select value={spatialScope} onChange={(event) => setSpatialScope(event.target.value)}>
            <option value="composite">Composite</option>
            <option value="zone">Zone</option>
            <option value="point">Point</option>
            <option value="field">Field</option>
          </select>
        </label>
        <label>
          Entry source
          <select value={sourceQuality} onChange={(event) => {
            setSourceQuality(event.target.value)
          }}>
            <option value="user_transcribed_lab_report">Typed from lab report</option>
            <option value="imported_lab_report">Imported lab report</option>
            <option value="lab_report">Lab data feed</option>
            <option value="field_kit">Field kit</option>
          </select>
        </label>
        <label>
          Lab name
          <input value={labName} onChange={(event) => setLabName(event.target.value)} maxLength={160} />
        </label>
        <label>
          Sampled at
          <input type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} />
        </label>
        <label className="field-event-summary soil-report-check">
          <input type="checkbox" checked={originalReportRetained} onChange={(event) => setOriginalReportRetained(event.target.checked)} />
          Original report retained
        </label>
        </fieldset>
        <button type="submit" className="map-primary-action" disabled={pending}>{pending ? 'Saving…' : 'Save soil test'}</button>
      </form>
      <small className="record-entry-status" aria-live="polite">{saveStatus}</small>
      </WorkspaceDialog> : null}
    </div>
  )
}
