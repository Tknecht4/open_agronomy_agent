import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { apiGet, apiPost } from './api'
import './FieldDataPanel.css'

type DataRole = 'measurement' | 'context' | 'identifier'
type Aggregation = 'none' | 'mean' | 'sum' | 'unique'
type EvidenceRole = 'observation' | 'model_output' | 'interpretation' | 'regional_prior'
type ValueScope = 'unknown' | 'record' | 'field_season'
type ColumnMapping = {
  column: string
  label: string
  unit: string | null
  role: DataRole
  aggregation: Aggregation
  evidence_role: EvidenceRole
  value_scope: ValueScope
}
type Mapping = {
  filters: Record<string, string>
  record_key: string[]
  columns: ColumnMapping[]
  source: { title: string; url?: string; license?: string; citation?: string }
}
type Preview = {
  import_id: string
  status: 'preview'
  profile: {
    filename: string
    content_sha256: string
    columns: string[]
    row_count: number
    preview_rows: Array<{ locator?: Record<string, unknown>; values?: Record<string, unknown> } | Record<string, unknown>>
    encoding?: string
    delimiter?: string
    warnings?: string[]
  }
  mapping_suggestion?: Partial<Mapping>
}
type ImportManifest = Record<string, unknown> & { import_id?: string; id?: string }
type Provider = Record<string, unknown> & { id?: string; provider_id?: string; name?: string; label?: string }
type Scene = Record<string, unknown>
type QueryOperation = 'rows' | 'count' | 'mean' | 'sum' | 'unique'

const MAX_FILE_BYTES = 8 * 1024 * 1024
const PREVIEW_ROWS = 5

function asObject(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function asText(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}

function readableError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  const match = message.match(/^\d+:\s*(.*)$/s)
  if (!match) return message
  try {
    const payload = JSON.parse(match[1]) as Record<string, unknown>
    const detail = payload.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') return asText(asObject(detail).message || asObject(detail).code) || message
  } catch {
    // The API can also return a plain-text error.
  }
  return message
}

async function base64File(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return btoa(binary)
}

function manifestId(manifest: ImportManifest): string {
  return asText(manifest.import_id || manifest.id)
}

function providerId(provider: Provider): string {
  return asText(provider.provider_id || provider.id)
}

function providerAccess(provider: Provider): string {
  return asText(provider.access || provider.access_mode || provider.authentication || provider.status).toLowerCase()
}

function needsAccount(provider: Provider): boolean {
  return provider.account_required === true || /account|credential|authenticated/.test(providerAccess(provider))
}

function sourceSummary(value: unknown): string {
  const source = asObject(value)
  return asText(source.title || source.name || source.url || value)
}

function TablePreview({ columns, rows, limit = PREVIEW_ROWS }: { columns: string[]; rows: Record<string, unknown>[]; limit?: number }) {
  return <div className="field-data-table-scroll"><table>
    <thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
    <tbody>{rows.slice(0, limit).map((row, index) => <tr key={index}>
      {columns.map((column) => <td key={column}>{asText(row[column]) || '—'}</td>)}
    </tr>)}</tbody>
  </table></div>
}

export function FieldDataPanel({
  fieldContextId,
  imageryReady = true,
  geometryKind = 'polygon',
  geometryKey = '',
  onAskQuestion,
}: {
  fieldContextId: string
  imageryReady?: boolean
  geometryKind?: 'none' | 'point' | 'polygon'
  geometryKey?: string
  onAskQuestion?: (question: string) => void
}) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [columns, setColumns] = useState<ColumnMapping[]>([])
  const [filters, setFilters] = useState<Array<{ column: string; value: string }>>([])
  const [recordKey, setRecordKey] = useState<string[]>([])
  const [source, setSource] = useState({ title: '', url: '', license: '', citation: '' })
  const [encoding, setEncoding] = useState('utf-8-sig')
  const [reviewed, setReviewed] = useState(false)
  const [imports, setImports] = useState<ImportManifest[]>([])
  const [importsState, setImportsState] = useState('Loading committed imports…')
  const [selectedImport, setSelectedImport] = useState('')
  const [operation, setOperation] = useState<QueryOperation>('rows')
  const [queryColumn, setQueryColumn] = useState('')
  const [queryFilterColumn, setQueryFilterColumn] = useState('')
  const [queryFilterValue, setQueryFilterValue] = useState('')
  const [queryResult, setQueryResult] = useState<Record<string, unknown> | null>(null)
  const [queryState, setQueryState] = useState('')
  const [providers, setProviders] = useState<Provider[]>([])
  const [providerState, setProviderState] = useState('Loading imagery sources…')
  const [networkMode, setNetworkMode] = useState('')
  const [selectedProvider, setSelectedProvider] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [scenes, setScenes] = useState<Scene[]>([])
  const [imageryState, setImageryState] = useState('')
  const [busy, setBusy] = useState<'preview' | 'commit' | 'query' | 'imagery' | ''>('')
  const [dataError, setDataError] = useState('')
  const imageryRequestRef = useRef(0)
  const [pointSearchSupport, setPointSearchSupport] = useState<'checking' | 'supported' | 'unsupported' | 'error'>('checking')
  const point = geometryKind === 'point'
  const canSearchImagery = imageryReady && geometryKind !== 'none' && (!point || pointSearchSupport === 'supported')

  useEffect(() => {
    if (!point) return
    let active = true
    setPointSearchSupport('checking')
    void apiGet<{ sampling_modes?: string[] }>(`/api/demo/fields/${encodeURIComponent(fieldContextId)}/imagery/analytics`)
      .then(result => { if (active) setPointSearchSupport(result.sampling_modes?.includes('point_pixel') ? 'supported' : 'unsupported') })
      .catch(() => { if (active) setPointSearchSupport('error') })
    return () => { active = false }
  }, [fieldContextId, point])

  useEffect(() => {
    imageryRequestRef.current += 1
    setScenes([])
    setImageryState('')
    setBusy((current) => current === 'imagery' ? '' : current)
    return () => { imageryRequestRef.current += 1 }
  }, [fieldContextId, geometryKey, geometryKind, imageryReady, selectedProvider, startDate, endDate])

  useEffect(() => {
    let active = true
    setPreview(null)
    setColumns([])
    setFilters([])
    setImports([])
    setSelectedImport('')
    setQueryResult(null)
    setScenes([])
    setDataError('')
    setImportsState('Loading committed imports…')
    setProviderState('Loading imagery sources…')
    void apiGet<{ imports: ImportManifest[] }>(`/api/demo/fields/${encodeURIComponent(fieldContextId)}/data`)
      .then((result) => {
        if (!active) return
        const next = Array.isArray(result.imports) ? result.imports : []
        setImports(next)
        setSelectedImport(manifestId(next[0] || {}))
        setImportsState(next.length ? `${next.length} committed import${next.length === 1 ? '' : 's'}.` : 'No committed tables for this field.')
      })
      .catch((error) => { if (active) setImportsState(`Could not load imports: ${readableError(error)}`) })
    void apiGet<{ providers?: Provider[]; network_mode?: string } | Provider[]>('/api/imagery/providers')
      .then((result) => {
        if (!active) return
        const next = Array.isArray(result) ? result : result.providers || []
        const mode = Array.isArray(result) ? '' : asText(result.network_mode)
        setNetworkMode(mode)
        setProviders(next)
        const anonymous = next.find((provider) => !needsAccount(provider))
        setSelectedProvider(providerId(anonymous || next[0] || {}))
        setProviderState(next.length ? mode === 'offline' ? 'Scene search is paused while network access is off.' : '' : 'No imagery sources are available.')
      })
      .catch((error) => { if (active) setProviderState(`Could not load imagery sources: ${readableError(error)}`) })
    return () => { active = false }
  }, [fieldContextId])

  const previewFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setPreview(null)
    setReviewed(false)
    setDataError('')
    if (file.size > MAX_FILE_BYTES) {
      setDataError('This file exceeds the 8 MiB preview limit. Choose a smaller export.')
      return
    }
    if (!/\.(csv|tsv|xlsx)$/i.test(file.name)) {
      setDataError('Choose a CSV, TSV, or XLSX file.')
      return
    }
    setBusy('preview')
    try {
      const result = await apiPost<Preview>(`/api/demo/fields/${encodeURIComponent(fieldContextId)}/data/preview`, {
        filename: file.name,
        base64_content: await base64File(file),
        ...(/\.xlsx$/i.test(file.name) ? {} : { encoding }),
      })
      const names = result.profile?.columns || []
      setColumns(names.map((name) => {
        const suggested = result.mapping_suggestion?.columns?.find((item) => item.column === name)
        return {
          column: name,
          label: suggested?.label || name,
          unit: suggested?.unit || null,
          role: suggested?.role || 'context',
          aggregation: 'none',
          evidence_role: suggested?.evidence_role || 'observation',
          value_scope: suggested?.value_scope || 'unknown',
        }
      }))
      setFilters([])
      setRecordKey([])
      setSource({ title: '', url: '', license: '', citation: '' })
      setPreview(result)
    } catch (error) {
      setDataError(`Preview failed: ${readableError(error)}`)
    } finally {
      setBusy('')
    }
  }

  const updateColumn = (name: string, patch: Partial<ColumnMapping>) => {
    setColumns((current) => current.map((column) => {
      if (column.column !== name) return column
      const updated = { ...column, ...patch }
      if (updated.value_scope === 'field_season' && (updated.aggregation === 'mean' || updated.aggregation === 'sum')) {
        updated.aggregation = 'none'
      }
      if (updated.value_scope !== 'record' && updated.aggregation === 'sum') updated.aggregation = 'none'
      return updated
    }))
    setReviewed(false)
  }

  const commit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!preview || !reviewed) return
    setDataError('')
    if (!source.title.trim()) {
      setDataError('Enter a source title before committing this table.')
      return
    }
    const selectedFilters = filters.filter((filter) => filter.column && filter.value !== '')
    if (selectedFilters.length !== filters.length || new Set(selectedFilters.map((filter) => filter.column)).size !== filters.length) {
      setDataError('Each exact-value filter needs a distinct column and a value.')
      return
    }
    if (columns.some((column) => column.aggregation === 'sum' && (column.value_scope !== 'record' || !recordKey.length))) {
      setDataError('Sum needs record-level values and a row identity column.')
      return
    }
    const mapping: Mapping = {
      filters: Object.fromEntries(selectedFilters.map(({ column, value }) => [column, value])),
      record_key: recordKey,
      columns,
      source: {
        title: source.title.trim(),
        ...(source.url.trim() ? { url: source.url.trim() } : {}),
        ...(source.license.trim() ? { license: source.license.trim() } : {}),
        ...(source.citation.trim() ? { citation: source.citation.trim() } : {}),
      },
    }
    setBusy('commit')
    try {
      const result = await apiPost<{ import: ImportManifest }>(
        `/api/demo/fields/${encodeURIComponent(fieldContextId)}/data/${encodeURIComponent(preview.import_id)}/commit`,
        { mapping },
      )
      const next = await apiGet<{ imports: ImportManifest[] }>(`/api/demo/fields/${encodeURIComponent(fieldContextId)}/data`)
      setImports(next.imports || [])
      setSelectedImport(manifestId(result.import || {}))
      setImportsState('Table committed to this field.')
      setPreview(null)
      setReviewed(false)
    } catch (error) {
      setDataError(`Commit failed; the preview remains available: ${readableError(error)}`)
    } finally {
      setBusy('')
    }
  }

  const runQuery = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedImport) return
    setQueryResult(null)
    setQueryState('Running a deterministic table query…')
    setBusy('query')
    try {
      const result = await apiPost<Record<string, unknown>>(
        `/api/demo/fields/${encodeURIComponent(fieldContextId)}/data/${encodeURIComponent(selectedImport)}/query`,
        {
          operation,
          ...(queryColumn ? { column: queryColumn } : {}),
          ...(queryFilterColumn && queryFilterValue ? { filters: { [queryFilterColumn]: queryFilterValue } } : {}),
          limit: 25,
        },
      )
      setQueryResult(result)
      setQueryState('Query complete. Values are from the committed table.')
    } catch (error) {
      setQueryState(`Query failed: ${readableError(error)}`)
    } finally {
      setBusy('')
    }
  }

  const searchImagery = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canSearchImagery || busy !== '' || !selectedProvider || !startDate || !endDate) return
    if (endDate < startDate) {
      setImageryState('End date must be on or after start date.')
      return
    }
    setScenes([])
    setImageryState('Searching scene metadata…')
    setBusy('imagery')
    const requestId = ++imageryRequestRef.current
    try {
      const result = await apiPost<Record<string, unknown>>(
        `/api/demo/fields/${encodeURIComponent(fieldContextId)}/imagery/search`,
        { provider_id: selectedProvider, start_date: startDate, end_date: endDate, limit: 10 },
      )
      const found = result.scenes || result.features || result.items
      const next = Array.isArray(found) ? found as Scene[] : []
      if (requestId !== imageryRequestRef.current) return
      setScenes(next)
      const resultStatus = asText(result.status)
      setImageryState(next.length
        ? `${next.length} scene${next.length === 1 ? '' : 's'} found.`
        : resultStatus === 'blocked_offline' ? 'Scene search is paused while network access is off.'
          : resultStatus === 'not_configured' ? 'This source requires an account and project setup.'
            : resultStatus === 'unavailable' ? 'The imagery source is unavailable right now.'
              : asText(result.message) || 'No scenes found in this window.')
    } catch (error) {
      if (requestId === imageryRequestRef.current) setImageryState(`Imagery search unavailable: ${readableError(error)}`)
    } finally {
      if (requestId === imageryRequestRef.current) setBusy('')
    }
  }

  const selectedManifest = imports.find((item) => manifestId(item) === selectedImport)
  const selectedProviderDetails = providers.find((item) => providerId(item) === selectedProvider)
  const selectedColumnSpecs = Array.isArray(selectedManifest?.columns) ? selectedManifest.columns.map(asObject) : []
  const mappedColumns = Array.isArray(selectedManifest?.columns)
    ? selectedManifest.columns.map((item) => asText(asObject(item).column)).filter(Boolean)
    : []
  const queryRows = queryResult && Array.isArray(queryResult.rows) ? queryResult.rows as Record<string, unknown>[] : []
  const queryTableRows = queryRows.map((row) => asObject(row.values || row))
  const previewTableRows = (preview?.profile.preview_rows || []).map((row) => asObject(row.values || row))
  const queryRecord = queryResult ? asObject(queryResult) : {}
  const queryValue = queryRecord.value ?? queryRecord.result ?? queryRecord.count
  const displayedValue = typeof queryValue === 'number'
    ? queryValue.toLocaleString(undefined, { maximumSignificantDigits: 10 })
    : Array.isArray(queryValue) ? queryValue.map(asText).join(', ') : asText(queryValue)
  const querySource = queryRecord.source || selectedManifest?.source
  const queryLocators = queryRecord.rowlocators || queryRecord.locators || queryRecord.row_locators || queryRecord.source_locators
  const questionFromReceipt = () => {
    const receiptOperation = asText(queryRecord.operation)
    const receiptImport = asText(queryRecord.import_id)
    const receiptColumn = asText(queryRecord.column)
    if (!receiptImport) return null
    if (receiptOperation === 'count') return `How many records in ${receiptImport}?`
    if (receiptOperation === 'rows') return `Show rows from ${receiptImport}`
    if (!receiptColumn) return null
    if (receiptOperation === 'unique') return `List unique ${receiptColumn} in ${receiptImport}`
    if (receiptOperation === 'mean' || receiptOperation === 'sum') return `What is the ${receiptOperation} ${receiptColumn} in ${receiptImport}?`
    return null
  }
  const receiptQuestion = questionFromReceipt()

  return <details className="workspace-disclosure field-data-panel">
    <summary>Field tables and imagery</summary>
    <p>Import a field table after reviewing its columns and source. Scene searches show imagery metadata, not a diagnosis.</p>
    <section aria-label="Field table import">
      <h3>Import a table</h3>
      <label>Text encoding
        <select value={encoding} onChange={(event) => setEncoding(event.target.value)} disabled={Boolean(busy)}>
          <option value="utf-8-sig">UTF-8</option><option value="latin-1">Latin-1</option>
        </select>
      </label>
      <label>CSV, TSV, or XLSX file (8 MiB maximum)
        <input type="file" accept=".csv,.tsv,.xlsx,text/csv,text/tab-separated-values,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => void previewFile(event)} disabled={Boolean(busy)} />
      </label>
      {busy === 'preview' ? <p role="status">Reading and previewing table…</p> : null}
      {dataError ? <p role="alert">{dataError}</p> : null}
      {preview ? <form onSubmit={(event) => void commit(event)}>
        <h4>Review {preview.profile.filename}</h4>
        <p>{preview.profile.row_count} rows · {preview.profile.columns.length} columns · source hash {preview.profile.content_sha256.slice(0, 12)}</p>
        {preview.profile.warnings?.map((warning, index) => <p className="field-data-warning" key={index}>{warning}</p>)}
        <TablePreview columns={preview.profile.columns} rows={previewTableRows} />
        <p>Choose exact field or year values when an export includes more than this field. Only matching rows will be committed.</p>
        {filters.map((filter, index) => <div className="field-data-filter" key={index}>
          <label>Filter column
            <select value={filter.column} onChange={(event) => { setFilters((current) => current.map((item, position) => position === index ? { ...item, column: event.target.value } : item)); setReviewed(false) }}>
              <option value="">Choose column</option>{preview.profile.columns.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </label>
          <label>Exact value <input value={filter.value} onChange={(event) => { setFilters((current) => current.map((item, position) => position === index ? { ...item, value: event.target.value } : item)); setReviewed(false) }} /></label>
          <button type="button" onClick={() => { setFilters((current) => current.filter((_, position) => position !== index)); setReviewed(false) }}>Remove filter</button>
        </div>)}
        <button type="button" onClick={() => { setFilters((current) => [...current, { column: '', value: '' }]); setReviewed(false) }}>Add exact-value filter</button>
        <fieldset><legend>Record identity columns</legend>
          <p>Select columns that identify a row, such as a sample ID or date.</p>
          <div className="field-data-checks">{preview.profile.columns.map((name) => <label key={name}><input type="checkbox" checked={recordKey.includes(name)} onChange={(event) => { setRecordKey((current) => event.target.checked ? [...current, name] : current.filter((item) => item !== name)); setReviewed(false) }} />{name}</label>)}</div>
        </fieldset>
        <div className="field-data-table-scroll"><table className="field-data-mapping">
          <caption>Review each column; aggregation starts at none.</caption>
          <thead><tr><th scope="col">Column</th><th scope="col">Label</th><th scope="col">Unit</th><th scope="col">Role</th><th scope="col">Value applies to</th><th scope="col">Aggregation</th><th scope="col">Evidence</th></tr></thead>
          <tbody>{columns.map((item) => <tr key={item.column}>
            <th scope="row">{item.column}</th>
            <td><input aria-label={`${item.column} label`} value={item.label} onChange={(event) => updateColumn(item.column, { label: event.target.value })} /></td>
            <td><input aria-label={`${item.column} unit`} value={item.unit || ''} placeholder="unknown" onChange={(event) => updateColumn(item.column, { unit: event.target.value || null })} /></td>
            <td><select aria-label={`${item.column} role`} value={item.role} onChange={(event) => updateColumn(item.column, { role: event.target.value as DataRole })}><option value="context">Context</option><option value="measurement">Measurement</option><option value="identifier">Identifier</option></select></td>
            <td><select aria-label={`${item.column} value scope`} value={item.value_scope} onChange={(event) => updateColumn(item.column, { value_scope: event.target.value as ValueScope })}><option value="unknown">Unknown</option><option value="record">Each record</option><option value="field_season">Whole field or season</option></select></td>
            <td><select aria-label={`${item.column} aggregation`} value={item.aggregation} onChange={(event) => updateColumn(item.column, { aggregation: event.target.value as Aggregation })}><option value="none">None</option><option value="mean" disabled={item.value_scope === 'field_season'}>Mean</option><option value="sum" disabled={item.value_scope !== 'record' || !recordKey.length}>Sum</option><option value="unique">Unique</option></select></td>
            <td><select aria-label={`${item.column} evidence role`} value={item.evidence_role} onChange={(event) => updateColumn(item.column, { evidence_role: event.target.value as EvidenceRole })}><option value="observation">Observation</option><option value="model_output">Model output</option><option value="interpretation">Interpretation</option><option value="regional_prior">Regional prior</option></select></td>
          </tr>)}</tbody>
        </table></div>
        <div className="field-data-source">
          <label>Source title <input required value={source.title} onChange={(event) => { setSource({ ...source, title: event.target.value }); setReviewed(false) }} /></label>
          <label>Source URL (optional) <input type="url" value={source.url} onChange={(event) => { setSource({ ...source, url: event.target.value }); setReviewed(false) }} /></label>
          <label>License (if known) <input value={source.license} onChange={(event) => { setSource({ ...source, license: event.target.value }); setReviewed(false) }} /></label>
          <label>Citation (optional) <input value={source.citation} onChange={(event) => { setSource({ ...source, citation: event.target.value }); setReviewed(false) }} /></label>
        </div>
        <small>Source details are supplied by you; importing does not verify ownership or reuse rights.</small>
        <label className="field-data-review"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />I reviewed the field filters, value scope, aggregation, and source.</label>
        <button type="submit" disabled={busy !== '' || !reviewed || !source.title.trim()}>{busy === 'commit' ? 'Committing…' : 'Commit reviewed table'}</button>
      </form> : null}
    </section>
    <section aria-label="Committed field tables">
      <h3>Committed tables</h3>
      <p role="status">{importsState}</p>
      {imports.length ? <ul className="field-data-imports">{imports.map((item) => <li key={manifestId(item)}>
        <strong>{sourceSummary(item.source) || asText(item.filename) || manifestId(item)}</strong>
        <span>{asText(item.row_count)} rows · {asText(item.filename)} · source hash {asText(item.source_sha256).slice(0, 12)}</span>
      </li>)}</ul> : null}
      {imports.length ? <form onSubmit={(event) => void runQuery(event)}>
        <label>Table <select value={selectedImport} onChange={(event) => { setSelectedImport(event.target.value); setQueryColumn(''); setQueryFilterColumn(''); setQueryFilterValue(''); setQueryResult(null) }}>{imports.map((item) => <option key={manifestId(item)} value={manifestId(item)}>{sourceSummary(item.source) || asText(item.filename) || manifestId(item)}</option>)}</select></label>
        <label>Query <select value={operation} onChange={(event) => { setOperation(event.target.value as QueryOperation); setQueryColumn(''); setQueryResult(null) }}><option value="rows">Rows</option><option value="count">Count</option><option value="mean">Mean</option><option value="sum">Sum</option><option value="unique">Unique</option></select></label>
        {operation !== 'count' ? <label>Column {operation === 'rows' ? '(optional)' : ''}<select value={queryColumn} onChange={(event) => setQueryColumn(event.target.value)}><option value="">{operation === 'rows' ? 'All columns' : 'Choose column'}</option>{mappedColumns.filter((name) => operation === 'rows' || selectedColumnSpecs.find((item) => item.column === name)?.aggregation === operation).map((name) => <option key={name} value={name}>{name}</option>)}</select></label> : null}
        <div className="field-data-filter"><label>Exact filter column (optional) <select value={queryFilterColumn} onChange={(event) => { setQueryFilterColumn(event.target.value); setQueryFilterValue('') }}><option value="">All committed rows</option>{mappedColumns.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>
          {queryFilterColumn ? <label>Exact filter value <input value={queryFilterValue} onChange={(event) => setQueryFilterValue(event.target.value)} /></label> : null}</div>
        <button type="submit" disabled={busy !== '' || !selectedImport || (operation !== 'rows' && operation !== 'count' && !queryColumn) || Boolean(queryFilterColumn && !queryFilterValue)}>{busy === 'query' ? 'Querying…' : 'Run table query'}</button>
      </form> : null}
      {queryState ? <p role="status">{queryState}</p> : null}
      {queryResult ? <div className="field-data-query-result">
        <p>Last query: {asText(queryRecord.operation)} {asText(queryRecord.column)}</p>
        {queryValue !== undefined ? <p title={`Exact value: ${asText(queryValue)}`}><strong>Result:</strong> {queryValue === null ? 'No valid numeric values' : displayedValue}</p> : null}
        {queryTableRows.length ? <TablePreview columns={Object.keys(queryTableRows[0])} rows={queryTableRows} limit={25} /> : null}
        <p>Selected rows: {asText(queryRecord.selected_row_count ?? 'unknown')}{queryRecord.truncated ? ' · output truncated' : ''}{queryRecord.unit ? ` · ${asText(queryRecord.unit)}` : ''}{queryRecord.value_scope ? ` · ${asText(queryRecord.value_scope).replace(/_/g, ' ')} value` : ''}</p>
        {querySource ? <p><strong>Source:</strong> {sourceSummary(querySource)}</p> : null}
        {queryLocators ? <details><summary>Source row provenance</summary><p><strong>Row locators:</strong> {JSON.stringify(queryLocators)}</p></details> : null}
        <p>Missing: {asText(queryRecord.missing_count ?? queryRecord.missing ?? 'unknown')} · Nonnumeric: {asText(queryRecord.invalid_count ?? queryRecord.nonnumeric_count ?? 'unknown')}</p>
        {onAskQuestion && receiptQuestion && !Object.keys(asObject(queryRecord.filters)).length ? <button type="button" onClick={() => onAskQuestion(receiptQuestion)}>Ask about this result</button> : null}
        {Object.keys(asObject(queryRecord.filters)).length ? <p>Filtered results remain in this query panel; conversational queries currently use the full committed selection.</p> : null}
      </div> : null}
    </section>
    <section aria-label="Field imagery scenes">
      <h3>Imagery scenes</h3>
      {!imageryReady || geometryKind === 'none' ? <p>Save the current location or boundary before searching imagery. Unknown geometry stays unavailable.</p> : null}
      {point ? <p>Search scenes at the saved location. This is independent of the analysis radius; scene cloud cover does not describe the sampled pixel.</p> : null}
      {point && pointSearchSupport !== 'supported' ? <p role="status">{pointSearchSupport === 'checking' ? 'Checking point scene-search support…' : pointSearchSupport === 'error' ? 'Point scene-search support could not be checked.' : 'Point scene search is not supported by this runtime.'}</p> : null}
      <p role="status">{providerState}</p>
      {providers.length ? <form onSubmit={(event) => void searchImagery(event)}>
        <label>Imagery source <select value={selectedProvider} onChange={(event) => setSelectedProvider(event.target.value)}>{providers.map((provider) => <option key={providerId(provider)} value={providerId(provider)}>{asText(provider.label || provider.name || providerId(provider))}{needsAccount(provider) ? ' · account required' : ' · public access'}</option>)}</select></label>
        {selectedProviderDetails ? <div className="field-data-provider-details">
          <p>{needsAccount(selectedProviderDetails) ? 'Account and project setup required.' : 'Public scene discovery.'}{networkMode === 'offline' ? ' Network access is off.' : ''}</p>
          <p>Source: {asText(selectedProviderDetails.source) || 'unknown'}</p>
          <p>Rights: {asText(selectedProviderDetails.rights) || 'check provider terms'}</p>
          <p>Available: {Array.isArray(selectedProviderDetails.capabilities) && selectedProviderDetails.capabilities.length
            ? selectedProviderDetails.capabilities.map((item) => asText(item).replace(/_/g, ' ')).join(', ')
            : 'source setup required'}</p>
          <p>{asText(selectedProviderDetails.limitations)}</p>
        </div> : null}
        <div className="field-data-dates"><label>Start date <input type="date" required value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label><label>End date <input type="date" required value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label></div>
        <button type="submit" disabled={!canSearchImagery || busy !== '' || !selectedProvider || !startDate || !endDate}>{busy === 'imagery' ? 'Searching…' : 'Search scenes'}</button>
      </form> : null}
      {imageryState ? <p role="status">{imageryState}</p> : null}
      {canSearchImagery && scenes.length ? <ul className="field-data-scenes">{scenes.map((scene, index) => {
        const properties = asObject(scene.properties)
        const cloud = scene.scene_cloud_percent ?? scene.cloud_cover ?? properties['eo:cloud_cover']
        return <li key={asText(scene.id) || index}>
          <strong>{asText(scene.title || scene.id || `Scene ${index + 1}`)}</strong>
          <span>Acquired: {asText(scene.acquired_at || scene.datetime || properties.datetime || scene.date) || 'unknown'}</span>
          <span>Scene cloud: {cloud === undefined || cloud === null ? 'unknown' : `${asText(cloud)}%`} · {point ? 'sample' : 'field'} cloud: unknown</span>
          {scene.license ? <span>License: {asText(scene.license)}</span> : null}
        </li>
      })}</ul> : null}
    </section>
  </details>
}

export default FieldDataPanel
