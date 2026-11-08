import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Plus, ArrowLeft, Search } from 'lucide-react'
import { apiGet, apiPatch, apiPost } from './api'
import { recoverableLazy as lazy } from './WorkspaceSectionBoundary'
import { WorkspaceDialog } from './WorkspaceDialog'
import { fieldArea, readableError, type Farm, type FarmOverview } from './farmTypes'
import type { FieldGeometry } from './fieldGeometry'
import { FarmDirectory } from './FarmDirectory'
import { FarmFieldTable } from './FarmFieldTable'
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
  const directory = mode === 'farms' && !scope.farm && !scope.field
  const title = mode === 'records' ? 'Records' : farm?.name || (scope.farm === 'unassigned' ? 'Unassigned fields' : mode === 'fields' ? 'Fields' : 'Farms')
  const openFarm = (id: string) => { updateScope({ farm: id, field: '', query: '' }); setSelected(''); setSearchPoint(emptyGeometry) }
  const createFarm = () => { setEditFarm(null); setFarmName(''); setArchived(false); setNewFarm(true); setError('') }
  return <section className="farm-workspace" aria-label="Farm workspace">
    {!scope.field ? <header className="farm-page-heading">
      <div>{scope.farm && mode === 'farms' ? <button type="button" className="farm-back" onClick={() => openFarm('')}><ArrowLeft size={15} />Farms</button> : null}<h1>{title}</h1></div>
      {mode !== 'records' ? <div className="farm-actions">
        {farm ? <button type="button" onClick={() => { setEditFarm(farm); setFarmName(farm.name); setArchived(Boolean(farm.archived)); setNewFarm(true) }}>Manage farm</button> : null}
        <button type="button" onClick={() => setImportOpen(true)}>Import fields</button>
        {directory ? <button type="button" className="primary-button" onClick={createFarm}><Plus size={16} />Create farm</button> : <button type="button" className="primary-button" onClick={() => onAddField(farm?.id || null)}><Plus size={16} />Add field</button>}
      </div> : null}
    </header> : null}
    <div className="farm-scope-bar">
      {scope.field ? <button type="button" className="farm-back" onClick={() => updateScope({ field: '', tab: 'overview' })}><ArrowLeft size={16} />{farm?.name || (mode === 'farms' ? 'Farms' : mode === 'records' ? 'Records' : 'Fields')}</button> : <label className="farm-scope-select"><span className="sr-only">Farm</span><select aria-label="Farm" value={scope.farm} onChange={event => openFarm(event.target.value)}>
        <option value="">All farms</option><option value="unassigned">Unassigned fields</option>{farms.map(item => <option key={item.id} value={item.id}>{item.name}{item.archived ? ' (archived)' : ''}</option>)}
      </select></label>}
      <div className="farm-period-controls"><label>Season<input aria-label="Season" type="number" min="1900" max="2200" value={scope.season} onChange={event => { const year = Number(event.target.value); if (year >= 1900 && year <= 2200) updateScope({ season: year }) }} /></label>
      {mode !== 'records' || scope.field ? <label><span className="sr-only">Area units</span><select aria-label="Area units" value={unit} onChange={event => { const value = event.target.value as 'ac' | 'ha'; setUnit(value); window.localStorage.setItem('open-agronomy.area-unit', value) }}><option value="ac">Acres</option><option value="ha">Hectares</option></select></label> : null}</div>
    </div>
    {error ? <div role="alert" className="farm-error">{error}<button type="button" onClick={() => setRefresh(v => v + 1)}>Retry</button></div> : null}
    {loading ? <p role="status">Loading farms…</p> : null}
    {!overview ? null : scope.field ? <Suspense fallback={<p role="status">Opening field…</p>}><FieldDossier key={scope.field} fieldId={scope.field} season={scope.season} tab={scope.tab} farms={farms} allowNetwork={allowNetwork} unit={unit}
      onTab={tab => updateScope({ tab })} onChanged={() => setRefresh(v => v + 1)} onEdit={() => onEditField(scope.field)} onAsk={question => onAsk(scope.field, question, scope.season)} /></Suspense>
    : mode === 'records' ? <Suspense fallback={<p>Loading records…</p>}><FarmRecords key={`${scope.farm}:${scope.season}`} fields={scopedFields} farmId={scope.farm} season={scope.season} onOpenField={id => openField(id, 'records')} /></Suspense>
    : directory ? <>
      <FarmDirectory farms={farms} overview={overview} season={scope.season} unit={unit} onOpen={openFarm} />
      {!loading && !overview.fields.length && !farms.length ? <div className="farm-empty"><h2>Add your first farm</h2><button type="button" className="primary-button" onClick={createFarm}>Create farm</button><button type="button" onClick={onGeneralQuestion}>Ask a question</button></div> : null}
    </> : <>
      <div className="farm-overview-summary"><span><strong>{scopedFields.length}</strong> {scopedFields.length === 1 ? 'field' : 'fields'}</span><span><strong>{fieldArea(coverage?.boundary_area_m2, unit)}</strong> boundary coverage</span>{scopedFields.some(field => field.geometry_status !== 'boundary') ? <span>{scopedFields.filter(field => field.geometry_status !== 'boundary').length} with unknown area</span> : null}</div>
      {(coverage?.overlapping_area_m2 || 0) > 1 ? <p className="farm-area-summary">{fieldArea(coverage?.overlapping_area_m2, unit)} of overlapping area excluded.</p> : null}
      <div className="farm-filters"><label className="farm-search"><Search size={16} aria-hidden="true" /><span className="sr-only">Search fields</span><input aria-label="Search fields" value={scope.query} placeholder="Search fields" onChange={event => updateScope({ query: event.target.value })} /></label>
        <label><span className="sr-only">Show</span><select aria-label="Show" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All fields</option><option value="boundary">Boundary needed</option><option value="crop">Crop not confirmed</option><option value="records">With records</option><option value="context">Sources to review</option></select></label>
        <label><span className="sr-only">Sort</span><select aria-label="Sort" value={sort} onChange={event => setSort(event.target.value)}><option value="name">Field name</option><option value="crop">Crop</option><option value="records">Latest record</option></select></label>
      </div>
      <div className="farm-overview-grid">
        <FarmFieldTable fields={fields} farms={farms} season={scope.season} unit={unit} selected={selected} showFarm={!scope.farm} onOpen={openField} onSelect={id => { setSelected(id); setSearchPoint(emptyGeometry) }} />
        <div className="farm-map-column"><div className="farm-map"><Suspense fallback={<p>Loading farm map…</p>}><LeafletFieldMap mode="inspect" scenarioId="farm-overview" fieldLabel={selectedField?.name || ''} fieldKey={selectedField?.id || 'farm'} geometry={searchPoint.kind !== 'none' ? searchPoint : selectedField?.geometry || emptyGeometry}
          fieldCollection={mapFields} collectionKey={scope.farm || 'all'} viewportKey={`farm:${scope.farm || 'all'}`} onSelectField={id => { setSelected(id); setSearchPoint(emptyGeometry) }} regionalCandidates={[]} regionalFeatureCollection={null} onGeometryChange={() => {}} onStatusChange={() => {}} allowNetwork={allowNetwork} /></Suspense></div>
          {selectedField ? <div className="farm-map-inspector"><div><strong>{selectedField.name}</strong><small>{fieldArea(selectedField.boundary_area_m2, unit)} · {selectedField.crop || 'Crop not confirmed'}</small></div><button type="button" onClick={() => openField(selectedField.id)}>Open field</button></div> : null}
          <details className="farm-coordinate-disclosure"><summary>Go to coordinates</summary><form className="farm-coordinate-search" onSubmit={event => { event.preventDefault(); const values = coordinate.split(/[,\s]+/).filter(Boolean).map(Number); if (values.length === 2 && values.every(Number.isFinite) && Math.abs(values[0]) <= 90 && Math.abs(values[1]) <= 180) { setSelected(''); setSearchPoint({ kind: 'point', point: { lat: values[0], lon: values[1] } }); setError('') } else setError('Enter latitude, longitude, for example 53.3, -113.6.') }}><label><span className="sr-only">Coordinates</span><input aria-label="Coordinates" value={coordinate} onChange={event => setCoordinate(event.target.value)} placeholder="Latitude, longitude" /></label><button type="submit">Go</button></form></details>
        </div>
      </div>
    </>}
    {importOpen ? <Suspense fallback={<p>Opening import…</p>}><FieldImportDialog farms={farms} initialFarm={scope.farm} allowNetwork={allowNetwork} onClose={() => setImportOpen(false)} onSaved={() => { setRefresh(v => v + 1); onFieldsImported() }} /></Suspense> : null}
    {newFarm ? <WorkspaceDialog title={editFarm ? "Manage farm" : "Create farm"} busy={saving} onClose={() => { if (!saving) setNewFarm(false) }}><form className="farm-form" onSubmit={event => { event.preventDefault(); void saveFarm() }}><label>Farm name<input data-dialog-initial-focus value={farmName} onChange={event => setFarmName(event.target.value)} maxLength={160} required /></label>{editFarm ? <label><input type="checkbox" checked={archived} onChange={event => setArchived(event.target.checked)} />Archive farm (move its fields first)</label> : null}{error ? <p role="alert">{error}</p> : null}<button type="submit" className="primary-button" disabled={saving || !farmName.trim()}>{saving ? 'Saving…' : editFarm ? 'Save farm' : 'Create farm'}</button></form></WorkspaceDialog> : null}
  </section>
}
