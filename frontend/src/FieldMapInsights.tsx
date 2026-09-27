import { useEffect, useMemo, useState } from 'react'
import { MapPin, Ruler, Scan, RefreshCw, ArrowUpRight } from 'lucide-react'
import { csrfHeaders } from './api'
import { mapLayerLabel, safeSourceUrl } from './mapPresentation'

type Zone = { code: string; name: string; area_ha: number | null; fraction_of_field: number | null }
type LayerAnalysis = {
  layer_id: string; label: string; source_url?: string; source_mode: string; status: string; reason?: string
  feature_count: number | null; covered_area_ha: number | null; coverage_fraction: number | null
  zones: Zone[]; omitted_zone_count: number; boundary?: string; coverage_method?: string; uncertainty?: string
}
export type FieldMapAnalysis = {
  schema_version: string; status: string
  geometry: { type: string; status: string; area_ha: number | null; area_ac: number | null; perimeter_m: number | null
    location: { longitude: number; latitude: number } | null; method: string }
  layers: LayerAnalysis[]; elapsed_ms: number; warnings: string[]
}
const number = (value: number | null | undefined, digits = 1) => typeof value === 'number' && Number.isFinite(value)
  ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—'
const percent = (fraction: number | null) => fraction === null ? '—' : `${number(fraction * 100)}%`
const statusLabel = (status: string) => ({ complete: 'Mapped result', partial: 'Partial coverage', not_installed: 'Not installed', blocked_offline: 'Online only', unavailable: 'Unavailable' }[status] || 'Unavailable')
const reasonLabel = (reason?: string) => ({
  spatial_dependencies_missing: 'Spatial analysis is not enabled on this installation.',
  source_query_failed: 'The map source did not return a usable result. Try again later.',
  source_transfer_limit_reached: 'The provider returned only part of the map. Total coverage is unknown.',
  malformed_source_collection: 'The provider response could not be verified.',
  malformed_source_feature: 'Some source shapes could not be verified.',
  source_normalization_incomplete: 'Some source records could not be verified.',
  legacy_remote_query_geometry_incomplete: 'This online source cannot confirm complete coverage for multipart boundaries or holes.',
  source_feature_limit_reached: 'This request reached the source limit. Coverage is incomplete.',
  source_candidate_limit_reached: 'This request reached the source limit. Coverage is incomplete.',
  source_vertex_limit_reached: 'This source is too detailed for an interactive calculation.',
  invalid_source_geometry: 'Some source shapes could not be analysed.',
  local_layer_not_installed: 'This map pack is not installed.',
  offline_network_policy: 'This source requires connected mode.',
  analysis_failed: 'This source could not be analysed.',
}[reason || ''] || 'Coverage could not be established.')

export function FieldMapInsights({ geometry, fieldKey, fieldName, layerIds, allowNetwork, recordedAcres = null }: {
  geometry: { type: string; coordinates: unknown } | null; fieldKey: string; fieldName: string
  layerIds: string[]; allowNetwork: boolean; recordedAcres?: number | null
}) {
  const [result, setResult] = useState<{ key: string; data: FieldMapAnalysis } | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [unit, setUnit] = useState<'ha' | 'ac'>('ha')
  const requestKey = useMemo(() => JSON.stringify({ fieldKey, geometry, layers: layerIds, allowNetwork }), [fieldKey, geometry, layerIds, allowNetwork])
  const data = result?.key === requestKey ? result.data : null
  useEffect(() => {
    const controller = new AbortController()
    let expired = false
    setState('loading'); setError('')
    const timeout = window.setTimeout(() => { expired = true; controller.abort(); setError('The map sources are taking too long. Retry or select fewer layers.'); setState('error') }, 60_000)
    fetch('/api/geo/field-analysis', {
      method: 'POST', headers: { 'content-type': 'application/json', ...csrfHeaders() },
      body: JSON.stringify({ geometry, layers: layerIds }), signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error(response.status === 413 ? 'This boundary is too detailed for interactive analysis. Use a simplified copy.' : response.status === 422 ? 'This boundary cannot be analysed. Check its shape and size.' : 'Field insights are unavailable. Try again shortly.')
      const payload = await response.json()
      if (payload.schema_version !== 'open_agronomy_agent.field_map_analysis.v1' || !payload.geometry || !Array.isArray(payload.layers)) throw new Error('The analysis response was incomplete. Try again.')
      return payload as FieldMapAnalysis
    }).then(payload => {
      if (!controller.signal.aborted) { setResult({ key: requestKey, data: payload }); setState('ready') }
    }).catch(cause => {
      if (!controller.signal.aborted || expired) { setError(expired ? 'The map sources are taking too long. Retry or select fewer layers.' : cause.message); setState('error') }
    }).finally(() => window.clearTimeout(timeout))
    return () => { window.clearTimeout(timeout); controller.abort() }
  }, [requestKey, retry])
  const point = geometry?.type === 'Point'
  const area = (ha: number | null) => `${number(ha === null ? null : unit === 'ha' ? ha : ha * 2.471053814671653)} ${unit}`
  return <div className="field-map-insights">
    <div className="insights-intro"><div><span className="eyebrow">YOUR FIELD, IN CONTEXT</span><h3>{fieldName || 'Selected location'}</h3></div>
      {!point ? <div className="insight-units" role="group" aria-label="Area units"><button type="button" aria-pressed={unit === 'ha'} onClick={() => setUnit('ha')}>ha</button><button type="button" aria-pressed={unit === 'ac'} onClick={() => setUnit('ac')}>ac</button></div> : null}
    </div>
    {state === 'loading' ? <div className="insights-loading" role="status"><RefreshCw size={22} className="spin" /><strong>Reading the map…</strong><span>{layerIds.length ? `${layerIds.length} selected ${layerIds.length === 1 ? 'layer' : 'layers'}` : 'Boundary measurements only'}</span></div> : null}
    {state === 'error' ? <p className="insights-message" role="alert">{error}</p> : null}
    {state === 'ready' && data ? <>
      <div className="insight-metrics" data-kind={point ? 'point' : 'boundary'} aria-label="Geometry measurements">
        <article><Scan size={18} /><span>Area</span><strong>{point ? 'Pin only' : unit === 'ha' ? `${number(data.geometry.area_ha)} ha` : `${number(data.geometry.area_ac)} ac`}</strong><small>{point ? 'Add a boundary for area' : 'Boundary estimate'}</small></article>
        {!point ? <article><Ruler size={18} /><span>Boundary length</span><strong>{point ? '—' : data.geometry.perimeter_m === null ? '—' : data.geometry.perimeter_m >= 1000 ? `${number(data.geometry.perimeter_m / 1000, 2)} km` : `${number(data.geometry.perimeter_m, 0)} m`}</strong><small>{point ? 'No boundary supplied' : 'Includes internal edges'}</small></article> : null}
        <article><MapPin size={18} /><span>Location</span><strong className="insight-coordinate">{data.geometry.location ? `${number(data.geometry.location.latitude, 4)}, ${number(data.geometry.location.longitude, 4)}` : '—'}</strong><small>{point ? 'Selected pin' : 'A point inside the boundary'}</small></article>
      </div>
      {!point && recordedAcres !== null && Number.isFinite(recordedAcres) && data.geometry.area_ac !== null && Math.abs(recordedAcres - data.geometry.area_ac) > Math.max(1, data.geometry.area_ac * 0.01) ? <p className="insight-record-note">Your field record says <strong>{number(recordedAcres)} ac</strong>. This boundary is about <strong>{number(data.geometry.area_ac)} ac</strong>.</p> : null}
      {data.geometry.status !== 'complete' ? <p className="insights-message">Spatial analysis is not enabled on this installation. <a href="https://tknecht4.github.io/open_agronomy_agent/operations/workspace/" target="_blank" rel="noreferrer">Setup guide ↗</a></p> : null}
      <section className="insight-coverage"><header><h4>{point ? 'At this location' : 'Across this boundary'}</h4><span>Mapped context</span></header>
        {!data.layers.length ? <p className="insights-message">Choose context layers in Map & layers to compare the field with official mapping.</p> : null}
        {data.layers.filter(layer => layer.status !== 'complete' || layer.zones.length > 0).map(layer => <article className="insight-layer" key={layer.layer_id}>
          <header><strong>{mapLayerLabel({ id: layer.layer_id, label: layer.label })}</strong><span className={`insight-status ${layer.status}`}>{statusLabel(layer.status)}</span></header>
          {layer.status !== 'complete' ? <p>{reasonLabel(layer.reason)}</p> : !layer.zones.length ? <p>No mapped zone intersects this {point ? 'location' : 'boundary'}.</p> : null}
          {!point && layer.coverage_fraction !== null ? <div className="insight-total"><strong>{percent(layer.coverage_fraction)}</strong><span>mapped coverage · {area(layer.covered_area_ha)}</span></div> : null}
          <div className="insight-zones">{layer.zones.map((zone, index) => <div className="insight-zone" key={`${zone.code}:${index}`}>
            <div><span>{zone.name || zone.code || 'Unnamed map zone'}</span>{!point && zone.fraction_of_field !== null ? <strong>{percent(zone.fraction_of_field)}</strong> : null}</div>
            {!point && zone.fraction_of_field !== null ? <div className="insight-bar" aria-hidden="true"><i style={{ width: `${Math.max(0, Math.min(1, zone.fraction_of_field)) * 100}%` }} /></div> : null}
          </div>)}</div>
          {layer.omitted_zone_count > 0 ? <small>{layer.omitted_zone_count} smaller zones included in coverage.</small> : null}
          <details><summary>Source & method</summary><p>{layer.label}</p><p>{layer.coverage_method}</p><p>{layer.uncertainty}</p><p>{layer.boundary}</p>{safeSourceUrl(layer.source_url) ? <a href={layer.source_url} target="_blank" rel="noreferrer">Open source <ArrowUpRight size={13} /></a> : null}</details>
        </article>)}
        {data.layers.some(layer => layer.status === 'complete' && layer.zones.length === 0) ? <details className="insight-empty-layers"><summary>{data.layers.filter(layer => layer.status === 'complete' && !layer.zones.length).length} layers had no mapped match</summary><ul>{data.layers.filter(layer => layer.status === 'complete' && !layer.zones.length).map(layer => <li key={layer.layer_id}><span>{mapLayerLabel({ id: layer.layer_id, label: layer.label })}</span>{!point && layer.coverage_fraction !== null ? <strong>{percent(layer.coverage_fraction)}</strong> : null}{safeSourceUrl(layer.source_url) ? <a href={layer.source_url} target="_blank" rel="noreferrer">Source ↗</a> : null}</li>)}</ul></details> : null}
      </section>
      <details className="insight-method"><summary>How to read these estimates</summary><p>{data.geometry.method}</p><p>Area uses the supplied boundary. Different mapped zones can overlap; their percentages may not add to 100%.</p>{data.warnings.map((warning, index) => <p key={index}>{warning}</p>)}</details>
    </> : null}
    <footer className="insights-footer"><span>Map context · not soil tests or field observations</span><button type="button" disabled={state === 'loading'} onClick={() => setRetry(value => value + 1)}><RefreshCw size={14} /> Refresh</button></footer>
  </div>
}
