import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FarmRecords from './FarmRecords'
import { recordLabel, type SavedRecord } from './RecordDetails'
import type { FarmField } from './farmTypes'

vi.mock('./FieldSyncPanel', () => ({ FieldSyncPanel: () => null }))
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })
const response = (value: unknown) => ({ ok: true, json: async () => value })
const empty = { events: [], total: 0, next_offset: null }
const record: SavedRecord = { id: 'sample', field_context_id: 'west', field_name: 'West', event_type: 'sample', occurred_at: '2026-01-12T12:00:00Z', recorded_at: '2026-01-12T12:00:00Z', provenance: { sampling_time_status: 'unknown' }, season_binding: 'explicit', payload: { summary: 'A: nitrate_n 12 mg/kg', measurement: { metric: 'nitrate_n', value: 12, unit: 'mg/kg', sample_id: 'A', method: 'Lab method', spatial_scope: 'composite', sample_depth: { top: 0, bottom: 15, unit: 'cm' } } } }

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
      if (init?.method === 'POST') writes.push({ url: String(input), body: JSON.parse(init.body) })
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

  it('formats machine-generated captions without rewriting grower prose or immutable records', () => {
    expect(recordLabel(record)).toBe('Nitrate nitrogen · sample A')
    const prose = { ...record, payload: { ...record.payload, summary: 'Check nitrate_n alongside the original report.' } }
    expect(recordLabel(prose)).toBe('Check nitrate_n alongside the original report.')
    expect(record.payload.summary).toBe('A: nitrate_n 12 mg/kg')
  })
})
