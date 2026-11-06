import type { SourceState } from './farmTypes'

export const sourceStateLabel = (state: string) => ({ not_requested: 'Not checked', queued: 'Waiting', running: 'Updating', available: 'Available', partial: 'Partial coverage', no_match: 'No match', not_applicable: 'Not applicable', jurisdiction_unknown: 'Location needs confirmation', not_installed: 'Not installed', integrity_failed: 'Source integrity failed', credentials_required: 'Credentials required', offline: 'Offline', provider_error: 'Source unavailable', rate_limited: 'Source request limit', invalid_geometry: 'Location or geometry needs review', unsupported_geometry: 'Geometry not supported by this source', superseded: 'Previous boundary', failed: 'Update failed', cancelled: 'Cancelled', interrupted: 'Interrupted', completed: 'Updated' }[state] || state.replace(/_/g, ' '))
const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const text = (value: unknown) => typeof value === 'string' ? value : ''
const number = (value: unknown, unit: string) => typeof value === 'number' && Number.isFinite(value) ? `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}${unit}` : 'Unknown'

function SourceValues({ source, values }: { source: string; values: unknown }) {
  const raw = object(values)
  if (source === 'weather') {
    const parameters = object(raw.parameter_summary)
    return <><p>{text(raw.observation_start)} – {text(raw.observation_end)}</p><dl>
      <div><dt>Mean temperature</dt><dd>{number(object(parameters.T2M).mean, ' °C')}</dd></div>
      <div><dt>Rain + snow water equivalent</dt><dd>{number(object(parameters.PRECTOTCORR).sum, ' mm')}</dd></div>
      <div><dt>Days reported</dt><dd>{number(raw.observed_day_count, '')} of {number(raw.requested_day_count, '')}</dd></div>
    </dl><small>Gridded historical weather; totals cover available days only.</small></>
  }
  if (source === 'soil') {
    const landscapes = Array.isArray(raw.landscapes) ? raw.landscapes.map(object) : []
    const mapUnits = Array.isArray(raw.map_units) ? raw.map_units.map(object) : []
    return <>{landscapes.slice(0, 3).map((row, index) => <p key={index}>{text(row.soil_great_group) || text(row.soil_order) || 'Unnamed soil landscape'}{row.slc_id ? ` · SLC ${row.slc_id}` : ''}</p>)}
      {mapUnits.slice(0, 3).map((row, index) => <p key={index}>{text(row.muname) || text(row.name) || 'Mapped soil unit'}</p>)}<small>Mapped soil context. Confirm field conditions with observations and soil tests.</small></>
  }
  if (source === 'crop_cover') {
    const summary = object(raw.class_summary)
    const classes = Array.isArray(summary.classes) ? summary.classes.map(object) : []
    return <><p>{raw.year ? `${raw.year} classified cover` : 'Historical classified cover'}</p>{classes.slice(0, 3).map((row, index) => <p key={index}>{text(row.aci_label) || text(row.label) || text(row.crop_name) || 'Unclassified'} · {number(row.count, '')} sample points</p>)}<small>Sampled land cover; not acreage or a confirmed planting record.</small>{object(raw.year_selection).selection === 'latest_advertised_year' ? <p>Latest year listed by the source at this check. Catalog checked {text(object(raw.year_selection).fetched_at).slice(0, 10)}.</p> : null}</>
  }
  if (source === 'imagery') {
    const scenes = Array.isArray(raw.scenes) ? raw.scenes.map(object) : []
    const latest = scenes.map(row => text(row.acquired_at)).filter(Boolean).sort().pop()
    return <><p>{scenes.length} scenes in the bounded search{latest ? ` · latest ${latest.slice(0, 10)}` : ''}</p><small>Scene metadata only. Field pixel quality has not been assessed.</small></>
  }
  return null
}

export function FieldSourceSummary({ source, result, onOpen }: { source: string; result: SourceState; onOpen?: () => void }) {
  const successful = ['available', 'partial', 'no_match', 'not_applicable'].includes(result.availability)
  const retained = successful ? result : result.last_success
  return <section className="field-source-summary">
    <h4>{source === 'crop_cover' ? 'Historical crop cover' : source.charAt(0).toUpperCase() + source.slice(1)}</h4>
    <p className="field-source-state"><strong>{sourceStateLabel(result.availability)}</strong>{result.refresh_status ? <span>{sourceStateLabel(result.refresh_status)}</span> : null}{result.freshness === 'stale' ? <span>Out of date</span> : null}</p>
    {retained?.values ? <>{!successful ? <p>Previous successful check · {retained.freshness === 'stale' ? 'out of date' : 'retained'}</p> : null}<SourceValues source={source} values={retained.values} /></> : null}
    {result.fetched_at ? <small>Checked {new Date(result.fetched_at).toLocaleString()}</small> : null}
    {result.message && !successful ? <p>{result.message}</p> : null}
    {(result.values || result.message || result.last_success) ? <details><summary>Coverage & source details</summary><p>{result.message}</p>{result.observed_at ? <p>Observation date / year: {result.observed_at}</p> : null}<pre>{JSON.stringify({ ...result, last_success: result.last_success ? { ...result.last_success, values: result.last_success.values } : undefined }, null, 2)}</pre></details> : null}
    {onOpen ? <button type="button" onClick={onOpen}>{source === 'imagery' ? 'Find / review images' : 'Inspect mapped context'}</button> : null}
  </section>
}
