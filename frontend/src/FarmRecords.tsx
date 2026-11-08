import { useEffect, useState } from 'react'
import { apiGet } from './api'
import { WorkspaceDialog } from './WorkspaceDialog'
import { readableError, type FarmField } from './farmTypes'
import { FieldSyncPanel } from './FieldSyncPanel'
import { displayDate, readableLabel } from './fieldLabels'
import { RecordDetails, RecordMeasurement, recordLabel, unknownRecordTime, type SavedRecord } from './RecordDetails'
import RecordEntryDialog from './RecordEntryDialog'

type Records = { events: SavedRecord[]; total: number; next_offset: number | null }
const recordTypes = ['observation', 'sample', 'operation', 'note', 'decision', 'outcome', 'correction']

export default function FarmRecords({ fields = [], fieldId, farmId, season, onOpenField, onChanged }: {
  fields?: FarmField[]; fieldId?: string; farmId?: string; season: number
  onOpenField?: (id: string) => void; onChanged?: () => void
}) {
  const [records, setRecords] = useState<Records | null>(null)
  const [offset, setOffset] = useState(0)
  const [kindFilter, setKindFilter] = useState('all')
  const [refresh, setRefresh] = useState(0)
  const [loadError, setLoadError] = useState('')
  const [notice, setNotice] = useState('')
  const [entry, setEntry] = useState<{ fieldId: string; record?: SavedRecord } | null>(null)
  const [choosingField, setChoosingField] = useState(false)
  const [chosenField, setChosenField] = useState('')

  useEffect(() => {
    let current = true
    setRecords(null); setLoadError('')
    const query = new URLSearchParams({ season: String(season), offset: String(offset) })
    if (fieldId) query.set('field_id', fieldId)
    if (farmId) query.set('farm_id', farmId)
    if (kindFilter !== 'all') query.set('event_type', kindFilter)
    apiGet<Records>(`/api/records?${query}`)
      .then(value => { if (current) setRecords(value) })
      .catch(cause => { if (current) setLoadError(readableError(cause)) })
    return () => { current = false }
  }, [fieldId, farmId, season, refresh, offset, kindFilter])

  const addRecord = () => {
    setNotice('')
    if (fieldId) setEntry({ fieldId })
    else { setChosenField(fields.length === 1 ? fields[0].id : ''); setChoosingField(true) }
  }
  const saved = () => { setNotice('Record saved.'); setOffset(0); setRefresh(value => value + 1); onChanged?.() }

  return <section className="farm-records" aria-label="Records">
    <div className="records-toolbar">
      <label><span className="sr-only">Record type</span><select aria-label="Record type" value={kindFilter} onChange={event => { setKindFilter(event.target.value); setOffset(0) }}>
        <option value="all">All record types</option>
        {recordTypes.map(kind => <option key={kind} value={kind}>{kind === 'sample' ? 'Soil samples' : readableLabel(kind)}</option>)}
      </select></label>
      {records ? <span className="records-count" role="status">{records.total} {records.total === 1 ? 'record' : 'records'} · {season}</span> : null}
      {fieldId || fields.length ? <button type="button" className="primary-button" onClick={addRecord}>Add record</button> : null}
    </div>
    {notice ? <p role="status" className="record-save-notice">{notice}</p> : null}
    {loadError ? <p role="alert" className="farm-error">{loadError}<button type="button" onClick={() => setRefresh(value => value + 1)}>Retry loading records</button></p>
      : !records ? <p role="status">Loading records…</p>
      : !records.events.length ? <div className="records-empty"><h3>{kindFilter === 'all' ? `No records for ${season}` : `No ${kindFilter === 'sample' ? 'soil samples' : kindFilter + ' records'} for ${season}`}</h3>
        {kindFilter !== 'all' ? <button type="button" onClick={() => { setKindFilter('all'); setOffset(0) }}>Show all record types</button> : <p>{fieldId || fields.length ? 'Add an observation, operation or soil report.' : 'Add a field to start keeping records.'}</p>}
      </div> : <ol className="farm-record-list">{records.events.map(event => {
        const time = unknownRecordTime(event) ? event.recorded_at : event.occurred_at
        return <li key={event.id} className={event.corrected_by ? 'record-superseded' : ''}>
          <div className="farm-record-meta"><span>{event.payload.imagery_analysis ? 'Satellite analysis' : event.event_type === 'sample' ? 'Soil sample' : readableLabel(event.event_type)}</span>
            <time dateTime={time} title={displayDate(time, true)}>{unknownRecordTime(event) ? 'Saved ' : ''}{displayDate(time)}</time>
            {unknownRecordTime(event) ? <small>{event.payload.measurement ? 'Sample date unknown' : 'Observation date unknown'}</small> : null}
            {event.corrected_by ? <strong>Replaced by correction</strong> : null}
          </div>
          <div className="record-content">
            {!fieldId ? <button type="button" className="field-open" onClick={() => onOpenField?.(event.field_context_id)}>{event.field_name}</button> : null}
            <p>{recordLabel(event)}</p><RecordMeasurement event={event} />
            <RecordDetails event={event} season={season} />
          </div>
          {!event.corrected_by && !event.payload.imagery_analysis ? <button type="button" className="record-correct" onClick={() => setEntry({ fieldId: event.field_context_id, record: event })}>Correct record</button> : null}
        </li>
      })}</ol>}
    {records && (offset > 0 || records.next_offset != null) ? <nav className="farm-pagination" aria-label="Record pages">
      {offset > 0 ? <button type="button" onClick={() => setOffset(Math.max(0, offset - 100))}>Previous records</button> : null}
      <span>{offset + 1}–{offset + records.events.length} of {records.total}</span>
      {records.next_offset != null ? <button type="button" onClick={() => setOffset(records.next_offset!)}>Next records</button> : null}
    </nav> : null}
    {fieldId ? <FieldSyncPanel fieldContextId={fieldId} onImported={saved} /> : null}
    {choosingField ? <WorkspaceDialog title="Choose a field" onClose={() => setChoosingField(false)}><form className="farm-form" onSubmit={event => { event.preventDefault(); if (chosenField) { setChoosingField(false); setEntry({ fieldId: chosenField }) } }}>
      <label>Field<select data-dialog-initial-focus required value={chosenField} onChange={event => setChosenField(event.target.value)}><option value="">Choose a field</option>{fields.map(field => <option key={field.id} value={field.id}>{field.name}</option>)}</select></label>
      <button className="primary-button" type="submit" disabled={!chosenField}>Continue</button>
    </form></WorkspaceDialog> : null}
    {entry ? <RecordEntryDialog key={`${entry.fieldId}:${season}:${entry.record?.id || 'new'}`} fieldId={entry.fieldId} fieldName={fields.find(field => field.id === entry.fieldId)?.name} season={season} initialRecord={entry.record} onSaved={saved} onClose={() => setEntry(null)} /> : null}
  </section>
}
