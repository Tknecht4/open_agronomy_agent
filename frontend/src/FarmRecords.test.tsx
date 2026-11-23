import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FarmRecords from './FarmRecords'
import RecordEntryDialog from './RecordEntryDialog'
import { RecordDetails, recordLabel, type SavedRecord } from './RecordDetails'
import type { FarmField } from './farmTypes'

vi.mock('./FieldSyncPanel', () => ({ FieldSyncPanel: () => null }))
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })
const originalId = '550e8400-e29b-41d4-a716-446655440000'
const savedId = '550e8400-e29b-41d4-a716-446655440001'
const response = (value: unknown) => ({ ok: true, json: async () => value })
const savedResponse = (body: { events: unknown[] }, field = 'west', status = 'saved', offset = 1) => response({ status, events: body.events.map((event, i) => ({ ...(event as object), id: `550e8400-e29b-41d4-a716-${String(446655440000 + offset + i)}`, field_context_id: field, occurred_at: '2026-11-18T12:00:00Z' })) })
const empty = { events: [], total: 0, next_offset: null }
const record: SavedRecord = { id: originalId, field_context_id: 'west', field_name: 'West', event_type: 'sample', occurred_at: '2026-01-12T12:00:00Z', recorded_at: '2026-01-12T12:00:00Z', provenance: { sampling_time_status: 'unknown' }, season_binding: 'explicit', payload: { summary: 'A: nitrate_n 12 mg/kg', measurement: { metric: 'nitrate_n', value: 12, unit: 'mg/kg', sample_id: 'A', method: 'Lab method', spatial_scope: 'composite', sample_depth: { top: 0, bottom: 15, unit: 'cm' } } } }

describe('record reading and intake', () => {
  it('filters the complete timeline and resets pagination when changing record type', async () => {
    const requests: string[] = []
    vi.stubGlobal('fetch', vi.fn(async input => {
      const url = String(input); requests.push(url)
      return response(url.includes('event_type=sample') ? { events: [record], total: 1, next_offset: null } : { events: [record], total: 201, next_offset: 100 })
    }))
    render(<FarmRecords fieldId="west" season={2026} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Next records' }))
    await waitFor(() => expect(requests.at(-1)).toContain('offset=100'))
    fireEvent.change(screen.getByRole('combobox', { name: 'Record type' }), { target: { value: 'sample' } })
    await waitFor(() => expect(requests.at(-1)).toBe('/api/records?season=2026&offset=0&field_id=west&event_type=sample'))
    expect(await screen.findByText('Nitrate nitrogen')).toBeVisible()
    expect(screen.getByText('Sample date unknown')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Next records' })).not.toBeInTheDocument()
  })

  it('adds a record from the main timeline to an explicitly selected field', async () => {
    const writes: Array<{ url: string; body: { events: Array<{ payload: { season: number; summary: string } }> } }> = []
    vi.stubGlobal('fetch', vi.fn(async (input, init) => {
      if (init?.method === 'POST') { const body = JSON.parse(init.body); writes.push({ url: String(input), body }); return savedResponse(body, 'east') }
      return response(empty)
    }))
    render(<FarmRecords fields={[{ id: 'west', name: 'West' }, { id: 'east', name: 'East' }] as FarmField[]} season={2026} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    fireEvent.change(screen.getByRole('combobox', { name: 'Field' }), { target: { value: 'east' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add record' })
    expect(within(dialog).getByText(/East · 2026/)).toBeVisible()
    fireEvent.change(within(dialog).getByLabelText('What did you observe or do?'), { target: { value: 'Synthetic scouting note' } })
    fireEvent.submit(within(dialog).getByRole('button', { name: 'Save record' }).closest('form')!)
    await screen.findByText('Record saved.')
    expect(writes).toHaveLength(1)
    expect(writes[0].url).toBe('/api/fields/east/records')
    expect(writes[0].body.events[0].payload).toMatchObject({ season: 2026, summary: 'Synthetic scouting note' })
  })

  it.each(['observation', 'sample', 'correction'] as const)('locks pending %s inputs and preserves the exact retry after a lost acknowledgement', async kind => {
    const writes: Array<{ operation_id: string; events: unknown[] }> = []
    let failFirst!: (error: Error) => void
    const pending = new Promise<never>((_resolve, reject) => { failFirst = reject })
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      if (init?.method === 'POST') {
        writes.push(JSON.parse(init.body))
        if (writes.length === 1) return pending
        return savedResponse(writes[0], 'west', 'already_saved')
      }
      return response(kind === 'correction' ? { events: [record], total: 1, next_offset: null } : empty)
    }))
    render(<FarmRecords fieldId="west" season={2026} />)
    fireEvent.click(await screen.findByRole('button', { name: kind === 'correction' ? 'Correct record' : 'Add record' }))
    const dialog = screen.getByRole('dialog', { name: kind === 'correction' ? 'Correct field record' : 'Add record' })
    if (kind === 'sample') {
      fireEvent.change(within(dialog).getByRole('combobox', { name: 'Record type' }), { target: { value: 'sample' } })
      fireEvent.change(within(dialog).getByLabelText('Measurement 1'), { target: { value: 'nitrate_n' } })
      for (const [label, value] of [['Sample ID', 'B'], ['Depth from', '0'], ['Depth to', '15'], ['Measurement 1 value', '8'], ['Measurement 1 unit', 'mg/kg'], ['Measurement 1 method', 'Lab method']]) {
        fireEvent.change(within(dialog).getByLabelText(label), { target: { value } })
      }
    }
    const summary = within(dialog).getByLabelText(kind === 'observation' ? 'What did you observe or do?' : 'Report note (optional)')
    fireEvent.change(summary, { target: { value: 'Captured synthetic record' } })
    fireEvent.submit(within(dialog).getByRole('button', { name: 'Save record' }).closest('form')!)
    await waitFor(() => expect(writes).toHaveLength(1))
    for (const control of dialog.querySelectorAll('input, textarea, select')) expect(control).toBeDisabled()
    for (const button of within(dialog).queryAllByRole('button', { name: /Add measurement|Remove measurement|Discard draft/ })) expect(button).toBeDisabled()
    expect(summary).toHaveValue('Captured synthetic record')
    await act(async () => { failFirst(new Error('Lost save acknowledgement')); await pending.catch(() => undefined) })
    expect(await screen.findByRole('alert')).toHaveTextContent('Lost save acknowledgement')
    expect(summary).toBeDisabled()
    expect(summary).toHaveValue('Captured synthetic record')
    fireEvent.submit(within(dialog).getByRole('button', { name: 'Retry saved request' }).closest('form')!)
    await screen.findByText('Record saved.')
    expect(writes).toHaveLength(2)
    expect(writes[1]).toEqual(writes[0])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it.each([false, true])('replays the captured request after reopening, preserving older-version edits (correction=%s)', async correction => {
    const writes: Array<{ operation_id: string; events: Array<Record<string, unknown>> }> = []
    const onClose = vi.fn(), onSaved = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      const body = JSON.parse(init!.body as string); writes.push(body)
      if (writes.length === 1) throw new Error('Lost acknowledgement')
      return savedResponse(body, 'west', 'already_saved', writes.length >= 3 ? 2 : 1)
    }))
    const props = { fieldId: 'west', season: 2026, initialRecord: correction ? record : undefined, onClose, onSaved }
    const first = render(<RecordEntryDialog {...props} />)
    const label = correction ? 'Report note (optional)' : 'What did you observe or do?'
    fireEvent.change(screen.getByLabelText(label), { target: { value: 'Original captured content' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Save record' }).closest('form')!)
    await screen.findByText('Lost acknowledgement')
    first.unmount()
    const oldKey = `open-agronomy.record-draft.west.2026${correction ? `.correction.${originalId}` : ''}`
    const legacy = JSON.parse(localStorage.getItem(oldKey)!); legacy.summary = 'Later edit from the earlier app'
    localStorage.setItem(oldKey, JSON.stringify(legacy))
    const reopened = render(<RecordEntryDialog {...props} />)
    expect(screen.getByLabelText(label)).toHaveValue(legacy.summary)
    expect(screen.getByLabelText(label)).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry saved request' }))
    await screen.findByText('The earlier save was confirmed. Your later edits are kept below for a new explicit save.')
    expect(writes).toHaveLength(2)
    expect(writes[1]).toEqual(writes[0])
    expect(onClose).not.toHaveBeenCalled()
    expect(onSaved).toHaveBeenCalledTimes(1)
    expect(screen.getByLabelText(label)).toBeEnabled()
    const newKey = correction ? `open-agronomy.record-draft.west.2026.correction.${savedId}` : oldKey
    const next = JSON.parse(localStorage.getItem(newKey)!)
    expect(next.summary).toBe(legacy.summary)
    expect(next.operation).not.toBe(legacy.operation)
    expect(next.signature).toBe('')
    if (correction) {
      expect(localStorage.getItem(oldKey)).toBeNull()
      expect(next.correction).toBe(savedId)
      reopened.unmount()
      render(<RecordEntryDialog {...props} initialRecord={{ ...record, id: savedId }} />)
      expect(screen.getByLabelText(label)).toHaveValue(legacy.summary)
    }
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(writes).toHaveLength(3)
    expect(writes[2].operation_id).not.toBe(writes[0].operation_id)
    expect(writes[2].events[0].payload).toMatchObject({ summary: legacy.summary })
    if (correction) expect(writes[2].events[0].corrects_event_id).toBe(savedId)
  })

  it('keeps a dated scouting offset and recovers an older captured request without a duplicate', async () => {
    const day = '2026-11-18T18:30'
    const occurredAt = new Date(day).toISOString()
    const writes: Array<{ operation_id: string; events: Array<{ provenance: Record<string, unknown> }> }> = []
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      const body = JSON.parse(init!.body as string)
      writes.push(body)
      if (writes.length === 1) throw new Error('Lost acknowledgement')
      return response({ status: 'already_saved', events: body.events.map((event: object) => ({ ...event, id: savedId, field_context_id: 'west', occurred_at: occurredAt })) })
    }))
    const props = { fieldId: 'west', season: 2026, onClose: vi.fn(), onSaved: vi.fn() }
    const first = render(<RecordEntryDialog {...props} />)
    fireEvent.change(screen.getByLabelText('Observed at (leave blank if unknown)'), { target: { value: day } })
    fireEvent.change(screen.getByLabelText('What did you observe or do?'), { target: { value: 'Scouted the entrance.' } })
    fireEvent.change(screen.getByLabelText('Where in the field? (optional)'), { target: { value: 'West gate' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
    await screen.findByText('Lost acknowledgement')
    expect(writes[0].events[0].provenance.observation_utc_offset_minutes).toBe(-new Date(day).getTimezoneOffset() || 0)
    first.unmount()

    const key = 'open-agronomy.record-draft.west.2026'
    const draft = JSON.parse(localStorage.getItem(key)!)
    const older = JSON.parse(draft.signature)
    delete older[0].provenance.observation_utc_offset_minutes
    localStorage.setItem(key, JSON.stringify({ ...draft, signature: JSON.stringify(older) }))

    render(<RecordEntryDialog {...props} />)
    fireEvent.click(screen.getByRole('button', { name: 'Retry saved request' }))
    await waitFor(() => expect(props.onClose).toHaveBeenCalledOnce())
    expect(writes).toHaveLength(2)
    expect(writes[1]).toEqual({ operation_id: writes[0].operation_id, events: older })
    expect(localStorage.getItem(key)).toBeNull()
  })

  it.each(['original', 'legacy', 'edited'] as const)('saves a correction with the %s observation time basis', async mode => {
    const instant = '2026-11-19T00:30:00.000Z'
    const viewerOffset = -new Date(instant).getTimezoneOffset() || 0
    const originalOffset = viewerOffset === -360 ? 60 : -360
    const edited = '2026-11-20T18:15'
    const writes: Array<{ events: Array<{ occurred_at: string; provenance: Record<string, unknown> }> }> = []
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      const body = JSON.parse(init!.body as string)
      writes.push(body)
      return response({ status: 'saved', events: body.events.map((event: object) => ({ ...event, id: savedId, field_context_id: 'west' })) })
    }))
    const initialRecord: SavedRecord = {
      ...record, event_type: 'observation', occurred_at: instant,
      provenance: { observation_time_status: 'user_supplied', ...(mode === 'legacy' ? {} : { observation_utc_offset_minutes: originalOffset }) },
      payload: { summary: 'Scouted the entrance.', scouting_location: 'West gate' },
    }
    const close = vi.fn()
    render(<RecordEntryDialog fieldId="west" season={2026} initialRecord={initialRecord} onSaved={vi.fn()} onClose={close} />)
    fireEvent.change(screen.getByLabelText('Where in the field? (optional)'), { target: { value: 'Near the west gate' } })
    if (mode === 'edited') fireEvent.change(screen.getByLabelText('Observed at (leave blank if unknown)'), { target: { value: edited } })
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
    await waitFor(() => expect(close).toHaveBeenCalledOnce())
    expect(writes).toHaveLength(1)
    const saved = writes[0].events[0]
    expect(saved.occurred_at).toBe(mode === 'edited' ? new Date(edited).toISOString() : instant)
    expect(saved.provenance.observation_utc_offset_minutes).toBe(mode === 'legacy' ? undefined : mode === 'original' ? originalOffset : (-new Date(edited).getTimezoneOffset() || 0))
  })

  it.each([false, true])('only unlocks a definite first validation rejection (previous uncertainty=%s)', async uncertain => {
    let calls = 0
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls += 1
      if (uncertain && calls === 1) throw new Error('Lost acknowledgement')
      return { ok: false, status: 422, text: async () => 'Invalid submitted record' }
    }))
    const props = { fieldId: 'west', season: 2026, onClose: vi.fn(), onSaved: vi.fn() }
    const first = render(<RecordEntryDialog {...props} />)
    fireEvent.change(screen.getByLabelText('What did you observe or do?'), { target: { value: 'Synthetic record' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
    if (uncertain) {
      await screen.findByText('Lost acknowledgement'); first.unmount()
      render(<RecordEntryDialog {...props} />)
      fireEvent.click(screen.getByRole('button', { name: 'Retry saved request' }))
    }
    await screen.findByText('422: Invalid submitted record')
    const input = screen.getByLabelText('What did you observe or do?')
    if (uncertain) {
      expect(input).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Discard draft' })).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Retry saved request' })).toBeEnabled()
    } else {
      expect(input).toBeEnabled()
      expect(screen.getByRole('button', { name: 'Save record' })).toBeEnabled()
    }
  })

  it.each(['missing status', 'wrong field', 'wrong payload', 'wrong correction', 'missing event', 'duplicate ids', 'invalid id', 'self correction'])('retains an uncertain request after an invalid acknowledgement: %s', async fault => {
    const close = vi.fn(), saved = vi.fn()
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      const body = JSON.parse(init!.body as string)
      const ack = await savedResponse(body).json() as { status?: string; events: Array<Record<string, unknown>> }
      if (fault === 'invalid id') ack.events[0].id = 'not-a-UUID'
      if (fault === 'self correction') ack.events[0].id = ack.events[0].corrects_event_id = originalId
      if (fault === 'missing status') delete ack.status
      if (fault === 'wrong field') ack.events[0].field_context_id = 'other'
      if (fault === 'wrong payload') ack.events[0].payload = { summary: 'Different' }
      if (fault === 'wrong correction') ack.events[0].corrects_event_id = 'other'
      if (fault === 'missing event') ack.events = []
      if (fault === 'duplicate ids') ack.events[1].id = ack.events[0].id
      return response(ack)
    }))
    render(<RecordEntryDialog fieldId="west" season={2026} onClose={close} onSaved={saved} />)
    if (fault === 'duplicate ids') {
      fireEvent.change(screen.getByLabelText('Record type'), { target: { value: 'sample' } })
      for (const [label, value] of [['Sample ID', 'B'], ['Depth from', '0'], ['Depth to', '15']]) fireEvent.change(screen.getByLabelText(label), { target: { value } })
      fireEvent.click(screen.getByRole('button', { name: 'Add measurement' }))
      for (const i of [1, 2]) for (const [label, value] of [[`Measurement ${i}`, 'nitrate_n'], [`Measurement ${i} value`, '8'], [`Measurement ${i} unit`, 'mg/kg'], [`Measurement ${i} method`, 'Lab']]) fireEvent.change(screen.getByLabelText(label), { target: { value } })
    } else fireEvent.change(screen.getByLabelText('What did you observe or do?'), { target: { value: 'Synthetic record' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
    await screen.findByText(/The save confirmation could not be verified/)
    expect(close).not.toHaveBeenCalled(); expect(saved).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Retry saved request' })).toBeEnabled()
    expect(JSON.parse(localStorage.getItem('open-agronomy.record-draft.west.2026')!).signature).not.toBe('')
  })

  it.each(['existing destination', 'quota failure', 'old version changes after copy'])('preserves both draft versions when correction migration is blocked by %s', async fault => {
    const writes: Array<{ events: unknown[] }> = []
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      const body = JSON.parse(init!.body as string); writes.push(body)
      if (writes.length === 1) throw new Error('Lost acknowledgement')
      return savedResponse(body, 'west', 'already_saved', writes.length >= 3 ? 2 : 1)
    }))
    const props = { fieldId: 'west', season: 2026, initialRecord: record, onClose: vi.fn(), onSaved: vi.fn() }
    const first = render(<RecordEntryDialog {...props} />)
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
    await screen.findByText('Lost acknowledgement'); first.unmount()
    const oldKey = `open-agronomy.record-draft.west.2026.correction.${originalId}`, destination = `open-agronomy.record-draft.west.2026.correction.${savedId}`
    const legacy = JSON.parse(localStorage.getItem(oldKey)!); legacy.summary = 'Later correction edit'
    const oldBytes = JSON.stringify(legacy); localStorage.setItem(oldKey, oldBytes)
    const otherBytes = JSON.stringify({ summary: 'Existing destination draft' })
    if (fault === 'existing destination') localStorage.setItem(destination, otherBytes)
    const setItem = Storage.prototype.setItem
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function(this: Storage, key, value) {
      if (fault === 'quota failure' && key === destination) throw new DOMException('Quota exceeded', 'QuotaExceededError')
      setItem.call(this, key, value)
      if (fault === 'old version changes after copy' && key === destination) setItem.call(this, oldKey, otherBytes)
    })
    try {
      render(<RecordEntryDialog {...props} />)
      fireEvent.click(screen.getByRole('button', { name: 'Retry saved request' }))
      await waitFor(() => expect(writes).toHaveLength(2))
      await screen.findByRole('alert')
      expect(localStorage.getItem(oldKey)).toBe(fault === 'old version changes after copy' ? otherBytes : oldBytes)
      if (fault === 'old version changes after copy') {
        expect(JSON.parse(localStorage.getItem(destination)!)).toMatchObject({ summary: legacy.summary, correction: savedId, signature: '' })
        expect(screen.getByRole('alert')).toHaveTextContent('Both stored versions have been kept')
      } else expect(localStorage.getItem(destination)).toBe(fault === 'existing destination' ? otherBytes : null)
      expect(screen.getByLabelText('Report note (optional)')).toHaveValue(legacy.summary)
      expect(screen.getByLabelText('Report note (optional)')).toBeDisabled()
      expect(props.onClose).not.toHaveBeenCalled()
      expect(props.onSaved).not.toHaveBeenCalled()
    } finally { spy.mockRestore() }
  })

  it('blocks dispatch when the exact request cannot be persisted', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    render(<RecordEntryDialog fieldId="west" season={2026} onClose={vi.fn()} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('What did you observe or do?'), { target: { value: 'Retained in this window' } })
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Quota exceeded', 'QuotaExceededError') })
    try {
      fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
      expect(await screen.findByRole('alert')).toHaveTextContent('Quota exceeded')
      expect(fetch).not.toHaveBeenCalled()
      expect(screen.getByLabelText('What did you observe or do?')).toHaveValue('Retained in this window')
      expect(screen.getByLabelText('What did you observe or do?')).toBeEnabled()
    } finally { spy.mockRestore() }
  })

  it.each(['{not JSON', JSON.stringify({ summary: 'Unsupported captured draft', signature: '[retained bytes]' })])('keeps an unreadable stored draft byte-for-byte without dispatch', async raw => {
    const key = 'open-agronomy.record-draft.west.2026'
    localStorage.setItem(key, raw)
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    const close = vi.fn()
    render(<RecordEntryDialog fieldId="west" season={2026} onClose={close} onSaved={vi.fn()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('The saved draft is unreadable')
    expect(screen.getByRole('button', { name: 'Recovery unavailable' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Discard draft' })).toBeDisabled()
    expect(screen.getByLabelText('What did you observe or do?')).toBeDisabled()
    expect(localStorage.getItem(key)).toBe(raw)
    fireEvent.click(screen.getByRole('button', { name: 'Close Add record' }))
    expect(close).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(key)).toBe(raw)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('does not clear or overwrite another stored version when a pending request succeeds', async () => {
    let resolve!: (value: unknown) => void
    const pending = new Promise(resolveReply => { resolve = resolveReply })
    let body!: { events: unknown[] }
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => { body = JSON.parse(init!.body as string); return pending }))
    const close = vi.fn()
    render(<RecordEntryDialog fieldId="west" season={2026} onClose={close} onSaved={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('What did you observe or do?'), { target: { value: 'First window' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
    const key = 'open-agronomy.record-draft.west.2026', other = JSON.stringify({ summary: 'Another window' })
    localStorage.setItem(key, other)
    await act(async () => { resolve(savedResponse(body)); await pending })
    expect(await screen.findByRole('alert')).toHaveTextContent('This draft changed in another window')
    expect(localStorage.getItem(key)).toBe(other)
    expect(close).not.toHaveBeenCalled()
  })

  it('resumes an uncertain correction from its superseded original after a full timeline reload', async () => {
    const writes: Array<{ operation_id: string; events: Array<Record<string, unknown>> }> = []
    let accepted: SavedRecord | null = null
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      if (init?.method === 'POST') {
        const body = JSON.parse(init.body); writes.push(body)
        if (!accepted) {
          accepted = { ...record, ...body.events[0], id: savedId, corrects_event_id: originalId }
          throw new Error('Correction committed but acknowledgement lost')
        }
        return response({ status: 'already_saved', events: [accepted] })
      }
      return response({ events: accepted ? [accepted, { ...record, corrected_by: savedId }] : [record], total: accepted ? 2 : 1, next_offset: null })
    }))
    const first = render(<FarmRecords fieldId="west" season={2026} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Correct record' }))
    fireEvent.change(screen.getByLabelText('Report note (optional)'), { target: { value: 'Corrected synthetic transcription' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save record' }))
    await screen.findByText('Correction committed but acknowledgement lost')
    first.unmount()
    render(<FarmRecords fieldId="west" season={2026} />)
    const resume = await screen.findByRole('button', { name: 'Resume record save' })
    expect(screen.getAllByRole('button', { name: 'Correct record' })).toHaveLength(1)
    fireEvent.click(resume)
    expect(screen.getByLabelText('Report note (optional)')).toHaveValue('Corrected synthetic transcription')
    expect(screen.getByLabelText('Report note (optional)')).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry saved request' }))
    await screen.findByText('Record saved.')
    expect(writes).toHaveLength(2)
    expect(writes[1]).toEqual(writes[0])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resume record save' })).not.toBeInTheDocument()
  })

  it('cannot turn a stale recovery affordance into a new correction of a superseded record', () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    render(<RecordEntryDialog fieldId="west" season={2026} initialRecord={{ ...record, corrected_by: savedId }} recoveryOnly onClose={vi.fn()} onSaved={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Recovery unavailable' })).toBeDisabled()
    expect(screen.getByLabelText('Report note (optional)')).toBeDisabled()
    expect(fetch).not.toHaveBeenCalled()
    expect(localStorage.getItem(`open-agronomy.record-draft.west.2026.correction.${originalId}`)).toBeNull()
  })

  it('keeps a failed load distinct from an empty season and supports retry', async () => {
    let fail = true
    vi.stubGlobal('fetch', vi.fn(async () => { if (fail) throw new Error('Connection lost'); return response(empty) }))
    render(<FarmRecords fieldId="west" season={2026} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Connection lost')
    expect(screen.queryByText('No records for 2026')).not.toBeInTheDocument()
    expect(screen.queryByText('Loading records…')).not.toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Retry loading records' }))
    expect(await screen.findByText('No records for 2026')).toBeVisible()
  })

  it('preserves a new-entry draft while opening and dismissing a correction', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ events: [record], total: 1, next_offset: null })))
    render(<FarmRecords fieldId="west" season={2026} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    fireEvent.change(screen.getByLabelText('What did you observe or do?'), { target: { value: 'Unfinished field note' } })
    fireEvent.click(screen.getByRole('button', { name: /^Close / }))
    fireEvent.click(await screen.findByRole('button', { name: 'Correct record' }))
    expect(screen.getByLabelText('Measurement 1')).toHaveValue('nitrate_n')
    fireEvent.click(screen.getByRole('button', { name: /^Close / }))
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    expect(screen.getByLabelText('What did you observe or do?')).toHaveValue('Unfinished field note')
    fireEvent.click(screen.getByRole('button', { name: 'Discard draft' }))
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    expect(screen.getByLabelText('What did you observe or do?')).toHaveValue('')
  })

  it('retains correction identity after discarding or saving a correction draft', async () => {
    const writes: Array<{ events: Array<{ event_type: string; corrects_event_id: string }> }> = []
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      if (init?.method === 'POST') { const body = JSON.parse(init.body); writes.push(body); return savedResponse(body) }
      return response({ events: [record], total: 1, next_offset: null })
    }))
    render(<FarmRecords fieldId="west" season={2026} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Correct record' }))
    fireEvent.click(screen.getByRole('button', { name: 'Discard draft' }))
    fireEvent.click(screen.getByRole('button', { name: 'Correct record' }))
    expect(screen.getByRole('dialog', { name: 'Correct field record' })).toBeVisible()
    expect(screen.getByLabelText('Measurement 1')).toHaveValue('nitrate_n')
    fireEvent.submit(screen.getByRole('button', { name: 'Save record' }).closest('form')!)
    await screen.findByText('Record saved.')
    expect(writes[0].events[0]).toMatchObject({ event_type: 'correction', corrects_event_id: record.id })
    fireEvent.click(screen.getByRole('button', { name: 'Correct record' }))
    expect(screen.getByRole('dialog', { name: 'Correct field record' })).toBeVisible()
    expect(screen.getByLabelText('Measurement 1')).toHaveValue('nitrate_n')
  })

  it('accepts custom soil measurements alongside the named presets', async () => {
    const writes: Array<{ events: Array<{ payload: { measurement: { metric: string } } }> }> = []
    vi.stubGlobal('fetch', vi.fn(async (_input, init) => {
      if (init?.method === 'POST') { const body = JSON.parse(init.body); writes.push(body); return savedResponse(body) }
      return response(empty)
    }))
    render(<FarmRecords fieldId="west" season={2026} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add record' }))
    fireEvent.change(within(screen.getByRole('dialog', { name: 'Add record' })).getByLabelText('Record type'), { target: { value: 'sample' } })
    fireEvent.change(screen.getByLabelText('Measurement 1'), { target: { value: 'custom' } })
    fireEvent.change(screen.getByLabelText('Measurement 1 identifier'), { target: { value: 'zinc' } })
    for (const [label, value] of [['Sample ID', 'A'], ['Depth from', '0'], ['Depth to', '15'], ['Measurement 1 value', '2'], ['Measurement 1 unit', 'mg/kg'], ['Measurement 1 method', 'Lab method']]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    fireEvent.submit(screen.getByRole('button', { name: 'Save record' }).closest('form')!)
    await screen.findByText('Record saved.')
    expect(writes[0].events[0].payload.measurement.metric).toBe('zinc')
  })

  it.each([
    ['field_kit', 'Field kit'], ['lab_report', 'Lab report'],
    ['imported_lab_report', 'Imported lab report'], ['user_transcribed_lab_report', 'Transcribed from a lab report'],
    [undefined, 'Source not recorded'],
  ])('describes measurement source %s without inventing provenance', (source, label) => {
    const event = { ...record, payload: { ...record.payload, measurement: { ...(record.payload.measurement as object), source_quality: source } } }
    render(<RecordDetails event={event} season={2026} />)
    expect(screen.getByText(`${label}; values have not been independently verified.`)).toBeInTheDocument()
  })

  it('formats machine-generated captions without rewriting grower prose or immutable records', () => {
    expect(recordLabel(record)).toBe('Nitrate nitrogen · sample A')
    const prose = { ...record, payload: { ...record.payload, summary: 'Check nitrate_n alongside the original report.' } }
    expect(recordLabel(prose)).toBe('Check nitrate_n alongside the original report.')
    expect(record.payload.summary).toBe('A: nitrate_n 12 mg/kg')
  })
})
