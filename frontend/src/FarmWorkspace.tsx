import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Plus, Search, X } from 'lucide-react'
import { apiGet, apiPatch, apiPost } from './api'
import { recoverableLazy as lazy } from './WorkspaceSectionBoundary'
import { WorkspaceDialog } from './WorkspaceDialog'
import { fieldArea, readableError, type Farm, type FarmOverview, type FieldSummary } from './farmTypes'
import type { FieldGeometry } from './fieldGeometry'
import { decodeImageryOverlay, ImageColorLegend, type FieldMapImage, type ShowFieldImage } from './ImageryMapPreview'
import { FarmDirectory } from './FarmDirectory'
import './FarmWorkspace.css'

const LeafletFieldMap = lazy(() => import('./LeafletFieldMap').then(m => ({ default: m.LeafletFieldMap })), 'Farm map')
const FieldImportDialog = lazy(() => import('./FieldImportDialog'), 'Boundary import')
const FieldDossier = lazy(() => import('./FieldDossier'), 'Field detail')
const FarmRecords = lazy(() => import('./FarmRecords'), 'Farm records')
const emptyGeometry: FieldGeometry = { kind: 'none' }
const readScope = () => {
  const query = new URLSearchParams(window.location.hash.split('?')[1] || '')
  const year = Number(query.get('season'))
  const field = query.get('field') || ''
  return {
    farm: query.get('farm') || '', field, mapView: query.get('view') === 'map',
    season: Number.isInteger(year) && year >= 1900 && year <= 2200 ? year : new Date().getFullYear(),
    tab: query.get('tab') || 'overview', query: query.get('q') || '',
  }
}

export default function FarmWorkspace({ mode, allowNetwork, refreshKey, onAddField, onEditField, onAsk, onGeneralQuestion, onFieldsImported }: {
  mode: 'farms' | 'records'; allowNetwork: boolean; refreshKey: string
  onAddField: (farmId: string | null) => void; onEditField: (fieldId: string) => void
  onAsk: (fieldId: string, question?: string, season?: number, imageryJobId?: string) => void; onGeneralQuestion: () => void; onFieldsImported: () => void
}) {
  const [scope, setScope] = useState(readScope)
  const [farms, setFarms] = useState<Farm[]>([])
  const [overview, setOverview] = useState<FarmOverview | null>(null)
  const [summary, setSummary] = useState<FieldSummary | null>(null)
  const [summaryError, setSummaryError] = useState('')
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
  const [coordinate, setCoordinate] = useState('')
  const [searchPoint, setSearchPoint] = useState<FieldGeometry>(emptyGeometry)
  const [focusRequest, setFocusRequest] = useState(0)
  const [narrowPane, setNarrowPane] = useState<'details' | 'map'>('details')
  const [image, setImage] = useState<(FieldMapImage & { url: string }) | null>(null)
  const [opacity, setOpacity] = useState(.85)
  const request = useRef(0)
  const openFieldButton = useRef<HTMLButtonElement>(null)
  const backToMapButton = useRef<HTMLButtonElement>(null)

  const records = mode === 'records'
  const detailOpen = !records && Boolean(scope.field) && !scope.mapView
  const previousDetailOpen = useRef(detailOpen)
  const selectedField = overview?.fields.find(field => field.id === scope.field)
  const field = detailOpen && summary?.id === scope.field && summary.season === scope.season ? summary : null
  const detailName = detailOpen ? field?.name || selectedField?.name : null
  const location = field && (field.mapped_location?.label
    || [field.confirmed_facts?.province_state, field.country].filter(Boolean).join(', ') || 'Location unavailable')
  const farmId = selectedField ? selectedField.farm_id || 'unassigned' : scope.farm
  const farm = farms.find(item => item.id === farmId)
  const query = scope.query.trim().toLowerCase()
  const filtering = Boolean(query || filter !== 'all')
  const fields = useMemo(() => (overview?.fields || []).filter(field => {
    const matches = `${field.name} ${field.crop || ''} ${farms.find(item => item.id === field.farm_id)?.name || 'unassigned'}`.toLowerCase().includes(query)
    return matches && (filter === 'all' || filter === 'boundary' && field.geometry_status !== 'boundary' || filter === 'crop' && !field.crop || filter === 'records' && field.record_count > 0 || filter === 'context' && (field.context_review_count || 0) > 0)
  }).sort((a, b) => sort === 'records' ? (b.last_record_at || '').localeCompare(a.last_record_at || '') : sort === 'crop' ? (a.crop || '').localeCompare(b.crop || '') || a.name.localeCompare(b.name) : a.name.localeCompare(b.name)), [overview, query, filter, sort, farms])
  const mapFields = useMemo(() => fields
    .filter(field => field.geometry.kind !== 'none' && (!farmId || (field.farm_id || 'unassigned') === farmId))
    .map(({ id, name, geometry }) => ({ id, name, geometry })), [fields, farmId])
  const recordFields = records ? (overview?.fields || []).filter(field => !farmId || (field.farm_id || 'unassigned') === farmId) : []
  const geometry = searchPoint.kind !== 'none' ? searchPoint : selectedField?.geometry || emptyGeometry
  const empty = !loading && overview && !overview.fields.length && !farms.length

  const showImage: ShowFieldImage = (next) => {
    if (next && next.geometryKey !== selectedField?.geometry_revision_id) {
      throw new Error('This image belongs to an earlier field boundary.')
    }
    setImage(next ? { ...next, url: URL.createObjectURL(decodeImageryOverlay(next.overlay)) } : null)
    if (next) setNarrowPane('map')
  }
  const visibleImage = detailOpen && scope.tab === 'imagery' && image?.geometryKey === selectedField?.geometry_revision_id ? image : null
  useEffect(() => {
    if (image) return () => URL.revokeObjectURL(image.url)
  }, [image])
  useEffect(() => {
    setImage(null)
    setNarrowPane('details')
  }, [detailOpen, scope.field, scope.tab, selectedField?.geometry_revision_id])

  const updateScope = (patch: Partial<typeof scope>, replace = false) => {
    const next = { ...scope, ...patch }
    setScope(next)
    const params = new URLSearchParams({ season: String(next.season) })
    if (next.farm) params.set('farm', next.farm)
    if (next.field) {
      params.set('field', next.field)
      if (next.mapView) params.set('view', 'map')
    }
    if (next.tab !== 'overview') params.set('tab', next.tab)
    if (next.query) params.set('q', next.query)
    const hash = `#${mode}?${params}`
    if (replace) window.history.replaceState(null, '', hash)
    else if (window.location.hash !== hash) window.history.pushState(null, '', hash)
  }
  useEffect(() => {
    if (previousDetailOpen.current === detailOpen) return
    previousDetailOpen.current = detailOpen
    const destination = detailOpen ? backToMapButton : openFieldButton
    destination.current?.focus()
  }, [detailOpen])
  useEffect(() => {
    const changed = () => {
      setScope(readScope())
      setSearchPoint(emptyGeometry)
    }
    window.addEventListener('hashchange', changed)
    window.addEventListener('popstate', changed)
    return () => {
      window.removeEventListener('hashchange', changed)
      window.removeEventListener('popstate', changed)
    }
  }, [])
  useEffect(() => {
    const id = ++request.current
    setLoading(true)
    setError('')
    Promise.all([apiGet<{ farms: Farm[] }>('/api/farms'), apiGet<FarmOverview>(`/api/farms/overview?season=${scope.season}`)])
      .then(([farmResult, result]) => {
        if (!Array.isArray(farmResult.farms) || !Array.isArray(result.fields)) throw new Error('Saved farm information could not be read. Retry the connection.')
        if (id === request.current) { setFarms(farmResult.farms); setOverview(result) }
      })
      .catch(cause => { if (id === request.current) setError(readableError(cause)) })
      .finally(() => { if (id === request.current) setLoading(false) })
    return () => { request.current += 1 }
  }, [scope.season, refresh, refreshKey])

  useEffect(() => {
    setSummaryError('')
    if (!detailOpen) {
      setSummary(null)
      return
    }
    let active = true
    apiGet<FieldSummary>(`/api/fields/${encodeURIComponent(scope.field)}/summary?season=${scope.season}`)
      .then(value => { if (active) setSummary(value) })
      .catch(cause => { if (active) setSummaryError(readableError(cause)) })
    return () => { active = false }
  }, [detailOpen, scope.field, scope.season, refresh, refreshKey])

  const openFarmForm = (item: Farm | null) => {
    setEditFarm(item)
    setFarmName(item?.name || '')
    setArchived(Boolean(item?.archived))
    setNewFarm(true)
    setError('')
  }
  const saveFarm = async () => {
    setSaving(true)
    setError('')
    try {
      const created = editFarm
        ? await apiPatch<Farm>(`/api/farms/${encodeURIComponent(editFarm.id)}`, { name: farmName.trim(), archived, expected_revision: editFarm.revision })
        : await apiPost<Farm>('/api/farms', { name: farmName.trim() })
      setFarms(current => [...current.filter(item => item.id !== created.id), created])
      setSearchPoint(emptyGeometry)
      updateScope({ farm: created.archived ? '' : created.id, field: '', tab: 'overview' })
      setNewFarm(false)
      setRefresh(value => value + 1)
    } catch (cause) { setError(readableError(cause)) } finally { setSaving(false) }
  }
  const openFarm = (id: string) => {
    setSearchPoint(emptyGeometry)
    updateScope({ farm: id, field: '', tab: 'overview' })
  }
  const selectField = (id: string) => {
    const field = overview?.fields.find(item => item.id === id)
    if (!field) return
    setSearchPoint(emptyGeometry)
    setFocusRequest(value => value + 1)
    updateScope({ farm: field.farm_id || 'unassigned', field: id, mapView: !detailOpen, tab: scope.field === id ? scope.tab : 'overview' })
  }
  const openRecordField = (id: string) => {
    const params = new URLSearchParams({ season: String(scope.season), field: id, tab: 'records' })
    const assignedFarm = overview?.fields.find(item => item.id === id)?.farm_id
    if (assignedFarm) params.set('farm', assignedFarm)
    window.location.hash = `farms?${params}`
  }
  const goToCoordinates = () => {
    const values = coordinate.split(/[,\s]+/).filter(Boolean).map(Number)
    if (values.length !== 2 || !values.every(Number.isFinite) || Math.abs(values[0]) > 90 || Math.abs(values[1]) > 180) {
      setError('Enter latitude, longitude, for example 53.3, -113.6.')
      return
    }
    updateScope({ farm: farmId, field: '', tab: 'overview' })
    setSearchPoint({ kind: 'point', point: { lat: values[0], lon: values[1] } })
    setFocusRequest(value => value + 1)
    setError('')
  }

  const periodControls = (
    <div className="farm-period-controls">
      <label>Season<input key={scope.season} aria-label="Season" type="number" min="1900" max="2200" defaultValue={scope.season}
        onBlur={event => {
          const year = event.currentTarget.valueAsNumber
          if (Number.isInteger(year) && year >= 1900 && year <= 2200 && year !== scope.season) updateScope({ season: year })
          else event.currentTarget.value = String(scope.season)
        }}
        onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur() }} /></label>
      {!records ? <label><span className="sr-only">Area units</span><select aria-label="Area units" value={unit} onChange={event => {
        const value = event.target.value as 'ac' | 'ha'
        setUnit(value)
        window.localStorage.setItem('open-agronomy.area-unit', value)
      }}><option value="ac">Acres</option><option value="ha">Hectares</option></select></label> : null}
    </div>
  )

  return <section className="farm-workspace" aria-label="Farm workspace">
    <header className="farm-page-heading" data-farms={!records || undefined}>
      <div className="farm-page-title">
        <h1>{records ? 'Records' : 'Farms'}</h1>
        {detailName ? <div className="farm-field-identity">
          <h2>{detailName}</h2>
          {location ? <small>{location}</small> : null}
        </div> : null}
      </div>
      {!records ? periodControls : null}
      {field ? <div className="farm-actions">
        <button type="button" onClick={() => onEditField(field.id)}>Edit field</button>
        <button type="button" onClick={() => onAsk(field.id, undefined, scope.season, undefined)}>Ask about this field</button>
      </div> : null}
      {!records && !detailOpen ? <div className="farm-actions">
        <button type="button" onClick={() => openFarmForm(null)}>Create farm</button>
        <button type="button" onClick={() => setImportOpen(true)}>Import fields</button>
        <button type="button" className="primary-button" onClick={() => onAddField(farm && !farm.archived ? farm.id : null)}><Plus size={16} />Add field</button>
      </div> : null}
    </header>
    {records ? <div className="farm-scope-bar">
      <label className="farm-scope-select"><span className="sr-only">Farm</span><select aria-label="Farm" value={scope.farm} onChange={event => openFarm(event.target.value)}>
        <option value="">All farms</option><option value="unassigned">Unassigned fields</option>{farms.map(item => <option key={item.id} value={item.id}>{item.name}{item.archived ? ' (archived)' : ''}</option>)}
      </select></label>
      {periodControls}
    </div> : null}
    {error ? <div role="alert" className="farm-error">{error}<button type="button" onClick={() => setRefresh(value => value + 1)}>Retry</button></div> : null}
    {loading && !overview ? <p role="status">Loading farms…</p> : null}
    {records && overview ? <Suspense fallback={<p>Loading records…</p>}>
      <FarmRecords key={`${scope.farm}:${scope.season}`} fields={recordFields} farmId={scope.farm} season={scope.season} onOpenField={openRecordField} />
    </Suspense> : null}
    {!records && overview ? (
      <div className="farm-overview-grid" data-narrow-pane={detailOpen ? narrowPane : undefined}>
        {detailOpen ? <div className="farm-narrow-switch" role="group" aria-label="Field view">
          <button type="button" aria-pressed={narrowPane === 'details'} onClick={() => setNarrowPane('details')}>Details</button>
          <button type="button" aria-pressed={narrowPane === 'map'} onClick={() => setNarrowPane('map')}>Map</button>
        </div> : null}
        <div className="farm-list-column">
          {detailOpen ? <>
            <div className="farm-back-bar">
              <button ref={backToMapButton} type="button" className="farm-back-to-map" onClick={() => updateScope({ farm: farmId, mapView: true })}>
                <ArrowLeft size={16} aria-hidden="true" />Back to farms
              </button>
            </div>
            <Suspense fallback={<p role="status">Opening field…</p>}>
              <FieldDossier key={scope.field} field={field} summaryError={summaryError} fieldId={scope.field} season={scope.season} tab={scope.tab} farms={farms} allowNetwork={allowNetwork} unit={unit}
                onShowImage={showImage} onTab={tab => updateScope({ farm: farmId, tab })} onChanged={() => setRefresh(value => value + 1)} onEdit={() => onEditField(scope.field)}
                onAsk={(question, imageryJobId) => onAsk(scope.field, question, scope.season, imageryJobId)} />
            </Suspense>
          </> : empty ? <div className="farm-empty">
            <h2>Add your first farm</h2>
            <button type="button" onClick={onGeneralQuestion}>Ask a question</button>
          </div> : <>
            <div className="farm-filters">
              <label className="farm-search"><Search size={16} aria-hidden="true" /><span className="sr-only">Search fields</span>
                <input aria-label="Search fields" value={scope.query} placeholder="Search fields" onChange={event => updateScope({ query: event.target.value }, true)} />
              </label>
              <label><span className="sr-only">Show</span><select aria-label="Show" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All fields</option><option value="boundary">Boundary needed</option><option value="crop">Crop not confirmed</option><option value="records">With records</option><option value="context">Sources to review</option></select></label>
              <label><span className="sr-only">Sort</span><select aria-label="Sort" value={sort} onChange={event => setSort(event.target.value)}><option value="name">Field name</option><option value="crop">Crop</option><option value="records">Latest record</option></select></label>
            </div>
            {!farmId && overview.fields.length ? <div className="farm-overview-summary">
              {overview.coverage?.boundary_area_m2 != null ? <span><strong>{fieldArea(overview.coverage.boundary_area_m2, unit)}</strong> in boundaries across all farms</span>
                : <span>Boundary area unknown</span>}
              {overview.coverage?.unknown_area_count ? <span>{overview.coverage.unknown_area_count} with unknown area</span> : null}
              {(overview.coverage?.overlapping_area_m2 || 0) > 1 ? <span>{fieldArea(overview.coverage.overlapping_area_m2, unit)} of overlapping area excluded</span> : null}
            </div> : null}
            <FarmDirectory farms={farms} overview={overview} fields={fields} unit={unit} expandedFarm={farmId} selected={scope.field} filtering={filtering}
              onToggle={id => openFarm(farmId === id ? '' : id)} onSelect={selectField} onManage={openFarmForm} />
          </>}
        </div>
        <div className="farm-map-column" role="region" aria-label="Farm map">
          <div className="farm-map-inspector" data-field-detail={detailOpen || undefined}>
            <div className="farm-map-inspector-copy" aria-live="polite">
              {!detailOpen ? <strong title={selectedField?.name}>{selectedField?.name || 'Farm map'}</strong> : null}
              <small>{selectedField ? <>
                {selectedField.crop || 'Crop not confirmed'} · {selectedField.geometry.kind === 'none' ? 'Location unknown'
                  : selectedField.geometry.kind === 'point' ? 'Point location' : fieldArea(selectedField.boundary_area_m2, unit)}
              </> : 'Select a field'}</small>
            </div>
            {selectedField && !detailOpen ? <button ref={openFieldButton} type="button" className="farm-open-field" onClick={() => updateScope({ farm: farmId, mapView: false })}>
              Open field<ArrowRight size={16} aria-hidden="true" />
            </button> : null}
          </div>
          <div className="farm-map">
            {visibleImage ? <div className="farm-map-image-toolbar" role="group" aria-label="Map image controls">
              <div className="farm-map-image-heading">
                <strong>{visibleImage.label}</strong>
                <button type="button" aria-label="Hide image" title="Hide image" onClick={() => setImage(null)}><X size={16} aria-hidden="true" /></button>
              </div>
              <ImageColorLegend scale={visibleImage.overlay.color_scale} />
              <label>Opacity<input aria-label="Image opacity" type="range" min="0" max="1" step=".05" value={opacity} onChange={event => setOpacity(Number(event.target.value))} /></label>
            </div> : null}
            <Suspense fallback={<p role="status">Loading farm map…</p>}>
              <LeafletFieldMap mode="inspect" scenarioId="farm-overview" fieldLabel={selectedField?.name || ''} fieldKey={selectedField?.id || (searchPoint.kind !== 'none' ? 'coordinates' : 'farm')}
                geometry={geometry} fieldCollection={mapFields} collectionKey={farmId || 'all'} collectionMaxZoom={13} viewportKey="farm-overview"
                focusRequest={focusRequest} onSelectField={selectField}
                analyticalOverlay={visibleImage ? { url: visibleImage.url, bounds: visibleImage.overlay.bounds, opacity } : undefined} regionalCandidates={[]} regionalFeatureCollection={null}
                onGeometryChange={() => {}} onStatusChange={() => {}} allowNetwork={allowNetwork} />
            </Suspense>
          </div>
          {!detailOpen ? <details className="farm-coordinate-disclosure">
            <summary>Go to coordinates</summary>
            <form className="farm-coordinate-search" onSubmit={event => { event.preventDefault(); goToCoordinates() }}>
              <label><span className="sr-only">Coordinates</span><input aria-label="Coordinates" value={coordinate} onChange={event => setCoordinate(event.target.value)} placeholder="Latitude, longitude" /></label>
              <button type="submit">Go</button>
            </form>
          </details> : null}
        </div>
      </div>
    ) : null}
    {importOpen ? <Suspense fallback={<p>Opening import…</p>}>
      <FieldImportDialog farms={farms} initialFarm={farm && !farm.archived ? farm.id : ''} allowNetwork={allowNetwork} onClose={() => setImportOpen(false)}
        onSaved={() => { setRefresh(value => value + 1); onFieldsImported() }} />
    </Suspense> : null}
    {newFarm ? <WorkspaceDialog title={editFarm ? 'Manage farm' : 'Create farm'} busy={saving} onClose={() => { if (!saving) setNewFarm(false) }}>
      <form className="farm-form" onSubmit={event => { event.preventDefault(); void saveFarm() }}>
        <label>Farm name<input data-dialog-initial-focus value={farmName} onChange={event => setFarmName(event.target.value)} maxLength={160} required /></label>
        {editFarm ? <label><input type="checkbox" checked={archived} onChange={event => setArchived(event.target.checked)} />Archive farm (move its fields first)</label> : null}
        {error ? <p role="alert">{error}</p> : null}
        <button type="submit" className="primary-button" disabled={saving || !farmName.trim()}>{saving ? 'Saving…' : editFarm ? 'Save farm' : 'Create farm'}</button>
      </form>
    </WorkspaceDialog> : null}
  </section>
}
