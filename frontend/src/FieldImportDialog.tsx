import { Suspense, useRef, useState } from 'react'
import { apiPost, apiUpload } from './api'
import { WorkspaceDialog } from './WorkspaceDialog'
import { recoverableLazy as lazy } from './WorkspaceSectionBoundary'
import { importedFieldGeometry } from './FieldSetupDialog'
import { fieldArea, readableError, type Farm } from './farmTypes'

const LeafletFieldMap = lazy(() => import('./LeafletFieldMap').then(m => ({ default: m.LeafletFieldMap })), 'Import map')
type Feature = { id: string; label: string; acres: number; geometry_type: string; properties: Record<string, unknown>; duplicate: boolean; existing_field_id?: string }
type Preview = { id: string; filename: string; features: Feature[]; warnings: string[]; coordinate_reference: unknown; feature_collection: { features: Array<{ id: string; geometry: { type: string; coordinates?: unknown } }> } }
type Receipt = { features: Array<{ feature_id: string; field_id: string; status: string }> }

export default function FieldImportDialog({ farms, initialFarm, allowNetwork, onClose, onSaved }: {
  farms: Farm[]; initialFarm: string; allowNetwork: boolean; onClose: () => void; onSaved: () => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [names, setNames] = useState<Record<string, string>>({})
  const [farmId, setFarmId] = useState(initialFarm === 'unassigned' ? '' : initialFarm)
  const [jurisdiction, setJurisdiction] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const operation = useRef(crypto.randomUUID())
  const attempted = useRef<object | null>(null)
  const upload = async (file?: File) => {
    if (!file) return
    setBusy(true); setError('')
    try {
      const form = new FormData(); form.append('file', file)
      const value = await apiUpload<Preview>('/api/field-imports/preview', form)
      setPreview(value); setSelected(Object.fromEntries(value.features.map(item => [item.id, !item.duplicate])))
      setNames(Object.fromEntries(value.features.map(item => [item.id, item.label])))
      attempted.current = null; operation.current = crypto.randomUUID()
    } catch (cause) { setError(readableError(cause)) } finally { setBusy(false) }
  }
  const commit = async () => {
    if (!preview) return
    setBusy(true); setError('')
    try {
      // Preserve the exact request on a failed transport; never silently create twice.
      attempted.current ||= { operation_id: operation.current, farm_id: farmId || null, jurisdiction,
        features: preview.features.filter(item => selected[item.id]).map(item => ({ feature_id: item.id, name: names[item.id].trim() })) }
      setReceipt(await apiPost<Receipt>(`/api/field-imports/${preview.id}/commit`, attempted.current))
      onSaved()
    } catch (cause) { setError(readableError(cause)) } finally { setBusy(false) }
  }
  const fields = preview?.feature_collection.features.filter(item => selected[item.id]).map(item => ({ id: item.id, name: names[item.id], geometry: importedFieldGeometry(item.geometry) })) || []
  const locked = busy || Boolean(attempted.current)
  return <WorkspaceDialog title="Import fields" wide busy={busy} onClose={onClose}>
    {error ? <p role="alert" className="farm-error">{error}</p> : null}
    {receipt ? <div className="farm-form"><h3>Import saved</h3><p>{receipt.features.filter(item => item.status === 'created').length} fields created. {receipt.features.filter(item => item.status === 'duplicate_skipped').length} existing boundaries skipped.</p><p>Source attributes and complete boundaries were retained. Confirm crops in each field’s season details.</p><button type="button" className="primary-button" onClick={onClose}>View fields</button></div> : <div className="farm-form">
      <p>Review each feature, select the fields to save, and choose a farm. Holes and multipart boundaries stay intact. Source crop attributes remain unconfirmed.</p>
      <label>Boundary file<input data-dialog-initial-focus type="file" accept=".geojson,.json,.gpkg,.zip" disabled={locked} onChange={event => { void upload(event.target.files?.[0]); event.target.value = '' }} /></label>
      {busy ? <p role="status">{preview ? 'Saving reviewed fields…' : 'Reading boundaries…'}</p> : null}
      {preview ? <>
        <label>Assign to farm<select value={farmId} disabled={locked} onChange={event => setFarmId(event.target.value)}><option value="">Unassigned</option>{farms.filter(item => !item.archived).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>Province / jurisdiction (optional)<input value={jurisdiction} disabled={locked} onChange={event => setJurisdiction(event.target.value)} placeholder="Confirm if known, e.g. Alberta" maxLength={120} /></label>
        <p>{preview.filename} · {preview.features.length} features. Identical saved boundaries are skipped on commit.</p>
        {preview.warnings.filter(warning => !warning.includes('selected by default')).map(warning => <p key={warning}>{warning}</p>)}
        <div className="farm-table-scroll"><table className="farm-field-table"><thead><tr><th>Include</th><th>Field name</th><th>Boundary</th><th>Source attributes</th></tr></thead><tbody>{preview.features.map(item => <tr key={item.id}><td><input type="checkbox" aria-label={`Import ${item.label}`} checked={Boolean(selected[item.id])} disabled={locked || item.duplicate} onChange={event => setSelected({ ...selected, [item.id]: event.target.checked })} />{item.duplicate ? <small>Duplicate</small> : null}</td><td><input aria-label={`Name for ${item.label}`} value={names[item.id]} maxLength={160} disabled={locked} onChange={event => setNames({ ...names, [item.id]: event.target.value })} /></td><td>{item.geometry_type}<small>{fieldArea(item.acres == null ? null : item.acres * 4046.8564224)}</small></td><td><details><summary>Review attributes</summary><pre>{JSON.stringify(item.properties, null, 2)}</pre></details></td></tr>)}</tbody></table></div>
        <div className="farm-map"><Suspense fallback={<p>Loading import map…</p>}><LeafletFieldMap mode="inspect" scenarioId="boundary-import" fieldKey={preview.id} fieldLabel="Selected imports" geometry={{ kind: 'none' }} fieldCollection={fields} collectionKey={preview.id} regionalCandidates={[]} regionalFeatureCollection={null} onGeometryChange={() => {}} onStatusChange={() => {}} allowNetwork={allowNetwork} /></Suspense></div>
        <details><summary>Coordinate reference</summary><pre>{JSON.stringify(preview.coordinate_reference, null, 2)}</pre></details>
        <button type="button" className="primary-button" disabled={busy || !fields.length || preview.features.some(item => selected[item.id] && !names[item.id]?.trim())} onClick={() => void commit()}>{attempted.current ? 'Retry the same save' : `Save ${fields.length} ${fields.length === 1 ? 'field' : 'fields'}`}</button>
      </> : null}
    </div>}
  </WorkspaceDialog>
}
