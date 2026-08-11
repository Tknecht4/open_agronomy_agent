import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FieldSyncPanel } from './FieldSyncPanel'

const apiGetMock = vi.hoisted(() => vi.fn())

vi.mock('./api', () => ({ apiGet: apiGetMock }))

const FIELD_ID = 'field-context-1'
const schemaVersion = 'open_agronomy_agent.field_event_sync.v1'

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response
}

function testStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() { return values.size },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  }
}

function recordFile(payload: unknown, name = 'field-records.json'): File {
  const content = JSON.stringify(payload)
  const file = new File([content], name, { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => content })
  return file
}

function validEnvelope() {
  return {
    schema_version: schemaVersion,
    source_device_id: 'browser-test',
    base_head_sha256: null,
    events: [{ id: 'event-1', field_context_id: FIELD_ID }],
  }
}

function openPanel() {
  fireEvent.click(screen.getByText('Move field records between devices'))
}

describe('FieldSyncPanel', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: testStorage(),
    })
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:field-records'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('exports only non-empty field records with a descriptive device label', async () => {
    apiGetMock.mockResolvedValue({
      schema_version: schemaVersion,
      field_context_id: FIELD_ID,
      base_head_sha256: null,
      head_sha256: 'a'.repeat(64),
      event_count: 1,
      events: [{ id: 'event-1', field_context_id: FIELD_ID }],
    })
    const onImported = vi.fn()
    render(<FieldSyncPanel fieldContextId={FIELD_ID} onImported={onImported} />)
    openPanel()

    fireEvent.click(screen.getByRole('button', { name: 'Export records' }))

    expect(await screen.findByText('1 records exported. Keep the file private.')).toBeInTheDocument()
    expect(apiGetMock).toHaveBeenCalledWith(`/api/demo/fields/${FIELD_ID}/events/sync`)
    expect(URL.createObjectURL).toHaveBeenCalledOnce()
    expect(onImported).not.toHaveBeenCalled()
  })

  it('imports a verified fast-forward and refreshes the field timeline', async () => {
    const fetchMock = vi.fn(async () => response({
      status: 'imported',
      imported_event_count: 1,
      chain: { valid: true, head_sha256: 'b'.repeat(64) },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const onImported = vi.fn()
    render(<FieldSyncPanel fieldContextId={FIELD_ID} onImported={onImported} />)
    openPanel()

    fireEvent.change(screen.getByLabelText('Import records'), {
      target: { files: [recordFile(validEnvelope())] },
    })

    expect(await screen.findByText('1 records imported with a valid chain.')).toBeInTheDocument()
    expect(onImported).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/demo/fields/${FIELD_ID}/events/sync`,
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('preserves both branches and explains a divergent-head conflict', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({
      detail: {
        code: 'divergent_head',
        message: 'local and incoming field histories have diverged',
        local_head_sha256: 'a'.repeat(64),
        requested_base_head_sha256: 'b'.repeat(64),
        resolution: 'Export and preserve both branches.',
      },
    }, 409)))
    const onImported = vi.fn()
    render(<FieldSyncPanel fieldContextId={FIELD_ID} onImported={onImported} />)
    openPanel()

    fireEvent.change(screen.getByLabelText('Import records'), {
      target: { files: [recordFile(validEnvelope())] },
    })

    expect(await screen.findByText('Branch conflict. No records were changed.')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Keep both files. Nothing was overwritten.')
    expect(screen.getByRole('alert')).toHaveTextContent('Export and preserve both branches.')
    expect(onImported).not.toHaveBeenCalled()
  })

  it('rejects malformed and cross-field files before contacting the server', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<FieldSyncPanel fieldContextId={FIELD_ID} onImported={vi.fn()} />)
    openPanel()
    const input = screen.getByLabelText('Import records')

    fireEvent.change(input, {
      target: { files: [recordFile({ schema_version: schemaVersion, events: [] })] },
    })
    expect(await screen.findByText(/not a non-empty Open Agronomy field-record file/i)).toBeInTheDocument()

    fireEvent.change(input, {
      target: {
        files: [recordFile({
          ...validEnvelope(),
          events: [{ id: 'event-1', field_context_id: 'different-field' }],
        })],
      },
    })
    expect(await screen.findByText(/branch belongs to a different field/i)).toBeInTheDocument()
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled())
  })
})
