import { displayDate, imagerySourceLabel, measurementLabel, readableLabel } from './fieldLabels'

export type SavedRecord = {
  id: string; field_context_id: string; field_name: string; event_type: string
  occurred_at: string; recorded_at: string; payload: Record<string, unknown>; provenance: Record<string, unknown>
  corrects_event_id?: string; corrected_by?: string; season_binding: string
}
const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const text = (value: unknown) => typeof value === 'string' || typeof value === 'number' ? String(value) : 'Unknown'
export const unknownRecordTime = (event: SavedRecord) => event.provenance.sampling_time_status === 'unknown' || event.provenance.observation_time_status === 'unknown'

export function recordLabel(event: SavedRecord): string {
  const image = object(event.payload.imagery_analysis)
  if (image.job_id) return `${imagerySourceLabel(text(image.provider_id))} satellite analysis`
  const measurement = object(event.payload.measurement)
  const summary = typeof event.payload.summary === 'string' ? event.payload.summary : typeof event.payload.note === 'string' ? event.payload.note : ''
  // Replace only the known auto-generated caption, never a grower's prose.
  const generated = `${measurement.sample_id}: ${measurement.metric} ${measurement.value} ${measurement.unit}`
  if (measurement.metric && (!summary || summary === generated)) return `${measurementLabel(text(measurement.metric))} · sample ${text(measurement.sample_id)}`
  return summary || readableLabel(event.event_type)
}

export function RecordMeasurement({ event }: { event: SavedRecord }) {
  const measurement = object(event.payload.measurement)
  if (!measurement.metric) return null
  return <p className="record-measurement"><strong>{measurementLabel(text(measurement.metric))}</strong> {text(measurement.value)} {text(measurement.unit)}</p>
}

export function RecordDetails({ event, season }: { event: SavedRecord; season: number }) {
  const measurement = object(event.payload.measurement)
  const depth = object(measurement.sample_depth)
  const image = object(event.payload.imagery_analysis)
  return <details className="record-details">
    <summary>Source & record details</summary>
    <dl className="readable-details">
      <div><dt>Season</dt><dd>{event.season_binding === 'explicit' ? season : event.season_binding === 'observation_year' ? `${season} · from observation date` : 'Not recorded'}</dd></div>
      <div><dt>{measurement.metric ? 'Sampled' : 'Observed'}</dt><dd>{unknownRecordTime(event) ? 'Date not recorded' : displayDate(event.occurred_at, true)}</dd></div>
      <div><dt>Saved</dt><dd>{displayDate(event.recorded_at, true)}</dd></div>
      {measurement.metric ? <>
        <div><dt>Sample</dt><dd>{text(measurement.sample_id)}</dd></div>
        <div><dt>Lab</dt><dd>{text(measurement.lab_name)}</dd></div>
        <div><dt>Lab method</dt><dd>{text(measurement.method)}</dd></div>
        <div><dt>Depth</dt><dd>{text(depth.top)}–{text(depth.bottom)} {text(depth.unit)}</dd></div>
        <div><dt>Sample area</dt><dd>{readableLabel(text(measurement.spatial_scope))}</dd></div>
      </> : null}
      {image.job_id ? <div><dt>Source</dt><dd>{imagerySourceLabel(text(image.provider_id))}</dd></div> : null}
      {event.corrects_event_id ? <div><dt>History</dt><dd>Corrects an earlier entry. The original remains available.</dd></div> : null}
      {event.corrected_by ? <div><dt>Status</dt><dd>Replaced by a later correction</dd></div> : null}
    </dl>
    {measurement.metric ? <p>Transcribed from a lab report; values have not been independently verified.</p> : null}
    {image.job_id ? <p>Satellite measurements describe processed pixels. They are not a field observation or a diagnosis.</p> : null}
    <details><summary>Technical record</summary><pre>{JSON.stringify({ id: event.id, corrects_event_id: event.corrects_event_id, corrected_by: event.corrected_by, payload: event.payload, provenance: event.provenance }, null, 2)}</pre></details>
  </details>
}
