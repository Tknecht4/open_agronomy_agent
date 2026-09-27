import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, MapPin, Pencil, Upload, Check } from 'lucide-react'
import { WorkspaceDialog } from './WorkspaceDialog'
import { estimatePolygonAcres, fieldGeometryIssue, validFieldPoint, type FieldGeometry, type MapMode } from './fieldGeometry'
import { apiUpload } from './api'

const LeafletFieldMap = lazy(() => import('./LeafletFieldMap').then(module => ({ default: module.LeafletFieldMap })))
export type NewFieldDraft = {
  name: string; crop: string; jurisdiction: string; region: string; concern: string;
  geometry: FieldGeometry; acres: string; notes: string;
}
type UploadFeature = { id: string; label: string; acres: number; geometry_type?: string }
type UploadGeometry = { type: string; coordinates?: unknown; geometry?: { type: string; coordinates?: unknown } }
type UploadGeoFeature = { type: 'Feature'; id?: string; geometry: UploadGeometry; properties?: Record<string, unknown> }
type BoundaryResponse = {
  geometry: UploadGeometry;
  filename: string; feature_count?: number; warnings?: string[]; selected_feature_id?: string;
  feature_summaries?: UploadFeature[];
  feature_collection?: { type: 'FeatureCollection'; features: UploadGeoFeature[] };
}

const coordinateValue = (raw: string): number | null => {
  const text = raw.trim()
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)) return null
  const value = Number(text)
  return Number.isFinite(value) ? value : null
}

export const importedFieldGeometry = (value: BoundaryResponse['geometry']): FieldGeometry => {
  const geometry = value.type === 'Feature' && value.geometry ? value.geometry : value
  if (geometry.type === 'Point' && Array.isArray(geometry.coordinates)) {
    const [lon, lat] = geometry.coordinates
    if (typeof lat === 'number' && typeof lon === 'number' && validFieldPoint({ lat, lon })) return { kind: 'point', point: { lat, lon } }
  }
  if (geometry.type === 'Polygon' && Array.isArray(geometry.coordinates)) {
    // A field ring with holes cannot be represented by the current editable map contract.
    if (geometry.coordinates.length !== 1) throw new Error('This boundary contains holes. Import a single exterior field boundary.')
    const ring = geometry.coordinates[0] as unknown[]
    if (!Array.isArray(ring)) throw new Error('Invalid polygon coordinates.')
    const points = ring.map(value => {
      if (!Array.isArray(value) || typeof value[0] !== 'number' || typeof value[1] !== 'number') throw new Error('Invalid boundary coordinates.')
      return { lat: value[1], lon: value[0] }
    })
    if (points.length > 1 && points[0].lat === points[points.length - 1]?.lat && points[0].lon === points[points.length - 1]?.lon) points.pop()
    const result: FieldGeometry = { kind: 'polygon', points, acres: estimatePolygonAcres(points) }
    const issue = fieldGeometryIssue(result)
    if (issue) throw new Error(issue)
    return result
  }
  throw new Error('Choose a single point or polygon. Multipart boundaries must be separated before editing.')
}

export function FieldSetupDialog({ onClose, onSave, allowNetwork, previousRegion }: {
  onClose: () => void; onSave: (draft: NewFieldDraft) => Promise<void>; allowNetwork: boolean;
  previousRegion?: { region: string; jurisdiction: string };
}) {
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [crop, setCrop] = useState('')
  const [jurisdiction, setJurisdiction] = useState('')
  const [region, setRegion] = useState('')
  const [geometry, setGeometry] = useState<FieldGeometry>({ kind: 'none' })
  const [mode, setMode] = useState<MapMode>('point')
  const [latitude, setLatitude] = useState('')
  const [longitude, setLongitude] = useState('')
  const [status, setStatus] = useState('Place a pin to start. A full boundary is optional.')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [upload, setUpload] = useState<BoundaryResponse | null>(null)
  const [uploadNote, setUploadNote] = useState('')
  const [selectedFeature, setSelectedFeature] = useState('')
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const mountedRef = useRef(true)
  const requestIdRef = useRef(0)
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false; requestIdRef.current += 1 }
  }, [])
  const issue = fieldGeometryIssue(geometry)
  const dirty = Boolean(name || crop || jurisdiction || region || latitude || longitude || uploadNote || geometry.kind !== 'none')
  const requestClose = () => {
    if (busy) return
    if (dirty) setConfirmDiscard(true)
    else onClose()
  }
  const setManualGeometry = (next: FieldGeometry) => {
    if (busy) return
    requestIdRef.current += 1
    setGeometry(next); setUpload(null); setUploadNote(''); setSelectedFeature('')
  }
  const chooseFeature = (payload: BoundaryResponse, id: string) => {
    const features = payload.feature_collection?.features
    const selected = features?.find(feature => String(feature.id ?? '') === id)
      || (features?.length === 1 && !id ? features[0] : undefined)
    if (features?.length && !selected) throw new Error('The selected field was not found in this upload. Choose another field or import again.')
    if (!features?.length && (payload.feature_count || payload.feature_summaries?.length || 0) > 1) {
      throw new Error('This file contains multiple fields, but their boundaries are unavailable. Import one field at a time.')
    }
    const next = importedFieldGeometry(selected?.geometry || payload.geometry)
    setGeometry(next); setMode('inspect'); setSelectedFeature(id)
    const label = payload.feature_summaries?.find(feature => feature.id === id)?.label
    if (!name && label) setName(label)
    setUploadNote(`Imported from ${payload.filename}${label ? ` · ${label}` : ''}. Check the boundary before saving.`)
  }
  const importFile = async (file?: File) => {
    if (!file) return
    const requestId = ++requestIdRef.current
    setBusy(true); setError('')
    try {
      const form = new FormData(); form.append('file', file)
      const payload = await apiUpload<BoundaryResponse>('/api/geo/boundary-upload?intersect=false', form)
      if (!mountedRef.current || requestId !== requestIdRef.current) return
      chooseFeature(payload, payload.selected_feature_id || payload.feature_summaries?.[0]?.id || '')
      setUpload(payload)
    } catch (cause) { if (mountedRef.current && requestId === requestIdRef.current) setError(String((cause as Error)?.message || cause)) }
    finally { if (mountedRef.current && requestId === requestIdRef.current) setBusy(false) }
  }
  const save = async () => {
    if (busy) return
    setBusy(true); setError('')
    try {
      await onSave({ name: name.trim(), crop: crop.trim(), region: region.trim(), jurisdiction: jurisdiction.trim(),
        geometry, acres: geometry.kind === 'polygon' ? String(Math.round(geometry.acres)) : '', concern: '', notes: uploadNote })
    } catch (cause) { if (mountedRef.current) setError(String((cause as Error)?.message || cause)) }
    finally { if (mountedRef.current) setBusy(false) }
  }
  return <WorkspaceDialog title="Add a field" onClose={requestClose} busy={busy} wide>
    <ol className="setup-steps" aria-label="Field setup progress">
      {['Name & crop', 'Location', 'Review'].map((label, index) => <li key={label} aria-current={step === index ? 'step' : undefined} className={step === index ? 'active' : step > index ? 'complete' : ''}>
        <span>{step > index ? <Check size={14} /> : index + 1}</span>{label}
      </li>)}</ol>
    <div className="setup-body">
      {error ? <p role="alert" className="inline-error">{error}</p> : null}
      {confirmDiscard ? <div className="setup-discard-confirm" role="alertdialog" aria-label="Discard field draft?">
        <p>Discard this field draft? Your entries and unsaved location will be lost.</p>
        <button type="button" autoFocus onClick={() => setConfirmDiscard(false)}>Keep editing</button>
        <button type="button" onClick={onClose}>Discard draft</button>
      </div> : null}
      {step === 0 ? <div className="setup-details">
        <div><span className="eyebrow">A small start</span><h3>Make it yours.</h3><p>A name and a location are enough. Add observations and measurements as you go.</p></div>
        <label>Field name<input data-dialog-initial-focus value={name} onChange={event => setName(event.target.value)} placeholder="e.g. North quarter" maxLength={160} /></label>
        <label>Crop <span className="optional">optional</span><input value={crop} list="field-crops" onChange={event => setCrop(event.target.value)} placeholder="Choose or type a crop" /></label>
        <datalist id="field-crops">{['Barley', 'Canola', 'Wheat', 'Oats', 'Corn', 'Soybean', 'Lentils', 'Peas', 'Forage'].map(value => <option key={value} value={value} />)}</datalist>
        <details className="setup-region"><summary>Region & province <span className="optional">optional</span></summary>
          <div className="field-grid"><label>Region<input value={region} onChange={event => setRegion(event.target.value)} placeholder="County or municipality" /></label>
          <label>Province / jurisdiction<input value={jurisdiction} onChange={event => setJurisdiction(event.target.value)} placeholder="e.g. Alberta" /></label></div>
          {previousRegion?.jurisdiction ? <button type="button" className="text-button" onClick={() => { setJurisdiction(previousRegion.jurisdiction); setRegion(previousRegion.region) }}>Use {previousRegion.region || previousRegion.jurisdiction} from my previous field</button> : null}
        </details>
      </div> : null}
      {step === 1 ? <div className="setup-location">
        <div className="setup-location-heading"><div><h3>Where is this field?</h3><p>Use a pin now. You can refine the boundary later.</p></div></div>
        <div className="location-methods" role="group" aria-label="Location method">
          <button type="button" disabled={busy} aria-pressed={mode === 'point'} onClick={() => { setMode('point'); setManualGeometry({ kind: 'none' }); setStatus('Click the map to place a pin.') }}><MapPin size={16} /> Place a pin</button>
          <button type="button" disabled={busy} aria-pressed={mode === 'boundary'} onClick={() => { setMode('boundary'); setManualGeometry({ kind: 'none' }); setStatus('Add corners, then finish your boundary.') }}><Pencil size={16} /> Draw boundary</button>
          <label className="upload-button"><Upload size={16} /> Import boundary<input type="file" aria-label="Import field boundary" accept=".geojson,.json,.zip,.gpkg" disabled={busy} onChange={event => { void importFile(event.target.files?.[0]); event.target.value = '' }} /></label>
        </div>
        <div className="setup-map"><Suspense fallback={<p>Loading map…</p>}><LeafletFieldMap fieldKey="new-field-wizard" mode={busy ? 'inspect' : mode} scenarioId="new-field" fieldLabel={name || 'New field'} geometry={geometry}
          regionalCandidates={[]} regionalFeatureCollection={null} onGeometryChange={setManualGeometry} onStatusChange={setStatus} allowNetwork={allowNetwork}
          onFinishBoundary={() => setMode('edit')} onCancelDrawing={() => { setManualGeometry({ kind: 'none' }); setMode('point') }} /></Suspense></div>
        <p role="status" className="setup-map-status">{status}</p>
        <details className="coordinate-entry"><summary>Enter coordinates instead</summary><div className="field-grid">
          <label>Latitude<input inputMode="decimal" value={latitude} onChange={event => setLatitude(event.target.value)} placeholder="53.3" /></label>
          <label>Longitude<input inputMode="decimal" value={longitude} onChange={event => setLongitude(event.target.value)} placeholder="-113.6" /></label>
          <button type="button" disabled={busy} onClick={() => {
            const lat = coordinateValue(latitude); const lon = coordinateValue(longitude)
            if (lat === null || lon === null || !validFieldPoint({ lat, lon })) { setError('Enter a latitude between −90 and 90 and longitude between −180 and 180.'); return }
            setError(''); setManualGeometry({ kind: 'point', point: { lat, lon } }); setMode('inspect'); setStatus('Coordinates set. Review the location before saving.')
          }}>Use coordinates</button></div></details>
        {upload?.feature_summaries && upload.feature_summaries.length > 1 ? <label>Field in this file<select value={selectedFeature} onChange={event => { try { chooseFeature(upload, event.target.value); setError('') } catch (cause) { setError((cause as Error).message) } }}>{upload.feature_summaries.map(feature => <option key={feature.id} value={feature.id}>{feature.label}</option>)}</select></label> : null}
        {uploadNote ? <p className="prefill-note">{uploadNote}</p> : null}
        {upload?.warnings?.map(warning => <p key={warning} className="prefill-note">{warning}</p>)}
      </div> : null}
      {step === 2 ? <div className="setup-review"><span className="eyebrow">Ready when you are</span><h3>{name}</h3>
        <dl><div><dt>Crop</dt><dd>{crop || 'Not specified'}</dd></div><div><dt>Region</dt><dd>{[region, jurisdiction].filter(Boolean).join(', ') || 'Not specified'}</dd></div>
          <div><dt>Location</dt><dd>{geometry.kind === 'point' ? `${geometry.point.lat.toFixed(5)}, ${geometry.point.lon.toFixed(5)}` : geometry.kind === 'polygon' ? `${geometry.points.length} boundary corners` : 'Missing'}</dd></div>
          <div><dt>Area</dt><dd>{geometry.kind === 'polygon' ? `About ${Math.round(geometry.acres).toLocaleString()} acres · calculated from boundary` : 'Not measured · add a boundary later'}</dd></div></dl>
        <p>Only the details you entered will be saved. Regional maps add context; they never replace field observations.</p>
        {uploadNote ? <p className="prefill-note">{uploadNote}</p> : null}
      </div> : null}
    </div>
    <footer className="setup-footer"><button type="button" className="secondary-button" disabled={busy} onClick={() => step ? setStep(step - 1) : requestClose()}><ArrowLeft size={16} />{step ? 'Back' : 'Cancel'}</button>
      <span>Step {step + 1} of 3</span>
      <button type="button" className="primary-button" disabled={busy || !name.trim() || (step > 0 && issue !== null)} onClick={() => step < 2 ? setStep(step + 1) : void save()}>
        {busy ? 'Saving…' : step < 2 ? 'Continue' : 'Save field'}<ArrowRight size={16} /></button></footer>
  </WorkspaceDialog>
}
