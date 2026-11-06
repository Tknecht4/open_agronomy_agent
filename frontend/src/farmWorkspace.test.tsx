import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FarmWorkspace from './FarmWorkspace'
import type { FarmField } from './farmTypes'
vi.mock('./LeafletFieldMap',()=>({LeafletFieldMap:({fieldCollection,onSelectField}:{fieldCollection:Array<{id:string;name:string}>;onSelectField:(id:string)=>void})=><div aria-label="Test map">{fieldCollection.map(field=><button key={field.id} onClick={()=>onSelectField(field.id)}>Map {field.name}</button>)}</div>}))
vi.mock('./FieldSyncPanel',()=>({FieldSyncPanel:()=>null}))
const field = (id:string,name:string,farm:string,located:boolean):FarmField=>({id,name,farm_id:farm,assignment_revision:1,season:2026,crop:null,crop_status:'unknown',season_revision:0,legacy_undated_crop:'Wheat',geometry:located?{kind:'point',point:{lat:53,lon:-113}}:{kind:'none'},geometry_revision_id:'revision',geometry_sha256:'hash',geometry_status:located?'point':'unknown',boundary_area_m2:null,boundary_perimeter_m:null,record_count:0,last_record_at:null,updated_at:'2026-11-05',country:null})
const fields=[field('west','West','a',true),field('east','East','b',false)]
const farms=[{id:'a',name:'Home',revision:1,archived:0},{id:'b',name:'Second',revision:1,archived:0}]
const props={mode:'farms' as const,allowNetwork:false,refreshKey:'1',onAddField:vi.fn(),onEditField:vi.fn(),onAsk:vi.fn(),onGeneralQuestion:vi.fn(),onFieldsImported:vi.fn()}
afterEach(()=>{vi.unstubAllGlobals();window.history.replaceState(null,'','#farms')})
describe('farm cockpit workflows',()=>{
  it('keeps table and map selection together and confirms a season without changing a legacy crop',async()=>{
    window.history.replaceState(null,'','#farms?season=2026')
    let crop:string|null=null
    const request=vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
      const url=String(input)
      let result:unknown={}
      if(url==='/api/farms')result={farms}
      else if(url.startsWith('/api/farms/overview'))result={fields,coverage:{boundary_area_m2:null}}
      else if(url.startsWith('/api/fields/west/summary'))result={...fields[0],crop,seasons:[],geometry_revisions:[],source_status:{},public_context:{}}
      else if(url==='/api/fields/west/seasons/2026'){crop=JSON.parse(String(init?.body)).crops.map((item:{crop:string})=>item.crop).join(' + ');result={crop}}
      return {ok:true,status:200,json:async()=>result,text:async()=>JSON.stringify(result)} as Response
    })
    vi.stubGlobal('fetch',request)
    render(<FarmWorkspace {...props} mode="fields" />)
    await screen.findByRole('button',{name:'West'})
    expect(screen.getByRole('button',{name:'Show East on map'})).toBeDisabled()
    fireEvent.click(await screen.findByRole('button',{name:'Map West'}))
    expect(screen.getByRole('row',{name:/West.*Home/})).toHaveAttribute('aria-selected','true')
    fireEvent.click(screen.getByRole('button',{name:'West'}))
    expect(await screen.findByText(/An older entry says/)).toHaveTextContent('without a year')
    fireEvent.click(screen.getByRole('button',{name:'Confirm crop & season'}))
    const dialog=await screen.findByRole('dialog',{name:'Confirm 2026 season'})
    fireEvent.change(within(dialog).getByLabelText('Crop 1'),{target:{value:'Canola'}})
    fireEvent.click(within(dialog).getByRole('button',{name:'Add another crop'}))
    fireEvent.change(within(dialog).getByLabelText('Crop 2'),{target:{value:'Pea'}})
    fireEvent.change(within(dialog).getByLabelText('How do the crops share this field?'),{target:{value:'intercrop'}})
    fireEvent.click(within(dialog).getByRole('button',{name:'Save season'}))
    await waitFor(()=>expect(crop).toBe('Canola + Pea'))
    expect(await screen.findByText(/An older entry says/)).toHaveTextContent('Wheat')
    fireEvent.click(screen.getByRole('button',{name:'Ask about this field'}))
    expect(props.onAsk).toHaveBeenCalledWith('west',undefined,2026)
  })
  it('opens one farm at a time and returns from field detail with the farm and season intact', async () => {
    window.history.replaceState(null, '', '#farms?season=2025')
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const result = url === '/api/farms' ? { farms } : url.includes('/summary')
        ? { ...fields[0], season: 2025, seasons: [], geometry_revisions: [], source_status: {}, public_context: {} }
        : { fields, coverage: { boundary_area_m2: null } }
      return { ok: true, json: async () => result }
    }))
    render(<FarmWorkspace {...props} />)
    const home = await screen.findByRole('button', { name: /Home.*1.*Unknown area/ })
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    fireEvent.click(home)
    expect(await screen.findByRole('heading', { level: 1, name: 'Home' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'East' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'West' }))
    await screen.findByRole('heading', { level: 1, name: 'West' })
    expect(screen.queryByRole('button', { name: 'Import fields' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Home' }))
    expect(screen.getByRole('heading', { level: 1, name: 'Home' })).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: 'Season' })).toHaveValue(2025)
    expect(window.location.hash).toContain('farm=a')
    fireEvent.click(screen.getByRole('button', { name: 'Farms' }))
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View all 2 fields' })).toHaveAttribute('href', '#fields?season=2025')
  })
  it('reports a malformed farm response without inventing an empty farm',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,status:200,json:async()=>({}),text:async()=>'{}'})))
    render(<FarmWorkspace {...props} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Saved farm information could not be read')
    expect(screen.queryByText('Start with your farm')).not.toBeInTheDocument()
  })
})

describe('retained record intake', () => {
  it('keeps an uncertain save across reload and retries the same operation without duplicating it', async () => {
    const { default: FarmRecords } = await import('./FarmRecords')
    localStorage.clear()
    const writes: Array<{ operation_id: string; events: unknown[] }> = []
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
      if (init?.method === 'POST') {
        writes.push(JSON.parse(init.body))
        if (writes.length === 1) throw new TypeError('Connection lost after server acceptance')
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
    fireEvent.submit(screen.getByRole('button', { name: 'Save record' }).closest('form')!)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(writes).toHaveLength(2)
    expect(writes[1]).toEqual(writes[0])
    await waitFor(() => expect(JSON.parse(localStorage.getItem('open-agronomy.record-draft.west.2026')!).summary).toBe(''))
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
