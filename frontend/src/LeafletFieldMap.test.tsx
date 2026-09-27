import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LeafletFieldMap } from './LeafletFieldMap'
import { estimatePolygonAcres, type FieldGeometry, type MapMode } from './fieldGeometry'

const leaf = vi.hoisted(() => ({
  maps: [] as any[],
  tiles: [] as any[],
  markers: [] as any[],
  regions: [] as any[],
  pointTooltips: [] as any[],
}))

vi.mock('leaflet', () => {
  const layer = () => ({ setStyle: vi.fn().mockReturnThis(), on: vi.fn().mockReturnThis(), off: vi.fn().mockReturnThis(), addTo: vi.fn().mockReturnThis(), clearLayers: vi.fn(), bindTooltip: vi.fn().mockReturnThis(), bindPopup: vi.fn().mockReturnThis() })
  return {
    default: {
      map: () => {
        const events = new Map<string, (event: any) => void>()
        const activeLayers = new Set<any>()
        const map = {
          on: vi.fn((name: string, fn: (event: any) => void) => { events.set(name, fn) }),
          off: vi.fn((name: string) => { events.delete(name) }),
          fire: (name: string, event?: any) => events.get(name)?.(event),
          setView: vi.fn().mockReturnThis(),
          fitBounds: vi.fn(),
          getZoom: () => 12,
          getBounds: () => ({ getWest: () => -114, getSouth: () => 53, getEast: () => -113, getNorth: () => 54 }),
          registerLayer: (item: any) => { activeLayers.add(item) },
          hasLayer: vi.fn((item: any) => activeLayers.has(item)),
          removeLayer: vi.fn((item: any) => { activeLayers.delete(item) }),
          invalidateSize: vi.fn(),
          stop: vi.fn(),
          remove: vi.fn(),
          doubleClickZoom: { disable: vi.fn(), enable: vi.fn() },
        }
        leaf.maps.push(map)
        return map
      },
      control: {
        zoom: () => layer(),
        scale: () => layer(),
        layers: () => ({ ...layer(), getContainer: () => document.createElement('div'), addOverlay: vi.fn(), addBaseLayer: vi.fn(), removeLayer: vi.fn() }),
      },
      tileLayer: () => {
        const tile = layer()
        tile.addTo = vi.fn((map: any) => { map.registerLayer(tile); return tile })
        leaf.tiles.push(tile)
        return tile
      },
      layerGroup: layer,
      geoJSON: (feature: any) => {
        leaf.regions.push(feature)
        return layer()
      },
      circleMarker: () => {
        const marker = layer()
        marker.bindTooltip = vi.fn((content: any) => { leaf.pointTooltips.push(content); return marker })
        return marker
      },
      polyline: layer,
      polygon: layer,
      divIcon: () => ({}),
      marker: (latLng: [number, number], options: any) => {
        const handlers = new Map<string, () => void>()
        const marker = {
          ...layer(), options,
          on: (name: string, fn: () => void) => { handlers.set(name, fn) },
          getLatLng: () => ({ lat: latLng[0] + 0.01, lng: latLng[1] }),
          drag: () => handlers.get('dragend')?.(),
        }
        leaf.markers.push(marker)
        return marker
      },
      latLngBounds: () => ({ isValid: () => true, pad: () => ({}) }),
    },
  }
})

const empty: FieldGeometry = { kind: 'none' }
const points = [
  { lat: 53.3, lon: -113.6 },
  { lat: 53.3, lon: -113.5 },
  { lat: 53.4, lon: -113.5 },
]
const polygon: FieldGeometry = { kind: 'polygon', points, acres: estimatePolygonAcres(points) }

const props = {
  scenarioId: 'central-alberta-barley',
  fieldLabel: 'Test field',
  regionalCandidates: [],
  regionalFeatureCollection: null,
  onStatusChange: vi.fn(),
}

function ControlledMap({ onFinishBoundary, onCancelDrawing }: { onFinishBoundary: () => void; onCancelDrawing: () => void }) {
  const [geometry, setGeometry] = useState<FieldGeometry>(empty)
  const [mode, setMode] = useState<MapMode>('boundary')
  return <LeafletFieldMap {...props} mode={mode} geometry={geometry} onGeometryChange={setGeometry}
    onFinishBoundary={() => { onFinishBoundary(); setMode('edit') }} onCancelDrawing={onCancelDrawing} />
}

const catalog = { layers: [{ id: 'canada_ecozones', label: 'Canada ecozones', system: 'Ecozone', source_url: 'https://example.test/source', color: '#477957', source_mode: 'arcgis', available_in_current_mode: true, installation_status: 'remote' }] }

beforeEach(() => {
  window.localStorage.clear()
  leaf.maps.length = 0
  leaf.tiles.length = 0
  leaf.markers.length = 0
  leaf.regions.length = 0
  leaf.pointTooltips.length = 0
  vi.stubGlobal('fetch', vi.fn(async (url) => ({ ok: true, json: async () => String(url) === '/api/geo/layers' ? catalog : ({ feature_collection: { type: 'FeatureCollection', features: [] } }) })))
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('field map interactions', () => {
  it('lets a user undo a corner, finish only a valid boundary, then escape to cancel', () => {
    const finish = vi.fn()
    const cancel = vi.fn()
    render(<ControlledMap onFinishBoundary={finish} onCancelDrawing={cancel} />)
    const map = leaf.maps[0]
    expect(map.doubleClickZoom.disable).toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Finish boundary' })).toBeDisabled()
    for (const point of points) act(() => map.fire('click', { latlng: { lat: point.lat, lng: point.lon }, originalEvent: { detail: 1 } }))
    expect(screen.getByRole('button', { name: 'Finish boundary' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Undo corner' }))
    expect(screen.getByRole('button', { name: 'Finish boundary' })).toBeDisabled()
    act(() => map.fire('click', { latlng: { lat: 53.4, lng: -113.5 }, originalEvent: { detail: 1 } }))
    fireEvent.click(screen.getByRole('button', { name: 'Finish boundary' }))
    expect(finish).toHaveBeenCalledOnce()
    expect(map.doubleClickZoom.enable).toHaveBeenCalled()
    fireEvent.keyDown(screen.getByRole('application'), { key: 'Escape' })
    expect(cancel).toHaveBeenCalledOnce()
  })

  it('fits imported geometry once per field and does not snap back after a vertex drag', () => {
    const onGeometryChange = vi.fn()
    const { rerender } = render(<LeafletFieldMap {...props} fieldKey="field-a" mode="edit" geometry={empty} onGeometryChange={onGeometryChange} />)
    const map = leaf.maps[0]
    rerender(<LeafletFieldMap {...props} fieldKey="field-a" mode="edit" geometry={polygon} onGeometryChange={onGeometryChange} />)
    expect(map.fitBounds).toHaveBeenCalledTimes(1)
    expect(leaf.markers.slice(-3).every((marker) => marker.options.draggable)).toBe(true)
    act(() => leaf.markers.at(-3)?.drag())
    expect(onGeometryChange).toHaveBeenCalledWith(expect.objectContaining({ kind: 'polygon' }))
    expect(map.fitBounds).toHaveBeenCalledTimes(1)
    rerender(<LeafletFieldMap {...props} fieldKey="field-b" mode="edit" geometry={polygon} onGeometryChange={onGeometryChange} />)
    expect(map.fitBounds).toHaveBeenCalledTimes(2)
  })

  it('fits the selected field on the recreated map after StrictMode effect replay', () => {
    render(<StrictMode><LeafletFieldMap {...props} fieldKey="saved-field" mode="inspect" geometry={polygon} onGeometryChange={vi.fn()} /></StrictMode>)
    expect(leaf.maps).toHaveLength(2)
    expect(leaf.maps[0].fitBounds).toHaveBeenCalledOnce()
    expect(leaf.maps[1].fitBounds).toHaveBeenCalledOnce()
  })

  it('renders an untrusted field name as text in the point tooltip', () => {
    const fieldLabel = '<img src=x onerror=alert(1)> Field'
    render(<LeafletFieldMap {...props} fieldLabel={fieldLabel} mode="inspect" geometry={{ kind: 'point', point: points[0] }} onGeometryChange={vi.fn()} />)
    expect(leaf.pointTooltips).toHaveLength(1)
    expect(leaf.pointTooltips[0]).toBeInstanceOf(HTMLElement)
    expect(leaf.pointTooltips[0].textContent).toBe(fieldLabel)
    expect(leaf.pointTooltips[0].querySelector('img')).toBeNull()
  })

  it('does not load imagery while offline and removes it when connectivity changes', () => {
    const onGeometryChange = vi.fn()
    const { rerender } = render(<LeafletFieldMap {...props} allowNetwork={false} mode="inspect" geometry={empty} onGeometryChange={onGeometryChange} />)
    expect(leaf.tiles[0].addTo).not.toHaveBeenCalled()
    expect(screen.getByText('Offline map')).toBeInTheDocument()
    rerender(<LeafletFieldMap {...props} allowNetwork mode="inspect" geometry={empty} onGeometryChange={onGeometryChange} />)
    expect(leaf.tiles[0].addTo).toHaveBeenCalledOnce()
    rerender(<LeafletFieldMap {...props} allowNetwork={false} mode="inspect" geometry={empty} onGeometryChange={onGeometryChange} />)
    expect(leaf.maps[0].removeLayer).toHaveBeenCalledWith(leaf.tiles[0])
  })

  it('resizes the Leaflet viewport when its panel expands and disconnects on unmount', () => {
    let resize!: () => void
    const disconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: () => void) { resize = callback }
      observe = vi.fn()
      disconnect = disconnect
    })
    const { unmount } = render(<LeafletFieldMap {...props} mode="inspect" geometry={empty} onGeometryChange={vi.fn()} />)
    act(() => resize())
    expect(leaf.maps[0].invalidateSize).toHaveBeenCalledWith({ pan: false, debounceMoveend: true })
    unmount()
    expect(disconnect).toHaveBeenCalledOnce()
  })

  it('ignores a stale regional response after the viewport moves', async () => {
    let resolveFirst!: (payload: any) => void
    const first = new Promise<any>((resolve) => { resolveFirst = resolve })
    const regionFetch = vi.fn()
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ feature_collection: { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: { layer_id: 'canada_ecozones', name: 'new' } }] } }) })
    const fetchMock = vi.fn((url) => String(url) === '/api/geo/layers'
      ? Promise.resolve({ ok: true, json: async () => catalog }) : regionFetch(url))
    vi.stubGlobal('fetch', fetchMock)
    render(<LeafletFieldMap {...props} mode="inspect" geometry={empty} onGeometryChange={vi.fn()} />)
    await waitFor(() => expect(regionFetch).toHaveBeenCalledTimes(1))
    act(() => {
      leaf.maps[0].fire('moveend')
      leaf.maps[0].fire('moveend')
      leaf.maps[0].fire('moveend')
    })
    await waitFor(() => expect(regionFetch).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(leaf.regions.some((item) => item.properties.name === 'new')).toBe(true))
    resolveFirst({ ok: true, json: async () => ({ feature_collection: { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: { layer_id: 'canada_ecozones', name: 'stale' } }] } }) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })
    expect(leaf.regions.some((item) => item.properties.name === 'stale')).toBe(false)
  })
  it('changes basemap style without moving the viewport or changing the field', async () => {
    const changed = vi.fn()
    render(<LeafletFieldMap {...props} fieldKey="saved-field" mode="inspect" geometry={polygon} onGeometryChange={changed} />)
    const map = leaf.maps[0]
    const fitted = map.fitBounds.mock.calls.length
    const centered = map.setView.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: 'Streets' }))
    expect(leaf.tiles).toHaveLength(2)
    expect(map.removeLayer).toHaveBeenCalledWith(leaf.tiles[0])
    expect(leaf.tiles[1].addTo).toHaveBeenCalledWith(map)
    fireEvent.click(screen.getByRole('button', { name: 'Simple' }))
    expect(map.removeLayer).toHaveBeenCalledWith(leaf.tiles[1])
    expect(map.fitBounds).toHaveBeenCalledTimes(fitted)
    expect(map.setView).toHaveBeenCalledTimes(centered)
    expect(changed).not.toHaveBeenCalled()
  })

  it('stops viewport requests and ignores their results when all layers are hidden', async () => {
    let release!: (response: unknown) => void
    const request = new Promise(resolve => { release = resolve })
    const regionFetch = vi.fn(() => request)
    vi.stubGlobal('fetch', vi.fn((url) => String(url) === '/api/geo/layers'
      ? Promise.resolve({ ok: true, json: async () => catalog }) : regionFetch()))
    render(<LeafletFieldMap {...props} mode="inspect" geometry={empty} onGeometryChange={vi.fn()} />)
    await waitFor(() => expect(regionFetch).toHaveBeenCalledOnce())
    fireEvent.click(screen.getByRole('checkbox', { name: 'Canada ecozones' }))
    act(() => leaf.maps[0].fire('moveend'))
    await act(async () => { release({ ok: true, json: async () => ({ feature_collection: { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: { layer_id: 'canada_ecozones' } }] } }) }); await request })
    expect(regionFetch).toHaveBeenCalledOnce()
    expect(leaf.regions).toHaveLength(0)
  })

  it('closes appearance controls before Escape cancels a drawing', () => {
    const cancel = vi.fn()
    render(<LeafletFieldMap {...props} mode="boundary" geometry={polygon} onGeometryChange={vi.fn()} onCancelDrawing={cancel} />)
    const summary = screen.getByLabelText('Map appearance and layers')
    const menu = summary.closest('details')!
    menu.open = true
    fireEvent.keyDown(summary, { key: 'Escape' })
    expect(menu.open).toBe(false)
    expect(cancel).not.toHaveBeenCalled()
    fireEvent.keyDown(screen.getByRole('application'), { key: 'Escape' })
    expect(cancel).toHaveBeenCalledOnce()
  })

  it('changes layer shading without rebuilding source geometry', async () => {
    const features = [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [] }, properties: { layer_id: 'canada_ecozones', name: 'Zone' } }]
    vi.stubGlobal('fetch', vi.fn(async (url) => ({ ok: true, json: async () => String(url) === '/api/geo/layers' ? catalog : { feature_collection: { type: 'FeatureCollection', features } } })))
    render(<LeafletFieldMap {...props} mode="inspect" geometry={polygon} onGeometryChange={vi.fn()} />)
    await waitFor(() => expect(leaf.regions).toHaveLength(1))
    fireEvent.change(screen.getByRole('slider', { name: 'Layer shading' }), { target: { value: '60' } })
    expect(leaf.regions).toHaveLength(1)
  })

})
