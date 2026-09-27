import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './LeafletFieldMap.css'
import { MapPresentationControls } from './MapPresentationControls'
import { BASEMAPS, readMapPreferences, saveMapPreferences, safeSourceUrl, type MapLayerChoice, type BasemapStyle } from './mapPresentation'
import { estimatePolygonAcres, fieldGeometryIssue, polygonSelfIntersects, type FieldGeometry, type FieldPoint, type MapMode } from './fieldGeometry'

type RegionalCandidate = {
  system: string
  code: string
}

type GeoJsonFeatureCollection = {
  type: 'FeatureCollection'
  features: Array<{
    type: 'Feature'
    geometry: GeoJsonGeometry
    properties?: Record<string, unknown>
  }>
}

type GeoJsonGeometry = {
  type: string
  coordinates: unknown
}

type LeafletFieldMapProps = {
  mode: MapMode
  scenarioId: string
  fieldLabel: string
  geometry: FieldGeometry
  regionalCandidates: RegionalCandidate[]
  regionalFeatureCollection: GeoJsonFeatureCollection | null
  onGeometryChange: (geometry: FieldGeometry) => void
  onStatusChange: (status: string) => void
  /** Stable identity of the selected field. Changing it fits that field once. */
  fieldKey?: string
  onFinishBoundary?: () => void
  onCancelDrawing?: () => void
  allowNetwork?: boolean
  onLayerSelectionChange?: (ids: string[]) => void
}

const scenarioViews: Record<string, { center: [number, number]; zoom: number }> = {
  'central-alberta-barley': { center: [53.3, -113.6], zoom: 12 },
  'abbotsford-capability': { center: [49.05, -122.3], zoom: 12 },
  'regina-thematic-soil': { center: [50.45, -104.73], zoom: 12 },
  'canola-acidity': { center: [49.87, -99.95], zoom: 11 },
  'iowa-phosphorus': { center: [42.03, -93.72], zoom: 12 },
  'irrigated-salinity': { center: [42.9, -114.4], zoom: 12 },
}

const toLatLng = (point: FieldPoint): L.LatLngTuple => [point.lat, point.lon]

const pointLabel = (point: FieldPoint) => `${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`

export function LeafletFieldMap({
  mode,
  scenarioId,
  fieldLabel,
  geometry,
  regionalCandidates,
  regionalFeatureCollection,
  onGeometryChange,
  onStatusChange,
  fieldKey,
  onFinishBoundary,
  onCancelDrawing,
  allowNetwork = true,
  onLayerSelectionChange,
}: LeafletFieldMapProps) {
  const [viewportFeatures, setViewportFeatures] = useState<GeoJsonFeatureCollection | null>(null)
  const [drawingFinished, setDrawingFinished] = useState(false)
  const [preferences, setPreferences] = useState(readMapPreferences)
  const [catalog, setCatalog] = useState<MapLayerChoice[]>([])
  const [catalogStatus, setCatalogStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [layerErrors, setLayerErrors] = useState<Record<string, string>>({})
  const [regionsLoading, setRegionsLoading] = useState(false)
  const [tileError, setTileError] = useState(false)
  const [retry, setRetry] = useState(0)
  const activeLayers = useMemo(() => preferences.layers.filter(id => catalog.some(layer =>
    layer.id === id && layer.available_in_current_mode && (allowNetwork || layer.source_mode === 'local_sqlite'))), [preferences.layers, catalog, allowNetwork])
  const activeLayerKey = activeLayers.join(',')
  const activeLayersRef = useRef(activeLayers)
  activeLayersRef.current = activeLayers
  const loadRegionsRef = useRef<() => void>(() => {})
  const selectionCallbackRef = useRef(onLayerSelectionChange)
  selectionCallbackRef.current = onLayerSelectionChange
  const effectiveStyle = allowNetwork ? preferences.style : 'simple'
  useEffect(() => { saveMapPreferences(preferences) }, [preferences])
  useEffect(() => {
    selectionCallbackRef.current?.(activeLayers)
    setViewportFeatures(null)
    loadRegionsRef.current()
  }, [activeLayerKey])
  useEffect(() => {
    const controller = new AbortController()
    setCatalogStatus('loading')
    fetch('/api/geo/layers', { signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error('Layer catalog unavailable')
      return response.json()
    }).then(payload => {
      if (controller.signal.aborted) return
      if (!Array.isArray(payload.layers)) throw new Error('Invalid layer catalog')
      setCatalog(payload.layers.filter((layer: MapLayerChoice) => typeof layer.id === 'string' && typeof layer.label === 'string'))
      setCatalogStatus('ready')
    }).catch(() => { if (!controller.signal.aborted) { setCatalog([]); setCatalogStatus('error') } })
    return () => controller.abort()
  }, [allowNetwork, retry])
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const drawLayerRef = useRef<L.LayerGroup | null>(null)
  const regionLayersRef = useRef(new Map<string, L.LayerGroup>())
  const regionStyleTargetsRef = useRef<Array<{ layer: L.GeoJSON; selected: boolean }>>([])
  const basemapLayersRef = useRef(new Map<BasemapStyle, L.TileLayer>())
  const modeRef = useRef(mode)
  const geometryRef = useRef<FieldGeometry>(geometry)
  const onGeometryChangeRef = useRef(onGeometryChange)
  const onStatusChangeRef = useRef(onStatusChange)
  const fittedFieldKeyRef = useRef<string | null>(null)
  const selectedFieldKeyRef = useRef(fieldKey ?? scenarioId)
  const previousModeRef = useRef(mode)
  const drawingFinishedRef = useRef(false)

  const selectedCodeKey = JSON.stringify(regionalCandidates.map(candidate => candidate.code).sort())
  const selectedCodes = useMemo(() => new Set<string>(JSON.parse(selectedCodeKey)), [selectedCodeKey])
  const visibleFeatures = useMemo(() => {
    const features = [...(viewportFeatures?.features || [])]
    const seen = new Set(
      features.map((feature) => {
        const properties = feature.properties || {}
        return `${properties.layer_id || ''}:${properties.code || ''}:${properties.name || ''}`
      }),
    )
    for (const feature of regionalFeatureCollection?.features || []) {
      const properties = feature.properties || {}
      const key = `${properties.layer_id || ''}:${properties.code || ''}:${properties.name || ''}`
      if (!seen.has(key)) {
        seen.add(key)
        features.push(feature)
      }
    }
    return { type: 'FeatureCollection' as const, features: features.filter(feature => activeLayers.includes(String(feature.properties?.layer_id || ''))) }
  }, [regionalFeatureCollection, viewportFeatures, activeLayerKey])
  const visibleCounts = useMemo(() => visibleFeatures.features.reduce<Record<string, number>>((counts, feature) => {
    const id = String(feature.properties?.layer_id || '')
    counts[id] = (counts[id] || 0) + 1
    return counts
  }, {}), [visibleFeatures])
  useEffect(() => {
    modeRef.current = mode
    if (mode !== 'boundary' || previousModeRef.current !== 'boundary') {
      drawingFinishedRef.current = false
      setDrawingFinished(false)
    }
    previousModeRef.current = mode
  }, [mode])

  useEffect(() => {
    geometryRef.current = geometry
  }, [geometry])

  useEffect(() => {
    selectedFieldKeyRef.current = fieldKey ?? scenarioId
  }, [fieldKey, scenarioId])

  useEffect(() => {
    onGeometryChangeRef.current = onGeometryChange
    onStatusChangeRef.current = onStatusChange
  }, [onGeometryChange, onStatusChange])

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return
    }
    const view = scenarioViews[scenarioId] || scenarioViews['canola-acidity']
    const map = L.map(containerRef.current, {
      zoomControl: false,
      attributionControl: true,
    }).setView(view.center, view.zoom)
    L.control.zoom({ position: 'bottomright' }).addTo(map)
    L.control.scale({ position: 'bottomleft', imperial: false }).addTo(map)
    // Constructing a tile layer does not fetch it; only the chosen online style is added.
    basemapLayersRef.current.set('satellite', L.tileLayer(BASEMAPS.satellite.url, {
      maxZoom: 19, attribution: BASEMAPS.satellite.attribution,
    }))
    const drawLayer = L.layerGroup().addTo(map)
    drawLayerRef.current = drawLayer
    mapRef.current = map

    map.on('click', (event: L.LeafletMouseEvent) => {
      // The second click of a double click is not another intended vertex.
      if (event.originalEvent?.detail > 1) return
      const point = { lat: event.latlng.lat, lon: event.latlng.lng }
      if (modeRef.current === 'point') {
        fittedFieldKeyRef.current = selectedFieldKeyRef.current
        geometryRef.current = { kind: 'point', point }
        onGeometryChangeRef.current({ kind: 'point', point })
        onStatusChangeRef.current(`Point set at ${pointLabel(point)}.`)
        return
      }
      if (modeRef.current === 'boundary' && !drawingFinishedRef.current) {
        fittedFieldKeyRef.current = selectedFieldKeyRef.current
        const current = geometryRef.current.kind === 'polygon' ? geometryRef.current.points : []
        const points = [...current, point]
        const nextGeometry: FieldGeometry = { kind: 'polygon', points, acres: estimatePolygonAcres(points) }
        geometryRef.current = nextGeometry
        onGeometryChangeRef.current(nextGeometry)
        onStatusChangeRef.current(
          polygonSelfIntersects(points)
            ? 'Boundary edges cross. Switch to edit and move the vertices before intersecting or saving.'
            : points.length < 3
            ? `Boundary draft has ${points.length} point${points.length === 1 ? '' : 's'}.`
            : `Boundary draft has ${points.length} vertices. Choose Finish boundary to edit or save.`,
        )
      }
    })
    let requestTimer: ReturnType<typeof setTimeout> | undefined
    let activeRequest: AbortController | undefined
    let requestVersion = 0
    const loadVisibleRegions = () => {
      const version = ++requestVersion
      if (requestTimer) clearTimeout(requestTimer)
      activeRequest?.abort()
      const ids = [...activeLayersRef.current]
      if (!ids.length) {
        setViewportFeatures(null)
        setLayerErrors({})
        setRegionsLoading(false)
        return
      }
      setRegionsLoading(true)
      requestTimer = setTimeout(() => {
        const bounds = map.getBounds()
        const bbox = [
          bounds.getWest().toFixed(5),
          bounds.getSouth().toFixed(5),
          bounds.getEast().toFixed(5),
          bounds.getNorth().toFixed(5),
        ].join(',')
        const controller = new AbortController()
        activeRequest = controller
        fetch(`/api/geo/regions?bbox=${encodeURIComponent(bbox)}&layers=${encodeURIComponent(ids.join(','))}`, { signal: controller.signal })
          .then((response) => {
            if (!response.ok) {
              throw new Error(`region layer request failed: ${response.status}`)
            }
            return response.json()
          })
          .then((payload) => {
            if (version === requestVersion && payload.feature_collection?.type === 'FeatureCollection' && Array.isArray(payload.feature_collection.features)) {
              setViewportFeatures(payload.feature_collection)
              const errors: Record<string, string> = {}
              for (const item of [...(payload.errors || []), ...(payload.skipped_layers || [])]) {
                errors[String(item.layer_id || item.id)] = 'Source unavailable'
              }
              setLayerErrors(errors)
            }
          })
          .catch(() => {
            if (version === requestVersion && !controller.signal.aborted) {
              setViewportFeatures({ type: 'FeatureCollection', features: [] })
              setLayerErrors(Object.fromEntries(ids.map(id => [id, 'Source unavailable'])))
            }
          }).finally(() => { if (version === requestVersion) setRegionsLoading(false) })
      }, 220)
    }
    loadRegionsRef.current = loadVisibleRegions
    map.on('moveend', loadVisibleRegions)
    loadVisibleRegions()

    const measureCanvas = () => {
      const shell = containerRef.current?.parentElement
      if (shell) shell.style.setProperty('--map-viewport-height', `${shell.clientHeight}px`)
    }
    measureCanvas()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      measureCanvas()
      map.invalidateSize({ pan: false, debounceMoveend: true })
    })
    if (containerRef.current?.parentElement) observer?.observe(containerRef.current.parentElement)

    return () => {
      map.off('moveend', loadVisibleRegions)
      if (requestTimer) clearTimeout(requestTimer)
      ++requestVersion
      activeRequest?.abort()
      observer?.disconnect()
      // Leaflet may still have a CSS zoom transition queued when the user
      // changes tabs. Stop it before removing the map panes; otherwise the
      // delayed transition-end callback can dereference a removed pane.
      map.stop()
      ;(map as L.Map & { _animatingZoom?: boolean })._animatingZoom = false
      map.remove()
      mapRef.current = null
      drawLayerRef.current = null
      regionLayersRef.current.clear()
      regionStyleTargetsRef.current = []
      basemapLayersRef.current.clear()
      loadRegionsRef.current = () => {}
      fittedFieldKeyRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    for (const layer of basemapLayersRef.current.values()) {
      if (map.hasLayer(layer)) map.removeLayer(layer)
    }
    setTileError(false)
    if (effectiveStyle === 'simple') return
    let layer = basemapLayersRef.current.get(effectiveStyle)
    if (!layer) {
      const style = BASEMAPS[effectiveStyle]
      layer = L.tileLayer(style.url, { maxZoom: style.maxZoom, attribution: style.attribution })
      basemapLayersRef.current.set(effectiveStyle, layer)
    }
    const failed = () => setTileError(true)
    layer.on('tileerror', failed)
    layer.addTo(map)
    return () => { layer?.off('tileerror', failed) }
  }, [effectiveStyle, retry])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (mode === 'boundary') map.doubleClickZoom.disable()
    else map.doubleClickZoom.enable()
  }, [mode])

  useEffect(() => {
    const map = mapRef.current
    if (!map || geometry.kind !== 'none') {
      return
    }
    const view = scenarioViews[scenarioId] || scenarioViews['canola-acidity']
    map.setView(view.center, view.zoom, { animate: true })
  }, [scenarioId])

  useEffect(() => {
    const map = mapRef.current
    if (!map) {
      return
    }
    regionStyleTargetsRef.current = []
    const featuresByLayer = new Map<string, Array<GeoJsonFeatureCollection['features'][number]>>()
    visibleFeatures.features.forEach((feature) => {
      const layerId = String(feature.properties?.layer_id || feature.properties?.system || 'regional_context')
      const entries = featuresByLayer.get(layerId) || []
      entries.push(feature)
      featuresByLayer.set(layerId, entries)
    })
    for (const [layerId, layer] of regionLayersRef.current) {
      if (!featuresByLayer.has(layerId)) {
        map.removeLayer(layer)
        regionLayersRef.current.delete(layerId)
      } else {
        layer.clearLayers()
      }
    }
    featuresByLayer.forEach((features, layerId) => {
      let layer = regionLayersRef.current.get(layerId)
      if (!layer) {
        layer = L.layerGroup().addTo(map)
        regionLayersRef.current.set(layerId, layer)
      }
      features.forEach((feature) => {
        const properties = feature.properties || {}
        const code = String(properties.code || '')
        const selected = selectedCodes.has(code)
        const color = String(properties.fill || properties.stroke || '#65a9d4')
        const geoJsonLayer = L.geoJSON(feature as GeoJSON.Feature, {
          interactive: mode === 'inspect',
          style: {
            color,
            fillColor: color,
            fillOpacity: (preferences.opacity / 100) * (selected ? 1 : 0.55),
            opacity: selected ? 0.95 : 0.65,
            weight: selected ? 3 : 2,
            dashArray:
              properties.layer_id === 'epa_l3_us' || properties.layer_id === 'canada_ecozones'
                ? '8 5'
                : properties.layer_id === 'bc_agriculture_capability'
                  ? '5 3'
                  : properties.layer_id === 'sk_thematic_soil'
                    ? '3 3'
                  : properties.layer_id === 'sk_detailed_soil'
                    ? undefined
                  : properties.layer_id === 'pei_detailed_soil'
                    ? '2 4'
                  : properties.layer_id === 'ns_pictou_detailed_soil'
                    ? '7 3 2 3'
                  : undefined,
          },
        })
        if (mode === 'inspect') {
          const system = String(properties.system || 'Regional layer')
          const name = String(properties.name || properties.label || 'Unnamed region')
          const tooltip = document.createElement('span')
          tooltip.textContent = `${name} · ${system}`
          const popup = document.createElement('div')
          popup.className = 'map-feature-popup'
          const heading = document.createElement('strong')
          heading.textContent = name
          const caption = document.createElement('small')
          caption.textContent = `${system}${code ? ` · ${code}` : ''}`
          const note = document.createElement('p')
          note.textContent = 'Mapped context, not a field measurement.'
          popup.append(heading, caption, note)
          const source = safeSourceUrl(String(properties.source_url || ''))
          if (source) {
            const link = document.createElement('a')
            link.href = source; link.target = '_blank'; link.rel = 'noreferrer'; link.textContent = 'View source ↗'
            popup.append(link)
          }
          geoJsonLayer
            .bindTooltip(tooltip, { sticky: true, className: 'regional-layer-tooltip' })
            .bindPopup(popup)
        }
        geoJsonLayer.addTo(layer)
        regionStyleTargetsRef.current.push({ layer: geoJsonLayer, selected })
      })
    })
  }, [mode, selectedCodes, visibleFeatures])

  useEffect(() => {
    for (const { layer, selected } of regionStyleTargetsRef.current) {
      layer.setStyle({ fillOpacity: (preferences.opacity / 100) * (selected ? 1 : 0.55) })
    }
  }, [preferences.opacity])

  useEffect(() => {
    const layer = drawLayerRef.current
    if (!layer) {
      return
    }
    layer.clearLayers()
    if (geometry.kind === 'none') {
      return
    }
    if (geometry.kind === 'point') {
      const fieldTooltip = document.createElement('span')
      fieldTooltip.textContent = fieldLabel || 'Field point'
      L.circleMarker(toLatLng(geometry.point), {
        radius: 8,
        color: '#fff7d0',
        fillColor: '#cf402f',
        fillOpacity: 1,
        weight: 3,
      })
        .bindTooltip(fieldTooltip, { permanent: false })
        .addTo(layer)
      return
    }

    const latLngs = geometry.points.map(toLatLng)
    if (latLngs.length > 1) {
      L.polyline(latLngs, {
        color: effectiveStyle === 'satellite' ? '#ffe07a' : '#235447',
        opacity: 0.98,
        weight: 3,
      }).addTo(layer)
    }
    if (latLngs.length > 2) {
      L.polygon(latLngs, {
        color: effectiveStyle === 'satellite' ? '#ffe07a' : '#235447',
        fillColor: effectiveStyle === 'satellite' ? '#f1c84b' : '#6b9b73',
        fillOpacity: 0.28,
        weight: 3,
      })
        .bindTooltip(`${estimatePolygonAcres(geometry.points).toLocaleString(undefined, { maximumFractionDigits: 1 })} ac · boundary estimate`, { sticky: true })
        .addTo(layer)
    }
    if (mode === 'inspect') return
    geometry.points.forEach((point, index) => {
      const marker = L.marker(toLatLng(point), {
        draggable: mode === 'edit',
        icon: L.divIcon({
          className: 'field-vertex-icon',
          html: '<span></span>',
          iconSize: [18, 18],
          iconAnchor: [9, 9],
        }),
      }).addTo(layer)
      marker.on('dragend', () => {
        const nextLatLng = marker.getLatLng()
        const points = geometry.points.map((candidate, candidateIndex) =>
          candidateIndex === index ? { lat: nextLatLng.lat, lon: nextLatLng.lng } : candidate,
        )
        onGeometryChangeRef.current({ kind: 'polygon', points, acres: estimatePolygonAcres(points) })
        onStatusChangeRef.current(
          polygonSelfIntersects(points)
            ? 'Boundary edges cross. Keep editing before intersecting or saving.'
            : `Updated vertex ${index + 1}.`,
        )
      })
    })
  }, [fieldLabel, geometry, mode, effectiveStyle])

  const fitField = () => {
    const map = mapRef.current
    const field = geometryRef.current
    if (!map || field.kind === 'none') return
    if (field.kind === 'point') {
      map.setView(toLatLng(field.point), Math.max(map.getZoom(), 14), { animate: false })
      return
    }
    if (field.points.length === 1) {
      map.setView(toLatLng(field.points[0]), Math.max(map.getZoom(), 14), { animate: false })
      return
    }
    const bounds = L.latLngBounds(field.points.map(toLatLng))
    if (bounds.isValid()) {
      map.fitBounds(bounds.pad(0.35), { animate: false, maxZoom: 16, padding: [28, 28] })
    }
  }

  useEffect(() => {
    const key = fieldKey ?? scenarioId
    if (geometry.kind === 'none' || fittedFieldKeyRef.current === key) return
    fittedFieldKeyRef.current = key
    fitField()
    // Geometry edits must not recenter the map. A new field identity may.
  }, [fieldKey, scenarioId, geometry.kind])

  const undoLastVertex = () => {
    const field = geometryRef.current
    if (mode !== 'boundary' || drawingFinishedRef.current || field.kind !== 'polygon' || field.points.length === 0) return
    const points = field.points.slice(0, -1)
    const nextGeometry: FieldGeometry = points.length
      ? { kind: 'polygon', points, acres: estimatePolygonAcres(points) }
      : { kind: 'none' }
    geometryRef.current = nextGeometry
    onGeometryChange(nextGeometry)
    onStatusChange(points.length ? `Removed last vertex. ${points.length} remain.` : 'Boundary draft cleared.')
  }

  const finishBoundary = () => {
    if (mode !== 'boundary' || drawingFinishedRef.current) return
    const issue = fieldGeometryIssue(geometryRef.current)
    if (issue) {
      onStatusChange(issue)
      return
    }
    drawingFinishedRef.current = true
    setDrawingFinished(true)
    onStatusChange('Boundary complete. Review the shape, then save the field edits.')
    onFinishBoundary?.()
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const menu = event.target instanceof Element ? event.target.closest<HTMLDetailsElement>('details.map-presentation[open]') : null
    if (event.key === 'Escape' && menu) {
      event.preventDefault(); event.stopPropagation(); menu.open = false; menu.querySelector<HTMLElement>('summary')?.focus(); return
    }
    if (menu) return
    if (event.key === 'Escape' && mode !== 'inspect' && onCancelDrawing) {
      event.preventDefault()
      onCancelDrawing()
    } else if (event.key === 'Backspace' && mode === 'boundary' && !(event.target instanceof HTMLInputElement)) {
      event.preventDefault()
      undoLastVertex()
    }
  }

  return (
    <div className={`leaflet-map-shell basemap-${effectiveStyle} ${mode !== 'inspect' ? 'is-editing' : ''}`} onKeyDown={handleKeyDown}>
      <div ref={containerRef} className="leaflet-map" tabIndex={0} role="application" aria-label={allowNetwork ? `Field map with ${BASEMAPS[effectiveStyle].label.toLowerCase()} style and regional overlays` : 'Offline field map with regional overlays'} />
      <MapPresentationControls preferences={preferences} onChange={setPreferences} layers={catalog} allowNetwork={allowNetwork} catalogStatus={catalogStatus} layerErrors={layerErrors} visibleCounts={visibleCounts} loading={regionsLoading} tileError={tileError} onRetry={() => { setRetry(value => value + 1); loadRegionsRef.current() }} />
      {!allowNetwork ? <div className="leaflet-offline-label" title="Offline map: enter coordinates or import a boundary for precise placement.">Offline map</div> : null}
      {geometry.kind !== 'none' ? <button type="button" className="leaflet-fit-field" onClick={fitField}>Fit field</button> : null}
      {mode === 'inspect' ? null : (
        <div className="leaflet-mode-hint">
          {mode === 'point'
            ? 'Click the field location. This marks a point, not a boundary.'
            : mode === 'boundary'
              ? drawingFinished ? 'Boundary complete. Review and save the field edits.' : 'Click around the field edge. Finish after at least three corners.'
              : 'Drag boundary corners to correct the shape.'}
          {mode === 'boundary' && !drawingFinished ? (
            <span className="leaflet-drawing-actions">
              <button type="button" aria-label="Undo corner" onClick={undoLastVertex} disabled={geometry.kind !== 'polygon' || geometry.points.length === 0}>Undo</button>
              <button type="button" aria-label="Finish boundary" onClick={finishBoundary} disabled={geometry.kind !== 'polygon' || geometry.points.length < 3}>Finish</button>
            </span>
          ) : null}
          {onCancelDrawing ? <button type="button" aria-label="Cancel drawing" onClick={onCancelDrawing}>Cancel</button> : null}
        </div>
      )}
    </div>
  )
}
