import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Plus, ArrowLeft, MapPin, Search } from 'lucide-react'
import { apiGet, apiPatch, apiPost } from './api'
import { recoverableLazy as lazy } from './WorkspaceSectionBoundary'
import { WorkspaceDialog } from './WorkspaceDialog'
import { fieldArea, readableError, type Farm, type FarmOverview } from './farmTypes'
import type { FieldGeometry } from './fieldGeometry'
import './FarmWorkspace.css'

const LeafletFieldMap = lazy(() => import('./LeafletFieldMap').then(m => ({ default: m.LeafletFieldMap })), 'Farm map')
const FieldImportDialog = lazy(() => import('./FieldImportDialog'), 'Boundary import')
const FieldDossier = lazy(() => import('./FieldDossier'), 'Field detail')
const FarmRecords = lazy(() => import('./FarmRecords'), 'Farm records')
const emptyGeometry: FieldGeometry = { kind: 'none' }
const readScope = () => {
  const query = new URLSearchParams(window.location.hash.split('?')[1] || '')
  const year = Number(query.get('season'))
  return { farm: query.get('farm') || '', field: query.get('field') || '',
    season: year >= 1900 && year <= 2200 ? year : new Date().getFullYear(),
    tab: query.get('tab') || 'overview', query: query.get('q') || '' }
}

export default function FarmWorkspace({ mode, allowNetwork, refreshKey, onAddField, onEditField, onAsk, onGeneralQuestion, onFieldsImported }: {
  mode: 'farms' | 'fields' | 'records'; allowNetwork: boolean; refreshKey: string
  onAddField: (farmId: string | null) => void; onEditField: (fieldId: string) => void
  onAsk: (fieldId: string, question?: string, season?: number) => void; onGeneralQuestion: () => void; onFieldsImported: () => void
}) {
  const [scope, setScope] = useState(readScope)
  const [farms, setFarms] = useState<Farm[]>([])
  const [overview, setOverview] = useState<FarmOverview | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [importOpen, setImportOpen] = useState(false)
  const [editFarm, setEditFarm] = useState<Farm | null>(null)
  const [archived, setArchived] = useState(false)
  const [newFarm, setNewFarm] = useState(false)
  const [farmName, setFarmName] = useState('')
  const [saving, setSaving] = useState(false)
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState('name')
  const [unit, setUnit] = useState<'ac' | 'ha'>(() => window.localStorage.getItem('open-agronomy.area-unit') === 'ha' ? 'ha' : 'ac')
  const [selected, setSelected] = useState('')
  const [coordinate, setCoordinate] = useState('')
  const [searchPoint, setSearchPoint] = useState<FieldGeometry>(emptyGeometry)
  const request = useRef(0)
  const farm = farms.find(item => item.id === scope.farm)
  const scopedFields = useMemo(() => (overview?.fields || []).filter(field => !scope.farm || (scope.farm === 'unassigned' ? !field.farm_id : field.farm_id === scope.farm)), [overview, scope.farm])
  const selectedField = scopedFields.find(field => field.id === selected)
  const fields = useMemo(() => scopedFields.filter(field => {
    const matches = `${field.name} ${field.crop || ''} ${farms.find(f => f.id === field.farm_id)?.name || 'unassigned'}`.toLowerCase().includes(scope.query.toLowerCase())
    return matches && (filter === 'all' || filter === 'boundary' && field.geometry_status !== 'boundary' || filter === 'crop' && !field.crop || filter === 'records' && field.record_count > 0 || filter === 'context' && (field.context_review_count || 0) > 0)
  }).sort((a, b) => sort === 'records' ? (b.last_record_at || '').localeCompare(a.last_record_at || '') : sort === 'crop' ? (a.crop || '').localeCompare(b.crop || '') || a.name.localeCompare(b.name) : a.name.localeCompare(b.name)), [scopedFields, scope.query, filter, sort, farms])
  const coverage = scope.farm ? overview?.farm_coverage?.[scope.farm] : overview?.coverage
  const mapFields = useMemo(() => fields.map(({ id, name, geometry }) => ({ id, name, geometry })), [fields])
  const updateScope = (patch: Partial<typeof scope>) => {
    const next = { ...scope, ...patch }
    setScope(next)
    const query = new URLSearchParams({ season: String(next.season) })
    if (next.farm) query.set('farm', next.farm)
    if (next.field) query.set('field', next.field)
    if (next.tab !== 'overview') query.set('tab', next.tab)
    if (next.query) query.set('q', next.query)
    window.history.pushState(null, '', `#${mode}?${query}`)
  }
  useEffect(() => {
    const changed = () => setScope(readScope())
    window.addEventListener('hashchange', changed); window.addEventListener('popstate', changed)
    return () => { window.removeEventListener('hashchange', changed); window.removeEventListener('popstate', changed) }
  }, [])
  useEffect(() => {
    const id = ++request.current
    setLoading(true); setError('')
    Promise.all([apiGet<{ farms: Farm[] }>('/api/farms'), apiGet<FarmOverview>(`/api/farms/overview?season=${scope.season}`)])
      .then(([farmResult, result]) => { if (!Array.isArray(farmResult.farms) || !Array.isArray(result.fields)) throw new Error('Saved farm information could not be read. Retry the connection.'); if (id === request.current) { setFarms(farmResult.farms); setOverview(result) } })
      .catch(cause => { if (id === request.current) setError(readableError(cause)) })
      .finally(() => { if (id === request.current) setLoading(false) })
    return () => { request.current += 1 }
  }, [scope.season, refresh, refreshKey])
  const saveFarm = async () => {
    setSaving(true); setError('')
    try {
      const created = editFarm ? await apiPatch<Farm>(`/api/farms/${encodeURIComponent(editFarm.id)}`, { name: farmName.trim(), archived, expected_revision: editFarm.revision }) : await apiPost<Farm>('/api/farms', { name: farmName.trim() })
      setFarms(current => [...current.filter(item => item.id !== created.id), created]); updateScope({ farm: created.archived ? '' : created.id, field: '' }); setNewFarm(false); setEditFarm(null); setFarmName(''); setRefresh(v => v + 1)
    } catch (cause) { setError(readableError(cause)) } finally { setSaving(false) }
  }
  const openField = (id: string, tab = 'overview') => { setSelected(id); updateScope({ field: id, tab }) }
  return <section className="farm-workspace" aria-label="Farm workspace">
    <div className="farm-scope-bar">
      <label>Farm<select aria-label="Farm" value={scope.farm} onChange={event => { updateScope({ farm: event.target.value, field: '' }); setSelected(''); setSearchPoint(emptyGeometry) }}>
        <option value="">All farms</option><option value="unassigned">Unassigned fields</option>{farms.map(item => <option key={item.id} value={item.id}>{item.name}{item.archived ? " (archived)" : ""}</option>)}
      </select></label>
      <label>Season<input aria-label="Season" type="number" min="1900" max="2200" value={scope.season} onChange={event => { const year = Number(event.target.value); if (year >= 1900 && year <= 2200) updateScope({ season: year }) }} /></label>
      <label>Area units<select aria-label="Area units" value={unit} onChange={event => { const value = event.target.value as 'ac' | 'ha'; setUnit(value); window.localStorage.setItem('open-agronomy.area-unit', value) }}><option value="ac">Acres</option><option value="ha">Hectares</option></select></label>
      <div className="farm-actions">{farm ? <button type="button" onClick={() => { setEditFarm(farm); setFarmName(farm.name); setArchived(Boolean(farm.archived)); setNewFarm(true) }}>Manage farm</button> : null}<button type="button" onClick={() => setImportOpen(true)}>Import fields</button><button type="button" onClick={() => { setEditFarm(null); setFarmName(''); setArchived(false); setNewFarm(true); setError('') }}>Create farm</button><button type="button" className="primary-button" onClick={() => onAddField(farm?.id || null)}><Plus size={16} />Add field</button></div>
    </div>
    {error ? <div role="alert" className="farm-error">{error}<button type="button" onClick={() => setRefresh(v => v + 1)}>Retry</button></div> : null}
    {loading ? <p role="status">Loading saved farm information…</p> : null}
    {!overview ? null : scope.field ? <>
      <button type="button" className="farm-back" onClick={() => updateScope({ field: '', tab: 'overview' })}><ArrowLeft size={16} />Back to {farm?.name || 'fields'}</button>
      <Suspense fallback={<p role="status">Opening field…</p>}><FieldDossier key={scope.field} fieldId={scope.field} season={scope.season} tab={scope.tab} farms={farms} allowNetwork={allowNetwork} unit={unit}
        onTab={tab => updateScope({ tab })} onChanged={() => setRefresh(v => v + 1)} onEdit={() => onEditField(scope.field)} onAsk={question => onAsk(scope.field, question, scope.season)} /></Suspense>
    </> : mode === 'records' ? <Suspense fallback={<p>Loading records…</p>}><FarmRecords key={`${scope.farm}:${scope.season}`} fields={scopedFields} farmId={scope.farm} season={scope.season} onOpenField={id => openField(id, 'records')} /></Suspense> : <>
      {mode === 'farms' && !scope.farm ? <div className="farm-directory" aria-label="Farms">
        {farms.filter(item => !item.archived).map(item => {
          const members = overview.fields.filter(field => field.farm_id === item.id)
          const area = overview.farm_coverage?.[item.id]
          const latest = members.map(field => field.last_record_at).filter((date): date is string => Boolean(date)).sort().pop()
          const unchecked = members.filter(field => !field.context_checked_count).length
          const review = members.reduce((count, field) => count + (field.context_review_count || 0), 0)
          return <button type="button" className="farm-directory-row" key={item.id} onClick={() => updateScope({ farm: item.id })}>
            <strong>{item.name}</strong><span>{members.length} fields</span>
            <span className="farm-directory-summary"><small>{fieldArea(area?.boundary_area_m2, unit)} boundary coverage · {area?.unknown_area_count ?? members.filter(field => field.geometry_status !== 'boundary').length} fields with unknown area</small>
              <small>{review} source checks need review · {unchecked} fields not checked</small>
              <small>{latest ? <>Last saved record: <time dateTime={latest}>{new Date(latest).toLocaleDateString()}</time></> : 'No saved records this season'}</small>
            </span><span aria-hidden="true">→</span>
          </button>
        })}
        {overview?.fields.some(field => !field.farm_id) ? <button type="button" className="farm-directory-row" onClick={() => updateScope({ farm: 'unassigned' })}><strong>Unassigned fields</strong><span>{overview.fields.filter(field => !field.farm_id).length} fields</span><small>Assign existing fields to a farm when ready.</small><span aria-hidden="true">→</span></button> : null}
      </div> : null}
      {!loading && !overview?.fields.length && !farms.length ? <div className="farm-empty"><h2>Start with your farm</h2><p>Name your farm, then add fields by drawing, importing boundaries, or keeping locations unknown.</p><button type="button" className="primary-button" onClick={() => setNewFarm(true)}>Create your first farm</button><button type="button" onClick={onGeneralQuestion}>Ask a general question</button></div> : <>
        <div className="farm-section-heading"><div><h2>{farm?.name || (scope.farm === 'unassigned' ? 'Unassigned fields' : 'All fields')}</h2><p>{scopedFields.length} fields · {scopedFields.filter(field => field.geometry_status === 'boundary').length} with boundaries · {scopedFields.filter(field => field.geometry_status !== 'boundary').length} with unknown area</p></div><span>{scope.season} season</span></div>
        {coverage?.boundary_area_m2 != null ? <p className="farm-area-summary">Combined boundary coverage: {fieldArea(coverage.boundary_area_m2, unit)}{(coverage.overlapping_area_m2 || 0) > 1 ? ` · ${fieldArea(coverage.overlapping_area_m2, unit)} of overlapping area excluded` : ''}. Calculated from saved boundaries.</p> : null}
        <div className="farm-filters"><label className="farm-search"><Search size={16} /><span className="sr-only">Search fields</span><input aria-label="Search fields" value={scope.query} placeholder="Search field, crop or farm" onChange={event => updateScope({ query: event.target.value })} /></label>
          <label>Show<select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All fields</option><option value="boundary">Boundary needed</option><option value="crop">Crop not confirmed</option><option value="records">With records this season</option><option value="context">Context needs refresh / review</option></select></label>
          <label>Sort<select value={sort} onChange={event => setSort(event.target.value)}><option value="name">Field name</option><option value="crop">Crop</option><option value="records">Latest record</option></select></label>
        </div>
        <div className="farm-overview-grid"><div className="farm-table-scroll"><table className="farm-field-table"><caption className="sr-only">Fields for {scope.season}</caption><thead><tr><th>Field</th><th>Crop</th><th>Boundary area</th><th>Public context</th><th>Last record</th></tr></thead><tbody>{fields.map(field => <tr key={field.id} aria-selected={selected === field.id}>
          <td><button type="button" className="field-open" onClick={() => openField(field.id)}>{field.name}</button><small>{farms.find(item => item.id === field.farm_id)?.name || 'Unassigned'}</small><button type="button" className="field-on-map" aria-label={`Show ${field.name} on map`} disabled={field.geometry.kind === 'none'} onClick={() => { setSelected(field.id); setSearchPoint(emptyGeometry) }}><MapPin size={13} />Map</button></td>
          <td>{field.crop || <span className="farm-unknown">Not confirmed</span>}{field.legacy_undated_crop && !field.crop ? <small>Undated: {field.legacy_undated_crop}</small> : null}</td>
          <td>{fieldArea(field.boundary_area_m2, unit)}{field.geometry_status === 'point' ? <small>Point location only</small> : null}</td>
          <td>{field.context_checked_count || 0} of 4 sources checked<small>{field.context_review_count ? `${field.context_review_count} need refresh / review` : field.context_checked_count ? 'No reported stale or failed checks' : 'Not checked'}</small></td><td>{field.last_record_at ? <time dateTime={field.last_record_at}>{new Date(field.last_record_at).toLocaleDateString()}</time> : <span className="farm-unknown">No records</span>}<small>{field.record_count || 'No'} records this season</small></td>
        </tr>)}</tbody></table>{!fields.length ? <p className="farm-table-empty">No fields match. Adjust the filters or add a field.</p> : null}</div>
          <div className="farm-map-column"><div className="farm-map"><Suspense fallback={<p>Loading farm map…</p>}><LeafletFieldMap mode="inspect" scenarioId="farm-overview" fieldLabel={selectedField?.name || ''} fieldKey={selectedField?.id || 'farm'} geometry={searchPoint.kind !== 'none' ? searchPoint : selectedField?.geometry || emptyGeometry}
            fieldCollection={mapFields} collectionKey={scope.farm || 'all'} viewportKey={`farm:${scope.farm || 'all'}`} onSelectField={id => { setSelected(id); setSearchPoint(emptyGeometry) }} regionalCandidates={[]} regionalFeatureCollection={null} onGeometryChange={() => {}} onStatusChange={() => {}} allowNetwork={allowNetwork} /></Suspense></div>
            {selectedField ? <div className="farm-map-inspector"><strong>{selectedField.name}</strong><span>{fieldArea(selectedField.boundary_area_m2, unit)} · {selectedField.crop || 'Crop not confirmed'}</span><button type="button" onClick={() => openField(selectedField.id)}>Open field</button></div> : <p className="farm-map-note">Select a field in the table or map. Fields without a location remain in the table.</p>}
            <form className="farm-coordinate-search" onSubmit={event => { event.preventDefault(); const values = coordinate.split(/[,\s]+/).filter(Boolean).map(Number); if (values.length === 2 && values.every(Number.isFinite) && Math.abs(values[0]) <= 90 && Math.abs(values[1]) <= 180) { setSelected(''); setSearchPoint({ kind: 'point', point: { lat: values[0], lon: values[1] } }); setError('') } else setError('Enter latitude, longitude, for example 53.3, -113.6.') }}><label>Go to coordinates<input value={coordinate} onChange={event => setCoordinate(event.target.value)} placeholder="Latitude, longitude" /></label><button type="submit">Go</button></form>
          </div></div>
      </>}
    </>}
    {importOpen ? <Suspense fallback={<p>Opening import…</p>}><FieldImportDialog farms={farms} initialFarm={scope.farm} allowNetwork={allowNetwork} onClose={() => setImportOpen(false)} onSaved={() => { setRefresh(v => v + 1); onFieldsImported() }} /></Suspense> : null}
    {newFarm ? <WorkspaceDialog title={editFarm ? "Manage farm" : "Create farm"} busy={saving} onClose={() => { if (!saving) setNewFarm(false) }}><form className="farm-form" onSubmit={event => { event.preventDefault(); void saveFarm() }}><label>Farm name<input data-dialog-initial-focus value={farmName} onChange={event => setFarmName(event.target.value)} maxLength={160} required /></label><p>A farm groups fields within your private workspace.</p>{editFarm ? <label><input type="checkbox" checked={archived} onChange={event => setArchived(event.target.checked)} />Archived · move all fields first. An archived farm can be restored here.</label> : null}{error ? <p role="alert">{error}</p> : null}<button type="submit" className="primary-button" disabled={saving || !farmName.trim()}>{saving ? 'Saving…' : editFarm ? 'Save farm' : 'Create farm'}</button></form></WorkspaceDialog> : null}
  </section>
}
