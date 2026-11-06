import { useEffect, useRef, useState } from 'react'
import { completeBoundaryGeometry, estimatePolygonAcres, validFieldPoint, type FieldGeometry } from './fieldGeometry'

/** Keyboard path to the same draft geometry used by the map, with bounded undo. */
export function GeometryCoordinateEditor({ geometry, pointMode = false, onChange }: { geometry: FieldGeometry; pointMode?: boolean; onChange: (value: FieldGeometry) => void }) {
  const [part, setPart] = useState(0), [ring, setRing] = useState(0), [vertex, setVertex] = useState(0)
  const [lat, setLat] = useState(''), [lon, setLon] = useState(''), [error, setError] = useState('')
  const history = useRef<FieldGeometry[]>([structuredClone(geometry)]), position = useRef(0), replay = useRef(false)
  const [, refresh] = useState(0)
  const polygons = geometry.kind === 'geojson' ? geometry.geojson.type === 'Polygon' ? [geometry.geojson.coordinates] : geometry.geojson.coordinates : null
  const points = polygons ? (polygons[part]?.[ring] || []).slice(0,-1).map(([lon,lat]) => ({lat,lon})) : geometry.kind === 'polygon' ? geometry.points : geometry.kind === 'point' ? [geometry.point] : []
  const selected = points[Math.min(vertex, Math.max(0, points.length - 1))]
  useEffect(() => { setLat(selected ? String(selected.lat) : ''); setLon(selected ? String(selected.lon) : '') }, [selected?.lat, selected?.lon, vertex, part, ring])
  useEffect(() => {
    if (replay.current) { replay.current = false; return }
    if (JSON.stringify(history.current[position.current]) !== JSON.stringify(geometry)) {
      history.current = [...history.current.slice(0,position.current + 1), structuredClone(geometry)].slice(-50)
      position.current = history.current.length - 1; refresh(v => v + 1)
    }
  }, [geometry])
  const restore = (delta: number) => { position.current += delta; replay.current = true; onChange(structuredClone(history.current[position.current])); refresh(v => v + 1) }
  const apply = (action: 'replace' | 'add' | 'remove') => {
    try {
      const point = {lat:Number(lat),lon:Number(lon)}
      if (action !== 'remove' && (!lat.trim() || !lon.trim() || !validFieldPoint(point))) throw new Error('Enter valid latitude and longitude. Blank is not zero.')
      if (pointMode || geometry.kind === 'point') { onChange({kind:'point',point}); setError(''); return }
      const next = points.map(p => ({...p})), index = Math.min(vertex, Math.max(0, points.length - 1))
      if (action === 'remove') next.splice(index,1)
      else if (action === 'add') next.splice(points.length ? index + 1 : 0,0,point)
      else next[index] = point
      if (polygons && geometry.kind === 'geojson') {
        if (next.length < 3) throw new Error('A retained ring needs at least three vertices. Other parts and holes are preserved.')
        const edited = structuredClone(geometry.geojson)
        const target = edited.type === 'Polygon' ? [edited.coordinates] : edited.coordinates
        target[part][ring] = [...next,next[0]].map(p => [p.lon,p.lat])
        onChange(completeBoundaryGeometry(edited))
      } else onChange({kind:'polygon', points:next, acres:estimatePolygonAcres(next)})
      setVertex(Math.max(0, Math.min(action === 'add' ? index + 1 : index, next.length - 1))); setError('')
    } catch(cause) { setError((cause as Error).message) }
  }
  return <details className="geometry-coordinate-editor"><summary>Edit coordinates with keyboard</summary>
    <p>Edits update the map draft. Review it, then save or cancel. Coordinates use WGS84 latitude and longitude.</p>
    <div className="geometry-coordinate-controls">
      {polygons ? <><label>Polygon<select value={part} onChange={e => {setPart(Number(e.target.value));setRing(0);setVertex(0)}}>{polygons.map((_,i)=><option key={i} value={i}>Part {i+1}</option>)}</select></label><label>Ring<select value={ring} onChange={e=>{setRing(Number(e.target.value));setVertex(0)}}>{polygons[part]?.map((_,i)=><option key={i} value={i}>{i ? `Hole ${i}` : 'Outer boundary'}</option>)}</select></label></> : null}
      {!pointMode && geometry.kind !== 'point' && points.length ? <label>Vertex<select value={Math.min(vertex,points.length-1)} onChange={e=>setVertex(Number(e.target.value))}>{points.map((_,i)=><option key={i} value={i}>Vertex {i+1}</option>)}</select></label> : null}
      <label>Draft latitude<input inputMode="decimal" value={lat} onChange={e=>setLat(e.target.value)} /></label><label>Draft longitude<input inputMode="decimal" value={lon} onChange={e=>setLon(e.target.value)} /></label>
      <button type="button" onClick={()=>apply('replace')}>{pointMode || geometry.kind === 'point' ? 'Set point' : 'Update vertex'}</button>
      {!pointMode && geometry.kind !== 'point' ? <><button type="button" onClick={()=>apply('add')}>Add vertex after</button><button type="button" disabled={!points.length} onClick={()=>apply('remove')}>Remove vertex</button></> : null}
      <button type="button" disabled={position.current === 0} onClick={()=>restore(-1)}>Undo coordinate edit</button><button type="button" disabled={position.current >= history.current.length-1} onClick={()=>restore(1)}>Redo coordinate edit</button>
    </div>{error ? <p role="alert">{error}</p> : null}
  </details>
}
