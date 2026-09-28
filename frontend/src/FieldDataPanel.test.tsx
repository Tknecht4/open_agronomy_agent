import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FieldDataPanel } from './FieldDataPanel'

const apiGet = vi.hoisted(() => vi.fn())
const apiPost = vi.hoisted(() => vi.fn())
vi.mock('./api', () => ({ apiGet, apiPost }))

const fieldId = 'saved-field-1'
const preview = {
  import_id: 'preview-1',
  status: 'preview',
  profile: {
    filename: 'samples.csv',
    content_sha256: 'a'.repeat(64),
    columns: ['field', 'year', 'nitrate'],
    row_count: 2,
    preview_rows: [
      { locator: { record: 2 }, values: { field: 'North', year: '2025', nitrate: '12' } },
      { locator: { record: 3 }, values: { field: 'South', year: '2025', nitrate: '14' } },
    ],
    warnings: ['Review field identifiers before committing.'],
  },
  mapping_suggestion: {},
}

function file() {
  const result = new File(['field,year,nitrate\nNorth,2025,12\n'], 'samples.csv', { type: 'text/csv' })
  Object.defineProperty(result, 'arrayBuffer', { value: async () => new TextEncoder().encode('field,year,nitrate\nNorth,2025,12\n').buffer })
  return result
}

function open() {
  fireEvent.click(screen.getByText('Field tables and imagery'))
}

describe('FieldDataPanel', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockImplementation(async (path: string) => path === '/api/imagery/providers'
      ? { providers: [
        { id: 'sentinel2-c1-earth-search', name: 'Sentinel-2 Earth Search', access: 'anonymous_metadata_and_cog', account_required: false },
        { id: 'hls-earth-engine', name: 'Earth Engine HLS', access: 'account_and_project_required_not_configured', account_required: true },
      ] }
      : { imports: [] })
  })

  it('previews a bounded upload and commits only after explicit mapping review', async () => {
    const manifest = {
      import_id: 'preview-1',
      source: { title: 'Field lab export' },
      columns: [{ column: 'nitrate' }],
      row_count: 1,
    }
    apiPost.mockResolvedValueOnce(preview).mockResolvedValueOnce({ import: manifest })
    apiGet.mockImplementation(async (path: string) => path === '/api/imagery/providers'
      ? { providers: [] }
      : { imports: apiPost.mock.calls.length > 1 ? [manifest] : [] })
    render(<FieldDataPanel fieldContextId={fieldId} />)
    open()
    fireEvent.change(screen.getByLabelText(/CSV, TSV, or XLSX file/), { target: { files: [file()] } })

    expect(await screen.findByText('Review samples.csv')).toBeInTheDocument()
    expect(screen.getByText(/2 rows · 3 columns/)).toBeInTheDocument()
    expect(screen.getByText('Review field identifiers before committing.')).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'North' })).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(apiPost).toHaveBeenCalledWith(`/api/demo/fields/${fieldId}/data/preview`, expect.objectContaining({ filename: 'samples.csv' }))
    expect(screen.getByLabelText('nitrate aggregation')).toHaveValue('none')
    expect(screen.getByLabelText('nitrate value scope')).toHaveValue('unknown')
    expect(screen.getByRole('button', { name: 'Commit reviewed table' })).toBeDisabled()

    fireEvent.click(screen.getByRole('button', { name: 'Add exact-value filter' }))
    fireEvent.change(screen.getByLabelText('Filter column'), { target: { value: 'field' } })
    fireEvent.change(screen.getByLabelText('Exact value'), { target: { value: 'North' } })
    fireEvent.change(screen.getByLabelText('nitrate role'), { target: { value: 'measurement' } })
    fireEvent.change(screen.getByLabelText('nitrate value scope'), { target: { value: 'record' } })
    fireEvent.change(screen.getByLabelText('nitrate unit'), { target: { value: 'mg/kg' } })
    fireEvent.change(screen.getByLabelText('Source title'), { target: { value: 'Field lab export' } })
    fireEvent.click(screen.getByLabelText(/I reviewed the field filters/))
    fireEvent.click(screen.getByRole('button', { name: 'Commit reviewed table' }))

    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(2))
    expect(apiPost).toHaveBeenLastCalledWith(`/api/demo/fields/${fieldId}/data/preview-1/commit`, {
      mapping: {
        filters: { field: 'North' },
        record_key: [],
        columns: [
          expect.objectContaining({ column: 'field', aggregation: 'none', value_scope: 'unknown' }),
          expect.objectContaining({ column: 'year', aggregation: 'none', value_scope: 'unknown' }),
          expect.objectContaining({ column: 'nitrate', role: 'measurement', unit: 'mg/kg', aggregation: 'none', value_scope: 'record' }),
        ],
        source: { title: 'Field lab export' },
      },
    })
    expect(await screen.findByText('Table committed to this field.')).toBeInTheDocument()
    expect(screen.queryByText('Review samples.csv')).not.toBeInTheDocument()
  })

  it('rejects oversized files locally and preserves a preview on permission failure', async () => {
    apiPost.mockResolvedValueOnce(preview).mockRejectedValueOnce(new Error('403: {"detail":"Field access denied"}'))
    render(<FieldDataPanel fieldContextId={fieldId} />)
    open()
    const oversized = file()
    Object.defineProperty(oversized, 'size', { value: 8 * 1024 * 1024 + 1 })
    fireEvent.change(screen.getByLabelText(/CSV, TSV, or XLSX file/), { target: { files: [oversized] } })
    expect(screen.getByRole('alert')).toHaveTextContent('8 MiB preview limit')
    expect(apiPost).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText(/CSV, TSV, or XLSX file/), { target: { files: [file()] } })
    expect(await screen.findByText('Review samples.csv')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Source title'), { target: { value: 'Source' } })
    fireEvent.click(screen.getByLabelText(/I reviewed the field filters/))
    fireEvent.click(screen.getByRole('button', { name: 'Commit reviewed table' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Field access denied')
    expect(screen.getByText('Review samples.csv')).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledTimes(2)
  })

  it('shows account access and separates scene cloud from unknown field cloud', async () => {
    apiPost.mockResolvedValueOnce({ scenes: [{ id: 'S2-1', datetime: '2025-06-01', scene_cloud_percent: 17 }], count: 1 })
    render(<FieldDataPanel fieldContextId={fieldId} />)
    open()
    const imagery = screen.getByRole('region', { name: 'Field imagery scenes' })
    expect(await within(imagery).findByRole('option', { name: /Sentinel-2 Earth Search · public access/ })).toBeInTheDocument()
    expect(within(imagery).getByRole('option', { name: /Earth Engine HLS · account required/ })).toBeInTheDocument()
    fireEvent.change(within(imagery).getByLabelText('Start date'), { target: { value: '2025-06-01' } })
    fireEvent.change(within(imagery).getByLabelText('End date'), { target: { value: '2025-06-30' } })
    fireEvent.click(within(imagery).getByRole('button', { name: 'Search scenes' }))
    expect(await within(imagery).findByText('S2-1')).toBeInTheDocument()
    expect(within(imagery).getByText('Scene cloud: 17% · field cloud: unknown')).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledWith(`/api/demo/fields/${fieldId}/imagery/search`, {
      provider_id: 'sentinel2-c1-earth-search', start_date: '2025-06-01', end_date: '2025-06-30', limit: 10,
    })
  })

  it('keeps imagery search blocked for a data-only field while allowing table work', async () => {
    render(<FieldDataPanel fieldContextId={fieldId} imageryReady={false} />)
    open()
    const imagery = screen.getByRole('region', { name: 'Field imagery scenes' })
    expect(within(imagery).getByText(/Save the current location or boundary/)).toBeInTheDocument()
    await within(imagery).findByRole('option', { name: /Sentinel-2 Earth Search/ })
    fireEvent.change(within(imagery).getByLabelText('Start date'), { target: { value: '2025-06-01' } })
    fireEvent.change(within(imagery).getByLabelText('End date'), { target: { value: '2025-06-30' } })
    expect(within(imagery).getByRole('button', { name: 'Search scenes' })).toBeDisabled()
    expect(apiPost).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/CSV, TSV, or XLSX file/)).toBeEnabled()
  })

  it('drops an in-flight scene response when the field loses polygon support', async () => {
    let resolveSearch!: (value: unknown) => void
    apiPost.mockReturnValueOnce(new Promise(resolve => { resolveSearch = resolve }))
    const view = render(<FieldDataPanel fieldContextId={fieldId} imageryReady />)
    open()
    const imagery = screen.getByRole('region', { name: 'Field imagery scenes' })
    await within(imagery).findByRole('option', { name: /Sentinel-2 Earth Search/ })
    fireEvent.change(within(imagery).getByLabelText('Start date'), { target: { value: '2025-06-01' } })
    fireEvent.change(within(imagery).getByLabelText('End date'), { target: { value: '2025-06-30' } })
    fireEvent.click(within(imagery).getByRole('button', { name: 'Search scenes' }))
    view.rerender(<FieldDataPanel fieldContextId={fieldId} imageryReady={false} />)
    resolveSearch({ scenes: [{ id: 'STALE-SCENE' }] })
    await waitFor(() => expect(within(imagery).getByRole('button', { name: 'Search scenes' })).toBeDisabled())
    expect(within(imagery).queryByText('STALE-SCENE')).not.toBeInTheDocument()
  })

  it('queries a committed import and presents its source, row locator, and missing counts', async () => {
    const onAskQuestion = vi.fn()
    apiGet.mockImplementation(async (path: string) => path === '/api/imagery/providers'
      ? { providers: [], network_mode: 'offline' }
      : { imports: [{
        import_id: 'committed-1', filename: 'samples.csv', row_count: 1,
        source_sha256: 'b'.repeat(64), source: { title: 'Lab export' },
        columns: [{ column: 'nitrate', aggregation: 'mean' }, { column: 'other_metric', aggregation: 'mean' }],
      }] })
    apiPost.mockResolvedValueOnce({
      operation: 'mean', column: 'nitrate', import_id: 'committed-1', value: 12, selected_row_count: 1, unit: 'mg/kg',
      source: { title: 'Lab export' }, locators: [{ record: 2 }], missing_count: 0,
      invalid_count: 1,
    })
    render(<FieldDataPanel fieldContextId={fieldId} onAskQuestion={onAskQuestion} />)
    open()
    expect(await screen.findByRole('option', { name: 'Lab export' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Query'), { target: { value: 'mean' } })
    fireEvent.change(screen.getByLabelText(/^Column/), { target: { value: 'nitrate' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run table query' }))
    expect(await screen.findByText('Result:')).toHaveProperty('parentElement.textContent', 'Result: 12')
    expect(screen.getByText('Row locators:').parentElement).toHaveTextContent('"record":2')
    expect(screen.getByText(/Missing: 0 · Nonnumeric: 1/)).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledWith(`/api/demo/fields/${fieldId}/data/committed-1/query`, {
      operation: 'mean', column: 'nitrate', limit: 25,
    })
    fireEvent.change(screen.getByLabelText(/^Column/), { target: { value: 'other_metric' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask about this result' }))
    expect(onAskQuestion).toHaveBeenCalledWith('What is the mean nitrate in committed-1?')
  })

  it('discovers scenes at a saved point without requiring optional raster processing or sending a radius', async () => {
    const get = apiGet.getMockImplementation()!
    apiGet.mockImplementation(async (path: string) => path.endsWith('/imagery/analytics')
      ? { status:'not_configured', sampling_modes:['field_polygon','point_pixel','point_buffer'] } : get(path))
    apiPost.mockResolvedValue({ status:'available',query:{geometry_type:'Point',spatial_scope:'at_location'},scenes:[{id:'POINT-SCENE',scene_cloud_percent:15}] })
    render(<FieldDataPanel fieldContextId={fieldId} imageryReady geometryKind="point" geometryKey="point-1" />)
    open()
    const imagery = screen.getByRole('region', {name:'Field imagery scenes'})
    await within(imagery).findByLabelText('Start date')
    fireEvent.change(within(imagery).getByLabelText('Start date'), {target:{value:'2025-06-01'}})
    fireEvent.change(within(imagery).getByLabelText('End date'), {target:{value:'2025-06-30'}})
    await waitFor(() => expect(within(imagery).getByRole('button',{name:'Search scenes'})).toBeEnabled())
    fireEvent.click(within(imagery).getByRole('button',{name:'Search scenes'}))
    expect(await within(imagery).findByText('POINT-SCENE')).toBeInTheDocument()
    expect(within(imagery).getByText('Scene cloud: 15% · sample cloud: unknown')).toBeInTheDocument()
    expect(within(imagery).getByText(/independent of the analysis radius/)).toBeInTheDocument()
    expect(apiPost).toHaveBeenCalledWith(`/api/demo/fields/${fieldId}/imagery/search`,{
      provider_id:'sentinel2-c1-earth-search',start_date:'2025-06-01',end_date:'2025-06-30',limit:10,
    })
  })

  it('does not enable point discovery on an older backend with no advertised point support', async () => {
    render(<FieldDataPanel fieldContextId={fieldId} imageryReady geometryKind="point" geometryKey="point-1" />)
    open()
    const imagery = screen.getByRole('region', {name:'Field imagery scenes'})
    expect(await within(imagery).findByText('Point scene search is not supported by this runtime.')).toBeInTheDocument()
    fireEvent.change(within(imagery).getByLabelText('Start date'), {target:{value:'2025-06-01'}})
    fireEvent.change(within(imagery).getByLabelText('End date'), {target:{value:'2025-06-30'}})
    expect(within(imagery).getByRole('button',{name:'Search scenes'})).toBeDisabled()
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('invalidates a pending scene search when a saved point moves even if readiness stays true', async () => {
    const get = apiGet.getMockImplementation()!
    apiGet.mockImplementation(async (path:string) => path.endsWith('/imagery/analytics') ? {sampling_modes:['point_pixel']} : get(path))
    let release!: (value:unknown)=>void
    apiPost.mockReturnValue(new Promise(resolve=>{release=resolve}))
    const view=render(<FieldDataPanel fieldContextId={fieldId} imageryReady geometryKind="point" geometryKey="point-1" />)
    open()
    const imagery=screen.getByRole('region',{name:'Field imagery scenes'})
    await within(imagery).findByLabelText('Start date')
    fireEvent.change(within(imagery).getByLabelText('Start date'),{target:{value:'2025-06-01'}})
    fireEvent.change(within(imagery).getByLabelText('End date'),{target:{value:'2025-06-30'}})
    await waitFor(()=>expect(within(imagery).getByRole('button',{name:'Search scenes'})).toBeEnabled())
    fireEvent.click(within(imagery).getByRole('button',{name:'Search scenes'}))
    view.rerender(<FieldDataPanel fieldContextId={fieldId} imageryReady geometryKind="point" geometryKey="point-2" />)
    await act(async()=>{release({scenes:[{id:'STALE-POINT'}]})})
    expect(within(imagery).queryByText('STALE-POINT')).not.toBeInTheDocument()
    expect(within(imagery).getByRole('button',{name:'Search scenes'})).toBeEnabled()
  })

})
