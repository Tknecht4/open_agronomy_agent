import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { apiGet } from './api'
import { displayDate } from './fieldLabels'
import { readableError } from './farmTypes'
import type { FieldGeometry } from './fieldGeometry'
import { recoverableLazy as lazy } from './WorkspaceSectionBoundary'
import './FieldImageryAnalyticsPanel.css'

const LeafletFieldMap = lazy(() => import('./LeafletFieldMap').then(m => ({ default: m.LeafletFieldMap })), 'Image map')
type ColorStop = { value: number; color: string }
type ImageColorScale = { stops: ColorStop[] }
export type ImageryOverlay = {
  display_crs: string; display_resampling: string; png_base64: string
  bounds: [[number, number], [number, number]]; boundary: string; color_scale?: ImageColorScale
}
export type FieldMapImage = { overlay: ImageryOverlay; label: string; geometryKey: string }
export type ShowFieldImage = (value: FieldMapImage | null) => void
type Overlay = ImageryOverlay & { chip_hash: string; geometry_revision_id: string }

export function ImageColorLegend({ scale }: { scale?: ImageColorScale }) {
  const validStop = (stop: ColorStop) => Number.isFinite(stop.value) && /^#[0-9a-f]{6}$/i.test(stop.color)
  if (!Array.isArray(scale?.stops) || scale.stops.length < 2 || !scale.stops.every(validStop)) return null
  const first = scale.stops[0].value
  const last = scale.stops[scale.stops.length - 1].value
  if (first >= last) return null
  const position = (value: number) => `${100 * (value - first) / (last - first)}%`
  const stops = scale.stops.map(({ value, color }) => `${color} ${position(value)}`).join(', ')

  return <div className="image-color-legend" role="group" aria-label="Image colour scale">
    <div className="image-color-ramp" aria-hidden="true" style={{ backgroundImage: `linear-gradient(to right, ${stops})` }} />
    <div className="image-color-ticks">
      {scale.stops.map(({ value }) => <span key={value} style={{ left: position(value) }}>{value}</span>)}
    </div>
  </div>
}

export function decodeImageryOverlay(value: ImageryOverlay): Blob {
  if (value.display_crs !== 'EPSG:3857' || value.display_resampling !== 'nearest'
    || !Array.isArray(value.bounds) || value.bounds.length !== 2 || value.bounds.some(point => !Array.isArray(point) || point.length !== 2 || point.some(number => !Number.isFinite(number)))
    || !value.png_base64 || value.png_base64.length > 3 * 1024 * 1024) throw new Error('The map image is invalid.')
  const bytes = Uint8Array.from(atob(value.png_base64), character => character.charCodeAt(0))
  if (![137, 80, 78, 71, 13, 10, 26, 10].every((byte, index) => bytes[index] === byte)) throw new Error('The overlay was not a PNG image.')
  return new Blob([bytes], { type: 'image/png' })
}

export default function ImageryMapPreview({ jobId, chipHash, geometry, geometryKey, acquiredAt, allowNetwork, onShowImage }: {
  jobId: string; chipHash: string; geometry: FieldGeometry; geometryKey: string; acquiredAt: string; allowNetwork: boolean; onShowImage?: ShowFieldImage
}) {
  const [overlay, setOverlay] = useState<Overlay | null>(null)
  const [url, setUrl] = useState('')
  const [opacity, setOpacity] = useState(.8)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const active = useRef(true)
  const objectUrl = useRef('')
  useEffect(() => { active.current = true; return () => { active.current = false; if (objectUrl.current) URL.revokeObjectURL(objectUrl.current) } }, [])
  const load = async () => {
    setBusy(true); setError('')
    try {
      const value = await apiGet<Overlay>(`/api/imagery-jobs/${encodeURIComponent(jobId)}/overlay`)
      if (!active.current) return
      if (value.chip_hash !== chipHash || value.geometry_revision_id !== geometryKey) throw new Error('The map image did not match this analysis.')
      if (onShowImage) {
        onShowImage({ overlay: value, label: `NDVI · ${displayDate(acquiredAt)}`, geometryKey })
        return
      }
      const next = URL.createObjectURL(decodeImageryOverlay(value))
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
      objectUrl.current = next; setUrl(next); setOverlay(value)
    } catch (cause) { if (active.current) setError(readableError(cause)) } finally { if (active.current) setBusy(false) }
  }
  const layer = useMemo(() => overlay && url ? { url, bounds: overlay.bounds, opacity } : undefined, [overlay, url, opacity])
  return <section className="imagery-map-preview" aria-label="Image on field map">
    {!overlay ? <button type="button" disabled={busy} onClick={() => void load()}>{busy ? 'Preparing image…' : onShowImage ? 'Show NDVI on map' : 'View image on field map'}</button> : <>
      <h4>NDVI · {displayDate(acquiredAt)}</h4>
      <label>Image opacity<input aria-label="Image opacity" type="range" min="0" max="1" step="0.05" value={opacity} onChange={event => setOpacity(Number(event.target.value))} /></label>
      <div className="farm-map"><Suspense fallback={<p>Loading image map…</p>}><LeafletFieldMap mode="inspect" scenarioId="analysis" fieldLabel="Analysis boundary" fieldKey={geometryKey} geometry={geometry} analyticalOverlay={layer} regionalCandidates={[]} regionalFeatureCollection={null} onGeometryChange={() => {}} onStatusChange={() => {}} allowNetwork={allowNetwork} /></Suspense></div>
      <ImageColorLegend scale={overlay.color_scale} />
      <small>{overlay.boundary} Basemap imagery has separate acquisition dates.</small>
    </>}
    {error ? <p role="alert">{error}</p> : null}
  </section>
}
