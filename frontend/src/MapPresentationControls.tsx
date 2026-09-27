import { Layers3, Info, RotateCcw } from 'lucide-react'
import { BASEMAPS, DEFAULT_MAP_LAYERS, mapLayerLabel, safeSourceUrl, type BasemapStyle, type MapLayerChoice, type MapPreferences } from './mapPresentation'

export function MapPresentationControls({ preferences, onChange, layers, allowNetwork, catalogStatus, layerErrors, visibleCounts, loading, tileError, onRetry }: {
  preferences: MapPreferences; onChange: (value: MapPreferences) => void; layers: MapLayerChoice[]
  allowNetwork: boolean; catalogStatus: 'loading' | 'ready' | 'error'; layerErrors: Record<string, string>
  visibleCounts: Record<string, number>; loading: boolean; tileError: boolean; onRetry: () => void
}) {
  const usable = (layer: MapLayerChoice) => layer.available_in_current_mode && (allowNetwork || layer.source_mode === 'local_sqlite')
  const available = layers.filter(usable)
  const unavailable = layers.filter(layer => !usable(layer))
  const activeSelected = preferences.layers.filter(id => available.some(layer => layer.id === id))
  const toggleLayer = (id: string) => onChange({ ...preferences, layers: activeSelected.includes(id)
    ? activeSelected.filter(item => item !== id) : [...activeSelected, id].slice(0, 4) })
  return <details className="map-presentation" data-workspace-menu>
    <summary aria-label="Map appearance and layers" title="Choose a basemap and mapped context"><Layers3 size={17} /><span>Map & layers</span></summary>
    <section className="map-presentation-panel" aria-label="Map appearance">
      <header><strong>Make the map yours</strong><button type="button" className="map-small-action" title="Reset map display preferences" aria-label="Reset map display" onClick={() => onChange({ style: 'satellite', layers: DEFAULT_MAP_LAYERS, opacity: 35 })}><RotateCcw size={15} /></button></header>
      <div className="basemap-options" role="group" aria-label="Map style">
        {(Object.keys(BASEMAPS) as BasemapStyle[]).map(id => <button type="button" key={id} aria-pressed={(allowNetwork ? preferences.style : 'simple') === id} disabled={!allowNetwork && id !== 'simple'}
          title={!allowNetwork && id !== 'simple' ? 'Available in connected mode' : BASEMAPS[id].description} onClick={() => onChange({ ...preferences, style: id })}>
          <span className={`basemap-preview ${id}`} aria-hidden="true"><i /></span><span>{BASEMAPS[id].label}</span>
        </button>)}
      </div>
      {tileError ? <p className="map-control-notice" role="status">Basemap tiles unavailable. Try Simple or retry.</p> : null}
      {!allowNetwork ? <p className="map-control-note">Offline · boundary and installed layers only.</p> : null}
      <div className="map-layer-heading"><strong>Mapped context</strong><span title="Show up to four layers. Mapped context is not a field measurement."><Info size={14} aria-label="Up to four context layers" /></span></div>
      {catalogStatus === 'loading' ? <p role="status">Loading layers…</p> : catalogStatus === 'error' ? <p role="status">Layer list unavailable.</p> : null}
      <div className="map-layer-choices">
        {available.map(layer => <div className="map-layer-option" key={layer.id}>
          <label><input type="checkbox" checked={preferences.layers.includes(layer.id)} disabled={!preferences.layers.includes(layer.id) && activeSelected.length >= 4}
            onChange={() => toggleLayer(layer.id)} /><i style={{ background: layer.color }} aria-hidden="true" /><span>{mapLayerLabel(layer)}</span></label>
          <details className="map-layer-source"><summary aria-label={`About ${mapLayerLabel(layer)}`} title={`About ${mapLayerLabel(layer)}`}><Info size={14} /></summary>
            <div><strong>{layer.label}</strong><p>{layer.boundary || 'Mapped context; not a field measurement.'}</p>{safeSourceUrl(layer.source_url) ? <a href={layer.source_url} target="_blank" rel="noreferrer">Source ↗</a> : null}</div>
          </details>
          {preferences.layers.includes(layer.id) ? <small className={layerErrors[layer.id] ? 'map-layer-error' : ''}>{layerErrors[layer.id] ? 'Unavailable · retry' : loading ? 'Loading…' : (visibleCounts[layer.id] || 0) > 0 ? `${visibleCounts[layer.id]} in view` : 'No match in view'}</small> : null}
        </div>)}
      </div>
      {unavailable.length ? <details className="map-unavailable-layers"><summary>{unavailable.length} other layers</summary><ul>{unavailable.map(layer => <li key={layer.id}><span>{mapLayerLabel(layer)}</span><small>{layer.installation_status === 'not_installed' ? 'Not installed' : 'Online only'}</small></li>)}</ul></details> : null}
      {preferences.layers.length ? <label className="map-opacity">Layer shading <input type="range" min="10" max="70" value={preferences.opacity} onChange={event => onChange({ ...preferences, opacity: Number(event.target.value) })} /></label> : null}
      <footer><span>Context, not field measurements.</span><button type="button" className="map-small-action" onClick={onRetry}>Retry sources</button></footer>
    </section>
  </details>
}
