import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { estimatePolygonAcres, polygonSelfIntersects, type FieldGeometry, type FieldPoint, type MapMode } from './fieldGeometry'

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
}

const ESRI_WORLD_IMAGERY =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'

const scenarioViews: Record<string, { center: [number, number]; zoom: number }> = {
  'abbotsford-capability': { center: [49.05, -122.3], zoom: 12 },
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
}: LeafletFieldMapProps) {
  const [viewportFeatures, setViewportFeatures] = useState<GeoJsonFeatureCollection | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const drawLayerRef = useRef<L.LayerGroup | null>(null)
  const regionLayerRef = useRef<L.LayerGroup | null>(null)
  const modeRef = useRef(mode)
  const geometryRef = useRef<FieldGeometry>(geometry)
  const onGeometryChangeRef = useRef(onGeometryChange)
  const onStatusChangeRef = useRef(onStatusChange)

  const selectedCodes = useMemo(() => new Set(regionalCandidates.map((candidate) => candidate.code)), [regionalCandidates])
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
    return { type: 'FeatureCollection' as const, features }
  }, [regionalFeatureCollection, viewportFeatures])
  const hasBcCapability = useMemo(
    () => visibleFeatures.features.some((feature) => feature.properties?.layer_id === 'bc_agriculture_capability'),
    [visibleFeatures],
  )
  const hasSkThematicSoil = useMemo(
    () => visibleFeatures.features.some((feature) => feature.properties?.layer_id === 'sk_thematic_soil'),
    [visibleFeatures],
  )
  const hasPeiDetailedSoil = useMemo(
    () => visibleFeatures.features.some((feature) => feature.properties?.layer_id === 'pei_detailed_soil'),
    [visibleFeatures],
  )
  const hasNsPictouDetailedSoil = useMemo(
    () => visibleFeatures.features.some((feature) => feature.properties?.layer_id === 'ns_pictou_detailed_soil'),
    [visibleFeatures],
  )
  const hasCaErosionRisk = useMemo(
    () => visibleFeatures.features.some((feature) => feature.properties?.layer_id === 'ca_soil_erosion_risk'),
    [visibleFeatures],
  )

  useEffect(() => {
    modeRef.current = mode
  }, [mode])

  useEffect(() => {
    geometryRef.current = geometry
  }, [geometry])

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
    L.tileLayer(ESRI_WORLD_IMAGERY, {
      maxZoom: 19,
      attribution: 'Tiles © Esri',
    }).addTo(map)
    const regionLayer = L.layerGroup().addTo(map)
    const drawLayer = L.layerGroup().addTo(map)
    regionLayerRef.current = regionLayer
    drawLayerRef.current = drawLayer
    mapRef.current = map

    map.on('click', (event: L.LeafletMouseEvent) => {
      const point = { lat: event.latlng.lat, lon: event.latlng.lng }
      if (modeRef.current === 'point') {
        onGeometryChangeRef.current({ kind: 'point', point })
        onStatusChangeRef.current(`Point set at ${pointLabel(point)}.`)
        return
      }
      if (modeRef.current === 'boundary') {
        const current = geometryRef.current.kind === 'polygon' ? geometryRef.current.points : []
        const points = [...current, point]
        onGeometryChangeRef.current({ kind: 'polygon', points, acres: estimatePolygonAcres(points) })
        onStatusChangeRef.current(
          polygonSelfIntersects(points)
            ? 'Boundary edges cross. Switch to edit and move the vertices before intersecting or saving.'
            : points.length < 3
            ? `Boundary draft has ${points.length} point${points.length === 1 ? '' : 's'}.`
            : `Boundary draft has ${points.length} vertices. Switch to edit to drag corners.`,
        )
      }
    })
    const loadVisibleRegions = () => {
      const bounds = map.getBounds()
      const bbox = [
        bounds.getWest().toFixed(5),
        bounds.getSouth().toFixed(5),
        bounds.getEast().toFixed(5),
        bounds.getNorth().toFixed(5),
      ].join(',')
      fetch(`/api/geo/regions?bbox=${encodeURIComponent(bbox)}`)
        .then((response) => {
          if (!response.ok) {
            throw new Error(`region layer request failed: ${response.status}`)
          }
          return response.json()
        })
        .then((payload) => {
          if (payload.feature_collection?.type === 'FeatureCollection') {
            setViewportFeatures(payload.feature_collection)
          }
        })
        .catch(() => {
          setViewportFeatures({ type: 'FeatureCollection', features: [] })
        })
    }
    map.on('moveend', loadVisibleRegions)
    loadVisibleRegions()

    return () => {
      map.off('moveend', loadVisibleRegions)
      // Leaflet may still have a CSS zoom transition queued when the user
      // changes tabs. Stop it before removing the map panes; otherwise the
      // delayed transition-end callback can dereference a removed pane.
      map.stop()
      ;(map as L.Map & { _animatingZoom?: boolean })._animatingZoom = false
      map.remove()
      mapRef.current = null
      drawLayerRef.current = null
      regionLayerRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || geometry.kind !== 'none') {
      return
    }
    const view = scenarioViews[scenarioId] || scenarioViews['canola-acidity']
    map.setView(view.center, view.zoom, { animate: true })
  }, [scenarioId, geometry.kind])

  useEffect(() => {
    const layer = regionLayerRef.current
    if (!layer) {
      return
    }
    layer.clearLayers()
    visibleFeatures.features.forEach((feature) => {
      const properties = feature.properties || {}
      const code = String(properties.code || '')
      const selected = selectedCodes.has(code)
      const color = String(properties.fill || properties.stroke || '#65a9d4')
      const geoJsonLayer = L.geoJSON(feature as GeoJSON.Feature, {
        interactive: mode === 'inspect',
        style: {
          color,
          fillColor: color,
          fillOpacity: selected ? 0.3 : 0.14,
          opacity: selected ? 0.95 : 0.65,
          weight: selected ? 3 : 2,
          dashArray:
            properties.layer_id === 'epa_l3_us' || properties.layer_id === 'canada_ecozones'
              ? '8 5'
              : properties.layer_id === 'bc_agriculture_capability'
                ? '5 3'
                : properties.layer_id === 'sk_thematic_soil'
                  ? '3 3'
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
        geoJsonLayer
          .bindTooltip(`${system} ${code}`, { sticky: true, className: 'regional-layer-tooltip' })
          .bindPopup(`<strong>${name}</strong>`)
      }
      geoJsonLayer.addTo(layer)
    })
  }, [mode, selectedCodes, visibleFeatures])

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
      L.circleMarker(toLatLng(geometry.point), {
        radius: 8,
        color: '#fff7d0',
        fillColor: '#cf402f',
        fillOpacity: 1,
        weight: 3,
      })
        .bindTooltip(fieldLabel || 'Field point', { permanent: false })
        .addTo(layer)
      return
    }

    const latLngs = geometry.points.map(toLatLng)
    if (latLngs.length > 1) {
      L.polyline(latLngs, {
        color: '#ffe07a',
        opacity: 0.98,
        weight: 3,
      }).addTo(layer)
    }
    if (latLngs.length > 2) {
      L.polygon(latLngs, {
        color: '#ffe07a',
        fillColor: '#f1c84b',
        fillOpacity: 0.28,
        weight: 3,
      })
        .bindTooltip(`${Math.round(geometry.acres).toLocaleString()} ac`, { sticky: true })
        .addTo(layer)
    }
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
  }, [fieldLabel, geometry, mode])

  useEffect(() => {
    const map = mapRef.current
    if (!map || geometry.kind === 'none') {
      return
    }
    if (mode === 'boundary') {
      return
    }
    if (geometry.kind === 'point') {
      map.setView(toLatLng(geometry.point), Math.max(map.getZoom(), 14), { animate: true })
      return
    }
    if (geometry.points.length === 1) {
      map.setView(toLatLng(geometry.points[0]), Math.max(map.getZoom(), 14), { animate: true })
      return
    }
    const bounds = L.latLngBounds(geometry.points.map(toLatLng))
    if (bounds.isValid()) {
      map.fitBounds(bounds.pad(0.35), { animate: true, maxZoom: 16, padding: [28, 28] })
    }
  }, [geometry, mode])

  return (
    <div className="leaflet-map-shell">
      <div ref={containerRef} className="leaflet-map" aria-label="Field map with Esri imagery and regional overlays" />
      <div className="leaflet-mode-hint">
        {mode === 'inspect'
          ? 'Inspect regional layers or choose a drawing tool.'
          : mode === 'point'
            ? 'Click the field location.'
            : mode === 'boundary'
              ? 'Click around the field edge.'
              : 'Drag boundary vertices.'}
      </div>
      <div className="layer-legend" aria-label="Map legend">
        <span><i className="legend-mlra" /> MLRA</span>
        <span><i className="legend-eco" /> Ecoregion</span>
        {hasBcCapability ? <span><i className="legend-bc-capability" /> BC capability</span> : null}
        {hasSkThematicSoil ? <span><i className="legend-sk-soil" /> SK thematic soil</span> : null}
        {hasPeiDetailedSoil ? <span><i className="legend-pei-soil" /> PEI mapped soil</span> : null}
        {hasNsPictouDetailedSoil ? <span><i className="legend-ns-pictou-soil" /> Pictou County soil</span> : null}
        {hasCaErosionRisk ? <span><i className="legend-ca-erosion" /> Erosion risk</span> : null}
        <span><i className="legend-field" /> Field</span>
      </div>
    </div>
  )
}
