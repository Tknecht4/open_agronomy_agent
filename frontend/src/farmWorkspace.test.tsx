import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FarmWorkspace from './FarmWorkspace'
import type { FarmField } from './farmTypes'
vi.mock('./LeafletFieldMap', () => ({
  LeafletFieldMap: ({ fieldCollection, fieldKey, geometry, onSelectField }: {
    fieldCollection: Array<{ id: string; name: string }>
    fieldKey: string
    geometry: { kind: string }
    onSelectField: (id: string) => void
  }) => <div data-testid="farm-map" data-field={fieldKey} data-geometry={geometry.kind}>
    {fieldCollection.map(field => <button key={field.id} onClick={() => onSelectField(field.id)}>Map {field.name}</button>)}
  </div>,
}))
vi.mock('./FieldSyncPanel',()=>({FieldSyncPanel:()=>null}))
const field = (id:string,name:string,farm:string,located:boolean):FarmField=>({id,name,farm_id:farm,assignment_revision:1,season:2026,crop:null,crop_status:'unknown',season_revision:0,legacy_undated_crop:'Wheat',geometry:located?{kind:'point',point:{lat:53,lon:-113}}:{kind:'none'},geometry_revision_id:'revision',geometry_sha256:'hash',geometry_status:located?'point':'unknown',boundary_area_m2:null,boundary_perimeter_m:null,record_count:0,last_record_at:null,updated_at:'2026-11-05',country:null})
const fields=[field('west','West','a',true),field('east','East','b',false)]
const farms=[{id:'a',name:'Home',revision:1,archived:0},{id:'b',name:'Second',revision:1,archived:0}]
const props={mode:'farms' as const,allowNetwork:false,refreshKey:'1',onAddField:vi.fn(),onEditField:vi.fn(),onAsk:vi.fn(),onGeneralQuestion:vi.fn(),onFieldsImported:vi.fn()}
afterEach(()=>{vi.unstubAllGlobals();window.history.replaceState(null,'','#farms')})
describe('farm cockpit workflows',()=>{
  it('opens field details on request and returns to the same map selection',async()=>{
    window.history.replaceState(null,'','#farms?season=2026')
    let crop:string|null=null
    const request=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const url=String(input)
      let result:unknown={}
      if(url==='/api/farms')result={farms}
      else if(url.startsWith('/api/farms/overview'))result={fields,coverage:{boundary_area_m2:null}}
      else if(url.startsWith('/api/fields/west/summary'))result={...fields[0],crop,mapped_location:{label:'Parkland County, Alberta, Canada'},seasons:[],geometry_revisions:[],source_status:{},public_context:{}}
      else if(url==='/api/fields/west/seasons/2026'){crop=JSON.parse(String(init?.body)).crops.map((item:{crop:string})=>item.crop).join(' + ');result={crop}}
      return {ok:true,status:200,json:async()=>result,text:async()=>JSON.stringify(result)} as Response
    })
    vi.stubGlobal('fetch',request)
    render(<FarmWorkspace {...props} />)
    const home = await screen.findByRole('button', { name: /Home/ })
    const map = await screen.findByTestId('farm-map')
    expect(home).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(home)
    expect(home).toHaveAttribute('aria-expanded', 'true')
    const west = screen.getByRole('button', { name: /^West/ })
    fireEvent.click(west)
    expect(west).toHaveAttribute('aria-pressed', 'true')
    expect(map).toHaveAttribute('data-field', 'west')
    expect(map).toHaveAttribute('data-geometry', 'point')
    expect(screen.queryByRole('region', { name: 'Field detail' })).not.toBeInTheDocument()
    expect(request.mock.calls.some(([url]) => String(url).includes('/west/summary'))).toBe(false)
    fireEvent.change(screen.getByRole('textbox', { name: 'Search fields' }), { target: { value: 'west' } })
    fireEvent.click(screen.getByRole('button', { name: 'Open field' }))
    const header = screen.getByRole('heading', { level: 1, name: 'Farms' }).closest('header')!
    expect(await within(header).findByRole('heading', { level: 2, name: 'West' })).toBeInTheDocument()
    expect(await within(header).findByText('Parkland County, Alberta, Canada')).toBeInTheDocument()
    expect(within(header).getByRole('spinbutton', { name: 'Season' })).toHaveValue(2026)
    expect(within(header).getByRole('combobox', { name: 'Area units' })).toHaveValue('ac')
    expect(within(header).getByRole('button', { name: 'Edit field' })).toBeEnabled()
    expect(within(header).getByRole('button', { name: 'Ask about this field' })).toBeEnabled()
    const detail = await screen.findByRole('region', { name: 'Field detail' })
    expect(within(detail).queryByText('West')).not.toBeInTheDocument()
    expect(screen.getByTestId('farm-map')).toBe(map)
    expect(screen.getByRole('button', { name: 'Back to farms' })).toHaveFocus()
    expect(window.location.hash).not.toContain('view=map')
    fireEvent.click(screen.getByRole('button', { name: 'Back to farms' }))
    expect(screen.getByRole('button', { name: 'Open field' })).toHaveFocus()
    expect(screen.getByRole('textbox', { name: 'Search fields' })).toHaveValue('west')
    expect(screen.getByRole('button', { name: /^West/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('farm-map')).toHaveAttribute('data-field', 'west')
    expect(window.location.hash).toContain('view=map')
    fireEvent.click(screen.getByRole('button', { name: 'Open field' }))
    expect(await screen.findByText(/Undated: Wheat/)).toHaveTextContent('Undated: Wheat')
    fireEvent.click(screen.getByRole('button',{name:'Confirm crop & season'}))
    const dialog=await screen.findByRole('dialog',{name:'Confirm 2026 season'})
    fireEvent.change(within(dialog).getByLabelText('Crop 1'),{target:{value:'Canola'}})
    fireEvent.click(within(dialog).getByRole('button',{name:'Add another crop'}))
    fireEvent.change(within(dialog).getByLabelText('Crop 2'),{target:{value:'Pea'}})
    fireEvent.change(within(dialog).getByLabelText('How do the crops share this field?'),{target:{value:'intercrop'}})
    fireEvent.click(within(dialog).getByRole('button',{name:'Save season'}))
    await waitFor(()=>expect(crop).toBe('Canola + Pea'))
    expect(await screen.findByText(/Undated: Wheat/)).toHaveTextContent('Wheat')
    fireEvent.click(screen.getByRole('button',{name:'Ask about this field'}))
    expect(props.onAsk).toHaveBeenCalledWith('west', undefined, 2026, undefined)
  })
  it('starts a field question with an explicit analysis ID without writing a note', async () => {
    window.history.replaceState(null, '', '#farms?season=2026&field=west&tab=imagery')
    const jobId = '550e8400-e29b-41d4-a716-446655440001'
    const onAsk = vi.fn()
    const request = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      let result: unknown = {}
      if (url === '/api/farms') result = { farms }
      else if (url.startsWith('/api/farms/overview')) result = { fields, coverage: {} }
      else if (url.startsWith('/api/fields/west/summary')) result = {
        ...fields[0], seasons: [], geometry_revisions: [], public_context: {}, source_status: {},
      }
      else if (url === '/api/imagery/providers') result = { providers: [] }
      else if (url === '/api/fields/west/imagery-jobs') result = { jobs: [{
        id: jobId, status: 'completed', current_geometry: true, geometry_revision_id: 'revision',
        geometry: { type: 'Point', coordinates: [-113, 53] },
        request: { provider_id: 'hls-s30-planetary-computer', scene_id: 'synthetic',
                   start_date: '2026-07-01', end_date: '2026-07-31' },
        result: { source: { acquired_at: '2026-07-03T00:00:00Z' } },
      }] }
      return { ok: true, status: 200, json: async () => result } as Response
    })
    vi.stubGlobal('fetch', request)
    render(<FarmWorkspace {...props} onAsk={onAsk} />)
    fireEvent.click(await screen.findByRole('button', { name: /Ready · Current boundary/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Ask about this analysis' }))
    expect(onAsk).toHaveBeenCalledWith('west', 'For this field, what are the NDVI and NDMI averages in the selected satellite image, and what area do those averages describe?', 2026, jobId)
    expect(request.mock.calls.some(([url]) => String(url).endsWith('/record'))).toBe(false)
  })

  it('puts a supported chart observation on the existing map and keeps excluded dates out of the plot', async () => {
    window.history.replaceState(null, '', '#farms?season=2026&field=west&tab=imagery')
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL() { return 'blob:imagery' }
      static revokeObjectURL() {}
    })
    const first = {
      scene_id: 'hls2-l30:Landsat', job_id: 'landsat-job', provider_id: 'hls-l30-planetary-computer',
      acquired_at: '2026-07-03T12:00:00Z', status: 'observed', indices: { NDVI: .65, NDMI: .24 },
      scene_cloud_percent: 50, field_cloud_fraction: .1, usable_fraction: .6001, field_cloud_status: 'detected',
    }
    const clear = {
      ...first, scene_id: 'hls2-s30:Clear', provider_id: 'hls-s30-planetary-computer',
      acquired_at: '2026-07-18T12:00:00Z', indices: { NDVI: .55, NDMI: .16 },
    }
    const sameDay = {
      ...clear, scene_id: 'hls2-s30:SameDay',
      acquired_at: '2026-07-04T01:00:00+07:00', indices: { NDVI: .55, NDMI: .18 },
    }
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      let result: unknown = {}
      if (url === '/api/farms') result = { farms }
      else if (url.startsWith('/api/farms/overview')) result = { fields, coverage: {} }
      else if (url.startsWith('/api/fields/west/summary')) result = { ...fields[0], seasons: [], geometry_revisions: [], public_context: {}, source_status: {} }
      else if (url.endsWith('/imagery-jobs')) result = { jobs: [] }
      else if (url.endsWith('/imagery/analytics')) result = { status: 'ready' }
      else if (url.endsWith('/imagery-series')) result = { jobs: [{
        id: 'series-job', status: 'completed', current_geometry: true, geometry_revision_id: 'revision',
        request: { start_date: '2026-07-01', end_date: '2026-07-31' },
        result: { status: 'complete', scenes: [clear, first, sameDay], total: 4, processed: 4, minimum_usable_fraction: .6,
          exclusions: { low_coverage: 1, unknown_coverage: 0, no_usable_pixels: 0, unavailable: 0 } },
      }, {
        id: 'older-series', status: 'completed', current_geometry: true, geometry_revision_id: 'revision',
        request: { start_date: '2026-06-01', end_date: '2026-06-30' },
        result: { status: 'complete', scenes: [], total: 2, processed: 2, minimum_usable_fraction: .6,
          exclusions: { low_coverage: 2, unknown_coverage: 0, no_usable_pixels: 0, unavailable: 0 } },
      }] }
      else if (url.endsWith('/overlay?index=NDMI')) result = {
        index: 'NDMI', geometry_revision_id: 'revision', display_crs: 'EPSG:3857', display_resampling: 'nearest',
        bounds: [[53, -113], [53.1, -112.9]], png_base64: 'iVBORw0KGgo=',
        color_scale: { stops: [{ value: -1, color: '#b93c5f' }, { value: 0, color: '#5c912f' }, { value: 1, color: '#00e600' }] },
      }
      return { ok: true, status: 200, json: async () => result } as Response
    })
    vi.stubGlobal('fetch', request)
    render(<FarmWorkspace {...props} />)
    const point = await screen.findByRole('button', { name: /NDMI 0\.240.*Landsat/ })
    const ndmi = screen.getByRole('region', { name: 'NDMI by acquisition date' })
    const ndvi = screen.getByRole('region', { name: 'NDVI by acquisition date' })
    expect(within(ndmi).getByText('0.3')).toBeInTheDocument()
    expect(within(ndvi).getByText('0.7')).toBeInTheDocument()
    const checkDailyMean = (chart: HTMLElement, labels: RegExp[]) => {
      expect(within(chart).getByText('Daily mean')).toBeInTheDocument()
      const [first, sameDay, later] = labels.map(name => within(chart).getByRole('button', { name }))
      const vertices = chart.querySelector('polyline')?.getAttribute('points')?.split(' ')
        .map(vertex => vertex.split(',').map(Number))
      expect(vertices).toHaveLength(2)
      for (const [axis, property] of (['left', 'top'] as const).entries()) {
        expect(vertices?.[0][axis]).toBeCloseTo((parseFloat(first.style[property]) + parseFloat(sameDay.style[property])) / 2)
        expect(vertices?.[1][axis]).toBeCloseTo(parseFloat(later.style[property]))
      }
    }
    checkDailyMean(ndmi, [/NDMI 0\.240.*Jul 3/, /NDMI 0\.180.*Jul 3/, /NDMI 0\.160.*Jul 18/])
    checkDailyMean(ndvi, [/NDVI 0\.650.*Jul 3/, /NDVI 0\.550.*Jul 3/, /NDVI 0\.550.*Jul 18/])
    expect(within(point).getByText('NDMI 0.240')).toBeInTheDocument()
    const analyze = screen.getByRole('button', { name: 'Analyze' })
    const recent = screen.getByRole('combobox', { name: 'Recent analyses' })
    expect(analyze.parentElement).toContainElement(recent)
    expect(recent).toHaveValue('series-job')
    expect(screen.getByRole('button', { name: 'Last 180 days' }).compareDocumentPosition(analyze) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const map = screen.getByTestId('farm-map')
    fireEvent.click(point)
    const imageControls = await screen.findByRole('group', { name: 'Map image controls' })
    expect(within(imageControls).getByText('NDMI · Jul 3, 2026 · Landsat')).toBeInTheDocument()
    const legend = within(imageControls).getByRole('group', { name: 'Image colour scale' })
    expect(within(legend).getByText('-1')).toBeInTheDocument()
    expect(within(legend).getByText('1')).toBeInTheDocument()
    expect(within(imageControls).getByRole('button', { name: 'Hide image' })).toBeInTheDocument()
    expect(screen.getByTestId('farm-map')).toBe(map)
    expect(request.mock.calls.some(([url]) => String(url).endsWith('/landsat-job/overlay?index=NDMI'))).toBe(true)
    expect(screen.getByText('1 with 60% usable coverage or less')).toBeInTheDocument()
    expect(screen.getByText(/>60% usable/)).toBeInTheDocument()
    expect(within(screen.getByRole('combobox', { name: 'Acquisition' })).getAllByRole('option')).toHaveLength(4)
    expect(screen.queryByText(/Coverage details|Scene details|Source and processing details|Source and interpretation limits/)).not.toBeInTheDocument()
    fireEvent.change(recent, { target: { value: 'older-series' } })
    expect(screen.getByLabelText('From')).toHaveValue('2026-06-01')
    expect(screen.getByText('No acquisitions had more than 60% usable coverage and a usable index.')).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: 'Acquisition' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'NDVI by acquisition date' })).not.toBeInTheDocument()
  })

  it('switches expanded farms and keeps map, list and browser history in sync', async () => {
    window.history.replaceState(null, '', '#farms?season=2025')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const result = url === '/api/farms' ? { farms } : url.includes('/summary')
        ? { ...(url.includes('/east/') ? fields[1] : fields[0]), season: 2025, seasons: [], geometry_revisions: [], source_status: {}, public_context: {} }
        : { fields, coverage: { boundary_area_m2: null } }
      return { ok: true, json: async () => result }
    }))
    render(<FarmWorkspace {...props} />)
    const home = await screen.findByRole('button', { name: /^Home/ })
    expect(screen.queryByRole('button', { name: /^West/ })).not.toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Map West' }))
    expect(home).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: /^West/ })).toHaveAttribute('aria-pressed', 'true')
    const mapRegion = screen.getByRole('region', { name: 'Farm map' })
    expect(within(mapRegion).getByText('West', { exact: true })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import fields' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Add field' }))
    expect(props.onAddField).toHaveBeenCalledWith('a')
    const westHash = window.location.hash

    fireEvent.click(screen.getByRole('button', { name: /^Second/ }))
    expect(home).toHaveAttribute('aria-expanded', 'false')
    expect(within(mapRegion).queryByText('West', { exact: true })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^East/ }))
    expect(within(mapRegion).getByText('East', { exact: true })).toBeInTheDocument()
    expect(screen.getByTestId('farm-map')).toHaveAttribute('data-geometry', 'none')
    expect(within(screen.getByRole('region', { name: 'Farm map' })).getByText(/Location unknown/)).toBeInTheDocument()

    act(() => {
      window.history.replaceState(null, '', westHash)
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(within(mapRegion).getByText('West', { exact: true })).toBeInTheDocument()
    expect(home).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByTestId('farm-map')).toHaveAttribute('data-field', 'west')
    const season = screen.getByRole('spinbutton', { name: 'Season' })
    expect(season).toHaveValue(2025)
    fireEvent.change(season, { target: { value: '2' } })
    expect(season).toHaveValue(2)
    expect(window.location.hash).toContain('season=2025')
    fireEvent.change(season, { target: { value: '2024' } })
    fireEvent.blur(season)
    expect(window.location.hash).toContain('season=2024')
    fireEvent.click(home)
    expect(home).toHaveAttribute('aria-expanded', 'false')
    expect(window.location.hash).not.toContain('field=')
    await waitFor(() => expect(screen.queryByText('Loading farms…')).not.toBeInTheDocument())
  })
  it('shows retained soil context and refreshes only soil on request', async () => {
    window.history.replaceState(null, '', '#farms?season=2026&field=west&tab=soil')
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      let result: unknown = { id: 'soil-update', status: 'completed' }
      if (url === '/api/farms') result = { farms }
      else if (url.startsWith('/api/farms/overview')) result = { fields, coverage: {} }
      else if (url.includes('/summary')) result = {
        ...fields[0], seasons: [], geometry_revisions: [], public_context: {},
        source_status: { soil: { availability: 'available', freshness: 'current', values: { map_units: [{ name: 'Synthetic soil map unit' }] } } },
      }
      return { ok: true, status: 200, json: async () => result }
    })
    vi.stubGlobal('fetch', request)
    render(<FarmWorkspace {...props} />)
    expect(await screen.findByText('Synthetic soil map unit')).toBeVisible()
    expect(request.mock.calls.some(([url]) => String(url).includes('/enrichment-jobs'))).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Refresh mapped soil' }))
    await waitFor(() => expect(request).toHaveBeenCalledWith('/api/fields/west/enrichment-jobs', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ sources: ['soil'] }),
    })))
  })
  it('shows completion when a soil update finishes before cancellation', async () => {
    window.history.replaceState(null, '', '#farms?season=2026&field=west&tab=soil')
    let summaryReads = 0
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      let result: unknown = { id: 'soil-update', status: 'running' }
      if (url === '/api/farms') result = { farms }
      else if (url.startsWith('/api/farms/overview')) result = { fields, coverage: {} }
      else if (url.includes('/summary')) {
        summaryReads += 1
        result = { ...fields[0], seasons: [], geometry_revisions: [], public_context: {}, source_status: {} }
      } else if (url.endsWith('/cancel')) result = { id: 'soil-update', status: 'completed' }
      return { ok: true, json: async () => result }
    }))
    render(<FarmWorkspace {...props} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Refresh mapped soil' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel update' }))
    expect(await screen.findByText('Updated', { exact: true })).toBeVisible()
    expect(screen.queryByText('Cancelled', { exact: true })).not.toBeInTheDocument()
    await waitFor(() => expect(summaryReads).toBeGreaterThan(1))
  })

  it('drops an in-flight terrain result when the saved boundary revision changes', async () => {
    window.history.replaceState(null, '', '#farms?season=2026&field=west&tab=soil')
    let revision = 'first-revision'
    let resolveTerrain!: (value: unknown) => void
    const terrain = new Promise(resolve => { resolveTerrain = resolve })
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      let result: unknown = { id: 'soil-update', status: 'completed' }
      if (url === '/api/farms') result = { farms }
      else if (url.startsWith('/api/farms/overview')) result = { fields, coverage: {} }
      else if (url.includes('/summary')) result = {
        ...fields[0], name: revision, geometry_revision_id: revision,
        geometry: { kind: 'polygon', points: [], acres: 1 },
        confirmed_facts: { province_state: 'Quebec' }, seasons: [], geometry_revisions: [],
        public_context: {}, source_status: {},
      }
      else if (url.endsWith('/quebec-lidar/plan')) result = await terrain
      return { ok: true, json: async () => result }
    }))
    render(<FarmWorkspace {...props} />)
    fireEvent.click(await screen.findByText('Offline terrain context'))
    fireEvent.click(screen.getByRole('button', { name: 'Check saved field' }))
    revision = 'second-revision'
    fireEvent.click(screen.getByRole('button', { name: 'Refresh mapped soil' }))
    await screen.findByRole('heading', { name: 'second-revision' })
    await act(async () => resolveTerrain({
      status: 'ready_to_download', receipt: { matched_tile_count: 1, field_geometry_sha256: 'prior-boundary' },
    }))
    expect(screen.queryByLabelText('Offline terrain availability receipt')).not.toBeInTheDocument()
  })

  it('reports a malformed farm response without inventing an empty farm',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,status:200,json:async()=>({}),text:async()=>'{}'})))
    render(<FarmWorkspace {...props} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Saved farm information could not be read')
    expect(screen.queryByText('Add your first farm')).not.toBeInTheDocument()
  })
})

describe('retained record intake', () => {
  it('keeps an uncertain save across reload and retries the same captured operation', async () => {
    const { default: FarmRecords } = await import('./FarmRecords')
    localStorage.clear()
    const writes: Array<{ operation_id: string; events: unknown[] }> = []
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
      if (init?.method === 'POST') {
        writes.push(JSON.parse(init.body))
        if (writes.length === 1) throw new TypeError('Connection lost after server acceptance')
        return { ok: true, json: async () => ({ status: 'already_saved', events: writes[0].events.map(event => ({ ...(event as object), id: '550e8400-e29b-41d4-a716-446655440001', field_context_id: 'west', occurred_at: '2026-11-18T12:00:00Z' })) }) }
      }
      return { ok: true, json: async () => ({ events: [], total: 0, next_offset: null }) }
    }))
    const first = render(<FarmRecords key="west:2026" fieldId="west" season={2026} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    fireEvent.change(screen.getByLabelText('What did you observe or do?'), { target: { value: 'Synthetic scouting note' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Save record' }).closest('form')!)
    await screen.findAllByText(/Connection lost after server acceptance/)
    first.unmount()
    render(<FarmRecords key="west:2026" fieldId="west" season={2026} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    expect(screen.getByLabelText('What did you observe or do?')).toHaveValue('Synthetic scouting note')
    expect(screen.getByLabelText('What did you observe or do?')).toBeDisabled()
    fireEvent.submit(screen.getByRole('button', { name: 'Retry saved request' }).closest('form')!)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(writes).toHaveLength(2)
    expect(writes[1]).toEqual(writes[0])
    expect(localStorage.getItem('open-agronomy.record-draft.west.2026')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    expect(screen.getByLabelText('What did you observe or do?')).toHaveValue('')
    localStorage.clear()
  })

  it('isolates field drafts by season and returns to the original draft', async () => {
    const { default: FarmRecords } = await import('./FarmRecords')
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ events: [], total: 0, next_offset: null }) })))
    const view = render(<FarmRecords key="west:2026" fieldId="west" season={2026} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    fireEvent.change(screen.getByLabelText('What did you observe or do?'), { target: { value: '2026 draft' } })
    view.rerender(<FarmRecords key="west:2025" fieldId="west" season={2025} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    expect(screen.getByLabelText('What did you observe or do?')).toHaveValue('')
    view.rerender(<FarmRecords key="west:2026" fieldId="west" season={2026} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    expect(screen.getByLabelText('What did you observe or do?')).toHaveValue('2026 draft')
    localStorage.clear()
  })
})
