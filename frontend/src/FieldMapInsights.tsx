import { useEffect, useState } from 'react'
import { MapPin, RefreshCw, ArrowUpRight, ChevronDown } from 'lucide-react'
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

type AnalysisRequest = {
  key: string; data: FieldMapAnalysis | null; state: 'loading' | 'ready' | 'error'; error: string
}

// Geometry-only requests never query providers. Keep them independent so a slow or
// failed mapped source cannot hide usable boundary measurements.
function useAnalysisRequest(body: string, identity: string, enabled: boolean, retry: number) {
  const key = `${identity}:${retry}`
  const [result, setResult] = useState<AnalysisRequest | null>(null)
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    setResult({ key, data: null, state: 'loading', error: '' })
    const timeoutMessage = 'This request is taking too long. Try again.'
    const timeout = window.setTimeout(() => {
      controller.abort()
      setResult({ key, data: null, state: 'error', error: timeoutMessage })
    }, 60_000)
    fetch('/api/geo/field-analysis', {
      method: 'POST', headers: { 'content-type': 'application/json', ...csrfHeaders() },
      body, signal: controller.signal,
    }).then(async response => {
      if (!response.ok) throw new Error(response.status === 413 ? 'This boundary is too detailed for interactive analysis. Use a simplified copy.' : response.status === 422 ? 'This boundary cannot be analysed. Check its shape and size.' : 'Field insights are unavailable. Try again shortly.')
      const payload = await response.json()
      if (payload.schema_version !== 'open_agronomy_agent.field_map_analysis.v1' || !payload.geometry || !Array.isArray(payload.layers)) throw new Error('The analysis response was incomplete. Try again.')
      return payload as FieldMapAnalysis
    }).then(payload => {
      if (!controller.signal.aborted) setResult({ key, data: payload, state: 'ready', error: '' })
    }).catch(cause => {
      if (!controller.signal.aborted) setResult({ key, data: null, state: 'error', error: cause.message })
    }).finally(() => window.clearTimeout(timeout))
    return () => { window.clearTimeout(timeout); controller.abort() }
  }, [body, key, enabled])
  return result?.key === key ? result : { key, data: null, state: 'loading' as const, error: '' }
}

export function FieldMapInsights({ geometry, fieldKey, fieldName, layerIds, allowNetwork, recordedAcres = null }: {
  geometry: { type: string; coordinates: unknown } | null; fieldKey: string; fieldName: string
  layerIds: string[]; allowNetwork: boolean; recordedAcres?: number | null
}) {
  const [retry, setRetry] = useState(0)
  const [unit, setUnit] = useState<'ha' | 'ac'>('ha')
  const geometryKey = JSON.stringify({ fieldKey, geometry })
  const layersKey = JSON.stringify({ geometryKey, layers: layerIds, allowNetwork })
  const measurements = useAnalysisRequest(JSON.stringify({ geometry, layers: [] }), geometryKey, true, retry)
  const mapping = useAnalysisRequest(JSON.stringify({ geometry, layers: layerIds }), layersKey, layerIds.length > 0, retry)
  const metrics = measurements.data?.geometry || mapping.data?.geometry
  const layers = mapping.data?.layers || []
  const unmatched = layers.filter(layer => layer.status === 'complete' && !layer.zones.length)
  const point = geometry?.type === 'Point'
  const area = (ha: number | null) => ha === null ? '—' : `${number(unit === 'ha' ? ha : ha * 2.471053814671653)} ${unit}`
  const location = metrics?.location ? `${number(metrics.location.latitude, 4)}, ${number(metrics.location.longitude, 4)}` : '—'
  const warnings = [...new Set([...(measurements.data?.warnings || []), ...(mapping.data?.warnings || [])])]
  const busy = measurements.state === 'loading' || (layerIds.length > 0 && mapping.state === 'loading')
  const discrepantArea = !point && recordedAcres !== null && Number.isFinite(recordedAcres) && metrics?.area_ac != null
    && Math.abs(recordedAcres - metrics.area_ac) > Math.max(1, metrics.area_ac * 0.01)
  return <div className="field-map-insights">
    <div className="insights-intro"><h3>{fieldName || 'Selected location'}</h3>
      <div className="insights-actions">{!point ? <div className="insight-units" role="group" aria-label="Area units"><button type="button" aria-pressed={unit === 'ha'} onClick={() => setUnit('ha')}>ha</button><button type="button" aria-pressed={unit === 'ac'} onClick={() => setUnit('ac')}>ac</button></div> : null}<button type="button" className="insight-refresh" aria-label="Refresh" title="Refresh field insights" disabled={busy} onClick={() => setRetry(value => value + 1)}><RefreshCw size={16} className={busy ? 'spin' : undefined} /></button></div>
    </div>
    {!metrics && measurements.state === 'loading' ? <p className="insights-loading" role="status"><RefreshCw size={16} className="spin" /> Measuring boundary…</p> : null}
    {!metrics && measurements.state === 'error' ? <p className="insights-message" role="alert">{measurements.error}</p> : null}
    {metrics ? <>
      {point ? <div className="insight-pin"><MapPin size={18} /><div><strong>{location}</strong><span>Pin only · no boundary supplied</span></div></div> : <dl className="insight-metrics" aria-label="Geometry measurements">
        <div><dt>Area <span>· estimate</span></dt><dd>{unit === 'ha' ? area(metrics.area_ha) : metrics.area_ac === null ? '—' : `${number(metrics.area_ac)} ac`}</dd></div>
        <div><dt>Boundary length</dt><dd>{metrics.perimeter_m === null ? '—' : metrics.perimeter_m >= 1000 ? `${number(metrics.perimeter_m / 1000, 2)} km` : `${number(metrics.perimeter_m, 0)} m`}</dd></div>
      </dl>}
      {discrepantArea ? <p className="insight-record-note"><strong>{number(recordedAcres)} ac recorded</strong><span>{number(metrics.area_ac)} ac from boundary</span></p> : null}
      {metrics.status !== 'complete' ? <p className="insights-message">Spatial analysis is not enabled on this installation. <a href="https://tknecht4.github.io/open_agronomy_agent/operations/workspace/" target="_blank" rel="noreferrer">Setup guide ↗</a></p> : null}
    </> : null}
    <section className="insight-coverage" aria-label="Mapped context">
      <header><h4>{point ? 'At this location' : 'Mapped zones'}</h4><span>Context, not measurements</span></header>
      {!layerIds.length ? <p className="insights-message">Choose context layers in Map & layers to compare this field with official mapping.</p> : mapping.state === 'loading' ? <p className="insights-loading" role="status"><RefreshCw size={15} className="spin" /> Reading {layerIds.length} map {layerIds.length === 1 ? 'source' : 'sources'}…</p> : mapping.state === 'error' ? <p className="insights-message" role="alert">{mapping.error} {metrics ? 'Boundary measurements remain available above.' : ''}</p> : <>
        {layers.filter(layer => layer.status !== 'complete' || layer.zones.length > 0).map(layer => <article className="insight-layer" key={layer.layer_id}>
          <details>
            <summary>
              <div className="insight-layer-label"><strong>{mapLayerLabel({ id: layer.layer_id, label: layer.label })}</strong><span>{layer.zones.length === 1 ? layer.zones[0].name || layer.zones[0].code || 'Unnamed map zone' : layer.zones.length > 1 ? `${layer.zones.length} mapped zones` : 'No verified match'}</span></div>
              <div className="insight-layer-value">{!point && layer.coverage_fraction !== null ? <><strong>{percent(layer.coverage_fraction)}</strong><span>covered</span></> : <span className={`insight-status ${layer.status}`}>{statusLabel(layer.status)}</span>}</div>
              <ChevronDown size={15} className="insight-chevron" aria-hidden="true" />
            </summary>
            <div className="insight-layer-detail">
              {!point && layer.coverage_fraction !== null ? <p className="insight-total">{area(layer.covered_area_ha)} mapped · {percent(layer.coverage_fraction)} of boundary</p> : null}
              {layer.zones.length ? <table className="insight-zones"><caption className="sr-only">Mapped zones in {layer.label}</caption><thead><tr><th scope="col">Zone</th>{!point ? <><th scope="col">Area</th><th scope="col">Share</th></> : null}</tr></thead><tbody>{layer.zones.map((zone, index) => <tr key={`${zone.code}:${index}`}><th scope="row">{zone.name || zone.code || 'Unnamed map zone'}</th>{!point ? <><td>{area(zone.area_ha)}</td><td>{percent(zone.fraction_of_field)}</td></> : null}</tr>)}</tbody></table> : null}
              {layer.omitted_zone_count > 0 ? <p>{layer.omitted_zone_count} smaller zones included in total coverage.</p> : null}
              <div className="insight-source"><strong>Source & method</strong><p>{layer.label}</p><p>{layer.coverage_method}</p><p>{layer.uncertainty}</p><p>{layer.boundary}</p>{safeSourceUrl(layer.source_url) ? <a href={layer.source_url} target="_blank" rel="noreferrer">Open source <ArrowUpRight size={13} /></a> : null}</div>
            </div>
          </details>
          {layer.status !== 'complete' ? <p className="insight-source-note"><strong>{statusLabel(layer.status)}.</strong> {reasonLabel(layer.reason)}</p> : null}
        </article>)}
        {unmatched.length ? <details className="insight-empty-layers"><summary>{unmatched.length} {unmatched.length === 1 ? 'layer had' : 'layers had'} no mapped match</summary><ul>{unmatched.map(layer => <li key={layer.layer_id}><span>{mapLayerLabel({ id: layer.layer_id, label: layer.label })}</span>{!point && layer.coverage_fraction !== null ? <strong>{percent(layer.coverage_fraction)}</strong> : null}{safeSourceUrl(layer.source_url) ? <a href={layer.source_url} target="_blank" rel="noreferrer">Source ↗</a> : null}</li>)}</ul></details> : null}
      </>}
    </section>
    {metrics ? <details className="insight-method"><summary>{point ? 'Measurement details' : 'Boundary details'}</summary>{!point ? <p><strong>Location:</strong> {location} · a point inside the boundary.</p> : null}<p>{metrics.method}</p><p>Area uses the supplied boundary. Boundary length includes internal edges. Mapped zones can overlap; shares may not add to 100%.</p>{warnings.map((warning, index) => <p key={index}>{warning}</p>)}</details> : null}
  </div>
}
